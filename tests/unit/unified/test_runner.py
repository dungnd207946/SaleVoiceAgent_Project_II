import asyncio
import json
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.agent.runner import run_turn
from noble_agent.config import UnifiedSettings
from noble_agent.storage.models import Customer, Meta, State, ThreadMessage
from noble_agent.storage.repo import StateRepo
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


@pytest.fixture
def agent():
    return load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)


class _Sink:
    def __init__(self):
        self.tokens: list[str] = []
        self.tool_starts: list[tuple[str, dict]] = []
        self.tool_dones: list[tuple[str, str]] = []

    async def on_token(self, t):
        self.tokens.append(t)

    async def on_tool_start(self, name, args):
        self.tool_starts.append((name, args))

    async def on_tool_done(self, name, result):
        self.tool_dones.append((name, result))

    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


async def test_no_tool_calls_appends_assistant_and_returns(agent):
    state = State(history=[ThreadMessage(role="user", content="hi")])
    customer = Customer()
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("hello!", []))
    dispatcher = MagicMock()
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)
    sink = _Sink()

    await run_turn(
        agent=agent,
        state=state,
        customer=customer,
        llm=llm,
        dispatcher=dispatcher,
        callbacks=sink,
    )

    assert state.history[-1].role == "assistant"
    assert state.history[-1].content == "hello!"
    dispatcher.dispatch.assert_not_called()


async def test_tool_call_dispatched_then_loop_continues(agent):
    state = State(history=[ThreadMessage(role="user", content="cho em xin danh sách dự án")])
    customer = Customer()

    tc = {
        "id": "c1",
        "type": "function",
        "function": {"name": "discover_projects", "arguments": "{}"},
    }
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(
        side_effect=[
            ("", [tc]),
            ("Bên em có Noble Crystal Long Biên...", []),
        ]
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value='{"projects":["NCLB"]}')
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)
    sink = _Sink()

    await run_turn(
        agent=agent,
        state=state,
        customer=customer,
        llm=llm,
        dispatcher=dispatcher,
        callbacks=sink,
    )

    assert llm.stream_completion.await_count == 2
    dispatcher.dispatch.assert_awaited_once_with(tc)
    # State has: user, assistant(tc), tool, assistant(reply) = 4 messages.
    assert len(state.history) == 4
    assert state.history[-1].content.startswith("Bên em có")


