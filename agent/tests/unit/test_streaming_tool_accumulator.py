"""Regression tests for StreamingClient's tool-call delta accumulator.

Covers the OpenAI streaming convention (stable ``tc.index``, name sent once,
arguments streamed) AND Gemini's OpenAI-compat quirk of emitting multiple tool
calls at the SAME ``tc.index`` (or ``index=None``) in separate chunks. Before
the fix, two Gemini tool calls would be concatenated into a single Frankenstein
``tool_call`` whose name was ``"update_customernoble_search"`` and whose args
was ``{"a":"1"}{"b":"2"}`` — invalid JSON.

The accumulator now lives in ``StreamingClient._stream_once`` (agent/llm/client.py);
``stream_completion`` returns ``(content, tool_calls)`` where ``tool_calls`` is the
ordered list of accumulated raw tool-call dicts. The blank-name DROP is a
separate concern that lives in ``agent/runner.py`` (see ``test_runner.py``), so
the client must return blank-name entries RAW and SEPARATE — never merged — so
the runner can drop them without the accumulator having corrupted a sibling call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from noble_agent.agent.llm.client import StreamingClient


def _tc(index: int | None, tool_id: str | None, name: str | None, args: str | None) -> MagicMock:
    tc = MagicMock()
    tc.index = index
    tc.id = tool_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = args
    return tc


def _chunk(
    tool_calls: list[MagicMock] | None = None, content: str | None = None, finish_reason: str | None = None
) -> MagicMock:
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    c = MagicMock()
    c.choices = [choice]
    return c


class _FakeStream:
    def __init__(self, chunks: list[MagicMock]) -> None:
        self._chunks = chunks
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        c = self._chunks[self._idx]
        self._idx += 1
        return c


async def _noop_token(_t: str) -> None:
    return None


async def _run(chunks: list[MagicMock], provider_name: str = "openai") -> tuple[str, list[dict] | None]:
    stream = _FakeStream(chunks)
    provider = MagicMock()
    provider.chat.completions.create = AsyncMock(return_value=stream)
    client = StreamingClient(providers=[(provider_name, provider)])
    return await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x"}}],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=_noop_token,
    )


async def test_distinct_index_tools_are_not_concatenated():
    """Two tool calls at DISTINCT present indexes must stay separate and keep
    first-seen order. If they merged, the name would become
    'update_customernoble_search' and args would be invalid JSON.

    (Present index is the stable OpenAI key: fragments sharing an index are the
    SAME call — see ``test_openai_style_streaming_args_still_accumulate``. Two
    DISTINCT tools therefore arrive at distinct indexes; Gemini's index-less
    parallel-call quirk is covered separately below.)
    """
    _content, tcs = await _run(
        [
            _chunk(tool_calls=[_tc(0, "call_A", "update_customer", '{"name":"Hùng"}')]),
            _chunk(
                tool_calls=[_tc(1, "call_B", "kb_search", '{"project_name":"Noble Crystal"}')],
                finish_reason="tool_calls",
            ),
        ]
    )

    assert tcs is not None
    assert [tc["function"]["name"] for tc in tcs] == ["update_customer", "kb_search"], (
        f"expected two distinct tool names, got {[tc['function']['name'] for tc in tcs]!r} "
        "(if names concatenate, the accumulator bug is back)"
    )
    assert tcs[0]["function"]["arguments"] == '{"name":"Hùng"}'
    assert tcs[1]["function"]["arguments"] == '{"project_name":"Noble Crystal"}'
    assert tcs[0]["id"] == "call_A"
    assert tcs[1]["id"] == "call_B"


async def test_gemini_style_none_index_tools_are_not_concatenated():
    """Real Gemini sends tc.index=None for each tool call — must not crash or
    concatenate; distinct ids keep them in separate slots."""
    _content, tcs = await _run(
        [
            _chunk(tool_calls=[_tc(None, "call_A", "update_customer", '{"name":"Hùng"}')]),
            _chunk(
                tool_calls=[_tc(None, "call_B", "kb_search", '{"project_name":"Noble Crystal"}')],
                finish_reason="tool_calls",
            ),
        ]
    )

    assert tcs is not None
    assert [tc["function"]["name"] for tc in tcs] == ["update_customer", "kb_search"]
    assert tcs[0]["function"]["arguments"] == '{"name":"Hùng"}'
    assert tcs[1]["function"]["arguments"] == '{"project_name":"Noble Crystal"}'


async def test_blank_name_tool_call_returned_raw_and_separate():
    """Small fine-tuned models occasionally emit a tool-call structure with a
    blank function name (observed: empty name + "{}" args). The accumulator must
    return it RAW and SEPARATE (its own slot, keyed by id) — it must NOT merge
    the blank entry into a sibling call. Dropping the blank entry is the runner's
    job (see test_runner.py::test_empty_id_tool_calls_are_filtered).
    """
    _content, tcs = await _run(
        [
            _chunk(tool_calls=[_tc(None, "call_X", None, "{}")]),
            _chunk(tool_calls=[_tc(None, "call_Y", "", "{}")], finish_reason="tool_calls"),
        ]
    )

    assert tcs is not None
    assert len(tcs) == 2
    # Both blank-name entries preserved raw & separate (distinct ids, empty names).
    assert tcs[0]["id"] == "call_X"
    assert tcs[0]["function"]["name"] == ""
    assert tcs[1]["id"] == "call_Y"
    assert tcs[1]["function"]["name"] == ""


async def test_blank_name_and_valid_call_in_same_turn_stay_separate():
    """A turn mixing one blank-name call and one real call must keep them in
    separate slots so the runner can drop only the blank one; the valid call's
    name and args must survive intact (not corrupted by the blank sibling)."""
    _content, tcs = await _run(
        [
            _chunk(tool_calls=[_tc(0, "call_bad", None, "{}")]),
            _chunk(
                tool_calls=[_tc(1, "call_ok", "update_customer", '{"name":"Hùng"}')],
                finish_reason="tool_calls",
            ),
        ]
    )

    assert tcs is not None
    assert len(tcs) == 2
    assert tcs[0]["id"] == "call_bad"
    assert tcs[0]["function"]["name"] == ""
    assert tcs[1]["id"] == "call_ok"
    assert tcs[1]["function"]["name"] == "update_customer"
    assert tcs[1]["function"]["arguments"] == '{"name":"Hùng"}'


async def test_openai_style_streaming_args_still_accumulate():
    """Classic OpenAI: name arrives once, arguments stream across chunks at a
    STABLE index; continuation deltas (no name/id) concatenate into the slot."""
    _content, tcs = await _run(
        [
            _chunk(tool_calls=[_tc(0, "call_A", "update_customer", '{"na')]),
            _chunk(tool_calls=[_tc(0, None, None, 'me":"Hùng"}')]),
            _chunk(
                tool_calls=[_tc(1, "call_B", "kb_search", '{"project_name":"NCLB"}')],
                finish_reason="tool_calls",
            ),
        ]
    )

    assert tcs is not None
    assert [tc["function"]["name"] for tc in tcs] == ["update_customer", "kb_search"]
    assert tcs[0]["function"]["arguments"] == '{"name":"Hùng"}'
    assert tcs[1]["function"]["arguments"] == '{"project_name":"NCLB"}'
