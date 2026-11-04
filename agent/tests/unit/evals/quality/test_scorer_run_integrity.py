"""Run-integrity scorer tests — pure, fabricated traces.

This axis is the one that catches "the run itself collapsed". The per-axis
scorers only look at cases on their own axis, so without it a run where every
case crashed can read PASS.
"""

from __future__ import annotations

from evals.quality.cases import parse_case
from evals.quality.scorers.run_integrity import score_run_integrity
from evals.quality.trace import TraceCase, TraceTurn


def _case(case_id: str, tag: str = "tool", *, reviewed: bool = True, turns: int = 1):
    return parse_case(
        {
            "id": case_id,
            "tags": [tag],
            "origin": "handwritten",
            "tenant": "noble",
            "channel": "chat",
            "reviewed": reviewed,
            "turns": [{"user": f"u{i}", "expect": {}} for i in range(turns)],
        }
    )


def _trace(case_id: str, *, tag: str = "tool", error: str | None = None, turns: int = 1) -> TraceCase:
    return TraceCase(
        case_id=case_id,
        tags=(tag,),
        tenant="noble",
        channel="chat",
        reviewed=True,
        turns=tuple(TraceTurn(user=f"u{i}", reply="r", tool_calls=(), customer_after={}) for i in range(turns)),
        error=error,
    )


def test_healthy_run_reports_zero_and_no_findings():
    score = score_run_integrity([_case("TOOL-1"), _case("POL-1", "policy")], [_trace("TOOL-1"), _trace("POL-1")])
    assert score.axis == "run"
    assert score.metrics == {"cases_errored": 0.0, "cases_missing_trace": 0.0, "cases_gated": 2.0}
    assert score.findings == ()
    assert score.pass_rate == 1.0


def test_a_tool_axis_crash_is_counted_even_though_no_policy_case_exists():
    """I3 regression. `--axis tool` + every case crashing used to leave the policy
    scorer with zero cases and the tool scorer with no assertions to fail →
    scorecard PASS over a run that measured nothing.
    """
    score = score_run_integrity(
        [_case("TOOL-1"), _case("TOOL-2")],
        [_trace("TOOL-1", error="RuntimeError: no published config"), _trace("TOOL-2", error="OSError: pg down")],
    )
    assert score.metrics["cases_errored"] == 2.0
    assert [f.kind for f in score.findings] == ["case_error", "case_error"]
    assert "pg down" in score.findings[1].detail


def test_missing_trace_and_truncated_trace_both_count_as_missing():
    score = score_run_integrity(
        [_case("TOOL-1"), _case("TOOL-2", turns=3)],
        [_trace("TOOL-2", turns=1)],  # TOOL-1 absent; TOOL-2 stopped after 1 of 3 turns
    )
    assert score.metrics["cases_missing_trace"] == 2.0
    assert {f.kind for f in score.findings} == {"missing_trace", "missing_turn"}


def test_a_crashed_case_is_not_double_counted_as_missing():
    score = score_run_integrity([_case("TOOL-1", turns=2)], [_trace("TOOL-1", error="Boom: x", turns=0)])
    assert score.metrics["cases_errored"] == 1.0
    assert score.metrics["cases_missing_trace"] == 0.0


def test_it_sees_every_axis_not_just_its_own():
    """The whole point: no `case.axis` filter. A grounding-axis case crashing must
    still be counted, or a future axis's crashes go unnoticed.
    """
    score = score_run_integrity(
        [_case("POL-1", "policy"), _case("TOOL-1", "tool")],
        [_trace("POL-1", error="Boom: a"), _trace("TOOL-1", error="Boom: b")],
    )
    assert score.metrics["cases_errored"] == 2.0
    assert score.metrics["cases_gated"] == 2.0


def test_unreviewed_cases_are_not_gated():
    """An unreviewed case crashing is not a release blocker — it is a case still
    being authored, and it can never move a gated number.
    """
    score = score_run_integrity(
        [_case("TOOL-1", reviewed=False), _case("TOOL-2")],
        [_trace("TOOL-1", error="Boom: x"), _trace("TOOL-2")],
    )
    assert score.metrics["cases_errored"] == 0.0
    assert score.metrics["cases_gated"] == 1.0
    assert score.findings == ()


def test_no_gated_case_at_all_reports_none_so_the_gate_fails_closed():
    """A selection of only unreviewed cases inspected NOTHING. `0 errors out of 0
    cases` is not evidence the run was healthy, so both gated metrics go `None`.
    """
    score = score_run_integrity([_case("TOOL-1", reviewed=False)], [])
    assert score.metrics["cases_errored"] is None
    assert score.metrics["cases_missing_trace"] is None
    assert score.metrics["cases_gated"] == 0.0
