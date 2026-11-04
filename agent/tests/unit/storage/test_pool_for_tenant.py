"""pool_for_tenant: pool per-tenant từ credential, fallback shared khi không có."""

from datetime import UTC, datetime, timedelta

import pytest

from noble_agent.storage import postgres_client as pc
from noble_agent.storage import tenant_credentials as tc


def setup_function():
    tc.clear_for_tests()
    pc.set_pool_for_tests(None)
    pc.close_tenant_pools_for_tests()


def _exp():
    return datetime.now(UTC) + timedelta(hours=1)


def test_build_tenant_dsn_basic():
    dsn = pc.build_tenant_dsn("postgresql://10.50.13.220:5433/odyssey", "agent_anphu", "s3cret")
    assert dsn == "postgresql://agent_anphu:s3cret@10.50.13.220:5433/odyssey"


def test_build_tenant_dsn_quotes_special_chars():
    dsn = pc.build_tenant_dsn("postgresql://h:5432/db", "agent_a", "p@ss:w/ord")
    assert dsn == "postgresql://agent_a:p%40ss%3Aw%2Ford@h:5432/db"


def test_build_tenant_dsn_strips_existing_userinfo():
    dsn = pc.build_tenant_dsn("postgresql://old:cred@h:5432/db", "agent_a", "pw")
    assert dsn == "postgresql://agent_a:pw@h:5432/db"


async def test_no_credential_falls_back_to_shared(monkeypatch):
    shared = object()
    pc.set_pool_for_tests(shared)
    assert await pc.pool_for_tenant("anphu") is shared


async def test_credential_builds_tenant_pool(monkeypatch):
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": "postgresql://h:5432/db"})(),
    )
    created = {}

    async def fake_create_pool(dsn, **kw):
        created["dsn"] = dsn
        return object()

    monkeypatch.setattr(pc, "_create_tenant_pool", fake_create_pool)
    pool = await pc.pool_for_tenant("anphu")
    assert created["dsn"] == "postgresql://agent_anphu:pw@h:5432/db"
    # Gọi lần 2 cùng credential → cache, không dựng lại
    created.clear()
    assert await pc.pool_for_tenant("anphu") is pool
    assert created == {}


async def test_password_change_rebuilds_pool(monkeypatch):
    tc.register("anphu", role="agent_anphu", password="pw1", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": "postgresql://h:5432/db"})(),
    )

    class _FakePool:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    pools = []

    async def fake_create_pool(dsn, **kw):
        p = _FakePool()
        pools.append(p)
        return p

    monkeypatch.setattr(pc, "_create_tenant_pool", fake_create_pool)
    p1 = await pc.pool_for_tenant("anphu")
    tc.register("anphu", role="agent_anphu", password="pw2", expires_at=_exp())
    p2 = await pc.pool_for_tenant("anphu")
    assert p2 is not p1
    assert pools[0].terminated  # pool cũ bị đóng khi fingerprint đổi


async def test_credential_but_no_server_dsn_falls_back_shared(monkeypatch):
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": ""})(),
    )
    shared = object()
    pc.set_pool_for_tests(shared)
    assert await pc.pool_for_tenant("anphu") is shared


async def test_expired_credential_falls_back_shared():
    tc.register("anphu", role="agent_anphu", password="pw",
                expires_at=datetime.now(UTC) - timedelta(seconds=1))
    shared = object()
    pc.set_pool_for_tests(shared)
    assert await pc.pool_for_tenant("anphu") is shared


async def test_pool_build_failure_raises_no_fallback(monkeypatch):
    """Password sai / PG từ chối → lỗi nổi lên, KHÔNG rơi về shared (mở rộng quyền = sai hướng)."""
    tc.register("anphu", role="agent_anphu", password="bad", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": "postgresql://h:5432/db"})(),
    )

    async def boom(dsn, **kw):
        raise RuntimeError("auth failed")

    monkeypatch.setattr(pc, "_create_tenant_pool", boom)
    pc.set_pool_for_tests(object())
    with pytest.raises(RuntimeError):
        await pc.pool_for_tenant("anphu")
