"""Unit tests for differ.py — synthetic report fixtures, no I/O beyond tmp_path."""

from __future__ import annotations

import json
from pathlib import Path

from tests.bench_estate.differ import Diff, compare


def _write_report(
    path: Path,
    run_id: str,
    cases: list[dict],
    totals: dict | None = None,
    sections: dict | None = None,
    latency: dict | None = None,
) -> None:
    data = {
        "schema_version": "1.0",
        "run_id": run_id,
        "config": {"prompt_version": "v9-bench", "agent_provider": "openai"},
        "totals": totals or {"score_raw": 0.0, "score_max": 0.0, "percent": 0.0, "verdict": "?"},
        "sections": sections or {},
        "latency_ms": latency or {},
        "judge_stats": {"cost_usd": 0.0, "errors": 0, "cached_hits": 0},
        "cases": cases,
        "failures": [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_compare_classifies_fixed_regressed_unchanged(tmp_path: Path) -> None:
    a_cases = [
        {"case_id": "A-1", "topic": "t1", "verdict": "fail", "score_raw": 0.0, "score_max": 2.0},
        {"case_id": "A-2", "topic": "t2", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
        {"case_id": "A-3", "topic": "t3", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
        {"case_id": "A-4", "topic": "t4", "verdict": "fail", "score_raw": 0.0, "score_max": 2.0},
    ]
    b_cases = [
        {"case_id": "A-1", "topic": "t1", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
        {"case_id": "A-2", "topic": "t2", "verdict": "fail", "score_raw": 0.0, "score_max": 2.0},
        {"case_id": "A-3", "topic": "t3", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
        {"case_id": "A-4", "topic": "t4", "verdict": "fail", "score_raw": 0.0, "score_max": 2.0},
    ]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write_report(a, "run-A", a_cases)
    _write_report(b, "run-B", b_cases)
    diff = compare(a, b)
    assert isinstance(diff, Diff)
    assert [r["case_id"] for r in diff.fixed] == ["A-1"]
    assert [r["case_id"] for r in diff.regressed] == ["A-2"]
    assert [r["case_id"] for r in diff.unchanged_pass] == ["A-3"]
    assert [r["case_id"] for r in diff.unchanged_fail] == ["A-4"]
    assert diff.fixed[0]["score_a"] == 0.0
    assert diff.fixed[0]["score_b"] == 2.0


def test_compare_handles_new_and_removed_cases(tmp_path: Path) -> None:
    a_cases = [
        {"case_id": "A-1", "topic": "t1", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
        {"case_id": "A-2", "topic": "t2", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
    ]
    b_cases = [
        {"case_id": "A-1", "topic": "t1", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
        {"case_id": "A-3", "topic": "t3", "verdict": "pass", "score_raw": 2.0, "score_max": 2.0},
    ]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write_report(a, "run-A", a_cases)
    _write_report(b, "run-B", b_cases)
    diff = compare(a, b)
    assert [r["case_id"] for r in diff.removed_cases] == ["A-2"]
    assert [r["case_id"] for r in diff.new_cases] == ["A-3"]
    assert [r["case_id"] for r in diff.unchanged_pass] == ["A-1"]
    assert diff.fixed == []
    assert diff.regressed == []


def test_compare_carries_overall_and_latency_metadata(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write_report(
        a,
        "run-A",
        [],
        totals={"score_raw": 100.0, "score_max": 200.0, "percent": 50.0, "verdict": "?"},
        sections={"A": {"raw": 50.0, "max": 100.0}, "B": {"raw": 50.0, "max": 100.0}},
        latency={"llm_ttft": {"p50": 200, "p95": 1500, "p99": 3000}},
    )
    _write_report(
        b,
        "run-B",
        [],
        totals={"score_raw": 150.0, "score_max": 200.0, "percent": 75.0, "verdict": "?"},
        sections={"A": {"raw": 80.0, "max": 100.0}, "B": {"raw": 70.0, "max": 100.0}},
        latency={"llm_ttft": {"p50": 180, "p95": 1300, "p99": 2700}},
    )
    diff = compare(a, b)
    assert diff.overall_a == (100.0, 200.0)
    assert diff.overall_b == (150.0, 200.0)
    assert diff.sections_a["A"]["raw"] == 50.0
    assert diff.sections_b["B"]["raw"] == 70.0
    assert diff.latency_a["llm_ttft"]["p95"] == 1500
    assert diff.latency_b["llm_ttft"]["p95"] == 1300
