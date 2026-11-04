import re
from pathlib import Path

import pytest

import noble_agent
from noble_agent.agent.agent_config import OPTIONAL_TOOLS
from noble_agent.agent.base import PERSONA_CHANNELS

SKELETON_BASE = Path(noble_agent.__file__).resolve().parent / "persona"
_KNOWN_PLACEHOLDERS = {
    "identity.agent_name", "identity.brand", "identity.honorific_self",
    "identity.honorific_customer",
    "scope.does", "scope.does_not", "scope.refusal", "scope.handoff_department",
    "style.tone_desc", "style.reply_length_desc",
    "d.ten", "d.khi_nao",   # loop vars over scope.departments
}

pytestmark = pytest.mark.parametrize("channel", PERSONA_CHANNELS)


def _dir(channel: str) -> Path:
    return SKELETON_BASE / channel


def _text(channel: str) -> str:
    d = _dir(channel)
    return (d / "SOUL.md").read_text("utf-8") + (d / "RULES.md").read_text("utf-8")


def test_no_config_json(channel):
    assert not (_dir(channel) / "config.json").exists()


def test_required_files_present(channel):
    for f in ("SOUL.md", "RULES.md", "PROMPT_TEMPLATE.md", "CUSTOMER_PROFILE.md"):
        assert (_dir(channel) / f).is_file()


def test_placeholders_are_known(channel):
    tokens = set(re.findall(r"\{\{\s*([a-z_.]+)\s*\}\}", _text(channel)))
    assert tokens <= _KNOWN_PLACEHOLDERS, f"unknown placeholders: {tokens - _KNOWN_PLACEHOLDERS}"


def test_tool_markers_balanced(channel):
    txt = _text(channel)
    for name in OPTIONAL_TOOLS:
        starts = txt.count(f"<!-- TOOL:{name}:START -->")
        ends = txt.count(f"<!-- TOOL:{name}:END -->")
        assert starts == ends, f"{name}: {starts} START vs {ends} END"
    assert txt.count("<!-- FENG_SHUI:START -->") == txt.count("<!-- FENG_SHUI:END -->")


def test_feng_shui_nested_in_search_units(channel):
    # Merge 2026-09-07: phong thủy sống trong search_units (tool căn hợp nhất).
    rules = (_dir(channel) / "RULES.md").read_text("utf-8")
    fs = rules.index("<!-- FENG_SHUI:START -->")
    su_start = rules.rindex("<!-- TOOL:search_units:START -->", 0, fs)
    su_end = rules.index("<!-- TOOL:search_units:END -->", fs)
    assert su_start < fs < su_end   # FENG_SHUI sits inside a search_units region


def test_core_tools_not_wrapped(channel):
    # core-tool text must never be inside a strippable region → grep the marker names
    txt = _text(channel)
    for core in ("update_customer", "kb_search", "find_project", "escalate"):
        assert f"<!-- TOOL:{core}:START -->" not in txt


def test_no_flat_skeleton_left(channel):
    # After the channel split, the base persona/ dir must not carry loadable
    # files — otherwise resolve_persona_dir's fallback could silently serve them.
    assert not (SKELETON_BASE / "SOUL.md").exists()


def test_update_customer_rule_batches_fields_into_one_call(channel):
    """Quy tắc 4 + Tool catalog: gộp mọi field khách vừa cho vào MỘT lời gọi
    update_customer — "mỗi field một call" bơm 3–4 tool message/lượt vào history
    và 3–4 lần persist DB cho một câu tự giới thiệu."""
    rules = (_dir(channel) / "RULES.md").read_text("utf-8")
    assert "mỗi field một call" not in rules
    assert "MỘT lời gọi" in rules


# ── Bước 2 review chất lượng: RULES chỉ giữ quy tắc XUYÊN tool; protocol riêng từng tool
# sống ở schema description (một nguồn sự thật). Ngân sách đo trên bản ĐÃ render với
# mọi tool optional bật — con số prefill thật mỗi lượt.
_RULES_BUDGET_CHARS = {"chat": 16_000, "voice": 11_000}  # gồm ~1k "Bản đồ tool" (index, không phải protocol)


def _rendered_rules(channel: str) -> str:
    from noble_agent.agent.agent_config import parse_config
    from noble_agent.agent.persona_compose import compose_persona

    cfg = parse_config({
        "name": "Luna", "brand_name": "Noble",
        "scope_does": "tư vấn dự án, đặt lịch tham quan", "scope_does_not": "hợp đồng, thanh toán",
        "departments": [{"ten": "CVTV", "khi_nao": "cần báo giá"}],
        "skills": list(OPTIONAL_TOOLS),
    })
    _soul, rules = compose_persona(_dir(channel), cfg)
    return rules


def test_rendered_rules_within_budget(channel):
    rules = _rendered_rules(channel)
    assert len(rules) <= _RULES_BUDGET_CHARS[channel], f"{channel} RULES = {len(rules)} chars"


def test_tool_protocol_lives_in_schema_not_rules(channel):
    raw = (_dir(channel) / "RULES.md").read_text("utf-8")
    assert "## Tool catalog" not in raw            # bảng "khi nào gọi tool gì" = schema description
    assert "use_profile_name" not in raw          # protocol đặt lịch (bước tên/số) → schema booking
    assert "category_fallback" not in raw         # luồng hai bước media → schema send_media
    assert "Operational Protocol" in raw          # quy tắc xuyên tool vẫn ở đây


def test_rules_explain_the_ephemeral_context_block(channel):
    raw = (_dir(channel) / "RULES.md").read_text("utf-8")
    assert "Ngữ cảnh hiện tại" in raw


def test_price_questions_are_routed_to_search_units_not_kb_search(channel):
    """27/08: tài liệu (kb_search) không có giá — giá căn lấy từ kho căn (search_units).
    Dòng bản đồ tool không được đẩy "Giá" vào kb_search nữa; khối search_units phải nhận
    câu hỏi giá (khối này bị cắt cho tenant không bật tool, khi đó kb_search là đường còn lại)."""
    raw = (_dir(channel) / "RULES.md").read_text("utf-8")
    assert "Giá / chính sách" not in raw
    blocks = re.findall(r"<!-- TOOL:search_units:START -->(.*?)<!-- TOOL:search_units:END -->", raw, re.S)
    assert any("giá" in b.lower() for b in blocks), blocks


def test_sales_policy_documents_are_routed_to_get_document(channel):
    """27/08: "có bản CSBH nào đang áp dụng / mới nhất" → get_document; kb_search chỉ nhận NỘI DUNG."""
    raw = (_dir(channel) / "RULES.md").read_text("utf-8")
    assert "- Chính sách / vay" not in raw
    blocks = re.findall(r"<!-- TOOL:get_document:START -->(.*?)<!-- TOOL:get_document:END -->", raw, re.S)
    assert any("đang áp dụng" in b for b in blocks), blocks


def test_escalate_rule_is_about_the_customers_transaction_not_purchase_status(channel):
    """27/08: 'chưa có sổ mà bán lại', 'điều khoản bất lợi HĐMB', 'cam kết có ghi vào hợp đồng không'
    là giao dịch của khách → escalate dù khách CHƯA mua; pháp lý DỰ ÁN vẫn kb_search."""
    raw = (_dir(channel) / "RULES.md").read_text("utf-8")
    assert "chuyển nhượng" in raw and "CHƯA mua" in raw
    assert "pháp lý phức tạp" not in raw                      # tiêu chí mơ hồ cũ đã thay bằng ranh giới rõ
