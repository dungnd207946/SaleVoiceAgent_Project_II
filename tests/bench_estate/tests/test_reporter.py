"""Unit tests for reporter.py — pure aggregation + render."""

from __future__ import annotations

import json

import pytest

from tests.bench_estate.reporter import (
    build_report,
    dump_json,
    dump_markdown,
    latency_breakdown,
    percentiles,
    render_markdown,
    section_breakdown,
    status_icon,
    tool_stats,
    topic_breakdown,
)
from tests.bench_estate.runner import CaseResult


def _r(
    case_id,
    section="A",
    topic="t",
    verdict="pass",
    score=2.0,
    max_=2.0,
    ttft=300,
    total=1000,
    stage_ms=None,
    tool_calls=None,
):
    r = CaseResult(case_id=case_id, section=section, topic=topic, delivery_mode="roleplay")
    r.user_inputs.append("u")
    r.agent_outputs.append("a")
    r.ttft_ms.append(float(ttft))
    r.total_ms.append(float(total))
    r.stage_ms.append(stage_ms or {"llm_ttft": ttft, "llm_total": total})
    r.tool_calls = tool_calls or []
    r.verdict = verdict
    r.score_raw = score
    r.score_max = max_
    return r


def test_percentiles_basic():
    p = percentiles([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    assert 50 <= p["p50"] <= 60
    assert p["p95"] >= 90


def test_percentiles_empty():
    assert percentiles([]) == {"p50": 0.0, "p95": 0.0, "p99": 0.0}


def test_percentiles_singleton():
    assert percentiles([42.0]) == {"p50": 42.0, "p95": 42.0, "p99": 42.0}


def test_status_icon_known_verdicts():
    assert "✓" in status_icon("pass")
    assert "✗" in status_icon("fail")
    assert "?" in status_icon("zzz")  # unknown defaults


def test_section_breakdown_counts():
    results = [
        _r("A-1", section="A", verdict="pass", score=2, max_=2),
        _r("A-2", section="A", verdict="fail", score=0, max_=2),
        _r("A-3", section="A", verdict="refused", score=0, max_=2),
        _r("B-1", section="B", verdict="pass", score=2.5, max_=2.5),
    ]
    sb = section_breakdown(results)
    assert sb["A"]["passed"] == 1
    assert sb["A"]["failed"] == 1
    assert sb["A"]["refused"] == 1
    assert sb["A"]["count"] == 3
    assert sb["B"]["count"] == 1


def test_topic_breakdown_fail_rate():
    results = [
        _r("A-1", topic="CCHN", verdict="pass"),
        _r("A-2", topic="CCHN", verdict="fail"),
        _r("A-3", topic="CCHN", verdict="fail"),
        _r("A-4", topic="NƠHTTL", verdict="pass"),
    ]
    tb = topic_breakdown(results)
    assert tb["CCHN"]["fail_rate"] == pytest.approx(2 / 3)
    assert tb["NƠHTTL"]["fail_rate"] == 0.0


def test_latency_breakdown_aggregates_per_stage():
    results = [
        _r("A-1", stage_ms={"llm_ttft": 300, "llm_total": 1000}),
        _r("A-2", stage_ms={"llm_ttft": 500, "llm_total": 2000}),
    ]
    lb = latency_breakdown(results)
    assert "llm_ttft" in lb
    assert lb["llm_ttft"]["p50"] >= 300


def test_tool_stats_counts():
    results = [
        _r("A-1", tool_calls=[{"name": "kb_search"}, {"name": "kb_search"}]),
        _r("A-2", tool_calls=[{"name": "update_customer"}]),
    ]
    ts = tool_stats(results)
    assert ts["kb_search"]["calls"] == 2
    assert ts["update_customer"]["calls"] == 1


def test_build_report_shape():
    results = [_r("A-1", verdict="pass", score=2, max_=2)]
    config = {
        "run_id": "test-run",
        "agent_provider": "openai",
        "agent_model": "gpt-x",
        "judge_model": "gpt-y",
        "self_bias_warning": False,
    }
    report = build_report(
        results,
        config,
        judge_cost_usd=0.001,
        started_at="2026-05-04T00:00:00",
        finished_at="2026-05-04T00:01:00",
        total_seconds=60.0,
    )
    assert report["schema_version"] == "1.0"
    assert report["run_id"] == "test-run"
    assert report["totals"]["score_raw"] == 2.0
    assert report["totals"]["verdict"] == "ĐẠT"
    assert "A" in report["sections"]
    assert len(report["cases"]) == 1


def test_dump_json_roundtrip(tmp_path):
    results = [_r("A-1", verdict="pass", score=2, max_=2)]
    report = build_report(results, {"run_id": "x"}, 0.0, "s", "f", 1.0)
    out = tmp_path / "report.json"
    dump_json(report, out)
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["run_id"] == "x"


def test_render_markdown_contains_sections_and_totals():
    results = [
        _r("A-1", verdict="pass", score=2, max_=2),
        _r("A-2", verdict="fail", score=0, max_=2),
    ]
    report = build_report(
        results,
        {
            "run_id": "test",
            "agent_provider": "openai",
            "agent_model": "x",
            "judge_model": "y",
        },
        0.0,
        "s",
        "f",
        1.0,
    )
    md = render_markdown(report)
    assert "# Noble Hotline Eval" in md
    assert "## Sections" in md
    assert "A-2" in md  # failure listed


def test_dump_markdown_writes_file(tmp_path):
    results = [_r("A-1")]
    report = build_report(results, {"run_id": "x"}, 0.0, "s", "f", 1.0)
    out = tmp_path / "report.md"
    dump_markdown(report, out)
    assert out.exists()
    assert "# Noble Hotline Eval" in out.read_text(encoding="utf-8")
