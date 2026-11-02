"""Unit tests for `RoomSession` — Phase 3.

Tests transport wiring without a real LiveKit server. The `rtc.Room`,
`RemoteParticipant`, and `AgentAudioIO` collaborators are mocked.
`BaseSession` internals are allowed to run (cheap constructor) with its
usual heavy dependencies patched at the base_session import site.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@asynccontextmanager
async def _patched_base() -> AsyncIterator[dict]:
    """Make `BaseSession.__init__` cheap."""
    with (
        patch("noble_agent.server.base_session.settings") as mock_settings,
        patch("noble_agent.server.base_session.SileroVAD"),
        patch("noble_agent.server.base_session.VoiceAgent") as MockAgent,
        patch("noble_agent.server.base_session.MetricsCollector"),
        patch("noble_agent.server.base_session.EchoCooldown"),
        patch("noble_agent.server.base_session.WhisperHallucinationFilter"),
    ):
        mock_settings.stt_sample_rate = 16000
        mock_settings.vad_chunk_ms = 32
        mock_settings.smart_turn_enabled = False
        mock_settings.stt_backend = "sherpa"
        mock_settings.tts_backend = "vieneu"
        mock_settings.idle_first_delay = 10.0
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
        mock_settings.speaker_match_threshold = 0.5
        mock_settings.speaker_min_enroll_sec = 1.0
        mock_settings.speaker_verification_enabled = False
        # spv_* probe/enroll schedule (spec 2026-09-03) — parse_probe_schedule and
        # SpeakerTracker's float math need real values, not MagicMock attrs. This
        # file's local .env has SPEAKER_MODE=multi, and `resolve_speaker_mode()`
        # reads the REAL settings (not this mock), so `BaseSession.__init__` takes
        # the speaker-mode branch here regardless of `speaker_mode` above.
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
        mock_settings.spv_max_centroids = 10
        mock_settings.spv_min_match_probe = 2
        mock_settings.spv_min_match_identify = 1
        mock_settings.spv_mismatch_streak_max = 2
        mock_settings.spv_utt_cap_sec = 30.0
        mock_settings.vad_interrupt_confirm_chunks = 3
        mock_settings.addressee_gate_mode = "off"
        mock_settings.addressee_min_speech_ms = 400
        mock_settings.addressee_llm_timeout_ms = 600
        mock_settings.addressee_gate_when_idle = False
        mock_settings.addressee_max_pause_ms = 4000
        mock_settings.agent_name = "Luna"
        # Off by default (matches the real settings default). A bare MagicMock
        # attribute is TRUTHY, so leaving this unset registers a real UsageMeter
        # into the process-global `billing.context._sessions` under the generic id
        # "sid" for every RoomSession built here — and `TestStop` then reaches
        # `BaseSession.stop`'s billing block, which appends the `call` row (making
        # drain() non-empty) and calls the UNMOCKED `sink.flush`, i.e.
        # `asyncpg.create_pool(POSTGRES_DSN)` with no timeout. On a machine whose
        # DSN points at a tunnel-only host with packets dropped rather than
        # refused, the unit suite blocks until TCP timeout.
        mock_settings.billing_metering_enabled = False

        agent = AsyncMock()
        agent._tts = MagicMock(spec=[])
        MockAgent.return_value = agent

        yield {"agent": agent}


@contextmanager
def _patched_audio_io():
    """Replace `AgentAudioIO` with a lightweight stand-in."""
    with patch("noble_agent.transport.livekit.room_session.AgentAudioIO") as MockAudioIO:
        stub = MagicMock()
        stub.start = AsyncMock()
        stub.stop = AsyncMock()
        stub.send = AsyncMock()
        stub.clear = MagicMock()
        stub.queued_duration_s = 0.0

        # Supply an empty async iterator as the input stream.
        async def _empty_stream() -> AsyncIterator[bytes]:
            if False:
                yield b""

        stub.input_stream = MagicMock(return_value=_empty_stream())
        MockAudioIO.return_value = stub
        yield stub


def _make_mock_room(participants=None) -> MagicMock:
    handlers: dict[str, list] = {}

    def _on(event_name):
        def _register(fn):
            handlers.setdefault(event_name, []).append(fn)
            return fn

        return _register

    room = MagicMock()
    room.on.side_effect = _on
    room.name = "call-unit-test"
    room.remote_participants = participants or {}
    room._handlers = handlers  # expose for dispatch in tests
    return room


# ----------------------------------------------------------------------
# participant_disconnected → ends session
# ----------------------------------------------------------------------


class TestDisconnectPlumbing:
    async def test_caller_disconnect_fires_event(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            room = _make_mock_room()
            s = RoomSession(room=room, session_id="sid", caller_identity="caller")

            # Dispatch the participant_disconnected callback registered on room.on.
            handler = room._handlers["participant_disconnected"][0]

            caller = MagicMock()
            caller.identity = "caller"
            handler(caller)
            assert s._disconnect_event.is_set()

    async def test_unrelated_participant_does_not_trigger(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            room = _make_mock_room()
            s = RoomSession(room=room, session_id="sid", caller_identity="caller")

            handler = room._handlers["participant_disconnected"][0]
            other = MagicMock()
            other.identity = "someone-else"
            handler(other)
            assert not s._disconnect_event.is_set()

    async def test_room_disconnect_fires_event(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            room = _make_mock_room()
            s = RoomSession(room=room, session_id="sid", caller_identity="caller")

            handler = room._handlers["disconnected"][0]
            handler("server_shutdown")
            assert s._disconnect_event.is_set()


# ----------------------------------------------------------------------
# Caller lookup
# ----------------------------------------------------------------------


class TestCallerLookup:
    async def test_get_caller_from_dict(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            caller = MagicMock()
            caller.identity = "bob"
            room = _make_mock_room(participants={"bob": caller})
            s = RoomSession(room=room, session_id="sid", caller_identity="bob")

            found = s._get_caller_participant()
            assert found is caller

    async def test_missing_caller_returns_none(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            room = _make_mock_room(participants={})
            s = RoomSession(room=room, session_id="sid", caller_identity="ghost")
            assert s._get_caller_participant() is None


# ----------------------------------------------------------------------
# Track acquisition
# ----------------------------------------------------------------------


class TestAudioTrackAcquisition:
    async def test_returns_already_subscribed_track_immediately(self) -> None:
        async with _patched_base():
            from livekit import rtc

            from noble_agent.transport.livekit.room_session import RoomSession

            caller = MagicMock()
            caller.identity = "bob"

            track = MagicMock()
            pub = MagicMock()
            pub.kind = rtc.TrackKind.KIND_AUDIO
            pub.track = track
            caller.track_publications = {"pub1": pub}

            room = _make_mock_room(participants={"bob": caller})
            s = RoomSession(room=room, session_id="sid", caller_identity="bob")

            result = await s._wait_for_caller_audio_track(caller, timeout=0.1)
            assert result is track

    async def test_times_out_when_no_audio_published(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            caller = MagicMock()
            caller.identity = "bob"
            caller.track_publications = {}

            room = _make_mock_room(participants={"bob": caller})
            s = RoomSession(room=room, session_id="sid", caller_identity="bob")

            with pytest.raises(RuntimeError, match="timed out"):
                await s._wait_for_caller_audio_track(caller, timeout=0.05)


# ----------------------------------------------------------------------
# stop() teardown
# ----------------------------------------------------------------------


class TestStop:
    async def test_stop_cancels_pipeline_and_closes_audio_io(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            room = _make_mock_room()
            s = RoomSession(room=room, session_id="sid", caller_identity="caller")

            # Install a fake audio_io that records .stop() calls.
            fake_audio_io = MagicMock()
            fake_audio_io.stop = AsyncMock()
            s._audio_io = fake_audio_io

            # Stub out shared stop so we don't need DB/RAG collaborators.
            with (
                patch("noble_agent.storage.session_store.load_customer", new_callable=AsyncMock, return_value={}),
            ):
                await s.stop()

            fake_audio_io.stop.assert_awaited_once()
            assert s._stopping is True

    async def test_idle_disconnect_sets_event(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            room = _make_mock_room()
            s = RoomSession(room=room, session_id="sid", caller_identity="caller")

            with (
                patch("noble_agent.storage.session_store.load_customer", new_callable=AsyncMock, return_value={}),
            ):
                await s._on_idle_disconnect()
            assert s._disconnect_event.is_set()


# ----------------------------------------------------------------------
# start() orchestration (with AgentAudioIO stubbed)
# ----------------------------------------------------------------------


class TestStartOrchestration:
    async def test_start_wires_audio_io_and_launches_pipeline(self) -> None:
        async with _patched_base() as cols:
            from livekit import rtc

            from noble_agent.transport.livekit.room_session import RoomSession

            caller = MagicMock()
            caller.identity = "bob"
            track = MagicMock()
            pub = MagicMock()
            pub.kind = rtc.TrackKind.KIND_AUDIO
            pub.track = track
            caller.track_publications = {"pub1": pub}

            room = _make_mock_room(participants={"bob": caller})

            with (
                _patched_audio_io() as audio_io,
                patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
                patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=AsyncMock()),
            ):
                s = RoomSession(room=room, session_id="sid", caller_identity="bob")
                await s.start()

                audio_io.start.assert_awaited_once()
                assert s._audio_io is audio_io
                assert s._pipeline_task is not None
                # Pipeline task should terminate quickly because input_stream is empty.
                await s._pipeline_task

            cols["agent"].start.assert_awaited()

    async def test_start_raises_when_caller_missing(self) -> None:
        async with _patched_base():
            from noble_agent.transport.livekit.room_session import RoomSession

            room = _make_mock_room(participants={})
            with (
                patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
                patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=AsyncMock()),
            ):
                s = RoomSession(room=room, session_id="sid", caller_identity="ghost")
                with pytest.raises(RuntimeError, match="not found in room"):
                    await s.start()
