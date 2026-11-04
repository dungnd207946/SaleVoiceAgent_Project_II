"""ReconnectingSTT — backend-agnostic mid-call STT stream recovery.

Init-time fallback picks a healthy backend once; nothing recovered a stream
that died mid-call (every WS backend's send() silently no-ops on a closed
socket). The wrapper restarts the SAME backend in the background when its
stream reports dead via the optional `is_alive()` probe. Backends without
`is_alive()` (in-process sherpa, mocks) are assumed alive → pure passthrough,
which is what keeps the wrapper safe for ANY current or future backend.
"""

from __future__ import annotations

import asyncio

import pytest

from noble_agent.voice.stt_reconnect import ReconnectingSTT


class FakeSTT:
    """Backend stub with a controllable liveness flag."""

    def __init__(self, *, fail_starts: int = 0):
        self.on_partial = None
        self.on_final = None
        self.alive = False
        self.sent: list[bytes] = []
        self.start_calls = 0
        self.stop_calls = 0
        self._fail_starts = fail_starts

    def is_alive(self) -> bool:
        return self.alive

    async def start(self) -> None:
        self.start_calls += 1
        if self._fail_starts > 0:
            self._fail_starts -= 1
            raise RuntimeError("service down")
        self.alive = True

    async def send(self, pcm_bytes: bytes) -> None:
        self.sent.append(pcm_bytes)

    async def stop(self) -> None:
        self.stop_calls += 1
        self.alive = False


class PlainSTT:
    """Backend with NO is_alive() — must be treated as always alive."""

    def __init__(self):
        self.on_partial = None
        self.on_final = None
        self.sent: list[bytes] = []
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def send(self, pcm_bytes: bytes) -> None:
        self.sent.append(pcm_bytes)

    async def stop(self) -> None:
        self.stop_calls += 1


async def _drain():
    # Let scheduled reconnect tasks run to completion.
    for _ in range(5):
        await asyncio.sleep(0)


async def test_passthrough_while_alive():
    inner = FakeSTT()
    stt = ReconnectingSTT(inner, min_interval_s=0.0)
    await stt.start()
    await stt.send(b"a")
    assert inner.sent == [b"a"]
    assert inner.start_calls == 1


async def test_dead_stream_triggers_restart_of_same_backend():
    inner = FakeSTT()
    stt = ReconnectingSTT(inner, min_interval_s=0.0)
    await stt.start()
    inner.alive = False  # stream died mid-call (e.g. server closed the WS)
    await stt.send(b"lost")  # dropped, schedules reconnect
    await _drain()
    assert inner.stop_calls == 1  # cleaned up before restarting
    assert inner.start_calls == 2
    assert inner.alive
    await stt.send(b"b")  # flows again after recovery
    assert b"b" in inner.sent
    assert b"lost" not in inner.sent


async def test_reconnect_attempts_are_throttled():
    inner = FakeSTT()
    stt = ReconnectingSTT(inner, min_interval_s=60.0)
    await stt.start()
    inner._fail_starts = 100  # service stays down
    inner.alive = False
    for _ in range(10):
        await stt.send(b"x")
        await _drain()
    # 20ms frames arrive constantly; only ONE attempt within the interval.
    assert inner.start_calls <= 2  # the init call + at most one retry


async def test_no_reconnect_after_stop():
    inner = FakeSTT()
    stt = ReconnectingSTT(inner, min_interval_s=0.0)
    await stt.start()
    await stt.stop()
    starts_after_stop = inner.start_calls
    await stt.send(b"x")
    await _drain()
    assert inner.start_calls == starts_after_stop


async def test_backend_without_is_alive_is_pure_passthrough():
    inner = PlainSTT()
    stt = ReconnectingSTT(inner, min_interval_s=0.0)
    await stt.start()
    await stt.send(b"a")
    await _drain()
    assert inner.sent == [b"a"]
    assert inner.start_calls == 1  # never restarted
    assert inner.stop_calls == 0


async def test_failed_reconnect_retries_later():
    inner = FakeSTT()
    stt = ReconnectingSTT(inner, min_interval_s=0.0)
    await stt.start()
    inner.alive = False
    inner._fail_starts = 1  # first retry fails, second succeeds
    await stt.send(b"x")
    await _drain()
    assert not inner.alive  # first attempt failed
    await stt.send(b"y")
    await _drain()
    assert inner.alive  # second attempt recovered
    assert inner.start_calls == 3  # init + failed retry + good retry


async def test_callbacks_proxy_to_inner():
    inner = FakeSTT()
    stt = ReconnectingSTT(inner)
    assert stt.on_partial is None
    fn = lambda t: None  # noqa: E731
    stt.on_final = fn
    assert inner.on_final is fn
    assert stt.on_final is fn
    assert stt.inner is inner


async def test_start_failure_propagates():
    # Session init relies on start() raising so the fallback chain can move on.
    inner = FakeSTT(fail_starts=1)
    stt = ReconnectingSTT(inner, min_interval_s=0.0)
    with pytest.raises(RuntimeError):
        await stt.start()
