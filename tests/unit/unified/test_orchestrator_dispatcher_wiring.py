"""TurnRunner phải truyền bộ phận tiếp nhận của tenant xuống ToolDispatcher —
không thì auto-escalate của mọi tenant đều rơi vào "CVTV" của noble."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent import orchestrator as orch
from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.config import UnifiedSettings
from noble_agent.storage.models import Customer, Meta, State
from noble_agent.storage.repo import StateRepo
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


class _Sink:
    async def on_token(self, t): ...
    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


@pytest.fixture
async def repo():
    r = fakeredis.aioredis.FakeRedis()
    yield StateRepo(redis_client=r, ttl_seconds=3600)
    await r.aclose()


async def test_run_live_passes_agent_handoff_department_to_dispatcher(repo, monkeypatch):
    seen: dict = {}

    class _Recording(orch.ToolDispatcher):
        def __init__(self, *a, **kw):
            seen.update(kw)
            super().__init__(*a, **kw)

    monkeypatch.setattr(orch, "ToolDispatcher", _Recording)
    monkeypatch.setattr(orch, "run_turn", AsyncMock())

    now = datetime.now(UTC)
    await repo.save_all("sid-H", Meta(session_id="sid-H", started_at=now, last_active=now), Customer(), State())
    agent = replace(load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS), handoff_department="CSKH")
    settings = UnifiedSettings(USE_UNIFIED_AGENT=True)
    runner = TurnRunner(repo=repo, agent_def=agent, llm=AsyncMock(), rag=None, settings=settings)

    await runner.handle_turn("sid-H", "xin chào", _Sink())

    assert seen.get("handoff_department") == "CSKH"
