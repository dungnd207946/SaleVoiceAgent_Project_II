"""Interrupt handling across the two current seams.

The legacy `StreamingLLM.stream_response(..., interrupt_check=)` object (which
also executed tools inline) was removed in the unified single-agent refactor.
Interrupt handling is now split across two layers:

  * `agent.llm.client.StreamingClient.stream_completion` — polls
    `interrupt_check` between SSE chunks and stops token streaming early,
    returning whatever partial content/tool-calls it had accumulated. It does
    NOT execute tools.
  * `agent.runner.run_turn` — owns the tool loop. After the LLM returns
    tool_calls it re-checks `interrupt_check`; if set, it injects placeholder
    `{"interrupted": true}` tool results (so the history invariant holds) and
    returns WITHOUT dispatching any tool.

These tests exercise both seams against current behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.llm.client import StreamingClient
from noble_agent.agent.runner import run_turn
from noble_agent.storage.models import Customer, State, ThreadMessage
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


class FakeChunk:
    """Simulates one SSE chunk from an OpenAI-shaped stream."""

    def __init__(self, content: str | None = None, finish_reason: str | None = None):
        delta = MagicMock()
        delta.content = content
        delta.tool_calls = None
        choice = MagicMock()
        choice.delta = delta
        choice.finish_reason = finish_reason
        self.choices = [choice]


class FakeStream:
    """Async iterator that yields FakeChunks."""

    def __init__(self, chunks: list[FakeChunk]):
        self._chunks = chunks
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


def _make_client(stream: FakeStream) -> StreamingClient:
    """Build a StreamingClient with one provider whose stream returns `stream`."""
    provider = MagicMock()
    provider.base_url = "http://test.local"  # not api.openai.com → OpenAI-compat shaping
    provider.chat.completions.create = AsyncMock(return_value=stream)
    return StreamingClient(providers=[("test", provider)])


async def test_stream_completion_stops_on_interrupt():
    """interrupt_check True mid-stream → stream_completion stops early.

    `interrupt_check` is polled at the TOP of each chunk before the chunk's
    content is emitted, so the chunk whose check returns True is not emitted.
    With `count > 5` the 6th poll (top of chunk index 5) breaks after 5 tokens.
    """
    chunks = [FakeChunk(content=f"word{i} ") for i in range(20)]
    chunks.append(FakeChunk(finish_reason="stop"))

    interrupt_after_5 = {"count": 0}

    def interrupt_check() -> bool:
        interrupt_after_5["count"] += 1
        return interrupt_after_5["count"] > 5

    tokens_received: list[str] = []

    async def on_token(t: str) -> None:
        tokens_received.append(t)

    client = _make_client(FakeStream(chunks))

    content, tool_calls = await client.stream_completion(
        messages=[{"role": "system", "content": "test"}, {"role": "user", "content": "hello"}],
        tools=[],
        model="test",
        temperature=0.3,
        max_tokens=256,
        on_token=on_token,
        interrupt_check=interrupt_check,
    )

    # Stopped around token 5, not all 20.
    assert len(tokens_received) <= 6
    assert len(tokens_received) < 20
    # Partial content is returned (whatever was emitted before the break).
    assert content == "".join(tokens_received)


class _Sink:
    def __init__(self):
        self.tokens: list[str] = []

    async def on_token(self, t):
        self.tokens.append(t)

    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


async def test_tool_calls_skipped_on_interrupt():
    """When interrupted after the LLM returns tool_calls, run_turn injects
    placeholder tool results and returns WITHOUT dispatching any tool."""
    agent = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    state = State(history=[ThreadMessage(role="user", content="book a viewing")])
    customer = Customer()

    tc = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_project_overview", "arguments": '{"project":"NCLB"}'},
    }

    # LLM returns one tool call on the first (only) completion.
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("", [tc]))

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="ok")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    # Not interrupted before the LLM call / after tool_calls arrive? The runner
    # polls interrupt_check (a) before the LLM call and (b) after tool_calls
    # return. We want it to pass (a) and trip (b): first poll False, then True.
    poll = {"n": 0}

    def interrupt_check() -> bool:
        poll["n"] += 1
        return poll["n"] > 1

    await run_turn(
        agent=agent,
        state=state,
        customer=customer,
        llm=llm,
        dispatcher=dispatcher,
        callbacks=_Sink(),
        interrupt_check=interrupt_check,
    )

    # Tool was NEVER dispatched (interrupted before dispatch).
    dispatcher.dispatch.assert_not_awaited()
    # A placeholder interrupted tool result was injected so the history
    # invariant (every tool_call has a sibling tool message) holds.
    tool_msgs = [m for m in state.history if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "call_1"
    assert '"interrupted": true' in tool_msgs[0].content
