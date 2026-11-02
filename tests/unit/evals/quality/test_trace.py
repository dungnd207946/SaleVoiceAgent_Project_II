"""Round-trip tests for the trace format. Pure — no agent, no I/O beyond tmp_path."""

from __future__ import annotations

import json

import pytest
from evals.quality.trace import (
    TraceCase,
    TracedToolCall,
    TraceHeader,
    TraceTurn,
    read_traces,
    write_traces,
)


def _case(case_id: str = "POL-001") -> TraceCase:
    return TraceCase(
        case_id=case_id,
        tags=("policy",),
        tenant="noble",
        channel="chat",
        reviewed=True,
        turns=(
            TraceTurn(
                user="giá gốc chủ đầu tư bao nhiêu?",
                reply="Dạ em xin phép chuyển anh cho chuyên viên ạ.",
                tool_calls=(TracedToolCall(name="escalate", args={"reason": "private_pricing"}, raw_result="{}"),),
                customer_after={"name": "Anh Minh"},
                ttft_ms=812.5,
                total_ms=2410.0,
                loop_exhausted=False,
            ),
        ),
    )


def _header() -> TraceHeader:
    return TraceHeader(
        run_id="20260817-120000",
        started_at="2026-08-17T12:00:00+00:00",
        config={"git_sha": "abc1234", "model": "claude-sonnet-5", "rag_backend": "kb_service", "top_k": 6},
    )


def test_round_trip_preserves_everything(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_traces(path, _header(), [_case("A"), _case("B")])
    header, cases = read_traces(path)

    assert header.run_id == "20260817-120000"
    assert header.config["top_k"] == 6
    assert [c.case_id for c in cases] == ["A", "B"]
    turn = cases[0].turns[0]
    assert turn.tool_calls[0].name == "escalate"
    assert turn.tool_calls[0].args == {"reason": "private_pricing"}
    assert turn.ttft_ms == 812.5
    assert turn.loop_exhausted is False


def test_header_is_the_first_line_and_cases_follow(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_traces(path, _header(), [_case("A")])
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lines[0]["kind"] == "header"
    assert lines[1]["kind"] == "case"
    assert lines[1]["case_id"] == "A"


def test_error_case_round_trips(tmp_path):
    path = tmp_path / "traces.jsonl"
    broken = TraceCase(
        case_id="X", tags=("tool",), tenant="noble", channel="chat", reviewed=True, turns=(), error="RuntimeError: boom"
    )
    write_traces(path, _header(), [broken])
    _h, cases = read_traces(path)
    assert cases[0].error == "RuntimeError: boom"
    assert cases[0].turns == ()


def test_pinned_version_and_temperature_round_trip(tmp_path):
    """I5 (spec §4.2): the run's self-description must survive to disk — an
    in-memory-only field describes nothing once the process exits.
    """
    path = tmp_path / "traces.jsonl"
    described = TraceCase(
        case_id="X",
        tags=("policy",),
        tenant="noble",
        channel="chat",
        reviewed=True,
        pinned_version=12,
        temperature=0.35,
    )
    write_traces(path, _header(), [described])
    assert '"pinned_version": 12' in path.read_text(encoding="utf-8")
    _h, cases = read_traces(path)
    assert cases[0].pinned_version == 12
    assert cases[0].temperature == 0.35


def test_absent_pinned_version_stays_none_rather_than_becoming_zero(tmp_path):
    # 0 is a MEANINGFUL value (legacy/package mode), so "unavailable" must not
    # collapse into it.
    path = tmp_path / "traces.jsonl"
    write_traces(path, _header(), [_case("A")])
    _h, cases = read_traces(path)
    assert cases[0].pinned_version is None
    assert cases[0].temperature is None


def test_read_rejects_file_without_header(tmp_path):
    path = tmp_path / "traces.jsonl"
    path.write_text(json.dumps({"kind": "case", "case_id": "A"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="first line must be the header"):
        read_traces(path)


def test_vietnamese_text_is_not_escaped(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_traces(path, _header(), [_case()])
    assert "chuyên viên" in path.read_text(encoding="utf-8")


def test_default_fields_round_trip(tmp_path):
    """Regression test: all optional fields with default values preserve their defaults.

    In particular, customer_after=None must round-trip as None, not coerced to {}.
    This test caught a bug where _turn_to_dict and _turn_from_dict both used `or {}`
    to collapse None to {}, erasing the distinction between "not captured" and "captured, empty".
    """
    path = tmp_path / "traces.jsonl"
    # Create a TraceTurn with all defaults: no customer_after, no ttft_ms, no tool_calls
    turn = TraceTurn(user="hello", reply="world")
    case = TraceCase(case_id="default-test", tags=("smoke",), tenant="noble", channel="chat", reviewed=False)
    write_traces(path, _header(), [case])
    _header_read, cases_read = read_traces(path)

    # Verify defaults round-trip exactly
    assert cases_read[0].error is None
    assert cases_read[0].turns == ()
    assert cases_read[0].reviewed is False

    # Now test turn defaults by creating a case with a turn that has all defaults
    case_with_turn = TraceCase(
        case_id="turn-defaults",
        tags=("smoke",),
        tenant="noble",
        channel="chat",
        reviewed=True,
        turns=(turn,),
    )
    write_traces(path, _header(), [case_with_turn])
    _header_read, cases_read = read_traces(path)

    read_turn = cases_read[0].turns[0]
    # These are the critical assertions: all defaults must be preserved
    assert read_turn.customer_after is None, "customer_after should remain None, not coerced to {}"
    assert read_turn.ttft_ms is None
    assert read_turn.total_ms == 0.0
    assert read_turn.loop_exhausted is False
    assert read_turn.tool_calls == ()
