"""SP-E2 appointments cutover: best-effort PG wrappers map the booking dict ↔ PG.

Unit-level: the DAO round-trip itself is proven live (test_pg_data_plane_live.py).
Here we pin the field mapping (project ↔ project_code), the no-pool no-op, and the
swallow-on-error contract that keeps the booking hot path best-effort.
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
        return object()  # any non-None db handle

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    monkeypatch.setattr(DP, "tenant_conn", lambda pool, tid: _PassthroughTenantConn(pool))


async def _pool_none(monkeypatch):
    async def _p(tid):
        return None

    monkeypatch.setattr(DP, "_pool_or_none", _p)


def _booking() -> dict:
    return {
        "appointment_id": "APT12345",
        "session_id": "s1",
        "phone": "0912345678",
        "customer_name": "Hùng",
        "project": "NCLB",
        "preferred_date": "23/04/2026",
        "preferred_time": "09:00 - 10:00",
        "status": "confirmed",
    }


async def test_persist_appointment_maps_project_to_project_code(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _upsert(db, **kw):
        seen.update(kw)
        return 1

    monkeypatch.setattr(DP, "upsert_appointment", _upsert)
    await DP.persist_appointment(_booking(), "s1")

    assert seen["tenant_id"] == "noble"
    assert seen["appointment_id"] == "APT12345"
    assert seen["project_code"] == "NCLB"  # booking["project"] → PG project_code
    assert seen["phone"] == "0912345678"
    assert seen["customer_name"] == "Hùng"
    assert seen["status"] == "confirmed"
    assert seen["preferred_date"] == "23/04/2026"
    assert seen["preferred_time"] == "09:00 - 10:00"


async def test_persist_appointment_noop_without_pool(monkeypatch, _tenant):
    await _pool_none(monkeypatch)
    called = []

    async def _upsert(db, **kw):
        called.append(kw)

    monkeypatch.setattr(DP, "upsert_appointment", _upsert)
    await DP.persist_appointment(_booking(), "s1")  # must not raise
    assert called == []


async def test_persist_appointment_skips_without_appointment_id(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    called = []

    async def _upsert(db, **kw):
        called.append(kw)

    monkeypatch.setattr(DP, "upsert_appointment", _upsert)
    b = _booking()
    b["appointment_id"] = ""
    await DP.persist_appointment(b, "s1")
    assert called == []


async def test_persist_appointment_swallows_dao_error(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _upsert(db, **kw):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(DP, "upsert_appointment", _upsert)
    await DP.persist_appointment(_booking(), "s1")  # must not raise


async def test_read_hint_maps_project_code_to_project(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _get(db, **kw):
        return {"customer_name": "Hùng", "project_code": "NCLB"}

    monkeypatch.setattr(DP, "get_latest_appointment_by_phone", _get)
    hint = await DP.read_latest_booking_hint("0912345678")
    assert hint == {"customer_name": "Hùng", "project": "NCLB"}


async def test_read_hint_empty_without_pool(monkeypatch, _tenant):
    await _pool_none(monkeypatch)
    assert await DP.read_latest_booking_hint("0912345678") == {}


async def test_read_hint_empty_without_phone(monkeypatch, _tenant):
    called = []

    async def _p(tid):
        called.append(True)
        return object()

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    assert await DP.read_latest_booking_hint("") == {}
    assert called == []  # short-circuits before touching the pool


async def test_read_hint_swallows_error(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _get(db, **kw):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(DP, "get_latest_appointment_by_phone", _get)
    assert await DP.read_latest_booking_hint("0912345678") == {}
