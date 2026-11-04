from pathlib import Path

import noble_agent
from noble_agent.agent.agent_config import parse_config
from noble_agent.agent.persona_compose import compose_persona, strip_tool_regions

# compose tests exercise the mechanism, not per-channel content — one channel is enough
SKELETON = Path(noble_agent.__file__).resolve().parent / "persona" / "chat"

_SAMPLE = (
    "keep base\n"
    "<!-- TOOL:booking:START -->\nbooking body\n<!-- TOOL:booking:END -->\n"
    "<!-- TOOL:recommend_units:START -->\nru body\n"
    "<!-- FENG_SHUI:START -->\nfengshui body\n<!-- FENG_SHUI:END -->\n"
    "<!-- TOOL:recommend_units:END -->\n"
    "tail\n"
)


def test_strip_removes_disabled_tool_block():
    out = strip_tool_regions(_SAMPLE, enabled_optional={"recommend_units"}, feng_shui=True)
    assert "booking body" not in out           # booking disabled → removed
    assert "ru body" in out and "fengshui body" in out
    assert "<!-- TOOL:" not in out and "<!-- FENG_SHUI:" not in out  # kept-region markers stripped


def test_strip_removes_fengshui_when_off_keeps_recommend():
    out = strip_tool_regions(_SAMPLE, enabled_optional={"recommend_units"}, feng_shui=False)
    assert "ru body" in out
    assert "fengshui body" not in out


def test_compose_fills_placeholders_and_strips(tmp_path):
    cfg = parse_config({
        "name": "Luna", "brand_name": "An Phú Land", "greeting": "",
        "scope_does": "Tư vấn.", "scope_does_not": "Hậu mãi.", "refusal_line": "Xin lỗi.",
        "departments": [{"ten": "CSKH", "khi_nao": "hợp đồng đã ký"}],
        "skills": ["search_units"],
    })
    soul, rules = compose_persona(SKELETON, cfg)
    assert "{{" not in soul and "{{" not in rules        # every placeholder filled
    assert "<!-- TOOL:" not in rules and "<!-- FENG_SHUI:" not in rules
    assert "Luna" in soul and "An Phú Land" in rules
    assert "booking body" not in rules                   # booking not enabled
    assert "search_units" in rules                       # its catalog row survives (as text)
    # booking disabled → its scheduling protocol text (rule 6) gone
    assert "action=\"schedule\"" not in rules and "check_availability" not in rules


def test_compose_greeting_never_in_soul():
    # The opening line moved to the voice transport (build_greeting); the
    # system prompt must not carry it even when configured.
    cfg = parse_config({"name": "Luna", "greeting": "Alô, Luna nghe đây ạ"})
    soul, _ = compose_persona(SKELETON, cfg)
    assert "Câu chào mở đầu" not in soul
    assert "Alô, Luna nghe đây ạ" not in soul
