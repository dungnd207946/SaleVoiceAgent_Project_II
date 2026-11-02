"""Run-integrity axis — did the run actually PRODUCE the evidence it is scored on?

Every other scorer answers "was the agent right?". This one answers the question
that must be settled first: "did the agent run at all?". It exists because the
per-axis scorers only look at cases on THEIR axis, so no behaviour scorer sees a
crashed case on a different axis. Without this axis, `--axis tool` with every
case crashing (no LLM key, Postgres down) produces zero policy checks and no
tool assertions to fail — and the scorecard reads PASS over a run that measured
nothing. A release gate that goes green when the run collapsed is worse than no
gate, because it reads as evidence.

So this scorer is the one that IGNORES `axis`: it sees every selected case. It
does keep the `reviewed` filter, because it counts the cases that would
otherwise move a gated number — an unreviewed case crashing is not a release
blocker, it is a case still being authored.

`cases_gated` is the honest coverage number and is deliberately NOT gated: it is
informational, the reviewed-only companion to `config.cases_scored` (the size of
the whole selection).

Pure: no I/O, no agent import.
"""

from __future__ import annotations

from collections.abc import Sequence

from evals.quality.cases import EvalCase
from evals.quality.scorers import AxisScore, Finding
from evals.quality.trace import TraceCase

AXIS = "run"


def score_run_integrity(cases: Sequence[EvalCase], traces: Sequence[TraceCase]) -> AxisScore:
    by_id = {t.case_id: t for t in traces}
    findings: list[Finding] = []
    checks = 0
    gated = 0
    errored = 0
    missing = 0

    for case in cases:
        # NOTE: no `case.axis` filter — that is this scorer's whole point.
        if not case.reviewed:
            continue
        gated += 1
        checks += 1

        trace = by_id.get(case.id)
        if trace is None:
            missing += 1
            findings.append(Finding(case.id, -1, "missing_trace", "case ran no trace — run incomplete"))
            continue
        if trace.error:
            errored += 1
            findings.append(Finding(case.id, -1, "case_error", trace.error))
            continue
        if len(trace.turns) < len(case.turns):
            missing += 1
            findings.append(
                Finding(
                    case.id,
                    -1,
                    "missing_turn",
                    f"trace has {len(trace.turns)} turn(s), case has {len(case.turns)} — run incomplete",
                )
            )

    return AxisScore(
        axis=AXIS,
        checks=checks,
        failures=len(findings),
        findings=tuple(findings),
        metrics={
            # GATED. `None` when NO gated case was selected at all (e.g. every
            # selected case is `reviewed: false`): counting 0 errors across 0
            # inspected cases is not evidence the run was healthy.
            "cases_errored": None if gated <= 0 else float(errored),
            "cases_missing_trace": None if gated <= 0 else float(missing),
            # Informational, never gated — the reviewed-only coverage number.
            "cases_gated": float(gated),
        },
    )
