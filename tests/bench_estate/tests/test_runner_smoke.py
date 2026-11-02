"""Smoke tests for runner.py.

M2.2 covers only the CaseResult dataclass shape. M2.3 adds run_one() with
mockable seams. M2.5 will add a `@pytest.mark.slow` live integration test.
"""

from unittest.mock import AsyncMock, patch

import pytest

from tests.bench_estate.loader import EssayCase, MCQCase, Turn
from tests.bench_estate.runner import CaseResult, run_one


def test_case_result_defaults():
    r = CaseResult(case_id="A-6", section="A", topic="CCHN", delivery_mode="roleplay")
    assert r.user_inputs == []
    assert r.agent_outputs == []
    assert r.tool_calls == []
    assert r.score_raw == 0.0
    assert r.score_max == 0.0
    assert r.verdict == "fail"
    assert r.error is None
    assert r.rubric_breakdown is None


def test_case_result_mutable_collections():
    r = CaseResult(case_id="A-1", section="A", topic="t", delivery_mode="roleplay")
    r.user_inputs.append("hello")
    r.ttft_ms.append(312.0)
    assert r.user_inputs == ["hello"]
    assert r.ttft_ms == [312.0]


def test_case_result_separate_instances_independent():
    """Defaults must use field(default_factory=list) — not shared mutable state."""
    a = CaseResult(case_id="A-1", section="A", topic="t", delivery_mode="roleplay")
    b = CaseResult(case_id="A-2", section="A", topic="t", delivery_mode="roleplay")
    a.user_inputs.append("x")
    assert b.user_inputs == []  # not shared


@pytest.mark.asyncio
async def test_run_one_mcq_captures_io(mock_streaming_llm):
    case = MCQCase(
        case_id="A-6",
        section="A",
        topic="CCHN",
        question="Thời hạn?",
        choices={"A": "3", "B": "5", "C": "7", "D": "10"},
        correct="B",
        points=2.0,
        delivery_mode="roleplay",
        roleplay_question="Em ơi chứng chỉ mấy năm?",
    )
    with (
        patch("tests.bench_estate.runner._create_llm", AsyncMock(return_value=mock_streaming_llm)),
        patch("tests.bench_estate.runner._flush_redis", AsyncMock(return_value=None)),
    ):
        result = await run_one(case, run_id="test-run")
    assert result.case_id == "A-6"
    assert result.user_inputs == ["Em ơi chứng chỉ mấy năm?"]
    assert result.agent_outputs == ["Dạ anh, là 5 năm ạ"]
    assert len(result.ttft_ms) == 1
    assert result.ttft_ms[0] >= 0
    assert result.total_ms[0] >= 0
    assert result.error is None


@pytest.mark.asyncio
async def test_run_one_multiturn_replays_kh_turns(mock_streaming_llm):
    case = EssayCase(
        case_id="C-1",
        title="t",
        case_text="ctx",
        turns=(
            Turn("KH", "câu 1?"),
            Turn("Sale", "REFERENCE: x"),
            Turn("KH", "câu 2?"),
        ),
        rubric_checkpoints=(("a",), ("b",)),
        key_answers={},
    )
    with (
        patch("tests.bench_estate.runner._create_llm", AsyncMock(return_value=mock_streaming_llm)),
        patch("tests.bench_estate.runner._flush_redis", AsyncMock(return_value=None)),
    ):
        result = await run_one(case, run_id="test-run")
    assert result.user_inputs == ["câu 1?", "câu 2?"]
    assert len(result.agent_outputs) == 2
    assert mock_streaming_llm.stream_response.await_count == 2


