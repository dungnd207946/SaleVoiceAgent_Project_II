"""Phase 4.1 — end-to-end interrupt latency regression.

Drives the full `BaseSession._handle_interrupt` pipeline (pause_tts →
task.cancel → audio_output.clear → vad.set_idle) against a live LiveKit
server with stubbed agent. Measures wall-clock time from interrupt
trigger (caller-side) to the moment the caller observes silence on the
agent's audio track.

Exit: p95 (here: max across 3 trials) must be <200 ms to satisfy plan §5
Phase 4.1.
"""

from __future__ import annotations

import asyncio
import math
import os
import socket
import time
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
AMPLITUDE = 12_000
SILENCE_RMS_THRESHOLD = 400
PLAY_BEFORE_INTERRUPT_MS = 300
TRIALS = 3
LATENCY_BUDGET_MS = 200

LK_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LK_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LK_SECRET = os.environ.get("LIVEKIT_API_SECRET", "devsecret_change_me_for_prod_1234567890abcdef")


def _reachable() -> bool:
    parsed = urlparse(LK_URL.replace("ws://", "http://").replace("wss://", "https://"))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 7880), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.requires_docker,
    pytest.mark.skipif(not _reachable(), reason=f"LiveKit unreachable at {LK_URL}"),
]


def _token(identity: str, room: str) -> str:
    grants = VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)
    return AccessToken(api_key=LK_KEY, api_secret=LK_SECRET).with_identity(identity).with_grants(grants).to_jwt()


def _tone_frame(phase: int) -> rtc.AudioFrame:
    t = (np.arange(SAMPLES_PER_FRAME) + phase) / SAMPLE_RATE
    pcm = (np.sin(2 * math.pi * TONE_HZ * t) * AMPLITUDE).astype(np.int16)
    return rtc.AudioFrame(
        data=pcm.tobytes(),
        sample_rate=SAMPLE_RATE,
        num_channels=CHANNELS,
        samples_per_channel=SAMPLES_PER_FRAME,
    )


async def _run_one_trial(trial_idx: int) -> float:
    """Return end-to-end interrupt latency in ms."""
    room_name = f"phase4-interrupt-{trial_idx}-{int(time.time() * 1000)}"

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
        send_audio_cb = {}
        agent = AsyncMock()
        agent.pause_tts = AsyncMock()
        agent._tts = type("X", (), {"__hasattr__": lambda self, a: False})()

        def _construct_agent(**kwargs):
            send_audio_cb["fn"] = kwargs["send_audio"]
            return agent

        MockAgent.side_effect = _construct_agent

        from noble_agent.transport.livekit.room_session import RoomSession

        # --- Caller side ---
        caller_room = rtc.Room()
        await caller_room.connect(LK_URL, _token("caller", room_name))
        caller_src = rtc.AudioSource(SAMPLE_RATE, CHANNELS, queue_size_ms=200)
        caller_track = rtc.LocalAudioTrack.create_audio_track("caller", caller_src)
        await caller_room.local_participant.publish_track(caller_track)

        agent_track_fut: asyncio.Future[rtc.Track] = asyncio.get_event_loop().create_future()

        @caller_room.on("track_subscribed")
        def _on_sub(track: rtc.Track, _pub, _p) -> None:  # type: ignore[no-untyped-def]
            if not agent_track_fut.done() and track.kind == rtc.TrackKind.KIND_AUDIO:
                agent_track_fut.set_result(track)

        # --- Agent side ---
        agent_room = rtc.Room()
        await agent_room.connect(LK_URL, _token("agent", room_name))
        await asyncio.sleep(0.5)

        session = RoomSession(room=agent_room, session_id=room_name, caller_identity="caller")
        try:
            await session.start()
            agent_track = await asyncio.wait_for(agent_track_fut, timeout=10)
            stream = rtc.AudioStream(agent_track, sample_rate=SAMPLE_RATE, num_channels=CHANNELS)

            last_audible: list[float] = [0.0]

            async def _consume() -> None:
                async for event in stream:
                    pcm = np.frombuffer(event.frame.data, dtype=np.int16)
                    if pcm.size == 0:
                        continue
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
                    if rms > SILENCE_RMS_THRESHOLD:
                        last_audible[0] = time.perf_counter()

            consume_task = asyncio.create_task(_consume())

            # Fake an in-flight agent task so _handle_interrupt has something
            # to cancel.
            async def _long() -> None:
                await asyncio.sleep(30)

            session._agent_task = asyncio.create_task(_long())

            # Pump agent tone.
            send = send_audio_cb["fn"]
            stop_pump = asyncio.Event()

            async def _pump() -> None:
                phase = 0
                while not stop_pump.is_set():
                    await send(_tone_frame(phase).data.tobytes())
                    phase += SAMPLES_PER_FRAME

            pump_task = asyncio.create_task(_pump())
            await asyncio.sleep(PLAY_BEFORE_INTERRUPT_MS / 1000)

            # Trigger interrupt. Stop pumping FIRST so the queue drains — then
            # fire the interrupt pipeline, which clears buffered audio at the source.
            stop_pump.set()
            interrupt_t0 = time.perf_counter()
            await session._handle_interrupt()

            # Give subscriber time to observe silence.
            await asyncio.sleep(0.8)

            consume_task.cancel()
            pump_task.cancel()
            await stream.aclose()

            latency_ms = max(0.0, (last_audible[0] - interrupt_t0) * 1000)
            return latency_ms
        finally:
            await session.stop()
            await caller_src.aclose()
            await caller_room.disconnect()
            await agent_room.disconnect()


@pytest.mark.asyncio
async def test_interrupt_latency_under_200ms() -> None:
    latencies: list[float] = []
    for i in range(TRIALS):
        lat = await _run_one_trial(i)
        latencies.append(lat)
        await asyncio.sleep(0.5)  # gap to let ports settle

    p_max = max(latencies)
    print(f"\nInterrupt latency (ms): trials={latencies} max={p_max:.1f}")
    assert p_max < LATENCY_BUDGET_MS, (
        f"interrupt latency max {p_max:.1f}ms exceeds {LATENCY_BUDGET_MS}ms budget; all trials: {latencies}"
    )
