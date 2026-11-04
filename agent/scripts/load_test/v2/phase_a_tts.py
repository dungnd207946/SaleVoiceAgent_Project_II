"""Load client for the TTS service (:8011). WS: send {"type":"synthesize",...}, drain
binary PCM until {"type":"end"}. Protocol inlined (3 keys) to keep this dependency-light."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import websockets
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
URL = ENV["TTS_SERVICE_URL"]
TOKEN = (ENV.get("VOICE_SERVICE_AUTH_TOKEN") or "").strip()
VOICE = (ENV.get("VIENEU_VOICE_ID") or "").strip() or None
TEXT = "Dạ em xin phép giới thiệu về dự án của Noble, đây là một dự án căn hộ cao cấp rất đáng để anh chị tham khảo ạ."


async def _synth_once() -> float:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    t0 = time.monotonic()
    msg = {"type": "synthesize", "text": TEXT}
    if VOICE:
        msg["voice"] = VOICE
    async with websockets.connect(URL, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(msg))
        got_audio = False
        async for raw in ws:
            if isinstance(raw, bytes):
                got_audio = got_audio or bool(raw)
            elif json.loads(raw).get("type") == "end":
                break
    if not got_audio:
        raise ValueError("no PCM received")
    return time.monotonic() - t0


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=64)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()
    print(f"TTS load → {URL} (GPU-bound, serial synth expected)")
    result = await common.run_campaign(
        _synth_once, label="tts :8011",
        ramp=common.ramp_schedule(max_concurrency=args.max), hold_s=args.hold,
        full_ramp=True,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "tts_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'tts_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
