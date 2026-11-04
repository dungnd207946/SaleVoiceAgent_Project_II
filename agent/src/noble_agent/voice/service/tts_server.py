"""WebSocket server thường trú cho TTS (vieneu).

Load model singleton một lần (warmup) qua AsyncVieNeuTTS/_load_tts. Mỗi kết nối
nhận các yêu cầu {"type":"synthesize","text":...,"voice"?:...}; stream binary PCM
int16 24kHz từng chunk rồi gửi {"type":"end"}. `_inference_lock` toàn cục trong
vieneu.py tuần tự hóa GPU giữa mọi kết nối (đánh đổi đã chọn: 1 model, hàng đợi).

Client đóng WS giữa chừng (barge-in) → ws.send raise ConnectionClosed → handler
thoát. Vì mỗi synthesize chỉ là một clause nên đủ ngắn.

Chạy: `noble-tts-service` hoặc `python -m noble_agent.voice.service.tts_server`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import threading

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p

logger = logging.getLogger("tts_server")


def _make_tts():
    """Build the TTS engine selected by `settings.tts_service_engine`.

    Both backends expose the SAME async interface (stream/set_voice/pause/
    list_voices) so the handler is engine-agnostic. Lazy imports keep the unused
    backend's heavy deps out of the process.
      - "vieneu"      → in-process transformers backbone + token streaming (GPU here)
      - "vieneu_vllm" → client to a separate vLLM server (codec runs here, backbone in vLLM)
    """
    if settings.tts_service_engine == "vieneu_vllm":
        from noble_agent.voice.tts.vieneu_vllm import AsyncVieNeuVLLMTTS

        return AsyncVieNeuVLLMTTS()
    from noble_agent.voice.tts.vieneu import AsyncVieNeuTTS

    return AsyncVieNeuTTS()


async def handler(websocket) -> None:
    """Một kết nối TTS; phục vụ nhiều yêu cầu synthesize tuần tự."""
    if not p.check_token(websocket.request.headers, settings.voice_service_auth_token):
        logger.warning("TTS connection rejected: bad/missing auth token")
        await websocket.close(1008, "unauthorized")
        return

    try:
        tts = _make_tts()  # engine selected by settings.tts_service_engine (warmed at startup)
        async for msg in websocket:
            if isinstance(msg, bytes):
                continue  # TTS client chỉ gửi text control
            data = p.parse(msg)
            if data.get("type") != p.SYNTHESIZE:
                continue
            voice = data.get("voice")
            if voice:
                tts.set_voice(voice)
            text = data.get("text", "")
            if not text:
                await websocket.send(p.control_msg(p.END))
                continue
            # Per-synthesize barge-in event: if the client drops mid-stream, set it so
            # the remote GPU generate thread aborts on its next token instead of running
            # to EOS (today the WS just sees ConnectionClosed at the next send).
            stop_event = threading.Event()
            try:
                async for chunk in tts.stream(text, stop_event=stop_event):
                    if chunk:
                        await websocket.send(chunk)  # binary PCM
            except Exception:
                stop_event.set()  # cancel the GPU generate thread, then re-raise
                raise
            await websocket.send(p.control_msg(p.END))
    except Exception as exc:  # noqa: BLE001 — kết nối rớt/barge-in là bình thường
        logger.info("TTS session ended: %s", exc)


async def _run() -> None:
    from websockets.asyncio.server import serve

    # Warm the selected engine once: vieneu → load the GPU backbone; vieneu_vllm →
    # load the local codec singleton AND probe the vLLM /health (fail-fast if the
    # vLLM server isn't up, so the operator sees it at startup, not on first call).
    logger.info("TTS service: engine=%s — warming up ...", settings.tts_service_engine)
    _make_tts()
    logger.info("TTS service: model ready")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover
            loop.add_signal_handler(sig, stop.set)

    async with serve(handler, settings.tts_service_host, settings.tts_service_port, max_size=10 * 1024 * 1024):
        logger.info("TTS service listening on %s:%d", settings.tts_service_host, settings.tts_service_port)
        await stop.wait()
    logger.info("TTS service stopped.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
