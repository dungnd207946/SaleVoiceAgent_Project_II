from pathlib import Path

import pytest

from noble_agent.tenant.current import use_tenant
from noble_agent.tenant.db_context import default_db_context, reset_db_context_for_tests, set_db_context
from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests


@pytest.fixture(autouse=True)
def _clean():
    reset_tenant_context_for_tests()
    reset_db_context_for_tests()
    yield
    reset_tenant_context_for_tests()
    reset_db_context_for_tests()


def test_db_mode_no_minio_default(monkeypatch):
    from noble_agent import config

    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    # Không set_db_context → default pg_kb, KHÔNG gọi manifest/MinIO
    monkeypatch.setattr(
        "noble_agent.tenant.loader._build_store",
        lambda s: (_ for _ in ()).throw(AssertionError("MinIO touched")),
    )
    with use_tenant("org_1_t"):
        ctx = get_tenant_context()
    assert ctx.data_source == "pg_kb"


def test_db_mode_returns_cached(monkeypatch):
    from noble_agent import config

    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    cached = default_db_context("org_1_t", skeleton_dir=Path("/tmp/sk"))
    set_db_context("org_1_t", cached)
    with use_tenant("org_1_t"):
        assert get_tenant_context() is cached
