"""Aggregate kết quả bench per-component — thuần."""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.common import percentiles_ms


@dataclass
class ComponentResult:
    component: str
    runs: int
    errors: int
    stats: dict[str, dict[str, float]] = field(default_factory=dict)


def aggregate_runs(component: str, samples: list[dict[str, float]], errors: int) -> ComponentResult:
    metrics: dict[str, list[float]] = {}
    for sample in samples:
        for key, value in sample.items():
            metrics.setdefault(key, []).append(value)
    return ComponentResult(
        component=component, runs=len(samples), errors=errors,
        stats={k: percentiles_ms(v) for k, v in metrics.items()},
    )


def flatten(results: list[ComponentResult]) -> dict[str, float]:
    out: dict[str, float] = {}
    for res in results:
        for metric, pcts in res.stats.items():
            # Only append "_ms" when the source metric actually is one — otherwise a
            # non-time metric like "audio_bytes" gets a fabricated "_ms" suffix
            # (registry.jsonl is tracked append-only; must be right before the first
            # real bench row lands).
            is_ms = metric.endswith("_ms")
            base = f"{res.component}_{metric.removesuffix('_ms') if is_ms else metric}"
            for pname in ("p50", "p95"):
                if pname in pcts:
                    key = f"{base}_{pname}_ms" if is_ms else f"{base}_{pname}"
                    out[key] = pcts[pname]
        attempts = res.runs + res.errors
        out[f"{res.component}_error_rate"] = (res.errors / attempts) if attempts else 0.0
    return out
