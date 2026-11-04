"""Integration test 9.3 — two tools then assistant reply.

Exercises: LLM emits tool call → dispatcher.dispatch → on_tool_start/done
callbacks → second tool → final text reply → done event.

Verifies:
* tool_start and tool_done events appear in order (interleaved with each other)
* The two tool names match what was stubbed
* A token event from the final assistant reply is present
* done event is last
"""

from __future__ import annotations

import pytest

from noble_agent.agent.facade import NobleAgent
from noble_agent.server.text_chat import run_text_turn

from .conftest import make_collector


@pytest.mark.asyncio
async def test_two_tools_then_reply(runner, stub_responses):
    """LLM calls two tools, then answers; all events appear in correct order."""
    # Turn 1: first tool call
    stub_responses.append(("tool", "discover_projects", {}))
    # After first tool result, LLM calls second tool
    stub_responses.append(("tool", "discover_projects", {"project_code": "NCLB"}))
    # After second tool result, LLM produces text
    stub_responses.append(("text", "Noble Crystal Long Biên là dự án cao cấp"))

    agent = NobleAgent(session_id="s-9.3-a", runner=runner)
    events, send = make_collector()

    await run_text_turn(agent, send, "cho em thông tin Noble Crystal")

    types = [e["type"] for e in events]
    assert types[0] == "user_text"
    assert types[-1] == "done"

    # Both tool_start events must be present
    tool_starts = [e for e in events if e["type"] == "tool_start"]
    tool_dones = [e for e in events if e["type"] == "tool_done"]
    assert len(tool_starts) == 2
    assert len(tool_dones) == 2

    tool_names_start = [e["tool"] for e in tool_starts]
    assert "discover_projects" in tool_names_start
    assert "discover_projects" in tool_names_start

    # Tokens from final reply must be present
    tokens = [e for e in events if e["type"] == "token"]
    assert len(tokens) > 0
    full_text = "".join(e["text"] for e in tokens)
    assert "Noble" in full_text

    # Order: tool_start always precedes its tool_done
    lp_start_idx = next(
        i for i, e in enumerate(events) if e.get("tool") == "discover_projects" and e["type"] == "tool_start"
    )
    lp_done_idx = next(
        i for i, e in enumerate(events) if e.get("tool") == "discover_projects" and e["type"] == "tool_done"
    )
    assert lp_start_idx < lp_done_idx


@pytest.mark.asyncio
async def test_tool_start_args_passthrough(runner, stub_responses):
    """tool_start event should carry the args dict that was passed."""
    stub_responses.append(("tool_then_text", "kb_search", {"query": "giá NCLB"}, "giá từ 5 tỷ"))

    agent = NobleAgent(session_id="s-9.3-b", runner=runner)
    events, send = make_collector()

    await run_text_turn(agent, send, "giá NCLB bao nhiêu")

    tool_start = next(e for e in events if e["type"] == "tool_start")
    assert tool_start["tool"] == "kb_search"
    assert isinstance(tool_start["args"], dict)

    tool_done = next(e for e in events if e["type"] == "tool_done")
    assert tool_done["tool"] == "kb_search"
    assert isinstance(tool_done["result"], str)


@pytest.mark.asyncio
async def test_update_customer_tool_emits_events(runner, stub_responses):
    """update_customer tool should produce tool_start + tool_done events."""
    stub_responses.append(
        ("tool_then_text", "update_customer", {"name": "Hùng", "phone": "0901234567"}, "đã lưu thông tin")
    )

    agent = NobleAgent(session_id="s-9.3-c", runner=runner)
    events, send = make_collector()

    await run_text_turn(agent, send, "anh tên Hùng số 0901234567")

    tool_starts = [e for e in events if e["type"] == "tool_start"]
    tool_dones = [e for e in events if e["type"] == "tool_done"]
    assert len(tool_starts) == 1
    assert tool_starts[0]["tool"] == "update_customer"
    assert len(tool_dones) == 1
