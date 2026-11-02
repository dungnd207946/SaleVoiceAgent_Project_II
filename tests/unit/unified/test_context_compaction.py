"""Bước 3 review chất lượng — dựng request từ history: kết quả tool của các lượt CŨ
được rút gọn thành digest, khối ngữ cảnh ephemeral chèn vào user message cuối.
History persist KHÔNG đổi — chỉ bản request gửi LLM."""

from __future__ import annotations

import json

from noble_agent.agent.context_compaction import build_request_messages, digest_tool_result
from noble_agent.storage.models import ThreadMessage

_KB = (
    "[Noble Crystal › Giá bán]\nGiá từ 90 triệu/m², căn 2PN từ 3,2 tỷ. " + "x" * 600 + "\n---\n"
    "[Noble Crystal › Chính sách bán hàng]\nVay 70% ân hạn gốc 24 tháng. " + "y" * 600
)
_UNITS = json.dumps(
    {
        "units": [
            {
                "unit_code": "A-1203",
                "bedrooms": 2,
                "price_vnd": 3200000000,
                "project_name": "Noble Crystal",
                "direction": "dong_nam",
                "area_built_m2": 72.5,
                "product_type": "chung_cu",
            },
            {
                "unit_code": "B-0805",
                "bedrooms": 3,
                "price_vnd": 4500000000,
                "project_name": "Noble Crystal",
                "direction": "tay",
                "area_built_m2": 95.0,
                "product_type": "chung_cu",
            },
        ],
        "counts": {"total": 2},
        "criteria": {},
        "instruction": "Giới thiệu 2-3 căn nổi bật " + "z" * 300,
    },
    ensure_ascii=False,
)


def _tc(name, args, cid="c1"):
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def test_kb_search_digest_keeps_query_and_section_headers():
    d = digest_tool_result("kb_search", {"query": "giá Noble Crystal"}, _KB)
    assert "giá Noble Crystal" in d
    assert "Noble Crystal › Giá bán" in d and "Chính sách bán hàng" in d
    assert len(d) < 300 and "xxxx" not in d


def test_units_digest_lists_code_bedrooms_price_project():
    d = digest_tool_result("search_units", {}, _UNITS)
    assert "A-1203" in d and "B-0805" in d
    assert "2PN" in d and "3,2 tỷ" in d and "Noble Crystal" in d
    assert "zzzz" not in d and len(d) < 400


def test_short_results_are_left_verbatim():
    small = json.dumps({"ok": True, "updated_fields": ["name"]})
    assert digest_tool_result("update_customer", {}, small) == small


def test_unknown_big_result_is_truncated_not_dropped():
    big = json.dumps({"blob": "w" * 2000})
    d = digest_tool_result("some_tool", {}, big)
    assert d.startswith(big[:100]) and len(d) < 400


def _history():
    return [
        ThreadMessage(role="user", content="giá Noble Crystal?"),
        ThreadMessage(
            role="assistant", content="", tool_calls=[_tc("kb_search", {"query": "giá Noble Crystal"}, "c1")]
        ),
        ThreadMessage(role="tool", tool_call_id="c1", name="kb_search", content=_KB),
        ThreadMessage(role="assistant", content="Giá từ 90 triệu/m²."),
        ThreadMessage(role="user", content="có căn nào 2 ngủ?"),
        ThreadMessage(role="assistant", content="", tool_calls=[_tc("search_units", {"bedrooms": 2}, "c2")]),
        ThreadMessage(role="tool", tool_call_id="c2", name="search_units", content=_UNITS),
        ThreadMessage(role="assistant", content="Có căn A-1203."),
        ThreadMessage(role="user", content="căn đó hướng gì?"),
    ]


def test_tool_results_outside_last_two_user_turns_are_digested():
    out = build_request_messages(_history(), keep_user_turns=2)
    tools = [m for m in out if m["role"] == "tool"]
    assert len(tools) == 2
    assert "xxxx" not in tools[0]["content"] and "Giá bán" in tools[0]["content"]  # lượt 1: digest
    assert tools[1]["content"] == _UNITS  # lượt 2: nguyên văn
    assert tools[0]["tool_call_id"] == "c1" and tools[0]["name"] == "kb_search"
    # assistant tool_calls giữ nguyên
    assert out[1]["tool_calls"][0]["id"] == "c1"


def test_history_objects_are_not_mutated():
    h = _history()
    build_request_messages(h, keep_user_turns=1, ephemeral="[ctx]")
    assert h[2].content == _KB and h[6].content == _UNITS and h[-1].content == "căn đó hướng gì?"


def test_ephemeral_block_is_prepended_to_last_user_message_only():
    out = build_request_messages(_history(), keep_user_turns=2, ephemeral="[Ngữ cảnh hiện tại]\nHồ sơ: tên Hùng")
    assert out[-1]["role"] == "user"
    assert out[-1]["content"].startswith("[Ngữ cảnh hiện tại]") and out[-1]["content"].endswith("căn đó hướng gì?")
    assert out[0]["content"] == "giá Noble Crystal?"  # user message cũ không bị chèn


def test_no_ephemeral_when_none_and_no_user_message():
    out = build_request_messages(_history(), ephemeral=None)
    assert out[-1]["content"] == "căn đó hướng gì?"
    assert (
        build_request_messages([ThreadMessage(role="assistant", content="x")], ephemeral="[ctx]")[0]["content"] == "x"
    )


def test_start_offset_applies_to_summary_boundary():
    h = _history()
    out = build_request_messages(h, start=4, keep_user_turns=2)
    assert out[0]["content"] == "có căn nào 2 ngủ?"
    assert len(out) == 5
