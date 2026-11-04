"""Aggregate per-turn ttft_ms/total_ms từ trace thành percentiles cho scorecard/registry.

Trace đã LUÔN capture hai số này (runner.py) — trước đây không ai aggregate. Không gate:
chỉ báo cáo để theo dõi trend (spec §5.2a); gate latency thêm sau khi có baseline.
"""

from __future__ import annotations

from evals.common import percentiles_ms
from evals.quality.scorers import AxisScore
from evals.quality.trace import TraceCase


def score_latency(cases: list, traces: list[TraceCase]) -> AxisScore:  # noqa: ARG001 — chữ ký scorer chung
    ttft = [t.ttft_ms for c in traces for t in c.turns if t.ttft_ms is not None]
    total = [t.total_ms for c in traces for t in c.turns if t.total_ms > 0]
    metrics: dict[str, float | None] = {}
    for name, samples in (("ttft", ttft), ("turn_total", total)):
        pcts = percentiles_ms(samples)
        metrics[f"{name}_p50_ms"] = pcts.get("p50")
        metrics[f"{name}_p95_ms"] = pcts.get("p95")
    return AxisScore(axis="latency", checks=0, failures=0, metrics=metrics)
