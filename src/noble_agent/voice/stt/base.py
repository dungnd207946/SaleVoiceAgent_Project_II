"""Base protocol for all STT backends."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class STTBase(Protocol):
    """Interface contract for STT backends.

    All backends must implement:
      - start()  → connect to provider
      - send()   → forward PCM audio chunk
      - stop()   → disconnect and cleanup
    """

    on_partial: Callable[[str], None] | None
    on_final: Callable[[str], None] | None

    async def start(self) -> None: ...
    async def send(self, pcm_bytes: bytes) -> None: ...
    async def stop(self) -> None: ...
