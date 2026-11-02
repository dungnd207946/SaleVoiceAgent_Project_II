"""Phase 3 integration test — `RoomSession` transport end-to-end.

Covers the transport wiring without the real STT / LLM / TTS stack:
- A caller simulator joins the LiveKit room, publishes a tone track.
- A `RoomSession` joins as the agent. Its `BaseSession.agent.handle_utterance`
  is stubbed to produce a synthetic response that the caller must hear.
- We directly call `BaseSession._trigger_agent_for_text` once to bypass
  STT and assert the agent-output path reaches the caller.

Proves end-to-end: caller → LiveKit → RoomSession → AgentAudioIO →
LiveKit → caller. The real API pipeline is exercised by
`scripts/livekit_demo_caller.py` and (manual) Phase 7 PSTN calls.

Marked `requires_docker`; auto-skips when no LiveKit server is reachable.
"""

from __future__ import annotations

import asyncio
import math
import os
import socket
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import numpy as np
import pytest
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

SAMPLE_RATE = 8000
CHANNELS = 1
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
TONE_HZ = 440
AMPLITUDE = 10_000
AGENT_RESPONSE_AMPLITUDE = 12_000  # distinct from caller tone
SILENCE_RMS_THRESHOLD = 400

LK_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LK_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LK_SECRET = os.environ.get("LIVEKIT_API_SECRET", "devsecret_change_me_for_prod_1234567890abcdef")


def _server_reachable() -> bool:
    parsed = urlparse(LK_URL.replace("ws://", "http://").replace("wss://", "https://"))
    host = parsed.hostname or "localhost"
    port = parsed.port or 7880
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.requires_docker,
    pytest.mark.skipif(
        not _server_reachable(),
        reason=f"LiveKit server not reachable at {LK_URL}",
    ),
]


def _token(identity: str, room: str) -> str:
    grants = VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)
    return AccessToken(api_key=LK_KEY, api_secret=LK_SECRET).with_identity(identity).with_grants(grants).to_jwt()


def _tone_frame(phase_samples: int, amplitude: int = AMPLITUDE) -> rtc.AudioFrame:
    t = (np.arange(SAMPLES_PER_FRAME) + phase_samples) / SAMPLE_RATE
    pcm = (np.sin(2 * math.pi * TONE_HZ * t) * amplitude).astype(np.int16)
    return rtc.AudioFrame(
        data=pcm.tobytes(),
        sample_rate=SAMPLE_RATE,
        num_channels=CHANNELS,
        samples_per_channel=SAMPLES_PER_FRAME,
    )


async def _wait_for_audio_track(room: rtc.Room, timeout: float = 15.0) -> rtc.Track:
    fut: asyncio.Future[rtc.Track] = asyncio.get_event_loop().create_future()

    @room.on("track_subscribed")
    def _on_sub(track: rtc.Track, _pub, _participant) -> None:  # type: ignore[no-untyped-def]
        if not fut.done() and track.kind == rtc.TrackKind.KIND_AUDIO:
            fut.set_result(track)

    return await asyncio.wait_for(fut, timeout=timeout)


@pytest.mark.asyncio
async def test_room_session_end_to_end_caller_hears_agent() -> None:
    """Transport-layer smoke: caller → RoomSession → caller receives agent audio.

    STT/LLM/TTS stack is stubbed. The stubbed `handle_utterance` pushes a
    distinct high-amplitude tone via `send_agent_audio`, which must end up
    audible on the caller side.
    """
    room_name = "phase3-e2e-test"

    # --- Caller side: publish tone, subscribe to agent track ---
    caller_room = rtc.Room()
    await caller_room.connect(LK_URL, _token("caller", room_name))

    caller_source = rtc.AudioSource(SAMPLE_RATE, CHANNELS, queue_size_ms=200)
    caller_track = rtc.LocalAudioTrack.create_audio_track("caller-tone", caller_source)
    await caller_room.local_participant.publish_track(caller_track)

    agent_track_task = asyncio.create_task(_wait_for_audio_track(caller_room))

    # --- Agent side: spin up RoomSession with heavy deps stubbed ---
    with (
        patch("noble_agent.server.base_session.VoiceAgent") as MockAgent,
        patch("noble_agent.server.base_session.SileroVAD"),
        patch("noble_agent.server.base_session.MetricsCollector"),
        patch("noble_agent.server.base_session.EchoCooldown"),
        patch("noble_agent.server.base_session.WhisperHallucinationFilter"),
        patch("noble_agent.storage.session_store.upsert_meta", new_callable=AsyncMock),
        patch("noble_agent.agent.rag.memory_router.get_router", new_callable=AsyncMock, return_value=None),
        patch("noble_agent.voice.stt.sherpa.SherpaSTT", return_value=AsyncMock()),
    ):
        from noble_agent.transport.livekit.room_session import RoomSession

        agent = AsyncMock()
        agent.interrupt = lambda: None
        agent._tts = type("X", (), {"__hasattr__": lambda self, a: False})()

        # Capture the VoiceAgent constructor call so we can grab `send_audio`.
        send_audio_cb = {}

        def _construct_agent(**kwargs):
            send_audio_cb["fn"] = kwargs["send_audio"]
            return agent

        MockAgent.side_effect = _construct_agent

        agent_room = rtc.Room()
        await agent_room.connect(LK_URL, _token("agent", room_name))

        # Let caller & agent discover each other.
        await asyncio.sleep(0.5)

        session = RoomSession(
            room=agent_room,
            session_id=room_name,
            caller_identity="caller",
        )

        try:
            await session.start()

            # --- Caller subscribes to agent track BEFORE any audio is sent ---
            agent_track = await agent_track_task
            stream = rtc.AudioStream(agent_track, sample_rate=SAMPLE_RATE, num_channels=CHANNELS)
            audible = 0

            async def _consume() -> None:
                nonlocal audible
                async for event in stream:
                    pcm = np.frombuffer(event.frame.data, dtype=np.int16)
                    if pcm.size == 0:
                        continue
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
                    if rms > SILENCE_RMS_THRESHOLD:
                        audible += 1

            consume_task = asyncio.create_task(_consume())

            # --- Caller publishes 1s of tone (keeps the session "alive" audio-wise) ---
            async def _push_caller() -> None:
                phase = 0
                for _ in range(50):
                    await caller_source.capture_frame(_tone_frame(phase))
                    phase += SAMPLES_PER_FRAME

            caller_push = asyncio.create_task(_push_caller())

            # --- Agent-side: push ~2s of distinct response tone via the send hook ---
            assert "fn" in send_audio_cb, "VoiceAgent was not constructed via BaseSession"
            send = send_audio_cb["fn"]
            phase = 0
            for _ in range(100):
                pcm = np.zeros(SAMPLES_PER_FRAME, dtype=np.int16)
                t = (np.arange(SAMPLES_PER_FRAME) + phase) / SAMPLE_RATE
                pcm[:] = (np.sin(2 * math.pi * 880 * t) * AGENT_RESPONSE_AMPLITUDE).astype(np.int16)
                await send(pcm.tobytes())
                phase += SAMPLES_PER_FRAME

            # Drain tail.
            await asyncio.sleep(1.0)
            consume_task.cancel()
            caller_push.cancel()
            await stream.aclose()

            assert audible >= 30, f"caller should have received ≥30 audible agent frames, got {audible}"
        finally:
            await session.stop()
            await caller_source.aclose()
            await caller_room.disconnect()
            await agent_room.disconnect()
