"""Streaming STT via ElevenLabs Scribe v2 Realtime — WebSocket.

Drop-in replacement for SherpaSTT / SonioxSTT:
    stt = ElevenLabsSTT(on_partial=..., on_final=...)
    await stt.start()
    await stt.send(pcm_bytes)   # PCM int16, 16kHz, mono
    await stt.stop()

Uses server-side VAD (commit_strategy=vad) for automatic endpoint detection.
Auto-detects language when language_code is omitted (supports Vietnamese + English
code-switching). Explicit language_code can be set via config.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from urllib.parse import urlencode

import websockets
from websockets.protocol import State as WsState

from noble_agent.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_STT_WS_BASE = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"


class ElevenLabsSTT:
    """One streaming STT session backed by ElevenLabs Scribe v2 Realtime."""

    def __init__(
        self,
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
    ):
        self.on_partial = on_partial
        self.on_final = on_final
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task | None = None
        self._first_chunk = True

    async def start(self):
        params: dict = {
            "model_id": settings.elevenlabs_stt_model,
            "audio_format": f"pcm_{settings.stt_sample_rate}",
            "commit_strategy": "vad",
            "vad_silence_threshold_secs": settings.elevenlabs_stt_vad_silence_sec,
            "vad_threshold": settings.elevenlabs_stt_vad_threshold,
        }
        if settings.elevenlabs_stt_language_code:
            params["language_code"] = settings.elevenlabs_stt_language_code
        if settings.elevenlabs_stt_language_detection:
            params["include_language_detection"] = "true"

        url = f"{ELEVENLABS_STT_WS_BASE}?{urlencode(params)}"
        self._ws = await websockets.connect(
            url,
            additional_headers={"xi-api-key": settings.elevenlabs_api_key},
            max_size=10 * 1024 * 1024,
            ping_interval=20,
        )
        self._recv_task = asyncio.create_task(self._receive_loop())
        logger.info(
            "ElevenLabsSTT started (model=%s, lang=%s).",
            settings.elevenlabs_stt_model,
            settings.elevenlabs_stt_language_code or "auto",
        )

    def is_alive(self) -> bool:
        """Liveness probe for ReconnectingSTT: is the stream still usable?"""
        return self._ws is not None and self._ws.state == WsState.OPEN

    async def send(self, pcm_bytes: bytes):
        if self._ws and self._ws.state == WsState.OPEN:
            b64 = base64.b64encode(pcm_bytes).decode("ascii")
            msg = {
                "message_type": "input_audio_chunk",
                "audio_base_64": b64,
            }
            if self._first_chunk and settings.elevenlabs_stt_context_text:
                msg["previous_text"] = settings.elevenlabs_stt_context_text[:50]
                self._first_chunk = False
            try:
                await self._ws.send(json.dumps(msg))
            except Exception:
                pass

    async def stop(self):
        if self._ws and self._ws.state == WsState.OPEN:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        self._ws = None
        self._recv_task = None
        logger.info("ElevenLabsSTT stopped.")

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                mtype = msg.get("message_type", "")

                if mtype == "partial_transcript":
                    text = msg.get("text", "")
                    if text and self.on_partial:
                        await _safe_call(self.on_partial, text)

                elif mtype in ("committed_transcript", "committed_transcript_with_timestamps"):
                    text = msg.get("text", "")
                    if text and self.on_final:
                        await _safe_call(self.on_final, text.strip())

                elif mtype == "session_started":
                    logger.info("ElevenLabs STT session: %s", msg.get("session_id"))

                elif mtype in (
                    "auth_error",
                    "quota_exceeded",
                    "transcriber_error",
                    "input_error",
                    "rate_limited",
                    "resource_exhausted",
                ):
                    logger.error("ElevenLabs STT error [%s]: %s", mtype, msg)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("ElevenLabs STT receive error: %s", exc, exc_info=True)


async def _safe_call(fn: Callable, text: str) -> None:
    try:
        result = fn(text)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.error("STT callback error: %s", exc)
