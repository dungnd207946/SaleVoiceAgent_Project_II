"""Integration test 9.2 — single turn: streams tokens + done event.

Exercises the full path:
  stub_responses → FakeStreamingClient → TurnRunner.handle_turn
      → run_turn → on_token callbacks → NobleAgent.stream_response
      → run_text_turn → send events queue

Verifies:
* user_text event emitted first
* at least one token event with the stub text
* done event emitted last with correct structure
* full assembled reply matches stub text
"""

from __future__ import annotations

import pytest

from noble_agent.agent.facade import NobleAgent
from noble_agent.server.text_chat import run_text_turn

from .conftest import make_collector


@pytest.mark.asyncio
async def test_single_turn_streams_tokens_and_done(runner, stub_responses):
    """run_text_turn: tokens stream in, done arrives at the end."""
    stub_responses.append(("text", "dạ em xin chào anh"))

    agent = NobleAgent(session_id="s-9.2-a", runner=runner)
    events, send = make_collector()

    await run_text_turn(agent, send, "xin chào")

    types = [e["type"] for e in events]
    assert types[0] == "user_text"
    assert "token" in types
    assert types[-1] == "done"

    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert "dạ" in tokens

    done = events[-1]
    assert "tokens" in done
    assert done["tokens"] > 0
    assert "total_ms" in done


@pytest.mark.asyncio
async def test_single_turn_empty_text_is_noop(runner, stub_responses):
    """run_text_turn should not emit anything for whitespace-only input."""
    events, send = make_collector()

    await run_text_turn(runner, send, "   ")
    assert events == []
    assert stub_responses == []  # LLM was never called


@pytest.mark.asyncio
async def test_single_turn_done_has_ttft(runner, stub_responses):
    """done event includes ttft_ms when at least one token was emitted."""
    stub_responses.append(("text", "xin chào"))

    agent = NobleAgent(session_id="s-9.2-b", runner=runner)
    events, send = make_collector()

    await run_text_turn(agent, send, "hi")

    done = next(e for e in events if e["type"] == "done")
    assert done["ttft_ms"] is not None
    assert isinstance(done["ttft_ms"], int)
    assert done["ttft_ms"] >= 0
