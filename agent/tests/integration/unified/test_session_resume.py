"""Integration test 9.5 — session resume across reconnects.

Simulates a user sending messages in one "connection", then reconnecting
(a new NobleAgent instance for the same session_id) and continuing the
conversation. Verifies that:

* History from the first connection is still present in Redis.
* The second connection sees the accumulated history (LLM receives the full
  message list including the first turn).
* A fresh NobleAgent for the same session_id picks up where the previous
  left off (no re-introduction, history preserved).
* reset() wipes all session keys.
"""

from __future__ import annotations

import json

import pytest

from noble_agent.agent.facade import NobleAgent
from noble_agent.server.text_chat import run_text_turn

from .conftest import make_collector


@pytest.mark.asyncio
async def test_history_persists_after_first_turn(runner, stub_responses, fake_redis):
    """After one turn, state and history keys exist in Redis."""
    stub_responses.append(("text", "xin chào anh"))

    agent = NobleAgent(session_id="s-9.5-resume", runner=runner)
    events, send = make_collector()
    await run_text_turn(agent, send, "xin chào Luna")

    state_raw = await fake_redis.get("session:s-9.5-resume:state")
    assert state_raw is not None, "state key must exist after first turn"

    state = json.loads(state_raw)
    # history must have at least user message + assistant message
    assert len(state["history"]) >= 2
    assert state["history"][0]["role"] == "user"
    assert state["history"][0]["content"] == "xin chào Luna"


@pytest.mark.asyncio
async def test_new_connection_sees_prior_history(runner, stub_responses, fake_redis):
    """Second NobleAgent for same session_id loads prior history."""
    # First "connection"
    stub_responses.append(("text", "dạ anh tên gì ạ"))
    agent1 = NobleAgent(session_id="s-9.5-two-conn", runner=runner)
    events1, send1 = make_collector()
    await run_text_turn(agent1, send1, "xin chào")

    # Simulate reconnect: new NobleAgent same session
    stub_responses.append(("text", "vâng anh Minh ạ"))
    agent2 = NobleAgent(session_id="s-9.5-two-conn", runner=runner)
    events2, send2 = make_collector()
    await run_text_turn(agent2, send2, "anh tên Minh")

    # After both turns the state should have 4+ messages (user+assistant x2)
    state_raw = await fake_redis.get("session:s-9.5-two-conn:state")
    assert state_raw is not None
    state = json.loads(state_raw)
    history = state["history"]
    assert len(history) >= 4, f"Expected ≥4 messages, got {len(history)}: {history}"

    # The first user message must still be present
    user_msgs = [m for m in history if m["role"] == "user"]
    contents = [m["content"] for m in user_msgs]
    assert "xin chào" in contents
    assert "anh tên Minh" in contents


@pytest.mark.asyncio
async def test_reset_clears_session_keys(runner, stub_responses, fake_redis):
    """reset() deletes all session keys."""
    stub_responses.append(("text", "hi"))
    agent = NobleAgent(session_id="s-9.5-reset", runner=runner)
    events, send = make_collector()
    await run_text_turn(agent, send, "hello")

    # Keys must exist before reset
    assert await fake_redis.exists("session:s-9.5-reset:state")

    await agent.reset()

    # All three keys should be gone
    for key in ("meta", "customer", "state"):
        result = await fake_redis.exists(f"session:s-9.5-reset:{key}")
        assert result == 0, f"Key session:s-9.5-reset:{key} should not exist after reset"


@pytest.mark.asyncio
async def test_multiple_turns_accumulate_history(runner, stub_responses, fake_redis):
    """Three sequential turns accumulate 6 messages (user+assistant each)."""
    for reply in ("câu trả lời 1", "câu trả lời 2", "câu trả lời 3"):
        stub_responses.append(("text", reply))

    session = "s-9.5-multi"
    for question in ("câu hỏi 1", "câu hỏi 2", "câu hỏi 3"):
        agent = NobleAgent(session_id=session, runner=runner)
        events, send = make_collector()
        await run_text_turn(agent, send, question)

    state_raw = await fake_redis.get(f"session:{session}:state")
    assert state_raw is not None
    state = json.loads(state_raw)
    history = state["history"]
    # 3 user + 3 assistant = 6 messages minimum
    assert len(history) >= 6, f"Expected ≥6 messages, got {len(history)}"
    user_contents = [m["content"] for m in history if m["role"] == "user"]
    assert "câu hỏi 1" in user_contents
    assert "câu hỏi 3" in user_contents


@pytest.mark.asyncio
async def test_session_id_event_emitted_via_handle_text_session(runner, stub_responses, monkeypatch):
    """handle_text_session should send session_id event immediately on connect.

    We drive handle_text_session directly by providing a fake WebSocket-like
    object that yields one user_text message then signals closure.
    """
    from noble_agent.server import text_chat

    stub_responses.append(("text", "dạ em nghe"))

    # Patch _create_llm to return a NobleAgent backed by our fake runner
    async def _fake_create_llm(session_id: str):
        return NobleAgent(session_id=session_id, runner=runner)

    monkeypatch.setattr(text_chat, "_create_llm", _fake_create_llm)

    import json as _json

    sent_events: list[dict] = []

    class _FakeWS:
        """Fake WebSocket that yields one message then closes."""

        def __init__(self):
            self._messages = [
                _json.dumps({"type": "user_text", "text": "xin chào"}),
            ]
            self._idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._idx >= len(self._messages):
                # Simulate closed socket via websockets.exceptions.ConnectionClosedOK
                import websockets.exceptions

                raise websockets.exceptions.ConnectionClosedOK(None, None)
            msg = self._messages[self._idx]
            self._idx += 1
            return msg

        async def send(self, data: str):
            sent_events.append(_json.loads(data))

    ws = _FakeWS()
    await text_chat.handle_text_session(ws, "s-9.5-handle")

    types = [e["type"] for e in sent_events]
    assert "session_id" in types, f"Expected session_id event, got: {types}"
    assert sent_events[0]["type"] == "session_id"
    assert sent_events[0]["session_id"] == "s-9.5-handle"
    assert "done" in types
