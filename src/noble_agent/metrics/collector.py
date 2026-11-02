"""MetricsCollector — in-memory latency + counter tracking with percentile calculations.

Moved from rag/metrics.py for proper module organization.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class LatencyRecord:
    component: str
    operation: str
    duration_ms: float
    timestamp: float


class MetricsCollector:
    def __init__(self) -> None:
        self._records: list[LatencyRecord] = []
        self._counters: dict[str, int] = defaultdict(int)

    def record_latency(self, component: str, operation: str, duration_ms: float) -> None:
        self._records.append(
            LatencyRecord(
                component=component,
                operation=operation,
                duration_ms=duration_ms,
                timestamp=time.time(),
            )
        )

    def increment(self, counter_name: str, amount: int = 1) -> None:
        self._counters[counter_name] += amount

    def get_counter(self, counter_name: str) -> int:
        return self._counters.get(counter_name, 0)

    @property
    def cache_hit_rate(self) -> float:
        hits = self._counters.get("cache_hit", 0)
        misses = self._counters.get("cache_miss", 0)
        total = hits + misses
        return hits / total if total > 0 else 0.0

    def _percentile(self, values: list[float], p: int) -> float:
        if not values:
            return 0.0
        sorted_v = sorted(values)
        k = (len(sorted_v) - 1) * (p / 100)
        f = int(k)
        c = min(f + 1, len(sorted_v) - 1)
        return sorted_v[f] + (k - f) * (sorted_v[c] - sorted_v[f])

    def _get_durations(self, component: str, operation: str | None = None) -> list[float]:
        return [
            r.duration_ms
            for r in self._records
            if r.component == component and (operation is None or r.operation == operation)
        ]

    def get_avg_latency(self, component: str, operation: str | None = None) -> float:
        durations = self._get_durations(component, operation)
        return sum(durations) / len(durations) if durations else 0.0

    def get_p50_latency(self, component: str, operation: str | None = None) -> float:
        return self._percentile(self._get_durations(component, operation), 50)

    def get_p95_latency(self, component: str, operation: str | None = None) -> float:
        return self._percentile(self._get_durations(component, operation), 95)

    def get_p99_latency(self, component: str, operation: str | None = None) -> float:
        return self._percentile(self._get_durations(component, operation), 99)

    def summary(self) -> dict[str, Any]:
        components = {r.component for r in self._records}
        result: dict[str, Any] = {
            "counters": dict(self._counters),
            "cache_hit_rate": f"{self.cache_hit_rate:.1%}",
            "latency": {},
        }
        for comp in sorted(components):
            operations = {r.operation for r in self._records if r.component == comp}
            result["latency"][comp] = {}
            for op in sorted(operations):
                durations = self._get_durations(comp, op)
                result["latency"][comp][op] = {
                    "count": len(durations),
                    "avg_ms": round(self.get_avg_latency(comp, op), 1),
                    "p50_ms": round(self._percentile(durations, 50), 1),
                    "p95_ms": round(self._percentile(durations, 95), 1),
                    "p99_ms": round(self._percentile(durations, 99), 1),
                    "min_ms": round(min(durations), 1) if durations else 0,
                    "max_ms": round(max(durations), 1) if durations else 0,
                }
        return result

    def to_records_list(self) -> list[dict]:
        return [
            {
                "component": r.component,
                "operation": r.operation,
                "duration_ms": round(r.duration_ms, 1),
                "timestamp": r.timestamp,
            }
            for r in self._records
        ]

    def reset(self) -> None:
        self._records.clear()
        self._counters.clear()


class Timer:
    """Context manager that auto-records latency on exit."""

    def __init__(self, metrics: MetricsCollector, component: str, operation: str) -> None:
        self._metrics = metrics
        self._component = component
        self._operation = operation
        self._start: float = 0
        self.elapsed_ms: float = 0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
        self._metrics.record_latency(self._component, self._operation, self.elapsed_ms)
