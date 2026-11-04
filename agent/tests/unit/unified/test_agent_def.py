from noble_agent.agent.base import AgentDef, load_agent_def
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


def test_load_agent_def_returns_populated_object():
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    assert isinstance(agent, AgentDef)
    assert agent.name == "Luna"
    assert agent.temperature == 0.7
    assert agent.max_tokens == 800
    assert "update_customer" in agent.tool_names
    assert "switch_agent" not in agent.tool_names
    assert len(agent.tool_names) == 10
    assert "recall_memory" not in agent.tool_names
    assert "analyze_projects" in agent.tool_names
    assert "find_project" in agent.tool_names


def test_load_agent_def_has_sections():
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    assert "Luna" in agent.sections["soul"]
    assert "Operational Protocol" in agent.sections["rules"]
    assert "customer.name" in agent.sections["customer_format"]
    assert agent.prompt_template is not None


def test_load_agent_def_has_tool_schemas():
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    assert len(agent.tool_schemas) == 10
    names = {s["function"]["name"] for s in agent.tool_schemas}
    assert "switch_agent" not in names
    assert "escalate" in names


def test_load_agent_def_injects_custom_name():
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS, agent_name="Aria")
    assert agent.name == "Aria"
    assert "Aria" in agent.sections["soul"]
    assert "Luna" not in agent.sections["soul"]
    assert "Aria" in agent.sections["rules"]
    assert "Luna" not in agent.sections["rules"]


def test_load_agent_def_default_name_luna():
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    assert agent.name == "Luna"
    assert "Luna" in agent.sections["soul"]


def test_legacy_bundle_handoff_department_defaults_to_cvtv():
    # Bundle legacy không có cột departments → giữ hành vi cũ ("CVTV").
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    assert agent.handoff_department == "CVTV"


def test_legacy_bundle_update_customer_rule_batches_fields():
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    assert "mỗi field một call" not in agent.sections["rules"]
    assert "mỗi field, parallel OK" not in agent.sections["rules"]
    assert "MỘT lời gọi" in agent.sections["rules"]
