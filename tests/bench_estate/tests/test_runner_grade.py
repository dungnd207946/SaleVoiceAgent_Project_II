"""Tests for runner.grade() dispatcher."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.bench_estate.judge import JudgeResult
from tests.bench_estate.loader import EssayCase, MCQCase, ScenarioCase, Turn
from tests.bench_estate.runner import CaseResult, grade


@pytest.mark.asyncio
async def test_grade_mcq_dispatches_to_judge_mcq():
    case = MCQCase(
        case_id="A-6",
        section="A",
        topic="t",
        question="Q?",
        choices={"A": "1", "B": "2", "C": "3", "D": "4"},
        correct="B",
        points=2.0,
        delivery_mode="roleplay",
    )
    result = CaseResult(case_id="A-6", section="A", topic="t", delivery_mode="roleplay")
    result.agent_outputs.append("Dạ 5 năm")
    fake_jr = JudgeResult(mapped="B", score=2.0, score_max=2.0, verdict="pass", rationale="ok")
    with patch("tests.bench_estate.runner.judge_mcq", AsyncMock(return_value=fake_jr)) as m:
        out = await grade(result, case, judge_model="test-model")
    m.assert_awaited_once()
    assert out.score_raw == 2.0
    assert out.verdict == "pass"
    assert out.judge_model == "test-model"


@pytest.mark.asyncio
async def test_grade_essay_builds_transcript():
    case = EssayCase(
        case_id="C-1",
        title="t",
        case_text="ctx",
        turns=(Turn("KH", "x"),),
        rubric_checkpoints=(("a",),),
        key_answers={},
    )
    result = CaseResult(case_id="C-1", section="C", topic="t", delivery_mode="scripted_multiturn")
    result.user_inputs = ["q1?", "q2?"]
    result.agent_outputs = ["a1", "a2"]
    fake_jr = JudgeResult(
        score=18.0,
        score_max=20.0,
        verdict="pass",
        rubric_breakdown={"T1": 4.0, "T2": 4.0, "T3": 4.0, "T4": 3.0, "T5": 3.0},
    )
    with patch("tests.bench_estate.runner.judge_essay", AsyncMock(return_value=fake_jr)) as m:
        await grade(result, case, judge_model="test-model")
    args, kwargs = m.call_args
    assert "USER: q1?" in kwargs["transcript_text"]
    assert "AGENT: a2" in kwargs["transcript_text"]


@pytest.mark.asyncio
async def test_grade_scenario_dispatches_to_judge_sales():
    case = ScenarioCase(
        case_id="S-1",
        title="t",
        setup="s",
        turns=(Turn("KH", "x"),),
        rubric_checkpoints=(("a",),),
    )
    result = CaseResult(case_id="S-1", section="S", topic="t", delivery_mode="scripted_multiturn")
    result.user_inputs = ["x"]
    result.agent_outputs = ["y"]
    fake_jr = JudgeResult(score=15.0, score_max=20.0, verdict="pass")
    with patch("tests.bench_estate.runner.judge_sales", AsyncMock(return_value=fake_jr)) as m:
        out = await grade(result, case, judge_model="test")
    m.assert_awaited_once()
    assert out.score_raw == 15.0
