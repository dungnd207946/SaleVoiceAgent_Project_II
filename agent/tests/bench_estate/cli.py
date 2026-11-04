"""bench_estate CLI — subcommands: list, run, compare, regrade.

All phases supported: case listing, full pipeline runs with optional judging,
report comparison (delta analysis), and regrade with alternative judge models.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import sys
import time
from pathlib import Path

from tests.bench_estate.judge import _set_cache_path, get_cost_usd, reset_cost, set_budget
from tests.bench_estate.loader import EssayCase, MCQCase, ScenarioCase, load_all
from tests.bench_estate.reporter import build_report, dump_json, dump_markdown, print_case_line, print_summary
from tests.bench_estate.runner import grade, run_one


def _cmd_list(args: argparse.Namespace) -> int:
    cases = load_all()
    if args.section and args.section != "all":
        cases = [
            c
            for c in cases
            if (
                (isinstance(c, MCQCase) and c.section == args.section)
                or (args.section == "C" and isinstance(c, EssayCase))
                or (args.section == "S" and isinstance(c, ScenarioCase))
            )
        ]
    for c in cases:
        if isinstance(c, MCQCase):
            print(f"{c.case_id:<6} [{c.section}] {c.delivery_mode:<8} {c.topic[:40]}")
        elif isinstance(c, EssayCase):
            print(f"{c.case_id:<6} [C] essay     {c.title[:40]}")
        elif isinstance(c, ScenarioCase):
            print(f"{c.case_id:<6} [S] scenario  {c.title[:40]}")
    print(f"\nTotal: {len(cases)} cases")
    return 0


def _filter_cases(cases, *, section: str, case_ids: str | None, max_cases: int | None):
    if case_ids:
        wanted = {x.strip() for x in case_ids.split(",") if x.strip()}
        cases = [c for c in cases if c.case_id in wanted]
    elif section and section != "all":
        if section in ("A", "B", "D"):
            cases = [c for c in cases if isinstance(c, MCQCase) and c.section == section]
        elif section == "C":
            cases = [c for c in cases if isinstance(c, EssayCase)]
        elif section == "S":
            cases = [c for c in cases if isinstance(c, ScenarioCase)]
    if max_cases:
        cases = cases[:max_cases]
    return cases


async def _cmd_run(args: argparse.Namespace) -> int:
    cases = load_all()
    cases = _filter_cases(cases, section=args.section, case_ids=args.case, max_cases=args.max_cases)
    if not cases:
        print("No cases match filter.", file=sys.stderr)
        return 2

    run_id = time.strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = Path("runs") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = _dt.datetime.now().isoformat(timespec="seconds")
    run_start_monotonic = time.monotonic()

    print(f"▶ Running {len(cases)} cases (run_id={run_id})")
    if args.no_judge:
        print("  --no-judge: judging skipped, transcripts only")

    # Configure judge cache + budget
    cache_path = Path("runs") / ".judge_cache.db"
    _set_cache_path(cache_path)
    reset_cost()
    if args.judge_budget_usd:
        set_budget(args.judge_budget_usd)

    # Run-phase (sequential — production realism)
    raw_results = []
    for c in cases:
        r = await run_one(c, run_id=run_id)
        raw_results.append(r)
        if r.verdict == "error":
            err = (r.error or "")[:80]
            print(f"  [{c.case_id}] ERROR  {err}")
        else:
            ttft = r.ttft_ms[0] if r.ttft_ms else 0
            total = r.total_ms[-1] if r.total_ms else 0
            n_out = sum(len(o) for o in r.agent_outputs)
            n_tools = len(r.tool_calls)
            print(f"  [{c.case_id}] ok     ttft={ttft:.0f}ms  total={total:.0f}ms  out={n_out}c  tools={n_tools}")

    # Judge-phase (parallel with semaphore)
    if not args.no_judge:
        sem = asyncio.Semaphore(args.judge_concurrency)

        async def _judge_one(r, c):
            async with sem:
                if r.verdict == "error":
                    return r
                return await grade(r, c, judge_model=args.judge_model)

        print(f"\n▶ Judging {len(raw_results)} cases (concurrency={args.judge_concurrency})")
        results = list(await asyncio.gather(*[_judge_one(r, c) for r, c in zip(raw_results, cases, strict=False)]))
        for r in results:
            print_case_line(r)
        print(f"\n  Judge cost: ${get_cost_usd():.4f}")
    else:
        results = raw_results

    # Dump per-case transcripts
    for r in results:
        path = out_dir / f"transcript_{r.case_id}.txt"
        body = [f"=== {r.case_id}  section={r.section}  topic={r.topic} ==="]
        for i, (u, o) in enumerate(zip(r.user_inputs, r.agent_outputs, strict=False)):
            body.append(f"\n--- turn {i} ---")
            body.append(f"USER: {u}")
            body.append(f"AGENT: {o}")
        if r.tool_calls:
            body.append("\n--- tool calls ---")
            for t in r.tool_calls:
                t_args = t.get("args", "")[:80]
                res = t.get("result", "")[:80]
                line = f"  turn={t.get('turn_idx')} {t.get('name')}({t_args}) → {res} [{t.get('ms', 0):.0f}ms]"
                body.append(line)
        if r.error:
            body.append(f"\n--- error ---\n{r.error}")
        text = "\n".join(body)
        path.write_text(text, encoding="utf-8")
        if args.verbose:
            print(text)
            print()

    # Build + dump report artifacts
    config = {
        "run_id": run_id,
        "agent_provider": args.provider,
        "agent_model": "(production .env OPENAI_MODEL)",
        "judge_model": args.judge_model,
        "self_bias_warning": args.provider == "openai",
        "judge_concurrency": args.judge_concurrency,
    }
    finished_at = _dt.datetime.now().isoformat(timespec="seconds")
    total_seconds = time.monotonic() - run_start_monotonic
    report = build_report(
        results,
        config,
        judge_cost_usd=get_cost_usd(),
        started_at=started_at,
        finished_at=finished_at,
        total_seconds=total_seconds,
    )
    dump_json(report, out_dir / "report.json")
    dump_markdown(report, out_dir / "report.md")
    print_summary(results, config, get_cost_usd(), total_seconds)
    print("\n  Artifacts:")
    print(f"    runs/{run_id}/report.json")
    print(f"    runs/{run_id}/report.md")
    print(f"    runs/{run_id}/transcript_*.txt")

    n_err = sum(1 for r in results if r.verdict == "error")
    return 0 if n_err == 0 else 1


def _cmd_compare(args: argparse.Namespace) -> int:
    from tests.bench_estate.differ import compare, print_diff

    if not args.a.exists():
        print(f"Report A not found: {args.a}", file=sys.stderr)
        return 2
    if not args.b.exists():
        print(f"Report B not found: {args.b}", file=sys.stderr)
        return 2
    diff = compare(args.a, args.b)
    print_diff(diff)
    return 1 if diff.regressed else 0


async def _cmd_regrade(args: argparse.Namespace) -> int:
    """Re-grade a finished run with a different judge model.

    Loads `report.json`, reconstructs CaseResult-like objects from saved
    `cases[]`, looks up the original Case by ID, runs grade() with the
    new judge model, dumps a new run dir.
    """
    if not args.report.exists():
        print(f"Report not found: {args.report}", file=sys.stderr)
        return 2
    src = json.loads(args.report.read_text(encoding="utf-8"))

    cases_by_id = {c.case_id: c for c in load_all()}
    new_run_id = time.strftime("%Y-%m-%dT%H-%M-%S") + "-regrade"
    out_dir = Path("runs") / new_run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = Path("runs") / ".judge_cache.db"
    _set_cache_path(cache_path)
    reset_cost()
    if args.judge_budget_usd:
        set_budget(args.judge_budget_usd)

    # Reconstruct CaseResult from saved dict — only fields needed by grade()
    from tests.bench_estate.runner import CaseResult

    results: list[CaseResult] = []
    skipped = 0
    for cdict in src.get("cases", []):
        cid = cdict.get("case_id")
        case = cases_by_id.get(cid)
        if case is None:
            print(f"  [{cid}] skipped (case_id not in test bank)", file=sys.stderr)
            skipped += 1
            continue
        r = CaseResult(
            case_id=cid,
            section=cdict.get("section", ""),
            topic=cdict.get("topic", ""),
            delivery_mode=cdict.get("delivery_mode", ""),
            user_inputs=list(cdict.get("user_inputs", [])),
            agent_outputs=list(cdict.get("agent_outputs", [])),
            tool_calls=list(cdict.get("tool_calls", [])),
            ttft_ms=list(cdict.get("ttft_ms", [])),
            total_ms=list(cdict.get("total_ms", [])),
            stage_ms=list(cdict.get("stage_ms", [])),
            agent_switches=list(cdict.get("agent_switches", [])),
            error=cdict.get("error"),
        )
        # If original was an error, no point regrading
        if cdict.get("verdict") == "error":
            r.verdict = "error"
            results.append(r)
            continue
        results.append(await grade(r, case, judge_model=args.judge_model))

    started_at = src.get("finished_at", "")
    finished_at = _dt.datetime.now().isoformat(timespec="seconds")
    config = dict(src.get("config", {}))
    config["judge_model"] = args.judge_model
    config["regrade_source"] = str(args.report)
    config["run_id"] = new_run_id
    is_gpt = args.judge_model.startswith("gpt-")
    config["self_bias_warning"] = config.get("agent_provider", "openai") == "openai" and is_gpt

    report = build_report(
        results,
        config,
        judge_cost_usd=get_cost_usd(),
        started_at=started_at,
        finished_at=finished_at,
        total_seconds=0.0,
    )
    dump_json(report, out_dir / "report.json")
    dump_markdown(report, out_dir / "report.md")
    print_summary(results, config, get_cost_usd(), 0.0)
    print(f"\n  Regrade source: {args.report}")
    print(f"  New report:     runs/{new_run_id}/report.json")
    if skipped:
        print(f"  Skipped:        {skipped} cases (not in current test bank)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench_estate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List cases from the test bank")
    p_list.add_argument(
        "--section",
        choices=["A", "B", "C", "D", "S", "all"],
        default="all",
        help="Filter by section (A/B/D=MCQ, C=essay, S=scenario)",
    )

    p_run = sub.add_parser("run", help="Run cases through production v9 pipeline")
    p_run.add_argument(
        "--section",
        choices=["A", "B", "C", "D", "S", "all"],
        default="all",
    )
    p_run.add_argument("--case", help="Comma-separated case IDs (overrides --section)")
    p_run.add_argument("--max-cases", type=int, help="Stop after N cases")
    p_run.add_argument("--no-judge", action="store_true", help="Skip judge LLM (transcripts only)")
    p_run.add_argument(
        "--judge-model",
        default="gpt-5.4-nano-2026-03-17",
        help="Judge LLM model (active in M3+)",
    )
    p_run.add_argument("--provider", default="openai", help="Agent provider (M3+)")
    p_run.add_argument("--verbose", action="store_true")
    p_run.add_argument("--judge-concurrency", type=int, default=10)
    p_run.add_argument(
        "--judge-budget-usd",
        type=float,
        default=None,
        help="Hard cap; aborts judge phase when total cost reaches cap",
    )

    p_compare = sub.add_parser("compare", help="Compare two report.json files")
    p_compare.add_argument("a", type=Path, help="Baseline report.json")
    p_compare.add_argument("b", type=Path, help="New report.json")

    p_regrade = sub.add_parser("regrade", help="Re-grade an existing report with a different judge")
    p_regrade.add_argument("report", type=Path, help="Path to existing report.json")
    p_regrade.add_argument("--judge-model", default="gpt-4o", help="New judge model")
    p_regrade.add_argument("--judge-budget-usd", type=float, default=None)

    return parser


async def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "run":
        return await _cmd_run(args)
    if args.cmd == "compare":
        return _cmd_compare(args)
    if args.cmd == "regrade":
        return await _cmd_regrade(args)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
