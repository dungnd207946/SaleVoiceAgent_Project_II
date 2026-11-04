"""Tests for evals.quality.latency aggregator."""

from evals.quality.latency import score_latency
from evals.quality.trace import TraceCase, TraceTurn


def _case(turns):
    return TraceCase(case_id="c1", tags=("tool",), tenant="noble", channel="chat", reviewed=True, turns=tuple(turns))


def test_aggregates_percentiles():
    traces = [_case([TraceTurn(user="u", reply="r", ttft_ms=100.0, total_ms=200.0),
                     TraceTurn(user="u", reply="r", ttft_ms=300.0, total_ms=400.0)])]
    score = score_latency([], traces)
    assert score.axis == "latency"
    assert score.metrics["ttft_p50_ms"] == 100.0
    assert score.metrics["turn_total_p95_ms"] == 400.0


def test_empty_sample_is_none():
    traces = [_case([TraceTurn(user="u", reply="r", ttft_ms=None, total_ms=0.0)])]
    score = score_latency([], traces)
    assert score.metrics["ttft_p50_ms"] is None
    assert score.metrics["turn_total_p50_ms"] is None
