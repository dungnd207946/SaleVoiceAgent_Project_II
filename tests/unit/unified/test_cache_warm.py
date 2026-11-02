"""Background prompt-cache warm after summary (orchestrator).

See docs/superpowers/specs/2026-07-03-summary-cache-warm-design.md.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.config import UnifiedSettings
from noble_agent.storage.models import Customer, Meta, State, ThreadMessage, ThreadSummary
from noble_agent.storage.repo import StateRepo
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR

SUMMARY_TEXT = "TOM_TAT_MOI_XYZ"


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


def _settings(**kw):
    base = dict(USE_UNIFIED_AGENT=True, NOBLE_SUMMARY_K=4, NOBLE_SUMMARY_KEEP_TAIL=2)
    base.update(kw)
    return UnifiedSettings(**base)


def _fake_summary():
    return ThreadSummary(text=SUMMARY_TEXT, covers_turns=3, updated_at=datetime.now(UTC))


async def _seed(repo, sid, state=None):
    now = datetime.now(UTC)
    if state is None:
        state = State(history=[ThreadMessage(role="user", content=f"old{i}") for i in range(6)])
    await repo.save_all(sid, Meta(session_id=sid, started_at=now, last_active=now), Customer(), state)


async def _drain(runner):
    """Await the summary bg task, then the warm task it spawns (2 passes)."""
    for _ in range(5):
        pending = [t for t in list(runner._bg_tasks) + list(runner._warm_tasks.values()) if not t.done()]
        if not pending:
            break
        await asyncio.gather(*pending, return_exceptions=True)


def _warm_call(llm):
    """The stream_completion call whose system message carries the new summary."""
    for c in llm.stream_completion.await_args_list:
        msgs = c.kwargs.get("messages") or []
        if msgs and msgs[0].get("role") == "system" and SUMMARY_TEXT in msgs[0].get("content", ""):
            return c
    return None


async def test_warm_fires_after_summary_with_correct_shape(agent, repo, monkeypatch):
    await _seed(repo, "sid-W")
    monkeypatch.setattr(
        "noble_agent.agent.orchestrator.summarize_and_persist",
        AsyncMock(return_value=_fake_summary()),
    )
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())

    await runner.handle_turn("sid-W", "cau moi", _Sink())
    await _drain(runner)

    call = _warm_call(llm)
    assert call is not None, "warm stream_completion not fired"
    # Same request shape as the next live turn so the provider cache prefix
    # matches — the live turn ships schemas THROUGH analytics_vocab.inject
    # (fills [VOCAB], adds the xref), so the warm call must compare against
    # the injected shape, not the raw AgentDef schemas.
    from noble_agent.agent.tools import analytics_vocab

    assert call.kwargs["tools"] == analytics_vocab.inject(agent.tool_schemas)
    assert call.kwargs["primary"] == runner._agent_primary
    assert call.kwargs["model"] == runner._model_map
    # tail after the system message = history_snapshot[covers_turns:]
    assert len(call.kwargs["messages"]) >= 2
    # small budget — warm is a prefill, not a generation
    assert call.kwargs["max_tokens"] <= 32


async def test_no_warm_when_disabled(agent, repo, monkeypatch):
    await _seed(repo, "sid-D")
    monkeypatch.setattr(
        "noble_agent.agent.orchestrator.summarize_and_persist",
        AsyncMock(return_value=_fake_summary()),
    )
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(
        repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings(NOBLE_SUMMARY_WARM_CACHE=False)
    )

    await runner.handle_turn("sid-D", "cau moi", _Sink())
    await _drain(runner)

    assert _warm_call(llm) is None
    assert runner._warm_tasks.get("sid-D") is None


async def test_no_warm_when_summary_skipped(agent, repo, monkeypatch):
    await _seed(repo, "sid-N")
    monkeypatch.setattr(
        "noble_agent.agent.orchestrator.summarize_and_persist",
        AsyncMock(return_value=None),
    )
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())

    await runner.handle_turn("sid-N", "cau moi", _Sink())
    await _drain(runner)

    assert _warm_call(llm) is None


async def test_handle_turn_cancels_prior_warm(agent, repo):
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())
    # A short history so this turn does NOT schedule a new summary/warm.
    await _seed(repo, "sid-C", state=State(history=[ThreadMessage(role="user", content="hi")]))

    async def _never():
        await asyncio.Event().wait()

    dummy = asyncio.create_task(_never())
    runner._warm_tasks["sid-C"] = dummy

    await runner.handle_turn("sid-C", "hello", _Sink())
    await asyncio.gather(dummy, return_exceptions=True)

    assert dummy.cancelled()


async def test_warm_exception_is_swallowed(agent, repo, monkeypatch):
    await _seed(repo, "sid-E")
    monkeypatch.setattr(
        "noble_agent.agent.orchestrator.summarize_and_persist",
        AsyncMock(return_value=_fake_summary()),
    )

    def _stream(**kw):
        msgs = kw.get("messages") or []
        if msgs and msgs[0].get("role") == "system" and SUMMARY_TEXT in msgs[0].get("content", ""):
            raise RuntimeError("warm boom")
        return ("ok", [])

    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=_stream)
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())

    # Must not raise despite the warm blowing up.
    await runner.handle_turn("sid-E", "cau moi", _Sink())
    await _drain(runner)

    wt = runner._warm_tasks.get("sid-E")
    assert wt is not None and wt.done()
    assert wt.exception() is None  # swallowed inside _warm, not propagated to the task


async def test_warm_request_uses_same_compacted_history_as_live_turn(agent, repo, monkeypatch):
    """Warm phải khớp prefix của lượt live: history cũng đi qua build_request_messages
    (digest kết quả tool cũ), không thì prompt cache warm vô nghĩa."""
    import json as _json

    big = "[P › Giá]\n" + "giá " * 400
    tc = {"id": "c1", "type": "function", "function": {"name": "kb_search", "arguments": _json.dumps({"query": "giá"})}}
    hist = [
        ThreadMessage(role="user", content="giá?"),
        ThreadMessage(role="assistant", content="", tool_calls=[tc]),
        ThreadMessage(role="tool", tool_call_id="c1", name="kb_search", content=big),
        ThreadMessage(role="assistant", content="90 triệu."),
    ] + [ThreadMessage(role="user", content=f"u{i}") if i % 2 == 0 else ThreadMessage(role="assistant", content=f"a{i}")
         for i in range(6)]
    await _seed(repo, "sid-C", State(history=hist))
    monkeypatch.setattr(
        "noble_agent.agent.orchestrator.summarize_and_persist",
        AsyncMock(return_value=ThreadSummary(text=SUMMARY_TEXT, covers_turns=0, updated_at=datetime.now(UTC))),
    )
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())

    await runner.handle_turn("sid-C", "cau moi", _Sink())
    await _drain(runner)

    call = _warm_call(llm)
    assert call is not None
    tool_msgs = [m for m in call.kwargs["messages"] if m["role"] == "tool"]
    assert tool_msgs and "giá giá giá" not in tool_msgs[0]["content"]
