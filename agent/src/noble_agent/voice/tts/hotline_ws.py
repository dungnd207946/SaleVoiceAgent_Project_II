"""Streaming TTS client cho hotline TTS service qua WebSocket (`hotline_ws`).

Drop-in của AsyncVieNeuTTS/RemoteTTS:
    tts = HotlineWsTTS()
    async for chunk in tts.stream("Xin chào"):
        send_audio(chunk)   # PCM int16 bytes

Mỗi lần stream() mở một WS mới (một synth/clause), gửi `{"cmd":"synth"}`, nhận
binary PCM chunk tới khi gặp `{"event":"end"}` rồi đóng. Barge-in: pause() gửi
`{"cmd":"stop"}` (best-effort) rồi đóng WS đang synth.

Giao thức hotline (`cmd`/`event`) KHÁC giao thức `remote` (`type`/`synthesize`/
`end`) trong `protocol.py`; ở đây chỉ tái dùng `auth_headers()` và `parse()`, còn
JSON `cmd`/`event` được dựng inline.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.protocol import State as WsState

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p

logger = logging.getLogger("hotline_ws_tts")

# Strip emoji only — KHÔNG chạm tiếng Việt / CJK. Nhắm các block emoji:
# Misc Symbols/Pictographs U+1F300–U+1FAFF, Transport U+1F680–U+1F6FF,
# Dingbats U+2700–U+27BF, Misc Symbols U+2600–U+26FF, regional indicators
# U+1F1E0–U+1F1FF, variation selector U+FE0F, ZWJ U+200D.
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U0001f680-\U0001f6ff"
    "\U00002700-\U000027bf"
    "\U00002600-\U000026ff"
    "\U0001f1e0-\U0001f1ff"
    "\U0000fe0f"
    "\U0000200d"
    "]+"
)


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text)


class HotlineWsTTS:
    """Client TTS nối tới hotline TTS service (một synth/clause)."""

    def __init__(self):
        self._voice_id: str = settings.vieneu_voice_id or ""
        self._active_ws: websockets.WebSocketClientProtocol | None = None
        self._id: int = 0

    def set_voice(self, voice_id: str) -> None:
        # Voice khóa server-side — store-only no-op để giữ interface.
        self._voice_id = voice_id
        logger.info("HotlineWsTTS voice set to: %s", voice_id)

    async def pause(self) -> None:
        """Barge-in: gửi stop (best-effort) rồi đóng WS đang synth."""
        ws = self._active_ws
        if ws is not None and ws.state == WsState.OPEN:
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"cmd": "stop"}))
            with contextlib.suppress(Exception):
                await ws.close()

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        text = _strip_emoji(text)
        if not text:
            return

        ws = await websockets.connect(
            settings.tts_service_url,
            additional_headers=p.auth_headers(settings.voice_service_auth_token),
            max_size=10 * 1024 * 1024,
            ping_interval=20,
        )
        self._active_ws = ws
        try:
            self._id += 1
            await ws.send(json.dumps({"cmd": "synth", "id": str(self._id), "text": text}))
            async for raw in ws:
                if isinstance(raw, bytes):
                    if raw:
                        yield raw
                else:
                    msg = p.parse(raw)
                    event = msg.get("event")
                    if event == "start":
                        continue
                    if event == "end":
                        reason = msg.get("reason")
                        if reason == "error":
                            logger.error("HotlineWsTTS synth error: %s", msg.get("error"))
                        else:
                            logger.debug("HotlineWsTTS synth end: %s", reason)
                        break
                    if event == "error":
                        logger.error("HotlineWsTTS protocol error: %s", msg.get("error"))
                        break
        except ConnectionClosedOK:
            pass  # normal end, or pause()/barge-in closed the ws — expected
        except ConnectionClosedError as exc:
            logger.warning("HotlineWsTTS stream closed unexpectedly: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("HotlineWsTTS stream error: %s", exc)
        finally:
            self._active_ws = None
            if ws.state == WsState.OPEN:
                with contextlib.suppress(Exception):
                    await ws.close()
