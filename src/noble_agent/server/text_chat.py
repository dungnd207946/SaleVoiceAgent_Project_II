"""Text-chat session handler.

Drives the SAME agent brain as the voice pipeline — StreamingLLM.stream_response
(prompt mode, tools, RAG, agent-switching) — but over a plain text WebSocket
instead of STT/TTS. Used by the /chat tester UI (static/chat.html).

stream_response invokes its callbacks SYNCHRONOUSLY from inside the async turn,
so callbacks enqueue events onto an asyncio.Queue that a concurrent drain task
sends over the WebSocket. This preserves emission order and keeps callbacks
non-blocking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger("server")

# Async sink that delivers one JSON-serialisable event to the client.
Send = Callable[[dict], Awaitable[None]]

_DONE = object()  # sentinel: stop the drain task


def is_chat_path(raw_path: str) -> bool:
    """True when a WebSocket/HTTP path belongs to the text-chat feature."""
    return urlparse(raw_path or "/").path.startswith("/chat")


async def _create_llm(session_id: str):
    """Construct the LLM-driving object for one /chat session.

    Uses the unified NobleAgent facade — same brain as voice, but the "chat"
    persona channel (persona/chat/ skeleton).
    """
    from noble_agent.agent.facade import NobleAgent

    return await NobleAgent.create(session_id, channel="chat")


async def run_text_turn(
    llm: Any,
    send: Send,
    text: str,
    *,
    tts: bool = False,
    send_bytes: Callable[[bytes], Awaitable[None]] | None = None,
    tts_backend: Any = None,
) -> None:
    """Run one user turn through the LLM, emitting ordered events via `send`.

    Emits: user_text, then interleaved token/tool_start/tool_done/agent_switch
    in occurrence order, then `done` (or `error` + `done` on failure).

    When `tts` is set and a `tts_backend` + `send_bytes` are supplied, the
    agent's reply is synthesised *concurrently with generation*: tokens feed a
    SentenceBuffer, and each completed sentence is synthesised + streamed to the
    client as raw PCM16 binary frames (bracketed by `tts_begin`/`tts_end` JSON)
    while the LLM keeps generating later sentences — same normalize + backend +
    sentence-streaming as the voice pipeline, so audio starts ~1 sentence in
    rather than after the whole reply.
    """
    if not text or not text.strip():
        return

    turn_id = uuid4().hex[:8]
    await send({"type": "user_text", "text": text})

    queue: asyncio.Queue = asyncio.Queue()

    # TTS sentence pipeline (only when enabled): LLM tokens → SentenceBuffer →
    # tts_q → background worker synthesises each sentence in order.
    tts_on = tts and tts_backend is not None and send_bytes is not None
    tts_q: asyncio.Queue | None = asyncio.Queue() if tts_on else None
    sbuf = None
    if tts_on:
        from noble_agent.voice.sentence_buffer import SentenceBuffer

        sbuf = SentenceBuffer()
    tts_started_at: float | None = None
    tts_bytes = 0

    turn_start = time.perf_counter()
    first_token_at: float | None = None
    segment_first_token_at: float | None = None
    token_count = 0

    def on_token(tok: str) -> None:
        nonlocal first_token_at, segment_first_token_at, token_count
        now = time.perf_counter()
        if segment_first_token_at is None:
            segment_first_token_at = now
            if first_token_at is None:
                first_token_at = now
            queue.put_nowait({"type": "metrics", "stage": "first_token", "ttft_ms": int((now - turn_start) * 1000)})
        token_count += 1
        queue.put_nowait({"type": "token", "text": tok})
        if sbuf is not None and tts_q is not None:
            for chunk in sbuf.add(tok):
                tts_q.put_nowait(chunk.text)

    def on_tool_start(name: str, args: dict) -> None:
        nonlocal segment_first_token_at
        segment_first_token_at = None
        queue.put_nowait({"type": "tool_start", "tool": name, "args": args})

    def on_tool_done(name: str, result: str) -> None:
        queue.put_nowait({"type": "tool_done", "tool": name, "result": result})

    def on_agent_switch() -> None:
        queue.put_nowait({"type": "agent_switch", "agent": getattr(llm, "_current_agent", "")})

    async def drain() -> None:
        while True:
            ev = await queue.get()
            if ev is _DONE:
                return
            await send(ev)

    async def tts_worker() -> None:
        """Synthesise queued sentences in order, streaming PCM as it arrives."""
        nonlocal tts_started_at, tts_bytes
        from noble_agent.config import settings as _settings
        from noble_agent.voice.tts._normalize import normalize_for_voice

        while True:
            sentence = await tts_q.get()
            if sentence is _DONE:
                return
            sentence = (sentence or "").strip()
            if not sentence:
                continue
            try:
                if tts_started_at is None:
                    tts_started_at = time.perf_counter()
                    await send({"type": "tts_begin", "turn_id": turn_id, "sample_rate": _settings.tts_sample_rate})
                async for pcm in tts_backend.stream(normalize_for_voice(sentence)):
                    if pcm:
                        tts_bytes += len(pcm)
                        await send_bytes(pcm)
            except Exception as exc:  # best-effort; keep draining so the turn completes
                logger.error("[CHAT] TTS error: %s", exc, exc_info=True)

    from noble_agent.config import get_settings

    drain_task = asyncio.ensure_future(drain())
    tts_task = asyncio.ensure_future(tts_worker()) if tts_on else None
    try:
        await llm.stream_response(
            text,
            on_token,
            on_tool_start,
            on_tool_done,
            lambda: False,  # interrupt_check — no barge-in in text mode
            on_agent_switch,
            show_thinking=get_settings().llm_show_thinking,
        )
    except Exception as exc:  # surface to the trace, never crash the socket
        logger.error("[CHAT] turn error: %s", exc, exc_info=True)
        queue.put_nowait({"type": "error", "message": str(exc)})
    finally:
        # Flush the trailing partial sentence to TTS before closing the queue.
        if sbuf is not None and tts_q is not None:
            tail = sbuf.flush()
            if tail and tail.text.strip():
                tts_q.put_nowait(tail.text)

        turn_end = time.perf_counter()
        ttft_ms = int((first_token_at - turn_start) * 1000) if first_token_at else None
        gen_ms = int((turn_end - first_token_at) * 1000) if first_token_at else 0
        tps = (
            round(token_count / (turn_end - first_token_at), 1) if first_token_at and turn_end > first_token_at else 0.0
        )
        queue.put_nowait(_DONE)
        await drain_task
        await send(
            {
                "type": "done",
                "turn_id": turn_id,
                "ttft_ms": ttft_ms,
                "tokens": token_count,
                "gen_ms": gen_ms,
                "tokens_per_sec": tps,
                "total_ms": int((turn_end - turn_start) * 1000),
            }
        )

        # Follow-up suggestion chips — generated by a small async LLM call OFF
        # the critical path (the answer + `done` are already delivered). Emitted
        # only when non-empty, via fire-and-forget so it never blocks the WS read
        # loop or the next turn.
        if get_settings().suggestions_enabled:
            from noble_agent.storage.persist import fire_and_forget

            async def _emit_suggestions() -> None:
                items = await llm.suggest_followups(llm.session_id)
                if items:
                    await send({"type": "suggestions", "items": items})

            fire_and_forget(_emit_suggestions())

        # Let queued sentences finish synthesising, then close out the audio.
        if tts_task is not None and tts_q is not None:
            tts_q.put_nowait(_DONE)
            await tts_task
            if tts_started_at is not None:
                await send(
                    {
                        "type": "tts_end",
                        "turn_id": turn_id,
                        "bytes": tts_bytes,
                        "tts_ms": int((time.perf_counter() - tts_started_at) * 1000),
                    }
                )


async def handle_text_session(ws: Any, session_id: str, *, tenant_id: str | None = None) -> None:
    """Lifecycle of one /chat WebSocket connection.

    Creates a StreamingLLM (honours settings.noble_prompt_mode, loads history,
    wires RAG — identical to voice) and loops over inbound JSON messages:
      {"type": "user_text", "text": ...} -> run a turn
      {"type": "reset"}                  -> reset conversation
    """
    from noble_agent.tenant.current import set_current_tenant

    if tenant_id:
        set_current_tenant(tenant_id)

    import websockets

    async def send(ev: dict) -> None:
        await ws.send(json.dumps(ev, ensure_ascii=False))

    async def send_bytes(data: bytes) -> None:
        await ws.send(data)

    await send({"type": "session_id", "session_id": session_id})
    logger.info("[CHAT] session=%s connected", session_id)

    from noble_agent.server.admission import get_chat_admission

    admission = get_chat_admission()
    if not await admission.try_admit():
        import contextlib

        # Best-effort both notify + close: the client may have vanished between
        # connect and this cap check, so neither await may block the return.
        with contextlib.suppress(Exception):
            await send({"type": "error", "message": "Hệ thống đang quá tải, vui lòng thử lại."})
        with contextlib.suppress(Exception):
            await ws.close(code=4029, reason="chat_at_capacity")
        return
    try:
        # Lazily-built TTS backend (shared across turns). Uses the SAME factory +
        # fallback chain as the voice pipeline, so /chat hears the production voice.
        tts_backend: Any = None
        tts_failed = False

        async def _get_tts() -> Any:
            nonlocal tts_backend, tts_failed
            if tts_backend is None and not tts_failed:
                try:
                    from noble_agent.voice.voice_agent import VoiceAgent

                    tts_backend = VoiceAgent._create_tts()
                    logger.info("[CHAT] session=%s TTS ready (%s)", session_id, type(tts_backend).__name__)
                except Exception as exc:
                    tts_failed = True
                    logger.error("[CHAT] TTS init failed: %s", exc, exc_info=True)
                    await send({"type": "error", "message": f"TTS không khả dụng: {exc}"})
            return tts_backend

        try:
            llm = await _create_llm(session_id)
            await llm.ensure_session_started()
            logger.info("[CHAT] session=%s LLM ready (type=%s)", session_id, type(llm).__name__)
        except Exception as exc:
            logger.error("[CHAT] session=%s LLM init failed: %s", session_id, exc, exc_info=True)
            try:
                await send({"type": "error", "message": f"LLM init failed: {exc}"})
            except Exception:
                pass
            return

        try:
            async for message in ws:
                if not isinstance(message, str):
                    continue
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                msg_type = data.get("type")
                if msg_type == "user_text":
                    want_tts = bool(data.get("tts"))
                    backend = await _get_tts() if want_tts else None
                    await run_text_turn(
                        llm,
                        send,
                        str(data.get("text", "")),
                        tts=want_tts and backend is not None,
                        send_bytes=send_bytes,
                        tts_backend=backend,
                    )
                elif msg_type == "reset":
                    await llm.reset()
                    await send({"type": "reset_ok"})
                elif msg_type == "set_customer":
                    # Seed caller identity from the tester UI. Maps the app's
                    # `identity` shape onto Customer fields EXACTLY like
                    # app_session.provision_session (gender M/F, email+birthday+
                    # noble_info folded into noble_info) so /chat testing mirrors the
                    # real NobleX-app provisioning path. Apply before the first turn
                    # so the frozen customer block picks it up.
                    from noble_agent.server.app_session import _compose_noble_info, _normalize_gender

                    identity = data.get("identity") or {}
                    fields: dict = {}
                    if identity.get("full_name"):
                        fields["full_name"] = identity["full_name"]
                        fields["name"] = identity["full_name"]
                    if identity.get("phone"):
                        fields["phone"] = identity["phone"]
                    gender = _normalize_gender(identity.get("gender"))
                    if gender:
                        fields["gender"] = gender
                    if isinstance(identity.get("is_noble_customer"), bool):
                        fields["is_noble_customer"] = identity["is_noble_customer"]
                    noble_info = _compose_noble_info(identity)
                    if noble_info:
                        fields["noble_info"] = noble_info
                    try:
                        applied = await llm.set_customer_fields(fields)
                        await send({"type": "customer_ok", "customer": applied})
                    except Exception as exc:
                        await send({"type": "error", "message": f"set_customer failed: {exc}"})
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosedError:
            pass
        except Exception as exc:
            logger.error("[CHAT] session error: %s", exc, exc_info=True)
        finally:
            if tts_backend is not None and hasattr(tts_backend, "aclose"):
                try:
                    await tts_backend.aclose()
                except Exception as exc:
                    logger.debug("[CHAT] TTS aclose error: %s", exc)
            await _persist_session_end(session_id, llm=locals().get("llm"))
            logger.info("[CHAT] session=%s closed", session_id)
    finally:
        await admission.release()


async def _persist_session_end(session_id: str, llm=None) -> None:
    """On /chat close, persist customer + call summary.

    Mirrors ``base_session.stop`` so text-chat has the same durable footprint as
    voice. History for the summary comes from the Redis state key (unified source).
    """
    from datetime import UTC, datetime

    from noble_agent.agent.summary import generator as summary_gen
    from noble_agent.storage import pg_data_plane, session_store

    try:
        customer = await session_store.load_customer(session_id)
        phone = customer.get("phone", "")
        if not phone:
            return
        try:
            await session_store.save_customer_persistent(phone, customer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CHAT] persist customer failed: %s", exc)

        # Billing: đường teardown không có ai set meter ContextVar (nó chỉ sống
        # trong handle_turn), nên nhãn `summary` lúc đóng phiên và nhãn `memory`
        # sẽ không bao giờ được ghi. `peek_` chứ không `get_`: không sinh meter
        # cho phiên chưa từng đo. Task fire-and-forget bên dưới thừa hưởng
        # context nhưng thường sống lâu hơn lần flush cuối — xem caveat contract
        # §2.2 (nhãn `memory`).
        from noble_agent.billing import context as billing_ctx

        with billing_ctx.use_meter(billing_ctx.peek_session_meter(session_id)):
            try:
                history = await session_store.load_history_from_state(session_id)
                # Generous overall backstop only — real bounding is per-provider inside
                # complete_once (request_timeout), so the full fallback chain (gemini →
                # openai → dashscope → anthropic) can actually run instead of being cut
                # off at a tight cap. generate_call_summary always returns a doc.
                summary_doc = await asyncio.wait_for(
                    summary_gen.generate_call_summary(session_id, customer, history, ended_at=datetime.now(UTC)),
                    timeout=40.0,
                )
                running_version = getattr(llm, "pinned_version", 0)
                await pg_data_plane.persist_conversation(
                    summary_doc,
                    phone=phone,
                    session_id=session_id,
                    running_version=running_version or None,
                    source="chat",
                )
            except TimeoutError:
                logger.warning("[CHAT][SUMMARY] summary exceeded backstop on close, skipping narrative")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CHAT][SUMMARY] save failed: %s", exc)

            # User snapshot memory: merge this chat into the caller's cumulative
            # snapshot (fire-and-forget, per-phone Redis lock, error-swallowing).
            try:
                from noble_agent.agent.memory import update_snapshot_after_call
                from noble_agent.config import get_settings
                from noble_agent.storage.persist import fire_and_forget

                fire_and_forget(
                    update_snapshot_after_call(
                        get_settings(),
                        phone=phone,
                        session_id=session_id,
                        history=history,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CHAT][MEMORY] snapshot scheduling failed: %s", exc)

    except Exception as exc:  # noqa: BLE001
        logger.warning("[CHAT] session-end persist pipeline failed: %s", exc)
    finally:
        # Chat không có dòng `call` — không có thời lượng cuộc gọi để tính.
        # In `finally` (not after the try/except) so the early `if not phone:
        # return` above still triggers this — a chat session with no phone
        # yet can still have accumulated LLM usage that must be flushed.
        try:
            from noble_agent.billing import context as billing_ctx
            from noble_agent.billing import sink as billing_sink

            meter = billing_ctx.pop_session_meter(session_id)
            if meter is not None:
                # final=True — xem chú thích ở BaseSession.stop.
                await billing_sink.flush(meter, final=True)
                billing_sink.forget_session(session_id)
        except Exception:  # noqa: BLE001
            logger.warning("billing: flush cuối phiên chat thất bại", exc_info=True)
