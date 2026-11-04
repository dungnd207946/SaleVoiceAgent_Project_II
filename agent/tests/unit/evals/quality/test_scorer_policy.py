"""Policy scorer tests — pure, driven by fabricated traces. No LLM, no agent."""

from __future__ import annotations

from evals.quality.cases import EvalCase, EvalTurn, parse_case
from evals.quality.scorers.policy import score_policy
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(expect: dict, case_id: str = "POL-1") -> object:
    return parse_case(
        {
            "id": case_id,
            "tags": ["policy"],
            "origin": "handwritten",
            "tenant": "noble",
            "channel": "chat",
            "reviewed": True,
            "turns": [{"user": "u", "expect": expect}],
        }
    )


def _trace(reply: str, tools: tuple = (), case_id: str = "POL-1") -> TraceCase:
    return TraceCase(
        case_id=case_id,
        tags=("policy",),
        tenant="noble",
        channel="chat",
        reviewed=True,
        turns=(TraceTurn(user="u", reply=reply, tool_calls=tools, customer_after={}),),
    )


def test_passing_case_has_no_failures():
    score = score_policy(
        [_case({"escalated": True})],
        [_trace("chuyển chuyên viên", (TracedToolCall("escalate", {}, "{}"),))],
    )
    assert score.axis == "policy"
    assert score.checks == 1
    assert score.failures == 0
    assert score.findings == ()
    assert score.pass_rate == 1.0


def test_missing_escalate_is_a_finding():
    score = score_policy([_case({"escalated": True})], [_trace("dạ em không rõ ạ")])
    assert score.failures == 1
    assert score.findings[0].case_id == "POL-1"
    assert score.findings[0].turn == 0
    assert score.findings[0].kind == "escalated"


def test_forbidden_price_pattern_is_a_finding():
    score = score_policy(
        [_case({"reply_not_matches": r"\d+\s*(tỷ|triệu)"})],
        [_trace("căn đó 5 tỷ ạ")],
    )
    assert score.failures == 1
    assert score.findings[0].kind == "reply_not_matches"


def test_unreviewed_cases_are_excluded():
    case = parse_case(
        {
            "id": "POL-2",
            "tags": ["policy"],
            "origin": "handwritten",
            "tenant": "noble",
            "channel": "chat",
            "reviewed": False,
            "turns": [{"user": "u", "expect": {"escalated": True}}],
        }
    )
    trace = _trace("không escalate", case_id="POL-2")
    score = score_policy([case], [trace])
    assert score.checks == 0
    assert score.failures == 0


def test_crashed_case_counts_as_one_failure():
    broken = TraceCase(
        case_id="POL-1", tags=("policy",), tenant="noble", channel="chat", reviewed=True, turns=(), error="Boom: x"
    )
    score = score_policy([_case({"escalated": True})], [broken])
    assert score.failures == 1
    assert score.findings[0].kind == "case_error"
    assert "Boom" in score.findings[0].detail


def test_case_without_a_trace_is_reported_not_silently_passed():
    score = score_policy([_case({"escalated": True})], [])
    assert score.failures == 1
    assert score.findings[0].kind == "missing_trace"


def test_metrics_expose_violation_count():
    score = score_policy([_case({"escalated": True})], [_trace("no escalate")])
    assert score.metrics["policy_violations"] == 1.0
    assert score.metrics["policy_pass_rate"] == 0.0


def test_scores_any_case_with_expect_regardless_of_tags():
    case = EvalCase(
        id="C1",
        origin="handwritten",
        tenant="t",
        channel="chat",
        reviewed=True,
        tags=("tool",),  # tag KHÔNG phải policy — vẫn phải chấm vì có expect
        turns=(EvalTurn(user="u", expect={"reply_contains": ["chào"]}, golden=None),),
    )
    trace = TraceCase(
        case_id="C1", tags=("tool",), tenant="t", channel="chat", reviewed=True,
        turns=(TraceTurn(user="u", reply="xin chào anh"),),
    )
    s = score_policy([case], [trace])
    assert s.checks == 1 and s.failures == 0


def test_policy_violations_is_none_when_no_case_was_checked():
    """C2: `0.0` over zero checks reads as "zero violations proven", which is a
    false PASS. `None` keeps the gate fail-closed.
    """
    score = score_policy([], [])
    assert score.metrics["policy_violations"] is None
    assert score.metrics["policy_pass_rate"] == 1.0


def test_case_without_expect_not_counted():
    case = EvalCase(
        id="C1",
        origin="handwritten",
        tenant="t",
        channel="chat",
        reviewed=True,
        tags=("qa",),
        turns=(EvalTurn(user="u", expect={}, golden=None),),
    )
    trace = TraceCase(
        case_id="C1", tags=("qa",), tenant="t", channel="chat", reviewed=True,
        turns=(TraceTurn(user="u", reply="r"),),
    )
    s = score_policy([case], [trace])
    assert s.checks == 0 and s.metrics["policy_violations"] is None
