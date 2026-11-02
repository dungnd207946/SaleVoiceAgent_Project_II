"""Tool-selection axis — did the agent call the right tools with the right args?

Scored from `golden.tools`/`golden.banned_tools` (schema v2), not `expect` — the
policy scorer owns `expect` and this scorer owns `golden`, so the two vocabularies
are disjoint and nothing double-counts.

`arg_accuracy` exists mainly to catch price-unit drift (a tool arg declared in
real VND but sometimes passed in tỷ is a 1e9 filter error that produces
plausible-looking output), so tool-arg cases are worth writing even where
selection already passes. Its sample is deliberately narrow: **only matchers of
tools the agent actually called**. A golden tool that was never called is a
selection failure — already counted by `tool_selection_accuracy` — and charging
its matchers to `arg_accuracy` too would double-count one mistake, scale the
penalty by how many matchers the case author happened to write, and make the
gate mean "picked the right tool AND passed the right args". When NO golden tool
in the run was called, `arg_total` is 0 and the metric is `None` → the gate fails
as `missing`, which is the honest reading: nothing about args was measured.

On `checks` vs the five metrics — the asymmetry is deliberate. Golden-driven
assertions (`tool_selection` / `tool_arg` / `banned_call`) increment `checks` on
pass AND fail. Unsolicited observations (`tool_error`, `irrelevant_call`)
increment it only when they fire, because a clean tool call was never an
assertion anyone made. That makes `AxisScore.pass_rate` for this axis
PESSIMISTIC: one tool error among a hundred clean calls reads far below 99%.
That direction is chosen on purpose. `pass_rate` is a display-only summary (the
release gates read `metrics`, which are computed from independent and exact
tallies), and for a summary line the failure mode to avoid is looking green
while findings exist. Counting observations symmetrically would render "99.2%
pass" on a run whose gate just failed; counting them not at all would render
100% with findings present, because `pass_rate` returns 1.0 when `checks == 0`.
Invariant, locked by a test: findings non-empty => pass_rate < 1.0.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from evals.quality.cases import EvalCase
from evals.quality.scorers import AxisScore, Finding
from evals.quality.trace import TraceCase

AXIS = "tool_selection"
_EXEMPT_TOOLS = frozenset({"update_customer"})  # agent được khuyến khích gọi bất cứ lúc nào — đếm là nhiễu


def _rate(hits: int, total: int, *, empty: float) -> float:
    """Rate for a metric NO gate reads. An empty sample renders as `empty`."""
    return empty if total <= 0 else hits / total


def _gated_rate(hits: int, total: int) -> float | None:
    """Rate for a metric a GATE reads — `None` when the denominator is zero.

    A gated rate must never default to its passing value. `arg_accuracy = 1.0`
    computed over zero tool-arg assertions reads as "the price-unit gate is
    green" when the truth is "nothing was measured"; the same applies to the
    `*_rate` metrics whose passing value is 0.0. `None` routes the metric through
    `scorecard.evaluate_gates`'s fail-closed missing path, so the gate FAILs with
    `missing` and the report states honestly that this run does not certify it.
    """
    return None if total <= 0 else hits / total


def _is_error_result(raw: str | None) -> bool:
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("error")) or data.get("ok") is False


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _arg_matches(actual, matcher: dict) -> bool:
    if "contains" in matcher:
        return _norm(matcher["contains"]) in _norm(str(actual))
    return actual == matcher["equals"]


def score_tool_selection(cases: Sequence[EvalCase], traces: Sequence[TraceCase]) -> AxisScore:
    by_id = {t.case_id: t for t in traces}
    findings: list[Finding] = []
    checks = 0

    sel_total = sel_ok = 0
    arg_total = arg_ok = 0
    banned_total = banned_bad = 0
    irrel_total = irrel_bad = 0
    calls_total = calls_error = 0

    for case in cases:
        turns_with_golden = [
            (i, t) for i, t in enumerate(case.turns) if t.golden and (t.golden.tools or t.golden.banned_tools)
        ]
        if not case.reviewed or not turns_with_golden:
            continue
        trace = by_id.get(case.id)
        if trace is None:
            checks += 1
            findings.append(Finding(case.id, -1, "missing_trace", "case ran no trace — run incomplete"))
            continue
        if trace.error:
            checks += 1
            findings.append(Finding(case.id, -1, "case_error", trace.error))
            continue

        for i, case_turn in turns_with_golden:
            if i >= len(trace.turns):
                checks += 1
                findings.append(Finding(case.id, i, "missing_turn", "trace has fewer turns than the case"))
                continue
            trace_turn = trace.turns[i]
            names = [tc.name for tc in trace_turn.tool_calls]
            golden = case_turn.golden

            calls_total += len(trace_turn.tool_calls)
            for tc in trace_turn.tool_calls:
                if _is_error_result(tc.raw_result):
                    calls_error += 1
                    checks += 1
                    findings.append(Finding(case.id, i, "tool_error", f"{tc.name} → {tc.raw_result}"))

            if golden.tools:
                wanted = [gt.name for gt in golden.tools]
                sel_total += 1
                checks += 1
                if all(w in names for w in wanted):
                    sel_ok += 1
                else:
                    missing = [w for w in wanted if w not in names]
                    findings.append(Finding(case.id, i, "tool_selection", f"missing {missing}; called={names}"))

                for gt in golden.tools:
                    matching_calls = [tc for tc in trace_turn.tool_calls if tc.name == gt.name]
                    # Tool KHÔNG được gọi ⇒ không chấm arg của nó. Một tool vắng mặt là MỘT
                    # sự kiện sai, và `tool_selection` ngay trên đã đếm nó rồi; đánh trượt
                    # thêm từng matcher chỉ nhân bản cùng một lỗi vào `arg_accuracy`, làm
                    # case khai nhiều matcher bị phạt nặng hơn case khai ít, và biến gate
                    # `arg_accuracy >= 1.0` thành "chọn đúng tool VÀ truyền đúng tham số" —
                    # chặt hơn thứ tên nó khai (bắt lệch đơn vị giá VNĐ/tỷ).
                    # Đo thật 2026-08-25 (aina_prod, 95 case): 186/219 = 0.849 với 32/33 lần
                    # trượt là "tool not called"; lọc đi còn 186/187 = 0.995 và gate VẪN đỏ
                    # đúng vì một lỗi tham số thật (check_inventory project_code='VOP3').
                    if not matching_calls:
                        continue
                    for arg, matcher in gt.args.items():
                        arg_total += 1
                        checks += 1
                        # ANY call của tool đó thoả matcher là đạt (mirror e2e tool_arg cũ)
                        if any(
                            arg in (tc.args or {}) and _arg_matches(tc.args[arg], matcher) for tc in matching_calls
                        ):
                            arg_ok += 1
                        else:
                            detail = (
                                f"{gt.name}.{arg} không khớp {matcher!r}; "
                                f"calls={[tc.args for tc in matching_calls]}"
                            )
                            findings.append(Finding(case.id, i, "tool_arg", detail))

                # irrelevant: call ngoài (golden.tools ∪ exempt) — banned đếm riêng bên dưới
                allowed = set(wanted) | _EXEMPT_TOOLS
                extras = sorted({n for n in names if n not in allowed and n not in golden.banned_tools})
                irrel_total += 1
                if extras:
                    irrel_bad += 1
                    checks += 1
                    findings.append(Finding(case.id, i, "irrelevant_call", f"called ngoài golden.tools: {extras}"))

            if golden.banned_tools:
                banned_total += 1
                hit = [b for b in golden.banned_tools if b in names]
                if hit:
                    banned_bad += 1
                for b in golden.banned_tools:
                    checks += 1
                    if b in names:
                        findings.append(Finding(case.id, i, "banned_call", f"tool {b!r} must not be called"))

    return AxisScore(
        axis=AXIS,
        checks=checks,
        failures=len(findings),
        findings=tuple(findings),
        metrics={
            "tool_selection_accuracy": _rate(sel_ok, sel_total, empty=1.0),
            "tool_error_rate": _rate(calls_error, calls_total, empty=0.0),
            "irrelevant_call_rate": _rate(irrel_bad, irrel_total, empty=0.0),
            "arg_accuracy": _gated_rate(arg_ok, arg_total),
            "banned_call_rate": _gated_rate(banned_bad, banned_total),
        },
    )
