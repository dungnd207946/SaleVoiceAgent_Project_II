"""Reporter: live color stream, end-of-run summary, JSON dump, Markdown render.

Functions are pure where possible (compute percentiles / build dict shapes) so
they're unit-testable without I/O. dump_json / dump_markdown / print_* functions
do I/O at the end and are exercised through CLI smoke runs.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from tests.bench_estate.runner import CaseResult

# ── ANSI palette (fall back to empty strings) ─────────────────────────────────

try:
    from tests.bench_llm import C as _C  # noqa: N814 - reuse ANSI palette
except ImportError:

    class _C:  # minimal fallback
        RESET = ""
        BOLD = ""
        DIM = ""
        RED = ""
        GREEN = ""
        YELLOW = ""
        CYAN = ""
        MAGENTA = ""
        BLUE = ""


def _attr(name: str) -> str:
    return getattr(_C, name, "")


# ── Percentiles ───────────────────────────────────────────────────────────────


def percentiles(values: list[float]) -> dict[str, float]:
    """Return {'p50','p95','p99'} for a list of floats. Empty input → all 0."""
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    if len(values) == 1:
        v = float(values[0])
        return {"p50": v, "p95": v, "p99": v}
    qs = statistics.quantiles(values, n=100, method="inclusive")
    return {"p50": float(qs[49]), "p95": float(qs[94]), "p99": float(qs[98])}


# ── Per-case live print ───────────────────────────────────────────────────────


def status_icon(verdict: str) -> str:
    return {
        "pass": f"{_attr('GREEN')}✓{_attr('RESET')}",
        "fail": f"{_attr('RED')}✗{_attr('RESET')}",
        "uncertain": f"{_attr('YELLOW')}⚠{_attr('RESET')}",
        "refused": f"{_attr('YELLOW')}🚫{_attr('RESET')}",
        "error": f"{_attr('RED')}!{_attr('RESET')}",
        "judge_error": f"{_attr('MAGENTA')}?{_attr('RESET')}",
    }.get(verdict, "?")


def print_case_line(r: CaseResult) -> None:
    ttft = r.ttft_ms[0] if r.ttft_ms else 0.0
    total = r.total_ms[-1] if r.total_ms else 0.0
    score_str = f"{r.score_raw:.1f}/{r.score_max:.1f}"
    print(
        f"[{r.case_id:<6}] {status_icon(r.verdict)} "
        f"{r.topic[:30]:<30} {score_str:>10}  "
        f"ttft={ttft:>5.0f}ms  total={total:>5.0f}ms  tools={len(r.tool_calls)}"
    )
    if r.verdict in ("fail", "uncertain", "refused", "judge_error"):
        rat = (r.judge_rationale or r.error or "")[:140]
        if rat:
            print(f"       {_attr('DIM')}└ {rat}{_attr('RESET')}")


# ── Aggregations ──────────────────────────────────────────────────────────────


def section_breakdown(results: list[CaseResult]) -> dict[str, dict]:
    """Per-section {raw, max, passed, failed, refused, uncertain, errored, review}."""
    out: dict[str, dict] = {}
    by_section: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_section[r.section].append(r)
    for sec, items in sorted(by_section.items()):
        raw = sum(i.score_raw for i in items)
        max_ = sum(i.score_max for i in items)
        verdicts = Counter(i.verdict for i in items)
        out[sec] = {
            "raw": round(raw, 2),
            "max": round(max_, 2),
            "passed": verdicts.get("pass", 0),
            "failed": verdicts.get("fail", 0),
            "refused": verdicts.get("refused", 0),
            "uncertain": verdicts.get("uncertain", 0),
            "error": verdicts.get("error", 0),
            "judge_error": verdicts.get("judge_error", 0),
            "count": len(items),
        }
    return out


def topic_breakdown(results: list[CaseResult]) -> dict[str, dict]:
    """Per-topic counts + fail_rate."""
    out: dict[str, dict] = {}
    by_topic: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        if r.topic:
            by_topic[r.topic].append(r)
    for topic, items in sorted(by_topic.items()):
        passed = sum(1 for i in items if i.verdict == "pass")
        failed = len(items) - passed
        out[topic] = {
            "total": len(items),
            "passed": passed,
            "failed": failed,
            "fail_rate": failed / len(items) if items else 0.0,
        }
    return out


def latency_breakdown(results: list[CaseResult]) -> dict[str, dict]:
    """Per-stage percentiles aggregated across all turns of all cases."""
    stages: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for s in r.stage_ms:
            for k, v in s.items():
                if isinstance(v, (int, float)):
                    stages[k].append(float(v))
    return {k: percentiles(v) for k, v in sorted(stages.items())}


def tool_stats(results: list[CaseResult]) -> dict[str, dict]:
    """Tool call counts per tool name."""
    counts: dict[str, int] = Counter()
    for r in results:
        for t in r.tool_calls:
            name = t.get("name", "?")
            counts[name] += 1
    return {n: {"calls": c} for n, c in sorted(counts.items())}


# ── End summary print ─────────────────────────────────────────────────────────


def print_summary(
    results: list[CaseResult],
    config: dict,
    judge_cost_usd: float,
    total_seconds: float,
) -> None:
    sections = section_breakdown(results)
    topics = topic_breakdown(results)
    latencies = latency_breakdown(results)
    tools = tool_stats(results)
    total_raw = sum(s["raw"] for s in sections.values())
    total_max = sum(s["max"] for s in sections.values()) or 1
    pct = total_raw / total_max * 100

    print(f"\n{_attr('BOLD')}═══ NOBLE HOTLINE EVAL — bench_estate ═══{_attr('RESET')}")
    print(f"  Run:        {config.get('run_id', '')}")
    print(f"  Agent:      {config.get('agent_provider', '?')}/{config.get('agent_model', '?')}")
    print(f"  Judge:      {config.get('judge_model', '?')}", end="")
    if config.get("self_bias_warning"):
        print(f"  {_attr('YELLOW')}⚠ self-bias-risk{_attr('RESET')}", end="")
    print()
    print(f"  Cases:      {len(results)}")
    print(
        f"  Total:      {total_raw:.1f}/{total_max:.1f}  ({pct:.1f}%)"
        f"  → {'ĐẠT' if pct >= 70 else 'CẦN CẢI THIỆN' if pct >= 50 else 'KHÔNG ĐẠT'}"
    )

    print(f"\n{_attr('BOLD')}── Sections ──{_attr('RESET')}")
    for sec, s in sections.items():
        sec_pct = (s["raw"] / s["max"] * 100) if s["max"] else 0
        print(
            f"  {sec}: {s['raw']:>6.1f}/{s['max']:.1f} ({sec_pct:>5.1f}%)"
            f"  pass={s['passed']:<3} fail={s['failed']:<3} refused={s['refused']:<3} err={s['error']:<3}"
        )

    weak = [(t, d) for t, d in topics.items() if d["fail_rate"] >= 0.4 and d["total"] >= 2]
    if weak:
        print(f"\n{_attr('BOLD')}── Weakest topics (fail_rate ≥ 40%) ──{_attr('RESET')}")
        for t, d in sorted(weak, key=lambda x: -x[1]["fail_rate"])[:10]:
            print(
                f"  {_attr('RED')}❌ {t[:50]:<50}{_attr('RESET')}"
                f"  {d['failed']}/{d['total']}  ({d['fail_rate'] * 100:.0f}% fail)"
            )

    if latencies:
        print(f"\n{_attr('BOLD')}── Latency ──{_attr('RESET')}")
        print(f"  {'stage':<14} {'p50':>8} {'p95':>8} {'p99':>8}")
        for stage, p in latencies.items():
            print(f"  {stage:<14} {p['p50']:>6.0f}ms {p['p95']:>6.0f}ms {p['p99']:>6.0f}ms")

    if tools:
        print(f"\n{_attr('BOLD')}── Tools ──{_attr('RESET')}")
        for name, d in tools.items():
            print(f"  {name:<20} {d['calls']} calls")

    print(f"\n{_attr('BOLD')}── Judge ──{_attr('RESET')}")
    print(f"  Cost:    ${judge_cost_usd:.4f}")
    judge_errors = sum(1 for r in results if r.verdict == "judge_error")
    if judge_errors:
        print(f"  {_attr('RED')}Judge errors: {judge_errors}{_attr('RESET')}")

    print(f"\n  Time total: {total_seconds:.1f}s\n")


# ── JSON dump ─────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"


def _result_to_dict(r: CaseResult) -> dict:
    return {
        "case_id": r.case_id,
        "section": r.section,
        "topic": r.topic,
        "delivery_mode": r.delivery_mode,
        "user_inputs": r.user_inputs,
        "agent_outputs": r.agent_outputs,
        "tool_calls": r.tool_calls,
        "ttft_ms": r.ttft_ms,
        "total_ms": r.total_ms,
        "stage_ms": r.stage_ms,
        "agent_switches": r.agent_switches,
        "judge": {
            "model": r.judge_model,
            "rationale": r.judge_rationale,
            "verdict": r.verdict,
            "rubric_breakdown": r.rubric_breakdown,
        },
        "score_raw": r.score_raw,
        "score_max": r.score_max,
        "verdict": r.verdict,
        "error": r.error,
    }


def build_report(
    results: list[CaseResult],
    config: dict,
    judge_cost_usd: float,
    started_at: str,
    finished_at: str,
    total_seconds: float,
) -> dict:
    sections = section_breakdown(results)
    total_raw = sum(s["raw"] for s in sections.values())
    total_max = sum(s["max"] for s in sections.values()) or 1
    pct = total_raw / total_max * 100
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": config.get("run_id", ""),
        "started_at": started_at,
        "finished_at": finished_at,
        "total_seconds": total_seconds,
        "config": config,
        "totals": {
            "score_raw": round(total_raw, 2),
            "score_max": round(total_max, 2),
            "percent": round(pct, 3),
            "verdict": "ĐẠT" if pct >= 70 else "CẦN CẢI THIỆN" if pct >= 50 else "KHÔNG ĐẠT",
        },
        "sections": sections,
        "topic_breakdown": topic_breakdown(results),
        "latency_ms": latency_breakdown(results),
        "tool_stats": tool_stats(results),
        "judge_stats": {
            "cost_usd": round(judge_cost_usd, 4),
            "errors": sum(1 for r in results if r.verdict == "judge_error"),
            "cached_hits": sum(1 for r in results if getattr(r, "_judge_cached", False)),
        },
        "cases": [_result_to_dict(r) for r in results],
        "failures": [_result_to_dict(r) for r in results if r.verdict in ("fail", "refused", "error", "judge_error")],
    }


def dump_json(report: dict, out_path: Path) -> None:
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Markdown render ───────────────────────────────────────────────────────────


def render_markdown(report: dict) -> str:
    lines = [f"# Noble Hotline Eval — {report['run_id']}", ""]
    cfg = report["config"]
    lines.append(f"- **Agent**: `{cfg.get('agent_provider')}/{cfg.get('agent_model')}`")
    lines.append(
        f"- **Judge**: `{cfg.get('judge_model')}`" + (" ⚠ self-bias-risk" if cfg.get("self_bias_warning") else "")
    )
    lines.append(f"- **Cases**: {len(report['cases'])}")
    t = report["totals"]
    lines.append(f"- **Total**: **{t['score_raw']}/{t['score_max']} ({t['percent']}%)** → {t['verdict']}")
    lines.append("")
    lines.append("## Sections")
    lines.append("| Section | Score | % | Pass | Fail | Refused | Errors |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for sec, s in report["sections"].items():
        sec_pct = (s["raw"] / s["max"] * 100) if s["max"] else 0
        lines.append(
            f"| {sec} | {s['raw']:.1f}/{s['max']:.1f} | {sec_pct:.1f}%"
            f" | {s['passed']} | {s['failed']} | {s['refused']} | {s['error']} |"
        )
    lines.append("")
    if report["latency_ms"]:
        lines.append("## Latency (ms)")
        lines.append("| Stage | p50 | p95 | p99 |")
        lines.append("|---|---:|---:|---:|")
        for stage, p in report["latency_ms"].items():
            lines.append(f"| {stage} | {p['p50']:.0f} | {p['p95']:.0f} | {p['p99']:.0f} |")
        lines.append("")
    if report["failures"]:
        lines.append(f"## Failures ({len(report['failures'])})")
        for f in report["failures"][:10]:
            ag = (f["agent_outputs"][0] if f["agent_outputs"] else "")[:200]
            lines.append(f"- **{f['case_id']}** ({f['verdict']}): {f.get('judge', {}).get('rationale', '')[:140]}")
            if ag:
                lines.append(f"  > {ag}")
        lines.append("")
    lines.append("## Judge")
    js = report["judge_stats"]
    lines.append(f"- Cost: ${js['cost_usd']}")
    lines.append(f"- Errors: {js['errors']}")
    lines.append("")
    lines.append(f"_Generated by bench_estate at {report['finished_at']} ({report['total_seconds']:.1f}s)_")
    return "\n".join(lines)


def dump_markdown(report: dict, out_path: Path) -> None:
    out_path.write_text(render_markdown(report), encoding="utf-8")
