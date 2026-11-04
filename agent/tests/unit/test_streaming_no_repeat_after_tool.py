"""History shape after a text-emitting tool iteration (unified runner).

Historical context: the legacy multi-agent ``StreamingLLM`` injected an
"already spoken" system note (``[Ghi chú nội bộ] Câu X đã được phát...``) between
tool iterations to stop the model re-speaking pre-tool text. That guard, the
``switch_agent`` tool, and the whole ``agent.llm.streaming.StreamingLLM`` module
were removed in the unified single-agent rewrite. The current tool loop lives in
``agent/runner.py::run_turn`` and injects NO such note.

These tests lock in the CURRENT behavior: when iteration 1 emits text AND a tool
call, the runner appends exactly ``assistant(content + tool_calls)`` → ``tool``
result → ``assistant(final text)``, with NO system message spliced between the
tool-calling assistant turn and the next assistant turn. (Repeat-suppression is
now handled by the prompt/definition layer, not by history mutation.)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.runner import run_turn
from noble_agent.storage.models import Customer, State, ThreadMessage
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


@pytest.fixture
def agent():
    return load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)


class _Sink:
    def __init__(self):
        self.tokens: list[str] = []

    async def on_token(self, t):
        self.tokens.append(t)

    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


def _tc(tool_id: str, name: str, args: str) -> dict:
    return {"id": tool_id, "type": "function", "function": {"name": name, "arguments": args}}


async def _run(agent, first_content: str, tc: dict, final_content: str) -> State:
    """Iteration 1 = text + one tool call; iteration 2 = final text."""
    state = State(history=[ThreadMessage(role="user", content="Ờ, xong tìm hiểu xem đi.")])
    customer = Customer()
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(
        side_effect=[
            (first_content, [tc]),
            (final_content, []),
        ]
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value='{"success": true, "updated_fields": ["purpose"]}')
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    await run_turn(
        agent=agent,
        state=state,
        customer=customer,
        llm=llm,
        dispatcher=dispatcher,
        callbacks=_Sink(),
    )
    return state


def _between_tool_and_next_assistant(history: list[ThreadMessage]) -> list[ThreadMessage]:
    tool_idx = next(i for i, m in enumerate(history) if m.role == "assistant" and m.tool_calls)
    next_asst = next((i for i, m in enumerate(history) if i > tool_idx and m.role == "assistant"), None)
    assert next_asst is not None, "expected an iteration-2 assistant message"
    return history[tool_idx + 1 : next_asst]


async def test_update_customer_iteration_has_no_system_note_between_iterations(agent):
    """After iteration 1 emits text + ``update_customer``, the only message
    between the tool-calling assistant turn and iteration 2 is the tool result
    — NO 'already spoken' system note (that guard was removed in unified)."""
    spoken = "Dạ em ghi nhận Quý Khách mua để đầu tư ạ."
    state = await _run(
        agent,
        first_content=spoken,
        tc=_tc("call_A", "update_customer", '{"purpose":"đầu tư"}'),
        final_content="Ngân sách Quý Khách dự kiến khoảng bao nhiêu ạ?",
    )

    between = _between_tool_and_next_assistant(state.history)
    assert [m.role for m in between] == ["tool"], (
        f"expected only a tool result between the tool-calling turn and iteration 2, got {between!r}"
    )
    assert not any(m.role == "system" for m in between), "unified runner must not splice a system note mid-turn"

    # The pre-tool text is preserved verbatim on the tool-calling assistant turn.
    tool_asst = next(m for m in state.history if m.role == "assistant" and m.tool_calls)
    assert tool_asst.content == spoken


async def test_text_plus_tool_iteration_produces_expected_history_shape(agent):
    """The full turn shape is user → assistant(text+tool) → tool → assistant(text)."""
    state = await _run(
        agent,
        first_content="Dạ để em tìm hiểu thông tin cho Quý Khách ngay ạ.",
        tc=_tc("call_S", "kb_search", '{"query":"NCLB","project_filter":"NCLB"}'),
        final_content="Dự án nào Quý Khách đang quan tâm ạ?",
    )

    assert [m.role for m in state.history] == ["user", "assistant", "tool", "assistant"]
    assert state.history[1].tool_calls, "iteration-1 assistant must carry the tool call"
    assert state.history[-1].content == "Dự án nào Quý Khách đang quan tâm ạ?"
