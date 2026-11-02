"""Schema case v2 — validation strict, lỗi phải kể tên file:line/field."""
import json

import pytest
from evals.quality.cases import load_case_dir, load_cases, parse_case


def _base(**over):
    d = {
        "id": "QA-001", "tenant": "t1", "origin": "handwritten", "reviewed": True,
        "tags": ["qa"], "channel": "chat",
        "turns": [{"user": "hỏi gì đó", "golden": {"answer": "trả lời chuẩn"}}],
    }
    d.update(over)
    return d


def test_parse_minimal_ok():
    case = parse_case(_base())
    assert case.tags == ("qa",)
    assert case.turns[0].golden.answer == "trả lời chuẩn"
    assert case.turns[0].expect == {}


def test_unknown_top_key_rejected():
    with pytest.raises(ValueError, match="unknown"):
        parse_case(_base(axis="tool"))  # schema cũ phải bị TỪ CHỐI


def test_unknown_tag_rejected():
    with pytest.raises(ValueError, match="tag"):
        parse_case(_base(tags=["qa", "banana"]))


def test_tool_called_in_expect_rejected_with_migration_hint():
    """`tool_called` còn trong vocabulary e2e nên phải chỉ đúng chỗ chuyển sang."""
    with pytest.raises(ValueError, match="golden.tools"):
        parse_case(_base(turns=[{"user": "u", "expect": {"tool_called": "kb_search"}}]))


def test_tool_keys_da_xoa_van_bi_tu_choi():
    """`tool_not_called`/`tool_arg` XOÁ khỏi KNOWN_KEYS 2026-08-25 → rơi vào nhánh
    unknown key. Vẫn phải fail, chỉ khác thông báo — case schema cũ không được lọt."""
    for key in ("tool_not_called", "tool_arg"):
        with pytest.raises(ValueError, match="unknown expect keys"):
            parse_case(_base(turns=[{"user": "u", "expect": {key: "kb_search"}}]))


def test_policy_expect_keys_ok():
    case = parse_case(_base(turns=[{"user": "u", "expect": {"reply_contains": ["x"], "escalated": True}}]))
    assert case.turns[0].expect["escalated"] is True


def test_golden_tools_matchers():
    turns = [{"user": "u", "golden": {"tools": [
        {"name": "kb_search", "args": {"query": {"contains": "khoáng nóng"}}},
        {"name": "find_project"},
    ], "banned_tools": ["escalate"]}}]
    case = parse_case(_base(turns=turns))
    g = case.turns[0].golden
    assert g.tools[0].args == {"query": {"contains": "khoáng nóng"}}
    assert g.tools[1].args == {}
    assert g.banned_tools == ("escalate",)


def test_bad_matcher_rejected():
    for bad in ({"regex": "x"}, {"contains": "a", "equals": "b"}, {}, "not-a-dict"):
        turns = [{"user": "u", "golden": {"tools": [{"name": "kb_search", "args": {"query": bad}}]}}]
        with pytest.raises(ValueError, match="matcher"):
            parse_case(_base(turns=turns))


def test_contains_matcher_must_be_str():
    turns = [{"user": "u", "golden": {"tools": [{"name": "t", "args": {"a": {"contains": 5}}}]}}]
    with pytest.raises(ValueError, match="contains"):
        parse_case(_base(turns=turns))


def test_unknown_golden_key_rejected():
    with pytest.raises(ValueError, match="unknown golden"):
        parse_case(_base(turns=[{"user": "u", "golden": {"evidence": "schema cũ"}}]))


def test_empty_turns_rejected():
    with pytest.raises(ValueError, match="turns"):
        parse_case(_base(turns=[]))


def test_load_cases_names_file_line(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps(_base()) + "\n" + "{bad json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="x.jsonl:2"):
        load_cases(p)


def test_load_case_dir_duplicate_id(tmp_path):
    (tmp_path / "a.jsonl").write_text(json.dumps(_base()) + "\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(json.dumps(_base()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_case_dir(tmp_path)
