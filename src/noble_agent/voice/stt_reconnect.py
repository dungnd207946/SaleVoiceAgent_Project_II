"""Backend-agnostic mid-call STT stream recovery.

Init-time fallback (`voice/fallback.py`) picks a healthy backend once; nothing
recovered a stream that died MID-call — every WS backend's `send()` silently
no-ops on a closed socket, so STT stayed deaf until the call ended (this is
how the Soniox 408 idle-timeout killed voice turns before the keepalive fix,
and how a `remote`/`elevenlabs` service restart still would).

`ReconnectingSTT` wraps any `STTBase` backend and restarts the SAME backend in
the background when its stream reports dead. Liveness comes from an optional
`is_alive()` method on the backend (WS backends: socket-open check); backends
without it — in-process sherpa, test mocks, future backends — are assumed
alive and pass through untouched, so wrapping is always safe.

Deliberately NOT re-running the fallback chain here: mid-call backend swapping
would change the documented invariant ("fallback chỉ chạy lúc init/start") and
swap recognizer behavior mid-conversation. Same backend, same callbacks.

Frames arriving while the stream is down are dropped (the input-gate pre-roll
recovers the next utterance's lead-in once the stream is back).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Minimum spacing between reconnect attempts. Audio frames arrive every ~20ms,
# so without a throttle a dead service would be hammered 50×/s.
RECONNECT_MIN_INTERVAL_S = 2.0


class ReconnectingSTT:
    """Wrap an STT backend; restart it in the background if its stream dies."""

    def __init__(self, inner, *, min_interval_s: float = RECONNECT_MIN_INTERVAL_S):
        self._inner = inner
        self._min_interval_s = min_interval_s
        self._stopped = False
        self._reconnect_task: asyncio.Task | None = None
        self._last_attempt = 0.0

    # Callbacks live on the inner backend (they were wired at construction);
    # proxy them so the wrapper stays a drop-in STTBase.
    @property
    def on_partial(self) -> Callable[[str], None] | None:
        return self._inner.on_partial

    @on_partial.setter
    def on_partial(self, fn: Callable[[str], None] | None) -> None:
        self._inner.on_partial = fn

    @property
    def on_final(self) -> Callable[[str], None] | None:
        return self._inner.on_final

    @on_final.setter
    def on_final(self, fn: Callable[[str], None] | None) -> None:
        self._inner.on_final = fn

    @property
    def inner(self):
        return self._inner

    def _inner_alive(self) -> bool:
        probe = getattr(self._inner, "is_alive", None)
        return probe() if callable(probe) else True

    async def start(self) -> None:
        self._stopped = False
        await self._inner.start()

    async def send(self, pcm_bytes: bytes) -> None:
        if self._inner_alive():
            await self._inner.send(pcm_bytes)
            return
        # Stream is down: drop the frame, recover in the background.
        self._schedule_reconnect()

    async def stop(self) -> None:
        self._stopped = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
        await self._inner.stop()

    def _schedule_reconnect(self) -> None:
        if self._stopped:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        now = time.monotonic()
        if now - self._last_attempt < self._min_interval_s:
            return
        self._last_attempt = now
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        name = type(self._inner).__name__
        logger.warning("STT stream died (%s) — reconnecting", name)
        try:
            await self._inner.stop()  # release the dead socket + recv tasks
        except Exception:  # noqa: BLE001 - a dead backend may fail to clean up
            logger.debug("%s.stop() during reconnect raised", name, exc_info=True)
        if self._stopped:
            return
        try:
            await self._inner.start()
            logger.info("STT stream reconnected (%s)", name)
        except Exception as exc:  # noqa: BLE001 - retried on a later frame
            logger.warning("STT reconnect failed (%s): %s — will retry", name, exc)
