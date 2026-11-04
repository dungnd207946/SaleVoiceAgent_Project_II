"""Display-channel thinking strip in the facade `_Callbacks`.

The history channel (StreamingClient return) keeps raw thinking; the display
channel (on_token → transport) must hide it unless show_thinking is on.
"""

from __future__ import annotations

from noble_agent.agent.facade import _Callbacks
from noble_agent.agent.llm.thinking import ThinkStripper


def _make_cb(*, stripper):
    forwarded: list[str] = []
    sink: list[str] = []

    def on_token(tok: str) -> None:
        forwarded.append(tok)

    cb = _Callbacks(
        on_token=on_token,
        on_tool_start=None,
        on_tool_done=None,
        interrupt_check=None,
        sink=sink,
        stripper=stripper,
    )
    return cb, forwarded, sink


async def test_callbacks_strips_thinking_from_display_when_stripper_set():
    cb, forwarded, sink = _make_cb(stripper=ThinkStripper())

    for tok in ["Chào ", "<think>", "reasoning", "</think>", "anh"]:
        await cb.on_token(tok)
    await cb.flush()

    assert "".join(forwarded) == "Chào anh"
    assert "".join(sink) == "Chào anh"


async def test_callbacks_handles_tag_split_across_tokens():
    cb, forwarded, _sink = _make_cb(stripper=ThinkStripper())

    for tok in ["a<thi", "nk>x</thi", "nk>b"]:
        await cb.on_token(tok)
    await cb.flush()

    assert "".join(forwarded) == "ab"


async def test_callbacks_flush_emits_trailing_real_text():
    cb, forwarded, _sink = _make_cb(stripper=ThinkStripper())

    # "<thi" looks like a partial open tag but never completes → real text.
    await cb.on_token("done<thi")
    await cb.flush()

    assert "".join(forwarded) == "done<thi"


async def test_callbacks_passthrough_when_no_stripper():
    cb, forwarded, sink = _make_cb(stripper=None)

    for tok in ["a", "<think>", "b", "</think>"]:
        await cb.on_token(tok)
    await cb.flush()

    assert "".join(forwarded) == "a<think>b</think>"
    assert "".join(sink) == "a<think>b</think>"
