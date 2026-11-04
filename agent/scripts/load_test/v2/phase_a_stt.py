"""Load client for the STT service (:8012). WS: blast PCM16 16kHz frames, then wait
for {"type":"final"}. Latency = start → final (raw decode throughput).

Do NOT send an `eos` here: `eos` makes the server break its read loop and stop the
recognizer, which races the background decode thread and can drop the final. Instead
the fixture carries 3.0 s of trailing silence so sherpa's endpoint rule (rule2,
1.2 s min trailing silence) fires on its own; then we close the socket.

Fixture = a real ~3.4 s Vietnamese utterance resampled to 16 kHz + 3.0 s trailing
silence. Built once by `build_stt_fixture.py`; committed as `fixture_16k.pcm` so this
client needs no audio libs at runtime."""
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
URL = ENV["STT_SERVICE_URL"]
TOKEN = (ENV.get("VOICE_SERVICE_AUTH_TOKEN") or "").strip()

_FRAME = 320  # 20 ms @ 16 kHz (samples); 640 bytes/frame
_AUDIO = (Path(__file__).resolve().parent / "fixture_16k.pcm").read_bytes()


async def _transcribe_once() -> float:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    t0 = time.monotonic()
    got_final = asyncio.Event()
    async with websockets.connect(URL, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        async def recv() -> None:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                if json.loads(raw).get("type") == "final":
                    got_final.set()
                    return

        rx = asyncio.create_task(recv())
        for off in range(0, len(_AUDIO), _FRAME * 2):
            await ws.send(_AUDIO[off:off + _FRAME * 2])
        try:
            await asyncio.wait_for(got_final.wait(), timeout=15.0)
        finally:
            rx.cancel()
    return time.monotonic() - t0


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=64)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()
    print(f"STT load → {URL} (CPU-bound, sherpa)")
    result = await common.run_campaign(
        _transcribe_once, label="stt :8012",
        ramp=common.ramp_schedule(max_concurrency=args.max), hold_s=args.hold,
        full_ramp=True,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "stt_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'stt_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
