"""Smoke tests for noble_agent.server.text_chat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.server.text_chat import is_chat_path, run_text_turn


def test_is_chat_path_true():
    assert is_chat_path("/chat") is True
    assert is_chat_path("/chat/ws") is True
    assert is_chat_path("/chat/ws?session=abc") is True


def test_is_chat_path_false():
    assert is_chat_path("/ws/voice") is False
    assert is_chat_path("/health") is False
    assert is_chat_path("/") is False


@pytest.mark.asyncio
async def test_run_text_turn_emits_done():
    """run_text_turn should emit a 'done' event even with an async-mock LLM."""
    events: list[dict] = []

    async def fake_send(ev: dict) -> None:
        events.append(ev)

    # NobleAgent.stream_response accepts positional args; AsyncMock is fine.
    fake_llm = MagicMock()
    fake_llm.stream_response = AsyncMock(return_value="hello")

    await run_text_turn(fake_llm, fake_send, "ping")

    types = [e["type"] for e in events]
    assert "done" in types, f"Expected 'done' event, got: {types}"
    assert "user_text" in types


@pytest.mark.asyncio
async def test_run_text_turn_noop_on_empty():
    """run_text_turn should be a no-op on empty / whitespace text."""
    calls: list[dict] = []

    async def fake_send(ev: dict) -> None:
        calls.append(ev)

    fake_llm = MagicMock()
    fake_llm.stream_response = AsyncMock()

    await run_text_turn(fake_llm, fake_send, "   ")
    assert calls == []
    fake_llm.stream_response.assert_not_called()
