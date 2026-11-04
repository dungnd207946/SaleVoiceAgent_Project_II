import pytest

from noble_agent.agent import facade


@pytest.mark.asyncio
async def test_create_captures_current_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()

    built = []

    async def fake_get_runner(tenant_id, channel):
        built.append(tenant_id)
        return object()

    async def _v0(tenant_id):
        return 0

    monkeypatch.setattr(facade, "_resolve_current_version", _v0)
    monkeypatch.setattr(facade, "_get_runner", fake_get_runner)

    with use_tenant("acme"):
        agent = await facade.NobleAgent.create("sess-1", channel="chat")
    assert agent.tenant_id == "acme"
    assert built == ["acme"]


def test_runners_keyed_by_tenant_version_and_channel():
    facade.reset_runner_for_tests()
    facade._runners[("t_a", 5, "chat")] = object()
    facade._runners[("t_b", 5, "chat")] = object()
    assert facade._runners[("t_a", 5, "chat")] is not facade._runners[("t_b", 5, "chat")]
    assert facade._RUNNERS_MAX >= 256
