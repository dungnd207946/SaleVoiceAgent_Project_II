"""Shared load-test primitives: ramp schedule, async step driver, percentiles, report writer.

Pure helpers (ramp_schedule/percentiles/is_broken/write_results_md) are unit-tested offline;
run_step/run_campaign are exercised with a fake make_request (no network).
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

# One request: returns latency in seconds, or raises on failure.
MakeRequest = Callable[[], Awaitable[float]]


def ramp_schedule(start: int = 1, factor: int = 2, max_concurrency: int = 256) -> list[int]:
    """[start, start*factor, ...] up to and including max_concurrency."""
    steps: list[int] = []
    c = start
    while c < max_concurrency:
        steps.append(c)
        c *= factor
    steps.append(max_concurrency)
    return steps


def percentiles(samples: list[float], ps: tuple[int, ...] = (50, 95, 99)) -> dict[str, float]:
    """Nearest-rank percentiles + max over samples (seconds). {} if empty."""
    if not samples:
        return {}
    ordered = sorted(samples)
    n = len(ordered)
    out: dict[str, float] = {}
    for p in ps:
        k = max(0, min(n - 1, (p * n + 99) // 100 - 1))  # ceil(p/100 * n) - 1
        out[f"p{p}"] = ordered[k]
    out["max"] = ordered[-1]
    return out


@dataclass
class StepResult:
    concurrency: int
    duration_s: float
    total: int
    ok: int
    failed: int
    latency: dict[str, float]
    err_rate: float

    @property
    def throughput(self) -> float:
        return self.ok / self.duration_s if self.duration_s else 0.0


def is_broken(step: StepResult, baseline_p95: float, err_thresh: float = 0.01, factor: float = 2.0) -> bool:
    if step.err_rate > err_thresh:
        return True
    p95 = step.latency.get("p95")
    return p95 is not None and baseline_p95 > 0 and p95 > factor * baseline_p95


async def run_step(make_request: MakeRequest, concurrency: int, hold_s: float) -> StepResult:
    """Run `concurrency` asyncio workers issuing requests back-to-back for hold_s seconds."""
    latencies: list[float] = []
    ok = 0
    failed = 0
    deadline = time.monotonic() + hold_s

    async def worker() -> None:
        nonlocal ok, failed  # single-threaded asyncio → counter mutation is safe
        while time.monotonic() < deadline:
            try:
                lat = await make_request()
                latencies.append(lat)
                ok += 1
            except Exception:
                failed += 1

    start = time.monotonic()
    await asyncio.gather(*[worker() for _ in range(concurrency)])
    dur = time.monotonic() - start
    total = ok + failed
    return StepResult(
        concurrency=concurrency,
        duration_s=dur,
        total=total,
        ok=ok,
        failed=failed,
        latency=percentiles(latencies),
        err_rate=(failed / total) if total else 0.0,
    )


@dataclass
class CampaignResult:
    label: str
    baseline_p95: float
    steps: list[StepResult] = field(default_factory=list)
    knee: int | None = None


def knee_by_plateau(steps: list[StepResult], err_thresh: float = 0.01, plateau_gain: float = 0.15) -> int | None:
    """Knee = highest concurrency still scaling: throughput gain over the previous step
    stays >= plateau_gain and errors stay within err_thresh. Steps must be concurrency-ordered."""
    if not steps:
        return None
    knee = steps[0].concurrency
    prev_thr = steps[0].throughput
    for s in steps[1:]:
        if s.err_rate > err_thresh:
            break
        gain = (s.throughput - prev_thr) / prev_thr if prev_thr > 0 else 0.0
        if gain < plateau_gain:
            break
        knee = s.concurrency
        prev_thr = s.throughput
    return knee


async def run_campaign(
    make_request: MakeRequest,
    *,
    label: str,
    ramp: list[int],
    hold_s: float,
    warmup_n: int = 3,
    full_ramp: bool = False,
    plateau_gain: float = 0.15,
) -> CampaignResult:
    """Run the ramp. full_ramp=True runs every step (no early stop) and picks the knee by
    throughput-plateau; otherwise it early-stops at the first is_broken step (2x baseline p95)."""
    for _ in range(warmup_n):
        with contextlib.suppress(Exception):
            await make_request()
    baseline = await run_step(make_request, 1, hold_s)
    baseline_p95 = baseline.latency.get("p95", 0.0)
    result = CampaignResult(label=label, baseline_p95=baseline_p95, steps=[baseline])
    knee = 1
    for c in ramp:
        if c <= 1:
            continue
        step = await run_step(make_request, c, hold_s)
        result.steps.append(step)
        if not full_ramp and is_broken(step, baseline_p95):
            break
        knee = c
    result.knee = knee_by_plateau(result.steps, plateau_gain=plateau_gain) if full_ramp else knee
    return result


def _ms(latency: dict[str, float], key: str) -> str:
    v = latency.get(key)
    return f"{v * 1000:.0f}" if v is not None else "-"


def write_results_md(result: CampaignResult, path: Path) -> None:
    lines = [
        f"# Load campaign — {result.label}",
        "",
        f"- warm baseline p95: {result.baseline_p95 * 1000:.0f} ms",
        f"- knee (max sustainable concurrency): **{result.knee}**",
        "",
        "| concurrency | ok | failed | err% | p50 ms | p95 ms | p99 ms | max ms | req/s |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in result.steps:
        lines.append(
            f"| {s.concurrency} | {s.ok} | {s.failed} | {s.err_rate * 100:.1f} | "
            f"{_ms(s.latency, 'p50')} | {_ms(s.latency, 'p95')} | {_ms(s.latency, 'p99')} | "
            f"{_ms(s.latency, 'max')} | {s.throughput:.1f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
