"""CLI for the e2e scenario harness.

    python -m tests.e2e_scenarios [--scenario NAME] [--model MODEL] [-v]

Exit code is non-zero if any scenario fails, so it drops into CI unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

_GREEN, _RED, _DIM, _RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m tests.e2e_scenarios")
    p.add_argument("--scenario", help="Run only the scenario with this name (default: all)")
    p.add_argument("--model", help="Pin NOBLE_AGENT_MODEL for the run (must match a configured <P>_MODEL)")
    p.add_argument("-v", "--verbose", action="store_true", help="Print each turn's reply + tool calls")
    p.add_argument("--json", action="store_true", help="Emit a machine-readable JSON summary (used by compare.py)")
    return p.parse_args(argv)


def _report_json(results) -> bool:
    """Print one JSON object to stdout. Return True if all scenarios passed."""
    payload = {
        "scenarios": [
            {
                "name": sr.scenario.name,
                "ok": sr.ok,
                "error": sr.error,
                "failed": [f"turn{i}:{a.kind}" for i, t in enumerate(sr.turns) for a in t.assertions if not a.ok],
            }
            for sr in results
        ],
    }
    payload["passed"] = sum(1 for s in payload["scenarios"] if s["ok"])
    payload["total"] = len(payload["scenarios"])
    print(json.dumps(payload, ensure_ascii=False))
    return all(s["ok"] for s in payload["scenarios"])


def _report(results, verbose: bool) -> bool:
    """Print a terminal report. Return True if all scenarios passed."""
    all_ok = True
    for sr in results:
        head = f"{_GREEN}PASS{_RESET}" if sr.ok else f"{_RED}FAIL{_RESET}"
        print(f"\n[{head}] {sr.scenario.name} — {sr.scenario.description}")
        if sr.error:
            all_ok = False
            print(f"  {_RED}ERROR:{_RESET} {sr.error}")
            continue
        for i, t in enumerate(sr.turns):
            mark = f"{_GREEN}✓{_RESET}" if t.ok else f"{_RED}✗{_RESET}"
            print(f"  {mark} turn {i}: {t.turn.user}")
            if verbose:
                calls = ", ".join(f"{c.name}({c.args})" for c in t.result.tool_calls) or "—"
                print(f"      {_DIM}tools: {calls}{_RESET}")
                print(f"      {_DIM}reply: {t.result.reply[:200]}{_RESET}")
            for a in t.assertions:
                if not a.ok:
                    all_ok = False
                    print(f"      {_RED}✗ {a.kind}:{_RESET} {a.detail}")
    passed = sum(1 for r in results if r.ok)
    print(f"\n{'=' * 60}\n{passed}/{len(results)} scenarios passed")
    return all_ok


async def _run(args: argparse.Namespace) -> bool:
    # Import after env is set (see main) so config picks up --model.
    from tests.e2e_scenarios.loader import load_scenarios
    from tests.e2e_scenarios.runner import run_scenario

    scenarios = load_scenarios(_SCENARIOS_DIR)
    if args.scenario:
        scenarios = [s for s in scenarios if s.name == args.scenario]
        if not scenarios:
            print(f"{_RED}No scenario named {args.scenario!r} in {_SCENARIOS_DIR}{_RESET}")
            return False
    results = [await run_scenario(s) for s in scenarios]
    if args.json:
        return _report_json(results)
    return _report(results, args.verbose)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.model:
        # Set BEFORE noble_agent.config is imported so pydantic-settings reads it.
        os.environ["NOBLE_AGENT_MODEL"] = args.model
    ok = asyncio.run(_run(args))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
