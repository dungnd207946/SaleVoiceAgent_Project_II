"""Compare models on the e2e scenario bank by pass-rate over N repeats.

    python -m tests.e2e_scenarios.compare --models gemini-2.5-flash,qwen3.6-flash --repeat 3

The agent is non-deterministic, so a single run per model is not a fair
comparison. This runs the full CLI in a FRESH subprocess for each (model,
repeat) — so `--model`/`NOBLE_AGENT_MODEL` is read at config-import time and the
runner singleton is clean — collects the `--json` summary, and reports the
per-scenario pass-rate (k of N) side by side.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict


def _run_once(model: str, scenario: str | None, timeout: int) -> dict | None:
    """One full CLI run in a subprocess. Returns the parsed JSON summary, or None on crash."""
    cmd = [sys.executable, "-m", "tests.e2e_scenarios", "--json", "--model", model]
    if scenario:
        cmd += ["--scenario", scenario]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tests.e2e_scenarios.compare")
    p.add_argument("--models", default="gemini-2.5-flash,qwen3.6-flash", help="Comma-separated model names")
    p.add_argument("--repeat", type=int, default=3, help="Runs per model (default 3)")
    p.add_argument("--scenario", help="Compare only this scenario (default: all)")
    p.add_argument("--timeout", type=int, default=600, help="Per-run subprocess timeout (s)")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    passed: dict[tuple[str, str], int] = defaultdict(int)
    seen: dict[tuple[str, str], int] = defaultdict(int)
    failed_kinds: dict[tuple[str, str], list[str]] = defaultdict(list)
    order: list[str] = []
    crashes: dict[str, int] = defaultdict(int)

    for model in models:
        for r in range(args.repeat):
            print(f"[compare] {model} run {r + 1}/{args.repeat} ...", flush=True)
            res = _run_once(model, args.scenario, args.timeout)
            if res is None:
                crashes[model] += 1
                print("[compare]   run produced no JSON (crash/timeout)", flush=True)
                continue
            for sc in res["scenarios"]:
                name = sc["name"]
                if name not in order:
                    order.append(name)
                seen[(model, name)] += 1
                if sc["ok"]:
                    passed[(model, name)] += 1
                else:
                    failed_kinds[(model, name)].extend(sc.get("failed", []) or (["error"] if sc.get("error") else []))

    _print_table(models, order, passed, seen, crashes, failed_kinds)
    return 0


def _cell(passed: dict, seen: dict, model: str, name: str) -> str:
    n = seen.get((model, name), 0)
    return f"{passed.get((model, name), 0)}/{n}" if n else "—"


def _print_table(models, order, passed, seen, crashes, failed_kinds) -> None:
    name_w = max(len("scenario"), *[len(n) for n in order]) if order else len("scenario")
    col_w = {m: max(len(m), 7) for m in models}

    print("\n" + "=" * (name_w + sum(col_w.values()) + 3 * len(models)))
    header = "scenario".ljust(name_w) + "".join("  " + m.ljust(col_w[m]) for m in models)
    print(header)
    print("-" * len(header))
    for name in order:
        row = name.ljust(name_w) + "".join("  " + _cell(passed, seen, m, name).ljust(col_w[m]) for m in models)
        print(row)

    print("-" * len(header))
    tot = "PASS-RATE".ljust(name_w)
    for m in models:
        tp = sum(passed[(m, n)] for n in order)
        ts = sum(seen[(m, n)] for n in order)
        pct = f"{100 * tp / ts:.0f}%" if ts else "n/a"
        tot += "  " + f"{tp}/{ts} ({pct})".ljust(col_w[m])
    print(tot)
    if any(crashes.values()):
        print("\ncrashed runs: " + ", ".join(f"{m}={crashes[m]}" for m in models if crashes[m]))

    # Per-model failures grouped by scenario (turn-index + assertion kind),
    # so a gap is attributable instead of a flat kind tally.
    print("\nFailures by scenario:")
    for m in models:
        print(f"  [{m}]")
        any_fail = False
        for name in order:
            fk = failed_kinds.get((m, name), [])
            if not fk:
                continue
            any_fail = True
            counts: dict[str, int] = defaultdict(int)
            for k in fk:
                counts[k] += 1
            detail = ", ".join(f"{k}×{c}" if c > 1 else k for k, c in counts.items())
            print(f"    {name}: {detail}")
        if not any_fail:
            print("    (none)")


if __name__ == "__main__":
    raise SystemExit(main())
