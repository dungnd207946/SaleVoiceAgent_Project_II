"""Bước 4 review chất lượng — khách ngắt lời khi TTS còn đang phát: history phải ghi đúng
phần khách ĐÃ NGHE, không phải toàn bộ câu LLM đã sinh."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from noble_agent.agent.facade import NobleAgent
from noble_agent.agent.interrupt_trim import INTERRUPT_MARK, UNSPOKEN_MARK, trim_last_assistant
from noble_agent.storage.models import Customer, Meta, State, ThreadMessage


def _hist(*msgs):
    out = []
    for r, c in msgs:
        if r == "tool":
            out.append(ThreadMessage(role="tool", tool_call_id="c1", name="kb_search", content=c))
        else:
            out.append(ThreadMessage(role=r, content=c))
    return out


def test_trim_replaces_last_assistant_with_spoken_prefix_and_marker():
    h = _hist(("user", "giá?"), ("assistant", "Giá từ 90 triệu. Căn A rất đẹp. Anh xem nhé?"))
    out, idx = trim_last_assistant(h, "Giá từ 90 triệu.")
    assert idx == 1
    assert out[1].content == f"Giá từ 90 triệu. {INTERRUPT_MARK}"
    assert h[1].content.endswith("Anh xem nhé?")  # history gốc không bị sửa tại chỗ


def test_trim_with_nothing_spoken_marks_unspoken():
    h = _hist(("user", "giá?"), ("assistant", "Giá từ 90 triệu."))
    out, idx = trim_last_assistant(h, "")
    assert idx == 1 and out[1].content == UNSPOKEN_MARK


def test_trim_noop_when_everything_was_spoken():
    h = _hist(("user", "giá?"), ("assistant", "Giá từ 90 triệu."))
    out, idx = trim_last_assistant(h, "Giá từ 90 triệu.")
    assert idx is None and out is h


def test_trim_ignores_ack_markers_in_spoken_text():
    h = _hist(("user", "giá?"), ("assistant", "Giá từ 90 triệu. Căn A rất đẹp."))
    out, idx = trim_last_assistant(h, "[ack] Giá từ 90 triệu.")
    assert idx == 1 and out[1].content.startswith("Giá từ 90 triệu.") and "[ack]" not in out[1].content


def test_trim_noop_when_no_assistant_after_last_user():
    h = _hist(("user", "a"), ("assistant", "x"), ("user", "b"), ("tool", '{"interrupted": true}'))
    out, idx = trim_last_assistant(h, "x")
    assert idx is None


def test_trim_keeps_tool_calls_on_the_message():
    h = [
        ThreadMessage(role="user", content="giá?"),
        ThreadMessage(
            role="assistant",
            content="Để em xem. Giá từ 90 triệu.",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "kb_search", "arguments": "{}"}}],
        ),
        ThreadMessage(role="tool", tool_call_id="c1", name="kb_search", content="..."),
    ]
    out, idx = trim_last_assistant(h, "Để em xem.")
    assert idx == 1 and out[1].tool_calls == h[1].tool_calls


def _agent_with_history(history):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    repo = MagicMock()
    meta = Meta(session_id="s1", started_at=now, last_active=now)
    repo.load = AsyncMock(return_value=(meta, Customer(), State(history=history)))
    repo.save_all = AsyncMock()
    r = MagicMock()
    r._repo = repo
    return NobleAgent(session_id="s1", runner=r), repo


async def test_note_interrupted_persists_trimmed_history():
    agent, repo = _agent_with_history(_hist(("user", "giá?"), ("assistant", "Giá từ 90 triệu. Căn A rất đẹp.")))
    assert await agent.note_interrupted(spoken_text="Giá từ 90 triệu.") is True
    repo.save_all.assert_awaited_once()
    saved_state = repo.save_all.call_args.args[3]
    assert saved_state.history[-1].content == f"Giá từ 90 triệu. {INTERRUPT_MARK}"


async def test_note_interrupted_skips_save_when_nothing_to_trim():
    agent, repo = _agent_with_history(_hist(("user", "giá?"), ("assistant", "Giá từ 90 triệu.")))
    assert await agent.note_interrupted(spoken_text="Giá từ 90 triệu.") is False
    repo.save_all.assert_not_awaited()


async def test_note_interrupted_never_raises():
    agent, repo = _agent_with_history([])
    repo.load = AsyncMock(side_effect=RuntimeError("redis down"))
    assert await agent.note_interrupted(spoken_text="x") is False
