"""StateRepo — 3-key Redis session state for the unified single agent.

Keys per session:
  - session:{sid}:meta      — Meta JSON
  - session:{sid}:customer  — Customer JSON
  - session:{sid}:state     — State JSON (history + summary + scratchpad)

`update_summary` is a narrow read-modify-write on the state key only, so the
background summary task doesn't clobber concurrent history writes from the
live turn. Uses WATCH for optimistic concurrency.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import ValidationError as _ValidationError

from noble_agent.storage.models import (
    Customer,
    Meta,
    State,
    ThreadSummary,
)

logger = logging.getLogger("noble_agent.repo")

try:
    from redis.exceptions import WatchError as _WatchError
except Exception:  # pragma: no cover — redis pkg always installed in this project
    _WatchError = None  # type: ignore[assignment]


class StateRepo:
    def __init__(self, *, redis_client, ttl_seconds: int = 86400):
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _keys(self, sid: str) -> tuple[str, str, str]:
        return (
            f"session:{sid}:meta",
            f"session:{sid}:customer",
            f"session:{sid}:state",
        )

    async def load(self, sid: str) -> tuple[Meta, Customer, State]:
        """Load 3-key state. On schema mismatch (legacy/corrupt blob), fall back
        to defaults and log loudly — never crash the turn.

        The unified state schema is incompatible with legacy/refactor (spec
        §9.5). A bad blob means the session was started on the wrong path or
        manually edited; the safe behavior is to start fresh rather than wedge
        every subsequent turn until TTL.
        """
        k_meta, k_cust, k_state = self._keys(sid)
        meta_raw, cust_raw, state_raw = await self._redis.mget(k_meta, k_cust, k_state)

        now = datetime.now(UTC)
        if meta_raw is None:
            meta = Meta(session_id=sid, started_at=now, last_active=now)
        else:
            try:
                meta = Meta.model_validate_json(_to_str(meta_raw))
            except _ValidationError as exc:
                logger.warning("repo.load: meta schema mismatch for sid=%s — resetting (%s)", sid, exc)
                meta = Meta(session_id=sid, started_at=now, last_active=now)

        if cust_raw is None:
            customer = Customer()
        else:
            try:
                customer = Customer.model_validate_json(_to_str(cust_raw))
            except _ValidationError as exc:
                logger.warning("repo.load: customer schema mismatch for sid=%s — resetting (%s)", sid, exc)
                customer = Customer()

        if state_raw is None:
            state = State()
        else:
            try:
                state = State.model_validate_json(_to_str(state_raw))
            except _ValidationError as exc:
                logger.warning("repo.load: state schema mismatch for sid=%s — resetting (%s)", sid, exc)
                state = State()

        return meta, customer, state

    async def save_all(self, sid: str, meta: Meta, customer: Customer, state: State) -> None:
        k_meta, k_cust, k_state = self._keys(sid)
        pipe = self._redis.pipeline()
        pipe.set(k_meta, meta.model_dump_json(), ex=self._ttl)
        pipe.set(k_cust, customer.model_dump_json(), ex=self._ttl)
        pipe.set(k_state, state.model_dump_json(), ex=self._ttl)
        await pipe.execute()

    async def update_summary(self, sid: str, summary: ThreadSummary) -> None:
        """WATCH-based atomic summary update on the state key only.

        No-op if the state key does not exist (session never had a turn).
        Retries once on WATCH conflict; if it still conflicts, the summary is
        dropped — the next overflow check will retry.
        """
        _, _, k_state = self._keys(sid)
        for attempt in range(2):
            async with self._redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(k_state)
                    raw = await pipe.get(k_state)
                    if raw is None:
                        await pipe.unwatch()
                        return
                    state = State.model_validate_json(_to_str(raw))
                    state.summary = summary
                    pipe.multi()
                    pipe.set(k_state, state.model_dump_json(), ex=self._ttl)
                    await pipe.execute()
                    return
                except _ValidationError as exc:
                    # Schema mismatch — the state key holds a payload we can't
                    # parse (older schema, manual edit, byte corruption).
                    # Retrying won't help; surface loudly so it gets attention
                    # instead of silently burning LLM cost on each overflow.
                    logger.error(
                        "repo.update_summary: state schema mismatch for sid=%s — %s",
                        sid,
                        exc,
                    )
                    return
                except Exception as exc:
                    if attempt == 0 and _is_watch_error(exc):
                        logger.info("repo.update_summary: retry on watch conflict")
                        continue
                    logger.warning("repo.update_summary failed: %s", exc)
                    return


def _to_str(raw) -> str:
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


def _is_watch_error(exc: Exception) -> bool:
    if _WatchError is not None and isinstance(exc, _WatchError):
        return True
    # Defensive: some test doubles raise a class named WatchError without
    # importing from redis.exceptions. Keep the name-based fallback so retries
    # still kick in there.
    return exc.__class__.__name__ == "WatchError"
