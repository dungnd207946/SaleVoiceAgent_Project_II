"""Chat-WS end-to-end load client (:8766/chat). Each virtual user holds one WS session
and loops scripted turns; per-turn latency = send user_text → receive `done`.
Reuses common.* for percentiles/break-detection/report. Trailing `suggestions` ignored."""
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
_HOST = "10.50.12.70"
_PORT = ENV.get("WS_PORT", "8766")
BASE = f"ws://{_HOST}:{_PORT}/chat"

TURNS = [
    "Chào em, cho anh hỏi Noble có những dự án nào?",
    "Dự án nào ở khu vực trung tâm và tầm giá khoảng 3 tỷ?",
    "Cho anh xin thông tin chi tiết dự án đó với.",
    "Anh muốn đặt lịch tham quan cuối tuần này được không?",
]


async def _run_turn(ws, text: str) -> float:
    t0 = time.monotonic()
    await ws.send(json.dumps({"type": "user_text", "text": text}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
        if not isinstance(raw, str):
            continue
        if json.loads(raw).get("type") == "done":
            return time.monotonic() - t0


async def _session_worker(idx: int, deadline: float, latencies: list[float], counters: dict) -> None:
    sid = f"load-{idx}-{int(deadline)}"
    try:
        async with websockets.connect(f"{BASE}?session={sid}", max_size=10 * 1024 * 1024) as ws:
            await asyncio.wait_for(ws.recv(), timeout=10.0)  # drain {"type":"session_id"} greeting
            i = 0
            while time.monotonic() < deadline:
                text = TURNS[i % len(TURNS)]
                i += 1
                try:
                    latencies.append(await _run_turn(ws, text))
                    counters["ok"] += 1
                except Exception:
                    counters["failed"] += 1
    except Exception:
        counters["failed"] += 1


async def _step(concurrency: int, hold_s: float) -> common.StepResult:
    latencies: list[float] = []
    counters = {"ok": 0, "failed": 0}
    start = time.monotonic()
    deadline = start + hold_s
    await asyncio.gather(*[_session_worker(i, deadline, latencies, counters) for i in range(concurrency)])
    dur = time.monotonic() - start
    total = counters["ok"] + counters["failed"]
    return common.StepResult(
        concurrency=concurrency, duration_s=dur, total=total,
        ok=counters["ok"], failed=counters["failed"],
        latency=common.percentiles(latencies),
        err_rate=(counters["failed"] / total) if total else 0.0,
    )


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=128)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()
    print(f"chat load → {BASE}")
    baseline = await _step(1, args.hold)
    result = common.CampaignResult(label="chat :8766", baseline_p95=baseline.latency.get("p95", 0.0),
                                   steps=[baseline])
    for c in common.ramp_schedule(max_concurrency=args.max):
        if c <= 1:
            continue
        result.steps.append(await _step(c, args.hold))
    result.knee = common.knee_by_plateau(result.steps)
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "chat_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'chat_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
