"""One-time voice enrollment — clone a voice from a reference audio clip and
register it under a name (voice_id) on a running TTS service. After this runs
once, use that voice_id like any preset with scripts/try_tts.py — no need to
send the reference clip again.

Chỉ "omnivoice" (:8016), xem docs/voice_cloning.md.

⚠️ BẮT BUỘC --ref-text: service không nạp model ASR nên không tự chép lại lời
trong clip được, phải đưa đúng nguyên văn những gì clip nói.

Giọng enroll được lưu thành .pt trong volume cache của service nên sống qua
restart và redeploy — chạy một lần là đủ.

Chạy đơn giản nhất — sửa khối CẤU HÌNH ngay dưới đây rồi:
    python scripts/enroll_voice.py

CLI vẫn dùng được để override khi cần:
    python scripts/enroll_voice.py --service omnivoice --ref-audio clip.wav \
        --voice-id khach_hang_A --ref-text "Đúng nguyên văn lời trong clip"
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import websockets

# ═══════════════ CẤU HÌNH — sửa trực tiếp ở đây, không cần qua CLI ═══════════════
# REF_AUDIO: đường dẫn tới file .wav trên MÁY BẠN — script tự đọc, KHÔNG cần "upload" đi đâu cả.
REF_AUDIO = "path/to/your/reference-clip.wav"
# VOICE_ID: tên bạn đặt cho giọng này — dùng lại đúng tên này trong scripts/try_tts.py sau khi enroll xong.
VOICE_ID = "khach_hang_A"
SERVICE = "omnivoice"
# REF_TEXT: BẮT BUỘC — đúng nguyên văn lời nói trong REF_AUDIO.
# Sai lời thì giọng clone ra sẽ lệch, service không kiểm tra hộ được.
REF_TEXT = ""
TOKEN = None            # ODYSSEY_MODELS_TOKEN — None nếu service đang tắt auth
# ═══════════════════════════════════════════════════════════════════════════════

_SERVICE_PORTS = {"omnivoice": 8016}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref-audio", default=REF_AUDIO, help="Path to the reference .wav to clone")
    p.add_argument("--voice-id", default=VOICE_ID, help="Name to register the cloned voice under")
    p.add_argument("--service", choices=sorted(_SERVICE_PORTS), default=SERVICE,
                   help="Which service to enroll on (picks the default localhost port)")
    p.add_argument("--ref-text", default=REF_TEXT,
                   help="Nguyên văn lời trong clip — BẮT BUỘC")
    p.add_argument("--url", default=None, help="Full ws:// URL — overrides --service/--host")
    p.add_argument("--host", default="localhost")
    p.add_argument("--token", default=TOKEN, help="ODYSSEY_MODELS_TOKEN — omit if the service has auth off")
    return p.parse_args()


async def enroll(
    url: str, voice_id: str, ref_audio_b64: str, token: str | None, ref_text: str | None
) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        req = {"type": "enroll_voice", "voice_id": voice_id, "ref_audio_b64": ref_audio_b64}
        if ref_text:
            req["ref_text"] = ref_text
        await ws.send(json.dumps(req))
        reply = json.loads(await ws.recv())
    return reply


def main() -> None:
    args = _parse_args()
    ref_path = Path(args.ref_audio)
    if not ref_path.is_file():
        print(f"❌ không tìm thấy file: {ref_path.resolve()}")
        print("   sửa REF_AUDIO ở đầu file (hoặc --ref-audio) trỏ tới file .wav thật trên máy bạn.")
        return

    if not args.ref_text.strip():
        print(f"❌ {args.service} bắt buộc --ref-text (hoặc REF_TEXT ở đầu file).")
        print("   Service này không có ASR để tự chép lời — phải đưa đúng nguyên văn")
        print(f"   những gì {ref_path.name} nói, nếu không giọng clone sẽ lệch.")
        return

    url = args.url or f"ws://{args.host}:{_SERVICE_PORTS[args.service]}/tts"
    ref_audio_b64 = base64.b64encode(ref_path.read_bytes()).decode("ascii")

    print(f"→ {url}  voice_id={args.voice_id!r}  ref_audio={ref_path}")
    t0 = time.monotonic()
    reply = asyncio.run(enroll(url, args.voice_id, ref_audio_b64, args.token, args.ref_text))
    elapsed = time.monotonic() - t0

    if reply.get("type") == "enrolled":
        print(f"✅ enrolled {reply['voice_id']!r} in {elapsed:.1f}s")
        print(
            f'   dùng lại: python scripts/try_tts.py --service {args.service} '
            f'--voice "{args.voice_id}" --text "..."'
        )
    else:
        print(f"❌ enroll thất bại: {reply.get('message', reply)}")


if __name__ == "__main__":
    main()
