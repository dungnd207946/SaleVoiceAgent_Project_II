"""Transport-agnostic voice-agent pipeline.

`BaseSession` owns everything *except* the physical audio channel and the
signaling fabric: VAD framing, STT feed, `VoiceAgent` orchestration, audio
guards, interrupt state, idle/hold timers, metrics, and gender detection.

Transports inject:
- `audio_input` — async iterator of PCM16 (little-endian) bytes from the caller.
- `audio_output` — `AudioOutput` protocol impl (send / clear / queued_duration_s).
- `event_sink` — optional async callable receiving JSON dict events (e.g. UI
  notifications, agent_speaking/agent_done). Defaults to a no-op so the
  LiveKit transport can ignore this layer cleanly.

Concrete subclasses (`noble_agent.server.session.Session` for aiortc;
`noble_agent.transport.livekit.room_session.RoomSession` in Phase 3) build the
underlying objects and hand them to `start_pipeline()`.

**CONCERNS.md 7.1 (partial fix, plan Phase 2):** `_interrupt_t0` renamed to
`_interrupt_log_t0` with a docstring clarifying that it is a Python-side
logging stamp only — it does not represent the moment the caller stops
hearing audio. The real audio-stop moment is owned by the transport's
`AudioOutput.clear()` and will be metered in Phase 4.1 alongside
`VoiceAgent.pause_tts()`. Interrupt ordering is now:
cancel agent task → clear output queue → `vad.set_idle()`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC
from typing import Protocol

import numpy as np

from noble_agent.config import parse_probe_schedule, resolve_speaker_mode, settings
from noble_agent.metrics import MetricsCollector
from noble_agent.voice import addressee_gate
from noble_agent.voice.addressee_gate import EpisodeTracker, Verdict
from noble_agent.voice.audio_guard import (
    EchoCooldown,
    WhisperHallucinationFilter,
)
from noble_agent.voice.fallback import STT_FALLBACK_CHAIN, _start_first_available, resolve_order
from noble_agent.voice.speaker_tracker import SpeakerRegistry, SpeakerTracker
from noble_agent.voice.speaker_verifier import SpeakerEmbedder
from noble_agent.voice.stt_input_gate import SttInputGate
from noble_agent.voice.stt_reconnect import ReconnectingSTT
from noble_agent.voice.vad import SileroVAD, VADState
from noble_agent.voice.voice_agent import VoiceAgent

logger = logging.getLogger("server")

VAD_CHUNK_BYTES = int(settings.stt_sample_rate * settings.vad_chunk_ms / 1000) * 2

# Startup self-defense warnings in __init__ run once PER SESSION, not once per
# process — a long-lived agent handling many calls would otherwise repeat the
# same misconfiguration warning on every single call. Key-dedupe so each
# distinct warning logs exactly once per process (review round 1, MINOR-6).
_WARNED_ONCE: set[str] = set()


def _warn_once(key: str, msg: str, *args: object) -> None:
    if key in _WARNED_ONCE:
        return
    _WARNED_ONCE.add(key)
    logger.warning(msg, *args)


class AudioOutput(Protocol):
    """Transport-provided audio sink handed to `BaseSession.start_pipeline()`."""

    async def send(self, pcm16_bytes: bytes) -> None: ...

    def clear(self) -> None: ...

    @property
    def queued_duration_s(self) -> float: ...


EventSink = Callable[[dict], Awaitable[None]]


async def _noop_event_sink(_msg: dict) -> None:  # pragma: no cover - trivial
    return None


class BaseSession:
    """Shared pipeline state for any audio transport.

    Lifecycle:
        1. `__init__(session_id)`
        2. `await start()` — parallel init of VoiceAgent, STT, RAG, TTS warm-up, persistence.
        3. `await start_pipeline(audio_input, audio_output, event_sink=None)` —
           consume caller audio until stream ends or `stop()` is called.
        4. `await stop()` — transport-independent teardown.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.vad = SileroVAD()
        self.stt = None
        self.metrics = MetricsCollector()

        from noble_agent.billing import context as _billing_ctx

        # `settings` đã được import ở đầu module — không alias lại.
        self.billing = (
            _billing_ctx.get_session_meter(session_id, "voice") if settings.billing_metering_enabled else None
        )

        # Transport-bound — set by start_pipeline. Defaults let the agent
        # safely log-and-drop audio before a pipeline is attached.
        self._audio_output: AudioOutput | None = None
        self._event_sink: EventSink = _noop_event_sink

        self.agent = VoiceAgent(
            send_audio=self._send_agent_audio,
            send_json=self._send_event,
            session_id=session_id,
            metrics=self.metrics,
            usage_meter=self.billing,
        )

        # Pipeline state.
        # CONCERNS.md 7.6 (Phase 4.6): most mutable fields below are under a
        # *single-writer* assumption — the asyncio task that owns the pipeline
        # loop. One exception: `SpeakerTracker`'s chunk-labelling task (spawned
        # through `_spawn_bg`) lands in `_on_speaker_verdict`, a background
        # writer that calls `vad.set_speaking()` / `_handle_interrupt` /
        # `_begin_addressee_pause_from_floor`. This is safe because:
        # (a) the event loop is single-threaded — the tracker's own 1-inflight
        #     invariant is a synchronous check-and-set with no await in between;
        # (b) `_label_chunk`'s `finally` clears the inflight slot even on
        #     exception, so the tracker cannot wedge;
        # (c) the task is held in `_bg_tasks` (strong ref) so GC cannot collect
        #     it mid-flight.
        # All other fields remain pipeline-loop-only. If a future phase adds a
        # second parallel consumer, wrap the relevant fields with an
        # `asyncio.Lock` — NEVER `threading.Lock`.
        self._vad_buf = b""  # single-writer: pipeline loop
        self._agent_task: asyncio.Task | None = None  # single-writer: pipeline loop / _trigger_agent_for_text
        self._current_project: str = ""  # single-writer: pipeline loop
        self._session_start: float = time.monotonic()
        self._stt_audio_start: float = 0.0  # single-writer: pipeline loop
        # Lúc stream STT được mở (billing `stt.wall_ms` = thời gian stream mở,
        # contract §2.1 — con số Portal dùng khi hợp đồng STT tính theo thời gian
        # kết nối chứ không theo giây audio thật gửi). 0 = chưa mở/đã tính.
        self._stt_stream_open: float = 0.0
        # Python-side logging stamp for interrupt metric — NOT the audible-stop
        # time. See class docstring (CONCERNS.md 7.1).
        self._interrupt_log_t0: float = 0.0  # single-writer: _handle_interrupt
        self._gender_detection_attempts: int = 0  # single-writer: pipeline loop
        self._gender_detected: bool = False  # single-writer: _run_gender_detection (one at a time)

        # Audio guards (1, 2, 3). 4 (RepetitionDetector) lives inside VoiceAgent.
        self._echo_cooldown = EchoCooldown()
        self._halluc_filter = WhisperHallucinationFilter()
        self._input_gate = SttInputGate.from_settings(settings)
        self._speaker_mode = resolve_speaker_mode()
        if self._speaker_mode == "off" and settings.speaker_verification_enabled:
            logger.warning("SPEAKER_VERIFICATION_ENABLED is deprecated — use SPEAKER_MODE=single.")
        # Parallel SPV engine (spec 2026-09-03) — SpeakerRegistry giữ N danh
        # tính sống trọn phiên (single: tối đa 1, multi: spv_max_identities);
        # không còn reset per-turn, con trỏ asker do drop rule trong `_on_final`
        # quản lý (set/keep/drop_asker), giống nhau cho cả single và multi.
        self._speaker_tracker: SpeakerTracker | None = None
        self._speaker_registry: SpeakerRegistry | None = None
        self._mismatch_streak = 0  # single-writer: _on_final (van thoát §4.3)
        if self._speaker_mode in ("single", "multi"):
            marks, thresholds = parse_probe_schedule(
                settings.spv_probe_marks_sec, settings.spv_probe_bonus, settings.speaker_match_threshold
            )
            single = self._speaker_mode == "single"
            self._speaker_registry = SpeakerRegistry(
                match_threshold=settings.speaker_match_threshold,
                adapt_margin=settings.spv_adapt_margin,
                # single: đúng MỘT danh tính cho cả phiên.
                max_identities=1 if single else settings.spv_max_identities,
                max_centroids=settings.spv_max_centroids,
                min_match_probe=settings.spv_min_match_probe,
                min_match_identify=settings.spv_min_match_identify,
            )
            self._speaker_tracker = SpeakerTracker(
                embed=self._spv_embed,
                registry=self._speaker_registry,
                sample_rate=settings.stt_sample_rate,
                probe_marks_sec=marks,
                probe_thresholds=thresholds,
                probe_tail_window_sec=settings.spv_probe_tail_window_sec,
                probe_tail_hop_sec=settings.spv_probe_tail_hop_sec,
                enroll_window_sec=settings.spv_enroll_window_sec,
                enroll_hop_sec=settings.spv_enroll_hop_sec,
                enroll_consensus_sim=settings.spv_enroll_consensus_sim,
                enroll_min_cluster=settings.spv_enroll_min_cluster,
                min_enroll_sec=settings.speaker_min_enroll_sec,
                utt_cap_sec=settings.spv_utt_cap_sec,
                single_identity=single,
                on_verdict=self._on_speaker_verdict,
                spawn_bg=self._spawn_bg,
            )
        # Strong-ref set for background asyncio tasks (prevents GC mid-flight).
        self._bg_tasks: set = set()

        # Addressee gate (chống nói leo) — spec 2026-08-12 (amendment đêm: verdict
        # giờ chờ STT final, KHÔNG còn classify trên partial). Episode đo
        # speech-ms khi có tiếng đè lên agent; đủ ngưỡng → soft-pause, giữ tới
        # khi final tới rồi classify đúng MỘT lần. `_addressee_deadline` là
        # background writer cùng kiểu `_on_speaker_verdict` (xem safety comment
        # phía trên).
        self._addr_gate_enabled = settings.addressee_gate_mode != "off"
        self._addr_tracker = EpisodeTracker(
            min_speech_ms=settings.addressee_min_speech_ms,
            chunk_ms=settings.vad_chunk_ms,
        )
        self._addr_episode_active = False
        self._addr_paused = False
        self._addr_episode_verdict: Verdict | None = None
        self._addr_deadline_handle: asyncio.TimerHandle | None = None
        # Bumped by _addr_reset_episode() — marks the episode this final's
        # inline classify was opened for as resolved (SIDE_TALK resume /
        # DIRECTED commit / new turn), so a verdict landing after the fact
        # discards itself instead of re-pausing.
        self._addr_episode_gen = 0
        self._last_user_text = ""
        # Session-local dialogue ring cho addressee LLM verdict context (2026-08-12
        # amendment): user text append khi final được chấp nhận (SAU gate — final
        # side-talk KHÔNG vào ring); agent text append lúc turn mới trigger, đọc
        # VoiceAgent.spoken_text_this_turn của turn TRƯỚC. Không sống qua reconnect.
        self._dialogue_ring: deque[tuple[str, str]] = deque(maxlen=6)

        # Startup self-defense (amendment 2026-08-12 đêm): ADDRESSEE_MAX_PAUSE_MS
        # must stay below the pacer's own _PAUSE_WATCHDOG_S (5s, voice_agent.py) —
        # otherwise the pacer self-resumes before this deadline ever fires,
        # silently defeating the fail-open commit path.
        if self._addr_gate_enabled and settings.addressee_max_pause_ms / 1000 >= 5.0:
            _warn_once(
                "addressee_max_pause_ms_watchdog",
                "addressee_max_pause_ms (%dms) >= pacer watchdog 5s — pacer will "
                "self-resume before the deadline; lower it.",
                settings.addressee_max_pause_ms,
            )

        # Startup self-defense (review 2026-08-12, multi-gate composition):
        # `_begin_addressee_pause_from_floor` skips re-running the EpisodeTracker
        # on the premise that the floor's asker-resolution (>= the probe schedule's
        # last mark, spv_probe_marks_sec) already proves more overlap-speech than
        # the gate's own soft-pause threshold (addressee_min_speech_ms). If a
        # misconfiguration inverts that, the shortcut soft-pauses on less evidence
        # than the gate would normally require.
        if (
            self._speaker_tracker is not None
            and self._addr_gate_enabled
            and marks[-1] * 1000 < settings.addressee_min_speech_ms
        ):
            _warn_once(
                "spv_probe_last_mark_vs_addressee_min_speech_ms",
                "mốc probe cuối (%.0fms) < addressee_min_speech_ms (%dms) — "
                "floor->gate soft-pause skips the EpisodeTracker on the assumption that "
                "probe resolution already proves enough overlap-speech; that premise is "
                "voided by this config.",
                marks[-1] * 1000,
                settings.addressee_min_speech_ms,
            )

        # Smart-turn hold — single-writer: pipeline loop + hold-timer callback
        # (same event loop, so they interleave rather than race).
        self._smart_turn = None
        self._audio_ring = bytearray()  # single-writer: pipeline loop
        self._pending_finals: list[str] = []  # single-writer: pipeline loop
        self._hold_timer: asyncio.TimerHandle | None = None

        # Idle state machine — single-writer: pipeline loop + idle-timer callback.
        self._idle_timer: asyncio.TimerHandle | None = None
        self._idle_state: int = 0
        self._stopping: bool = False

        if settings.smart_turn_enabled:
            from noble_agent.voice.turn_detection.smart_turn import get_detector

            self._smart_turn = get_detector()

    # ------------------------------------------------------------------
    # Shared agent/event plumbing (delegates to transport-provided sinks).
    # ------------------------------------------------------------------

    async def _send_agent_audio(self, pcm_bytes: bytes) -> None:
        """Callback handed to `VoiceAgent` — bookkeeps echo-guard then forwards."""
        self._echo_cooldown.on_tts_chunk(len(pcm_bytes))
        self.vad.playback_active = True  # audio really flowing → barge-in RMS floor live
        if self._audio_output is None:
            logger.warning(
                "send_agent_audio dropped %d bytes: no audio_output attached yet",
                len(pcm_bytes),
            )
            return
        await self._audio_output.send(pcm_bytes)

    async def _send_event(self, msg: dict) -> None:
        try:
            await self._event_sink(msg)
        except Exception:  # noqa: BLE001
            logger.exception("event_sink raised")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Parallel init of agent, STT, RAG, TTS warm-up, persistence."""

        async def _init_agent() -> None:
            await self.agent.start()

        async def _init_stt() -> None:
            # Init-time fallback: try the configured backend, then the rest of
            # STT_FALLBACK_CHAIN (sherpa→soniox). Non-chain backends (qwen3asr,
            # elevenlabs) yield a single-element order → behavior unchanged.
            # Builders lift the original if/elif branches verbatim (same
            # on_partial/on_final wiring, imports stay function-local). This
            # coroutine must never raise (it runs inside the start() gather).
            def _build_soniox():
                from noble_agent.voice.stt.soniox import SonioxSTT

                return SonioxSTT(on_partial=self._on_partial, on_final=self._on_final)

            def _build_qwen3asr():
                from noble_agent.voice.stt.qwen3asr import Qwen3ASRSTT

                return Qwen3ASRSTT(on_partial=self._on_partial, on_final=self._on_final)

            def _build_elevenlabs():
                from noble_agent.voice.stt.elevenlabs import ElevenLabsSTT

                return ElevenLabsSTT(on_partial=self._on_partial, on_final=self._on_final)

            def _build_sherpa():
                from noble_agent.voice.stt.sherpa import SherpaSTT

                return SherpaSTT(on_partial=self._on_partial, on_final=self._on_final)

            def _build_remote():
                from noble_agent.voice.stt.remote import RemoteSTT

                return RemoteSTT(on_partial=self._on_partial, on_final=self._on_final)

            # Track which backend actually came up so the success log can note
            # a fallback. Wrap each builder to stamp `chosen[0]` on construct;
            # `_start_first_available` returns the instance whose start() won,
            # which is the last builder it invoked.
            chosen: list[str] = [""]

            def _track(name: str, build):
                def _wrapped():
                    chosen[0] = name
                    return build()

                return _wrapped

            base_builders = {
                "soniox": _build_soniox,
                "qwen3asr": _build_qwen3asr,
                "elevenlabs": _build_elevenlabs,
                "sherpa": _build_sherpa,
                "remote": _build_remote,
            }
            builders = {name: _track(name, b) for name, b in base_builders.items()}
            order = resolve_order(settings.stt_backend, STT_FALLBACK_CHAIN)

            async def _on_exhausted() -> None:
                self.stt = None
                logger.error(
                    "STT chain exhausted (tried %s) — session continues without STT",
                    order,
                )
                await self._send_event(
                    {
                        "type": "error",
                        "message": f"STT chain failed to connect: tried {order}",
                    }
                )

            stt = await _start_first_available(order, builders, on_exhausted=_on_exhausted)
            if stt is not None:
                if chosen[0] != settings.stt_backend:
                    logger.warning("STT fell back to '%s' (primary '%s' unavailable)", chosen[0], settings.stt_backend)
                logger.info("STT started: %s", chosen[0])
                # Mid-call recovery: restart the SAME backend if its stream dies
                # (init-time fallback above never re-runs during a call).
                stt = ReconnectingSTT(stt)
                self._stt_stream_open = time.monotonic()
            self.stt = stt

        async def _init_tts_warmup() -> None:
            if settings.tts_backend == "elevenlabs" and hasattr(self.agent._tts, "warm_up"):
                await self.agent._tts.warm_up()

        async def _init_meta() -> None:
            from noble_agent.storage import session_store

            await session_store.upsert_meta(self.session_id)

        await asyncio.gather(
            _init_meta(),
            _init_agent(),
            _init_stt(),
            _init_tts_warmup(),
        )
        logger.info("Session started: id=%s (stt=%s)", self.session_id, settings.stt_backend)

    async def start_pipeline(
        self,
        audio_input: AsyncIterator[bytes],
        audio_output: AudioOutput,
        event_sink: EventSink | None = None,
    ) -> None:
        """Drive the pipeline from a caller-audio async iterator."""
        self._audio_output = audio_output
        if event_sink is not None:
            self._event_sink = event_sink
        try:
            async for frame in audio_input:
                if self._stopping:
                    break
                await self.process_audio_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("pipeline aborted")

    async def stop(self) -> None:
        """Transport-independent teardown. Subclasses super() first, then close transport."""
        self._stopping = True
        self._cancel_idle_timer()
        self._cancel_hold_timer()
        self._addr_reset_episode()
        self._pending_finals.clear()
        if self._audio_output is not None:
            try:
                self._audio_output.clear()
            except Exception:  # noqa: BLE001
                logger.exception("audio_output.clear() failed during stop")

        session_duration = time.monotonic() - self._session_start
        if self.stt:
            try:
                await self.stt.stop()
            except Exception:  # noqa: BLE001
                logger.exception("stt.stop() failed")

        # Billing: thời gian stream STT mở + số lần mở (contract §2.1). `audio_sec`
        # của stt cộng dồn trên đường nóng; hai số này chỉ biết được lúc đóng.
        # ReconnectingSTT restart cùng backend NGẦM bên dưới, nên một cuộc gọi có
        # reconnect vẫn tính đúng một lần mở (số vendor thu vẫn theo thời lượng).
        if self.billing is not None and self._stt_stream_open > 0:
            # purpose="stream": giá vốn CẢ PHIÊN (thời gian stream mở, số lần
            # mở), session-scoped — không được trộn vào (stt, conversation)
            # (giây khách nói, per-turn), nếu không sẽ ra dòng lai mang
            # turn_idx của một lượt nhưng wall_ms của cả cuộc gọi.
            self.billing.add_audio(
                "stt",
                purpose="stream",
                wall_ms=(time.monotonic() - self._stt_stream_open) * 1000.0,
                units=1,
            )
            self._stt_stream_open = 0.0

        # Part 2+3: persist customer profile by phone, then generate call
        # summary for cross-session memory. Only for LiveKit/browser paths
        # that have phone (SIP gateway with phone metadata, or manual inject).
        # Telephony path does the same from `TelephonySession._cleanup()`.
        from datetime import datetime

        try:
            from noble_agent.storage import session_store

            customer = await session_store.load_customer(self.session_id)
            phone = customer.get("phone", "")
            if phone:
                try:
                    await session_store.save_customer_persistent(phone, customer)
                except Exception as pers_exc:  # noqa: BLE001
                    logger.warning("persist customer failed: %s", pers_exc)

                # Billing: đường teardown KHÔNG có ai set meter ContextVar (nó
                # được set trong handle_turn và reset khi lượt xong), nên nhãn
                # `summary` cuối cuộc gọi và nhãn `memory` sẽ không bao giờ được
                # ghi. Gắn meter quanh cả hai để lời gọi có await được đếm; task
                # fire-and-forget bên dưới thừa hưởng context nhưng thường sống
                # lâu hơn lần flush cuối (xem caveat ở contract §2.2, nhãn
                # `memory`).
                from noble_agent.billing import context as _billing_ctx

                with _billing_ctx.use_meter(self.billing):
                    try:
                        from noble_agent.agent.summary.generator import generate_call_summary
                        from noble_agent.storage.pg_data_plane import persist_conversation

                        history = await session_store.load_history_from_state(self.session_id)
                        ended_at = datetime.now(UTC)
                        # Generous backstop only — per-provider bounding lives inside
                        # complete_once so the full fallback chain can run (see generator).
                        summary_doc = await asyncio.wait_for(
                            generate_call_summary(
                                self.session_id,
                                customer,
                                history,
                                ended_at=ended_at,
                            ),
                            timeout=40.0,
                        )
                        running_version = getattr(getattr(self.agent, "_llm", None), "pinned_version", 0)
                        await persist_conversation(
                            summary_doc,
                            phone=phone,
                            session_id=self.session_id,
                            running_version=running_version or None,
                            source="voice",
                        )
                    except TimeoutError:
                        logger.warning("[SUMMARY] summary exceeded backstop on stop, skipping narrative")
                    except Exception as sum_exc:  # noqa: BLE001
                        logger.warning("[SUMMARY] save failed: %s", sum_exc)

                    # User snapshot memory: merge this call into the caller's
                    # cumulative snapshot. Fire-and-forget so stop() stays fast; the
                    # helper holds a per-phone Redis lock so the next call from this
                    # phone waits for the merge, and swallows all errors.
                    try:
                        from noble_agent.agent.memory import update_snapshot_after_call
                        from noble_agent.config import get_settings
                        from noble_agent.storage.persist import fire_and_forget

                        fire_and_forget(
                            update_snapshot_after_call(
                                get_settings(),
                                phone=phone,
                                session_id=self.session_id,
                                history=history,
                            )
                        )
                    except Exception as mem_exc:  # noqa: BLE001
                        logger.warning("[MEMORY] snapshot scheduling failed: %s", mem_exc)

        except Exception as exc:  # noqa: BLE001
            logger.warning("customer persist/summary pipeline failed: %s", exc)

        if self.billing is not None:
            try:
                from noble_agent.billing import context as _billing_ctx
                from noble_agent.billing import sink as _billing_sink

                self.billing.add_audio("call", purpose="session", audio_sec=session_duration, units=1)
                # final=True: không còn lượt sau để thử lại → thất bại thì dump
                # payload ra log (spec §6) chứ không mất im lặng.
                await _billing_sink.flush(self.billing, final=True)
                _billing_ctx.pop_session_meter(self.session_id)
                _billing_sink.forget_session(self.session_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("billing: flush cuối phiên thất bại: %s", exc)

        logger.info("Session ended: id=%s (%.1fs)", self.session_id, session_duration)

    # ------------------------------------------------------------------
    # Pipeline core
    # ------------------------------------------------------------------

    async def process_audio_frame(self, data: bytes) -> None:
        """Feed one caller-audio frame through VAD + the STT input gate."""
        # VAD first: it drives BOTH interrupt detection and the vad-gate flag.
        self._vad_buf += data
        while len(self._vad_buf) >= VAD_CHUNK_BYTES:
            chunk = self._vad_buf[:VAD_CHUNK_BYTES]
            self._vad_buf = self._vad_buf[VAD_CHUNK_BYTES:]
            _t0 = time.perf_counter()
            result = self.vad.process_chunk(chunk)
            if self.billing is not None:
                # units cố ý bỏ trống: số chunk 32ms không quy ra đơn giá nào;
                # cơ sở tính tiền của VAD là audio_sec (giây audio đã quét).
                self.billing.add_audio(
                    "vad",
                    audio_sec=settings.vad_chunk_ms / 1000.0,
                    wall_ms=(time.perf_counter() - _t0) * 1000.0,
                )
            if self._input_gate.mode == "vad":
                self._input_gate.feed_vad(result["is_speech"])
            if self._addr_episode_active and not self._addr_paused:
                # Đang đo episode: tích lũy speech tới ngưỡng soft-pause. Ưu
                # tiên nhánh này lên trước INTERRUPTED — real Silero VAD KHÔNG
                # có transition thoát khỏi INTERRUPTED (silero.py::_update_state),
                # nó latch mãi cho tới khi set_speaking()/set_idle() được gọi.
                # Re-arm ở đây để VAD tiếp tục sống qua chunk kế; tracker bên
                # dưới là authority DUY NHẤT cho pause/reset khi episode active.
                if result["state"] == VADState.INTERRUPTED:
                    self.vad.set_speaking()
                action = self._addr_tracker.feed(result["is_speech"])
                if action == "pause":
                    await self._addressee_soft_pause()
                elif action == "reset":
                    self._addr_episode_active = False
                    self.vad.set_speaking()  # tiếp tục nghe barge-in mới
            elif result["state"] == VADState.INTERRUPTED:
                if self._speaker_tracker is not None:
                    # Verdict-driven barge-in: giữ máy trạng thái VAD sống;
                    # chunk verdict kế tiếp của tracker quyết pause/interrupt.
                    self.vad.set_speaking()
                elif self._addr_gate_enabled:
                    self._begin_addressee_episode()
                else:
                    await self._handle_interrupt()

        # Gate STT input (off/rms/vad) with shared pre-roll.
        if self.stt:
            chunks = self._input_gate.gate(data)
            if not chunks:
                self.metrics.record_latency("guard", "frames_gated_bytes", len(data))
                # Gate closed but an utterance may be pending: feed synthetic
                # silence so the STT endpoint fires at its normal timing. Bypasses
                # the real-chunk loop, so it never reaches the speaker tracker.
                silence = self._input_gate.keepalive(len(data))
                if silence is not None:
                    await self.stt.send(silence)
            for chunk in chunks:
                if self._stt_audio_start == 0.0:
                    self._stt_audio_start = time.monotonic()
                    if self._speaker_tracker is not None:
                        self._speaker_tracker.begin_utterance()
                if self._speaker_tracker is not None:
                    self._speaker_tracker.feed(chunk)
                if self.billing is not None:
                    # CHỈ audio thật của khách. Im lặng keepalive ở nhánh trên
                    # cố ý KHÔNG cộng vào audio_sec — agent tự bơm nó, khách
                    # không nói nó. Nó phản ánh trong wall_ms lúc đóng phiên.
                    self.billing.add_audio("stt", audio_sec=len(chunk) / (settings.stt_sample_rate * 2))
                await self.stt.send(chunk)

        self._audio_ring_append(data)

    def _agent_is_speaking(self) -> bool:
        return self._agent_task is not None and not self._agent_task.done()

    def _spawn_bg(self, coro: Awaitable) -> asyncio.Task:
        """Fire-and-forget a coroutine with a strong ref.

        asyncio only holds a *weakref* to a bare `ensure_future()` task, so an
        un-referenced background task can be GC'd mid-flight (repo gotcha).
        Every background writer in this class must go through here (or the
        equivalent inline `_bg_tasks.add` pattern) instead of a bare
        `asyncio.ensure_future`.
        """
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def _handle_interrupt(self) -> None:
        """Cancel the in-flight agent task and clear buffered agent audio.

        Order (CONCERNS.md 7.1, Phase 4.1 final):
          1. `agent.pause_tts()` — stops TTS production at the source.
          2. Cancel the agent task.
          3. `audio_output.clear()` — drops already-buffered audio so the
             caller stops hearing anything ASAP.
          4. Reset VAD to idle.

        `_interrupt_log_t0` is a Python-side logging stamp, NOT the moment
        the caller perceives silence (see class docstring). The recorded
        `interrupt.pipeline_ms` metric is therefore the time spent in this
        handler — a regression guard on the server-side interrupt path
        itself. The caller-perceived end-to-end cut is measured in Phase 6
        load tests and in the integration test that ships with this fix.
        """
        if not self._agent_task or self._agent_task.done():
            logger.info("Interrupt confirmed but no active agent task — nothing to cancel")
            return
        self._interrupt_log_t0 = time.monotonic()
        logger.info("Interruption detected — pausing TTS, cancelling agent, clearing audio.")
        try:
            await self.agent.pause_tts()
        except Exception:  # noqa: BLE001 - must not block the rest of the sequence
            logger.exception("agent.pause_tts() raised — continuing interrupt sequence")
        self._agent_task.cancel()
        if self._audio_output is not None:
            self._audio_output.clear()
        interrupt_ms = (time.monotonic() - self._interrupt_log_t0) * 1000
        self.metrics.record_latency("interrupt", "pipeline_ms", interrupt_ms)
        self.vad.set_idle()

    async def _on_speaker_verdict(self, label: str, sim: float, idx: int) -> None:
        """Tracker chunk verdict → quyết barge-in NGAY, không đợi final.

        speaker + agent đang nói → soft-pause (gate bật) / interrupt thẳng.
        non-speaker/unknown → agent nói tiếp (unknown = embed fail: interrupt
        fail-closed). Agent không nói → chỉ ghi nhãn, không hành động.
        """
        if not self._agent_is_speaking():
            return
        if label != "speaker":
            self.vad.set_speaking()
            return
        if self._addr_paused:
            return  # đã soft-pause; classifier của final sẽ quyết
        if self._addr_gate_enabled:
            await self._begin_addressee_pause_from_floor()
        else:
            await self._handle_interrupt()

    async def _spv_embed(self, pcm: bytes) -> np.ndarray | None:
        """Embed một span PCM off-loop — inject vào SpeakerTracker."""
        if not pcm:
            return None
        _t0 = time.perf_counter()
        try:
            return await asyncio.to_thread(SpeakerEmbedder.get_instance().embed, pcm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Speaker] embed error: %s", exc)
            return None
        finally:
            if self.billing is not None:
                self.billing.add_audio(
                    "speaker_verify",
                    audio_sec=len(pcm) / (settings.stt_sample_rate * 2),
                    wall_ms=(time.perf_counter() - _t0) * 1000.0,
                    units=1,
                )

    def _begin_addressee_episode(self) -> None:
        """Gate on: tiếng người đè lên agent — đo trước, quyết sau (KHÔNG cancel)."""
        if not self._agent_is_speaking() or self._addr_episode_active:
            return
        self._addr_episode_active = True
        self._addr_episode_verdict = None
        self._addr_tracker.reset()
        # VAD confirm chunks đã là speech — nạp trước vào tracker.
        for _ in range(settings.vad_interrupt_confirm_chunks):
            self._addr_tracker.feed(True)
        self.vad.set_speaking()  # giữ máy trạng thái VAD sống cho episode kế

    async def _begin_addressee_pause_from_floor(self) -> None:
        """Chunk verdict của tracker nói "speaker" đè lên agent — nạp vào gate.

        Đi thẳng soft-pause (KHÔNG chạy lại EpisodeTracker: một chunk verdict chỉ
        bắn sau ≥ mốc probe cuối (spv_probe_marks_sec) audio, ≥ addressee_min_speech_ms
        nên duration đã đủ). Re-entry no-op khi đang pause — timer deadline cũ không
        được re-arm (leak sẽ commit sớm).
        """
        if self._addr_paused or not self._agent_is_speaking():
            return
        self._addr_episode_active = True
        self._addr_episode_verdict = None
        self._addr_tracker.reset()  # mirrors _begin_addressee_episode — no stale feed leaks in
        self.vad.set_speaking()
        logger.info("[Addressee] soft-pause (floor-verified asker) — waiting for STT text")
        await self._addressee_soft_pause()

    def _addr_deadline_s(self) -> float:
        """Hạn tối đa giữ soft-pause chờ STT final.

        Khách nói đè nhưng STT chưa chốt final (chậm / audio ồn) trong hạn này
        → fail-open DIRECTED (commit interrupt) như behavior trước khi có gate.

        Phải nhỏ hơn `voice_agent._PAUSE_WATCHDOG_S` (5s) — pacer-side watchdog
        đó sẽ tự resume playback trước khi deadline này bao giờ bắn nếu vi phạm
        (xem warning ở `__init__`). `ADDRESSEE_LLM_TIMEOUT_MS` vẫn giữ vai trò
        riêng: bound cho một lần gọi LLM verdict, không còn liên quan deadline này.
        """
        return settings.addressee_max_pause_ms / 1000

    async def _addressee_soft_pause(self) -> None:
        """Speech đủ ngưỡng: agent im (soft), chờ STT text để phán đoán."""
        self._addr_paused = True
        self.agent.pause_playback()
        if self._audio_output is not None:
            self._audio_output.clear()
        loop = asyncio.get_running_loop()
        deadline_s = self._addr_deadline_s()
        self._addr_deadline_handle = loop.call_later(deadline_s, lambda: self._spawn_bg(self._addressee_deadline()))
        logger.info("[Addressee] soft-pause — waiting for STT text (%.1fs)", deadline_s)

    async def _addressee_deadline(self) -> None:
        """Hết hạn mà chưa có verdict → DIRECTED fail-open (behavior cũ)."""
        if not self._addr_paused:
            return
        logger.info("[Addressee] decision deadline — fail-open DIRECTED")
        await self._addressee_commit_interrupt()

    def _addr_reset_episode(self) -> None:
        if self._addr_deadline_handle is not None:
            self._addr_deadline_handle.cancel()
            self._addr_deadline_handle = None
        self._addr_episode_active = False
        self._addr_paused = False
        self._addr_tracker.reset()
        # Mark this episode resolved so a verdict landing late discards itself
        # on completion instead of re-pausing mid-NEXT-turn.
        self._addr_episode_gen += 1

    async def _addressee_commit_interrupt(self) -> None:
        self._addr_reset_episode()
        self._addr_episode_verdict = Verdict.DIRECTED
        await self._handle_interrupt()

    # ------------------------------------------------------------------
    # STT callbacks
    # ------------------------------------------------------------------

    async def _on_partial(self, text: str) -> None:
        await self._send_event({"type": "partial_transcript", "text": text})

    async def _on_final(self, text: str, speaker: str | None = None) -> None:
        self._reset_idle()  # user spoke — cancel any idle countdown
        self._input_gate.notify_final()  # utterance ended → stop keepalive silence

        # Record STT latency on every final (including dropped ones) so the
        # next accepted utterance doesn't inherit stale accumulated time.
        if self._stt_audio_start > 0:
            stt_ms = (time.monotonic() - self._stt_audio_start) * 1000
            self.metrics.record_latency("stt", "final", stt_ms)
            self._stt_audio_start = 0.0

        # Billing: text_units = ký tự transcript final — cơ sở khớp hoá đơn
        # output-text-token của vendor STT (Soniox). Đo TRƯỚC mọi filter:
        # vendor đã transcribe là giá vốn đã tiêu, kể cả khi final bị vứt.
        if self.billing is not None and text:
            self.billing.add_audio("stt", text_units=len(text))

        if self._halluc_filter.is_hallucination(text):
            logger.info("[STT] Final dropped — hallucination filter: %r", text)
            return

        if not self._echo_cooldown.allow_stt():
            logger.info(
                "[STT] Final dropped — echo cooldown (tts_playing=%s, agent_task_alive=%s): %r",
                self._echo_cooldown.is_tts_playing,
                self._agent_is_speaking(),
                text,
            )
            return

        if self._speaker_tracker is not None and self._speaker_registry is not None:
            spk_verdict = await self._speaker_tracker.finalize()
            reg = self._speaker_registry
            logger.info(
                "[Speaker] final identity=%s new=%s cluster=%d sim=%.3f labels=%s text=%r",
                spk_verdict.identity,
                spk_verdict.is_new,
                spk_verdict.cluster_size,
                spk_verdict.best_sim,
                spk_verdict.probe_labels,
                text,
            )
            await self._send_event(
                {
                    "type": "final_transcript",
                    "text": text,
                    "speaker_labels": spk_verdict.probe_labels,
                    "speaker_id": spk_verdict.identity,
                }
            )
            # Phạm vi drop: single = mọi final; multi = chỉ mid-turn (floor đang có chủ).
            enforce = self._speaker_mode == "single" or self._agent_is_speaking() or self._addr_paused
            if reg.asker is None:
                # Nhánh 1 — floor mở (đầu phiên / sau drop_asker): KHÔNG BAO GIỜ drop.
                # Đây là ca khách ngắt auto-greeting; drop ở đây là mất câu mở cuộc gọi.
                if spk_verdict.identity is not None:
                    reg.set_asker(spk_verdict.identity)
                self._mismatch_streak = 0
            elif spk_verdict.identity is None:
                # Nhánh 2 — không đủ bằng chứng: fail-open, final vẫn trôi tiếp.
                # Van thoát CHỈ đếm khi verdict có cụm nhất quán (cluster_size >=
                # spv_enroll_min_cluster) — tức bằng chứng DƯƠNG của một giọng lạ.
                # Final ngắn không đủ audio để cụm (bằng-chứng-less, ví dụ hai câu
                # "dạ"/"đúng rồi ạ" liên tiếp) KHÔNG phải bằng chứng danh tính asker
                # sai — không được đếm, cũng không reset (giữ nguyên streak cũ).
                if spk_verdict.cluster_size >= settings.spv_enroll_min_cluster:
                    self._mismatch_streak += 1
                    if self._mismatch_streak >= settings.spv_mismatch_streak_max:
                        logger.info(
                            "[Speaker] %d final liên tiếp không nhận diện được — bỏ asker, mở lại floor",
                            self._mismatch_streak,
                        )
                        reg.drop_asker()
                        self._mismatch_streak = 0
            elif spk_verdict.identity == reg.asker:
                # Nhánh 3 — đúng người đang giữ lượt.
                self._mismatch_streak = 0
            elif enforce:
                # Nhánh 4/5 — danh tính khác (hoặc người mới) chen ngang giữa turn.
                # Danh tính mới đã được tạo trong finalize(), nên turn sau khi agent
                # im họ hỏi là được nhận ngay: đổi người xảy ra ở RANH GIỚI turn.
                logger.info(
                    "[Speaker] Dropped final — identity %s ≠ asker %s: %r", spk_verdict.identity, reg.asker, text
                )
                if self._addr_paused:
                    self.agent.resume_playback()
                    self._addr_reset_episode()
                if self._agent_is_speaking():
                    self.vad.set_speaking()
                return
            else:
                # Agent đang im: floor mở cho người kế tiếp.
                reg.set_asker(spk_verdict.identity)
                self._mismatch_streak = 0

        if self._addr_gate_enabled:
            # Cache chỉ có thể là None hoặc DIRECTED (từ _addressee_deadline's
            # fail-open commit) — SIDE_TALK không bao giờ bị cache nữa, nên
            # nhánh cached-SIDE_TALK cũ đã xoá (review round 1, MINOR-5).
            verdict = self._addr_episode_verdict
            self._addr_episode_verdict = None  # consume-once
            if verdict is None and (self._agent_is_speaking() or self._addr_paused):
                # Agent đang nói — hoặc đang soft-pause dù turn vừa kết thúc tự
                # nhiên (race pause/turn-end) — classify đúng MỘT lần trên
                # nguyên văn final. Stamp gen BEFORE the await (review round 1,
                # IMPORTANT-1): classify() awaits an LLM round-trip, so the
                # deadline timer can fire WHILE we're waiting and resolve this
                # SAME episode itself (fail-open DIRECTED commit) before our
                # verdict lands. Compare gen AFTER the await to detect that —
                # otherwise our own SIDE_TALK arm would drop the final into
                # dead air on top of an already-committed interrupt, and would
                # never null the DIRECTED the deadline cached, leaking it into
                # the NEXT final's cached-verdict read.
                gen = self._addr_episode_gen
                v = await addressee_gate.classify(
                    text,
                    agent_line=getattr(self.agent, "spoken_text_this_turn", ""),
                    last_user_text=self._last_user_text,
                    agent_name=settings.agent_name,
                    recent_dialogue=tuple(self._dialogue_ring),
                )
                if self._addr_episode_gen != gen:
                    # The deadline already resolved (and committed DIRECTED)
                    # while we awaited classify() — that commit is
                    # authoritative. Discard our own verdict, null the cache
                    # it left behind, and let this final proceed normally
                    # (do NOT commit again — the deadline already did).
                    logger.info("[Addressee] verdict stale (episode moved) — falling through")
                    self._addr_episode_verdict = None
                elif v is Verdict.SIDE_TALK:
                    logger.info("[Addressee] Dropped side-talk final mid-turn: %r", text)
                    if self._addr_paused:
                        self.agent.resume_playback()
                    self._addr_reset_episode()
                    if self._agent_is_speaking():
                        self.vad.set_speaking()
                    elif not self._stopping:
                        # Turn already finished naturally before this drop
                        # (the paused-but-done race) — its own _run_agent
                        # finally already fired _start_idle_timer, but this
                        # method's entry _reset_idle() just cancelled it
                        # (review round 1, MINOR-3). Restart the countdown
                        # the same way _run_agent's finally does, or the
                        # idle nudge would never fire again this call.
                        playback_remaining_ms = (
                            self._audio_output.queued_duration_s * 1000 + 200 if self._audio_output is not None else 200
                        )
                        total_delay = settings.idle_first_delay + (playback_remaining_ms / 1000)
                        self._start_idle_timer(total_delay)
                    return
                else:
                    await self._addressee_commit_interrupt()
                    self._addr_episode_verdict = None
            elif verdict is None and settings.addressee_gate_when_idle:
                # Idle here means the agent isn't mid-turn per _agent_is_speaking,
                # but spoken_text_this_turn still holds the JUST-FINISHED turn's
                # text (handle_utterance only resets it at the next turn's start) —
                # exactly the context this branch's verdict needs.
                v = await addressee_gate.classify(
                    text,
                    agent_line=getattr(self.agent, "spoken_text_this_turn", ""),
                    last_user_text=self._last_user_text,
                    agent_name=settings.agent_name,
                    recent_dialogue=tuple(self._dialogue_ring),
                )
                if v is Verdict.SIDE_TALK:
                    logger.info("[Addressee] Dropped side-talk final (idle): %r", text)
                    return
        self._last_user_text = text

        if speaker:
            logger.info("[STT] Final transcript (speaker %s): %r", speaker, text)
            self._current_speaker = speaker
            asyncio.ensure_future(self._track_speaker(speaker))
        else:
            logger.info("[STT] Final transcript received: %r", text)

        if not self._gender_detected and self._gender_detection_attempts < 3:
            self._gender_detection_attempts += 1
            asyncio.ensure_future(self._run_gender_detection())

        if self._smart_turn:
            audio = np.frombuffer(bytes(self._audio_ring), dtype=np.int16).astype(np.float32) / 32768.0
            result = self._smart_turn.predict(audio)
            prob = result["probability"]
            logger.info("[SmartTurn] prob=%.3f threshold=%.2f", prob, settings.smart_turn_threshold)

            if prob < settings.smart_turn_threshold:
                self._pending_finals.append(text)
                self._reset_hold_timer()
                return

            if self._pending_finals:
                text = " ".join(self._pending_finals) + " " + text
                self._pending_finals.clear()
            self._cancel_hold_timer()

        await self._trigger_agent_for_text(text)

    async def _trigger_agent_for_text(self, text: str) -> None:
        # Dialogue ring (spec 2026-08-12 amendment): agent's prior-turn spoken
        # text first (handle_utterance for THIS turn hasn't run yet, so the
        # property still holds the previous turn's — possibly interrupt-truncated
        # — text), then this accepted user text. A SIDE_TALK-dropped final never
        # reaches this method, so it never pollutes the ring.
        prev = getattr(self.agent, "spoken_text_this_turn", "")
        if prev:
            self._dialogue_ring.append(("agent", prev))
        self._dialogue_ring.append(("user", text))

        if self._addr_gate_enabled:
            # New turn = new episode world; a stale paused-episode deadline
            # (from a turn that ended naturally without going through the
            # gate, e.g. _READY_END) must never cancel THIS turn.
            self._addr_reset_episode()
        if self._agent_task and not self._agent_task.done():
            logger.warning("[SERVER] Cancelling active agent task due to new STT transcript.")
            self.agent.interrupt()
            self._agent_task.cancel()
            if self._audio_output is not None:
                self._audio_output.clear()
            try:
                await self._agent_task
            except (asyncio.CancelledError, Exception):
                pass
            self.vad.set_idle()
        # Reset idle SAU khối cancel: finally của _run_agent bị cancel vừa
        # re-arm idle timer (nó không phân biệt cancel với kết thúc tự nhiên) —
        # reset trước thì timer ma 25s sống xuyên turn mới và idle prompt nổ
        # giữa lúc answer đang phát (2026-09-03).
        self._reset_idle()

        speaker = getattr(self, "_current_speaker", None)
        known_speakers = getattr(self, "_known_speakers", {})
        if speaker and len(known_speakers) > 1:
            speaker_info = known_speakers.get(speaker, {})
            speaker_name = speaker_info.get("name", f"Speaker {speaker}")
            text = f"[{speaker_name}] {text}"

        logger.info("[SERVER] Starting new agent task for text: %r", text)
        self._agent_task = asyncio.ensure_future(self._run_agent(text))

    async def _track_speaker(self, speaker: str) -> None:
        """Register a newly-heard speaker. In-memory only — the map is read back
        in `_on_transcript` to prefix multi-speaker transcripts."""
        if not hasattr(self, "_known_speakers"):
            self._known_speakers = {}
        if speaker not in self._known_speakers:
            self._known_speakers[speaker] = {}
            logger.info(
                "[SPEAKER] New speaker detected: %s (total: %d)",
                speaker,
                len(self._known_speakers),
            )

    # ------------------------------------------------------------------
    # Audio ring / smart-turn hold
    # ------------------------------------------------------------------

    def _audio_ring_append(self, data: bytes) -> None:
        self._audio_ring.extend(data)
        max_bytes = 8 * settings.stt_sample_rate * 2
        if len(self._audio_ring) > max_bytes:
            self._audio_ring = self._audio_ring[-max_bytes:]

    def _reset_hold_timer(self) -> None:
        self._cancel_hold_timer()
        loop = asyncio.get_running_loop()
        self._hold_timer = loop.call_later(
            settings.smart_turn_max_hold_sec,
            lambda: asyncio.ensure_future(self._flush_pending_finals()),
        )

    def _cancel_hold_timer(self) -> None:
        if self._hold_timer:
            self._hold_timer.cancel()
            self._hold_timer = None

    async def _flush_pending_finals(self) -> None:
        if not self._pending_finals:
            return
        text = " ".join(self._pending_finals)
        self._pending_finals.clear()
        self._hold_timer = None
        logger.info("[SmartTurn] Timeout flush: %r", text)
        await self._trigger_agent_for_text(text)

    # ------------------------------------------------------------------
    # Gender detection (background)
    # ------------------------------------------------------------------

    async def _run_gender_detection(self) -> None:
        try:
            from noble_agent.storage import session_store

            c = await session_store.load_customer(self.session_id)
            if c.get("gender"):
                self._gender_detected = True
                return

            max_bytes = int(4 * settings.stt_sample_rate * 2)
            ring_copy = bytes(self._audio_ring[-max_bytes:])
            if not ring_copy:
                return

            from noble_agent.voice.gender_detector import GenderDetector

            detector = GenderDetector.get_instance()

            t0 = time.time()
            gender = await asyncio.to_thread(detector.predict, ring_copy)
            t1 = time.time()

            if gender:
                self._gender_detected = True
                logger.info(
                    "[GENDER] Detected %s for session %s (took %dms, attempt %d)",
                    gender,
                    self.session_id,
                    int((t1 - t0) * 1000),
                    self._gender_detection_attempts,
                )
                await session_store.save_customer(self.session_id, {"gender": gender})
                await self.agent.refresh_system_prompt()
            else:
                logger.debug(
                    "[GENDER] No result on attempt %d — will retry",
                    self._gender_detection_attempts,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("[GENDER] Tác vụ nhận diện giới tính nền gặp lỗi: %s", e)

    # ------------------------------------------------------------------
    # Agent runner
    # ------------------------------------------------------------------

    async def _run_greeting(self) -> None:
        """Speak the auto-greeting through the SAME interrupt machinery as a
        normal turn so the caller can barge in over it.

        The greeting used to run as a bare ``agent.greet()`` task: the VAD was
        never armed (``set_speaking``) and the task wasn't registered as
        ``_agent_task``, so ``_handle_interrupt`` early-exited and the first
        utterance was un-interruptible — while later turns (via ``_run_agent``)
        worked. Arming the VAD + echo cooldown here also stops the greeting's
        own audio from being mis-transcribed as caller speech. The caller MUST
        assign the returned task to ``self._agent_task`` for ``_handle_interrupt``
        / ``_trigger_agent_for_text`` to see it. Idle-timer arming is
        deliberately omitted to preserve existing post-greeting behavior.
        """
        try:
            if self._audio_output is not None:
                self._audio_output.clear()
            self.vad.set_speaking()
            self._echo_cooldown.on_tts_start()
            await self.agent.greet(self.session_id)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Greeting error: %s", exc, exc_info=True)
        finally:
            self._echo_cooldown.on_tts_done()
            self.vad.set_idle()

    async def _run_agent(self, text: str) -> None:
        try:
            if self._audio_output is not None:
                self._audio_output.clear()  # drop residuals from any cancelled prior task
            self.vad.set_speaking()
            self._echo_cooldown.on_tts_start()
            await self.agent.handle_utterance(text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Agent error: %s", exc, exc_info=True)
            await self._send_event({"type": "error", "message": str(exc)})
        finally:
            self._echo_cooldown.on_tts_done()
            self.vad.set_idle()
            if not self._stopping:
                playback_remaining_ms = (
                    self._audio_output.queued_duration_s * 1000 + 200 if self._audio_output is not None else 200
                )
                total_delay = settings.idle_first_delay + (playback_remaining_ms / 1000)
                self._start_idle_timer(total_delay)

    # ------------------------------------------------------------------
    # Idle state machine
    # ------------------------------------------------------------------

    def _start_idle_timer(self, delay: float) -> None:
        self._cancel_idle_timer()
        loop = asyncio.get_running_loop()
        self._idle_timer = loop.call_later(
            delay,
            lambda: asyncio.ensure_future(self._on_idle_timeout()),
        )

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _reset_idle(self) -> None:
        self._cancel_idle_timer()
        self._idle_state = 0

    async def _on_idle_timeout(self) -> None:
        if self._stopping:
            return
        if self._agent_is_speaking():
            # Timer nổ giữa turn (mọi ngả arm đều qua finally của _run_agent,
            # turn đang chạy sẽ tự arm lại khi kết thúc). Không được chèn idle
            # prompt đè lên answer: hai producer cùng đẩy một AudioSource là
            # nguồn capture_frame InvalidState + goodbye cắt máy giữa cuộc gọi.
            logger.info("[IDLE] Timeout while agent speaking — ignored (turn end re-arms)")
            return

        if self._idle_state == 0:
            self._idle_state = 1
            text = "Anh chị còn muốn tìm hiểu thêm gì, hay muốn em đặt lịch xem dự án không ạ?"
            logger.info("[IDLE] State 0 → sending prompt")
            await self._send_event({"type": "agent_speaking", "text": text, "turn_id": "idle_0"})
            await self.agent.speak_text(text)
            await self._send_event({"type": "agent_done", "turn_id": "idle_0"})
            if self._idle_state == 1 and not self._stopping:
                self._start_idle_timer(settings.idle_prompt_delay)

        elif self._idle_state == 1:
            self._idle_state = 2
            text = "Em xin phép ngắt máy nhé, khi nào cần anh chị cứ gọi lại bên em."
            logger.info("[IDLE] State 1 → sending goodbye")
            await self._send_event({"type": "agent_speaking", "text": text, "turn_id": "idle_1"})
            await self.agent.speak_text(text)
            await self._send_event({"type": "agent_done", "turn_id": "idle_1"})
            if self._idle_state == 2 and not self._stopping:
                self._start_idle_timer(settings.idle_goodbye_delay)

        elif self._idle_state == 2:
            logger.info("[IDLE] State 2 → disconnecting session %s", self.session_id)
            if not self._stopping:
                self._stopping = True
                await self._send_event({"type": "session_ended", "reason": "idle_timeout"})
                await self._on_idle_disconnect()

    async def _on_idle_disconnect(self) -> None:
        """Override point for the transport to perform its disconnect sequence.

        Default tears down shared state by calling `stop()`. aiortc subclass
        additionally closes the websocket; LiveKit subclass ends the room.
        """
        await self.stop()
