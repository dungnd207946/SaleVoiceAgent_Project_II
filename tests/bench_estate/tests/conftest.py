"""Shared pytest fixtures for bench_estate tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_streaming_llm():
    """Stand-in for noble_agent.agent.llm.streaming.StreamingLLM.

    The real StreamingLLM exposes:
    - _history: list[dict[str, str]]  (system + user/assistant messages)
    - _current_agent: str
    - refresh_system_prompt() -> None  (async)
    - stream_response(user_input) -> str  (async, returns full assistant reply)
    """
    llm = MagicMock()
    llm._history = [{"role": "system", "content": "You are Noble agent."}]
    llm._current_agent = "router"
    llm.refresh_system_prompt = AsyncMock(return_value=None)
    llm.stream_response = AsyncMock(return_value="Dạ anh, là 5 năm ạ")
    return llm
