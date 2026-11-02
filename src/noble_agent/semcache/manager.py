"""High-level orchestration for the semantic response cache (unified).

Same algorithm as ``noble_agent_refactor.semcache.manager``:

1. ``try_hit`` — encode live user text, cosine-match against cached predicted
   queries, return the best entry above threshold (or ``None``).
2. ``schedule_refresh`` — fire-and-forget background task that predicts N next
   queries, runs them in parallel sandboxes, stores the resulting bundle.
3. ``cancel_refresh`` — abort any in-flight refresh at the start of every
   new user turn so predictor/ghost runs never compete with the live answer
   for LLM bandwidth.
4. ``invalidate`` — wipe the cache (used at session reset).

Replay of a cache hit is intentionally NOT done here — the orchestrator owns
the live history/customer/state and is the only place that can safely apply
``CacheEntry.customer_diff`` and re-invoke the runner for partial hits.

Diffs vs refactor:
- No ``registry`` — unified has one ``AgentDef`` passed in directly.
- ``state.history`` (flat) instead of ``state.threads[active_agent]``.
- ``state.summary`` (single) instead of ``state.summaries[active_agent]``.
- No briefings (unified has no handoff).
- No ``base_agent`` field on entries (only one agent).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from noble_agent.agent.base import AgentDef
from noble_agent.config import UnifiedSettings, primary_for, provider_model_map
from noble_agent.semcache import embedder, store
from noble_agent.semcache.models import CacheBundle, CacheEntry
from noble_agent.semcache.predictor import predict_next_queries
from noble_agent.semcache.sandbox import run_sandbox_turn
from noble_agent.storage.models import Customer, State, ThreadMessage

logger = logging.getLogger("noble_agent.semcache.manager")


@dataclass
class CacheHit:
    entry: CacheEntry
    similarity: float


class SemCacheManager:
    def __init__(
        self,
        *,
        redis,
        agent_def: AgentDef,
        llm,
        rag,
        settings: UnifiedSettings,
    ):
        self._redis = redis
        self._agent = agent_def
        self._llm = llm
        self._rag = rag
        self._settings = settings
        # Routing — same per-provider model map as everywhere else, with
        # NOBLE_SEMCACHE_MODEL pinning the primary provider for the
        # predictor + sandbox path. Computed once.
        self._model_map = provider_model_map(settings)
        self._semcache_primary = primary_for(settings, settings.semcache_model)
        # In-flight refresh task per session. A new turn cancels the previous
        # task before any live LLM work starts so predictor/ghost runs never
        # compete with the real answer for LLM bandwidth.
        self._inflight: dict[str, asyncio.Task] = {}

    @property
    def enabled(self) -> bool:
        return self._settings.semcache_enabled

    # ── lookup ───────────────────────────────────────────────────────────
    async def try_hit(self, sid: str, user_text: str) -> CacheHit | None:
        if not self.enabled:
            return None
        bundle = await store.load_bundle(self._redis, sid)
        if bundle is None or not bundle.entries:
            return None
        try:
            q_vec = await embedder.encode(
                user_text,
                model_name=self._settings.semcache_embed_model,
                is_query=True,
            )
        except Exception:
            logger.exception("semcache: encode query failed")
            return None

        threshold = self._settings.semcache_threshold
        best: tuple[float, CacheEntry] | None = None
        for entry in bundle.entries:
            sim = embedder.cosine(q_vec, entry.embedding)
            if sim >= threshold and (best is None or sim > best[0]):
                best = (sim, entry)

        if best is None:
            return None
        sim, entry = best
        logger.info(
            "semcache: HIT sid=%s sim=%.3f mode=%s predicted=%r user=%r",
            sid,
            sim,
            entry.mode,
            entry.query,
            user_text,
        )
        return CacheHit(entry=entry, similarity=sim)

    # ── refresh (fire-and-forget) ────────────────────────────────────────
    def schedule_refresh(
        self,
        *,
        sid: str,
        last_user_text: str,
        customer: Customer,
        state: State,
    ) -> None:
        """Spawn the background prediction + ghost-run task. Returns immediately."""
        if not self.enabled:
            return
        old = self._inflight.get(sid)
        if old is not None and not old.done():
            old.cancel()

        # Snapshots so the live turn can mutate state without affecting us.
        customer_snapshot = customer.model_copy(deep=True)
        state_snapshot = state.model_copy(deep=True)
        task = asyncio.create_task(
            self._refresh(
                sid=sid,
                last_user_text=last_user_text,
                customer=customer_snapshot,
                state=state_snapshot,
            )
        )
        self._inflight[sid] = task

        def _cleanup(t: asyncio.Task) -> None:
            # Only clear the slot if it still points at this task — a faster
            # follow-up schedule_refresh may have replaced it already.
            if self._inflight.get(sid) is t:
                self._inflight.pop(sid, None)

        task.add_done_callback(_cleanup)

    async def cancel_refresh(self, sid: str) -> None:
        """Abort any in-flight refresh for ``sid`` and await its termination."""
        if not self.enabled:
            return
        task = self._inflight.get(sid)
        if task is None or task.done():
            return
        logger.info("semcache: cancelling in-flight refresh for sid=%s", sid)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("semcache: cancelled refresh raised unexpectedly")

    async def _refresh(
        self,
        *,
        sid: str,
        last_user_text: str,
        customer: Customer,
        state: State,
    ) -> None:
        try:
            await self._refresh_inner(
                sid=sid,
                last_user_text=last_user_text,
                customer=customer,
                state=state,
            )
        except asyncio.CancelledError:
            logger.info("semcache: refresh cancelled mid-flight for sid=%s", sid)
            raise

    async def _refresh_inner(
        self,
        *,
        sid: str,
        last_user_text: str,
        customer: Customer,
        state: State,
    ) -> None:
        history = list(state.history)
        prior_summary = state.summary

        n = self._settings.semcache_num_predictions
        try:
            predicted = await predict_next_queries(
                llm=self._llm,
                model=self._model_map,
                primary=self._semcache_primary,
                history=history,
                customer=customer,
                last_user_text=last_user_text,
                n=n,
                lookback=self._settings.semcache_history_lookback,
                temperature=self._settings.semcache_predictor_temperature,
            )
        except Exception:
            logger.exception("semcache: predictor failed for sid=%s", sid)
            return

        if not predicted:
            logger.info("semcache: no predictions for sid=%s", sid)
            return

        logger.info("semcache: predicted %d queries for sid=%s: %r", len(predicted), sid, predicted)

        async def _one(q: str):
            return q, await run_sandbox_turn(
                agent=self._agent,
                base_history=history,
                customer=customer,
                state=state,
                prior_summary=prior_summary,
                llm=self._llm,
                rag=self._rag,
                sid=sid,
                predicted_query=q,
                model=self._model_map,
                primary=self._semcache_primary,
            )

        results = await asyncio.gather(*(_one(q) for q in predicted), return_exceptions=True)

        good: list[tuple[str, str, list[ThreadMessage], dict]] = []
        for r in results:
            if isinstance(r, BaseException):
                logger.warning("semcache: sandbox run raised: %r", r)
                continue
            q, (mode, chain, diff) = r
            if mode is None or not chain:
                continue
            good.append((q, mode, chain, diff))

        if not good:
            logger.info("semcache: no usable ghost runs for sid=%s", sid)
            return

        try:
            embeddings = await embedder.encode_batch(
                [q for q, _, _, _ in good],
                model_name=self._settings.semcache_embed_model,
                is_query=False,
            )
        except Exception:
            logger.exception("semcache: encode_batch failed")
            return

        entries = [
            CacheEntry(
                query=q,
                embedding=embeddings[i],
                mode=mode,
                chain=chain,
                customer_diff=diff,
            )
            for i, (q, mode, chain, diff) in enumerate(good)
        ]
        bundle = CacheBundle(
            entries=entries,
            created_at=datetime.now(UTC),
            base_history_len=len(history),
        )
        await store.save_bundle(self._redis, sid, bundle, ttl_seconds=self._settings.session_ttl_seconds)
        logger.info(
            "semcache: saved %d entries for sid=%s (modes=%s)",
            len(entries),
            sid,
            [e.mode for e in entries],
        )

    # ── invalidate ───────────────────────────────────────────────────────
    async def invalidate(self, sid: str) -> None:
        if not self.enabled:
            return
        await store.delete_bundle(self._redis, sid)
