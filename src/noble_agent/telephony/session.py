"""Telephony session — bridges AudioSocket audio to VoiceAgent pipeline.

Reuses the full existing pipeline: VAD → STT → LLM → SentenceBuffer → TTS.
Only the audio transport differs: AudioSocket TCP instead of WebRTC.

One TelephonySession per phone call. Created by AudioSocketServer on each
incoming connection, managed by TelephonyManager.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable
from datetime import UTC, datetime

from noble_agent.config import settings
from noble_agent.metrics import MetricsCollector
from noble_agent.telephony.audiosocket import TYPE_AUDIO, TYPE_ERROR, TYPE_HANGUP, AudioSocketServer
from noble_agent.telephony.resampler import resample_8k_to_16k, resample_tts_to_8k
from noble_agent.voice import addressee_gate
from noble_agent.voice.addressee_gate import EpisodeTracker, Verdict
from noble_agent.voice.vad import SileroVAD, VADState
from noble_agent.voice.voice_agent import VoiceAgent

logger = logging.getLogger("telephony.session")

# Startup self-defense warnings in __init__ run once PER CALL, not once per
# process — dedupe so each distinct warning logs exactly once per process
# (review round 1, MINOR-6; mirrors base_session.py's `_warn_once`).
_WARNED_ONCE: set[str] = set()


def _warn_once(key: str, msg: str, *args: object) -> None:
    if key in _WARNED_ONCE:
        return
    _WARNED_ONCE.add(key)
    logger.warning(msg, *args)


# Module-level singleton set by `TelephonyManager.start()`. Other modules
# (notably `ARIClient.originate_channel`) read this to pre-populate
# `_caller_map` before an outbound Local/from-internal originate, so the
# AudioSocket session knows the callee's number when it connects.
_telephony_manager = None

# VAD chunk size in bytes (16kHz, 16-bit mono, configured chunk_ms)
VAD_CHUNK_BYTES = int(settings.stt_sample_rate * settings.vad_chunk_ms / 1000) * 2


class TelephonySession:
    """Per-call session bridging AudioSocket ↔ VoiceAgent."""

    def __init__(
        self,
        call_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        caller_number: str = "",
    ):
        self.call_id = call_id
        self.session_id = f"tel-{call_id}"
        # Part 2: caller_number seeded by TelephonyManager from ARI StasisStart.
        # May be "" for calls without ARI (dev testing, broken trunk, etc.) —
        # everything downstream must treat empty as "unknown caller".
        self.caller_number = caller_number
        self._reader = reader
        self._writer = writer
        self._running = False
        self._start_time = time.monotonic()
        self._started_at = datetime.now(UTC)

        # Reuse existing pipeline components
        self.vad = SileroVAD()
        self.stt = None
        self.metrics = MetricsCollector()

        from noble_agent.billing import context as _billing_ctx

        self.billing = (
            _billing_ctx.get_session_meter(self.session_id, "voice") if settings.billing_metering_enabled else None
        )

        self.agent = VoiceAgent(
            send_audio=self._send_audio,
            send_json=self._send_json,
            session_id=self.session_id,
            metrics=self.metrics,
            usage_meter=self.billing,
        )

        self._vad_buf = b""
        self._agent_task: asyncio.Task | None = None
        self._stt_audio_start: float = 0.0
        # Lúc stream STT được mở — billing `stt.wall_ms`/`units` (contract §2.1).
        self._stt_stream_open: float = 0.0
        self._audio_ring = bytearray()
        self._tts_active = False  # suppress silence during TTS playback
        self._keepalive_task: asyncio.Task | None = None

        # Strong-ref set for background asyncio tasks (prevents GC mid-flight).
        self._bg_tasks: set = set()

        # Addressee gate (chống nói leo) — spec 2026-08-12, subset của BaseSession:
        # không speaker gates, không smart-turn. Amendment đêm 2026-08-12: verdict
        # giờ chờ STT final, KHÔNG còn classify trên partial. Episode đo speech-ms
        # khi có tiếng đè lên agent; đủ ngưỡng → soft-pause, giữ tới final rồi
        # classify đúng MỘT lần.
        self._addr_gate_enabled = settings.addressee_gate_mode != "off"
        self._addr_tracker = EpisodeTracker(
            min_speech_ms=settings.addressee_min_speech_ms,
            chunk_ms=settings.vad_chunk_ms,
        )
        self._addr_episode_active = False
        self._addr_paused = False
        self._addr_episode_verdict: Verdict | None = None
        self._addr_deadline_handle: asyncio.TimerHandle | None = None
        # Bumped by _addr_reset_episode() — lets a stale in-flight background
        # writer detect its episode was already resolved and discard itself
        # instead of acting mid-NEXT-turn.
        self._addr_episode_gen = 0
        self._last_user_text = ""
        # Session-local dialogue ring cho addressee LLM verdict context (2026-08-12
        # amendment) — xem base_session.py cho comment đầy đủ.
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

    async def run(self):
        """Main call loop — read AudioSocket frames, process audio, play TTS back."""
        self._running = True
        logger.info("[TEL] Call started: call_id=%s session_id=%s", self.call_id, self.session_id)

        # Start silence keepalive IMMEDIATELY — before any init that takes time.
        # Asterisk drops AudioSocket if it receives no audio frames within ~5s.
        self._keepalive_task = asyncio.ensure_future(self._silence_keepalive())

        # Start audio loop IMMEDIATELY so we read Asterisk's frames and
        # prevent the TCP receive buffer from filling up (which causes disconnect).
        audio_task = asyncio.ensure_future(self._audio_loop())

        try:
            # Initialize pipeline concurrently while audio flows
            from noble_agent.storage import session_store

            await session_store.upsert_meta(self.session_id)

            # Seed the caller-ID phone into Redis BEFORE agent.start() so the
            # first-turn profile bootstrap (orchestrator) can look the caller up
            # by phone. The DB lookup itself lives in the orchestrator now — this
            # only establishes the phone identity for this session.
            if self.caller_number:
                try:
                    await session_store.save_customer(self.session_id, {"phone": self.caller_number})
                except Exception as seed_exc:
                    logger.warning("[TEL] seed phone failed: %s", seed_exc)

            # Start LLM (loads agent prompt from registry)
            await self.agent.start()

            # Start STT backend
            await self._create_and_start_stt()

            # Auto-greeting (same as WebRTC session)
            asyncio.ensure_future(self._greet())

            # Wait for audio loop to finish (runs until hangup/disconnect)
            await audio_task

        except asyncio.CancelledError:
            logger.info("[TEL] Call cancelled: %s", self.call_id)
        except asyncio.IncompleteReadError:
            logger.info("[TEL] Asterisk disconnected: %s", self.call_id)
        except Exception as exc:
            logger.error("[TEL] Call error %s: %s", self.call_id, exc, exc_info=True)
        finally:
            await self._cleanup()

    async def _audio_loop(self):
        """Read AudioSocket TLV frames and process audio."""
        while self._running:
            frame_type, payload = await AudioSocketServer._read_frame(self._reader)

            if frame_type == TYPE_HANGUP:
                logger.info("[TEL] Hangup received from Asterisk: %s", self.call_id)
                break

            if frame_type == TYPE_ERROR:
                logger.warning("[TEL] Error frame from Asterisk: %s", self.call_id)
                break

            if frame_type == TYPE_AUDIO and payload:
                # Resample 8kHz → 16kHz for STT/VAD
                pcm_16k = resample_8k_to_16k(payload)
                await self._handle_audio(pcm_16k)

    async def _handle_audio(self, data_16k: bytes):
        """Process 16kHz audio through VAD and STT (same logic as Session.handle_audio)."""
        # Feed STT (may not be ready yet during early init — that's OK)
        if self.stt:
            try:
                if self._stt_audio_start == 0.0:
                    self._stt_audio_start = time.monotonic()
                if self.billing is not None:
                    # Telephony has no synthetic-silence keepalive into STT (the
                    # AudioSocket keepalive in _silence_keepalive writes straight
                    # to Asterisk, never through self.stt) — every frame reaching
                    # here is real caller audio, already resampled to 16kHz by
                    # resample_8k_to_16k in _audio_loop.
                    self.billing.add_audio("stt", audio_sec=len(data_16k) / (settings.stt_sample_rate * 2))
                await self.stt.send(data_16k)
            except Exception as exc:
                logger.debug("[TEL] STT send error: %s", exc)

        # Ring buffer for gender detection / smart turn
        self._audio_ring.extend(data_16k)
        max_bytes = 8 * settings.stt_sample_rate * 2
        if len(self._audio_ring) > max_bytes:
            self._audio_ring = self._audio_ring[-max_bytes:]

        # VAD processing (always runs — interrupt detection still works)
        self._vad_buf += data_16k
        while len(self._vad_buf) >= VAD_CHUNK_BYTES:
            chunk = self._vad_buf[:VAD_CHUNK_BYTES]
            self._vad_buf = self._vad_buf[VAD_CHUNK_BYTES:]
            _t0 = time.perf_counter()
            result = self.vad.process_chunk(chunk)
            if self.billing is not None:
                # units cố ý bỏ trống — xem chú thích tương ứng trong BaseSession.
                self.billing.add_audio(
                    "vad",
                    audio_sec=settings.vad_chunk_ms / 1000.0,
                    wall_ms=(time.perf_counter() - _t0) * 1000.0,
                )

            if self._addr_episode_active and not self._addr_paused:
                # Ưu tiên nhánh này lên trước INTERRUPTED — real Silero VAD
                # KHÔNG có transition thoát khỏi INTERRUPTED (silero.py::
                # _update_state), nó latch mãi tới khi set_speaking()/
                # set_idle() được gọi. Re-arm ở đây để VAD sống qua chunk kế;
                # tracker bên dưới là authority DUY NHẤT cho pause/reset khi
                # episode active.
                if result["state"] == VADState.INTERRUPTED:
                    self.vad.set_speaking()
                action = self._addr_tracker.feed(result["is_speech"])
                if action == "pause":
                    await self._addressee_soft_pause()
                elif action == "reset":
                    self._addr_episode_active = False
                    self.vad.set_speaking()
            elif result["state"] == VADState.INTERRUPTED:
                if self._agent_task and not self._agent_task.done():
                    if self._addr_gate_enabled:
                        self._begin_addressee_episode()
                    else:
                        logger.info("[TEL] Interruption detected — cancelling agent task")
                        self.agent.interrupt()
                        self._agent_task.cancel()
                        self.vad.set_idle()

    def _agent_is_speaking(self) -> bool:
        return self._agent_task is not None and not self._agent_task.done()

    def _spawn_bg(self, coro: Awaitable) -> asyncio.Task:
        """Fire-and-forget a coroutine with a strong ref (see base_session._spawn_bg)."""
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def _begin_addressee_episode(self) -> None:
        """Gate on: tiếng người đè lên agent — đo trước, quyết sau (KHÔNG cancel)."""
        if not self._agent_is_speaking() or self._addr_episode_active:
            return
        self._addr_episode_active = True
        self._addr_episode_verdict = None
        self._addr_tracker.reset()
        for _ in range(settings.vad_interrupt_confirm_chunks):
            self._addr_tracker.feed(True)
        self.vad.set_speaking()  # giữ máy trạng thái VAD sống cho episode kế

    def _addr_deadline_s(self) -> float:
        """Hạn tối đa giữ soft-pause chờ STT final — fail-open DIRECTED khi hết.

        Phải nhỏ hơn `voice_agent._PAUSE_WATCHDOG_S` (5s) — pacer-side watchdog
        đó sẽ tự resume playback trước khi deadline này bao giờ bắn nếu vi phạm
        (xem warning ở `__init__`).
        """
        return settings.addressee_max_pause_ms / 1000

    async def _addressee_soft_pause(self) -> None:
        """Speech đủ ngưỡng: agent im (soft), chờ STT text để phán đoán.

        Telephony không có AudioOutput riêng (frame ghi thẳng Asterisk qua
        _send_audio, buffer ~20ms) — không có gì để clear ngoài pause_playback.
        """
        self._addr_paused = True
        self.agent.pause_playback()
        loop = asyncio.get_running_loop()
        deadline_s = self._addr_deadline_s()
        self._addr_deadline_handle = loop.call_later(deadline_s, lambda: self._spawn_bg(self._addressee_deadline()))
        logger.info("[TEL][Addressee] soft-pause — waiting for STT text (%.1fs)", deadline_s)

    async def _addressee_deadline(self) -> None:
        """Hết hạn mà chưa có verdict → DIRECTED fail-open (behavior cũ)."""
        if not self._addr_paused:
            return
        logger.info("[TEL][Addressee] decision deadline — fail-open DIRECTED")
        await self._addressee_commit_interrupt()

    def _addr_reset_episode(self) -> None:
        if self._addr_deadline_handle is not None:
            self._addr_deadline_handle.cancel()
            self._addr_deadline_handle = None
        self._addr_episode_active = False
        self._addr_paused = False
        self._addr_tracker.reset()
        self._addr_episode_gen += 1

    async def _addressee_commit_interrupt(self) -> None:
        self._addr_reset_episode()
        self._addr_episode_verdict = Verdict.DIRECTED
        if self._agent_task and not self._agent_task.done():
            logger.info("[TEL] Interruption detected — cancelling agent task")
            self.agent.interrupt()
            self._agent_task.cancel()
            self.vad.set_idle()

    async def _silence_keepalive(self):
        """Send silence frames every 20ms to keep AudioSocket alive.

        Asterisk drops the connection if it receives no audio back within ~5s.
        This runs from call start until call end, pausing when TTS is active.
        """
        # 20ms of silence at 8kHz, 16-bit mono = 320 bytes of zeros
        silence_frame = b"\x00" * 320
        while self._running:
            if not self._tts_active:
                try:
                    AudioSocketServer.write_audio_frame(self._writer, silence_frame)
                    await self._writer.drain()
                except Exception:
                    break
            await asyncio.sleep(0.02)

    async def _send_audio(self, pcm_bytes: bytes):
        """TTS callback — resample 24kHz → 8kHz, chunk into 20ms frames, pace output.

        Asterisk expects small frames (320 bytes = 20ms @ 8kHz slin).
        Each frame is paced at ~18ms to match real-time playback.
        """
        if not self._running:
            return

        self._tts_active = True
        pcm_8k = resample_tts_to_8k(pcm_bytes)
        if not pcm_8k:
            self._tts_active = False
            return
        self.vad.playback_active = True  # audio really flowing → barge-in RMS floor live

        # Chunk into 320-byte frames (20ms @ 8kHz, 16-bit mono)
        FRAME_SIZE = 320
        offset = 0
        while offset < len(pcm_8k) and self._running:
            chunk = pcm_8k[offset : offset + FRAME_SIZE]
            if len(chunk) < FRAME_SIZE:
                chunk = chunk + b"\x00" * (FRAME_SIZE - len(chunk))
            try:
                AudioSocketServer.write_audio_frame(self._writer, chunk)
                await self._writer.drain()
            except Exception:
                self._tts_active = False
                return
            offset += FRAME_SIZE
            # Pace at real-time: 18ms per 20ms frame
            await asyncio.sleep(0.018)

        self._tts_active = False

    async def _send_json(self, msg: dict):
        """JSON callback — log only (no browser WebSocket in telephony mode)."""
        msg_type = msg.get("type", "")
        if msg_type == "agent_speaking":
            logger.info("[TEL] Agent: %s", msg.get("text", "")[:100])
        elif msg_type == "partial_transcript":
            logger.debug("[TEL] STT partial: %s", msg.get("text", ""))

    async def _on_partial(self, text: str):
        """STT partial transcript callback."""
        await self._send_json({"type": "partial_transcript", "text": text})

    async def _on_final(self, text: str, speaker: str = None):
        """STT final transcript — trigger agent response."""
        logger.info("[TEL] STT final: %r (speaker=%s)", text, speaker)

        if self._stt_audio_start > 0:
            stt_ms = (time.monotonic() - self._stt_audio_start) * 1000
            self.metrics.record_latency("stt", "final", stt_ms)
            self._stt_audio_start = 0.0

        # Billing: text_units = ký tự transcript final — xem chú thích trong
        # BaseSession._on_final (đo trước mọi gate).
        if self.billing is not None and text:
            self.billing.add_audio("stt", text_units=len(text))

        if self._addr_gate_enabled:
            # Cache chỉ có thể là None hoặc DIRECTED (từ _addressee_deadline's
            # fail-open commit) — SIDE_TALK không bao giờ bị cache nữa, nên
            # nhánh cached-SIDE_TALK cũ đã xoá (review round 1, MINOR-5).
            verdict = self._addr_episode_verdict
            self._addr_episode_verdict = None  # consume-once
            if verdict is None and (self._agent_is_speaking() or self._addr_paused):
                # Agent đang nói — hoặc đang soft-pause dù turn vừa kết thúc tự
                # nhiên (race pause/turn-end) — classify đúng MỘT lần trên
                # nguyên văn final. (PSTN 1-1 → không có nhánh gate-when-idle
                # như BaseSession; khách side-talk khi agent im hiếm nên bỏ
                # qua để giữ subset gọn.) Stamp gen BEFORE the await (review
                # round 1, IMPORTANT-1) — the deadline can fire WHILE classify
                # is in flight and resolve this SAME episode itself (fail-open
                # DIRECTED commit) before our verdict lands; compare after the
                # await to detect that instead of double-acting.
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
                    # while we awaited classify() — authoritative. Discard our
                    # verdict, null the cache it left, let the final proceed
                    # (do NOT commit again — the deadline already did).
                    logger.info("[TEL][Addressee] verdict stale (episode moved) — falling through")
                    self._addr_episode_verdict = None
                elif v is Verdict.SIDE_TALK:
                    logger.info("[TEL][Addressee] Dropped side-talk final mid-turn: %r", text)
                    if self._addr_paused:
                        self.agent.resume_playback()
                    self._addr_reset_episode()
                    if self._agent_is_speaking():
                        self.vad.set_speaking()
                    return
                else:
                    await self._addressee_commit_interrupt()
                    self._addr_episode_verdict = None
        self._last_user_text = text

        await self._trigger_agent(text)

    async def _trigger_agent(self, text: str):
        """Start agent response (cancel any active task first)."""
        # Dialogue ring (spec 2026-08-12 amendment) — see BaseSession._trigger_agent_for_text.
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
            logger.info("[TEL] Cancelling active agent task for new transcript")
            self.agent.interrupt()
            self._agent_task.cancel()
            try:
                await self._agent_task
            except (asyncio.CancelledError, Exception):
                pass
            self.vad.set_idle()

        logger.info("[TEL] Starting agent for: %r", text)
        self._agent_task = asyncio.ensure_future(self._run_agent(text))

    async def _run_agent(self, text: str):
        """Execute agent pipeline for one utterance."""
        try:
            self.vad.set_speaking()
            await self.agent.handle_utterance(text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[TEL] Agent error: %s", exc, exc_info=True)

    async def _greet(self):
        """Send auto-greeting when call starts."""
        try:
            await self.agent.greet(self.session_id)
        except Exception as exc:
            logger.error("[TEL] Greeting error: %s", exc, exc_info=True)

    async def _create_and_start_stt(self):
        """Initialize STT backend (same logic as Session.start)."""
        try:
            if settings.stt_backend == "soniox":
                from noble_agent.voice.stt.soniox import SonioxSTT

                self.stt = SonioxSTT(on_partial=self._on_partial, on_final=self._on_final)
            elif settings.stt_backend == "qwen3asr":
                from noble_agent.voice.stt.qwen3asr import Qwen3ASRSTT

                self.stt = Qwen3ASRSTT(on_partial=self._on_partial, on_final=self._on_final)
            elif settings.stt_backend == "elevenlabs":
                from noble_agent.voice.stt.elevenlabs import ElevenLabsSTT

                self.stt = ElevenLabsSTT(on_partial=self._on_partial, on_final=self._on_final)
            else:
                from noble_agent.voice.stt.sherpa import SherpaSTT

                self.stt = SherpaSTT(on_partial=self._on_partial, on_final=self._on_final)

            # Mid-call recovery: restart the SAME backend if its stream dies.
            from noble_agent.voice.stt_reconnect import ReconnectingSTT

            self.stt = ReconnectingSTT(self.stt)
            await self.stt.start()
            self._stt_stream_open = time.monotonic()
            logger.info("[TEL] STT started: %s", settings.stt_backend)
        except Exception as exc:
            logger.error("[TEL] STT failed to start: %s", exc)
            self.stt = None

    async def _cleanup(self):
        """Clean up resources on call end."""
        self._running = False
        self._addr_reset_episode()
        duration = time.monotonic() - self._start_time
        ended_at = datetime.now(UTC)

        # Cancel silence keepalive
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except (asyncio.CancelledError, Exception):
                pass

        # Cancel agent task
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()
            try:
                await self._agent_task
            except (asyncio.CancelledError, Exception):
                pass

        # Stop STT
        if self.stt:
            try:
                await self.stt.stop()
            except Exception:
                pass

        # Billing: thời gian stream STT mở + số lần mở (contract §2.1) — xem chú
        # thích tương ứng trong BaseSession.stop.
        if self.billing is not None and self._stt_stream_open > 0:
            # purpose="stream" — xem chú thích tương ứng trong BaseSession.stop.
            self.billing.add_audio(
                "stt",
                purpose="stream",
                wall_ms=(time.monotonic() - self._stt_stream_open) * 1000.0,
                units=1,
            )
            self._stt_stream_open = 0.0

        # Part 2: persist customer profile by phone (cross-session memory).
        # Run before summary generation so summary reads the latest state.
        if self.caller_number:
            try:
                from noble_agent.storage import session_store

                snapshot = await session_store.load_customer(self.session_id)
                await session_store.save_customer_persistent(self.caller_number, snapshot)
                logger.info("[TEL] Persisted customer profile for phone=%s", self.caller_number)
            except Exception as exc:
                logger.warning("[TEL] persist customer failed: %s", exc)

        # Part 3: generate + store call summary (phone-keyed, cross-session).
        # Only if we have phone; otherwise summary can't be recalled later.
        # Wrapped in timeout so slow LLM doesn't block teardown.
        if self.caller_number:
            # Billing: teardown không có ai set meter ContextVar → nhãn `summary`
            # cuối cuộc gọi và nhãn `memory` không bao giờ được ghi. Xem chú thích
            # tương ứng ở BaseSession.stop.
            from noble_agent.billing import context as _billing_ctx

            with _billing_ctx.use_meter(self.billing):
                try:
                    from noble_agent.agent.summary.generator import generate_call_summary
                    from noble_agent.storage import session_store
                    from noble_agent.storage.pg_data_plane import persist_conversation

                    customer = await session_store.load_customer(self.session_id)
                    history = await session_store.load_history_from_state(self.session_id)
                    # Generous backstop only — per-provider bounding lives inside
                    # complete_once so the full fallback chain can run (see generator).
                    summary_doc = await asyncio.wait_for(
                        generate_call_summary(
                            self.session_id,
                            customer,
                            history,
                            started_at=self._started_at,
                            ended_at=ended_at,
                        ),
                        timeout=40.0,
                    )
                    running_version = getattr(getattr(self.agent, "_llm", None), "pinned_version", 0)
                    await persist_conversation(
                        summary_doc,
                        phone=self.caller_number,
                        session_id=self.session_id,
                        running_version=running_version or None,
                        source="voice",
                    )

                    # User snapshot memory (PSTN is a real-phone path): fire-and-forget.
                    try:
                        from noble_agent.agent.memory import update_snapshot_after_call
                        from noble_agent.config import get_settings
                        from noble_agent.storage.persist import fire_and_forget

                        fire_and_forget(
                            update_snapshot_after_call(
                                get_settings(),
                                phone=self.caller_number,
                                session_id=self.session_id,
                                history=history,
                            )
                        )
                    except Exception as mem_exc:  # noqa: BLE001
                        logger.warning("[TEL][MEMORY] snapshot scheduling failed: %s", mem_exc)
                except TimeoutError:
                    logger.warning("[TEL][SUMMARY] LLM timeout, skipping narrative")
                except Exception as exc:
                    logger.warning("[TEL][SUMMARY] save failed: %s", exc)

        if self.billing is not None:
            try:
                from noble_agent.billing import context as _billing_ctx
                from noble_agent.billing import sink as _billing_sink

                self.billing.add_audio("call", purpose="session", audio_sec=duration, units=1)
                # final=True — xem chú thích ở BaseSession.stop.
                await _billing_sink.flush(self.billing, final=True)
                _billing_ctx.pop_session_meter(self.session_id)
                _billing_sink.forget_session(self.session_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[TEL] billing: flush cuối phiên thất bại: %s", exc)

        logger.info(
            "[TEL] Call ended: call_id=%s duration=%.1fs phone=%s",
            self.call_id,
            duration,
            self.caller_number or "(unknown)",
        )


class TelephonyManager:
    """Manages AudioSocket server + ARI client + active telephony sessions.

    Phone capture flow (Part 2):
      1. Caller dials hotline → FreePBX inbound route → dialplan enters
         `Stasis(noble-voice-agent)` — ARI WebSocket receives `StasisStart`.
      2. `_on_stasis_start` saves `channel.caller.number` into `_caller_map`
         keyed by `channel.id` (Asterisk UniqueID) and calls `continue_channel`
         so the dialplan proceeds to `AudioSocket(...)`.
      3. ~300ms later AudioSocket connects; `_on_new_call` looks up the phone
         in the map. Exact match works when dialplan uses
         `Set(AS_UUID=${CHANNEL(uniqueid)})`; fallback "most recent" kicks in
         when AS_UUID is hashed (MD5) and therefore can't exact-match.
      4. The resolved phone is passed to `TelephonySession` which seeds the
         customer profile from Postgres `tenant_data.contacts`.
    """

    def __init__(self):
        self._sessions: dict[str, TelephonySession] = {}
        self._audiosocket: AudioSocketServer | None = None
        self._ari_task: asyncio.Task | None = None
        self._ari_client = None  # populated in start() if ARI configured
        # Part 2: ARI channel_id → normalized caller phone. Entries expire 30s
        # after StasisEnd (AudioSocket may arrive up to 300ms later, giving
        # plenty of slack). Empty when agent runs without ARI.
        self._caller_map: dict[str, str] = {}

    async def start(self):
        """Start AudioSocket server and optionally ARI client."""
        # Register singleton so `ARIClient.originate_channel` can pre-populate
        # the caller_map for outbound calls.
        global _telephony_manager
        _telephony_manager = self

        # AudioSocket server
        self._audiosocket = AudioSocketServer(on_new_call=self._on_new_call)
        await self._audiosocket.start()

        # ARI client (optional — only if password is configured)
        if settings.asterisk_ari_password:
            from noble_agent.telephony.ari_client import ARIClient

            self._ari_client = ARIClient(
                on_stasis_start=self._on_stasis_start,
                on_stasis_end=self._on_stasis_end,
                on_channel_hangup=self._on_channel_hangup,
            )
            self._ari_task = asyncio.ensure_future(self._ari_client.connect())
            logger.info("[TEL] ARI client connecting to %s:%s", settings.asterisk_host, settings.asterisk_ari_port)
        else:
            logger.info("[TEL] ARI client skipped (no ASTERISK_ARI_PASSWORD set)")

        logger.info("[TEL] Telephony manager started")

    async def stop(self):
        """Stop everything."""
        if self._audiosocket:
            await self._audiosocket.stop()
        if self._ari_task:
            self._ari_task.cancel()
        for session in list(self._sessions.values()):
            session._running = False
        logger.info("[TEL] Telephony manager stopped")

    async def _on_new_call(self, call_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """AudioSocket callback — new phone call connected.

        Looks up phone from `_caller_map`:
        1. Exact match on `call_id` — works when dialplan sets
           `Set(AS_UUID=${CHANNEL(uniqueid)})` so AudioSocket frame UUID ==
           ARI channel.id.
        2. Fallback — consume any entry in the map (most-recent-wins). Required
           when dialplan hashes AS_UUID (e.g. `MD5(UNIQUEID+EPOCH)`), making
           exact correlation impossible.
        """
        phone = self._caller_map.pop(call_id, "")
        if not phone and self._caller_map:
            for ch_id, num in list(self._caller_map.items()):
                if num:
                    phone = num
                    self._caller_map.pop(ch_id, None)
                    logger.info(
                        "[TEL] Caller matched by fallback: channel=%s phone=%s (AudioSocket=%s)",
                        ch_id,
                        num,
                        call_id,
                    )
                    break
        if not phone:
            logger.info("[TEL] No caller phone available for call_id=%s (ARI skipped or trunk strips CLI)", call_id)

        session = TelephonySession(call_id, reader, writer, caller_number=phone)
        self._sessions[call_id] = session
        try:
            await session.run()
        finally:
            self._sessions.pop(call_id, None)

    async def _on_stasis_start(self, event: dict):
        """ARI callback — new call entered Stasis app.

        Extracts caller number, normalizes, caches it keyed by ARI channel.id,
        then calls `continue_channel` so the dialplan proceeds to AudioSocket.
        """
        channel = event.get("channel", {})
        channel_id = channel.get("id", "")
        raw_caller = channel.get("caller", {}).get("number", "")

        from noble_agent.telephony.phone_utils import normalize_phone

        phone = normalize_phone(raw_caller)

        logger.info(
            "[TEL][ARI] StasisStart: channel=%s caller_raw=%r phone=%r (map_size=%d)",
            channel_id,
            raw_caller,
            phone,
            len(self._caller_map),
        )
        if channel_id and phone:
            self._caller_map[channel_id] = phone
            logger.info("[TEL] Caller registered: channel=%s phone=%s", channel_id, phone)

        # Must resume dialplan or channel hangs in Stasis app forever.
        if channel_id and self._ari_client is not None:
            try:
                await self._ari_client.continue_channel(channel_id)
            except Exception as exc:
                logger.warning("[TEL] continue_channel failed: %s", exc)

    async def _on_stasis_end(self, event: dict):
        """ARI callback — channel left Stasis app.

        Do NOT delete from `_caller_map` immediately — AudioSocket typically
        connects 200-400ms after StasisEnd. Delete after 30s if no consumer.
        """
        channel_id = event.get("channel", {}).get("id", "")
        if not channel_id:
            return
        logger.info("[TEL][ARI] StasisEnd: channel=%s (keeping caller_map entry)", channel_id)

        async def _delayed_cleanup():
            await asyncio.sleep(30)
            removed = self._caller_map.pop(channel_id, None)
            if removed:
                logger.debug("[TEL] Cleaned stale caller_map entry: channel=%s", channel_id)

        asyncio.ensure_future(_delayed_cleanup())

    async def _on_channel_hangup(self, event: dict):
        """ARI callback — channel was destroyed."""
        channel_id = event.get("channel", {}).get("id")
        logger.info("[TEL] Channel hangup: %s", channel_id)
