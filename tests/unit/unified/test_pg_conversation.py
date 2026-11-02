"""SP-E2 conversations cutover: best-effort PG wrappers map the summary doc ↔ PG.

Unit-level: the DAO round-trip is proven live (test_pg_data_plane_live.py). Here we
pin the summary_doc → record_conversation mapping (project_code → project, running
version threading), the memory-read hint shape, and the best-effort no-op/swallow
contract that keeps the call-end path from ever raising.
"""

from __future__ import annotations

from datetime import UTC, datetime

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


class _FakeConn:
    """persist_conversation hỏi escalations trước khi upsert — conn phải trả lời được."""

    async def fetchval(self, sql, *a):
        return False


async def _pool_ok(monkeypatch):
    async def _p(tid):
        return _FakeConn()

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    monkeypatch.setattr(DP, "tenant_conn", lambda pool, tid: _PassthroughTenantConn(pool))


async def _pool_none(monkeypatch):
    async def _p(tid):
        return None

    monkeypatch.setattr(DP, "_pool_or_none", _p)


def _summary_doc() -> dict:
    return {
        "session_id": "sid-1",
        "customer_name": "Anh Ba",
        "summary": "quan tâm 2PN",
        "project_code": "VRI",
        "transferred_to_sales": True,
        "started_at": datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 7, 30, 9, 5, tzinfo=UTC),
    }


async def test_persist_conversation_maps_doc(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 42

    monkeypatch.setattr(DP, "record_conversation", _rec)
    cid = await DP.persist_conversation(_summary_doc(), phone="0900000002", session_id="sid-1", running_version=7)

    assert cid == 42
    assert seen["tenant_id"] == "noble"
    assert seen["session_id"] == "sid-1"
    assert seen["phone"] == "0900000002"
    assert seen["customer_name"] == "Anh Ba"
    assert seen["project"] == "VRI"  # summary_doc["project_code"] → PG project
    assert seen["summary"] == "quan tâm 2PN"
    assert seen["transferred_to_sales"] is True
    assert seen["running_version"] == 7
    assert seen["started_at"].hour == 9 and seen["ended_at"].minute == 5


async def test_persist_conversation_noop_without_pool(monkeypatch, _tenant):
    await _pool_none(monkeypatch)
    called = []

    async def _rec(db, **kw):
        called.append(kw)

    monkeypatch.setattr(DP, "record_conversation", _rec)
    assert await DP.persist_conversation(_summary_doc(), phone="09", session_id="sid-1") is None
    assert called == []


async def test_persist_conversation_noop_without_phone_or_session(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    called = []

    async def _rec(db, **kw):
        called.append(kw)

    monkeypatch.setattr(DP, "record_conversation", _rec)
    assert await DP.persist_conversation(_summary_doc(), phone="", session_id="sid-1") is None
    assert await DP.persist_conversation(_summary_doc(), phone="09", session_id="") is None
    assert called == []


async def test_persist_conversation_swallows_error(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _rec(db, **kw):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(DP, "record_conversation", _rec)
    assert await DP.persist_conversation(_summary_doc(), phone="09", session_id="sid-1") is None


async def test_list_conversation_hints_returns_rows(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    rows = [{"session_id": "s2", "ended_at": datetime.now(UTC)}, {"session_id": "s1", "ended_at": None}]

    async def _list(db, **kw):
        assert kw["phone"] == "09" and kw["limit"] == 5
        return rows

    monkeypatch.setattr(DP, "list_conversations_by_phone", _list)
    assert await DP.list_conversation_hints("09", limit=5) == rows


async def test_list_conversation_hints_empty_without_pool(monkeypatch, _tenant):
    await _pool_none(monkeypatch)
    assert await DP.list_conversation_hints("09") == []


async def test_list_conversation_hints_swallows_error(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _list(db, **kw):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(DP, "list_conversations_by_phone", _list)
    assert await DP.list_conversation_hints("09") == []


# ── no transcript snapshot on conversations ─────────────────────────────────


class _FakeRowDB:
    """Captures the SQL + positional args passed to fetchrow (the DAO's INSERT)."""

    def __init__(self):
        self.sql: str = ""
        self.args: tuple = ()

    async def fetchrow(self, sql, *args):
        self.sql = sql
        self.args = args
        return {"id": 99}


async def test_record_conversation_writes_no_full_conversation():
    db = _FakeRowDB()
    rid = await DP.record_conversation(db, tenant_id="noble", session_id="sid-1")
    assert rid == 99
    # the transcript lives in conversation_messages — the flat call record must
    # not reference the dropped full_conversation column
    assert "full_conversation" not in db.sql
    assert len(db.args) == 13


async def test_record_conversation_writes_source():
    db = _FakeRowDB()
    await DP.record_conversation(db, tenant_id="noble", session_id="sid-1", source="voice")
    assert "source" in db.sql
    assert "voice" in db.args
    # empty source normalizes to NULL so the merge-upsert COALESCE preserves
    # a previously-written value instead of clobbering it with ''
    db2 = _FakeRowDB()
    await DP.record_conversation(db2, tenant_id="noble", session_id="sid-1", source="")
    assert None in db2.args and "" not in db2.args


async def test_record_conversation_writes_agent_key_id():
    """Cột DB là bigint (Portal tạo, id số của control.agent_keys) — DAO nhận int."""
    db = _FakeRowDB()
    await DP.record_conversation(db, tenant_id="noble", session_id="sid-1", agent_key_id=20)
    assert "agent_key_id" in db.sql
    assert 20 in db.args


async def test_persist_conversation_stamps_agent_key_id_from_context(monkeypatch, _tenant):
    """Contextvar giữ string (đi qua header/stash) — biên PG convert sang int."""
    from noble_agent.tenant.current import reset_current_agent_key_id, set_current_agent_key_id

    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 1

    monkeypatch.setattr(DP, "record_conversation", _rec)
    tok = set_current_agent_key_id("20")
    try:
        await DP.persist_conversation(_summary_doc(), phone="09", session_id="sid-1")
    finally:
        reset_current_agent_key_id(tok)
    assert seen["agent_key_id"] == 20


async def test_persist_conversation_non_numeric_agent_key_becomes_null(monkeypatch, _tenant):
    """Giá trị không phải số KHÔNG được làm chết INSERT (bug live 2026-08-19:
    str '20' vào cột bigint → DataError → mất cả row conversations) — về NULL."""
    from noble_agent.tenant.current import reset_current_agent_key_id, set_current_agent_key_id

    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 1

    monkeypatch.setattr(DP, "record_conversation", _rec)
    tok = set_current_agent_key_id("ak_khong_phai_so")
    try:
        await DP.persist_conversation(_summary_doc(), phone="09", session_id="sid-1")
    finally:
        reset_current_agent_key_id(tok)
    assert seen["agent_key_id"] is None


async def test_persist_conversation_agent_key_id_none_without_context(monkeypatch, _tenant):
    """Dev/REPL/telephony không qua gateway → cột NULL, không phải lỗi."""
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 1

    monkeypatch.setattr(DP, "record_conversation", _rec)
    await DP.persist_conversation(_summary_doc(), phone="09", session_id="sid-1")
    assert seen["agent_key_id"] is None


async def test_persist_conversation_passes_source(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 1

    monkeypatch.setattr(DP, "record_conversation", _rec)
    await DP.persist_conversation(_summary_doc(), phone="09", session_id="sid-1", source="chat")
    assert seen["source"] == "chat"
