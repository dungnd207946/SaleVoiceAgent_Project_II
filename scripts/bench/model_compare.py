"""A/B model chính (qwen3.7-flash vs gemini-2.5-flash...) trên worker /chat local.

Bắn CÙNG một bộ câu hỏi vào worker đang chạy với model cần đo, mỗi câu một
session mới, lặp N lần. Đo hai lớp:

  1. Latency — ttft_ms (server-reported) gộp p50/p95/p99, ghi JSONL đúng schema
     `tests/bench/results/<suite>__<env>.jsonl` để `scripts.bench.print_compare`
     in bảng head-to-head sẵn có.
  2. Hành vi — tool nào được gọi, có gọi data-tool ở vòng đầu không, reply text
     (raw JSONL để diff giữa hai model, soi bịa/độn bằng mắt).

Chạy (worker local phải BẬT TRƯỚC với model + LLM_FORCE_TOOL_FIRST_ROUND cần đo):
    PYTHONPATH=src .venv/bin/python -m noble_agent   # + env model override
    python scripts/bench/model_compare.py --label qwen37-flash --repeat 3
    python scripts/bench/model_compare.py --label gemini25-flash --repeat 3
    python -m scripts.bench.print_compare --suite model

Worker /chat local không cần auth khi GATEWAY_WORKER_SECRET rỗng; tenant lấy
theo TENANT_ID trong .env (mặc định anphu — có KB thật để soi grounded).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from pathlib import Path

import websockets

RESULTS = Path(__file__).resolve().parents[2] / "tests" / "bench" / "results"

# (tag, câu hỏi, kỳ vọng data-tool?) — data-tool = mọi tool trừ no_lookup_needed.
QUESTIONS: list[tuple[str, str, bool]] = [
    ("opener", "Chào em, dự án nào đang mở bán ạ?", True),
    ("empty-filter", "Bên em có dự án nào sắp bàn giao không?", True),
    ("kb-policy", "Chính sách thanh toán của Sunrise City thế nào em?", True),
    ("units", "Căn hộ 2 phòng ngủ ở Sunrise City giá bao nhiêu?", True),
    ("recommend", "Anh có 5 tỷ thì mua căn nào được em?", True),
    ("smalltalk", "Cảm ơn em nhé", False),
]


async def run_turn(port: int, text: str, timeout: float) -> dict:
    """Một session mới → một turn. Trả metrics + tools + reply."""
    out: dict = {"tools": [], "reply": "", "ttft_ms": None, "total_ms": None, "error": None}
    url = f"ws://localhost:{port}/chat?session=cmp{random.randint(10**6, 10**7 - 1)}"
    async with websockets.connect(url, max_size=None) as ws:
        sent = False
        async with asyncio.timeout(timeout):
            while True:
                msg = await ws.recv()
                if not isinstance(msg, str):
                    continue
                ev = json.loads(msg)
                t = ev.get("type")
                if t == "session_id" and not sent:
                    sent = True
                    await ws.send(json.dumps({
                        "type": "set_customer",
                        "identity": {"full_name": "Anh Duy", "phone": f"0912{random.randint(10**6, 10**7 - 1)}"},
                    }))
                    await ws.send(json.dumps({"type": "user_text", "text": text}))
                elif t == "token":
                    out["reply"] += ev.get("text") or ""
                elif t == "tool_start":
                    out["tools"].append(ev.get("tool"))
                elif t == "done":
                    out["ttft_ms"] = ev.get("ttft_ms")
                    out["total_ms"] = ev.get("total_ms")
                    return out
                elif t == "error":
                    out["error"] = ev.get("message")
                    return out


def _pctl(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))
    return float(xs[i])


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", required=True, help="nhãn env_label, vd qwen37-flash / gemini25-flash")
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    latency_f = RESULTS / f"model__{args.label}.jsonl"
    raw_f = RESULTS / f"model_compare_raw__{args.label}.jsonl"

    behavior_rows: list[str] = []
    with latency_f.open("a", encoding="utf-8") as lat, raw_f.open("a", encoding="utf-8") as raw:
        for tag, text, expect_tool in QUESTIONS:
            ttfts: list[float] = []
            data_tool_hits = 0
            errors = 0
            for i in range(args.repeat):
                try:
                    r = await run_turn(args.port, text, args.timeout)
                except (TimeoutError, OSError, websockets.exceptions.WebSocketException) as exc:
                    r = {"tools": [], "reply": "", "ttft_ms": None, "total_ms": None, "error": str(exc)}
                r.update({"tag": tag, "question": text, "label": args.label, "iter": i})
                raw.write(json.dumps(r, ensure_ascii=False) + "\n")
                if r["error"]:
                    errors += 1
                    continue
                if r["ttft_ms"] is not None:
                    ttfts.append(float(r["ttft_ms"]))
                if any(t != "no_lookup_needed" for t in r["tools"]):
                    data_tool_hits += 1
            row = {
                "suite": "model",
                "name": f"chat ttft: {tag}",
                "env_label": args.label,
                "n": len(ttfts),
                "p50_ms": _pctl(ttfts, 0.50),
                "p95_ms": _pctl(ttfts, 0.95),
                "p99_ms": _pctl(ttfts, 0.99),
                "mean_ms": statistics.mean(ttfts) if ttfts else 0.0,
                "stdev_ms": statistics.stdev(ttfts) if len(ttfts) > 1 else 0.0,
                "ts": time.time(),
            }
            lat.write(json.dumps(row, ensure_ascii=False) + "\n")
            ok = data_tool_hits if expect_tool else args.repeat - errors - data_tool_hits
            behavior_rows.append(
                f"  {tag:<14} data-tool {'CẦN' if expect_tool else 'KHÔNG'}: "
                f"{'đạt' if ok == args.repeat - errors else 'LỆCH'} "
                f"({data_tool_hits}/{args.repeat - errors} lượt gọi data-tool"
                f"{', ' + str(errors) + ' lỗi' if errors else ''}) | "
                f"ttft p50={row['p50_ms']:.0f}ms"
            )

    print(f"\n[{args.label}] hành vi ({args.repeat} lượt/câu, tenant local):")
    print("\n".join(behavior_rows))
    print(f"\nlatency  → {latency_f}\nraw turn → {raw_f}")
    print("So sánh: python -m scripts.bench.print_compare --suite model")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
