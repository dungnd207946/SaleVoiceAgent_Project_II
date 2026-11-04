"""TurnRunner — entry per user turn. Single-agent, no handoff chain."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from noble_agent.agent.context_compaction import build_warm_messages
from noble_agent.agent.customer_bootstrap import bootstrap_customer_profile
from noble_agent.agent.prompts.builder import build_system_prompt, render_customer_block
from noble_agent.agent.runner import run_turn
from noble_agent.agent.suggestions import build_suggestions_prompt, parse_suggestions
from noble_agent.agent.summary.summarizer import summarize_and_persist
from noble_agent.agent.tools.dispatcher import ToolDispatcher
from noble_agent.config import primary_for, provider_model_map
from noble_agent.semcache.models import CacheEntry
from noble_agent.storage.models import ThreadMessage, ThreadSummary
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("noble_agent.orchestrator")

# Warm calls only need to trigger the provider's prefill (cache write); the
# generated output is discarded, so keep the token budget tiny.
_WARM_MAX_TOKENS = 16


async def _noop_token(_token: str) -> None:
    return None


def _build_project_index() -> None:
    """(Re)build the project-name resolution index from the warmed registry and
    install it for the find_project tool. Embedding channel is best-effort: it is
    left off here (lexical + phonetic cover the core); enable by passing an
    embed_fn once a shared embedder handle is available. Never raises."""
    from noble_agent.agent.tools import find_project
    from noble_agent.data import db_project_registry
    from noble_agent.data.project_matching.index import ProjectNameIndex

    try:
        rows = db_project_registry.registry_rows()
        find_project.set_index(ProjectNameIndex(rows), tenant=current_tenant())
    except Exception:  # noqa: BLE001 — resolution must never wedge the turn/boot
        logger.exception("failed to build project name index")


def _strip_tool_directives(history: list[ThreadMessage], start: int) -> None:
    """Gỡ khối chỉ đạo một-lượt (khoá ``instruction``, top-level + trong các
    list con) khỏi tool message của lượt vừa xong, TRƯỚC khi persist.

    Directive trong tool result (upsell pitch, "giới thiệu luôn"...) là mệnh
    lệnh cho ĐÚNG lượt hiện tại — model đã đọc nó từ messages sống. Giữ lại
    trong history là để chỉ đạo cũ sai ngữ cảnh lái các lượt sau + phình token.
    Dữ liệu thật (over_budget/price_delta_pct/highlights/count...) giữ nguyên;
    content không có gì để gỡ thì giữ nguyên byte (không re-dump vô cớ).
    Best-effort: không bao giờ được làm vỡ một lượt đã trả lời xong."""
    for msg in history[start:]:
        if msg.role != "tool" or not msg.content:
            continue
        try:
            data = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            continue  # kb_search trả chuỗi trần — không đụng
        if not isinstance(data, dict):
            continue
        changed = False
        for key in ("instruction", "upsell_instruction"):
            if data.pop(key, None) is not None:
                changed = True
        for v in data.values():
            if not isinstance(v, list):
                continue
            for item in v:
                if isinstance(item, dict) and item.pop("instruction", None) is not None:
                    changed = True
        if changed:
            msg.content = json.dumps(data, ensure_ascii=False)


class TurnCallbacks(Protocol):
    interrupt_check: Callable[[], bool] | None  # may be missing on some impls

    async def on_token(self, token: str) -> None: ...
    async def on_tool_start(self, name: str, args: dict) -> None: ...
    async def on_tool_done(self, name: str, result: str) -> None: ...
    async def on_agent_switch(self, *, from_: str, to: str, reason: str) -> None: ...
    async def on_done(self) -> None: ...


def _last_assistant_has_unresolved_tool_calls(history: list[ThreadMessage]) -> bool:
    """True if the most recent assistant(tool_calls=...) lacks all tool result siblings.

    Used to detect a partial mid-turn state — the LLM emitted tool_calls but the
    corresponding tool messages were not all appended before an exception aborted
    the turn. Persisting that shape causes the next provider call to 400.
    """
    if not history:
        return False
    # Walk back to the last assistant with tool_calls
    last_asst_idx: int | None = None
    for i in range(len(history) - 1, -1, -1):
        if history[i].role == "assistant" and history[i].tool_calls:
            last_asst_idx = i
            break
    if last_asst_idx is None:
        return False
    expected_ids = {tc.get("id") for tc in (history[last_asst_idx].tool_calls or []) if tc.get("id")}
    seen_ids = {m.tool_call_id for m in history[last_asst_idx + 1 :] if m.role == "tool" and m.tool_call_id}
    return not expected_ids.issubset(seen_ids)


def _last_exchange(history: list[ThreadMessage]) -> tuple[str, str]:
    """Return (last user_text, last non-empty assistant text after it).

    Walks back to the most recent ``role=="user"`` message, then scans forward
    from there for the LAST ``role=="assistant"`` message with non-empty content
    (tool messages and empty tool-call-only assistants are ignored). Returns
    ``("", "")`` when there is no user message or no assistant text follows it.
    """
    last_user_idx: int | None = None
    for i in range(len(history) - 1, -1, -1):
        if history[i].role == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        return "", ""
    user_text = history[last_user_idx].content or ""
    assistant_text = ""
    for m in history[last_user_idx + 1 :]:
        if m.role == "assistant" and m.content:
            assistant_text = m.content
    return user_text, assistant_text


class TurnRunner:
    def __init__(
        self,
        *,
        repo,
        agent_def,
        llm,
        rag,
        settings,
        transcript_writer=None,
        semcache=None,
        channel: str = "",
        version: int = 0,
    ):
        self._repo = repo
        self._agent = agent_def
        self._llm = llm
        self._rag = rag
        self._settings = settings
        self._transcript = transcript_writer
        self._semcache = semcache
        # Runners are cached per (tenant, version, channel), so these are constant
        # for every turn this runner serves — they stamp `source` / `running_version`
        # on the live `conversations` row. Empty/0 = direct construction (tests,
        # scripts) or legacy unversioned config → written as NULL.
        self._channel = channel
        self._version = version
        # Routing: same per-provider model map for every path, but each
        # path can pin its own "primary" provider via NOBLE_*_MODEL. Computed
        # once at startup so per-turn code doesn't re-scan settings.
        self._model_map = provider_model_map(settings)
        self._agent_primary = primary_for(settings, settings.agent_model)
        self._summary_primary = primary_for(settings, settings.summary_model)
        self._suggestions_primary = primary_for(settings, settings.suggestions_model)
        # Strong refs to fire-and-forget summary tasks. asyncio only keeps
        # weakrefs in its task registry, so without this set CPython may GC the
        # task before it finishes — silently dropping summaries under load.
        self._bg_tasks: set[asyncio.Task] = set()
        # Per-sid background cache-warm task. Cancelled at the start of the next
        # turn on that sid so a warm still in flight doesn't contend with the
        # live answer for LLM bandwidth (same rationale as semcache refresh).
        self._warm_tasks: dict[str, asyncio.Task] = {}

    async def handle_turn(self, sid: str, user_text: str, callbacks: TurnCallbacks) -> None:
        from noble_agent.billing import context as billing_ctx

        billing_on = bool(self._settings.billing_metering_enabled)
        meter = billing_ctx.get_session_meter(sid, self._channel or "chat") if billing_on else None
        meter_token = billing_ctx.set_meter(meter)

        # Cancel any in-flight semcache refresh from the previous turn first —
        # predictor / ghost runs share LLM bandwidth with the live answer, and
        # whatever they would produce is now stale.
        if self._semcache is not None:
            try:
                await self._semcache.cancel_refresh(sid)
            except Exception:
                logger.exception("orchestrator: semcache.cancel_refresh failed")

        # Cancel a still-running cache-warm from the previous turn — it shares
        # LLM bandwidth with the live answer we're about to produce.
        warm = self._warm_tasks.pop(sid, None)
        if warm is not None and not warm.done():
            warm.cancel()

        # `on_done` is fired in a `finally` so any failure (LLM provider death,
        # tool crash, save_all I/O error, transcript writer error) does not
        # leave the transport waiting forever for the terminal event.
        # `CancelledError` still propagates so voice barge-in semantics
        # (cancel the agent task) are preserved.
        done_fired = False

        async def _fire_done_once() -> None:
            nonlocal done_fired
            if done_fired:
                return
            done_fired = True
            try:
                await callbacks.on_done()
            except Exception:
                logger.exception("orchestrator: callbacks.on_done() raised")

        try:
            meta, customer, state = await self._repo.load(sid)

            # One-time customer-profile bootstrap. On the first turn of a session,
            # look the caller up by phone (Postgres contacts + latest appointment)
            # and FREEZE the rendered profile block for the whole call. Later turns
            # reuse the frozen block — update_customer still mutates `customer`
            # (for summary/booking/persist) but never changes the displayed block.
            # Refresh the DB project registry (find_project's name index +
            # send_media's code→name lookup) at the start of a new call so
            # ma_du_an changes land without a restart. TTL-debounced (never
            # raises).
            #
            # Own flag, NOT `_profile_loaded`: the roster has nothing to do with the
            # caller's identity, it only shared that block. `facade.set_customer_fields`
            # sets `_profile_loaded` when a session seeds identity up-front, and the
            # gateway does that for EVERY connection (`chat_proxy.first_messages`) — so
            # sharing the flag skipped the index build and `find_project` answered
            # "Danh mục dự án chưa sẵn sàng" for every gateway/app session.
            #
            # The flag lives in Redis (per SESSION) but the index lives in RAM (per
            # PROCESS): after a restart, a resumed session carries the flag while the
            # new process has no index → rebuild whenever THIS process lacks one for
            # the tenant (2026-08-25). The flag still bounds the cost to once per
            # session on the steady-state path.
            from noble_agent.agent.tools import find_project

            if not state.scratchpad.get("_roster_loaded") or find_project.get_index() is None:
                from noble_agent.data import db_project_registry

                await db_project_registry.warm_if_stale(self._settings.project_registry_refresh_sec)
                _build_project_index()
                state.scratchpad["_roster_loaded"] = True

            # Vocab giá trị cột cho analyze_projects — TTL-debounced, never raises,
            # chỉ khi tenant offer tool. Cùng nhịp warm với roster ngay trên.
            if "analyze_projects" in self._agent.tool_names:
                from noble_agent.agent.tools import analytics_vocab

                await analytics_vocab.warm_if_stale(self._settings.analyze_vocab_ttl_sec)

            if not state.scratchpad.get("_profile_loaded"):
                await bootstrap_customer_profile(customer)
                state.scratchpad["customer_block"] = render_customer_block(self._agent, customer)

                # Short-term memory: prepend snapshot + prior-call context into
                # the frozen customer_block. Always on when a phone is present;
                # short_term_block waits (bounded) for any in-flight snapshot
                # merge, then returns "" on any error.
                if customer.phone:
                    from noble_agent.agent.memory import short_term_block

                    mem_block = await short_term_block(self._settings, phone=customer.phone, session_id=sid)
                    if mem_block:
                        state.scratchpad["customer_block"] += "\n\n" + mem_block

                state.scratchpad["_profile_loaded"] = True

            history_anchor = len(state.history)
            state.history.append(ThreadMessage(role="user", content=user_text))

            cache_hit = await self._try_cache_hit(sid, user_text)
            replayed = False

            if cache_hit is not None:
                try:
                    await self._replay_cache_hit(
                        cache_entry=cache_hit,
                        customer=customer,
                        state=state,
                        callbacks=callbacks,
                    )
                    replayed = True
                except Exception:
                    logger.exception("orchestrator: cache replay failed — falling back to live run")
                    # Roll history back to anchor + re-append user message to undo
                    # any partial chain the replay may have appended.
                    del state.history[history_anchor:]
                    state.history.append(ThreadMessage(role="user", content=user_text))
                    replayed = False

            if not replayed:
                await self._run_live(
                    sid=sid,
                    user_text=user_text,
                    customer=customer,
                    state=state,
                    callbacks=callbacks,
                    history_anchor=history_anchor,
                )

            meta.last_active = datetime.now(UTC)

            # Directive một-lượt (`instruction`) trong tool result đã xong nhiệm
            # vụ — gỡ TRƯỚC save_all (và trước warm-cache, vốn replay request kế
            # tiếp dựng từ state đã persist) để lượt sau không bị chỉ đạo cũ sai
            # ngữ cảnh, đỡ token, và prefix cache ổn định từ đây. Dữ liệu
            # (over_budget/price_delta_pct/highlights...) giữ nguyên.
            _strip_tool_directives(state.history, history_anchor)

            # Compute the per-message transcript delta BEFORE save_all so the
            # persisted-count cursor (kept in scratchpad) is saved with the turn
            # and the next turn only inserts genuinely new messages. History
            # only grows on the success path (invariant), so the cursor is a
            # monotonic index into state.history.
            prev = int(state.scratchpad.get("_persisted_msg_count", 0))
            new_msgs = list(state.history[prev:])
            state.scratchpad["_persisted_msg_count"] = len(state.history)

            saved = False
            try:
                await self._repo.save_all(sid, meta, customer, state)
                saved = True
            except Exception:
                logger.exception("orchestrator: save_all failed")

            # Fire-and-forget per-message transcript insert (conversation_messages).
            # Never awaited on the response path — off the streaming critical path.
            # Gate on `saved`: the persisted-count cursor is bumped in-memory
            # above but only lands in Redis when save_all succeeds. If save_all
            # failed, the bumped cursor is lost, so the next turn would reload the
            # OLD cursor and recompute the same delta — inserting now would then
            # rewrite those rows. Only insert when the cursor actually persisted.
            if saved:
                from noble_agent.storage import pg_data_plane
                from noble_agent.storage.persist import fire_and_forget

                # Realtime flat call record (tenant_data.conversations): upsert a
                # PARTIAL row every turn so the conversation is visible while it is
                # happening. Voice used to look realtime only because a call ends on
                # its own; a chat tab stays open, so its row appeared only when the
                # WS closed (= page refresh). summary/ended_at stay NULL here — the
                # call-end write fills them through record_conversation's COALESCE
                # merge, and re-upserting each turn picks up phone/name/project as
                # the agent collects them.
                fire_and_forget(
                    pg_data_plane.seed_conversation(
                        sid,
                        phone=customer.phone or None,
                        customer_name=customer.full_name or customer.name or None,
                        project=customer.project_interest or None,
                        source=self._channel or None,
                        started_at=meta.started_at,
                        running_version=self._version or None,
                    )
                )

                if new_msgs:
                    # PG realtime per-message transcript (tenant_data.conversation_messages).
                    # seq is the message's absolute index in state.history (base =
                    # pre-turn cursor), so a retry rewrites the same rows.
                    fire_and_forget(pg_data_plane.persist_turn_messages(sid, base_seq=prev, messages=new_msgs))

                # Billing: rút meter và ghi lô — fire-and-forget, đúng khuôn
                # persist_turn_messages ở trên. Đặt SAU save_all vì lô mang
                # seq riêng của nó; ghi trước khi lượt chốt sẽ đóng seq cho một
                # lượt có thể còn hỏng.
                if meter is not None:
                    from noble_agent.billing import sink as billing_sink

                    # PHẢI chụp turn_idx ĐỒNG BỘ rồi truyền tường minh xuống
                    # flush. `add_llm` đóng dấu lúc append (trong lượt, = N) còn
                    # dòng audio đóng dấu trong `drain()`; mà `fire_and_forget`
                    # chỉ LÊN LỊCH coroutine (`loop.create_task`), nên dòng
                    # `meter.turn_idx += 1` bên dưới chạy TRƯỚC khi `drain()`
                    # thực sự chạy. Chỉ đảo thứ tự hai dòng là KHÔNG đủ — đó là
                    # một cuộc đua, và bản trước đã sập đúng kiểu này: cùng một
                    # lô ra `llm turn=0` và `stt turn=1`.
                    turn_stamp = meter.turn_idx
                    fire_and_forget(billing_sink.flush(meter, turn_idx=turn_stamp))
                    meter.turn_idx += 1

            # Count *user-turns* (one role=user message + its assistant/tool
            # responses = 1 conversational turn). `covers_turns` is still a
            # message-index boundary in history; we only count user messages
            # past it to decide whether the threshold is crossed.
            covered_idx = state.summary.covers_turns if state.summary else 0
            pending_user_turns = sum(1 for m in state.history[covered_idx:] if m.role == "user")
            if pending_user_turns > self._settings.summary_threshold_K:
                # Snapshot now: these reflect end-of-turn state (already saved to
                # repo above), which is exactly what the next turn loads. Copying
                # protects the warm from concurrent mutation by the next turn.
                task = asyncio.create_task(
                    self._run_summary_then_warm(
                        sid=sid,
                        history=list(state.history),
                        prior_summary=state.summary,
                        customer=customer.model_copy(deep=True),
                        customer_block=state.scratchpad.get("customer_block"),
                    )
                )
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)

            if self._transcript is not None:
                try:
                    await self._transcript.write_session_async(session_id=sid, customer=customer, state=state)
                except Exception:
                    logger.exception("orchestrator: transcript writer failed")

            await _fire_done_once()

            # Schedule the next cache build AFTER the user-facing turn is done so
            # predictor + ghost runs see the just-finalized history (including the
            # assistant's response). Cancelled at the start of the next user turn.
            if self._semcache is not None:
                try:
                    self._semcache.schedule_refresh(
                        sid=sid,
                        last_user_text=user_text,
                        customer=customer,
                        state=state,
                    )
                except Exception:
                    logger.exception("orchestrator: semcache.schedule_refresh failed")
        except asyncio.CancelledError:
            # Voice barge-in path: cooperate with cancellation by re-raising,
            # but still flush the done event so transport state machines don't
            # wedge waiting for it.
            await _fire_done_once()
            raise
        except Exception:
            logger.exception("orchestrator: handle_turn raised — emitting done to unblock transport")
            await _fire_done_once()
            raise
        finally:
            # Last-resort guard: even on BaseException that bypassed the
            # except blocks above (e.g. SystemExit), make sure `on_done` ran.
            if not done_fired:
                try:
                    await callbacks.on_done()
                except Exception:
                    logger.exception("orchestrator: final on_done() raised")
            billing_ctx.reset_meter(meter_token)

    async def suggest_followups(self, sid: str) -> list[dict]:
        """Generate follow-up quick-reply chips for the last exchange (chat).

        Read-only side call fired AFTER the turn has persisted and its ``done``
        event was sent, so it never touches turn-loop state or invariants. A
        never-raise boundary: any failure (disabled, no exchange, LLM error,
        parse error) yields ``[]`` and is swallowed.
        """
        if not self._settings.suggestions_enabled:
            return []
        try:
            _meta, customer, state = await self._repo.load(sid)
            user_text, assistant_text = _last_exchange(state.history)
            if not user_text or not assistant_text:
                return []
            prompt = build_suggestions_prompt(user_text, assistant_text, customer, agent_name=self._settings.agent_name)
            raw = await self._llm.simple_completion(
                prompt,
                model=self._model_map,
                primary=self._suggestions_primary,
                max_tokens=200,
                temperature=0.4,
                purpose="suggestions",
            )
            return parse_suggestions(raw, max_n=3)
        except Exception as exc:
            logger.warning("suggest_followups failed: %s", exc)
            return []

    async def _run_live(
        self,
        *,
        sid: str,
        user_text: str,
        customer,
        state,
        callbacks: TurnCallbacks,
        history_anchor: int,
    ) -> None:
        dispatcher = ToolDispatcher(
            state=state,
            customer=customer,
            rag=self._rag,
            callbacks=callbacks,
            session_id=sid,
            tenant=current_tenant(),
            handoff_department=self._agent.handoff_department,
        )
        interrupt_check = getattr(callbacks, "interrupt_check", None)

        try:
            await run_turn(
                agent=self._agent,
                state=state,
                customer=customer,
                llm=self._llm,
                dispatcher=dispatcher,
                callbacks=callbacks,
                interrupt_check=interrupt_check,
                model=self._model_map,
                primary=self._agent_primary,
                force_tool_first_round=self._settings.llm_force_tool_first_round,
            )
        except BaseException:
            # Preserve invariant: every assistant(tool_calls) must be followed
            # by its matching tool messages. If run_turn raised mid-tool-loop,
            # roll history back to the pre-turn anchor so the next turn loads
            # a consistent prompt.
            if _last_assistant_has_unresolved_tool_calls(state.history):
                logger.warning(
                    "orchestrator: run_turn raised mid-tool-loop; truncating history to anchor=%d",
                    history_anchor,
                )
                del state.history[history_anchor:]
            raise

    # ── async summary + prompt-cache warm ────────────────────────────────

    async def _run_summary_then_warm(
        self,
        *,
        sid: str,
        history: list[ThreadMessage],
        prior_summary: ThreadSummary | None,
        customer,
        customer_block: str | None = None,
    ) -> None:
        """Summarize (always runs to completion), then schedule a cache warm.

        The summary runs inline here so it can never be cancelled by the next
        turn (only the warm is cancellable). If a new summary was produced and
        warming is enabled, spawn a separate warm task keyed by sid.
        """
        new_summary = await summarize_and_persist(
            sid=sid,
            history=history,
            prior_summary=prior_summary,
            llm=self._llm,
            repo=self._repo,
            model=self._model_map,
            primary=self._summary_primary,
            keep_tail=self._settings.summary_keep_tail,
        )
        if new_summary is None or not self._settings.summary_warm_cache:
            return
        self._schedule_warm(
            sid=sid, history=history, new_summary=new_summary, customer=customer, customer_block=customer_block
        )

    def _schedule_warm(
        self,
        *,
        sid: str,
        history: list[ThreadMessage],
        new_summary: ThreadSummary,
        customer,
        customer_block: str | None = None,
    ) -> None:
        prior = self._warm_tasks.get(sid)
        if prior is not None and not prior.done():
            prior.cancel()
        task = asyncio.create_task(
            self._warm(
                sid=sid, history=history, new_summary=new_summary, customer=customer, customer_block=customer_block
            )
        )
        self._warm_tasks[sid] = task
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _warm(
        self,
        *,
        sid: str,
        history: list[ThreadMessage],
        new_summary: ThreadSummary,
        customer,
        customer_block: str | None = None,
    ) -> None:
        """Replay the next turn's exact request as a throwaway call so the
        provider's prompt cache is warm. Provider-agnostic: same
        ``stream_completion`` path, model map, primary, and tools as the live
        turn, so each provider's own caching applies to the identical prefix.
        Best-effort — never touches state/history/repo, never streams to the
        caller, never dispatches tools.
        """
        try:
            system = build_system_prompt(self._agent, customer, new_summary, customer_block=customer_block)
            messages: list[dict] = [{"role": "system", "content": system}]
            # Cùng compaction với lượt live kế tiếp (cửa sổ verbatim trượt 1) — lệch là
            # prefix cache warm vô nghĩa.
            messages.extend(build_warm_messages(history, start=new_summary.covers_turns))
            from noble_agent.agent.tools import analytics_vocab

            # Warm phải khớp đúng request live turn sẽ gửi (kể cả vocab đã inject),
            # không thì prefix cache lệch — cache warm vô nghĩa.
            await self._llm.stream_completion(
                messages=messages,
                tools=analytics_vocab.inject(self._agent.tool_schemas),
                model=self._model_map,
                temperature=self._agent.temperature,
                max_tokens=_WARM_MAX_TOKENS,
                on_token=_noop_token,
                primary=self._agent_primary,
                purpose="warm_cache",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("orchestrator: cache warm failed (sid=%s)", sid)

    # ── semcache helpers ─────────────────────────────────────────────────

    async def _try_cache_hit(self, sid: str, user_text: str) -> CacheEntry | None:
        if self._semcache is None:
            return None
        try:
            hit = await self._semcache.try_hit(sid, user_text)
        except Exception:
            logger.exception("orchestrator: semcache.try_hit failed")
            return None
        if hit is None:
            return None
        # Partial-mode replay needs to dispatch trailing write tools live and
        # resume the LLM loop — non-trivial in single-agent unified. Defer for
        # now: only honor full-mode entries, fall through to live run on partial.
        if hit.entry.mode != "full":
            logger.info(
                "semcache: skipping partial-mode entry (sim=%.3f) — live run instead",
                hit.similarity,
            )
            return None
        return hit.entry

    async def _replay_cache_hit(
        self,
        *,
        cache_entry: CacheEntry,
        customer,
        state,
        callbacks: TurnCallbacks,
    ) -> None:
        # Apply customer diffs from the sandbox run (e.g. project_interest set
        # by noble_search) BEFORE surfacing the cached assistant content, so
        # the next turn's prompt reflects the same state the sandbox saw.
        for field, value in (cache_entry.customer_diff or {}).items():
            try:
                setattr(customer, field, value)
            except (AttributeError, ValueError):
                logger.warning("semcache: bad customer_diff field %r", field)

        for msg in cache_entry.chain:
            state.history.append(msg)
            if msg.role == "assistant":
                if msg.content:
                    await callbacks.on_token(msg.content)
                for tc in msg.tool_calls or []:
                    name = tc.get("function", {}).get("name", "")
                    try:
                        args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    await callbacks.on_tool_start(name, args)
            elif msg.role == "tool":
                await callbacks.on_tool_done(msg.name or "", msg.content or "")
