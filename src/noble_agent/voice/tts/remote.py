"""Streaming TTS client cho service `tts_server` qua WebSocket.

Drop-in của AsyncVieNeuTTS/AsyncElevenLabsTTS:
    tts = RemoteTTS()
    async for chunk in tts.stream("Xin chào"):
        send_audio(chunk)   # PCM int16 bytes

Mỗi lần stream() mở một WS mới (như elevenlabs), gửi 1 yêu cầu synthesize, nhận
binary PCM chunk tới khi gặp {"type":"end"} rồi đóng. Barge-in: pause() đóng WS
đang synth → server thấy ConnectionClosed và dừng (xem ghi chú cancel trong plan).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.protocol import State as WsState

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p

logger = logging.getLogger("remote_tts")


class RemoteTTS:
    """Client TTS nối tới service vieneu từ xa (một synth/lần)."""

    def __init__(self):
        self._voice_id: str = settings.vieneu_voice_id or ""
        self._active_ws: websockets.WebSocketClientProtocol | None = None

    def set_voice(self, voice_id: str) -> None:
        self._voice_id = voice_id
        logger.info("RemoteTTS voice set to: %s", voice_id)

    async def pause(self) -> None:
        """Barge-in: đóng WS đang synth để hủy lần tổng hợp hiện tại."""
        ws = self._active_ws
        if ws is not None and ws.state == WsState.OPEN:
            with contextlib.suppress(Exception):
                await ws.close()

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        ws = await websockets.connect(
            settings.tts_service_url,
            additional_headers=p.auth_headers(settings.voice_service_auth_token),
            max_size=10 * 1024 * 1024,
            ping_interval=20,
        )
        self._active_ws = ws
        try:
            await ws.send(p.synthesize_msg(text, voice=self._voice_id or None))
            async for raw in ws:
                if isinstance(raw, bytes):
                    if raw:
                        yield raw
                else:
                    if p.parse(raw).get("type") == p.END:
                        break
        except ConnectionClosedOK:
            pass  # normal end, or pause()/barge-in closed the ws — expected
        except ConnectionClosedError as exc:
            logger.warning("RemoteTTS stream closed unexpectedly: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("RemoteTTS stream error: %s", exc)
        finally:
            self._active_ws = None
            if ws.state == WsState.OPEN:
                with contextlib.suppress(Exception):
                    await ws.close()
