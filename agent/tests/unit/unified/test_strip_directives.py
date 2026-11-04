"""orchestrator._strip_tool_directives — directive sống MỘT lượt.

Khối `instruction` trong tool result là chỉ đạo hành-động-ngay cho lượt hiện
tại; giữ nó trong history là để directive cũ chỉ đạo sai ngữ cảnh các lượt sau
+ phình token. Strip lúc persist (TRƯỚC save_all và TRƯỚC warm-cache) — trong
lượt model vẫn thấy đủ vì messages sống chưa qua persist; dữ liệu
(over_budget/price_delta_pct/highlights...) giữ nguyên, chỉ gỡ lời chỉ đạo.
"""

from __future__ import annotations

import json

from noble_agent.agent.orchestrator import _strip_tool_directives
from noble_agent.storage.models import ThreadMessage


def _tool(content: str) -> ThreadMessage:
    return ThreadMessage(role="tool", content=content, tool_call_id="c1", name="search_units")


def test_strips_top_level_and_nested_instruction():
    payload = {
        "instruction": "Giới thiệu 2-3 căn nổi bật",
        "count": 2,
        "units": [
            {"unit_code": "A-01", "over_budget": True, "price_delta_pct": 7, "instruction": "pitch"},
            {"unit_code": "B-01"},
        ],
    }
    history = [_tool(json.dumps(payload, ensure_ascii=False))]
    _strip_tool_directives(history, 0)
    out = json.loads(history[0].content)
    assert "instruction" not in out
    assert "instruction" not in out["units"][0]
    # Dữ liệu thật giữ nguyên — lượt sau vẫn biết căn nào vượt ngân sách.
    assert out["units"][0]["over_budget"] is True
    assert out["units"][0]["price_delta_pct"] == 7
    assert out["count"] == 2


def test_strips_group_upsell_instruction():
    # search_units (nhóm upsell) mang directive nhóm `upsell_instruction` — cũng là chỉ đạo
    # một-lượt, phải bị gỡ như `instruction`.
    payload = {
        "units": [{"unit_code": "W-00"}],
        "upsell_units": [{"unit_code": "U-00", "over_budget": True}],
        "instruction": "giới thiệu",
        "upsell_instruction": "chèo kéo",
    }
    history = [_tool(json.dumps(payload, ensure_ascii=False))]
    _strip_tool_directives(history, 0)
    out = json.loads(history[0].content)
    assert "instruction" not in out and "upsell_instruction" not in out
    assert out["upsell_units"][0]["over_budget"] is True


def test_non_json_tool_result_untouched():
    # kb_search trả chuỗi trần — không được đụng vào.
    history = [_tool("Dự án nằm tại Tây Hồ, pháp lý sổ đỏ lâu dài.")]
    _strip_tool_directives(history, 0)
    assert history[0].content == "Dự án nằm tại Tây Hồ, pháp lý sổ đỏ lâu dài."


def test_json_without_instruction_byte_identical():
    # Không có gì để gỡ → không re-dump (giữ nguyên byte, tránh xáo trộn vô cớ).
    raw = json.dumps({"ok": True, "updated_fields": ["name"]}, ensure_ascii=False)
    history = [_tool(raw)]
    _strip_tool_directives(history, 0)
    assert history[0].content == raw


def test_only_messages_from_start_index():
    old = _tool(json.dumps({"instruction": "cũ — đã strip từ lượt trước rồi mới phải"}))
    new = _tool(json.dumps({"instruction": "mới"}))
    history = [old, ThreadMessage(role="user", content="hỏi"), new]
    _strip_tool_directives(history, 1)
    assert "instruction" in json.loads(history[0].content)  # trước anchor: không đụng
    assert "instruction" not in json.loads(history[2].content)


def test_non_tool_roles_untouched():
    msg = ThreadMessage(role="assistant", content=json.dumps({"instruction": "x"}))
    history = [msg]
    _strip_tool_directives(history, 0)
    assert json.loads(history[0].content) == {"instruction": "x"}
