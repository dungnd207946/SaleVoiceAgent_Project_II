# tests/unit/storage/test_pg_wrappers_use_tenant_conn.py
import pytest

from noble_agent.storage import pg_data_plane as dp


@pytest.mark.asyncio
async def test_read_contact_snapshot_scopes_to_current_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()

    seen = {}

    class _Conn:
        async def execute(self, sql, *a):
            pass

        async def fetchrow(self, sql, *a):
            seen["args"] = a
            return {"snapshot": "hi"}

    class _CM:
        def __init__(self, tid):
            seen["tenant"] = tid

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            return False

    async def _pool_stub(tid):
        return object()

    monkeypatch.setattr(dp, "_pool_or_none", _pool_stub)
    monkeypatch.setattr(dp, "tenant_conn", lambda pool, tid: _CM(tid))

    with use_tenant("acme"):
        out = await dp.read_contact_snapshot("0900000000")
    assert out == "hi"
    assert seen["tenant"] == "acme"  # scoped to the request tenant, not settings
    assert seen["args"][0] == "acme"  # tenant_id still an explicit query arg


@pytest.mark.asyncio
async def test_pool_or_none_uses_pool_for_tenant(monkeypatch):
    """Wrapper best-effort phải xin pool THEO TENANT (per-tenant role khi có creds)."""
    from noble_agent.storage import pg_data_plane

    seen = {}

    async def fake_pool_for_tenant(tid):
        seen["tid"] = tid
        return None  # đủ để wrapper no-op

    monkeypatch.setattr("noble_agent.storage.postgres_client.pool_for_tenant", fake_pool_for_tenant)
    assert await pg_data_plane._pool_or_none("anphu") is None
    assert seen["tid"] == "anphu"
