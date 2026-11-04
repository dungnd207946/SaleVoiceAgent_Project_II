import json

import pytest

from noble_agent.agent.tools import projects_info
from noble_agent.data import providers
from noble_agent.data.providers.base import ProjectRegistryRow
from tests.unit.unified.providers.test_base_contract import FakeProvider


@pytest.fixture(autouse=True)
def _reset():
    providers.reset_for_tests()
    yield
    providers.reset_for_tests()


async def test_tool_uses_active_provider_and_keeps_json_shape(monkeypatch):
    fake = FakeProvider(projects=[ProjectRegistryRow("MCP", "Masteri", "mien_nam", "can_ho")])
    monkeypatch.setattr(providers, "get_provider", lambda settings: fake)
    out = json.loads(await projects_info.discover_projects({}))
    assert out["count"] == 1
    assert set(out["projects"][0]) == {
        "code", "name", "region", "category", "investor", "price_from_vnd", "sale_phase",
    }
