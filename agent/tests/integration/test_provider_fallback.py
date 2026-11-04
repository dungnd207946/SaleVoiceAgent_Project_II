"""Phase 5.4 — LLM provider fallback integration.

Exercises `StreamingClient`'s ordered provider fallback (in
`agent/llm/client.py::stream_completion`): when the primary provider's
client raises and the secondary succeeds, the fallback must be invoked
and the secondary's content returned; when every provider fails the
client must raise. Closes CONCERNS 7.4 + 7.8 gap flagged in the plan.

Rewritten from the removed `StreamingLLM._create_stream_with_retry` API to
the current `StreamingClient` — see `tests/unit/unified/test_llm_client.py`
for how providers/clients are constructed and mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.agent.llm.client import StreamingClient


def _make_stream_provider(text_pieces: list[str]) -> tuple[MagicMock, AsyncMock]:
    """Provider whose create() returns an async generator of OpenAI-shaped
    streaming chunks carrying `text_pieces` as delta.content, then a final
    stop chunk. Mirrors the reference helper in test_llm_client.py."""

    def _chunk(piece: str) -> MagicMock:
        return MagicMock(choices=[MagicMock(delta=MagicMock(content=piece, tool_calls=None))])

    async def gen():
        for p in text_pieces:
            yield _chunk(p)
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=None), finish_reason="stop")])

    create = AsyncMock(return_value=gen())
    provider = MagicMock()
    provider.chat.completions.create = create
    return provider, create


def _failing_provider(exc: Exception) -> tuple[SimpleNamespace, AsyncMock]:
    """Provider whose create() always raises `exc`."""
    create = AsyncMock(side_effect=exc)
    provider = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return provider, create


async def _noop_token(_t: str) -> None:
    return None


@pytest.mark.asyncio
async def test_fallback_to_secondary_when_primary_raises() -> None:
    """qwen primary fails → gemini secondary succeeds → its content is
    returned. The trailing openai provider must NOT be invoked."""
    _qwen, c_qwen = _failing_provider(RuntimeError("qwen down"))
    p_gemini, c_gemini = _make_stream_provider(["hi from gemini"])
    _openai, c_openai = _failing_provider(RuntimeError("should not try"))

    client = StreamingClient(
        providers=[
            ("qwen", _qwen),
            ("gemini", p_gemini),
            ("openai", _openai),
        ]
    )

    content, _tool_calls = await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=_noop_token,
    )

    assert content == "hi from gemini"
    # Fallback actually happened: the primary was attempted...
    c_qwen.assert_awaited_once()
    # ...the secondary served the response...
    c_gemini.assert_awaited_once()
    # ...and the last provider was never reached.
    c_openai.assert_not_awaited()


@pytest.mark.asyncio
async def test_raises_runtime_error_when_all_providers_fail() -> None:
    """Every provider's client raises → the client must raise, chaining the
    last provider's error as the cause."""
    _qwen, _ = _failing_provider(RuntimeError("a"))
    _gemini, _ = _failing_provider(RuntimeError("b"))
    last_err = RuntimeError("c")
    _openai, _ = _failing_provider(last_err)

    client = StreamingClient(
        providers=[
            ("qwen", _qwen),
            ("gemini", _gemini),
            ("openai", _openai),
        ]
    )

    with pytest.raises(RuntimeError, match="all LLM providers failed") as ei:
        await client.stream_completion(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            model="m",
            temperature=0.5,
            max_tokens=50,
            on_token=_noop_token,
        )

    assert ei.value.__cause__ is last_err
