from pathlib import Path

import noble_agent
from noble_agent.agent.agent_config import parse_config
from noble_agent.agent.base import build_agent_def_from_config

SKELETON = Path(noble_agent.__file__).resolve().parent / "persona" / "chat"


def _cfg(skills=()):
    return parse_config({
        "name": "Luna", "brand_name": "An Phú Land",
        "scope_does": "Tư vấn.", "scope_does_not": "Hậu mãi.", "refusal_line": "Xin lỗi.",
        "departments": [{"ten": "CSKH", "khi_nao": "hợp đồng đã ký"}],
        "skills": list(skills),
    })


def test_builds_agentdef_with_enabled_tools():
    cfg = _cfg(["booking", "search_units"])
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.5, max_tokens=700)
    assert ad.name == "Luna"
    assert ad.model == "m" and ad.temperature == 0.5 and ad.max_tokens == 700
    names = {s["function"]["name"] for s in ad.tool_schemas}
    assert {"update_customer", "kb_search", "find_project", "escalate", "booking", "search_units"} <= names
    assert "discover_projects" not in names          # not enabled


def test_brand_rendered_into_tool_schema():
    cfg = _cfg([])
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.7, max_tokens=800)
    blob = str(ad.tool_schemas)
    assert "{{ brand" not in blob and "{{brand" not in blob   # brand tokens rendered
    assert "An Phú Land" in blob                              # rendered from config.identity.brand


def test_identity_brand_and_greeting_carried_onto_agentdef():
    cfg = parse_config({"name": "Mai", "brand_name": "An Phú Land", "greeting": "Alô, Mai nghe đây ạ"})
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.7, max_tokens=800)
    assert ad.brand == "An Phú Land"
    assert ad.greeting == "Alô, Mai nghe đây ạ"
    # the greeting is transport-level only — never rendered into the prompt
    assert "Alô, Mai nghe đây ạ" not in ad.sections["soul"]


def test_feng_shui_params_present_when_search_units_enabled():
    # feng_shui is derived from search_units being enabled (no DB column yet),
    # so enabling search_units surfaces the phong-thuy params.
    cfg = _cfg(["search_units"])
    assert cfg.feng_shui is True
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.7, max_tokens=800)
    su = next(s for s in ad.tool_schemas if s["function"]["name"] == "search_units")
    props = su["function"]["parameters"]["properties"]
    assert "birth_year" in props and "menh" in props


def test_handoff_department_carried_onto_agentdef():
    # Bộ phận tiếp nhận mặc định của tenant đi theo AgentDef để dispatcher auto-escalate
    # và escalate-thiếu-department dùng đúng nó (không hardcode "CVTV").
    cfg = _cfg([])
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.7, max_tokens=800)
    assert ad.handoff_department == "CSKH"
