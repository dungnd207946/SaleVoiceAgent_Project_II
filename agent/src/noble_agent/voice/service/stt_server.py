"""WebSocket server thường trú cho STT (sherpa).

Load recognizer singleton một lần (warmup), rồi mỗi kết nối tạo một SherpaSTT
(per-session OnlineStream, dùng chung recognizer). Forward binary PCM → SherpaSTT;
callback on_partial/on_final → text frame về client. Đóng/eos → stop().

Chạy: `noble-stt-service` hoặc `python -m noble_agent.voice.service.stt_server`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p
from noble_agent.voice.stt.sherpa import SherpaSTT

logger = logging.getLogger("stt_server")


async def handler(websocket) -> None:
    """Một kết nối STT. Tạo SherpaSTT riêng; recognizer singleton dùng chung."""
    if not p.check_token(websocket.request.headers, settings.voice_service_auth_token):
        logger.warning("STT connection rejected: bad/missing auth token")
        await websocket.close(1008, "unauthorized")
        return

    async def on_partial(text: str) -> None:
        await websocket.send(p.transcript_msg(p.PARTIAL, text))

    async def on_final(text: str) -> None:
        await websocket.send(p.transcript_msg(p.FINAL, text))

    stt = SherpaSTT(on_partial=on_partial, on_final=on_final)
    try:
        await stt.start()
        logger.info("STT session started for %s", getattr(websocket.request, "path", "?"))
        async for msg in websocket:
            if isinstance(msg, bytes):
                await stt.send(msg)
            else:
                if p.parse(msg).get("type") == p.EOS:
                    break
    except Exception as exc:  # noqa: BLE001 — kết nối rớt là bình thường
        logger.info("STT session ended: %s", exc)
    finally:
        await stt.stop()


async def _run() -> None:
    from websockets.asyncio.server import serve

    from noble_agent.voice.stt import sherpa as sherpa_mod

    logger.info("STT service: warming recognizer ...")
    sherpa_mod._get_recognizer()  # load model một lần
    logger.info("STT service: recognizer ready")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - một số nền tảng
            loop.add_signal_handler(sig, stop.set)

    async with serve(handler, settings.stt_service_host, settings.stt_service_port, max_size=10 * 1024 * 1024):
        logger.info("STT service listening on %s:%d", settings.stt_service_host, settings.stt_service_port)
        await stop.wait()
    logger.info("STT service stopped.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
