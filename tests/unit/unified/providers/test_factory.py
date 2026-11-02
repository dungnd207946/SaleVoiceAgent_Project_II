import pytest

from noble_agent.data import providers
from noble_agent.tenant.current import use_tenant

# A tenant id with no bundle on disk: get_tenant_context() raises for it, so
# _active_source() falls through to the settings stand-in's noble_data_source
# below — these tests exercise the settings-driven dispatch, not any real
# tenant manifest.
_NO_BUNDLE_TENANT = "_no_bundle_test_tenant"


class _S:  # minimal settings stand-in
    def __init__(self, source):
        self.noble_data_source = source


def test_factory_returns_pg_kb():
    with use_tenant(_NO_BUNDLE_TENANT):
        p = providers.get_provider(_S("pg_kb"))
    assert p.name == "pg_kb"


def test_factory_unknown_source_raises():
    with use_tenant(_NO_BUNDLE_TENANT), pytest.raises(ValueError):
        providers.get_provider(_S("nope"))


def test_factory_singleton_per_source():
    with use_tenant(_NO_BUNDLE_TENANT):
        assert providers.get_provider(_S("pg_kb")) is providers.get_provider(_S("pg_kb"))


def test_default_source_is_pg_kb(monkeypatch):
    monkeypatch.delenv("NOBLE_DATA_SOURCE", raising=False)
    from noble_agent.config import UnifiedSettings

    # `_env_file=None` bypasses the repo's `.env` (which may already pin a source
    # for local dev) so this exercises the code default.
    assert UnifiedSettings(_env_file=None).noble_data_source == "pg_kb"


def test_discover_page_size_default_is_5():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)  # bypass repo-local .env
    assert s.discover_page_size == 5


def test_provider_instances_are_per_tenant(monkeypatch):
    from noble_agent.config import get_settings, reset_settings_for_tests

    monkeypatch.setenv("TENANT_ID", "noble")
    monkeypatch.setenv("NOBLE_DATA_SOURCE", "pg_kb")
    reset_settings_for_tests()
    providers.reset_for_tests()
    s = get_settings()

    with use_tenant("t_a"):
        pa = providers.get_provider(s)
        pa2 = providers.get_provider(s)
    with use_tenant("t_b"):
        pb = providers.get_provider(s)

    assert pa is pa2  # same tenant → cached
    assert pa is not pb  # different tenant → distinct instance (distinct roster cache)
