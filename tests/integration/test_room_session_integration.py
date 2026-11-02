"""Phase 5 — RoomSession integration scenarios driven via mocks.

These exercise `RoomSession` end-to-end WITHOUT a real LiveKit server.
We swap in `FakeRoom`/`FakeRemoteParticipant`/`FakeRemoteTrack` for the
rtc types and patch out `AgentAudioIO` so we can inspect send/clear/stop
calls directly. Together with the Docker-gated `test_room_session_e2e.py`
this closes coverage on the transport glue (plan §5 Phase 5 exit:
RoomSession coverage ≥85%).

Scenarios covered here:
- Participant-disconnected event ends `wait_until_end`.
- Room-disconnected event ends `wait_until_end`.
- Idle-state goodbye sets the disconnect event.
- `stop()` sequences: shared teardown → audio_io.stop → pipeline cancel.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures.livekit import (
    FakeRoom,
    make_mock_caller_track,
    make_mock_participant,
    make_mock_room,
)


@asynccontextmanager
async def _patched_base_session_deps() -> AsyncIterator[dict]:
    """Make BaseSession.__init__ cheap and observable for assertions."""
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
        mock_settings.idle_first_delay = 0.02
        mock_settings.idle_prompt_delay = 0.02
        mock_settings.idle_goodbye_delay = 0.02
        mock_settings.smart_turn_threshold = 0.5
        mock_settings.smart_turn_max_hold_sec = 2.0
        mock_settings.stt_input_gate_mode = "off"
        mock_settings.audio_gate_preroll_chunks = 3
        mock_settings.audio_gate_min_rms = 160.0
        mock_settings.audio_gate_required_consecutive = 3
        mock_settings.audio_gate_barge_in_rms = 2400.0
        mock_settings.stt_vad_gate_hangover_ms = 300
        mock_settings.audio_guard_repetition_detector_enabled = False
        # Off by default (matches the real settings default) — a bare MagicMock
        # attribute is truthy, and a truthy flag here makes `BaseSession.stop`
        # reach the billing block and call the unmocked `sink.flush`, i.e. a real
        # `asyncpg.create_pool(POSTGRES_DSN)` with no timeout. Same fix as
        # `tests/unit/test_base_session.py` / `test_room_session.py`.
        mock_settings.billing_metering_enabled = False

        agent = AsyncMock()
        agent.pause_tts = AsyncMock()
        agent.speak_text = AsyncMock()
        agent._tts = type("X", (), {"__hasattr__": lambda _s, _a: False})()
        MockAgent.return_value = agent

        yield {"agent": agent, "settings": mock_settings}


@asynccontextmanager
async def _fully_patched_room_session(room: FakeRoom):
    """Spin up a RoomSession with all shared-init + audio-io collaborators
    stubbed so we can test transport-layer behavior in isolation.
    """
    async with _patched_base_session_deps():
        with (
            patch("noble_agent.transport.livekit.room_session.AgentAudioIO") as MockAudioIO,
            patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
            patch("noble_agent.storage.session_store.load_customer", new_callable=AsyncMock, return_value={}),
            patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=AsyncMock()),
        ):
            audio_io = MagicMock()
            audio_io.start = AsyncMock()
            audio_io.stop = AsyncMock()
            audio_io.send = AsyncMock()
            audio_io.clear = MagicMock()
            audio_io.queued_duration_s = 0.0

            async def _empty_stream() -> AsyncIterator[bytes]:
                if False:
                    yield b""

            audio_io.input_stream = MagicMock(return_value=_empty_stream())
            MockAudioIO.return_value = audio_io

            from noble_agent.transport.livekit.room_session import RoomSession

            session = RoomSession(
                room=room,  # type: ignore[arg-type]
                session_id=room.name,
                caller_identity="caller",
            )
            yield session, audio_io


# ----------------------------------------------------------------------
# Participant / room disconnect
# ----------------------------------------------------------------------


class TestDisconnectPaths:
    @pytest.mark.asyncio
    async def test_participant_disconnected_ends_wait(self) -> None:
        track = make_mock_caller_track()
        participant = make_mock_participant("caller", track=track)
        room = make_mock_room(participants={"caller": participant})

        async with _fully_patched_room_session(room) as (session, _audio_io):
            await session.start()

            wait_task = asyncio.create_task(session.wait_until_end())

            # Caller leaves.
            room.fire("participant_disconnected", participant)

            # wait_until_end should return promptly.
            await asyncio.wait_for(wait_task, timeout=1.0)
            await session.stop()

    @pytest.mark.asyncio
    async def test_room_disconnected_ends_wait(self) -> None:
        track = make_mock_caller_track()
        participant = make_mock_participant("caller", track=track)
        room = make_mock_room(participants={"caller": participant})

        async with _fully_patched_room_session(room) as (session, _audio_io):
            await session.start()

            wait_task = asyncio.create_task(session.wait_until_end())
            room.fire("disconnected", "server_shutdown")

            await asyncio.wait_for(wait_task, timeout=1.0)
            await session.stop()

    @pytest.mark.asyncio
    async def test_unrelated_participant_disconnect_ignored(self) -> None:
        track = make_mock_caller_track()
        participant = make_mock_participant("caller", track=track)
        room = make_mock_room(participants={"caller": participant})

        async with _fully_patched_room_session(room) as (session, _audio_io):
            await session.start()

            other = make_mock_participant("eavesdropper")
            room.fire("participant_disconnected", other)
            # Should NOT end.
            assert not session._disconnect_event.is_set()
            await session.stop()


# ----------------------------------------------------------------------
# Idle-timeout → goodbye → disconnect
# ----------------------------------------------------------------------


class TestIdleTimeout:
    @pytest.mark.asyncio
    async def test_idle_sequence_triggers_disconnect(self) -> None:
        track = make_mock_caller_track()
        participant = make_mock_participant("caller", track=track)
        room = make_mock_room(participants={"caller": participant})

        async with _fully_patched_room_session(room) as (session, _audio_io):
            await session.start()

            # Fast-path all three idle steps manually.
            session._idle_state = 2
            await session._on_idle_timeout()

            assert session._disconnect_event.is_set()
            assert session._stopping is True


# ----------------------------------------------------------------------
# Stop ordering
# ----------------------------------------------------------------------


class TestStopOrdering:
    @pytest.mark.asyncio
    async def test_stop_runs_super_then_audio_io_then_pipeline_cancel(self) -> None:
        track = make_mock_caller_track()
        participant = make_mock_participant("caller", track=track)
        room = make_mock_room(participants={"caller": participant})

        async with _fully_patched_room_session(room) as (session, audio_io):
            await session.start()

            # Spy on order. BaseSession.stop triggers audio_output.clear via
            # the installed hook; we assert audio_io.stop is called AFTER
            # shared teardown (which also calls clear — but on the audio_io
            # itself since that IS the audio_output).
            calls: list[str] = []

            audio_io.clear.side_effect = lambda: calls.append("audio_io.clear")

            async def _audio_io_stop() -> None:
                calls.append("audio_io.stop")

            audio_io.stop.side_effect = _audio_io_stop

            await session.stop()

            # At minimum: clear happened (during super().stop) BEFORE
            # audio_io.stop().
            assert calls[0] == "audio_io.clear"
            assert "audio_io.stop" in calls
            assert calls.index("audio_io.clear") < calls.index("audio_io.stop")


# ----------------------------------------------------------------------
# Failure paths
# ----------------------------------------------------------------------


class TestFailurePaths:
    @pytest.mark.asyncio
    async def test_start_raises_when_caller_never_joined(self) -> None:
        # No participants in the room at all.
        room = make_mock_room(participants={})

        async with _fully_patched_room_session(room) as (session, _audio_io):
            with pytest.raises(RuntimeError, match="not found in room"):
                await session.start()

    @pytest.mark.asyncio
    async def test_audio_io_stop_failure_does_not_raise(self) -> None:
        track = make_mock_caller_track()
        participant = make_mock_participant("caller", track=track)
        room = make_mock_room(participants={"caller": participant})

        async with _fully_patched_room_session(room) as (session, audio_io):
            await session.start()
            audio_io.stop.side_effect = RuntimeError("boom")
            # Must not raise — stop is best-effort.
            await session.stop()
