"""Run noisy utterances through StreamingLLM (text); write accuracy report.

Requires API keys like normal app. Usage:
  python data/test_noisy/test_noisy_pipeline.py --input data/test_noisy/noisy_queries.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


async def _run_noisy_row(llm, row: dict) -> dict:
    noisy = row.get("noisy_text") or row.get("text") or ""
    exp_tools = set(row.get("expected_tools") or [])
    t0 = time.monotonic()

    class _RowBuf:
        __slots__ = ("tokens", "tools")

        def __init__(self) -> None:
            self.tokens: list[str] = []
            self.tools: list[str] = []

    buf = _RowBuf()

    def on_token(t: str) -> None:
        buf.tokens.append(t)

    def on_tool_start(name: str, _args: object) -> None:
        buf.tools.append(name)

    try:
        await llm.stream_response(noisy, on_token=on_token, on_tool_start=on_tool_start)
    except Exception as e:
        buf.tokens.append(f"[ERROR: {e}]")

    total_ms = (time.monotonic() - t0) * 1000
    agent = llm._current_agent
    tools_called = buf.tools
    tokens = buf.tokens
    got_tools = set(tools_called)
    tools_ok = exp_tools.issubset(got_tools) if exp_tools else True
    return {
        "noisy_text": noisy[:120],
        "agent": agent,
        "expected_agent": row.get("expected_agent"),
        "tools_called": tools_called,
        "expected_tools": list(exp_tools),
        "tools_expected_met": tools_ok,
        "total_ms": round(total_ms, 1),
        "response_preview": "".join(tokens)[:200],
    }


async def run_file(path: Path, out_path: Path) -> None:
    from noble_agent.agent.llm.streaming import StreamingLLM

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries") or data.get("rows") or []
    if not entries:
        print("No entries in input JSON")
        return

    results: list[dict] = []
    llm = await StreamingLLM.create("noisy-test")

    for row in entries:
        results.append(await _run_noisy_row(llm, row))

    n = len(results)
    tool_rate = sum(1 for r in results if r["tools_expected_met"]) / n if n else 0.0
    nonempty = sum(1 for r in results if len(r.get("response_preview", "").strip()) > 5) / n if n else 0.0
    agent_hits = sum(1 for r in results if r.get("expected_agent") and r.get("agent") == r.get("expected_agent"))
    agent_denom = sum(1 for r in results if r.get("expected_agent"))
    agent_rate = agent_hits / agent_denom if agent_denom else None

    summary = {
        "count": n,
        "tools_expected_met_rate": round(tool_rate, 3),
        "nonempty_response_rate": round(nonempty, 3),
        "agent_match_rate": round(agent_rate, 3) if agent_rate is not None else None,
        "agent_match_hits": agent_hits,
        "agent_match_total": agent_denom,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {out_path}")


def main() -> None:
    p = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    p.add_argument("--input", default=str(here / "noisy_queries.json"))
    p.add_argument("--output", default=str(here / "noisy_report.json"))
    args = p.parse_args()
    asyncio.run(run_file(Path(args.input), Path(args.output)))


if __name__ == "__main__":
    main()
