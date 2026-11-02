from evals.quality.cases import EvalCase, EvalTurn, GoldenTool, TurnGolden
from evals.quality.scorers.trajectory import score_trajectory
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(*turns: EvalTurn, reviewed=True) -> EvalCase:
    return EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=reviewed,
                    tags=("tool",), turns=tuple(turns))


def _turn(golden=None):
    return EvalTurn(user="u", expect={}, golden=golden)


def _trace(*turns: TraceTurn) -> TraceCase:
    return TraceCase(case_id="C1", tags=("tool",), tenant="t", channel="chat", reviewed=True, turns=tuple(turns))


def test_loop_exhaustion_rate():
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r", loop_exhausted=True))])
    assert s.metrics["loop_exhaustion_rate"] == 1.0
    assert any(f.kind == "loop_exhausted" for f in s.findings)


def test_repeated_identical_call_is_dead_end():
    calls = (TracedToolCall("kb_search", {"query": "giá"}), TracedToolCall("kb_search", {"query": "giá"}))
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r", tool_calls=calls))])
    assert s.metrics["repeated_call_rate"] == 1.0
    assert any(f.kind == "repeated_call" for f in s.findings)


def test_different_args_not_repeated():
    calls = (TracedToolCall("kb_search", {"query": "giá"}), TracedToolCall("kb_search", {"query": "pháp lý"}))
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r", tool_calls=calls))])
    assert s.metrics["repeated_call_rate"] == 0.0


def test_steps_overhead_floor_one():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    one = _trace(TraceTurn(user="u", reply="r", tool_calls=(TracedToolCall("kb_search", {}),)))
    three = _trace(TraceTurn(user="u", reply="r", tool_calls=(
        TracedToolCall("kb_search", {"query": "1"}), TracedToolCall("kb_search", {"query": "2"}),
        TracedToolCall("find_project", {}),)))
    assert score_trajectory([_case(_turn(g))], [one]).metrics["steps_overhead"] == 1.0
    assert score_trajectory([_case(_turn(g))], [three]).metrics["steps_overhead"] == 3.0
    # ít call hơn golden không được "thưởng" dưới 1.0
    zero = _trace(TraceTurn(user="u", reply="r"))
    assert score_trajectory([_case(_turn(g))], [zero]).metrics["steps_overhead"] == 1.0


def test_no_golden_tools_steps_overhead_none():
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r"))])
    assert s.metrics["steps_overhead"] is None


def test_empty_selection_gated_none():
    s = score_trajectory([], [])
    assert s.metrics["loop_exhaustion_rate"] is None


def test_unreviewed_skipped():
    s = score_trajectory([_case(_turn(), reviewed=False)],
                         [_trace(TraceTurn(user="u", reply="r", loop_exhausted=True))])
    assert s.checks == 0 and s.metrics["loop_exhaustion_rate"] is None
