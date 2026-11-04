"""Compare two `report.json` outputs from bench_estate runs.

Buckets cases as fixed / regressed / unchanged_pass / unchanged_fail / new / removed
based on verdict transitions. Pure-stdlib, no I/O outside `compare()`'s file reads.
Terminal output goes through `print_diff()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ANSI palette (reuse from reporter)
try:
    from tests.bench_llm import C as _C  # noqa: N814
except ImportError:

    class _C:
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


PASS_VERDICTS = {"pass"}
FAIL_VERDICTS = {"fail", "refused", "error", "judge_error", "uncertain"}


@dataclass
class Diff:
    """Result of comparing two reports.

    Each bucket is a list of dicts: {case_id, topic, score_a, score_b, verdict_a, verdict_b}.
    """

    a_run_id: str = ""
    b_run_id: str = ""
    a_config: dict = field(default_factory=dict)
    b_config: dict = field(default_factory=dict)
    overall_a: tuple[float, float] = (0.0, 0.0)  # (raw, max)
    overall_b: tuple[float, float] = (0.0, 0.0)
    sections_a: dict = field(default_factory=dict)
    sections_b: dict = field(default_factory=dict)
    latency_a: dict = field(default_factory=dict)
    latency_b: dict = field(default_factory=dict)
    judge_cost_a: float = 0.0
    judge_cost_b: float = 0.0
    fixed: list[dict] = field(default_factory=list)
    regressed: list[dict] = field(default_factory=list)
    unchanged_pass: list[dict] = field(default_factory=list)
    unchanged_fail: list[dict] = field(default_factory=list)
    new_cases: list[dict] = field(default_factory=list)
    removed_cases: list[dict] = field(default_factory=list)


def _index_by_case_id(cases: list[dict]) -> dict[str, dict]:
    return {c["case_id"]: c for c in cases}


def _row(case_id: str, ca: dict | None, cb: dict | None) -> dict:
    return {
        "case_id": case_id,
        "topic": (cb or ca or {}).get("topic", ""),
        "score_a": float((ca or {}).get("score_raw", 0.0)),
        "score_b": float((cb or {}).get("score_raw", 0.0)),
        "verdict_a": (ca or {}).get("verdict", ""),
        "verdict_b": (cb or {}).get("verdict", ""),
    }


def _classify(ca: dict, cb: dict) -> str:
    va, vb = ca.get("verdict", ""), cb.get("verdict", "")
    if va in PASS_VERDICTS and vb in PASS_VERDICTS:
        return "unchanged_pass"
    if va in FAIL_VERDICTS and vb == "pass":
        return "fixed"
    if va == "pass" and vb in FAIL_VERDICTS:
        return "regressed"
    return "unchanged_fail"


def compare(a_path: Path, b_path: Path) -> Diff:
    a = json.loads(Path(a_path).read_text(encoding="utf-8"))
    b = json.loads(Path(b_path).read_text(encoding="utf-8"))
    diff = Diff(
        a_run_id=a.get("run_id", ""),
        b_run_id=b.get("run_id", ""),
        a_config=a.get("config", {}),
        b_config=b.get("config", {}),
        sections_a=a.get("sections", {}),
        sections_b=b.get("sections", {}),
        latency_a=a.get("latency_ms", {}),
        latency_b=b.get("latency_ms", {}),
        judge_cost_a=float(a.get("judge_stats", {}).get("cost_usd", 0.0)),
        judge_cost_b=float(b.get("judge_stats", {}).get("cost_usd", 0.0)),
    )
    ta = a.get("totals", {})
    tb = b.get("totals", {})
    diff.overall_a = (float(ta.get("score_raw", 0.0)), float(ta.get("score_max", 0.0)))
    diff.overall_b = (float(tb.get("score_raw", 0.0)), float(tb.get("score_max", 0.0)))

    a_idx = _index_by_case_id(a.get("cases", []))
    b_idx = _index_by_case_id(b.get("cases", []))
    all_ids = sorted(set(a_idx.keys()) | set(b_idx.keys()))
    for cid in all_ids:
        ca, cb = a_idx.get(cid), b_idx.get(cid)
        if ca and not cb:
            diff.removed_cases.append(_row(cid, ca, None))
            continue
        if cb and not ca:
            diff.new_cases.append(_row(cid, None, cb))
            continue
        bucket = _classify(ca, cb)
        row = _row(cid, ca, cb)
        getattr(diff, bucket).append(row)
    return diff


def _arrow(delta: float) -> str:
    if delta > 0:
        return f"{_attr('GREEN')}↑ +{delta:.1f}{_attr('RESET')}"
    if delta < 0:
        return f"{_attr('RED')}↓ {delta:.1f}{_attr('RESET')}"
    return "—"


def print_diff(diff: Diff) -> None:
    a_id = diff.a_run_id or "?"
    b_id = diff.b_run_id or "?"
    a_prompt = diff.a_config.get("prompt_version", "?")
    b_prompt = diff.b_config.get("prompt_version", "?")
    a_agent = diff.a_config.get("agent_provider", "?")
    b_agent = diff.b_config.get("agent_provider", "?")
    print(
        f"\n{_attr('BOLD')}═══ DIFF: {a_id} → {b_id}  "
        f"(prompt {a_prompt}→{b_prompt}, agent {a_agent}→{b_agent}){_attr('RESET')}\n"
    )

    a_raw, a_max = diff.overall_a
    b_raw, b_max = diff.overall_b
    a_pct = (a_raw / a_max * 100) if a_max else 0.0
    b_pct = (b_raw / b_max * 100) if b_max else 0.0
    print(f"OVERALL:    {a_raw:>7.1f} → {b_raw:<7.1f}  {_arrow(b_raw - a_raw)}  ({a_pct:.1f}% → {b_pct:.1f}%)")

    common_secs = sorted(set(diff.sections_a) | set(diff.sections_b))
    for sec in common_secs:
        sa = diff.sections_a.get(sec, {})
        sb = diff.sections_b.get(sec, {})
        ra = float(sa.get("raw", 0.0))
        rb = float(sb.get("raw", 0.0))
        print(f"SECTION {sec}:  {ra:>7.1f} → {rb:<7.1f}  {_arrow(rb - ra)}")
    print()

    def _show(label: str, color: str, items: list[dict], limit: int = 20):
        print(f"  {color}{label}{_attr('RESET')} ({len(items)})")
        for r in items[:limit]:
            score_str = f"{r['score_a']:.1f} → {r['score_b']:.1f}"
            verdict_str = f"(was {r['verdict_a']}, now {r['verdict_b']})"
            print(f"     {r['case_id']:<6} {r['topic'][:25]:<25}  {score_str}  {verdict_str}")
        if len(items) > limit:
            print(f"     ... +{len(items) - limit} more")

    print(f"{_attr('BOLD')}CASE-LEVEL CHANGES:{_attr('RESET')}")
    if diff.fixed:
        _show("✅ FIXED", _attr("GREEN"), diff.fixed)
    if diff.regressed:
        _show("⚠️ REGRESSED", _attr("RED"), diff.regressed)
    print(f"  {_attr('DIM')}➖ UNCHANGED PASS{_attr('RESET')} ({len(diff.unchanged_pass)})")
    print(f"  {_attr('DIM')}➖ UNCHANGED FAIL{_attr('RESET')} ({len(diff.unchanged_fail)})")
    if diff.new_cases:
        _show("🆕 NEW", _attr("CYAN"), diff.new_cases)
    if diff.removed_cases:
        _show("🚫 REMOVED", _attr("MAGENTA"), diff.removed_cases)

    # latency deltas (only stages present in both)
    common_stages = sorted(set(diff.latency_a) & set(diff.latency_b))
    if common_stages:
        print(f"\n{_attr('BOLD')}LATENCY:{_attr('RESET')}")
        for stage in common_stages:
            pa = diff.latency_a[stage].get("p95", 0.0)
            pb = diff.latency_b[stage].get("p95", 0.0)
            delta = pb - pa
            arrow = (
                f"{_attr('RED')}↑ +{delta:.0f}ms{_attr('RESET')}"
                if delta > 0
                else f"{_attr('GREEN')}↓ {delta:.0f}ms{_attr('RESET')}"
                if delta < 0
                else "—"
            )
            print(f"  {stage:<14} p95: {pa:>6.0f}ms → {pb:>6.0f}ms  {arrow}")
        print(f"  judge cost:    ${diff.judge_cost_a:.4f} → ${diff.judge_cost_b:.4f}")

    if diff.regressed:
        print(f"\n{_attr('YELLOW')}⚠️  ATTENTION: {len(diff.regressed)} regressions need investigation.{_attr('RESET')}")
