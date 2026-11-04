"""Đo TTFB streaming: Soniox WebSocket vs ElevenLabs REST /stream.

Tình huống mô phỏng: LLM đã sinh xong câu trả lời -> đẩy toàn bộ text vào TTS,
đo thời gian tới byte audio ĐẦU TIÊN (quyết định độ trễ cảm nhận của voice agent).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import websockets
from _common import UA, api_key, ssl_context

SONIOX_WS = "wss://tts-rt.soniox.com/tts-websocket"
EL_STREAM = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
SSL_CTX = ssl_context()


async def soniox_ws_ttfb(cfg: dict, text: str, api_key: str) -> dict:
    """Trả về TTFB (tới audio chunk đầu) và tổng thời gian sinh xong."""
    config = {
        "api_key": api_key,
        "model": cfg["model"],
        "language": "vi",
        "voice": cfg["voice"],
        "audio_format": cfg.get("audio_format", "mp3"),
        "speed": cfg.get("speed", 1.0),
        "stream_id": "bench-1",
    }
    if config["audio_format"] != "mp3":
        config["sample_rate"] = cfg.get("sample_rate", 24000)
    else:
        config["sample_rate"] = 44100
        config["bitrate"] = 128000

    audio = bytearray()
    start = time.perf_counter()
    ttfb = None
    async with websockets.connect(SONIOX_WS, ssl=SSL_CTX, additional_headers={"User-Agent": UA}) as ws:
        connected = time.perf_counter() - start
        await ws.send(json.dumps(config))
        await ws.send(json.dumps({"text": text, "text_end": True, "stream_id": "bench-1"}))
        sent = time.perf_counter()
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            msg = json.loads(raw)
            if msg.get("error_code") or msg.get("error_type"):
                raise RuntimeError(f"soniox ws error: {raw[:300]}")
            chunk = msg.get("audio")
            if chunk:
                if ttfb is None:
                    ttfb = time.perf_counter() - sent
                audio.extend(base64.b64decode(chunk))
            if msg.get("terminated") or msg.get("audio_end"):
                break
    total = time.perf_counter() - sent
    return {
        "ttfb_s": round(ttfb, 3) if ttfb else None,
        "total_s": round(total, 3),
        "connect_s": round(connected, 3),
        "bytes": len(audio),
        "audio": bytes(audio),
    }


def el_stream_ttfb(cfg: dict, text: str, api_key: str) -> dict:
    body = {
        "text": text,
        "model_id": cfg["model"],
        "voice_settings": {
            "stability": cfg.get("stability", 1.0),
            "similarity_boost": cfg.get("similarity_boost", 0.75),
            "speed": cfg.get("speed", 1.0),
        },
    }
    if cfg.get("language_code"):
        body["language_code"] = cfg["language_code"]
    # ElevenLabs nhận output_format / optimize_streaming_latency qua QUERY param,
    # không phải body -- đặt trong body thì bị bỏ qua và trả mp3_44100_128 mặc định.
    params = {"output_format": cfg.get("output_format", "mp3_44100_128")}
    if cfg.get("optimize_streaming_latency") is not None:
        params["optimize_streaming_latency"] = str(cfg["optimize_streaming_latency"])
    url = EL_STREAM.format(voice=cfg["voice"]) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    audio = bytearray()
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
            first = resp.read(1)
            ttfb = time.perf_counter() - start
            audio.extend(first)
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                audio.extend(chunk)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
    total = time.perf_counter() - start
    return {
        "ttfb_s": round(ttfb, 3),
        "total_s": round(total, 3),
        "connect_s": None,
        "bytes": len(audio),
        "audio": bytes(audio),
    }


async def main() -> None:
    base = Path(__file__).parent
    cases = {c["id"]: c for c in json.loads((base / "cases.json").read_text())}
    case = cases[os.environ.get("CASE", "greet")]
    iters = int(os.environ.get("ITERS", "5"))
    sk = api_key("soniox")
    ek = api_key("elevenlabs")

    targets = [
        ("soniox-v2-ws-mp3", "ws", {"model": "tts-rt-v2", "voice": "Nina", "speed": 1.15, "audio_format": "mp3"}),
        (
            "soniox-v2-ws-mulaw8k",
            "ws",
            {"model": "tts-rt-v2", "voice": "Nina", "speed": 1.15, "audio_format": "pcm_mulaw", "sample_rate": 8000},
        ),
        (
            "soniox-v2-ws-pcm16k",
            "ws",
            {"model": "tts-rt-v2", "voice": "Nina", "speed": 1.15, "audio_format": "pcm_s16le", "sample_rate": 16000},
        ),
        (
            "el-flash-v2_5-stream",
            "rest",
            {"model": "eleven_flash_v2_5", "voice": "iSFxP4Z6YNcx9OXl62Ic", "language_code": "vi", "speed": 1.13},
        ),
        (
            "el-flash-v2_5-stream-ulaw8k",
            "rest",
            {
                "model": "eleven_flash_v2_5",
                "voice": "iSFxP4Z6YNcx9OXl62Ic",
                "language_code": "vi",
                "speed": 1.13,
                "output_format": "ulaw_8000",
            },
        ),
        (
            "el-flash-v2_5-stream-pcm16k",
            "rest",
            {
                "model": "eleven_flash_v2_5",
                "voice": "iSFxP4Z6YNcx9OXl62Ic",
                "language_code": "vi",
                "speed": 1.13,
                "output_format": "pcm_16000",
            },
        ),
    ]

    results = []
    for name, kind, cfg in targets:
        samples, err, last = [], None, None
        for _ in range(iters):
            try:
                last = (
                    (await soniox_ws_ttfb(cfg, case["text"], sk))
                    if kind == "ws"
                    else el_stream_ttfb(cfg, case["text"], ek)
                )
                samples.append(last)
            except Exception as exc:  # noqa: BLE001 - báo cáo mọi lỗi provider
                err = f"{type(exc).__name__}: {exc}"
                print(f"FAIL {name}: {err}", file=sys.stderr, flush=True)
                break
            await asyncio.sleep(0.5)
        if not samples:
            results.append({"target": name, "error": err})
            continue
        ttfbs = [s["ttfb_s"] for s in samples if s["ttfb_s"] is not None]
        results.append(
            {
                "target": name,
                "kind": kind,
                "case": case["id"],
                "iters": len(samples),
                "ttfb_min_s": min(ttfbs),
                "ttfb_median_s": round(statistics.median(ttfbs), 3),
                "ttfb_max_s": max(ttfbs),
                "total_median_s": round(statistics.median(s["total_s"] for s in samples), 3),
                "connect_median_s": round(
                    statistics.median([s["connect_s"] for s in samples if s["connect_s"] is not None]), 3
                )
                if samples[0]["connect_s"] is not None
                else None,
                "bytes": samples[-1]["bytes"],
            }
        )
        print(
            f"OK  {name:30s} ttfb min/med/max = {min(ttfbs):.3f}/{statistics.median(ttfbs):.3f}/{max(ttfbs):.3f}s",
            flush=True,
        )
        ext = "ulaw" if "ulaw" in name or "mulaw" in name else "pcm" if "pcm" in name else "mp3"
        (base / "out" / f"stream_{case['id']}__{name}.{ext}").write_bytes(last["audio"])

    name_out = os.environ.get("RESULTS_FILE", "results_stream.json")
    (base / name_out).write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n-> {name_out}")


if __name__ == "__main__":
    asyncio.run(main())