async def test_no_prompt_rebuild_mid_turn(agent):
    """update_customer / booking(schedule) no longer rebuild the prompt mid-turn.
    build_system_prompt is called exactly once per turn (freeze semantics)."""
    from unittest.mock import patch

    state = State(history=[ThreadMessage(role="user", content="hỏi noble crystal")])
    customer = Customer()
    tc = {"id": "c1", "type": "function", "function": {"name": "update_customer", "arguments": '{"name":"Hùng"}'}}
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[("", [tc]), ("ok", [])])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")

    with patch("noble_agent.agent.runner.build_system_prompt", wraps=None) as spy:
        spy.return_value = "SYS"
        await run_turn(agent=agent, state=state, customer=customer, llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    assert spy.call_count == 1


async def test_run_turn_uses_frozen_customer_block(agent):
    state = State(history=[ThreadMessage(role="user", content="hi")])
    state.scratchpad["customer_block"] = "__FROZEN_BLOCK__"
    customer = Customer(name="Hùng")  # live customer differs from the frozen block
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("hello!", []))
    dispatcher = MagicMock()

    await run_turn(agent=agent, state=state, customer=customer, llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    sent_messages = llm.stream_completion.call_args.kwargs["messages"]
    assert "__FROZEN_BLOCK__" in sent_messages[0]["content"]
    assert "Hùng" not in sent_messages[0]["content"]


async def test_run_turn_uses_agent_tool_schemas(agent):
    """Tools passed to the LLM are always the boot-built agent.tool_schemas —
    there is no per-session code-enum snapshot anymore (find_project resolves
    codes; project-code params are plain free-text strings)."""
    state = State(history=[ThreadMessage(role="user", content="hi")])
    customer = Customer()
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    dispatcher = MagicMock()

    await run_turn(agent=agent, state=state, customer=customer, llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    tools = llm.stream_completion.call_args.kwargs["tools"]
    expected_names = {s["function"]["name"] for s in agent.tool_schemas}
    assert {s["function"]["name"] for s in tools} == expected_names
    booking = next(t for t in tools if t["function"]["name"] == "booking")
    assert "enum" not in booking["function"]["parameters"]["properties"]["project_code"]


async def test_empty_id_tool_calls_are_filtered(agent, caplog):
    """Provider that cuts mid-stream may leave tool_calls with empty id/name.
    The runner must drop those before appending so the next turn doesn't see
    an orphan tool_call_id="".
    """
    state = State(history=[ThreadMessage(role="user", content="hi")])
    customer = Customer()

    bad_tc = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("partial", [bad_tc]))
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    with caplog.at_level(logging.WARNING, logger="noble_agent.runner"):
        await run_turn(
            agent=agent,
            state=state,
            customer=customer,
            llm=llm,
            dispatcher=dispatcher,
            callbacks=_Sink(),
        )

    # No tool dispatch, returns after first iteration as a plain assistant msg.
    dispatcher.dispatch.assert_not_called()
    assert state.history[-1].role == "assistant"
    assert state.history[-1].tool_calls is None
    assert any("dropping" in r.message for r in caplog.records)


async def test_max_tool_iterations_breaks(agent, caplog):
    state = State(history=[ThreadMessage(role="user", content="loop")])
    customer = Customer()

    tc = {"id": "c1", "type": "function", "function": {"name": "discover_projects", "arguments": "{}"}}
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("", [tc]))
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    with caplog.at_level(logging.WARNING, logger="noble_agent.runner"):
        await run_turn(
            agent=agent,
            state=state,
            customer=customer,
            llm=llm,
            dispatcher=dispatcher,
            callbacks=_Sink(),
        )
    assert any("MAX_TOOL_ITERATIONS" in r.message for r in caplog.records)


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


@pytest.fixture
def settings():
    return UnifiedSettings(USE_UNIFIED_AGENT=True, NOBLE_SUMMARY_K=4, NOBLE_SUMMARY_KEEP_TAIL=2)


async def test_handle_turn_persists_history(agent, repo, settings):
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("hi!", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-A", "xin chào", _Sink())

    _, _, state = await repo.load("sid-A")
    assert len(state.history) >= 2
    assert state.history[0].role == "user"
    assert state.history[-1].role == "assistant"


async def test_handle_turn_schedules_summary_when_history_exceeds_K(agent, repo, settings, monkeypatch):
    now = datetime.now(UTC)
    big_state = State(history=[ThreadMessage(role="user", content=f"old{i}") for i in range(6)])
    await repo.save_all(
        "sid-B",
        Meta(session_id="sid-B", started_at=now, last_active=now),
        Customer(),
        big_state,
    )

    summarize_called = asyncio.Event()

    async def fake_summarize(**kwargs):
        summarize_called.set()

    monkeypatch.setattr(
        "noble_agent.agent.orchestrator.summarize_and_persist",
        fake_summarize,
    )

    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-B", "câu mới", _Sink())
    await asyncio.wait_for(summarize_called.wait(), timeout=1.0)


async def test_handle_turn_bootstraps_profile_once(agent, repo, settings, monkeypatch):
    now = datetime.now(UTC)
    await repo.save_all(
        "sid-C",
        Meta(session_id="sid-C", started_at=now, last_active=now, phone="0901234567"),
        Customer(phone="0901234567"),
        State(),
    )

    calls = {"n": 0}

    async def fake_bootstrap(customer):
        calls["n"] += 1
        customer.name = "Hùng"

    monkeypatch.setattr("noble_agent.agent.orchestrator.bootstrap_customer_profile", fake_bootstrap)

    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-C", "xin chào", _Sink())
    await runner.handle_turn("sid-C", "câu hai", _Sink())

    assert calls["n"] == 1  # bootstrap runs only on the first turn
    _, customer, state = await repo.load("sid-C")
    assert state.scratchpad.get("_profile_loaded") is True
    assert "Hùng" in state.scratchpad.get("customer_block", "")
    assert customer.name == "Hùng"


async def test_force_tool_first_round_sends_required_then_none(agent):
    state = State(history=[ThreadMessage(role="user", content="dự án nào đang mở bán?")])
    tc = {"id": "1", "type": "function", "function": {"name": "kb_search", "arguments": "{}"}}
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[("", [tc]), ("ok", [])])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(
        agent=agent,
        state=state,
        customer=Customer(),
        llm=llm,
        dispatcher=dispatcher,
        callbacks=_Sink(),
        force_tool_first_round=True,
    )

    calls = llm.stream_completion.await_args_list
    assert calls[0].kwargs["tool_choice"] == "required"
    assert calls[1].kwargs["tool_choice"] is None


