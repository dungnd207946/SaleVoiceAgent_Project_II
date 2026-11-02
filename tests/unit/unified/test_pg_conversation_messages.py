"""Realtime per-message PG transcript (tenant_data.conversation_messages).

One row per turn message, inserted fire-and-forget from the orchestrator's
existing delta cursor — never on the streaming hot path. Format contract:
core {seq, role, content, created_at} + optional extensions in ``meta`` jsonb
(tool_calls / name / tool_call_id). Idempotent on (tenant, session, seq) via
ON CONFLICT DO UPDATE so a retry rewrites and a session reset that reuses the
session_id overwrites from seq 0 instead of silently dropping.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.config import UnifiedSettings
from noble_agent.storage import persist
from noble_agent.storage import pg_data_plane as DP
from noble_agent.storage.models import State, ThreadMessage
from noble_agent.storage.repo import StateRepo
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR

# ── ThreadMessage.created_at ─────────────────────────────────────────────────


def test_thread_message_stamps_created_at_utc():
    before = datetime.now(UTC)
    m = ThreadMessage(role="user", content="hi")
    after = datetime.now(UTC)
    assert m.created_at is not None
    assert m.created_at.tzinfo is not None
    assert before <= m.created_at <= after


def test_thread_message_created_at_roundtrips_json():
    m = ThreadMessage(role="assistant", content="dạ")
    back = ThreadMessage.model_validate_json(m.model_dump_json())
    assert back.created_at == m.created_at


def test_legacy_state_blob_without_created_at_still_validates():
    raw = json.dumps(
        {"history": [{"role": "user", "content": "cũ"}], "summary": None, "scratchpad": {}}
    )
    state = State.model_validate_json(raw)
    assert state.history[0].content == "cũ"
    assert state.history[0].created_at is not None  # stamped at load, never None


def test_to_openai_never_leaks_created_at():
    m = ThreadMessage(role="user", content="hi")
    assert "created_at" not in m.to_openai()


# ── DAO: insert_conversation_messages ────────────────────────────────────────


class _FakeManyDB:
    def __init__(self):
        self.sql = ""
        self.rows: list[tuple] = []

    async def executemany(self, sql, rows):
        self.sql = sql
        self.rows = list(rows)


async def test_insert_conversation_messages_batch_shape():
    db = _FakeManyDB()
    ts = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
    await DP.insert_conversation_messages(
        db,
        tenant_id="noble",
        session_id="sid-1",
        messages=[
            {"seq": 0, "role": "user", "content": "hỏi", "created_at": ts, "meta": {}},
            {
                "seq": 1,
                "role": "assistant",
                "content": "",
                "created_at": ts,
                "meta": {"tool_calls": [{"id": "t1"}]},
            },
        ],
    )
    assert "tenant_data.conversation_messages" in db.sql
    assert "ON CONFLICT (tenant_id, session_id, seq) DO UPDATE" in db.sql
    assert len(db.rows) == 2
    assert db.rows[0][:5] == ("noble", "sid-1", 0, "user", "hỏi")
    assert db.rows[0][5] == ts
    assert json.loads(db.rows[1][6]) == {"tool_calls": [{"id": "t1"}]}


async def test_insert_conversation_messages_noop_on_empty():
    db = _FakeManyDB()
    await DP.insert_conversation_messages(db, tenant_id="noble", session_id="sid-1", messages=[])
    assert db.rows == [] and db.sql == ""


# ── wrapper: persist_turn_messages ───────────────────────────────────────────


@pytest.fixture
def _tenant(monkeypatch):
    monkeypatch.setattr(DP, "_tenant_id", lambda: "noble")


class _PassthroughTenantConn:
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


def _turn_messages() -> list[ThreadMessage]:
    return [
        ThreadMessage(role="user", content="giá bao nhiêu?"),
        ThreadMessage(
            role="assistant",
            content="",
            tool_calls=[{"id": "t1", "function": {"name": "kb_search", "arguments": "{}"}}],
        ),
        ThreadMessage(role="tool", content="kq", tool_call_id="t1", name="kb_search"),
        ThreadMessage(role="assistant", content="tầm 5 tỷ ạ"),
    ]


async def test_persist_turn_messages_shapes_rows(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _ins(db, **kw):
        seen.update(kw)

    monkeypatch.setattr(DP, "insert_conversation_messages", _ins)
    await DP.persist_turn_messages("sid-1", base_seq=6, messages=_turn_messages())

    assert seen["tenant_id"] == "noble" and seen["session_id"] == "sid-1"
    rows = seen["messages"]
    assert [r["seq"] for r in rows] == [6, 7, 8, 9]
    assert [r["role"] for r in rows] == ["user", "assistant", "tool", "assistant"]
    # meta carries the optional extensions; core rows have empty meta
    assert rows[0]["meta"] == {}
    assert rows[1]["meta"]["tool_calls"][0]["id"] == "t1"
    assert rows[2]["meta"] == {"name": "kb_search", "tool_call_id": "t1"}
    assert all(r["created_at"].tzinfo is not None for r in rows)


async def test_persist_turn_messages_skips_system(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _ins(db, **kw):
        seen.update(kw)

    monkeypatch.setattr(DP, "insert_conversation_messages", _ins)
    msgs = [ThreadMessage(role="system", content="PROMPT"), ThreadMessage(role="user", content="hi")]
    await DP.persist_turn_messages("sid-1", base_seq=0, messages=msgs)

    rows = seen["messages"]
    # seq stays aligned to the history index even when system is skipped
    assert [(r["seq"], r["role"]) for r in rows] == [(1, "user")]


async def test_persist_turn_messages_noop_without_pool(monkeypatch, _tenant):
    await _pool_none(monkeypatch)
    called = []

    async def _ins(db, **kw):
        called.append(kw)

    monkeypatch.setattr(DP, "insert_conversation_messages", _ins)
    await DP.persist_turn_messages("sid-1", base_seq=0, messages=_turn_messages())
    assert called == []


async def test_persist_turn_messages_noop_on_empty(monkeypatch, _tenant):
    pool_calls = []

    async def _p(tid):
        pool_calls.append(1)
        return None

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    await DP.persist_turn_messages("sid-1", base_seq=0, messages=[])
    assert pool_calls == []  # empty delta never even resolves the pool


async def test_persist_turn_messages_swallows_error(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _ins(db, **kw):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(DP, "insert_conversation_messages", _ins)
    # Must not raise.
    await DP.persist_turn_messages("sid-1", base_seq=0, messages=_turn_messages())


# ── orchestrator wiring ──────────────────────────────────────────────────────


class _Sink:
    async def on_token(self, t): ...
    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


@pytest.fixture
def agent():
    return load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


@pytest.fixture
def settings():
    return UnifiedSettings(USE_UNIFIED_AGENT=True, NOBLE_SUMMARY_K=99)


async def _drain():
    await asyncio.sleep(0)
    tasks = [t for t in persist._bg_tasks if not t.done()]
    if tasks:
        await asyncio.gather(*tasks)


async def test_orchestrator_fires_pg_turn_messages(agent, repo, settings, monkeypatch):
    pg = AsyncMock()
    monkeypatch.setattr(DP, "persist_turn_messages", pg)
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("chào anh!", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-PG", "xin chào", _Sink())
    await _drain()

    pg.assert_awaited_once()
    args, kwargs = pg.await_args
    assert args[0] == "sid-PG"
    assert kwargs["base_seq"] == 0
    roles = [m.role for m in kwargs["messages"]]
    assert roles == ["user", "assistant"]


async def test_orchestrator_pg_delta_only_on_second_turn(agent, repo, settings, monkeypatch):
    calls: list[tuple[int, list]] = []

    async def _capture(sid, *, base_seq, messages):
        calls.append((base_seq, messages))

    monkeypatch.setattr(DP, "persist_turn_messages", _capture)
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-PG2", "câu 1", _Sink())
    await _drain()
    await runner.handle_turn("sid-PG2", "câu 2", _Sink())
    await _drain()

    assert len(calls) == 2
    base_seq, msgs = calls[1]
    assert base_seq == 2  # after turn-1's user+assistant
    assert len(msgs) == 2
    assert msgs[0].content == "câu 2"


async def test_orchestrator_no_pg_insert_when_save_all_fails(agent, repo, settings, monkeypatch):
    pg = AsyncMock()
    monkeypatch.setattr(DP, "persist_turn_messages", pg)

    async def _boom(*a, **k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(repo, "save_all", _boom)
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("chào!", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-PG3", "xin chào", _Sink())
    await _drain()

    pg.assert_not_awaited()


# ── DDL + provisioning cover the new table ───────────────────────────────────

_SQL = Path("src/noble_agent/storage/sql/odyssey_data_plane.sql").read_text(encoding="utf-8")


def test_ddl_creates_conversation_messages():
    assert "CREATE TABLE IF NOT EXISTS tenant_data.conversation_messages" in _SQL
    assert "PRIMARY KEY (tenant_id, session_id, seq)" in _SQL


def test_ddl_rls_covers_conversation_messages():
    assert "'conversation_messages'" in _SQL  # in the RLS FOREACH array


def test_provisioning_reaps_conversation_messages():
    from noble_agent.tenant.pg_provisioning import _TABLES

    assert "conversation_messages" in _TABLES
