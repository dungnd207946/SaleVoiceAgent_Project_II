"""Follow-up suggestion chips (quick-reply) after each Luna turn — CHAT only.

See docs/superpowers/specs/2026-07-13-followup-suggestion-chips-design.md.

Covers the pure helpers (parse/prompt), the TurnRunner side-call, the facade
delegate, and the text_chat delivery (post-`done`, gated, non-empty only).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner, _last_exchange
from noble_agent.agent.suggestions import build_suggestions_prompt, parse_suggestions
from noble_agent.config import UnifiedSettings
from noble_agent.storage.models import Customer, Meta, State, ThreadMessage
from noble_agent.storage.repo import StateRepo
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


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
    base = dict(USE_UNIFIED_AGENT=True)
    base.update(kw)
    return UnifiedSettings(**base)


async def _seed(repo, sid, history):
    now = datetime.now(UTC)
    await repo.save_all(
        sid,
        Meta(session_id=sid, started_at=now, last_active=now),
        Customer(),
        State(history=history),
    )


# ── Step 1: parse_suggestions (pure) ──────────────────────────────────────────


def test_parse_valid_json():
    raw = '[{"label":"A","text":"aa"},{"label":"B","text":"bb"}]'
    items = parse_suggestions(raw)
    assert items == [{"label": "A", "text": "aa"}, {"label": "B", "text": "bb"}]


def test_parse_caps_to_three():
    raw = '[{"label":"1","text":"a"},{"label":"2","text":"b"},{"label":"3","text":"c"},{"label":"4","text":"d"}]'
    items = parse_suggestions(raw)
    assert len(items) == 3
    assert [i["label"] for i in items] == ["1", "2", "3"]


def test_parse_truncates_label_to_24():
    long_label = "X" * 30
    long_text = "Y" * 120
    raw = f'[{{"label":"{long_label}","text":"{long_text}"}}]'
    items = parse_suggestions(raw)
    assert len(items) == 1
    assert len(items[0]["label"]) <= 24
    assert items[0]["text"] == long_text  # text is NOT truncated


def test_parse_strips_json_fence():
    raw = '```json\n[{"label":"A","text":"aa"}]\n```'
    items = parse_suggestions(raw)
    assert items == [{"label": "A", "text": "aa"}]


def test_parse_extracts_array_from_prose():
    raw = 'Đây là gợi ý:\n[{"label":"A","text":"aa"}]\nHy vọng hữu ích!'
    items = parse_suggestions(raw)
    assert items == [{"label": "A", "text": "aa"}]


def test_parse_garbage_returns_empty():
    assert parse_suggestions("") == []
    assert parse_suggestions("not json at all") == []
    assert parse_suggestions('{"x":1}') == []  # non-array JSON
    assert parse_suggestions("[unclosed") == []


def test_parse_drops_item_missing_fields():
    raw = (
        '[{"label":"ok","text":"good"},'
        '{"label":"nolabel"},'
        '{"text":"notext"},'
        '{"label":"","text":"empty label"},'
        '{"label":"blank","text":"  "},'
        '{"label":42,"text":"nonstr"}]'
    )
    items = parse_suggestions(raw)
    assert items == [{"label": "ok", "text": "good"}]


# ── Step 2: build_suggestions_prompt (pure) ───────────────────────────────────


def test_prompt_contains_exchange_and_empty_instruction():
    user_text = "Dự án NCTH giá bao nhiêu?"
    assistant_text = "Dạ NCTH hiện có căn từ 3 tỷ ạ."
    prompt = build_suggestions_prompt(user_text, assistant_text, Customer())
    assert user_text in prompt
    assert assistant_text in prompt
    assert "mảng rỗng" in prompt  # empty-array instruction (farewell/escalate/booked)
    assert "JSON" in prompt
    assert "label" in prompt
    assert "text" in prompt


def test_prompt_includes_profile_when_present():
    prompt = build_suggestions_prompt(
        "hỏi gì đó",
        "trả lời gì đó",
        Customer(project_interest="NCTH", purpose="đầu tư"),
    )
    assert "NCTH" in prompt
    assert "đầu tư" in prompt


def test_prompt_omits_profile_when_absent():
    prompt = build_suggestions_prompt("u", "a", Customer())
    # No stray "None" leaking from unset profile fields.
    assert "None" not in prompt


def test_build_suggestions_prompt_uses_agent_name():
    from types import SimpleNamespace

    cust = SimpleNamespace(project_interest=None, purpose=None)
    p = build_suggestions_prompt("cho xem giá", "dạ giá từ 2 tỷ", cust, agent_name="Aria")
    assert "Aria" in p
    assert "Luna" not in p


def test_build_suggestions_prompt_default_name_luna():
    from types import SimpleNamespace

    cust = SimpleNamespace(project_interest=None, purpose=None)
    p = build_suggestions_prompt("cho xem giá", "dạ giá từ 2 tỷ", cust)
    assert "Luna" in p


# ── Step 3: _last_exchange + TurnRunner.suggest_followups ─────────────────────


def test_last_exchange_skips_tools_and_takes_last_assistant():
    history = [
        ThreadMessage(role="user", content="first q"),
        ThreadMessage(role="assistant", content="first a"),
        ThreadMessage(role="user", content="second q"),
        ThreadMessage(role="assistant", content="", tool_calls=[{"id": "1", "function": {"name": "x"}}]),
        ThreadMessage(role="tool", content="tool result", tool_call_id="1", name="x"),
        ThreadMessage(role="assistant", content="final answer"),
    ]
    assert _last_exchange(history) == ("second q", "final answer")


def test_last_exchange_no_assistant_text_after_user():
    history = [
        ThreadMessage(role="user", content="q"),
        ThreadMessage(role="assistant", content="", tool_calls=[{"id": "1", "function": {"name": "x"}}]),
    ]
    assert _last_exchange(history) == ("q", "")


def test_last_exchange_no_user():
    assert _last_exchange([ThreadMessage(role="assistant", content="hi")]) == ("", "")


async def test_suggest_followups_disabled_returns_empty_no_llm_call(agent, repo):
    await _seed(
        repo,
        "sid-off",
        [ThreadMessage(role="user", content="q"), ThreadMessage(role="assistant", content="a")],
    )
    llm = AsyncMock()
    runner = TurnRunner(
        repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings(NOBLE_SUGGESTIONS_ENABLED=False)
    )
    result = await runner.suggest_followups("sid-off")
    assert result == []
    llm.simple_completion.assert_not_awaited()


async def test_suggest_followups_no_exchange_returns_empty(agent, repo):
    # Last assistant had only tool_calls (no text) → no exchange → [].
    await _seed(
        repo,
        "sid-noex",
        [
            ThreadMessage(role="user", content="q"),
            ThreadMessage(role="assistant", content="", tool_calls=[{"id": "1", "function": {"name": "x"}}]),
        ],
    )
    llm = AsyncMock()
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())
    result = await runner.suggest_followups("sid-noex")
    assert result == []
    llm.simple_completion.assert_not_awaited()


async def test_suggest_followups_llm_error_returns_empty(agent, repo):
    await _seed(
        repo,
        "sid-err",
        [ThreadMessage(role="user", content="q"), ThreadMessage(role="assistant", content="a")],
    )
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(side_effect=RuntimeError("boom"))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())
    result = await runner.suggest_followups("sid-err")
    assert result == []  # swallowed, never raises


async def test_suggest_followups_happy_path_uses_model_map_and_primary(agent, repo):
    await _seed(
        repo,
        "sid-ok",
        [
            ThreadMessage(role="user", content="Dự án NCTH thế nào?"),
            ThreadMessage(role="assistant", content="Dạ NCTH rất tốt ạ."),
        ],
    )
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(
        return_value='[{"label":"Xem hình","text":"Cho xem hình"},{"label":"Giá","text":"Giá bao nhiêu"}]'
    )
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=_settings())
    result = await runner.suggest_followups("sid-ok")
    assert result == [
        {"label": "Xem hình", "text": "Cho xem hình"},
        {"label": "Giá", "text": "Giá bao nhiêu"},
    ]
    llm.simple_completion.assert_awaited_once()
    call = llm.simple_completion.await_args
    assert call.kwargs["model"] == runner._model_map
    assert call.kwargs["primary"] == runner._suggestions_primary
    assert call.kwargs["max_tokens"] <= 200
    assert abs(call.kwargs["temperature"] - 0.4) < 1e-9


# ── Step 4: NobleAgent.suggest_followups (facade delegate) ────────────────────


async def test_facade_delegates_to_runner():
    from noble_agent.agent.facade import NobleAgent

    runner = AsyncMock()
    runner.suggest_followups = AsyncMock(return_value=[{"label": "L", "text": "T"}])
    agent = NobleAgent(session_id="sid-fac", runner=runner)

    result = await agent.suggest_followups("sid-fac")

    assert result == [{"label": "L", "text": "T"}]
    runner.suggest_followups.assert_awaited_once_with("sid-fac")


# ── Step 5: text_chat delivery (post-`done`, gated, non-empty only) ───────────


def _fake_chat_llm(session_id, followups):
    llm = MagicMock()
    llm.session_id = session_id
    llm.stream_response = AsyncMock(return_value="reply")
    llm.suggest_followups = AsyncMock(return_value=followups)
    return llm


async def _run_chat_turn_and_drain(llm, monkeypatch, *, enabled=True):
    """Run one chat turn, controlling settings + draining the fire-and-forget task."""
    import noble_agent.storage.persist as persist_mod
    from noble_agent import config as config_mod
    from noble_agent.server import text_chat as tc

    monkeypatch.setattr(config_mod, "get_settings", lambda: _settings(NOBLE_SUGGESTIONS_ENABLED=enabled))

    captured: list = []
    real_fire = persist_mod.fire_and_forget

    def _capturing_fire(coro):
        task = real_fire(coro)
        if task is not None:
            captured.append(task)
        return task

    monkeypatch.setattr(persist_mod, "fire_and_forget", _capturing_fire)

    events: list[dict] = []

    async def send(ev: dict) -> None:
        events.append(ev)

    await tc.run_text_turn(llm, send, "ping")
    if captured:
        import asyncio

        await asyncio.gather(*captured, return_exceptions=True)
    return events


async def test_text_chat_emits_suggestions_after_done(monkeypatch):
    llm = _fake_chat_llm("sid-a", [{"label": "L1", "text": "T1"}, {"label": "L2", "text": "T2"}])
    events = await _run_chat_turn_and_drain(llm, monkeypatch, enabled=True)

    types = [e["type"] for e in events]
    assert "done" in types
    assert "suggestions" in types
    assert types.index("suggestions") > types.index("done")  # AFTER done
    sugg = next(e for e in events if e["type"] == "suggestions")
    assert sugg["items"] == [{"label": "L1", "text": "T1"}, {"label": "L2", "text": "T2"}]
    llm.suggest_followups.assert_awaited_once_with("sid-a")


async def test_text_chat_no_event_when_items_empty(monkeypatch):
    llm = _fake_chat_llm("sid-b", [])
    events = await _run_chat_turn_and_drain(llm, monkeypatch, enabled=True)

    types = [e["type"] for e in events]
    assert "done" in types
    assert "suggestions" not in types
    llm.suggest_followups.assert_awaited_once_with("sid-b")


async def test_text_chat_disabled_no_call(monkeypatch):
    llm = _fake_chat_llm("sid-c", [{"label": "L", "text": "T"}])
    events = await _run_chat_turn_and_drain(llm, monkeypatch, enabled=False)

    types = [e["type"] for e in events]
    assert "done" in types
    assert "suggestions" not in types
    llm.suggest_followups.assert_not_awaited()
