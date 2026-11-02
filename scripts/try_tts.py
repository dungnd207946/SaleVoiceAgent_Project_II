"""Manual smoke-test client for the odyssey-models TTS service — sends one
text through the shared WebSocket protocol (see docs/remote_stt_tts_spect.md)
and saves the reply as a playable .wav.

    tts-omnivoice  :8016  OmniVoice / santa-tts-omnivoice (our fine-tune)

Chạy đơn giản nhất — sửa khối CẤU HÌNH ngay dưới đây rồi:
    python scripts/try_tts.py

CLI vẫn dùng được để override khi cần (không sửa file mỗi lần đổi 1 giá trị):
    python scripts/try_tts.py --service omnivoice --text "Xin chào"
    python scripts/try_tts.py --url ws://localhost:8016/tts --text "..." --out out.wav

The target service must already be running (see README.md's "Running
OmniVoice locally" section).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

import websockets

SAMPLE_RATE = 24000  # fixed by the shared WS protocol

# Mặc định lưu vào đây (cạnh chính file script này) — CỐ ĐỊNH bất kể bạn chạy
# lệnh từ thư mục nào, để không bao giờ phải đoán file audio vừa sinh ra nằm ở đâu.
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# ═══════════════ CẤU HÌNH — sửa trực tiếp ở đây, không cần qua CLI ═══════════════
TEXT = "Green Horizon Residence là dự án chung cư cao cấp tọa lạc tại khu vực phía Tây Hà Nội, gồm 3 tòa tháp cao 28 tầng với khoảng 1.200 căn hộ có diện tích từ 45–120 m², thiết kế từ 1 đến 3 phòng ngủ. Dự án sở hữu hệ thống tiện ích đồng bộ như bể bơi bốn mùa, phòng gym, khu vui chơi trẻ em, vườn dạo bộ, trung tâm thương mại, trường mầm non và bãi đỗ xe thông minh. Với không gian xanh rộng rãi, an ninh 24/7 và khả năng kết nối thuận tiện tới các tuyến đường lớn, Green Horizon Residence hướng tới một môi trường sống hiện đại, tiện nghi và phù hợp cho các gia đình trẻ."
SERVICE = "omnivoice"
VOICE = None                # None để dùng giọng mặc định của service
TOKEN = None                # ODYSSEY_MODELS_TOKEN — None nếu service đang tắt auth
OUT_PATH = None             # None → tự đặt tên "out_<service>.wav"
# ═══════════════════════════════════════════════════════════════════════════════

_SERVICE_PORTS = {
    "omnivoice": 8016,
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--text", default=TEXT, help="Text to synthesize (default: TEXT ở đầu file)")
    p.add_argument("--service", choices=sorted(_SERVICE_PORTS), default=SERVICE,
                   help="Which service to hit (picks the default localhost port)")
    p.add_argument("--url", default=None, help="Full ws:// URL — overrides --service/--host")
    p.add_argument("--host", default="localhost", help="Host, used with --service (default localhost)")
    p.add_argument("--voice", default=VOICE,
                   help="Voice/preset id (optional — falls back to the service's own default)")
    p.add_argument("--token", default=TOKEN, help="ODYSSEY_MODELS_TOKEN — omit if the service has auth off")
    p.add_argument("--out", default=OUT_PATH,
                   help=f"Output .wav path (default: {OUTPUT_DIR}/out_<service>.wav)")
    return p.parse_args()


async def synthesize(url: str, text: str, voice: str | None, token: str | None) -> tuple[bytes, float, float]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    t0 = time.monotonic()
    first_ms = None
    chunks: list[bytes] = []
    async with websockets.connect(url, additional_headers=headers) as ws:
        req = {"type": "synthesize", "text": text}
        if voice:
            req["voice"] = voice
        await ws.send(json.dumps(req))
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                if first_ms is None:
                    first_ms = (time.monotonic() - t0) * 1000
                chunks.append(msg)
            else:
                data = json.loads(msg)
                if data.get("type") == "end":
                    break
    total_ms = (time.monotonic() - t0) * 1000
    return b"".join(chunks), (first_ms or 0.0), total_ms


def main() -> None:
    args = _parse_args()
    url = args.url or f"ws://{args.host}:{_SERVICE_PORTS[args.service]}/tts"
    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"out_{args.service}.wav"

    print(f"→ {url}  text={args.text!r}  voice={args.voice or '(default)'}")
    pcm, ttfb_ms, total_ms = asyncio.run(synthesize(url, args.text, args.voice, args.token))

    if not pcm:
        print("⚠️  no audio returned (empty text, or synth error — check the service's own log)")
        return

    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)

    duration_s = len(pcm) / 2 / SAMPLE_RATE
    print(f"✅ {len(pcm)} bytes (~{duration_s:.2f}s audio), ttfb={ttfb_ms:.0f}ms total={total_ms:.0f}ms")
    print(f"   saved → {out_path}")


if __name__ == "__main__":
    main()
