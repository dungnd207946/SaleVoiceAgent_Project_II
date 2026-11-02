"""Trajectory efficiency — agent có chạy dài dòng / kẹt dead-end không.

Deterministic, không judge, chấm MỌI case reviewed có trace (không cần golden):
- loop_exhaustion_rate: turn chạm MAX_TOOL_ITERATIONS (tín hiệu từ trace, do
  runner nghe warning của noble_agent.runner — xem quality/runner.py).
- repeated_call_rate: turn có ≥2 tool call trùng hệt (name, args) — agent lặp
  cùng một hành động là dấu dead-end loop; args so sánh sau json.dumps(sort_keys).
- steps_overhead: trên turn có golden.tools — số call thực (trừ tool miễn trừ)
  chia số tool golden, floor 1.0 (gọi ít hơn là việc của tool_selection, không
  phải "hiệu quả hơn").
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from evals.quality.cases import EvalCase
from evals.quality.scorers import AxisScore, Finding
from evals.quality.scorers.tool_selection import _EXEMPT_TOOLS, _gated_rate, _rate
from evals.quality.trace import TraceCase

AXIS = "trajectory"


def _call_key(name: str, args: dict) -> str:
    return f"{name}|{json.dumps(args or {}, sort_keys=True, ensure_ascii=False)}"


def score_trajectory(cases: Sequence[EvalCase], traces: Sequence[TraceCase]) -> AxisScore:
    by_id = {t.case_id: t for t in traces}
    findings: list[Finding] = []
    checks = 0
    turns_total = turns_exhausted = turns_repeated = 0
    overheads: list[float] = []

    for case in cases:
        if not case.reviewed:
            continue
        trace = by_id.get(case.id)
        if trace is None or trace.error:
            continue  # run_integrity đã tính crash/thiếu trace — đây là scorer hiệu quả, không phải toàn vẹn
        for i, case_turn in enumerate(case.turns):
            if i >= len(trace.turns):
                continue
            trace_turn = trace.turns[i]
            turns_total += 1

            if trace_turn.loop_exhausted:
                turns_exhausted += 1
                checks += 1
                # keep in sync with src/noble_agent/agent/runner.py:MAX_TOOL_ITERATIONS
                findings.append(Finding(case.id, i, "loop_exhausted", "turn hit MAX_TOOL_ITERATIONS (=7)"))

            keys = [_call_key(tc.name, tc.args) for tc in trace_turn.tool_calls]
            dupes = sorted({k for k in keys if keys.count(k) > 1})
            if dupes:
                turns_repeated += 1
                checks += 1
                findings.append(Finding(case.id, i, "repeated_call", f"gọi lặp y hệt: {dupes}"))

            golden = case_turn.golden
            if golden and golden.tools:
                actual = sum(1 for tc in trace_turn.tool_calls if tc.name not in _EXEMPT_TOOLS)
                overheads.append(max(1.0, actual / len(golden.tools)))

    return AxisScore(
        axis=AXIS,
        checks=checks,
        failures=len(findings),
        findings=tuple(findings),
        metrics={
            "loop_exhaustion_rate": _gated_rate(turns_exhausted, turns_total),
            "repeated_call_rate": _rate(turns_repeated, turns_total, empty=0.0),
            "steps_overhead": (sum(overheads) / len(overheads)) if overheads else None,
        },
    )