async def test_force_tool_first_round_defaults_off(agent):
    state = State(history=[ThreadMessage(role="user", content="hi")])
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("hello!", []))
    dispatcher = MagicMock()
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(
        agent=agent,
        state=state,
        customer=Customer(),
        llm=llm,
        dispatcher=dispatcher,
        callbacks=_Sink(),
    )

    assert llm.stream_completion.await_args.kwargs["tool_choice"] is None


async def test_duplicate_tool_call_same_args_not_redispatched(agent):
    # qwen3.7-flash lặp kb_search cùng tham số 4-5 lần khi kết quả rỗng — lần
    # trùng phải nhận kết quả synthetic thay vì dispatch lại.
    state = State(history=[ThreadMessage(role="user", content="chính sách?")])
    tc1 = {"id": "a", "type": "function", "function": {"name": "kb_search", "arguments": '{"query": "csbh"}'}}
    tc2 = {"id": "b", "type": "function", "function": {"name": "kb_search", "arguments": '{"query": "csbh"}'}}
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[("", [tc1]), ("", [tc2]), ("xong", [])])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(agent=agent, state=state, customer=Customer(), llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    assert dispatcher.dispatch.await_count == 1
    dup_msg = [m for m in state.history if m.role == "tool" and m.tool_call_id == "b"][0]
    assert "repeat" in dup_msg.content


async def test_iteration_cap_forces_final_answer_without_tools(agent):
    # Chạm MAX_TOOL_ITERATIONS mà model vẫn đòi gọi tool → thêm MỘT vòng chốt
    # tool_choice="none" để khách luôn nhận được câu trả lời thay vì im lặng.
    from noble_agent.agent.runner import MAX_TOOL_ITERATIONS

    state = State(history=[ThreadMessage(role="user", content="hi")])
    calls = [
        (
            "",
            [
                {
                    "id": f"i{i}",
                    "type": "function",
                    "function": {"name": "kb_search", "arguments": f'{{"query": "q{i}"}}'},
                }
            ],
        )
        for i in range(MAX_TOOL_ITERATIONS)
    ]
    calls.append(("câu chốt cho khách", []))
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=calls)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(agent=agent, state=state, customer=Customer(), llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    assert llm.stream_completion.await_count == MAX_TOOL_ITERATIONS + 1
    assert llm.stream_completion.await_args_list[-1].kwargs["tools"] == []
    assert state.history[-1].role == "assistant"
    assert state.history[-1].content == "câu chốt cho khách"


async def test_same_tool_capped_at_two_dispatches_per_turn(agent):
    # qwen retry kb_search với query BIẾN TẤU — dup-guard exact không bắt được.
    # Cap: mỗi tool tối đa 2 lần dispatch thật/lượt, lần 3 nhận synthetic.
    state = State(history=[ThreadMessage(role="user", content="chính sách?")])
    tcs = [
        {
            "id": f"k{i}",
            "type": "function",
            "function": {"name": "kb_search", "arguments": f'{{"query": "biến tấu {i}"}}'},
        }
        for i in range(3)
    ]
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[("", [tcs[0]]), ("", [tcs[1]]), ("", [tcs[2]]), ("xong", [])])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(agent=agent, state=state, customer=Customer(), llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    assert dispatcher.dispatch.await_count == 2
    capped = [m for m in state.history if m.role == "tool" and m.tool_call_id == "k2"][0]
    assert "repeat" in capped.content


async def test_update_customer_exempt_from_tool_cap(agent):
    # Quy tắc 4 bảo gộp field, nhưng model tách 3 call vẫn không được chặn (mất field).
    state = State(history=[ThreadMessage(role="user", content="tên A, ngân sách 5 tỷ, ở Q7")])
    tcs = [
        {"id": f"u{i}", "type": "function", "function": {"name": "update_customer", "arguments": f'{{"f{i}": "v"}}'}}
        for i in range(3)
    ]
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[("", tcs), ("ok", [])])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(agent=agent, state=state, customer=Customer(), llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    assert dispatcher.dispatch.await_count == 3


async def test_escalate_capped_at_one_dispatch_per_turn(agent):
    # qwen escalate 2 lần cho một câu trả lời được — escalate cap riêng = 1.
    state = State(history=[ThreadMessage(role="user", content="5 tỷ mua gì?")])
    tcs = [
        {"id": f"e{i}", "type": "function", "function": {"name": "escalate", "arguments": f'{{"reason": "r{i}"}}'}}
        for i in range(2)
    ]
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[("", [tcs[0]]), ("", [tcs[1]]), ("xong", [])])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(agent=agent, state=state, customer=Customer(), llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    assert dispatcher.dispatch.await_count == 1


# ── Bước 3 review chất lượng: request gửi LLM = history rút gọn + khối ngữ cảnh ephemeral ──
_BIG_KB = "[Noble Crystal › Giá bán]\n" + "giá " * 400


async def test_runner_digests_old_tool_results_and_prepends_context_block(agent):
    from noble_agent.agent import session_facts

    def _tc(cid, name, args):
        return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    history = [
        ThreadMessage(role="user", content="giá Noble Crystal?"),
        ThreadMessage(role="assistant", content="", tool_calls=[_tc("c1", "kb_search", {"query": "giá"})]),
        ThreadMessage(role="tool", tool_call_id="c1", name="kb_search", content=_BIG_KB),
        ThreadMessage(role="assistant", content="Giá từ 90 triệu."),
        ThreadMessage(role="user", content="ok"),
        ThreadMessage(role="assistant", content="Anh cần gì thêm?"),
        ThreadMessage(role="user", content="căn nào 2 ngủ?"),
    ]
    state = State(history=list(history))
    customer = Customer(name="Hùng", gender="M")
    session_facts.record(
        state,
        "search_units",
        {},
        json.dumps(
            {
                "units": [
                    {"unit_code": "A-1203", "bedrooms": 2, "price_vnd": 3200000000, "project_name": "Noble Crystal"}
                ]
            }
        ),
    )
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("Có căn A-1203.", []))
    dispatcher = MagicMock()
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(agent=agent, state=state, customer=customer, llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    # runner append tiếp vào cùng list sau khi gọi → soi user message CUỐI, không phải phần tử cuối
    sent = llm.stream_completion.await_args.kwargs["messages"]
    tool_msgs = [m for m in sent if m["role"] == "tool"]
    assert tool_msgs and "giá giá giá" not in tool_msgs[0]["content"]  # lượt cũ → digest
    last_user = [m for m in sent if m["role"] == "user"][-1]
    assert last_user["content"].startswith("[Ngữ cảnh hiện tại")
    assert "anh Hùng" in last_user["content"] and "A-1203" in last_user["content"]
    assert last_user["content"].endswith("căn nào 2 ngủ?")
    # history persist không đổi
    assert state.history[2].content == _BIG_KB and state.history[6].content == "căn nào 2 ngủ?"
