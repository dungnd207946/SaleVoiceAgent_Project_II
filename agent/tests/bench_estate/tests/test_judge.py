"""Unit tests for judge.py — all 3 rubrics with mocked _call_openai."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from tests.bench_estate.judge import (
    BudgetExceeded,
    JudgeResult,
    _set_cache_path,
    judge_essay,
    judge_mcq,
    judge_sales,
    reset_cost,
    set_budget,
)
from tests.bench_estate.loader import EssayCase, MCQCase, ScenarioCase, Turn


def _mcq(correct="B"):
    return MCQCase(
        case_id="A-6",
        section="A",
        topic="CCHN",
        question="Thời hạn?",
        choices={"A": "3", "B": "5", "C": "7", "D": "10"},
        correct=correct,
        points=2.0,
        delivery_mode="roleplay",
    )


def _essay():
    return EssayCase(
        case_id="C-1",
        title="t",
        case_text="Bối cảnh",
        turns=(Turn("KH", "câu hỏi 1"),),
        rubric_checkpoints=(("hit a", "hit b"),),
        key_answers={"dot_1": "264tr"},
    )


def _scenario():
    return ScenarioCase(
        case_id="S-4",
        title="Khách chê giá",
        setup="anh Đức 35t",
        turns=(Turn("KH", "Sao giá cao"),),
        rubric_checkpoints=(("đồng cảm", "data"),),
    )


# ── P1 MCQ judge ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_judge_mcq_pass():
    fake_resp = '{"mapped":"B","score":2,"verdict":"pass","rationale":"đúng 5 năm"}'
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_mcq(case=_mcq(), agent_output="Dạ anh, 5 năm ạ")
    assert isinstance(result, JudgeResult)
    assert result.score == 2.0  # case.points * (2/2) = 2.0
    assert result.score_max == 2.0
    assert result.verdict == "pass"
    assert result.mapped == "B"


@pytest.mark.asyncio
async def test_judge_mcq_partial_credit():
    fake_resp = '{"mapped":"B","score":1,"verdict":"fail","rationale":"đáp đúng nhưng giải thích sai"}'
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_mcq(case=_mcq(), agent_output="5 năm vì luật cũ")
    assert result.score == 1.0  # case.points * (1/2) = 1.0
    assert result.verdict == "fail"


@pytest.mark.asyncio
async def test_judge_mcq_refused():
    fake_resp = '{"mapped":"refused","score":0,"verdict":"refused","rationale":"agent từ chối"}'
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_mcq(case=_mcq(), agent_output="em không phải luật sư")
    assert result.verdict == "refused"
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_judge_mcq_b_section_uses_2p5_points():
    case = MCQCase(
        case_id="B-72",
        section="B",
        topic="t",
        question="Q?",
        choices={"A": "1", "B": "2", "C": "3", "D": "4"},
        correct="A",
        points=2.5,
        delivery_mode="literal",
    )
    fake_resp = '{"mapped":"A","score":2,"verdict":"pass","rationale":"ok"}'
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_mcq(case=case, agent_output="Đáp án: A")
    assert result.score == 2.5  # 2.5 * (2/2)
    assert result.score_max == 2.5


@pytest.mark.asyncio
async def test_judge_retries_on_malformed_then_succeeds():
    bad = "not-json"
    good = '{"mapped":"B","score":2,"verdict":"pass","rationale":"ok"}'
    mock = AsyncMock(side_effect=[bad, bad, good])
    with patch("tests.bench_estate.judge._call_openai", mock):
        result = await judge_mcq(case=_mcq(), agent_output="5 năm")
    assert mock.call_count == 3  # initial + 2 retries
    assert result.verdict == "pass"


@pytest.mark.asyncio
async def test_judge_returns_judge_error_when_all_retries_fail():
    mock = AsyncMock(return_value="garbage")
    with patch("tests.bench_estate.judge._call_openai", mock):
        result = await judge_mcq(case=_mcq(), agent_output="5 năm")
    assert result.verdict == "judge_error"


# ── P2 Essay rubric ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_judge_essay_pass():
    fake_resp = json.dumps(
        {
            "scores": {"T1": 4, "T2": 3, "T3": 4, "T4": 3, "T5": 4},
            "total": 18,
            "verdict": "pass",
            "checkpoints_hit": ["hit a"],
            "checkpoints_missed": ["hit b"],
            "rationale": "good",
            "needs_human_review": False,
        }
    )
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_essay(case=_essay(), transcript_text="USER: x\nAGENT: y")
    assert result.score == 18.0
    assert result.score_max == 20.0
    assert result.verdict == "pass"
    assert result.rubric_breakdown == {"T1": 4.0, "T2": 3.0, "T3": 4.0, "T4": 3.0, "T5": 4.0}
    assert result.needs_human_review is False


@pytest.mark.asyncio
async def test_judge_essay_borderline_flags_review():
    """10 ≤ total < 14 → needs_human_review=True regardless of judge's flag."""
    fake_resp = json.dumps(
        {
            "scores": {"T1": 3, "T2": 2, "T3": 3, "T4": 2, "T5": 1},
            "total": 11,
            "verdict": "fail",
            "checkpoints_hit": [],
            "checkpoints_missed": ["a", "b"],
            "rationale": "borderline",
            "needs_human_review": False,
        }
    )
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_essay(case=_essay(), transcript_text="...")
    # judge said fail (correct since 11 < 14) and runner promotes review since 10 ≤ 11 < 14
    assert result.verdict == "fail"
    assert result.needs_human_review is True


