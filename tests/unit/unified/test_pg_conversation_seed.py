"""Realtime seed of the flat call record (tenant_data.conversations).

The `conversations` row used to be written ONCE, at session end (voice:
`base_session.stop`, chat: `/chat` WS close). A chat tab left open therefore had
no row until the user refreshed the page. The orchestrator now upserts a PARTIAL
row every turn — summary/ended_at left NULL — so the row exists from the first
turn on both transports; the call-end write still fills summary/ended_at through
the COALESCE merge in `record_conversation`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.config import UnifiedSettings
from noble_agent.storage import persist
from noble_agent.storage import pg_data_plane as DP
from noble_agent.storage.models import Customer, Meta, State
from noble_agent.storage.repo import StateRepo
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR

# ── wrapper: seed_conversation ───────────────────────────────────────────────


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


async def test_seed_conversation_shapes_partial_row(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 7

    monkeypatch.setattr(DP, "record_conversation", _rec)
    started = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
    await DP.seed_conversation(
        "sid-1",
        phone="0901234567",
        customer_name="Anh Dũng",
        project="NCLB",
        source="chat",
        started_at=started,
        running_version=3,
    )

    assert seen["tenant_id"] == "noble" and seen["session_id"] == "sid-1"
    assert seen["phone"] == "0901234567"
    assert seen["customer_name"] == "Anh Dũng"
    assert seen["project"] == "NCLB"
    assert seen["source"] == "chat"
    assert seen["started_at"] == started
    assert seen["running_version"] == 3
    # The seed must NEVER carry call-end fields: `summary`/`ended_at` are written
    # by persist_conversation at close, and COALESCE would keep a stale value if
    # the seed pushed one.
    assert seen.get("summary") is None
    assert seen.get("ended_at") is None
    assert seen.get("transferred_to_sales", False) is False


async def test_seed_conversation_writes_without_phone(monkeypatch, _tenant):
    """A phoneless session (chat tester) must still get a row — the whole point
    is that the conversation is visible while it is happening."""
    await _pool_ok(monkeypatch)
    calls = []

    async def _rec(db, **kw):
        calls.append(kw)
        return 1

    monkeypatch.setattr(DP, "record_conversation", _rec)
    await DP.seed_conversation("sid-2", source="chat")
    assert len(calls) == 1 and calls[0]["phone"] is None


async def test_seed_conversation_stamps_agent_key_id_from_context(monkeypatch, _tenant):
    """Contextvar per-connection (gateway auth) chảy qua fire_and_forget vào seed —
    mọi lượt upsert đều mang định danh API key đã mở conversation."""
    from noble_agent.tenant.current import reset_current_agent_key_id, set_current_agent_key_id

    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 1

    monkeypatch.setattr(DP, "record_conversation", _rec)
    tok = set_current_agent_key_id("20")
    try:
        await DP.seed_conversation("sid-AK", source="chat")
    finally:
        reset_current_agent_key_id(tok)
    assert seen["agent_key_id"] == 20


async def test_seed_conversation_agent_key_id_none_without_context(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)
    seen: dict = {}

    async def _rec(db, **kw):
        seen.update(kw)
        return 1

    monkeypatch.setattr(DP, "record_conversation", _rec)
    await DP.seed_conversation("sid-AK2", source="chat")
    assert seen["agent_key_id"] is None


async def test_seed_conversation_noop_without_session_id(monkeypatch, _tenant):
    pool_calls = []

    async def _p(tid):
        pool_calls.append(1)
        return None

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    await DP.seed_conversation("", source="chat")
    assert pool_calls == []


async def test_seed_conversation_noop_without_pool(monkeypatch, _tenant):
    async def _p(tid):
        return None

    monkeypatch.setattr(DP, "_pool_or_none", _p)
    called = []

    async def _rec(db, **kw):
        called.append(kw)

    monkeypatch.setattr(DP, "record_conversation", _rec)
    await DP.seed_conversation("sid-3", source="voice")
    assert called == []


async def test_seed_conversation_swallows_error(monkeypatch, _tenant):
    await _pool_ok(monkeypatch)

    async def _rec(db, **kw):
        raise RuntimeError("pg boom")

    monkeypatch.setattr(DP, "record_conversation", _rec)
    await DP.seed_conversation("sid-4", source="voice")  # must not raise


# ── orchestrator wiring (shared by chat + voice) ─────────────────────────────


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


@pytest.fixture
def seed(monkeypatch):
    monkeypatch.setattr(DP, "persist_turn_messages", AsyncMock())
    mock = AsyncMock()
    monkeypatch.setattr(DP, "seed_conversation", mock)
    return mock


def _llm():
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("chào anh!", []))
    return llm


async def test_orchestrator_seeds_conversation_on_first_turn(agent, repo, settings, seed):
    runner = TurnRunner(
        repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings, channel="chat", version=4
    )

    await runner.handle_turn("sid-SEED", "xin chào", _Sink())
    await _drain()

    seed.assert_awaited_once()
    args, kwargs = seed.await_args
    assert args[0] == "sid-SEED"
    assert kwargs["source"] == "chat"
    assert kwargs["running_version"] == 4
    assert kwargs["started_at"] is not None


async def test_orchestrator_seed_carries_customer_fields(agent, repo, settings, seed):
    now = datetime.now(UTC)
    await repo.save_all(
        "sid-SEED2",
        Meta(session_id="sid-SEED2", started_at=now, last_active=now),
        Customer(full_name="Chị Hạnh", phone="0987654321", project_interest="SLC"),
        State(),
    )
    runner = TurnRunner(
        repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings, channel="voice", version=0
    )

    await runner.handle_turn("sid-SEED2", "dự án này giá sao?", _Sink())
    await _drain()

    _, kwargs = seed.await_args
    assert kwargs["phone"] == "0987654321"
    assert kwargs["customer_name"] == "Chị Hạnh"
    assert kwargs["project"] == "SLC"
    assert kwargs["source"] == "voice"
    # version 0 = legacy/unversioned → NULL, so the call-end write can fill it
    assert kwargs["running_version"] is None


async def test_orchestrator_seeds_every_turn(agent, repo, settings, seed):
    """Re-upsert per turn so name/phone/project collected mid-conversation land
    on the row without waiting for the call to end (merge-upsert makes it safe)."""
    runner = TurnRunner(repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings, channel="chat")

    await runner.handle_turn("sid-SEED3", "câu 1", _Sink())
    await _drain()
    await runner.handle_turn("sid-SEED3", "câu 2", _Sink())
    await _drain()

    assert seed.await_count == 2


async def test_orchestrator_no_seed_when_save_all_fails(agent, repo, settings, seed, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(repo, "save_all", _boom)
    runner = TurnRunner(repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings, channel="chat")

    await runner.handle_turn("sid-SEED4", "xin chào", _Sink())
    await _drain()

    seed.assert_not_awaited()


async def test_orchestrator_seed_source_none_without_channel(agent, repo, settings, seed):
    """Direct TurnRunner construction (tests, scripts) has no channel — the row
    is still seeded, just with source NULL."""
    runner = TurnRunner(repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings)

    await runner.handle_turn("sid-SEED5", "xin chào", _Sink())
    await _drain()

    _, kwargs = seed.await_args
    assert kwargs["source"] is None
