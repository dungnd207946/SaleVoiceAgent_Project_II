"""Unit tests for the pure assertion engine (no LLM, no I/O)."""

from __future__ import annotations

from tests.e2e_scenarios.assertions import ToolCall, TurnResult, evaluate


def _result(reply="", tool_calls=(), customer=None):
    return TurnResult(user="u", reply=reply, tool_calls=tuple(tool_calls), customer=customer or {})


def _ok(results):
    return all(r.ok for r in results)


class TestToolCalled:
    def test_called_pass(self):
        r = _result(tool_calls=[ToolCall("kb_search", {})])
        assert _ok(evaluate({"tool_called": "kb_search"}, r))

    def test_called_fail(self):
        r = _result(tool_calls=[ToolCall("escalate", {})])
        assert not _ok(evaluate({"tool_called": "kb_search"}, r))

    def test_called_list_all_required(self):
        r = _result(tool_calls=[ToolCall("kb_search", {})])
        results = evaluate({"tool_called": ["kb_search", "escalate"]}, r)
        assert not _ok(results)  # escalate missing


class TestReply:
    def test_contains_case_insensitive(self):
        r = _result(reply="Dự án Noble Crystal Long Biên rất đẹp")
        assert _ok(evaluate({"reply_contains": "noble crystal long biên"}, r))

    def test_contains_all_of_list(self):
        r = _result(reply="Long Biên, giá tốt")
        assert not _ok(evaluate({"reply_contains": ["Long Biên", "Tây Hồ"]}, r))

    def test_contains_any(self):
        r = _result(reply="bên Long Biên nhé")
        assert _ok(evaluate({"reply_contains_any": ["Long Biên", "Tây Hồ"]}, r))
        assert not _ok(evaluate({"reply_contains_any": ["Tây Hồ", "Quận 7"]}, r))

    def test_not_contains(self):
        r = _result(reply="em gửi thông tin nhé")
        assert _ok(evaluate({"reply_not_contains": "3.5 tỷ"}, r))
        assert not _ok(evaluate({"reply_not_contains": "thông tin"}, r))

    def test_not_matches_blocks_price(self):
        r = _result(reply="Căn này khoảng 3 tỷ ạ")
        assert not _ok(evaluate({"reply_not_matches": r"\d+\s*(tỷ|triệu)"}, r))
        r2 = _result(reply="Để em kết nối chuyên viên báo giá ạ")
        assert _ok(evaluate({"reply_not_matches": r"\d+\s*(tỷ|triệu)"}, r2))


class TestCustomerAndEscalate:
    def test_customer_field_equals(self):
        r = _result(customer={"project_interest": "NCLB"})
        spec = {"field": "project_interest", "equals": "NCLB"}
        assert _ok(evaluate({"customer_field": spec}, r))
        assert not _ok(evaluate({"customer_field": {"field": "project_interest", "equals": "NPLB"}}, r))

    def test_escalated_true(self):
        r = _result(tool_calls=[ToolCall("escalate", {})])
        assert _ok(evaluate({"escalated": True}, r))
        assert not _ok(evaluate({"escalated": False}, r))

    def test_escalated_false(self):
        r = _result(tool_calls=[ToolCall("kb_search", {})])
        assert _ok(evaluate({"escalated": False}, r))


def test_empty_expect_passes():
    assert evaluate({}, _result()) == []
