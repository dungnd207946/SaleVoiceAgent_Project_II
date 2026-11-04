from evals.report import render_trend


def _e(kind, run_id, verdict, metrics, ts="2026-08-24T10:00:00+00:00"):
    return {
        "run_id": run_id,
        "ts": ts,
        "kind": kind,
        "git_sha": "abc",
        "config": {},
        "metrics": metrics,
        "gates": {},
        "verdict": verdict,
        "report_dir": "",
    }


def test_latest_per_kind_and_delta():
    entries = [
        _e("quality", "q1", "pass", {"policy_pass_rate": 1.0, "ttft_p95_ms": 800.0}),
        _e(
            "quality",
            "q2",
            "pass",
            {"policy_pass_rate": 0.9, "ttft_p95_ms": 900.0},
            ts="2026-08-25T10:00:00+00:00",
        ),
        _e("bench", "b1", "pass", {"stt_total_p95_ms": 1200.0}),
    ]
    md = render_trend(entries)
    assert "q2" in md and "b1" in md
    assert "Δ" in md and "-0.1" in md  # policy_pass_rate 1.0 → 0.9


def test_empty_registry():
    assert "chưa có run nào" in render_trend([])


def test_v2_metric_names_render():
    """_KIND_METRICS must point at live v2 metric names, not deleted v1 ones."""
    entries = [
        _e(
            "quality",
            "q1",
            "pass",
            {
                "policy_pass_rate": 1.0,
                "arg_accuracy": 1.0,
                "tool_selection_accuracy": 0.9,
                "banned_call_rate": 0.0,
                "ttft_p95_ms": 800.0,
                "answer_correctness_mean": 0.8,
                "grounded_rate": 0.95,
                "context_retention_score": 0.7,
            },
        ),
        _e(
            "rag",
            "r1",
            "pass",
            {
                "recall_at_1": 0.5,
                "recall_at_5": 0.8,
                "context_recall_at_5": 0.6,
                "mrr": 0.7,
                "empty_rate": 0.0,
                "retrieval_p95_ms": 120.0,
                "faithfulness_rate": 0.9,
            },
        ),
    ]
    md = render_trend(entries)
    for key in (
        "tool_selection_accuracy",
        "banned_call_rate",
        "answer_correctness_mean=0.8",
        "grounded_rate=0.95",
        "context_retention_score=0.7",
    ):
        assert key in md
    for key in ("context_recall_at_5=0.6", "faithfulness_rate=0.9"):
        assert key in md
    # dead v1 names must no longer be referenced
    assert "retrieval_hit_rate" not in md
    assert "judge_quality_mean" not in md
