"""tool_selection — chấm golden.tools/banned_tools trên trace, thuần."""
from evals.quality.cases import EvalCase, EvalTurn, GoldenTool, TurnGolden
from evals.quality.scorers.tool_selection import score_tool_selection
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(golden: TurnGolden, *, reviewed=True) -> EvalCase:
    return EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=reviewed,
                    tags=("tool",), turns=(EvalTurn(user="u", expect={}, golden=golden),))


def _trace(calls: list[TracedToolCall], *, error=None) -> TraceCase:
    return TraceCase(case_id="C1", tags=("tool",), tenant="t", channel="chat", reviewed=True,
                     turns=(TraceTurn(user="u", reply="r", tool_calls=tuple(calls)),), error=error)


def test_selection_hit_and_contains_arg():
    g = TurnGolden(tools=(GoldenTool("kb_search", {"query": {"contains": "Khoáng Nóng"}}),))
    tr = _trace([TracedToolCall("kb_search", {"query": "alumi có khoáng nóng không"})])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["tool_selection_accuracy"] == 1.0
    assert s.metrics["arg_accuracy"] == 1.0
    assert s.failures == 0


def test_tool_khong_goi_thi_khong_cham_arg():
    """Tool vắng mặt = MỘT lỗi, do `tool_selection` đếm. `arg_accuracy` không đếm lại.

    Mẫu số rỗng ⇒ None (fail-closed ở gate), KHÔNG phải 0.0 — không đo được gì về arg
    thì phải nói là không đo được.
    """
    g = TurnGolden(tools=(GoldenTool("kb_search", {"query": {"contains": "x"}}),))
    s = score_tool_selection([_case(g)], [_trace([])])
    assert s.metrics["tool_selection_accuracy"] == 0.0
    assert s.metrics["arg_accuracy"] is None
    kinds = {f.kind for f in s.findings}
    assert "tool_selection" in kinds
    assert "tool_arg" not in kinds, "không được nhân bản lỗi chọn tool sang trục arg"


def test_arg_accuracy_khong_bi_pha_loang_boi_tool_vang_mat():
    """Case A gọi đúng tool + đúng arg; case B trượt tool khai 3 matcher.

    Mẫu số chỉ được đếm 1 (của case A) → 1.0, chứ không phải 1/4 = 0.25.
    """
    a = EvalCase(id="A", origin="handwritten", tenant="t", channel="chat", reviewed=True, tags=("tool",),
                 turns=(EvalTurn(user="u", expect={},
                                 golden=TurnGolden(tools=(GoldenTool("kb_search", {"query": {"contains": "giá"}}),))),))
    b = EvalCase(id="B", origin="handwritten", tenant="t", channel="chat", reviewed=True, tags=("tool",),
                 turns=(EvalTurn(user="u", expect={}, golden=TurnGolden(tools=(GoldenTool(
                     "search_units",
                     {"project_code": {"equals": "X"}, "product_type": {"equals": "biet_thu"},
                      "max_price": {"equals": 20000000000}}),))),))
    ta = TraceCase(case_id="A", tags=("tool",), tenant="t", channel="chat", reviewed=True,
                   turns=(TraceTurn(user="u", reply="r",
                                    tool_calls=(TracedToolCall("kb_search", {"query": "giá bán"}),)),))
    tb = TraceCase(case_id="B", tags=("tool",), tenant="t", channel="chat", reviewed=True,
                   turns=(TraceTurn(user="u", reply="r", tool_calls=()),))
    s = score_tool_selection([a, b], [ta, tb])
    assert s.metrics["arg_accuracy"] == 1.0
    assert s.metrics["tool_selection_accuracy"] == 0.5


def test_arg_sai_that_van_bi_bat_khi_tool_duoc_goi():
    """Lọc bớt mẫu số KHÔNG được làm mất lỗi tham số thật — đây là lý do gate tồn tại."""
    g = TurnGolden(tools=(GoldenTool("check_inventory", {"project_code": {"equals": "VINHOMES_OCEAN_PARK_3"}}),))
    tr = _trace([TracedToolCall("check_inventory", {"project_code": "VOP3"})])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["arg_accuracy"] == 0.0
    assert any(f.kind == "tool_arg" for f in s.findings)


def test_arg_thieu_han_trong_call_van_tinh_truot():
    """Tool được gọi nhưng KHÔNG truyền arg cần thiết — đó đúng là lỗi tham số."""
    g = TurnGolden(tools=(GoldenTool("search_units", {"max_price": {"equals": 5000000000}}),))
    tr = _trace([TracedToolCall("search_units", {"project_code": "X"})])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["arg_accuracy"] == 0.0


def test_equals_matcher():
    g = TurnGolden(tools=(GoldenTool("booking", {"num_guests": {"equals": 2}}),))
    ok = _trace([TracedToolCall("booking", {"num_guests": 2})])
    bad = _trace([TracedToolCall("booking", {"num_guests": 3})])
    assert score_tool_selection([_case(g)], [ok]).metrics["arg_accuracy"] == 1.0
    assert score_tool_selection([_case(g)], [bad]).metrics["arg_accuracy"] == 0.0


def test_any_call_of_name_may_satisfy_args():
    g = TurnGolden(tools=(GoldenTool("kb_search", {"query": {"contains": "pháp lý"}}),))
    tr = _trace([TracedToolCall("kb_search", {"query": "giá bán"}),
                 TracedToolCall("kb_search", {"query": "pháp lý sổ hồng"})])
    assert score_tool_selection([_case(g)], [tr]).metrics["arg_accuracy"] == 1.0


def test_banned_call_rate_gated():
    g = TurnGolden(banned_tools=("escalate",))
    hit = _trace([TracedToolCall("escalate", {})])
    clean = _trace([])
    assert score_tool_selection([_case(g)], [hit]).metrics["banned_call_rate"] == 1.0
    assert score_tool_selection([_case(g)], [clean]).metrics["banned_call_rate"] == 0.0
    # không case nào khai banned → None (fail-closed ở gate), KHÔNG phải 0.0
    g2 = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    tr2 = _trace([TracedToolCall("kb_search", {})])
    assert score_tool_selection([_case(g2)], [tr2]).metrics["banned_call_rate"] is None


def test_irrelevant_call_exempts_update_customer():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    tr = _trace([TracedToolCall("kb_search", {}), TracedToolCall("update_customer", {"name": "Nam"})])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["irrelevant_call_rate"] == 0.0
    tr2 = _trace([TracedToolCall("kb_search", {}), TracedToolCall("send_media", {})])
    assert score_tool_selection([_case(g)], [tr2]).metrics["irrelevant_call_rate"] == 1.0


def test_tool_error_rate():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    tr = _trace([TracedToolCall("kb_search", {}, raw_result='{"error": "boom"}')])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["tool_error_rate"] == 1.0  # 1 call, 1 lỗi
    assert any(f.kind == "tool_error" for f in s.findings)


def test_unreviewed_and_no_golden_skipped():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    s = score_tool_selection([_case(g, reviewed=False)], [_trace([])])
    assert s.checks == 0 and s.metrics["arg_accuracy"] is None


def test_missing_trace_and_case_error_are_findings():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    s = score_tool_selection([_case(g)], [])
    assert any(f.kind == "missing_trace" for f in s.findings)
    s2 = score_tool_selection([_case(g)], [_trace([], error="Boom: x")])
    assert any(f.kind == "case_error" for f in s2.findings)


def test_findings_imply_pass_rate_below_one():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    s = score_tool_selection([_case(g)], [_trace([])])
    assert s.findings and s.pass_rate < 1.0
