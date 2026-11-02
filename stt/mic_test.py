"""Test STT + hotwords qua micro — không cần Docker.

Thu âm mic 16 kHz mono, stream PCM16 lên STT WS server, in partial/final ra
terminal. Hotwords per-session gửi qua config frame (--hotwords), hotwords
global thì server tự nạp từ STT_HOTWORDS_FILE — script này không cần biết.

Chạy server local (venv có sherpa-onnx numpy "websockets>=12"):
  STT_MODEL_DIR=<dir model> \
  STT_HOTWORDS_FILE=<hotwords.txt> \
  STT_BPE_VOCAB=<bpe.vocab> \
  STT_PRESERVE_CASE=true \
  python stt_server.py

Rồi (venv có thêm sounddevice — cần libportaudio2 trên Linux):
  python mic_test.py                                    # dùng hotwords global của server
  python mic_test.py --hotwords "noblex :2.0/noble city"  # thêm hotwords riêng phiên này
Ctrl+C để dừng.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import sounddevice as sd
import websockets

SAMPLE_RATE = 16000
CHUNK_MS = 100  # 100ms/chunk — nhỏ hơn nữa không giúp gì, to hơn tăng trễ partial


def _pick_device(requested: str) -> int | str:
    """Chọn input device mở được 16 kHz mono int16.

    Mic ALSA hw thường không hỗ trợ 16 kHz trực tiếp (paInvalidSampleRate) —
    ưu tiên nguồn PulseAudio/PipeWire vì nó tự resample. --device để ép tay
    (index hoặc tên); xem danh sách bằng: python -m sounddevice
    """
    def _opens(dev) -> bool:
        try:
            sd.check_input_settings(device=dev, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
            return True
        except Exception:
            return False

    if requested:
        dev = int(requested) if requested.isdigit() else requested
        if not _opens(dev):
            sys.exit(f"❌ device {requested!r} không mở được {SAMPLE_RATE} Hz mono int16")
        return dev
    pulse_first = sorted(
        (i for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0),
        key=lambda i: "pulse" not in sd.query_hostapis(sd.query_devices(i)["hostapi"])["name"].lower(),
    )
    for i in pulse_first:
        if _opens(i):
            return i
    sys.exit(f"❌ Không input device nào mở được {SAMPLE_RATE} Hz — xem `python -m sounddevice`")


async def run(url: str, hotwords: str, token: str, device: str) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with websockets.connect(url, max_size=None, additional_headers=headers) as ws:
        if hotwords:
            await ws.send(json.dumps({"type": "config", "hotwords": hotwords}))
            print(f"🔥 hotwords phiên này: {hotwords}")

        loop = asyncio.get_running_loop()
        audio_q: asyncio.Queue[bytes] = asyncio.Queue()

        def on_audio(indata, frames, time_info, status):  # chạy trên thread PortAudio
            if status:
                print(f"⚠️  {status}", file=sys.stderr)
            loop.call_soon_threadsafe(audio_q.put_nowait, bytes(indata))

        async def sender():
            while True:
                await ws.send(await audio_q.get())

        async def receiver():
            async for msg in ws:
                d = json.loads(msg)
                if d["type"] == "partial":
                    # partial đè lên cùng dòng; final xuống dòng mới
                    print(f"\r✏️  {d['text']}\x1b[K", end="", flush=True)
                elif d["type"] == "final":
                    print(f"\r📝 {d['text']}\x1b[K")

        dev = _pick_device(device)
        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=dev,
            blocksize=SAMPLE_RATE * CHUNK_MS // 1000, callback=on_audio,
        )
        print(f"🎙️  Đang nghe mic ({sd.query_devices(dev)['name']}) — nói đi, Ctrl+C để dừng.")
        with stream:
            try:
                await asyncio.gather(sender(), receiver())
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                await ws.send(json.dumps({"type": "eos"}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="ws://127.0.0.1:8113", help="STT WS endpoint")
    ap.add_argument("--hotwords", default="", help='hotwords phiên này, VD "noblex :2.0/noble city"')
    ap.add_argument("--token", default="", help="bearer token nếu server bật auth")
    ap.add_argument("--device", default="", help="input device (index/tên) — xem `python -m sounddevice`")
    args = ap.parse_args()
    try:
        asyncio.run(run(args.url, args.hotwords, args.token, args.device))
    except KeyboardInterrupt:
        print("\n👋 dừng.")


if __name__ == "__main__":
    main()
