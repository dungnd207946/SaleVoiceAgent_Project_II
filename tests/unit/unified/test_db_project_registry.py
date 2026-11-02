"""db_project_registry — sync cache accessors + test override (no live Postgres)."""

from __future__ import annotations

import pytest

from noble_agent.config import reset_settings_for_tests
from noble_agent.data import db_project_registry as reg
from noble_agent.data import providers


@pytest.fixture(autouse=True)
def _pin_pg_source(monkeypatch):
    # Pin the source + a bundle-less tenant so get_provider() resolves the
    # settings-driven pg_kb provider rather than the shipped "noble" manifest.
    monkeypatch.setenv("NOBLE_DATA_SOURCE", "pg_kb")
    monkeypatch.setenv("TENANT_ID", "_no_bundle_test_tenant")
    providers.reset_for_tests()
    reset_settings_for_tests()
    yield
    providers.reset_for_tests()
    reset_settings_for_tests()


def test_cached_codes_empty_when_cold():
    # pg_kb reads its roster from Postgres and carries NO bundled fallback, so a
    # cold provider yields an empty roster (never a fabricated code list).
    reg.set_cache_for_tests(None)
    assert reg.cached_codes() == []


def test_cached_codes_and_names_use_warm_cache():
    reg.set_cache_for_tests({"XYZ": {"code": "XYZ", "name": "Test Project", "region": "HN", "type": "Cao tầng"}})
    assert reg.cached_codes() == ["XYZ"]
    assert reg.code_to_name() == {"XYZ": "Test Project"}
    reg.set_cache_for_tests(None)
