"""Policy axis — deterministic hard assertions, no judge.

Wraps `tests/e2e_scenarios/assertions.py::evaluate` so the harness has exactly
ONE assertion vocabulary. `expect` lives in the case (not the trace) so a trace
can be re-scored after an assertion is tightened.

Chấm mọi case reviewed có `expect`. Vocabulary expect ở schema v2 không còn key
tool_* (loader từ chối), nên không thể double-count với tool_selection — đó là
lý do không cần axis filter nữa.

Only `reviewed` cases count — an unreviewed case may run, but it never moves a
number that gates a release.
"""

from __future__ import annotations

from collections.abc import Sequence

from tests.e2e_scenarios.assertions import ToolCall, TurnResult, evaluate

from evals.quality.cases import EvalCase
from evals.quality.scorers import AxisScore, Finding
from evals.quality.trace import TraceCase

AXIS = "policy"


def _to_turn_result(trace_turn) -> TurnResult:
    return TurnResult(
        user=trace_turn.user,
        reply=trace_turn.reply,
        # Keyword args on purpose: `ToolCall` lives in tests/e2e_scenarios (import-only
        # here), and its third field is named `result`. Positionally, a field reorder
        # there would silently miswire `raw_result` into the wrong slot.
        tool_calls=tuple(
            ToolCall(name=tc.name, args=dict(tc.args or {}), result=tc.raw_result) for tc in trace_turn.tool_calls
        ),
        customer=dict(trace_turn.customer_after or {}),
    )


def score_policy(cases: Sequence[EvalCase], traces: Sequence[TraceCase]) -> AxisScore:
    by_id = {t.case_id: t for t in traces}
    checks = 0
    findings: list[Finding] = []

    for case in cases:
        if not case.reviewed or not any(t.expect for t in case.turns):
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
        for i, case_turn in enumerate(case.turns):
            if not case_turn.expect:
                continue
            if i >= len(trace.turns):
                checks += 1
                findings.append(Finding(case.id, i, "missing_turn", "trace has fewer turns than the case"))
                continue
            for result in evaluate(case_turn.expect, _to_turn_result(trace.turns[i])):
                checks += 1
                if not result.ok:
                    findings.append(Finding(case.id, i, result.kind, result.detail))

    failures = len(findings)
    pass_rate = 1.0 if checks <= 0 else (checks - failures) / checks
    return AxisScore(
        axis=AXIS,
        checks=checks,
        failures=failures,
        findings=tuple(findings),
        metrics={
            # GATED. Zero policy checks performed (no policy case selected) means
            # this run measured no policy at all — `0.0` there would read as "zero
            # violations proven", which is the exact false PASS a `--axis tool` run
            # used to produce. `None` → gate FAILs as `missing`.
            "policy_violations": None if checks <= 0 else float(failures),
            # Ungated display summary → keep the vacuous 1.0.
            "policy_pass_rate": pass_rate,
        },
    )
