"""SP-E2 customers→contacts.profile: structured per-phone profile folded into contacts.

The old ``customers`` collection becomes the ``profile`` jsonb on ``tenant_data.contacts``.
Pins the truthy-merge clean, the "No Name" insert-only default, and jsonb-string parsing
on read (asyncpg returns jsonb as text).
"""

from __future__ import annotations

import pytest

from noble_agent.storage import pg_data_plane as DP


@pytest.fixture
def _tenant(monkeypatch):
    monkeypatch.setattr(DP, "_tenant_id", lambda: "noble")


class _PassthroughTenantConn:
    """tenant_conn stand-in: yields the fake pool itself as the "conn" so the
    monkeypatched DAO below still runs and observes the same fake handle,
    without needing a real asyncpg pool/txn."""

    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        return self._pool

    async def __aexit__(self, *a):
        return False


async def _pool_ok(monkeypatch):
    async def _p(tid):
        return object()

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    monkeypatch.setattr(DP, "tenant_conn", lambda pool, tid: _PassthroughTenantConn(pool))


async def _pool_none(monkeypatch):
    async def _p(tid):
        return None

    monkeypatch.setattr(DP, "_pool_or_none", _p)


async def test_persist_profile_cleans_and_defaults_no_name(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _upsert(db, **kw):
        seen.update(kw)

    monkeypatch.setattr(DP, "upsert_contact_profile", _upsert)
    await DP.persist_customer_profile("0912345678", {"budget": "3 tỷ", "phone": "x", "_id": "y", "empty": ""})

    assert seen["tenant_id"] == "noble"
    assert seen["phone"] == "0912345678"
    # truthy-only, drop _id/phone/empty
    assert seen["profile"] == {"budget": "3 tỷ"}
    # No Name only in the insert-only default (never overwrites a real later name)
    assert seen["insert_default"] == {"name": "No Name"}


async def test_persist_profile_keeps_bool_false(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _upsert(db, **kw):
        seen.update(kw)

    monkeypatch.setattr(DP, "upsert_contact_profile", _upsert)
    await DP.persist_customer_profile("09", {"name": "Hùng", "is_noble_customer": False})
    assert seen["profile"] == {"name": "Hùng", "is_noble_customer": False}
    assert seen["insert_default"] == {}  # real name → no default


async def test_persist_profile_noop_without_pool(monkeypatch, _tenant):
    await _pool_none(monkeypatch)
    called = []
    monkeypatch.setattr(DP, "upsert_contact_profile", lambda *a, **k: called.append(k))
    await DP.persist_customer_profile("09", {"name": "Hùng"})
    assert called == []


async def test_persist_profile_noop_without_phone(monkeypatch, _tenant):
    called = []

    async def _p(tid):
        called.append("pool")
        return object()

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    await DP.persist_customer_profile("", {"name": "Hùng"})
    assert called == []


async def test_persist_profile_swallows_error(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _upsert(db, **kw):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(DP, "upsert_contact_profile", _upsert)
    await DP.persist_customer_profile("09", {"name": "Hùng"})  # must not raise


async def test_read_profile_parses_jsonb_string(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _get(db, **kw):
        return {"snapshot": "s", "profile": '{"name": "Hùng", "gender": "M"}'}

    monkeypatch.setattr(DP, "get_contact", _get)
    assert await DP.read_customer_profile("09") == {"name": "Hùng", "gender": "M"}


async def test_read_profile_accepts_dict(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _get(db, **kw):
        return {"profile": {"name": "Lan"}}

    monkeypatch.setattr(DP, "get_contact", _get)
    assert await DP.read_customer_profile("09") == {"name": "Lan"}


async def test_read_profile_empty_without_pool(monkeypatch, _tenant):
    await _pool_none(monkeypatch)
    assert await DP.read_customer_profile("09") == {}


async def test_read_profile_empty_on_no_row(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _get(db, **kw):
        return None

    monkeypatch.setattr(DP, "get_contact", _get)
    assert await DP.read_customer_profile("09") == {}
