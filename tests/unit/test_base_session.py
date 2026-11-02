"""Unit tests for `BaseSession` — Phase 2.

Tests verify the transport-agnostic pipeline state machine without
spinning up any real transport, STT, TTS, or VoiceAgent. Collaborators are
patched at the `noble_agent.server.base_session` import site.

Coverage goals (≥80% of base_session.py):
- `_handle_interrupt` guards + ordering (CONCERNS 7.1 partial fix).
- `process_audio_frame` → STT feed + VAD interrupt trigger.
- `_on_final` audio guards.
- `_trigger_agent_for_text` task replacement.
- Idle state machine transitions.
- `_send_agent_audio` routing.
- Event sink defaulting and override.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from noble_agent.voice.speaker_tracker import UtteranceVerdict


@asynccontextmanager
async def _patched_collaborators() -> AsyncIterator[dict]:
    """Patch heavy collaborators so BaseSession can be instantiated cheaply."""
    with (
        patch("noble_agent.server.base_session.settings") as mock_settings,
        patch("noble_agent.server.base_session.resolve_speaker_mode") as mock_resolve_speaker_mode,
        patch("noble_agent.server.base_session.SileroVAD") as MockVAD,
        patch("noble_agent.server.base_session.VoiceAgent") as MockVoiceAgent,
        patch("noble_agent.server.base_session.MetricsCollector") as MockMetrics,
        patch("noble_agent.server.base_session.EchoCooldown") as MockEcho,
        patch("noble_agent.server.base_session.WhisperHallucinationFilter") as MockHalluc,
    ):
        mock_settings.stt_sample_rate = 16000
        mock_settings.vad_chunk_ms = 32
        mock_settings.smart_turn_enabled = False
        mock_settings.stt_backend = "sherpa"
        mock_settings.tts_backend = "vieneu"
        mock_settings.idle_first_delay = 0.01
        mock_settings.idle_prompt_delay = 0.01
        mock_settings.idle_goodbye_delay = 0.01
        mock_settings.smart_turn_threshold = 0.5
        mock_settings.smart_turn_max_hold_sec = 2.0
        mock_settings.stt_input_gate_mode = "off"
        mock_settings.audio_gate_preroll_chunks = 3
        mock_settings.audio_gate_min_rms = 160.0
        mock_settings.audio_gate_required_consecutive = 3
        mock_settings.audio_gate_barge_in_rms = 2400.0
        mock_settings.stt_vad_gate_hangover_ms = 300
        mock_settings.stt_gate_keepalive_max_sec = 2.0
        mock_settings.audio_guard_repetition_detector_enabled = False
        mock_settings.speaker_mode = "off"
        mock_settings.speaker_interrupt_min_sec = 0.8
        mock_settings.speaker_match_threshold = 0.5
        mock_settings.speaker_min_enroll_sec = 1.0
        mock_settings.speaker_embed_window_sec = 3.0
        mock_settings.spv_chunk_sec = 2.0
        mock_settings.spv_max_centroids = 10
        mock_settings.spv_min_match_probe = 2
        mock_settings.spv_min_match_identify = 1
        mock_settings.speaker_verification_enabled = False
        # New spv_* probe/enroll schedule (spec 2026-09-03) — parse_probe_schedule
        # and SpeakerTracker's float math need real values, not MagicMock attrs.
        mock_settings.spv_probe_marks_sec = "0.25,0.4,0.6,0.9,1.3"
        mock_settings.spv_probe_bonus = "0.15,0.1,0.05,0,0"
        mock_settings.spv_probe_tail_window_sec = 1.5
        mock_settings.spv_probe_tail_hop_sec = 1.0
        mock_settings.spv_enroll_window_sec = 1.5
        mock_settings.spv_enroll_hop_sec = 0.75
        mock_settings.spv_enroll_consensus_sim = 0.5
        mock_settings.spv_enroll_min_cluster = 2
        mock_settings.spv_adapt_margin = 0.1
        mock_settings.spv_max_identities = 4
        mock_settings.spv_utt_cap_sec = 30.0
        mock_settings.spv_mismatch_streak_max = 2
        mock_settings.vad_interrupt_confirm_chunks = 3
        mock_settings.addressee_gate_mode = "off"
        mock_settings.addressee_min_speech_ms = 400
        mock_settings.addressee_llm_timeout_ms = 600
        mock_settings.addressee_gate_when_idle = False
        mock_settings.addressee_max_pause_ms = 4000
        mock_settings.agent_name = "Luna"
        # Off by default (matches the real settings default) — a bare MagicMock
        # attribute is truthy, so leaving this unset would silently register a
        # real UsageMeter (billing/context._sessions) for every BaseSession
        # these ~90 unrelated tests construct (fix round 2, Task 7). Billing
        # tests override this explicitly per-test.
        mock_settings.billing_metering_enabled = False
        # resolve_speaker_mode reads from mock_settings.speaker_mode by default.
        mock_resolve_speaker_mode.side_effect = lambda: mock_settings.speaker_mode

        vad = MagicMock()
        vad.process_chunk = MagicMock(return_value={"state": "listening"})
        MockVAD.return_value = vad

        agent = AsyncMock()
        agent.interrupt = MagicMock()
        agent._tts = MagicMock(spec=[])  # no warm_up attr
        MockVoiceAgent.return_value = agent

        echo = MagicMock()
        echo.allow_stt.return_value = True
        MockEcho.return_value = echo

        halluc = MagicMock()
        halluc.is_hallucination.return_value = False
        MockHalluc.return_value = halluc

        MockMetrics.return_value = MagicMock()

        yield {
            "settings": mock_settings,
            "vad": vad,
            "agent": agent,
            "echo": echo,
            "halluc": halluc,
        }


class _FakeAudioOutput:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.clears = 0
        self.queued_s = 0.0

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    def clear(self) -> None:
        self.clears += 1

    @property
    def queued_duration_s(self) -> float:
        return self.queued_s


@pytest.fixture
def deps():  # noqa: ANN201 - pytest fixture
    return {}


# ----------------------------------------------------------------------
# _handle_interrupt
# ----------------------------------------------------------------------


class TestHandleInterrupt:
    async def test_noop_when_no_agent_task(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-1")
            s._audio_output = _FakeAudioOutput()
            # No agent task set.
            await s._handle_interrupt()

            cols["agent"].interrupt.assert_not_called()
            assert s._audio_output.clears == 0

    async def test_noop_when_agent_task_done(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-2")
            s._audio_output = _FakeAudioOutput()

            async def _instant() -> None:
                return None

            s._agent_task = asyncio.create_task(_instant())
            await s._agent_task  # mark it done

            await s._handle_interrupt()
            cols["agent"].interrupt.assert_not_called()
            assert s._audio_output.clears == 0

    async def test_cancels_task_clears_queue_sets_vad_idle_ordering(self) -> None:
        """CONCERNS 7.1: the ordering is interrupt→cancel→clear→set_idle."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-3")
            out = _FakeAudioOutput()
            s._audio_output = out

            call_order: list[str] = []

            async def _observe_pause() -> None:
                call_order.append("interrupt")

            cols["agent"].pause_tts = _observe_pause
            cols["agent"].interrupt.side_effect = lambda: call_order.append("interrupt_flag")

            async def _long() -> None:
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    call_order.append("cancel_observed")
                    raise

            original_clear = out.clear

            def _track_clear() -> None:
                call_order.append("clear")
                original_clear()

            out.clear = _track_clear  # type: ignore[method-assign]

            cols["vad"].set_idle.side_effect = lambda: call_order.append("set_idle")

            task = asyncio.create_task(_long())
            s._agent_task = task

            await s._handle_interrupt()
            # Let the cancellation propagate.
            with pytest.raises(asyncio.CancelledError):
                await task

            # interrupt came before clear which came before set_idle.
            assert call_order.index("interrupt") < call_order.index("clear")
            assert call_order.index("clear") < call_order.index("set_idle")
            assert out.clears == 1

    async def test_records_interrupt_metric(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-4")
            s._audio_output = _FakeAudioOutput()

            async def _long() -> None:
                await asyncio.sleep(10)

            task = asyncio.create_task(_long())
            s._agent_task = task

            await s._handle_interrupt()
            with pytest.raises(asyncio.CancelledError):
                await task

            # MetricsCollector is mocked in the patch.
            s.metrics.record_latency.assert_any_call("interrupt", "pipeline_ms", pytest_approx_any())


# Tiny helper — pytest's approx() requires a value; we just want "any float".
def pytest_approx_any():
    class _Any:
        def __eq__(self, _other: object) -> bool:
            return True

    return _Any()


# ----------------------------------------------------------------------
# process_audio_frame
# ----------------------------------------------------------------------


class TestProcessAudioFrame:
    async def test_feeds_stt_and_appends_ring(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-5")
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()

            data = b"\x00\x00" * 512
            await s.process_audio_frame(data)

            s.stt.send.assert_awaited_once_with(data)
            assert bytes(s._audio_ring) == data

    async def test_vad_interrupted_triggers_handle_interrupt(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import (
                VAD_CHUNK_BYTES,
                BaseSession,
            )
            from noble_agent.voice.vad import VADState

            cols["vad"].process_chunk.return_value = {"state": VADState.INTERRUPTED}

            s = BaseSession("sid-6")
            s.stt = None
            s._audio_output = _FakeAudioOutput()

            async def _long() -> None:
                await asyncio.sleep(10)

            s._agent_task = asyncio.create_task(_long())

            await s.process_audio_frame(b"\x00" * VAD_CHUNK_BYTES)

            cols["agent"].pause_tts.assert_awaited_once()
            with pytest.raises(asyncio.CancelledError):
                await s._agent_task

    async def test_audio_ring_is_trimmed(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-7")
            s.stt = None
            s._audio_output = _FakeAudioOutput()

            # max_bytes = 8 * sample_rate * 2 = 8 * 16000 * 2 = 256_000
            big = b"\x00" * 300_000
            s._audio_ring_append(big)
            assert len(s._audio_ring) <= 8 * cols["settings"].stt_sample_rate * 2


# ----------------------------------------------------------------------
# _on_final — audio guards
# ----------------------------------------------------------------------


class TestOnFinalGuards:
    async def test_hallucination_is_dropped(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["halluc"].is_hallucination.return_value = True
            s = BaseSession("sid-8")

            triggered: list[str] = []

            async def _fake_trigger(t: str) -> None:
                triggered.append(t)

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("ghost text")
            assert triggered == []

    async def test_echo_cooldown_blocks(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["echo"].allow_stt.return_value = False
            s = BaseSession("sid-9")

            triggered: list[str] = []

            async def _fake_trigger(t: str) -> None:
                triggered.append(t)

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("should be blocked")
            assert triggered == []

    async def test_clean_final_triggers_agent(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-10")
            triggered: list[str] = []

            async def _fake_trigger(t: str) -> None:
                triggered.append(t)

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("hello there")
            assert triggered == ["hello there"]


# ----------------------------------------------------------------------
# _trigger_agent_for_text
# ----------------------------------------------------------------------


class TestTriggerAgent:
    async def test_replaces_ongoing_task(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-11")
            s._audio_output = _FakeAudioOutput()

            # Pre-existing ongoing task.
            observed: list[str] = []
            started = asyncio.Event()

            async def _old() -> None:
                started.set()
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    observed.append("old_cancelled")
                    raise

            s._agent_task = asyncio.create_task(_old())
            # Yield control so `_old` enters its try block before we cancel.
            await started.wait()

            # Stub out the new agent run so we don't spin up a real one.
            async def _new_run(_text: str) -> None:
                observed.append("new_ran")

            s._run_agent = _new_run  # type: ignore[method-assign]

            await s._trigger_agent_for_text("new utterance")
            # Let the new task complete.
            await s._agent_task

            assert "old_cancelled" in observed
            assert "new_ran" in observed
            cols["agent"].interrupt.assert_called()

    async def test_prefixes_speaker_when_multi_speaker(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-12")
            s._current_speaker = "A"
            s._known_speakers = {"A": {"name": "Ann"}, "B": {"name": "Bob"}}

            captured: list[str] = []

            async def _capture(t: str) -> None:
                captured.append(t)

            s._run_agent = _capture  # type: ignore[method-assign]

            await s._trigger_agent_for_text("hi")
            # The task should complete with the prefixed text.
            await s._agent_task  # type: ignore[misc]
            assert captured == ["[Ann] hi"]


# ----------------------------------------------------------------------
# Idle state machine
# ----------------------------------------------------------------------


class TestIdleStateMachine:
    async def test_state_0_sends_prompt_and_advances_to_state_1(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-13")
            events: list[dict] = []

            async def _sink(msg: dict) -> None:
                events.append(msg)

            s._event_sink = _sink

            # Silence actual TTS.
            cols["agent"].speak_text = AsyncMock()

            await s._on_idle_timeout()
            assert s._idle_state == 1
            assert any(e.get("type") == "agent_speaking" and e.get("turn_id") == "idle_0" for e in events)
            assert any(e.get("type") == "agent_done" and e.get("turn_id") == "idle_0" for e in events)
            cols["agent"].speak_text.assert_awaited()

    async def test_state_2_invokes_on_idle_disconnect(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-14")
            s._idle_state = 2
            s._event_sink = AsyncMock()
            cols["agent"].speak_text = AsyncMock()

            disconnected = asyncio.Event()

            async def _fake_disconnect() -> None:
                disconnected.set()

            s._on_idle_disconnect = _fake_disconnect  # type: ignore[method-assign]

            await s._on_idle_timeout()
            assert disconnected.is_set()
            assert s._stopping is True

    async def test_reset_idle_clears_timer_and_state(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-15")
            s._idle_state = 1
            s._start_idle_timer(10)
            assert s._idle_timer is not None

            s._reset_idle()
            assert s._idle_timer is None
            assert s._idle_state == 0

    async def test_trigger_cancels_idle_timer_rearmed_by_cancelled_turn(self) -> None:
        """Bug 2026-09-03: `_trigger_agent_for_text` reset idle TRƯỚC khi cancel
        turn cũ, nên finally của `_run_agent` bị cancel re-arm timer 25s và nó
        sống xuyên turn mới — idle prompt nổ giữa lúc answer đang phát
        (capture_frame InvalidState burst, goodbye cắt máy giữa cuộc gọi)."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-idle-race")
            block = asyncio.Event()

            async def _blocked(_text: str) -> None:
                await block.wait()

            cols["agent"].handle_utterance = _blocked

            # Turn cũ chạy qua _run_agent THẬT để finally (re-arm idle) chạy khi cancel.
            s._agent_task = asyncio.ensure_future(s._run_agent("old"))
            await asyncio.sleep(0)  # cho task vào tới handle_utterance

            await s._trigger_agent_for_text("new")
            try:
                assert s._idle_timer is None, "timer ma từ turn bị cancel sống sót vào turn mới"
            finally:
                block.set()
                if s._agent_task is not None:
                    await s._agent_task
                s._cancel_idle_timer()

    async def test_idle_timeout_noop_while_agent_speaking(self) -> None:
        """Guard chống mọi ngả timer ma: timeout nổ khi agent đang nói phải
        no-op (không prompt, không advance state) — finally của turn đang chạy
        sẽ tự arm lại khi kết thúc."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-idle-guard")
            s._event_sink = AsyncMock()
            cols["agent"].speak_text = AsyncMock()

            async def _forever() -> None:
                await asyncio.Event().wait()

            s._agent_task = asyncio.create_task(_forever())
            try:
                await s._on_idle_timeout()
                assert s._idle_state == 0
                cols["agent"].speak_text.assert_not_awaited()
            finally:
                s._agent_task.cancel()
                with suppress(asyncio.CancelledError):
                    await s._agent_task


# ----------------------------------------------------------------------
# _send_agent_audio routing
# ----------------------------------------------------------------------


class TestSendAgentAudio:
    async def test_routes_to_audio_output_and_updates_echo(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-16")
            out = _FakeAudioOutput()
            s._audio_output = out

            await s._send_agent_audio(b"\x00\x00" * 10)
            assert out.sent == [b"\x00\x00" * 10]
            cols["echo"].on_tts_chunk.assert_called_with(20)

    async def test_marks_vad_playback_active(self) -> None:
        """First emitted TTS chunk = audio is really playing → RMS floor for
        barge-in becomes live (silero.py `playback_active`)."""
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-16b")
            s._audio_output = _FakeAudioOutput()
            assert s.vad.playback_active is not True

            await s._send_agent_audio(b"\x00\x00" * 10)
            assert s.vad.playback_active is True

    async def test_drops_when_no_audio_output(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-17")
            s._audio_output = None
            # Should not raise — just log-and-drop.
            await s._send_agent_audio(b"\x00\x00")
            # Echo bookkeeping still runs even on drop (pre-refactor semantics).
            cols["echo"].on_tts_chunk.assert_called_with(2)


# ----------------------------------------------------------------------
# Event sink
# ----------------------------------------------------------------------


class TestEventSink:
    async def test_default_sink_is_no_op(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-18")
            # Should not raise even without an explicit sink.
            await s._send_event({"type": "ping"})

    async def test_pipeline_installs_event_sink(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-19")
            received: list[dict] = []

            async def _sink(m: dict) -> None:
                received.append(m)

            async def _empty_audio_input() -> AsyncIterator[bytes]:
                if False:
                    yield b""

            out = _FakeAudioOutput()
            # start_pipeline returns immediately because the iterator is empty.
            await s.start_pipeline(_empty_audio_input(), out, event_sink=_sink)
            await s._send_event({"type": "after"})
            assert received == [{"type": "after"}]

    async def test_send_event_swallows_sink_exceptions(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-20")

            async def _bad(_msg: dict) -> None:
                raise RuntimeError("boom")

            s._event_sink = _bad
            # Must not raise — best-effort send.
            await s._send_event({"type": "x"})


# ----------------------------------------------------------------------
# start_pipeline + stop + start()
# ----------------------------------------------------------------------


class TestLifecycle:
    async def test_start_pipeline_processes_frames_until_end(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-21")
            s.stt = AsyncMock()
            out = _FakeAudioOutput()

            async def _input() -> AsyncIterator[bytes]:
                for _ in range(3):
                    yield b"\x00\x00" * 16

            await s.start_pipeline(_input(), out)
            assert s.stt.send.await_count == 3

    async def test_start_pipeline_honors_stopping_flag(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-22")
            s.stt = AsyncMock()
            s._stopping = True
            out = _FakeAudioOutput()

            async def _input() -> AsyncIterator[bytes]:
                yield b"\x00\x00" * 16

            await s.start_pipeline(_input(), out)
            s.stt.send.assert_not_awaited()

    async def test_stop_cleans_up(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            with (
                patch("noble_agent.storage.session_store.load_customer", new_callable=AsyncMock, return_value={}),
            ):
                s = BaseSession("sid-23")
                s.stt = AsyncMock()
                s._audio_output = _FakeAudioOutput()
                await s.stop()

                assert s._stopping is True
                s.stt.stop.assert_awaited()
                assert s._audio_output.clears == 1

    async def test_start_runs_parallel_init_and_warm_up_skipped_for_non_elevenlabs(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].stt_backend = "sherpa"
            cols["settings"].tts_backend = "vieneu"

            # Patch indirect deps that `start()` pulls in.
            mock_stt_inst = AsyncMock()

            with (
                patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=mock_stt_inst),
                patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
            ):
                from noble_agent.server.base_session import BaseSession

                s = BaseSession("sid-24")
                await s.start()

                cols["agent"].start.assert_awaited()
                mock_stt_inst.start.assert_awaited()
                from noble_agent.voice.stt_reconnect import ReconnectingSTT

                assert isinstance(s.stt, ReconnectingSTT)
                assert s.stt.inner is mock_stt_inst


# ----------------------------------------------------------------------
# _run_agent
# ----------------------------------------------------------------------


class TestRunAgent:
    async def test_run_agent_happy_path_starts_idle_timer(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-25")
            s._audio_output = _FakeAudioOutput()
            s._audio_output.queued_s = 0.1
            cols["agent"].handle_utterance = AsyncMock()

            await s._run_agent("hello")
            assert s._idle_timer is not None
            s._cancel_idle_timer()

    async def test_run_agent_swallows_cancel(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-26")
            s._audio_output = _FakeAudioOutput()

            async def _cancelled(_t: str) -> None:
                raise asyncio.CancelledError()

            cols["agent"].handle_utterance = AsyncMock(side_effect=_cancelled)
            # Should not propagate CancelledError to the caller.
            await s._run_agent("x")
            assert s._idle_timer is not None  # finally still started timer
            s._cancel_idle_timer()

    async def test_run_agent_error_emits_event(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-27")
            s._audio_output = _FakeAudioOutput()

            async def _raise(_t: str) -> None:
                raise RuntimeError("kaboom")

            cols["agent"].handle_utterance = AsyncMock(side_effect=_raise)

            sent: list[dict] = []

            async def _sink(m: dict) -> None:
                sent.append(m)

            s._event_sink = _sink
            await s._run_agent("y")
            assert any(m.get("type") == "error" and "kaboom" in m["message"] for m in sent)
            s._cancel_idle_timer()


# ----------------------------------------------------------------------
# speaker tracking + smart-turn hold
# ----------------------------------------------------------------------


class TestSpeakerAndHold:
    async def test_track_speaker_first_time_registers(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-28")
            await s._track_speaker("A")
            assert "A" in s._known_speakers

    async def test_track_speaker_no_ops_on_duplicate(self) -> None:
        """A repeat speaker must not reset the entry — the map is read back in
        `_on_transcript` to prefix multi-speaker transcripts."""
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-29")
            s._known_speakers = {"A": {"name": "Minh"}}
            await s._track_speaker("A")
            assert s._known_speakers == {"A": {"name": "Minh"}}

    async def test_flush_pending_finals_delegates_to_trigger(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-30")
            s._pending_finals = ["alpha", "beta"]

            captured: list[str] = []

            async def _fake(t: str) -> None:
                captured.append(t)

            s._trigger_agent_for_text = _fake  # type: ignore[method-assign]
            await s._flush_pending_finals()
            assert captured == ["alpha beta"]
            assert s._pending_finals == []

    async def test_flush_pending_finals_no_op_when_empty(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-31")
            called = False

            async def _fake(_t: str) -> None:
                nonlocal called
                called = True

            s._trigger_agent_for_text = _fake  # type: ignore[method-assign]
            await s._flush_pending_finals()
            assert called is False


# ----------------------------------------------------------------------
# Idle state 1 → goodbye
# ----------------------------------------------------------------------


class TestIdleGoodbye:
    async def test_state_1_sends_goodbye_and_advances_to_state_2(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-32")
            s._idle_state = 1
            events: list[dict] = []

            async def _sink(msg: dict) -> None:
                events.append(msg)

            s._event_sink = _sink
            cols["agent"].speak_text = AsyncMock()

            await s._on_idle_timeout()
            assert s._idle_state == 2
            assert any(e.get("turn_id") == "idle_1" and e.get("type") == "agent_speaking" for e in events)


# ----------------------------------------------------------------------
# Hold timer cancel semantics
# ----------------------------------------------------------------------


class TestHoldTimer:
    async def test_cancel_when_none_is_safe(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-33")
            s._hold_timer = None
            s._cancel_hold_timer()  # should not raise


# ----------------------------------------------------------------------
# Extra coverage: error branches and smart-turn
# ----------------------------------------------------------------------


class TestStartSTTError:
    async def test_stt_init_failure_logs_and_continues(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].stt_backend = "sherpa"
            cols["settings"].tts_backend = "vieneu"

            # Chain is remote → soniox → sherpa; with stt_backend=sherpa the
            # attempt order is sherpa → remote → soniox, so all three must fail
            # to exhaust the chain and leave stt=None.
            broken_stt = AsyncMock()
            broken_stt.start = AsyncMock(side_effect=RuntimeError("stt down"))
            broken_remote = AsyncMock()
            broken_remote.start = AsyncMock(side_effect=RuntimeError("remote down"))
            broken_soniox = AsyncMock()
            broken_soniox.start = AsyncMock(side_effect=RuntimeError("soniox down"))

            events: list[dict] = []

            async def _sink(m: dict) -> None:
                events.append(m)

            with (
                patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=broken_stt),
                patch("noble_agent.voice.stt.remote.RemoteSTT", return_value=broken_remote),
                patch("noble_agent.voice.stt.soniox.SonioxSTT", return_value=broken_soniox),
                patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
            ):
                from noble_agent.server.base_session import BaseSession

                s = BaseSession("sid-34")
                s._event_sink = _sink
                await s.start()

                assert s.stt is None
                assert any(e.get("type") == "error" for e in events)


class TestStartSTTFallback:
    async def test_init_stt_falls_back_to_soniox(self) -> None:
        """sherpa + remote start() raise → soniox selected; no error event fired.

        Chain is remote → soniox → sherpa; with stt_backend=sherpa the order is
        sherpa → remote → soniox, so both must fail to reach soniox.
        """
        async with _patched_collaborators() as cols:
            cols["settings"].stt_backend = "sherpa"
            cols["settings"].tts_backend = "vieneu"

            broken_sherpa = AsyncMock()
            broken_sherpa.start = AsyncMock(side_effect=RuntimeError("sherpa down"))
            broken_remote = AsyncMock()
            broken_remote.start = AsyncMock(side_effect=RuntimeError("stt service down"))
            good_soniox = AsyncMock()

            events: list[dict] = []

            async def _sink(m: dict) -> None:
                events.append(m)

            with (
                patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=broken_sherpa),
                patch("noble_agent.voice.stt.remote.RemoteSTT", return_value=broken_remote),
                patch("noble_agent.voice.stt.soniox.SonioxSTT", return_value=good_soniox),
                patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
            ):
                from noble_agent.server.base_session import BaseSession

                s = BaseSession("sid-fb-1")
                s._event_sink = _sink
                await s.start()

                assert s.stt.inner is good_soniox
                good_soniox.start.assert_awaited_once()
                assert not any(e.get("type") == "error" for e in events)

    async def test_init_stt_chain_exhausted(self) -> None:
        """All of sherpa + remote + soniox start() raise → stt None + one error event."""
        async with _patched_collaborators() as cols:
            cols["settings"].stt_backend = "sherpa"
            cols["settings"].tts_backend = "vieneu"

            broken_sherpa = AsyncMock()
            broken_sherpa.start = AsyncMock(side_effect=RuntimeError("sherpa down"))
            broken_remote = AsyncMock()
            broken_remote.start = AsyncMock(side_effect=RuntimeError("stt service down"))
            broken_soniox = AsyncMock()
            broken_soniox.start = AsyncMock(side_effect=RuntimeError("soniox down"))

            events: list[dict] = []

            async def _sink(m: dict) -> None:
                events.append(m)

            with (
                patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=broken_sherpa),
                patch("noble_agent.voice.stt.remote.RemoteSTT", return_value=broken_remote),
                patch("noble_agent.voice.stt.soniox.SonioxSTT", return_value=broken_soniox),
                patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
            ):
                from noble_agent.server.base_session import BaseSession

                s = BaseSession("sid-fb-2")
                s._event_sink = _sink
                await s.start()

                assert s.stt is None
                error_events = [e for e in events if e.get("type") == "error"]
                assert len(error_events) == 1

    async def test_init_stt_non_chain_primary_unchanged(self) -> None:
        """qwen3asr (not in chain) → single attempt, no fallback."""
        async with _patched_collaborators() as cols:
            cols["settings"].stt_backend = "qwen3asr"
            cols["settings"].tts_backend = "vieneu"

            good_qwen = AsyncMock()
            soniox_built = 0

            def _soniox(*_a, **_kw):
                nonlocal soniox_built
                soniox_built += 1
                return AsyncMock()

            with (
                patch("noble_agent.voice.stt.qwen3asr.Qwen3ASRSTT", return_value=good_qwen),
                patch("noble_agent.voice.stt.soniox.SonioxSTT", side_effect=_soniox),
                patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
            ):
                from noble_agent.server.base_session import BaseSession

                s = BaseSession("sid-fb-3")
                await s.start()

                assert s.stt.inner is good_qwen
                assert soniox_built == 0


class TestStartPipelineErrorSwallowed:
    async def test_exception_in_iterator_is_swallowed(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-35")
            s.stt = None

            async def _bad() -> AsyncIterator[bytes]:
                yield b"\x00\x00"
                raise RuntimeError("upstream died")

            out = _FakeAudioOutput()
            # Must not raise — BaseSession absorbs so the transport teardown can run.
            await s.start_pipeline(_bad(), out)


class TestFramesGate:
    """Phase 4.2 — SttInputGate wiring in BaseSession."""

    async def test_gate_off_mode_passes_all_frames(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            # Default settings: stt_input_gate_mode = "off" → passthrough.
            s = BaseSession("sid-gate-1")
            s.stt = AsyncMock()
            await s.process_audio_frame(b"\x00\x00" * 256)
            s.stt.send.assert_awaited()

    async def test_gate_rms_mode_drops_unconfirmed_frames(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].stt_input_gate_mode = "rms"
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-gate-2")
            s.stt = AsyncMock()
            # Inject a gate stub that never passes through.
            gate_stub = MagicMock(spec=SttInputGate)
            gate_stub.mode = "rms"
            gate_stub.gate.return_value = []
            gate_stub.keepalive.return_value = None
            s._input_gate = gate_stub

            await s.process_audio_frame(b"\x00\x00" * 256)
            s.stt.send.assert_not_awaited()

    async def test_gate_rms_mode_passes_once_confirmed(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].stt_input_gate_mode = "rms"
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            data = b"\x00\x00" * 256
            s = BaseSession("sid-gate-3")
            s.stt = AsyncMock()
            gate_stub = MagicMock(spec=SttInputGate)
            gate_stub.mode = "rms"
            gate_stub.gate.return_value = [data]
            s._input_gate = gate_stub

            await s.process_audio_frame(data)
            s.stt.send.assert_awaited()


# ----------------------------------------------------------------------
# Speaker tracker wiring in _on_final (parallel SPV engine, spec 2026-08-28)
# ----------------------------------------------------------------------


class TestSpeakerVerificationWiring:
    async def test_disabled_means_no_tracker_and_agent_proceeds(self) -> None:
        """speaker_mode=off → _speaker_tracker is None; agent triggers."""
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "off"

            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-spk-1")
            assert s._speaker_tracker is None

            triggered: list[str] = []

            async def _fake_trigger(t: str) -> None:
                triggered.append(t)

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("hello")
            assert triggered == ["hello"]


class TestSmartTurnHold:
    async def test_low_probability_pends_final_and_arms_timer(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            fake_turn = MagicMock()
            fake_turn.predict.return_value = {"probability": 0.0}

            s = BaseSession("sid-36")
            s._smart_turn = fake_turn
            s._audio_ring.extend(b"\x00\x00" * 100)

            triggered: list[str] = []

            async def _fake_trigger(t: str) -> None:
                triggered.append(t)

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("hold me")
            # low probability → held, not dispatched
            assert triggered == []
            assert s._pending_finals == ["hold me"]
            assert s._hold_timer is not None
            s._cancel_hold_timer()

    async def test_high_probability_flushes_pending_and_dispatches(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            fake_turn = MagicMock()
            fake_turn.predict.return_value = {"probability": 0.99}

            s = BaseSession("sid-37")
            s._smart_turn = fake_turn
            s._audio_ring.extend(b"\x00\x00" * 100)
            s._pending_finals = ["prev"]

            captured: list[str] = []

            async def _fake_trigger(t: str) -> None:
                captured.append(t)

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("now")
            assert captured == ["prev now"]
            assert s._pending_finals == []


# ----------------------------------------------------------------------
# SpeakerTracker feed wiring in process_audio_frame (spec 2026-08-28)
# ----------------------------------------------------------------------


class TestSpeakerTrackerFeed:
    async def test_chunks_are_fed_to_tracker(self) -> None:
        """Chunks forwarded to STT are also fed to the speaker tracker."""
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "single"

            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-pcm-1")
            gate_stub = MagicMock(spec=SttInputGate)
            gate_stub.mode = "off"
            chunk_a = b"\x01\x02" * 32
            chunk_b = b"\x03\x04" * 32
            gate_stub.gate.side_effect = [[chunk_a], [chunk_b]]
            s._input_gate = gate_stub
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            s._speaker_tracker.feed = MagicMock()

            await s.process_audio_frame(b"\x00" * 64)
            await s.process_audio_frame(b"\x00" * 64)

            assert [c.args[0] for c in s._speaker_tracker.feed.call_args_list] == [chunk_a, chunk_b]

    async def test_new_utterance_calls_begin_utterance_once(self) -> None:
        """begin_utterance fires on the first chunk of each utterance only."""
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "single"

            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-pcm-2")
            gate_stub = MagicMock(spec=SttInputGate)
            gate_stub.mode = "off"
            gate_stub.gate.return_value = [b"\xff\xfe" * 32]
            s._input_gate = gate_stub
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            s._speaker_tracker.begin_utterance = MagicMock()

            await s.process_audio_frame(b"\x00" * 64)
            await s.process_audio_frame(b"\x00" * 64)  # same utterance → no re-begin
            assert s._speaker_tracker.begin_utterance.call_count == 1

            s._stt_audio_start = 0.0  # utterance finalized
            await s.process_audio_frame(b"\x00" * 64)
            assert s._speaker_tracker.begin_utterance.call_count == 2

    async def test_no_tracker_when_speaker_mode_off(self) -> None:
        """Zero cost: speaker_mode=off builds no tracker at all."""
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "off"

            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-pcm-4")
            assert s._speaker_tracker is None

            gate_stub = MagicMock(spec=SttInputGate)
            gate_stub.mode = "off"
            gate_stub.gate.return_value = [b"\xab\xcd" * 32]
            s._input_gate = gate_stub
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()

            await s.process_audio_frame(b"\x00" * 64)  # must not raise

    async def test_spv_embed_passes_span_to_embedder(self) -> None:
        """_spv_embed embeds exactly the span it is handed (not the ring)."""
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "single"

            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-pcm-5")
            s._audio_ring = bytearray(b"\x99\x88" * 800)  # decoy
            span = b"\x11\x22" * 400

            embedded: list[bytes] = []
            fake_emb = MagicMock()
            fake_emb.embed.side_effect = lambda seg: embedded.append(seg) or MagicMock()

            with patch("noble_agent.server.base_session.SpeakerEmbedder") as MockEmbedder:
                MockEmbedder.get_instance.return_value = fake_emb
                await s._spv_embed(span)

            assert embedded == [span]

    async def test_spv_embed_returns_none_on_embedder_error(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "single"

            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-pcm-6")
            fake_emb = MagicMock()
            fake_emb.embed.side_effect = RuntimeError("boom")

            with patch("noble_agent.server.base_session.SpeakerEmbedder") as MockEmbedder:
                MockEmbedder.get_instance.return_value = fake_emb
                assert await s._spv_embed(b"\x11\x22" * 400) is None

    async def test_spv_embed_empty_span_is_none(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "single"

            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-pcm-7")
            assert await s._spv_embed(b"") is None


# ----------------------------------------------------------------------
# VAD INTERRUPTED routing when the tracker owns barge-in (spec 2026-08-28)
# ----------------------------------------------------------------------


class TestInterruptRouting:
    async def test_off_mode_vad_interrupted_calls_handle_interrupt_immediately(self) -> None:
        """Regression: speaker_mode=off (no tracker) → VAD INTERRUPTED still calls
        _handle_interrupt immediately."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import (
                VAD_CHUNK_BYTES,
                BaseSession,
            )
            from noble_agent.voice.vad import VADState

            cols["settings"].speaker_mode = "off"
            cols["vad"].process_chunk.return_value = {"state": VADState.INTERRUPTED}

            s = BaseSession("sid-int-3")
            assert s._speaker_tracker is None
            s.stt = None
            s._audio_output = _FakeAudioOutput()

            async def _long() -> None:
                await asyncio.sleep(10)

            s._agent_task = asyncio.create_task(_long())
            s._handle_interrupt = AsyncMock()

            await s.process_audio_frame(b"\x00" * VAD_CHUNK_BYTES)

            s._handle_interrupt.assert_awaited_once()

            s._agent_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await s._agent_task

    async def test_tracker_mode_vad_interrupted_only_rearms_vad(self) -> None:
        """Tracker present → INTERRUPTED never hard-interrupts nor opens an
        addressee episode; it only keeps the VAD state machine alive so the next
        chunk verdict can decide."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import (
                VAD_CHUNK_BYTES,
                BaseSession,
            )
            from noble_agent.voice.vad import VADState

            cols["settings"].speaker_mode = "multi"
            cols["settings"].addressee_gate_mode = "llm"
            cols["vad"].process_chunk.return_value = {"state": VADState.INTERRUPTED}

            s = BaseSession("sid-int-4")
            s.stt = None
            s._audio_output = _FakeAudioOutput()

            async def _long() -> None:
                await asyncio.sleep(10)

            s._agent_task = asyncio.create_task(_long())
            s._handle_interrupt = AsyncMock()

            await s.process_audio_frame(b"\x00" * VAD_CHUNK_BYTES)

            s._handle_interrupt.assert_not_awaited()
            assert s._addr_episode_active is False
            cols["vad"].set_speaking.assert_called()

            s._agent_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await s._agent_task


# ----------------------------------------------------------------------
# Gate keepalive: synthetic silence so STT endpoint fires when gate closed
# ----------------------------------------------------------------------


class TestGateKeepalive:
    """Silence keepalive: gate-closed frames feed STT so the endpoint fires."""

    async def test_keepalive_silence_sent_when_gate_closed(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka1")
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            gate = MagicMock(spec=SttInputGate)
            gate.mode = "vad"
            gate.gate.return_value = []  # withheld
            gate.keepalive.return_value = b"\x00" * 320
            s._input_gate = gate

            await s.process_audio_frame(b"\x00" * 320)

            gate.keepalive.assert_called_once_with(320)
            s.stt.send.assert_awaited_once_with(b"\x00" * 320)

    async def test_no_send_when_keepalive_returns_none(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka2")
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            gate = MagicMock(spec=SttInputGate)
            gate.mode = "vad"
            gate.gate.return_value = []
            gate.keepalive.return_value = None
            s._input_gate = gate

            await s.process_audio_frame(b"\x00" * 320)

            s.stt.send.assert_not_awaited()

    async def test_keepalive_silence_not_fed_to_speaker_tracker(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka3")
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            s._speaker_tracker.feed = MagicMock()
            gate = MagicMock(spec=SttInputGate)
            gate.mode = "vad"
            real = b"\x11\x11" * 160
            gate.gate.side_effect = [[real], []]  # frame 1 real, frame 2 withheld
            gate.keepalive.return_value = b"\x00" * 320
            s._input_gate = gate

            await s.process_audio_frame(real)  # real audio → fed to the tracker
            await s.process_audio_frame(b"\x00" * 320)  # withheld → keepalive silence

            assert [c.args[0] for c in s._speaker_tracker.feed.call_args_list] == [real]

    async def test_on_final_calls_notify_final(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka4")
            gate = MagicMock(spec=SttInputGate)
            s._input_gate = gate

            async def _fake_trigger(t: str) -> None:
                return None

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("hello there")

            gate.notify_final.assert_called_once()


# ----------------------------------------------------------------------
# Addressee gate (chống nói leo)
# ----------------------------------------------------------------------


def _speech_chunk_result(is_speech: bool = True, state="speaking"):
    return {"state": state, "is_speech": is_speech, "speech_prob": 0.9, "state_changed": False}


class TestAddresseeGate:
    async def test_gate_off_interrupts_immediately(self) -> None:
        """Mode off: VAD INTERRUPTED → _handle_interrupt như cũ, không episode."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession, VADState

            cols["settings"].addressee_gate_mode = "off"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            cols["vad"].process_chunk.return_value = {
                "state": VADState.INTERRUPTED, "is_speech": True, "speech_prob": 0.9, "state_changed": True,
            }
            await s.process_audio_frame(b"\x00" * 1024)
            cols["agent"].pause_playback.assert_not_called()
            await asyncio.sleep(0)  # let task.cancel() propagate
            assert s._agent_task.cancelled() or s._agent_task.done()

    async def test_sustained_speech_soft_pauses(self) -> None:
        """Gate on: INTERRUPTED mở episode; speech đủ 400ms → pause_playback,
        KHÔNG cancel agent task."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession, VADState

            cols["settings"].addressee_gate_mode = "hybrid"
            cols["settings"].addressee_min_speech_ms = 400
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            fake_out = _FakeAudioOutput()
            s._audio_output = fake_out
            # 1 chunk INTERRUPTED mở episode + ~13 chunk speech (416ms)
            cols["vad"].process_chunk.return_value = {
                "state": VADState.INTERRUPTED, "is_speech": True, "speech_prob": 0.9, "state_changed": True,
            }
            await s.process_audio_frame(b"\x00" * 1024)
            cols["vad"].process_chunk.return_value = _speech_chunk_result(True)
            for _ in range(13):
                await s.process_audio_frame(b"\x00" * 1024)
            cols["agent"].pause_playback.assert_called_once()
            assert fake_out.clears >= 1
            assert not s._agent_task.done()  # soft — turn còn sống
            s._agent_task.cancel()

    async def test_paused_final_side_talk_resumes_and_drops(self) -> None:
        """Amendment đêm 2026-08-12: verdict giờ quyết trên FINAL, không còn
        classify trên partial. Paused + final classify → SIDE_TALK → resume,
        final bị drop (agent task vẫn là task đang ngủ ban đầu, không bị
        cancel/retrigger), ring không bị đụng tới."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            original_task = s._agent_task
            s._addr_paused = True
            s._addr_episode_active = True
            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ):
                await s._on_final("con ơi ăn cơm đi")
            cols["agent"].resume_playback.assert_called_once()
            assert s._agent_task is original_task
            assert not s._agent_task.done()
            assert list(s._dialogue_ring) == []
            assert s._addr_paused is False
            s._agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await s._agent_task

    async def test_paused_final_directed_commits_and_triggers(self) -> None:
        """Paused + final classify → DIRECTED → commit interrupt (đường
        `_handle_interrupt` cũ) rồi trigger MỘT turn mới với chính final đó."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            original_task = s._agent_task
            s._addr_paused = True
            s._addr_episode_active = True

            captured: list[str] = []

            async def _capture(t: str) -> None:
                captured.append(t)

            s._run_agent = _capture  # type: ignore[method-assign]

            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.DIRECTED),
            ):
                await s._on_final("em ơi cho anh hỏi giá")

            cols["agent"].pause_tts.assert_awaited()  # _handle_interrupt đường cũ
            assert s._agent_task is not original_task  # turn mới được trigger
            await s._agent_task
            assert captured == ["em ơi cho anh hỏi giá"]
            assert s._addr_episode_verdict is None

    async def test_paused_final_mixed_sentence_directed(self) -> None:
        """Prompt-rule doc test: câu hỗn hợp (side-talk + nội dung hướng tới
        agent trong cùng câu) → DIRECTED. Rule thật nằm trong _LLM_PROMPT; ở
        mức session này chỉ verify plumbing khi classify() trả DIRECTED cho
        câu dạng đó — cùng assertions như test directed thuần."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            original_task = s._agent_task
            s._addr_paused = True
            s._addr_episode_active = True

            captured: list[str] = []

            async def _capture(t: str) -> None:
                captured.append(t)

            s._run_agent = _capture  # type: ignore[method-assign]

            mixed_text = "con đi ăn cơm ngay cho bố, bên em giá căn hộ như thế nào"
            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.DIRECTED),
            ):
                await s._on_final(mixed_text)

            cols["agent"].pause_tts.assert_awaited()
            assert s._agent_task is not original_task
            await s._agent_task
            assert captured == [mixed_text]
            assert s._addr_episode_verdict is None

    async def test_deadline_uses_max_pause_ms(self) -> None:
        """`_addr_deadline_s()` giờ đọc trực tiếp ADDRESSEE_MAX_PAUSE_MS, không
        còn công thức llm_timeout+1s."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["settings"].addressee_max_pause_ms = 1234
            s = BaseSession("sid")
            assert s._addr_deadline_s() == 1.234

    async def test_final_classify_races_live_deadline_falls_through_directed(self) -> None:
        """IMPORTANT-1 regression (review round 1): the deadline can fire
        WHILE the inline classify is in flight (awaiting the LLM) and
        resolve the SAME episode itself (fail-open DIRECTED commit) before
        our verdict lands. The epoch-guard must detect that and NOT take
        the SIDE_TALK arm — the deadline's commit is authoritative; the
        final proceeds as a normal (already-interrupted) turn instead of
        being dropped into dead air, and the cached DIRECTED must not leak
        into the next final."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            s._addr_paused = True
            s._addr_episode_active = True

            captured: list[str] = []

            async def _capture(t: str) -> None:
                captured.append(t)

            s._run_agent = _capture  # type: ignore[method-assign]

            async def _classify_races_deadline(*_args, **_kwargs):
                # Simulates the deadline timer firing WHILE this classify
                # call is still in flight — it resolves (and commits) the
                # SAME episode before we return our own (now-stale) verdict.
                await s._addressee_deadline()
                return Verdict.SIDE_TALK

            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(side_effect=_classify_races_deadline),
            ):
                await s._on_final("anh ơi con khóc kìa")

            cols["agent"].pause_tts.assert_awaited_once()  # committed exactly once (by the deadline)
            await s._agent_task  # let the new turn (stubbed _run_agent) finish
            assert captured == ["anh ơi con khóc kìa"]  # final proceeded, not dropped
            assert s._addr_episode_verdict is None  # not leaked to the next final
            cols["agent"].resume_playback.assert_not_called()  # SIDE_TALK arm never taken

    async def test_final_while_speaking_no_verdict_classifies_inline(self) -> None:
        """Final đến khi agent đang nói mà chưa có verdict (câu ngắn dưới
        duration gate) → classify tại chỗ; SIDE_TALK → drop + agent nói tiếp."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ):
                await s._on_final("ừ đúng đấy")
            cols["vad"].set_speaking.assert_called()
            assert not s._agent_task.done()  # agent không bị cancel
            assert list(s._dialogue_ring) == []  # dropped final never enters the ring
            s._agent_task.cancel()

    async def test_deadline_fail_open_commits_interrupt(self) -> None:
        """Không có text trong hạn → DIRECTED fail-open (commit interrupt)."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            s._addr_paused = True
            s._addr_episode_active = True
            await s._addressee_deadline()
            cols["agent"].pause_tts.assert_awaited()
            await asyncio.sleep(0)  # let task.cancel() propagate
            assert s._agent_task.cancelled() or s._agent_task.done()

    # ------------------------------------------------------------------
    # Review round 1: race fix + strong-ref fix + wiring coverage
    # ------------------------------------------------------------------

    async def test_on_partial_only_sends_event(self) -> None:
        """Amendment đêm 2026-08-12: `_on_partial` không còn spawn classify —
        chỉ forward partial_transcript event, kể cả khi đang paused."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._addr_paused = True

            classify_mock = AsyncMock()
            with patch("noble_agent.server.base_session.addressee_gate.classify", new=classify_mock):
                await s._on_partial("anh ơi con khóc kìa nữa luôn")

            classify_mock.assert_not_awaited()
            assert not s._bg_tasks

    async def test_tracker_takes_priority_over_addressee_episode(self) -> None:
        """speaker_mode=multi (tracker present): INTERRUPTED does NOT open an
        addressee episode — the tracker's chunk verdict owns barge-in routing
        now, so the VAD is merely kept alive (elif ordering in
        process_audio_frame)."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession, VADState

            cols["settings"].speaker_mode = "multi"
            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            begin_addressee_called = []
            s._begin_addressee_episode = lambda: begin_addressee_called.append(True)  # type: ignore[method-assign]
            cols["vad"].process_chunk.return_value = {
                "state": VADState.INTERRUPTED, "is_speech": True, "speech_prob": 0.9, "state_changed": True,
            }
            await s.process_audio_frame(b"\x00" * 1024)
            assert s._addr_episode_active is False
            assert begin_addressee_called == []  # routing never calls the idle-branch opener
            cols["vad"].set_speaking.assert_called()
            s._agent_task.cancel()

    async def test_episode_silence_resets_without_pausing(self) -> None:
        """Episode active, speech never reaches the soft-pause threshold and
        silence runs past silence_reset_ms → episode drops, VAD re-armed for
        a fresh barge-in, agent never paused."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession, VADState

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            cols["vad"].process_chunk.return_value = {
                "state": VADState.INTERRUPTED, "is_speech": True, "speech_prob": 0.9, "state_changed": True,
            }
            await s.process_audio_frame(b"\x00" * 1024)  # opens the episode
            assert s._addr_episode_active is True
            set_speaking_calls_after_open = cols["vad"].set_speaking.call_count

            cols["vad"].process_chunk.return_value = _speech_chunk_result(False, state="listening")
            for _ in range(10):  # 10 * vad_chunk_ms(32) = 320ms >= silence_reset_ms default
                await s.process_audio_frame(b"\x00" * 1024)

            assert s._addr_episode_active is False
            assert cols["vad"].set_speaking.call_count > set_speaking_calls_after_open
            cols["agent"].pause_playback.assert_not_called()
            s._agent_task.cancel()

    async def test_stop_cancels_addressee_deadline(self) -> None:
        """stop()'s teardown (_addr_reset_episode) must cancel the armed
        deadline TimerHandle, not just drop the reference (repo strong-ref
        gotcha's sibling: an armed but un-cancelled timer keeps firing)."""
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession

            with (
                patch("noble_agent.storage.session_store.load_customer", new_callable=AsyncMock, return_value={}),
            ):
                s = BaseSession("sid")
                s.stt = AsyncMock()
                s._audio_output = _FakeAudioOutput()
                handle = MagicMock()
                s._addr_deadline_handle = handle
                await s.stop()

                handle.cancel.assert_called_once()
                assert s._addr_deadline_handle is None

    async def test_final_no_verdict_idle_proceeds_to_trigger_agent(self) -> None:
        """Agent not speaking, no cached verdict, when_idle False → gate is a
        pure no-op: final proceeds to _trigger_agent_for_text and
        _last_user_text updates."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["settings"].addressee_gate_mode = "hybrid"
            cols["settings"].addressee_gate_when_idle = False
            s = BaseSession("sid")
            captured: list[str] = []

            async def _capture(t: str) -> None:
                captured.append(t)

            s._run_agent = _capture  # type: ignore[method-assign]

            await s._on_final("khi nào bàn giao nhà")
            await s._agent_task  # type: ignore[union-attr]

            assert s._agent_task is not None
            assert s._last_user_text == "khi nào bàn giao nhà"
            assert captured == ["khi nào bàn giao nhà"]

    async def test_paused_but_turn_finished_naturally_final_still_classifies(self) -> None:
        """Edge case (amendment đêm 2026-08-12): pause chớm lúc turn vừa kết
        thúc tự nhiên race với pacer — `_agent_task` đã done nhưng
        `_addr_paused` vẫn True. `_on_final` PHẢI vẫn classify (không bỏ qua
        vì `_agent_is_speaking()` đã False) để side-talk không lọt thành turn
        mới. Review round 1: MINOR-2 (vad.set_speaking() phải KHÔNG được gọi
        khi turn không còn sống — agent không "đang nói") + MINOR-3 (idle
        countdown mà turn's finally đã bắn, rồi bị `_on_final`'s entry
        `_reset_idle()` hủy, phải được restart lại chứ không rơi mất)."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")

            async def _already_done() -> None:
                return None

            s._agent_task = asyncio.ensure_future(_already_done())
            await s._agent_task  # turn finished naturally before the final arrived
            assert s._agent_task.done()

            s._addr_paused = True  # leaked pause from the race
            s._addr_episode_active = True

            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ) as mock_classify:
                await s._on_final("con ơi ăn cơm đi")

            mock_classify.assert_awaited_once()  # classified despite agent not "speaking"
            cols["agent"].resume_playback.assert_called_once()
            assert s._addr_paused is False
            cols["vad"].set_speaking.assert_not_called()  # MINOR-2: not "speaking" → no re-arm
            assert s._idle_timer is not None  # MINOR-3: idle countdown restarted, not dropped
            s._idle_timer.cancel()


# ----------------------------------------------------------------------
# Dialogue ring (2026-08-12 chiều amendment) — context for the addressee
# LLM verdict: user text on accepted final, prior agent text on new-turn
# trigger, SIDE_TALK-dropped finals never enter the ring.
# ----------------------------------------------------------------------


class TestAddresseeDialogueRing:
    async def test_trigger_agent_appends_prior_agent_text_then_user_text(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-ring-1")
            cols["agent"].spoken_text_this_turn = "Dạ dự án này ở quận 2 ạ."

            async def _noop_run(_text: str) -> None:
                return None

            s._run_agent = _noop_run  # type: ignore[method-assign]

            await s._trigger_agent_for_text("giá bao nhiêu vậy")
            await s._agent_task  # type: ignore[union-attr]

            assert list(s._dialogue_ring) == [
                ("agent", "Dạ dự án này ở quận 2 ạ."),
                ("user", "giá bao nhiêu vậy"),
            ]

    async def test_trigger_agent_skips_empty_prior_agent_text(self) -> None:
        """No prior turn (or the agent never spoke, e.g. the very first
        turn) → `spoken_text_this_turn` is "" → only the user entry lands."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-ring-2")
            cols["agent"].spoken_text_this_turn = ""

            async def _noop_run(_text: str) -> None:
                return None

            s._run_agent = _noop_run  # type: ignore[method-assign]

            await s._trigger_agent_for_text("chào em")
            await s._agent_task  # type: ignore[union-attr]

            assert list(s._dialogue_ring) == [("user", "chào em")]

    async def test_final_inline_classify_while_paused_passes_recent_dialogue_and_spoken_text(self) -> None:
        """The inline classify branch of `_on_final` also fires while the
        gate is soft-paused (not just while `_agent_is_speaking()`) — same
        ring + spoken-text context must reach `classify()`."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid-ring-4")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            s._addr_paused = True
            s._addr_episode_active = True
            s._dialogue_ring.append(("user", "trước đó khách hỏi gì đó"))
            cols["agent"].spoken_text_this_turn = "em đang nói dở câu này"

            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ) as mock_classify:
                await s._on_final("em ơi cho anh hỏi giá")

            _, kwargs = mock_classify.call_args
            assert kwargs["recent_dialogue"] == (("user", "trước đó khách hỏi gì đó"),)
            assert kwargs["agent_line"] == "em đang nói dở câu này"

            s._agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await s._agent_task

    async def test_on_final_inline_classify_passes_recent_dialogue_and_spoken_text(self) -> None:
        """The inline classify branch of `_on_final` (short utterance, no
        cached verdict yet) forwards the same ring + spoken-text context."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid-ring-5")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            s._dialogue_ring.append(("user", "câu trước"))
            cols["agent"].spoken_text_this_turn = "câu agent đang nói"

            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ) as mock_classify:
                await s._on_final("ừ đúng đấy")

            _, kwargs = mock_classify.call_args
            assert kwargs["recent_dialogue"] == (("user", "câu trước"),)
            assert kwargs["agent_line"] == "câu agent đang nói"

            s._agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await s._agent_task

    async def test_idle_branch_classify_passes_recent_dialogue_and_spoken_text(self) -> None:
        """Review round 1, Important finding: the `addressee_gate_when_idle`
        branch (agent not speaking) must ALSO forward `recent_dialogue` and
        `agent_line` — at this point `spoken_text_this_turn` still holds the
        just-finished turn's text (handle_utterance only resets it at the
        NEXT turn's start), which is exactly the context this verdict needs."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            cols["settings"].addressee_gate_when_idle = True
            s = BaseSession("sid-ring-6")
            s._dialogue_ring.append(("user", "câu trước"))
            cols["agent"].spoken_text_this_turn = "câu agent vừa nói xong"

            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.DIRECTED),
            ) as mock_classify:
                await s._on_final("nói với ai đó bên cạnh")
                await s._agent_task  # type: ignore[union-attr]

            _, kwargs = mock_classify.call_args
            assert kwargs["recent_dialogue"] == (("user", "câu trước"),)
            assert kwargs["agent_line"] == "câu agent vừa nói xong"


# ----------------------------------------------------------------------
# Final-review wave: VAD-latch starvation (CRITICAL-1) + stale deadline
# on new turn (IMPORTANT-2)
# ----------------------------------------------------------------------


class _LatchingFakeVAD:
    """Faithful replica of the REAL SileroVAD's INTERRUPTED-latch semantics
    (`voice/vad/silero.py::_update_state`): once in INTERRUPTED there is NO
    exit transition — every subsequent chunk keeps returning INTERRUPTED
    until `set_speaking()` / `set_idle()` is called explicitly. A plain
    MagicMock (as used by `_patched_collaborators`) does NOT reproduce this —
    it just returns whatever `process_chunk.return_value` was last set to,
    which is why the production bug this regression covers slipped past the
    existing addressee-gate tests.

    Starts in SPEAKING (agent is mid-turn); every chunk is speech, matching
    the "khách nói leo liên tục" scenario the gate exists to catch.
    """

    def __init__(self, confirm_chunks: int = 3) -> None:
        from noble_agent.voice.vad import VADState

        self._VADState = VADState
        self._confirm_chunks = confirm_chunks
        self.state = VADState.SPEAKING
        self._interrupt_chunks = 0
        self.speaking_resets = 0

    def process_chunk(self, _chunk: bytes) -> dict:
        is_speech = True
        if self.state == self._VADState.SPEAKING:
            self._interrupt_chunks += 1
            if self._interrupt_chunks >= self._confirm_chunks:
                self.state = self._VADState.INTERRUPTED
                self._interrupt_chunks = 0
        # INTERRUPTED: latched — no exit transition (mirrors the real bug).
        return {"state": self.state, "is_speech": is_speech, "speech_prob": 0.9, "state_changed": False}

    def set_speaking(self) -> None:
        self.state = self._VADState.SPEAKING
        self._interrupt_chunks = 0
        self.speaking_resets += 1

    def set_idle(self) -> None:
        self.state = self._VADState.IDLE
        self._interrupt_chunks = 0


class TestAddresseeGateVADLatchRegression:
    async def test_latching_vad_does_not_starve_episode_tracker(self) -> None:
        """CRITICAL-1: with the real VAD's INTERRUPTED-latch behavior, ~20
        consecutive speech chunks over an agent turn must still cross the
        400ms soft-pause threshold and call `agent.pause_playback()`.

        Pre-fix routing (`if INTERRUPTED: ... elif episode_active: feed
        tracker`) makes this FAIL: `_begin_addressee_episode()` re-arms the
        VAD to SPEAKING exactly once, the latching fake (like the real VAD)
        re-fires INTERRUPTED after `vad_interrupt_confirm_chunks` more speech
        chunks, then latches forever — every later chunk takes the
        INTERRUPTED branch (episode already active → no-op early return) and
        the tracker is never fed again, frozen at the ~96ms preload from
        `_begin_addressee_episode`, well under the 400ms threshold.
        """
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import VAD_CHUNK_BYTES, BaseSession

            cols["settings"].addressee_gate_mode = "hybrid"
            cols["settings"].addressee_min_speech_ms = 400
            cols["settings"].vad_interrupt_confirm_chunks = 3
            s = BaseSession("sid-vad-latch")
            s.stt = None
            s._audio_output = _FakeAudioOutput()
            s.vad = _LatchingFakeVAD(confirm_chunks=3)

            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))

            for _ in range(20):
                await s.process_audio_frame(b"\x00" * VAD_CHUNK_BYTES)

            cols["agent"].pause_playback.assert_called_once()
            assert not s._agent_task.done()  # soft-pause, turn stays alive
            s._agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await s._agent_task


class TestAddresseeGateStaleDeadlineOnNewTurn:
    async def test_trigger_agent_resets_stale_paused_episode(self) -> None:
        """IMPORTANT-2: a paused episode from a turn that ended naturally
        (no `_addr_reset_episode()` call — e.g. `_READY_END`) must not
        survive into the NEXT turn. `_trigger_agent_for_text` must reset the
        episode (cancelling any armed deadline) before starting the new
        turn, so a stale deadline can never fire mid-turn and cancel it."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid-stale-deadline")

            async def _noop_run(_text: str) -> None:
                await asyncio.sleep(10)

            s._run_agent = _noop_run  # type: ignore[method-assign]

            # Simulate the leaked state: paused + a real armed deadline timer.
            s._addr_paused = True
            s._addr_episode_active = True
            loop = asyncio.get_running_loop()
            fired: list[bool] = []
            handle = loop.call_later(10, lambda: fired.append(True))
            s._addr_deadline_handle = handle

            await s._trigger_agent_for_text("câu hỏi hợp lệ ở lượt mới")

            assert handle.cancelled()
            assert s._addr_paused is False
            assert s._addr_episode_active is False

            s._agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await s._agent_task


# ----------------------------------------------------------------------
# Parallel speaker verification (spec 2026-08-28)
# ----------------------------------------------------------------------


class TestParallelSpeakerVerdict:
    """Spec 2026-08-28: verdict per-chunk điều khiển interrupt + drop final."""

    async def test_speaker_verdict_while_agent_speaking_interrupts(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("speaker", 0.9, 0)
            session._handle_interrupt.assert_awaited_once()
            session._agent_task.cancel()

    async def test_speaker_verdict_routes_via_addressee_gate_when_enabled(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            c["settings"].addressee_gate_mode = "llm"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._begin_addressee_pause_from_floor = AsyncMock()
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("speaker", 0.9, 0)
            session._begin_addressee_pause_from_floor.assert_awaited_once()
            session._handle_interrupt.assert_not_awaited()
            session._agent_task.cancel()

    async def test_non_speaker_verdict_keeps_agent_talking(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("non-speaker", 0.1, 0)
            session._handle_interrupt.assert_not_awaited()
            c["vad"].set_speaking.assert_called()
            session._agent_task.cancel()

    async def test_unknown_verdict_never_interrupts(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("unknown", float("nan"), 0)
            session._handle_interrupt.assert_not_awaited()
            session._agent_task.cancel()

    async def test_speaker_verdict_while_already_paused_is_noop(self) -> None:
        """Đã soft-pause rồi: verdict speaker kế tiếp KHÔNG re-arm deadline/
        pause lần hai — classifier của final mới là người quyết."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            c["settings"].addressee_gate_mode = "llm"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._addr_paused = True
            session._begin_addressee_pause_from_floor = AsyncMock()
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("speaker", 0.9, 1)
            session._begin_addressee_pause_from_floor.assert_not_awaited()
            session._handle_interrupt.assert_not_awaited()
            session._agent_task.cancel()

    async def test_verdict_when_agent_idle_is_noop(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("speaker", 0.9, 0)
            session._handle_interrupt.assert_not_awaited()


def _verdict(identity=None, is_new=False, cluster=2, sim=0.9, labels=None):
    return UtteranceVerdict(
        identity=identity,
        is_new=is_new,
        cluster_size=cluster,
        best_sim=sim,
        probe_labels=labels or ["speaker"],
    )


class TestFinalDropRule:
    async def test_first_utterance_of_call_is_never_dropped(self) -> None:
        """Nhánh 1: khách ngắt auto-greeting — chưa ai giữ lượt nên floor mở.
        Bản nháp spec từng drop đúng ca này."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop1")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=7, is_new=True))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("bên em có dự án gì")
            session._trigger_agent_for_text.assert_awaited_once()
            session._agent_task.cancel()

    async def test_asker_final_is_kept_and_streak_resets(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop2")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            session._mismatch_streak = 1
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=ident))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("cho anh hỏi thêm")
            session._trigger_agent_for_text.assert_awaited_once()
            assert session._mismatch_streak == 0
            session._agent_task.cancel()

    async def test_other_identity_mid_turn_is_dropped(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop3")
            reg = session._speaker_registry
            a = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            b = reg.observe([np.array([1.0, 0.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(a)
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=b))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("người khác chen vào")
            session._trigger_agent_for_text.assert_not_awaited()
            assert reg.asker == a  # asker KHÔNG đổi
            session._agent_task.cancel()

    async def test_unidentified_final_is_kept_and_bumps_streak(self) -> None:
        """Verdict CÓ cụm nhất quán (cluster >= spv_enroll_min_cluster) nhưng không
        khớp asker = bằng chứng dương của một giọng lạ → phải đếm vào van thoát."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop4")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=None, cluster=2))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("không nhận diện được")
            session._trigger_agent_for_text.assert_awaited_once()
            assert session._mismatch_streak == 1
            session._agent_task.cancel()

    async def test_evidence_less_final_does_not_bump_streak(self) -> None:
        """C1: final ngắn không đủ audio để cụm (cluster dưới spv_enroll_min_cluster,
        ví dụ "dạ"/"đúng rồi ạ") KHÔNG phải bằng chứng danh tính asker sai — final vẫn
        trôi tiếp nhưng streak phải giữ nguyên (không bump, không reset)."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop4b")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            session._mismatch_streak = 1  # giá trị trước đó — phải giữ nguyên
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=None, cluster=0))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("dạ")
            session._trigger_agent_for_text.assert_awaited_once()
            assert session._mismatch_streak == 1
            assert reg.asker == ident
            session._agent_task.cancel()

    async def test_streak_limit_drops_asker_and_reopens_floor(self) -> None:
        """Van thoát: danh tính asker sai thì xoá nó đi, đừng khoá cứng người đang nói."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            c["settings"].spv_mismatch_streak_max = 2
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop5")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            session._trigger_agent_for_text = AsyncMock()
            for _ in range(2):
                session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
                session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=None, cluster=2))
                await session._on_final("vẫn không nhận ra")
                session._agent_task.cancel()
            assert reg.asker is None
            assert session._mismatch_streak == 0

    async def test_final_event_carries_speaker_id(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop6")
            session._speaker_tracker.finalize = AsyncMock(
                return_value=_verdict(identity=3, labels=["speaker", "non-speaker"])
            )
            sent: list[dict] = []
            session._send_event = AsyncMock(side_effect=lambda m: sent.append(m))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("xin chào")
            evt = [m for m in sent if m["type"] == "final_transcript"][0]
            assert evt["speaker_id"] == 3
            assert evt["speaker_labels"] == ["speaker", "non-speaker"]

    async def test_single_mode_drops_non_asker_even_when_agent_idle(self) -> None:
        """Fix round 1 — Finding 2a: single mode ép `enforce=True` vô điều kiện,
        nên nhánh 4/5 phải drop cả khi agent đang im (không có _agent_task).

        Chỉ tạo MỘT identity thật qua `observe()`: single mode giới hạn
        `max_identities=1` (BaseSession.__init__), nên gọi `observe()` lần thứ
        hai sẽ evict identity đầu ngay trước khi `set_asker` kịp chạy — verdict
        chỉ cần một số nguyên KHÁC asker, không cần tồn tại thật trong registry
        (nhánh 4/5 không tra registry theo identity)."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop7")
            reg = session._speaker_registry
            a = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(a)
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=a + 1))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("người khác chen vào lúc agent im")
            session._trigger_agent_for_text.assert_not_awaited()
            assert reg.asker == a  # asker KHÔNG đổi

    async def test_paused_drop_resumes_playback_and_resets_episode(self) -> None:
        """Fix round 1 — Finding 2b: drop khi đang soft-pause (addressee gate) phải
        resume playback + reset episode, giống hệt hành vi cũ đã bị xoá test."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop8")
            reg = session._speaker_registry
            a = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            b = reg.observe([np.array([1.0, 0.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(a)
            session._addr_paused = True
            session._addr_reset_episode = MagicMock()
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=b))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("chen vào lúc đang soft-pause")
            session._trigger_agent_for_text.assert_not_awaited()
            c["agent"].resume_playback.assert_called_once()
            session._addr_reset_episode.assert_called_once()
            c["vad"].set_speaking.assert_not_called()  # agent không nói — không cần rearm VAD
            assert reg.asker == a


class TestSpeakerHandover:
    async def test_a_then_b_then_a_recognises_a_again(self) -> None:
        """Yêu cầu §2.1 — đổi người giữa cuộc. Bản 2026-08-28 không thể pass:
        reset() mỗi turn xoá sạch danh tính A trước khi A quay lại."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-handover")
            reg = session._speaker_registry
            a_vec = np.array([0.0, 1.0], dtype=np.float32)
            b_vec = np.array([1.0, 0.0], dtype=np.float32)
            session._trigger_agent_for_text = AsyncMock()

            # Turn 1 — A mở cuộc (floor mở).
            session._speaker_tracker.finalize = AsyncMock(
                return_value=_verdict(identity=reg.observe([a_vec], allow_new=True).identity, is_new=True)
            )
            await session._on_final("A hỏi câu đầu")
            a_id = reg.asker
            assert a_id is not None

            # Turn 2 — B nói khi agent IM: được trao lượt.
            b_id = reg.observe([b_vec], allow_new=True).identity
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=b_id, is_new=True))
            await session._on_final("B hỏi câu tiếp")
            assert reg.asker == b_id

            # Turn 3 — A quay lại: PHẢI nhận ra danh tính cũ, không tạo mới.
            ident, sim = reg.identify(a_vec)
            assert ident == a_id and sim > 0.9
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=a_id))
            await session._on_final("A hỏi lại")
            assert reg.asker == a_id


class TestRegistryLifecycle:
    async def test_identity_survives_turn_end(self) -> None:
        """Bỏ reset() cuối turn: danh tính KHÔNG bị xoá khi agent nói xong.
        Regression cho lỗi 'mỗi turn tung xúc xắc lại'."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-reg")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            await session._run_agent("xin chào")
            assert reg.asker == ident
            assert not reg.empty

    async def test_trigger_agent_no_longer_resets_or_enrolls(self) -> None:
        """Enrollment đã chuyển vào finalize(); _trigger_agent_for_text không được
        đụng vào danh tính nữa."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-reg2")
            assert not hasattr(session._speaker_tracker, "reset")
            assert not hasattr(session._speaker_tracker, "enroll_from_utterance")

    async def test_verdict_non_speaker_keeps_agent_talking(self) -> None:
        """ADDRESSEE_GATE_MODE=off: không khớp → agent nói tiếp liền mạch, KHÔNG khựng."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            c["settings"].addressee_gate_mode = "off"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-reg3")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._handle_interrupt = AsyncMock()
            session.agent.pause_playback = MagicMock()
            session.vad.set_speaking = MagicMock()
            await session._on_speaker_verdict("non-speaker", 0.1, 0)
            session._handle_interrupt.assert_not_awaited()
            session.agent.pause_playback.assert_not_called()
            session.vad.set_speaking.assert_called_once()
            session._agent_task.cancel()
