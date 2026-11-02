"""Streaming STT client cho service `stt_server` qua WebSocket.

Drop-in của SherpaSTT/SonioxSTT (interface STTBase):
    stt = RemoteSTT(on_partial=..., on_final=...)
    await stt.start(); await stt.send(pcm); await stt.stop()

Gửi PCM int16 16kHz mono dưới dạng binary frame; nhận text frame
{"type":"partial"|"final","text":...} và gọi callback tương ứng. Mirror
voice/stt/elevenlabs.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

import websockets
from websockets.protocol import State as WsState

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p

logger = logging.getLogger(__name__)


class RemoteSTT:
    """Một phiên STT nối tới service sherpa từ xa."""

    def __init__(
        self,
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
    ):
        self.on_partial = on_partial
        self.on_final = on_final
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._ws = await websockets.connect(
            settings.stt_service_url,
            additional_headers=p.auth_headers(settings.voice_service_auth_token),
            max_size=10 * 1024 * 1024,
            ping_interval=20,
        )
        self._recv_task = asyncio.create_task(self._receive_loop())
        logger.info("RemoteSTT connected: %s", settings.stt_service_url)

    def is_alive(self) -> bool:
        """Liveness probe for ReconnectingSTT: is the stream still usable?"""
        return self._ws is not None and self._ws.state == WsState.OPEN

    async def send(self, pcm_bytes: bytes) -> None:
        if self._ws and self._ws.state == WsState.OPEN:
            with contextlib.suppress(Exception):
                await self._ws.send(pcm_bytes)  # binary frame

    async def stop(self) -> None:
        if self._ws and self._ws.state == WsState.OPEN:
            with contextlib.suppress(Exception):
                await self._ws.send(p.control_msg(p.EOS))
                await self._ws.close()
        if self._recv_task:
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
        self._ws = None
        self._recv_task = None
        logger.info("RemoteSTT stopped.")

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue  # STT server chỉ gửi text
                msg = p.parse(raw)
                kind = msg.get("type")
                text = msg.get("text", "")
                if not text:
                    continue
                if kind == p.PARTIAL and self.on_partial:
                    await _safe_call(self.on_partial, text)
                elif kind == p.FINAL and self.on_final:
                    await _safe_call(self.on_final, text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("RemoteSTT receive error: %s", exc)


async def _safe_call(fn: Callable, text: str) -> None:
    try:
        result = fn(text)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.error("STT callback error: %s", exc)
