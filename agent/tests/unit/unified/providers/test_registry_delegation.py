"""db_project_registry delegates its public accessors to the active provider."""

from __future__ import annotations

from noble_agent.data import db_project_registry as reg
from noble_agent.data import providers
from noble_agent.data.providers.base import ProjectRegistryRow


class _StubProvider:
    name = "stub"

    def registry_rows(self):
        return [ProjectRegistryRow("MCP", "Masteri Centre Point", "mien_bac", "can_ho")]

    def cached_codes(self):
        return ["MCP"]

    def code_to_name(self):
        return {"MCP": "Masteri Centre Point"}

    async def warm(self): ...

    async def warm_if_stale(self, ttl): ...


def test_registry_delegates_to_active_provider(monkeypatch):
    reg.set_cache_for_tests(None)
    monkeypatch.setattr(providers, "get_provider", lambda settings: _StubProvider())
    assert reg.cached_codes() == ["MCP"]
    assert reg.code_to_name()["MCP"] == "Masteri Centre Point"
    rows = reg.registry_rows()
    assert rows[0]["code"] == "MCP"
    assert rows[0]["name"] == "Masteri Centre Point"
    assert rows[0]["region"] == "mien_bac"
    assert rows[0]["type"] == "can_ho"
