"""Voice bridge: provider → room audio relay must never build a permanent backlog.

Measured on dev (2026-08-26): audio sent before the worker joined the room was
queued (websockets max_queue → TCP backpressure) and then drained at exactly
real-time by `AudioSource.capture_frame`, so the ~2 s head start became a fixed
lag for the whole call (first STT partial +3.4 s vs +1.2 s when the client
waited). The relay buffer is bounded and drops the OLDEST frames, so lag can
never exceed its capacity; `_pump_provider_audio` is the capture loop over it.
"""

import asyncio

import pytest

from noble_agent.gateway import server as s

FRAME_20MS = bytes(640)  # 20 ms PCM16 mono @ 16 kHz


def test_capacity_is_derived_from_ms_at_16k_pcm16():
    buf = s.AudioRelayBuffer(max_ms=300)
    assert buf.max_bytes == 300 * 32  # 16 kHz * 2 bytes = 32 bytes per ms


def test_fifo_order_without_overflow():
    buf = s.AudioRelayBuffer(max_ms=300)
    buf.push(b"a" * 640)
    buf.push(b"b" * 640)
    assert buf.pop_nowait() == b"a" * 640
    assert buf.pop_nowait() == b"b" * 640
    assert buf.dropped == 0


def test_overflow_drops_oldest_and_counts():
    buf = s.AudioRelayBuffer(max_ms=100)  # 5 frames of 20 ms
    for i in range(8):
        buf.push(bytes([i]) * 640)
    # only the 5 newest survive, oldest first
    assert [f[0] for f in buf.drain()] == [3, 4, 5, 6, 7]
    assert buf.dropped == 3


def test_pop_waits_for_data():
    async def run():
        buf = s.AudioRelayBuffer(max_ms=300)

        async def producer():
            await asyncio.sleep(0.02)
            buf.push(FRAME_20MS)

        asyncio.ensure_future(producer())
        assert await asyncio.wait_for(buf.pop(), 1.0) == FRAME_20MS

    asyncio.run(run())


def test_close_wakes_pop_with_none():
    async def run():
        buf = s.AudioRelayBuffer(max_ms=300)
        waiter = asyncio.ensure_future(buf.pop())
        await asyncio.sleep(0.01)
        buf.close()
        assert await asyncio.wait_for(waiter, 1.0) is None
        assert buf.pop_nowait() is None  # stays closed

    asyncio.run(run())


# ------------------------------------------------------- _pump_provider_audio


class _FakeSource:
    """Stands in for rtc.AudioSource: records captured PCM, paces like real-time."""

    sample_rate = 16000

    def __init__(self):
        self.captured: list[bytes] = []

    async def capture_frame(self, frame):
        self.captured.append(bytes(frame.data))
        await asyncio.sleep(0)


def test_pump_forwards_frames_until_closed():
    async def run():
        buf = s.AudioRelayBuffer(max_ms=300)
        src = _FakeSource()
        task = asyncio.ensure_future(s._pump_provider_audio(buf, src, frame_factory=lambda b: _Frame(b)))
        buf.push(b"x" * 640)
        buf.push(b"y" * 640)
        await asyncio.sleep(0.02)
        buf.close()
        await asyncio.wait_for(task, 1.0)
        assert src.captured == [b"x" * 640, b"y" * 640]

    asyncio.run(run())


class _Frame:
    def __init__(self, data):
        self.data = data


@pytest.mark.parametrize("n_stale", [0, 40])
def test_pre_ready_audio_is_trimmed_to_capacity(n_stale):
    """Frames pushed before the capture loop starts (room not ready yet) must not
    pile up: when the loop finally starts it sees at most `max_ms` of audio."""

    async def run():
        buf = s.AudioRelayBuffer(max_ms=200)  # 10 frames
        for i in range(n_stale):
            buf.push(bytes([i % 256]) * 640)
        src = _FakeSource()
        task = asyncio.ensure_future(s._pump_provider_audio(buf, src, frame_factory=_Frame))
        await asyncio.sleep(0.02)
        buf.close()
        await asyncio.wait_for(task, 1.0)
        assert len(src.captured) == min(n_stale, 10)
        assert buf.dropped == max(0, n_stale - 10)

    asyncio.run(run())