@pytest.mark.asyncio
async def test_run_one_handles_stream_exception(mock_streaming_llm):
    case = MCQCase(
        case_id="A-7",
        section="A",
        topic="t",
        question="Q?",
        choices={"A": "a", "B": "b", "C": "c", "D": "d"},
        correct="A",
        points=2.0,
        delivery_mode="roleplay",
        roleplay_question="câu hỏi?",
    )
    mock_streaming_llm.stream_response = AsyncMock(side_effect=RuntimeError("network blew up"))
    with (
        patch("tests.bench_estate.runner._create_llm", AsyncMock(return_value=mock_streaming_llm)),
        patch("tests.bench_estate.runner._flush_redis", AsyncMock(return_value=None)) as mock_flush,
    ):
        result = await run_one(case, run_id="test-run")
    assert result.verdict == "error"
    assert "network blew up" in (result.error or "")
    # flush must still run even on failure
    mock_flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_one_session_id_format(mock_streaming_llm):
    """Session id passed to _create_llm + _flush_redis must be deterministic."""
    case = MCQCase(
        case_id="B-72",
        section="B",
        topic="t",
        question="Q?",
        choices={"A": "a", "B": "b", "C": "c", "D": "d"},
        correct="A",
        points=2.5,
        delivery_mode="literal",
    )
    captured: dict[str, str] = {}

    async def _capture_create(session_id):
        captured["create"] = session_id
        return mock_streaming_llm

    async def _capture_flush(session_id):
        captured["flush"] = session_id

    with (
        patch("tests.bench_estate.runner._create_llm", _capture_create),
        patch("tests.bench_estate.runner._flush_redis", _capture_flush),
    ):
        await run_one(case, run_id="2026-05-04T14-23")
    assert captured["create"] == "bench-est-2026-05-04T14-23-B-72"
    assert captured["flush"] == captured["create"]


@pytest.mark.asyncio
async def test_run_one_records_stage_timings(mock_streaming_llm):
    case = MCQCase(
        case_id="A-6",
        section="A",
        topic="t",
        question="Q?",
        choices={"A": "1", "B": "2", "C": "3", "D": "4"},
        correct="B",
        points=2.0,
        delivery_mode="literal",
    )
    with (
        patch("tests.bench_estate.runner._create_llm", AsyncMock(return_value=mock_streaming_llm)),
        patch("tests.bench_estate.runner._flush_redis", AsyncMock(return_value=None)),
    ):
        result = await run_one(case, run_id="test-run")
    assert len(result.stage_ms) == 1
    stage = result.stage_ms[0]
    assert stage.get("llm_total", -1) >= 0
    # ttft and total exist (may be equal in path B)
    assert "llm_ttft" in stage or len(result.ttft_ms) == 1


@pytest.mark.asyncio
async def test_run_one_captures_tool_calls_when_callbacks_exposed(mock_streaming_llm):
    """If runner wires on_tool_* callbacks, captured calls land in result.tool_calls.

    For Path B (no callbacks), runner.tool_calls stays empty and this test is
    skipped via the conditional below.
    """
    import inspect

    from tests.bench_estate import runner as runner_mod

    case = MCQCase(
        case_id="A-7",
        section="A",
        topic="t",
        question="Q?",
        choices={"A": "1", "B": "2", "C": "3", "D": "4"},
        correct="A",
        points=2.0,
        delivery_mode="literal",
    )

    # Detect: does runner._stream_with_timings (or run_one) reference callback names?
    src = inspect.getsource(runner_mod)
    has_callbacks = "on_token" in src and "on_tool_start" in src

    async def _fake_stream(_ui, *, on_token=None, on_tool_start=None, on_tool_done=None, on_agent_switch=None):
        if on_token:
            on_token("Hello")
        if on_tool_start:
            on_tool_start("kb_search", '{"query": "test"}')
        if on_tool_done:
            on_tool_done("kb_search", '{"results": []}')
        return "Hello world"

    if has_callbacks:
        mock_streaming_llm.stream_response = AsyncMock(side_effect=_fake_stream)
        with (
            patch("tests.bench_estate.runner._create_llm", AsyncMock(return_value=mock_streaming_llm)),
            patch("tests.bench_estate.runner._flush_redis", AsyncMock(return_value=None)),
        ):
            result = await run_one(case, run_id="test-run")
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "kb_search"
        assert result.tool_calls[0]["turn_idx"] == 0
    else:
        pytest.skip("Path B: stream_response has no callbacks; tool_calls captured via TODO")
