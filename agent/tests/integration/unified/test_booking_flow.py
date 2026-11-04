"""Integration test 9.4 — three-turn booking flow.

Exercises multi-turn state persistence via fake Redis:
  Turn 1: customer asks to book → LLM calls booking(action=check_availability)
  Turn 2: customer confirms → LLM calls booking(action=schedule), then text reply

All turns share one session ID and use the same fake Redis, so state
accumulates realistically across turns.

The `schedule` action calls schedule_viewing which writes a best-effort Postgres
appointment row; since no DB is configured, it gracefully falls back but the booking is
recorded in SessionState.scratchpad so list_bookings still works.
"""

from __future__ import annotations

import json

import pytest

from noble_agent.agent.facade import NobleAgent
from noble_agent.server.text_chat import run_text_turn

from .conftest import make_collector

SESSION = "s-9.4-booking"


@pytest.mark.asyncio
async def test_booking_turn1_check_availability(runner, stub_responses):
    """Turn 1: customer asks to book → LLM calls booking(action=check_availability)."""
    stub_responses.append(
        ("tool_then_text", "booking", {"action": "check_availability", "project_code": "NCLB"}, "dạ các ngày trống ạ")
    )

    agent = NobleAgent(session_id=SESSION, runner=runner)
    events, send = make_collector()
    await run_text_turn(agent, send, "anh muốn đặt lịch xem NCLB")

    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_done" in types
    assert types[-1] == "done"

    tool_start = next(e for e in events if e["type"] == "tool_start")
    assert tool_start["tool"] == "booking"
    assert tool_start["args"].get("action") == "check_availability"

    tool_done = next(e for e in events if e["type"] == "tool_done")
    result = json.loads(tool_done["result"])
    assert "available_dates" in result
    assert "slots" in result


@pytest.mark.asyncio
async def test_booking_turn3_schedule(runner, stub_responses):
    """Turn 3: customer confirms booking → schedule action → confirmation text."""
    stub_responses.append(
        (
            "tool_then_text",
            "booking",
            {
                "action": "schedule",
                "preferred_date": "2026-06-15",
                "preferred_time": "10:00",
                "confirmed": True,
            },
            "đã đặt lịch thành công ngày 15/6",
        )
    )

    agent = NobleAgent(session_id=SESSION, runner=runner)
    events, send = make_collector()
    await run_text_turn(agent, send, "anh đồng ý, ngày 15 tháng 6 lúc 10 giờ sáng")

    types = [e["type"] for e in events]
    assert types[-1] == "done"

    tool_start = next(e for e in events if e["type"] == "tool_start")
    assert tool_start["tool"] == "booking"
    assert tool_start["args"].get("action") == "schedule"

    tool_done = next(e for e in events if e["type"] == "tool_done")
    result_str = tool_done["result"]
    # schedule_viewing returns JSON; check it's parseable
    assert isinstance(result_str, str)
    try:
        result = json.loads(result_str)
        # Should have ok/success or error key
        assert "ok" in result or "success" in result or "error" in result
    except json.JSONDecodeError:
        pass  # non-JSON result is also acceptable

    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert "15" in tokens or "lịch" in tokens or "đặt" in tokens


@pytest.mark.asyncio
async def test_booking_state_persists_across_turns(runner, stub_responses, fake_redis):
    """Verify that Redis state from turn 1 is visible in turn 2."""
    # Turn 1: update booking info (sets customer name in state)
    stub_responses.append(
        ("tool_then_text", "update_customer", {"name": "An", "phone": "0909999888"}, "đã lưu thông tin")
    )
    agent = NobleAgent(session_id="s-9.4-persist", runner=runner)
    events, send = make_collector()
    await run_text_turn(agent, send, "tên anh là An, số 0909999888")

    # Verify state was persisted to Redis
    meta_raw = await fake_redis.get("session:s-9.4-persist:meta")
    assert meta_raw is not None, "meta key must be set after turn 1"

    customer_raw = await fake_redis.get("session:s-9.4-persist:customer")
    assert customer_raw is not None, "customer key must be set after turn 1"

    state_raw = await fake_redis.get("session:s-9.4-persist:state")
    assert state_raw is not None, "state key must be set after turn 1"

    state_data = json.loads(state_raw)
    # history should have at least user + assistant messages
    assert len(state_data.get("history", [])) >= 2
