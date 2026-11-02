import pytest

from noble_agent.agent import facade


class _FakeRunner:
    def __init__(self, v):
        self.v = v


@pytest.mark.asyncio
async def test_create_pins_version_and_reuses_runner(monkeypatch):
    facade._runners.clear()
    built = []

    async def fake_build(tenant_id, version, channel):
        built.append(version)
        return _FakeRunner(version)

    monkeypatch.setattr(facade, "_build_runner_for_version", fake_build)

    async def _v5(tenant_id):
        return 5

    monkeypatch.setattr(facade, "_resolve_current_version", _v5)
    a = await facade.NobleAgent.create("sess-A", channel="chat")
    assert a.pinned_version == 5 and a._runner.v == 5
    # a SECOND conversation at the same version reuses the cached runner (no rebuild)
    b = await facade.NobleAgent.create("sess-B", channel="chat")
    assert b._runner is a._runner and built == [5]

    # publish -> version 6; a NEW conversation gets v6, but 'a' keeps v5 (BR05)
    async def _v6(tenant_id):
        return 6

    monkeypatch.setattr(facade, "_resolve_current_version", _v6)
    c = await facade.NobleAgent.create("sess-C", channel="chat")
    assert c.pinned_version == 6 and a.pinned_version == 5 and a._runner.v == 5


@pytest.mark.asyncio
async def test_create_legacy_path_when_version_zero(monkeypatch):
    facade._runners.clear()
    sentinel = _FakeRunner(0)

    async def fake_get_runner(tenant_id, channel):
        return sentinel

    async def _v0(tenant_id):
        return 0

    monkeypatch.setattr(facade, "_resolve_current_version", _v0)
    monkeypatch.setattr(facade, "_get_runner", fake_get_runner)
    a = await facade.NobleAgent.create("sess-legacy", channel="chat")
    assert a.pinned_version == 0 and a._runner is sentinel
    assert not facade._runners  # legacy path does not touch the version registry


@pytest.mark.asyncio
async def test_resolve_current_version_zero_when_store_disabled(monkeypatch):
    class _S:
        agent_config_source = "legacy"
        tenant_store_enabled = False
        tenant_id = "noble"

    monkeypatch.setattr(facade, "get_settings", lambda: _S())
    # Store disabled → legacy package path signalled by version 0 (byte-identical
    # to pre-SP-C2). No store is ever constructed.
    assert await facade._resolve_current_version("noble") == 0


@pytest.mark.asyncio
async def test_get_runner_for_version_evicts_over_cap(monkeypatch):
    facade._runners.clear()
    monkeypatch.setattr(facade, "_RUNNERS_MAX", 4)

    async def fake_build(tenant_id, version, channel):
        return _FakeRunner(version)

    monkeypatch.setattr(facade, "_build_runner_for_version", fake_build)
    for v in range(1, 7):  # 6 distinct versions, cap is 4
        await facade._get_runner_for_version("noble", v, "chat")
    assert list(facade._runners.keys()) == [
        ("noble", 3, "chat"), ("noble", 4, "chat"), ("noble", 5, "chat"), ("noble", 6, "chat")
    ]


@pytest.mark.asyncio
async def test_get_runner_for_version_keyed_by_tenant_not_just_version(monkeypatch):
    """Same version number, different tenants, must never collide/share a runner."""
    facade._runners.clear()

    async def fake_build(tenant_id, version, channel):
        return _FakeRunner((tenant_id, version))

    monkeypatch.setattr(facade, "_build_runner_for_version", fake_build)
    a = await facade._get_runner_for_version("t_a", 5, "chat")
    b = await facade._get_runner_for_version("t_b", 5, "chat")
    assert a is not b
    assert list(facade._runners.keys()) == [("t_a", 5, "chat"), ("t_b", 5, "chat")]


@pytest.mark.asyncio
async def test_get_runner_for_version_keyed_by_channel(monkeypatch):
    """Same tenant + version, different persona channels → distinct runners."""
    facade._runners.clear()

    async def fake_build(tenant_id, version, channel):
        return _FakeRunner((tenant_id, version, channel))

    monkeypatch.setattr(facade, "_build_runner_for_version", fake_build)
    chat = await facade._get_runner_for_version("noble", 5, "chat")
    voice = await facade._get_runner_for_version("noble", 5, "voice")
    assert chat is not voice
    assert list(facade._runners.keys()) == [("noble", 5, "chat"), ("noble", 5, "voice")]


@pytest.mark.asyncio
async def test_ensure_version_built_goes_through_shared_cache(monkeypatch):
    """SP-D heartbeat warms a version through the SAME locked/cached path
    conversations use — so it never double-builds or races _get_runner_for_version."""
    facade._runners.clear()
    built = []

    async def fake_build(tenant_id, version, channel):
        built.append((version, channel))
        return _FakeRunner(version)

    monkeypatch.setattr(facade, "_build_runner_for_version", fake_build)
    await facade.ensure_version_built(7, tenant_id="noble")  # channel=None → warms every channel
    await facade.ensure_version_built(7, tenant_id="noble")  # cached — no rebuild
    assert built == [(7, "chat"), (7, "voice")]
    assert ("noble", 7, "chat") in facade._runners and ("noble", 7, "voice") in facade._runners


class _OutageStore:
    def read_pointer(self, tenant_id):
        raise RuntimeError("minio down")


class _LegacyStore:
    """In-place tenant: has a bundle but no published pointer (pre-SP-C1)."""

    def read_pointer(self, tenant_id):
        return None


class _GateSettings:
    agent_config_source = "legacy"
    tenant_store_enabled = True
    tenant_id = "noble"
    noble_config_poll_sec = 20.0


@pytest.mark.asyncio
async def test_resolve_version_legacy_in_place_uses_legacy_path(monkeypatch):
    """A tenant with no pointer (legacy in-place) → 0 so create() takes the
    legacy loader path (read_bundle read-compat), NOT the versioned path which
    has no versions/ to materialize. Regression: the current live `noble` is
    in-place, so the versioned path must not engage for it."""
    from noble_agent.tenant import version_resolver as VR

    VR.reset_for_tests()
    monkeypatch.setattr(facade, "get_settings", lambda: _GateSettings())
    monkeypatch.setattr("noble_agent.tenant.loader._build_store", lambda s: _LegacyStore())
    assert await facade._resolve_current_version("noble") == 0


@pytest.mark.asyncio
async def test_resolve_version_store_outage_serves_last_good(monkeypatch):
    """E01: store unreachable at the gate → serve the last-good version this
    process already resolved (not the package fallback)."""
    from noble_agent.tenant import version_resolver as VR

    VR.reset_for_tests()
    VR._last_good["noble"] = 4  # a version was resolved earlier this process
    monkeypatch.setattr(facade, "get_settings", lambda: _GateSettings())
    monkeypatch.setattr("noble_agent.tenant.loader._build_store", lambda s: _OutageStore())
    assert await facade._resolve_current_version("noble") == 4


@pytest.mark.asyncio
async def test_resolve_version_store_outage_no_last_good_falls_legacy(monkeypatch):
    """Cold process + store down → 0 (legacy/package path), fail-loud downstream."""
    from noble_agent.tenant import version_resolver as VR

    VR.reset_for_tests()
    monkeypatch.setattr(facade, "get_settings", lambda: _GateSettings())
    monkeypatch.setattr("noble_agent.tenant.loader._build_store", lambda s: _OutageStore())
    assert await facade._resolve_current_version("noble") == 0