@pytest.mark.asyncio
async def test_judge_essay_clear_fail():
    fake_resp = json.dumps(
        {
            "scores": {"T1": 1, "T2": 2, "T3": 1, "T4": 2, "T5": 1},
            "total": 7,
            "verdict": "fail",
            "checkpoints_hit": [],
            "checkpoints_missed": ["a"],
            "rationale": "missed all",
            "needs_human_review": False,
        }
    )
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_essay(case=_essay(), transcript_text="...")
    assert result.verdict == "fail"
    assert result.needs_human_review is False


# ── P3 Sales rubric ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_judge_sales_pass():
    fake_resp = json.dumps(
        {
            "scores": {"M1": 4, "M2": 3, "M3": 4, "M4": 4, "M5": 3},
            "total": 18,
            "verdict": "pass",
            "checkpoints_hit": ["đồng cảm"],
            "checkpoints_missed": [],
            "rationale": "good handling",
            "needs_human_review": False,
        }
    )
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_sales(case=_scenario(), transcript_text="...")
    assert result.score == 18.0
    assert result.verdict == "pass"
    assert "M1" in result.rubric_breakdown


@pytest.mark.asyncio
async def test_judge_sales_uses_M_keys_not_T():
    """P3 rubric returns M1..M5 (not T1..T5 like essay)."""
    fake_resp = json.dumps(
        {
            "scores": {"M1": 2, "M2": 2, "M3": 1, "M4": 1, "M5": 2},
            "total": 8,
            "verdict": "fail",
            "checkpoints_hit": [],
            "checkpoints_missed": [],
            "rationale": "bad",
            "needs_human_review": False,
        }
    )
    with patch("tests.bench_estate.judge._call_openai", AsyncMock(return_value=fake_resp)):
        result = await judge_sales(case=_scenario(), transcript_text="...")
    assert set(result.rubric_breakdown.keys()) == {"M1", "M2", "M3", "M4", "M5"}


# ── M3.4 cache tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_judge_cache_hit_skips_call(tmp_path):
    _set_cache_path(tmp_path / "cache.db")
    fake_resp = '{"mapped":"B","score":2,"verdict":"pass","rationale":"ok"}'
    mock = AsyncMock(return_value=fake_resp)
    with patch("tests.bench_estate.judge._call_openai", mock):
        r1 = await judge_mcq(case=_mcq(), agent_output="Dạ 5 năm")
        r2 = await judge_mcq(case=_mcq(), agent_output="Dạ 5 năm")
    assert mock.call_count == 1
    assert r2.cached is True
    assert r1.score == r2.score
    _set_cache_path(None)


@pytest.mark.asyncio
async def test_judge_cache_miss_on_different_output(tmp_path):
    _set_cache_path(tmp_path / "cache.db")
    fake_resp = '{"mapped":"B","score":2,"verdict":"pass","rationale":"ok"}'
    mock = AsyncMock(return_value=fake_resp)
    with patch("tests.bench_estate.judge._call_openai", mock):
        await judge_mcq(case=_mcq(), agent_output="answer A")
        await judge_mcq(case=_mcq(), agent_output="answer B")
    assert mock.call_count == 2
    _set_cache_path(None)


# ── M3.5 budget tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_exceeded_raises_inside_call_openai():
    """Verify the budget gate raises BudgetExceeded before calling the API."""
    import tests.bench_estate.judge as j

    reset_cost()
    j._COST_USD = 100.0
    set_budget(0.01)
    with pytest.raises(BudgetExceeded):
        await j._call_openai("gpt-5.4-nano-2026-03-17", "sys", "user")
    set_budget(None)
    j._COST_USD = 0.0


@pytest.mark.asyncio
async def test_budget_exceeded_propagates_through_retry_loop():
    """Regression: BudgetExceeded must NOT be swallowed by `_call_with_retry`.

    Previously the retry loop's `except Exception` swallowed the cost-cap
    exception, leading to up to JUDGE_RETRY extra paid API calls before the
    error reached the caller.
    """
    import tests.bench_estate.judge as j

    reset_cost()
    j._COST_USD = 100.0
    set_budget(0.01)
    try:
        with pytest.raises(BudgetExceeded):
            await j._call_with_retry("gpt-5.4-nano-2026-03-17", "sys", "user")
    finally:
        set_budget(None)
        j._COST_USD = 0.0
