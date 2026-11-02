from datetime import UTC, datetime
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.summary.summarizer import summarize_and_persist
from noble_agent.storage.models import State, ThreadMessage, ThreadSummary
from noble_agent.storage.repo import StateRepo


@pytest.fixture
async def repo():
    r = fakeredis.aioredis.FakeRedis()
    yield StateRepo(redis_client=r, ttl_seconds=3600)
    await r.aclose()


def _msg(i: int) -> ThreadMessage:
    return ThreadMessage(role="user", content=f"m{i}")


async def test_below_keep_tail_does_nothing(repo):
    history = [_msg(i) for i in range(3)]
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="should not be called")

    await summarize_and_persist(
        sid="s1",
        history=history,
        prior_summary=None,
        llm=llm,
        repo=repo,
        model="m",
        keep_tail=4,
    )
    llm.simple_completion.assert_not_called()
    _, _, state = await repo.load("s1")
    assert state.summary is None


async def test_returns_none_when_skipped(repo):
    history = [_msg(i) for i in range(3)]
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="x")

    result = await summarize_and_persist(
        sid="s-skip",
        history=history,
        prior_summary=None,
        llm=llm,
        repo=repo,
        model="m",
        keep_tail=4,
    )
    assert result is None


async def test_returns_new_summary(repo):
    from noble_agent.storage.models import Customer, Meta

    now = datetime.now(UTC)
    await repo.save_all(
        "s-ret",
        Meta(session_id="s-ret", started_at=now, last_active=now),
        Customer(),
        State(history=[_msg(i) for i in range(10)]),
    )
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="summary text")

    result = await summarize_and_persist(
        sid="s-ret",
        history=[_msg(i) for i in range(10)],
        prior_summary=None,
        llm=llm,
        repo=repo,
        model="m",
        keep_tail=4,
    )
    assert isinstance(result, ThreadSummary)
    assert result.text == "summary text"
    assert result.covers_turns == 6


async def test_summarizes_overflow_only(repo):
    from noble_agent.storage.models import Customer, Meta

    now = datetime.now(UTC)
    await repo.save_all(
        "s2",
        Meta(session_id="s2", started_at=now, last_active=now),
        Customer(),
        State(history=[_msg(i) for i in range(10)]),
    )

    history = [_msg(i) for i in range(10)]
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="summary text")

    await summarize_and_persist(
        sid="s2",
        history=history,
        prior_summary=None,
        llm=llm,
        repo=repo,
        model="m",
        keep_tail=4,
    )
    llm.simple_completion.assert_awaited_once()
    _, _, state = await repo.load("s2")
    assert state.summary is not None
    assert state.summary.text == "summary text"
    assert state.summary.covers_turns == 6


async def test_incremental_summary_extends_prior_coverage(repo):
    from noble_agent.storage.models import Customer, Meta

    now = datetime.now(UTC)
    prior = ThreadSummary(text="old", covers_turns=4, updated_at=now)
    history = [_msg(i) for i in range(12)]
    await repo.save_all(
        "s3",
        Meta(session_id="s3", started_at=now, last_active=now),
        Customer(),
        State(history=history, summary=prior),
    )

    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="new summary")

    await summarize_and_persist(
        sid="s3",
        history=history,
        prior_summary=prior,
        llm=llm,
        repo=repo,
        model="m",
        keep_tail=4,
    )

    _, _, state = await repo.load("s3")
    # Coverage: prior.covers_turns(4) + (12-4-4=4) = 8.
    assert state.summary.covers_turns == 8
    assert state.summary.text == "new summary"


async def test_cut_lands_on_user_turn_boundary(repo):
    """K / keep_tail are counted in user-turns. The cut MUST land on a
    role=user message so that (a) "keep last N user-turns verbatim" is the
    literal meaning of keep_tail and (b) the tail never starts with role=tool
    (which would 400 the next provider call as an orphan tool result).
    """
    from noble_agent.storage.models import Customer, Meta

    now = datetime.now(UTC)
    # 6 user-turns, keep_tail=4 → summarize the first 2 user-turns, keep the
    # last 4 verbatim. user-turn boundaries are indices 0, 3, 7, 9, 11, 13
    # in the history list. Expected cut = boundary index 7 (start of the 3rd
    # user-turn) so user-turns #3..#6 stay verbatim.
    history = [
        ThreadMessage(role="user", content="u1"),  # 0
        ThreadMessage(role="assistant", content="", tool_calls=[{"id": "a", "function": {"name": "f"}}]),  # 1
        ThreadMessage(role="tool", tool_call_id="a", name="f", content="ra"),  # 2
        ThreadMessage(role="user", content="u2"),  # 3
        ThreadMessage(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "b", "function": {"name": "f"}},
                {"id": "c", "function": {"name": "f"}},
            ],
        ),  # 4
        ThreadMessage(role="tool", tool_call_id="b", name="f", content="rb"),  # 5
        ThreadMessage(role="tool", tool_call_id="c", name="f", content="rc"),  # 6
        ThreadMessage(role="user", content="u3"),  # 7  ← cut here
        ThreadMessage(role="assistant", content="a3"),  # 8
        ThreadMessage(role="user", content="u4"),  # 9
        ThreadMessage(role="assistant", content="a4"),  # 10
        ThreadMessage(role="user", content="u5"),  # 11
        ThreadMessage(role="assistant", content="a5"),  # 12
        ThreadMessage(role="user", content="u6"),  # 13
        ThreadMessage(role="assistant", content="a6"),  # 14
    ]
    await repo.save_all(
        "s4",
        Meta(session_id="s4", started_at=now, last_active=now),
        Customer(),
        State(history=history),
    )

    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="turn-boundary summary")

    await summarize_and_persist(
        sid="s4",
        history=history,
        prior_summary=None,
        llm=llm,
        repo=repo,
        model="m",
        keep_tail=4,
    )

    _, _, state = await repo.load("s4")
    assert state.summary.covers_turns == 7
    assert history[state.summary.covers_turns].role == "user"


async def test_keep_tail_zero_does_not_index_past_end(repo):
    """Regression: with `keep_tail=0` the naive `history[total - keep_tail]`
    deref is `history[len(history)]` → IndexError. The fix bypasses the
    walk-back when keep_tail==0 because the tail is empty by definition.
    """
    from noble_agent.storage.models import Customer, Meta

    now = datetime.now(UTC)
    history = [_msg(i) for i in range(5)]
    await repo.save_all(
        "s5",
        Meta(session_id="s5", started_at=now, last_active=now),
        Customer(),
        State(history=history),
    )

    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="all summarised")

    await summarize_and_persist(
        sid="s5",
        history=history,
        prior_summary=None,
        llm=llm,
        repo=repo,
        model="m",
        keep_tail=0,
    )

    _, _, state = await repo.load("s5")
    # All 5 messages should be folded in; the verbatim tail is empty.
    assert state.summary is not None
    assert state.summary.covers_turns == 5


def test_summary_prompt_has_fixed_sections():
    """Bước 3: summary theo khung cố định (khách / đã tra / đã chốt / còn mở) thay vì
    'một đoạn duy nhất' — mã căn, tài liệu, lịch không còn rơi khi nén."""
    from noble_agent.agent.summary.summarizer import build_summary_prompt

    p = build_summary_prompt(None, [_msg(0)])
    for label in ("KHÁCH:", "ĐÃ TRA:", "ĐÃ CHỐT:", "CÒN MỞ:"):
        assert label in p
    assert "mã căn" in p.lower()
