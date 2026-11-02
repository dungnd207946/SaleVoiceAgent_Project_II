import pytest

from noble_agent.agent import facade

pytestmark = pytest.mark.asyncio


async def test_resolve_version_db_mode(monkeypatch):
    from noble_agent import config

    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)

    async def _fake(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig

        return PublishedConfig(version=7, config={})

    monkeypatch.setattr(facade, "read_published_config", _fake)
    assert await facade._resolve_current_version("org_1_t") == 7


async def test_resolve_version_db_none_returns_0(monkeypatch):
    from noble_agent import config

    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)

    async def _none(tid, **kw):
        return None

    monkeypatch.setattr(facade, "read_published_config", _none)
    assert await facade._resolve_current_version("org_1_t") == 0
