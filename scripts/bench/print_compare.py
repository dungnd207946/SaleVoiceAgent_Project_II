"""Pretty-print side-by-side bench comparison from results/*.jsonl.

Reads tests/bench/results/<suite>__<env>.jsonl, picks the LATEST entry per
(suite, name, env), groups paired tests so local + cloud appear next to each
other.

Usage:
    python -m scripts.bench.print_compare
    python -m scripts.bench.print_compare --suite compare
    python -m scripts.bench.print_compare --suite storage,rag,tools,dashboard,compare

Tip: rerun benches first so JSONL has fresh entries:
    pytest tests/bench -v -s -m bench
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "tests" / "bench" / "results"


def _load_latest(suite_filter: list[str]) -> dict[tuple[str, str], dict]:
    """Return {(test_name, env_label): latest result row}."""
    out: dict[tuple[str, str], dict] = {}
    if not RESULTS.is_dir():
        return out
    for f in sorted(RESULTS.glob("*.jsonl")):
        # filename: <suite>__<env>.jsonl
        stem = f.stem
        if "__" not in stem:
            continue
        suite, env = stem.split("__", 1)
        if suite_filter and suite not in suite_filter:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row.setdefault("env_label", env)
            out[(row["name"], row["env_label"])] = row
    return out


# ─── Pairing rules: rows that should appear next to each other ──────────

PAIRS = [
]


def _row(row: dict | None) -> str:
    if row is None or row.get("n", 0) == 0:
        return f"{'—':>8}  {'—':>8}  {'—':>8}  {'—':>10}"
    return (
        f"{row['p50_ms']:>7.1f}  "
        f"{row['p95_ms']:>7.1f}  "
        f"{row['p99_ms']:>7.1f}  "
        f"{row['mean_ms']:>5.1f}±{row['stdev_ms']:<3.1f}"
    )


def print_pair_table(data: dict[tuple[str, str], dict], envs: list[str]) -> None:
    print()
    print("=" * 110)
    print(" HEAD-TO-HEAD COMPARISON  (p50 / p95 / p99 / mean±stdev — all in ms)")
    print("=" * 110)

    for env in envs:
        rows_seen: set[str] = set()
        title = f"  ENV: {env}"
        print(f"\n{title}\n  " + "─" * 100)
        # Header
        print(f"  {'Test':<50s} {'p50':>7s}  {'p95':>7s}  {'p99':>7s}  {'mean±sd':>10s}")
        print("  " + "─" * 100)
        # Pairs
        for left, right in PAIRS:
            l = data.get((left, env))
            r = data.get((right, env))
            if l is None and r is None:
                continue
            print(f"  {left:<50s} {_row(l)}")
            print(f"  {right:<50s} {_row(r)}")
            if l and r and l.get("n") and r.get("n"):
                p50_ratio = r["p50_ms"] / max(l["p50_ms"], 0.01)
                p95_ratio = r["p95_ms"] / max(l["p95_ms"], 0.01)
                print(
                    f"    → cloud/local  p50: {p50_ratio:5.1f}×   "
                    f"p95: {p95_ratio:5.1f}×   "
                    f"max(cloud)={r['max_ms']:.0f}ms",
                )
            print()
            rows_seen.add(left)
            rows_seen.add(right)


def print_full_table(data: dict[tuple[str, str], dict], envs: list[str]) -> None:
    """Flat dump — every (test, env) combination."""
    print()
    print("=" * 110)
    print(" ALL BENCH ROWS (latest per env)")
    print("=" * 110)
    by_name: dict[str, dict[str, dict]] = {}
    for (name, env), row in data.items():
        by_name.setdefault(name, {})[env] = row

    if len(envs) <= 1:
        # single-env dump
        env = envs[0] if envs else "unknown"
        print(f"\n  ENV: {env}")
        print(f"  {'Test':<50s} {'n':>4s} {'p50':>7s} {'p95':>7s} {'p99':>7s} {'mean±sd':>10s}")
        print("  " + "─" * 90)
        for name in sorted(by_name):
            row = by_name[name].get(env)
            if not row:
                continue
            print(
                f"  {name:<50s} {row.get('n', 0):>4d} "
                f"{_row(row)}",
            )
    else:
        # multi-env side-by-side
        env_a, env_b = envs[0], envs[1]
        print(f"\n  Comparing: {env_a}  ↔  {env_b}")
        col = f"{'p50':>7s} {'p95':>7s}"
        print(f"  {'Test':<48s} | {env_a:^17s} | {env_b:^17s}")
        print("  " + "─" * 92)
        for name in sorted(by_name):
            ra = by_name[name].get(env_a)
            rb = by_name[name].get(env_b)
            la = (
                f"{ra['p50_ms']:>7.1f} {ra['p95_ms']:>7.1f}"
                if ra and ra.get("n") else f"{'—':>7s} {'—':>7s}"
            )
            lb = (
                f"{rb['p50_ms']:>7.1f} {rb['p95_ms']:>7.1f}"
                if rb and rb.get("n") else f"{'—':>7s} {'—':>7s}"
            )
            print(f"  {name:<48s} | {la} | {lb}")


def cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--suite",
        default="compare",
        help="Comma-list (compare,storage,rag,tools,dashboard) or 'all'",
    )
    p.add_argument("--full", action="store_true", help="Also print full flat table")
    args = p.parse_args()

    suites = (
        ["compare", "storage", "rag", "tools", "dashboard"]
        if args.suite == "all"
        else [s.strip() for s in args.suite.split(",")]
    )
    data = _load_latest(suites)
    if not data:
        print("No bench results found in tests/bench/results/. Run pytest first.")
        return 1

    envs = sorted({env for (_, env) in data.keys()})
    print_pair_table(data, envs)

    if args.full or len(envs) > 1:
        print_full_table(data, envs)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
