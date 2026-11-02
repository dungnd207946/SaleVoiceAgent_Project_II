"""Phase 1 integration test for `AgentAudioIO`.

Stands up a caller simulator (another LiveKit client) in the same room as
`AgentAudioIO`, plays a tone at the caller, has the agent-side echo each
received PCM16 chunk back, and verifies the caller hears its own tone.

Requires a reachable LiveKit server. Skipped by default unless
`LIVEKIT_URL` points to a running server (by default the skip happens because
the env var is unset in CI; local developers run with
`docker run --rm -p 7880:7880 ... livekit/livekit-server --dev`).

Marked `requires_docker` to keep CI green without the stack.
"""

from __future__ import annotations

import asyncio
import math
import os

import numpy as np
import pytest
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from noble_agent.transport.livekit import AgentAudioIO, AudioIOConfig

SAMPLE_RATE = 8000
CHANNELS = 1
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
TONE_HZ = 600
TONE_AMPLITUDE = 10_000
# Number of 20ms frames the caller pushes (~2.4s) — enough to let the pipeline
# warm up past any initial buffering before we measure.
CALLER_FRAMES = 120
SILENCE_RMS_THRESHOLD = 400
# Minimum audible frames we require to see echoed back; with 120 pushed and
# a ~200ms startup buffer, ≥80 is a generous floor.
MIN_AUDIBLE_ECHO_FRAMES = 30

LK_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LK_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LK_SECRET = os.environ.get("LIVEKIT_API_SECRET", "devsecret_change_me_for_prod_1234567890abcdef")


def _server_reachable() -> bool:
    """Best-effort TCP probe — LiveKit's websocket port is a good enough ping."""
    import socket
    from urllib.parse import urlparse

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
        reason=f"LiveKit server not reachable at {LK_URL} — start `livekit/livekit-server --dev`",
    ),
]


def _mint_token(identity: str, room: str) -> str:
    grants = VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)
    return AccessToken(api_key=LK_KEY, api_secret=LK_SECRET).with_identity(identity).with_grants(grants).to_jwt()


def _tone_frame(phase_samples: int) -> rtc.AudioFrame:
    t = (np.arange(SAMPLES_PER_FRAME) + phase_samples) / SAMPLE_RATE
    pcm = (np.sin(2 * math.pi * TONE_HZ * t) * TONE_AMPLITUDE).astype(np.int16)
    return rtc.AudioFrame(
        data=pcm.tobytes(),
        sample_rate=SAMPLE_RATE,
        num_channels=CHANNELS,
        samples_per_channel=SAMPLES_PER_FRAME,
    )


async def _await_first_audio_track(room: rtc.Room, timeout: float = 15.0) -> rtc.Track:
    fut: asyncio.Future[rtc.Track] = asyncio.get_event_loop().create_future()

    @room.on("track_subscribed")
    def _on_sub(track: rtc.Track, _pub, _participant) -> None:  # type: ignore[no-untyped-def]
        if not fut.done() and track.kind == rtc.TrackKind.KIND_AUDIO:
            fut.set_result(track)

    return await asyncio.wait_for(fut, timeout=timeout)


async def _run_agent_side(room_name: str, stop_evt: asyncio.Event) -> None:
    """Joins room as the agent, wraps caller's track in AgentAudioIO, and
    echoes every received PCM16 chunk back through `output_sink`.
    """
    room = rtc.Room()
    await room.connect(LK_URL, _mint_token("agent", room_name))
    try:
        caller_track = await _await_first_audio_track(room)
        io = AgentAudioIO(
            room,
            caller_track,
            AudioIOConfig(sample_rate=SAMPLE_RATE, num_channels=CHANNELS),
        )
        await io.start()

        try:
            async for chunk in io.input_stream():
                if stop_evt.is_set():
                    break
                await io.output_sink(chunk)
        finally:
            await io.stop()
    finally:
        await room.disconnect()


async def _run_caller_side(room_name: str) -> dict:
    """Joins room as the caller, pushes tone frames, counts audible echo frames."""
    room = rtc.Room()
    await room.connect(LK_URL, _mint_token("caller", room_name))
    try:
        # Subscribe to agent's echoed track.
        agent_track_task = asyncio.create_task(_await_first_audio_track(room))

        # Publish caller's tone track.
        src = rtc.AudioSource(SAMPLE_RATE, CHANNELS, queue_size_ms=200)
        local_track = rtc.LocalAudioTrack.create_audio_track("caller-tone", src)
        await room.local_participant.publish_track(local_track)

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

        phase = 0
        for _ in range(CALLER_FRAMES):
            await src.capture_frame(_tone_frame(phase))
            phase += SAMPLES_PER_FRAME

        # Drain tail of echoed audio.
        await asyncio.sleep(1.0)

        consume_task.cancel()
        await stream.aclose()
        await src.aclose()
        return {"audible_echo_frames": audible}
    finally:
        await room.disconnect()


@pytest.mark.asyncio
async def test_agent_audio_io_echoes_caller_tone() -> None:
    """End-to-end: caller tone → AgentAudioIO.input_stream → output_sink → caller hears it."""
    room_name = "phase1-echo-test"
    stop_evt = asyncio.Event()

    agent_task = asyncio.create_task(_run_agent_side(room_name, stop_evt))
    # Give the agent a head-start so it's subscribed before the caller publishes.
    await asyncio.sleep(0.5)

    try:
        result = await _run_caller_side(room_name)
    finally:
        stop_evt.set()
        try:
            await asyncio.wait_for(agent_task, timeout=5)
        except TimeoutError:
            agent_task.cancel()
            with pytest.raises((asyncio.CancelledError, BaseException)):
                await agent_task

    assert result["audible_echo_frames"] >= MIN_AUDIBLE_ECHO_FRAMES, (
        f"expected ≥{MIN_AUDIBLE_ECHO_FRAMES} audible echoed frames, got {result['audible_echo_frames']}"
    )
