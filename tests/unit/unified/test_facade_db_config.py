import pytest

from noble_agent import config as cfgmod
from noble_agent.agent import facade
from noble_agent.storage.agent_config_store import PublishedConfig


def test_settings_default_is_legacy():
    s = cfgmod.UnifiedSettings(_env_file=None)
    assert s.agent_config_source == "legacy"
    assert s.agent_temperature == 0.7
    assert s.agent_max_tokens == 800


async def test_db_path_builds_agentdef_from_published_config(monkeypatch):
    async def _fake_read(tenant_id, *, pool=None):
        return PublishedConfig(version=2, config={
            "name": "Luna", "brand_name": "An Phú Land",
            "scope_does": "Tư vấn.", "scope_does_not": "Hậu mãi.", "refusal_line": "Xin lỗi.",
            "departments": [{"ten": "CSKH", "khi_nao": "hợp đồng đã ký"}],
            "skills": ["booking"],
        })

    monkeypatch.setattr(facade, "read_published_config", _fake_read, raising=False)
    ad = await facade._agent_def_from_db("org_a1b2c3d4_x", "chat")
    assert ad.name == "Luna"
    names = {s["function"]["name"] for s in ad.tool_schemas}
    assert "booking" in names and "escalate" in names          # optional + core
    assert "discover_projects" not in names


async def test_db_path_none_raises(monkeypatch):
    async def _none(tenant_id, *, pool=None):
        return None

    monkeypatch.setattr(facade, "read_published_config", _none, raising=False)
    with pytest.raises(RuntimeError, match="no published config"):
        await facade._agent_def_from_db("org_a1b2c3d4_x", "chat")
