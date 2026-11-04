"""Shared utilities for the bench suite.

Goal: every bench file produces the same JSON shape under tests/bench/results/
so we can diff Mac (local) vs Pod (RunPod) vs EC2 (in-region) easily.
"""

from __future__ import annotations

import json
import os
import socket
import statistics
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Result directory — gitignored (see .gitignore)
RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Stats ────────────────────────────────────────────────────────────────


def percentile(data: Iterable[float], p: float) -> float:
    arr = sorted(data)
    if not arr:
        return 0.0
    if len(arr) == 1:
        return arr[0]
    k = (len(arr) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    return arr[f] + (k - f) * (arr[c] - arr[f])


@dataclass
class BenchResult:
    name: str  # e.g. "mongo.ping"
    n: int  # successful sample count
    failed: int = 0  # exception count
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    stdev_ms: float = 0.0
    samples: list[float] = field(default_factory=list)
    env_label: str = ""
    timestamp: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_samples(
        cls,
        name: str,
        samples_ms: list[float],
        failed: int = 0,
        extra: dict | None = None,
        first_error: str | None = None,
    ) -> "BenchResult":
        merged = dict(extra or {})
        if first_error:
            merged["first_error"] = first_error
        if not samples_ms:
            return cls(
                name=name,
                n=0,
                failed=failed,
                env_label=detect_env_label(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                extra=merged,
            )
        return cls(
            name=name,
            n=len(samples_ms),
            failed=failed,
            p50_ms=round(percentile(samples_ms, 50), 2),
            p95_ms=round(percentile(samples_ms, 95), 2),
            p99_ms=round(percentile(samples_ms, 99), 2),
            min_ms=round(min(samples_ms), 2),
            max_ms=round(max(samples_ms), 2),
            mean_ms=round(statistics.mean(samples_ms), 2),
            stdev_ms=round(statistics.stdev(samples_ms), 2) if len(samples_ms) > 1 else 0.0,
            samples=[round(x, 2) for x in samples_ms],
            env_label=detect_env_label(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            extra=merged,
        )

    def pretty(self) -> str:
        if self.n == 0:
            err = self.extra.get("first_error", "")
            tail = f"  err={err}" if err else ""
            return f"[{self.name}] NO SAMPLES (failed={self.failed}){tail}"
        return (
            f"[{self.name}] n={self.n} fail={self.failed}  "
            f"p50={self.p50_ms:>7.1f}ms  p95={self.p95_ms:>7.1f}ms  "
            f"p99={self.p99_ms:>7.1f}ms  min={self.min_ms:>6.1f}  "
            f"max={self.max_ms:>7.1f}  mean={self.mean_ms:>6.1f}±{self.stdev_ms:.1f}"
        )


# ─── Env detection (Mac local vs RunPod vs EC2) ──────────────────────────


def detect_env_label() -> str:
    """Auto-label run environment so JSON files self-identify.

    Heuristic: hostname pattern → mac | runpod | ec2 | other.
    Override with BENCH_ENV_LABEL.
    """
    override = os.environ.get("BENCH_ENV_LABEL")
    if override:
        return override
    host = socket.gethostname().lower()
    if "runpod" in host or host.startswith("pod-") or "/workspace" in os.environ.get("PWD", ""):
        return "runpod"
    if "ip-" in host or "ec2" in host:
        return "ec2"
    if host.endswith(".local") or "macbook" in host or "mbp" in host or "mac" in host:
        return "mac-local"
    return host


# ─── Timing primitives ────────────────────────────────────────────────────


@asynccontextmanager
async def atimer():
    """Async timer ctx → yields a list, [0] holds elapsed ms after exit."""
    t0 = time.perf_counter()
    box = [0.0]
    try:
        yield box
    finally:
        box[0] = (time.perf_counter() - t0) * 1000


async def run_async(fn, n_runs: int, warmup: int = 0) -> tuple[list[float], int, str | None]:
    """Run async callable `fn()` n_runs times.

    Returns (samples_ms, failed_count, first_error_repr). Captures the FIRST
    exception text so silent failures get surfaced — caller can assert/print.
    """
    samples: list[float] = []
    failed = 0
    first_err: str | None = None
    for i in range(n_runs + warmup):
        t0 = time.perf_counter()
        try:
            await fn()
        except Exception as e:
            failed += 1
            if first_err is None:
                first_err = f"{type(e).__name__}: {e}"
            continue
        elapsed = (time.perf_counter() - t0) * 1000
        if i >= warmup:
            samples.append(elapsed)
    return samples, failed, first_err


def run_sync(fn, n_runs: int, warmup: int = 0) -> tuple[list[float], int, str | None]:
    """Sync version of run_async."""
    samples: list[float] = []
    failed = 0
    first_err: str | None = None
    for i in range(n_runs + warmup):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception as e:
            failed += 1
            if first_err is None:
                first_err = f"{type(e).__name__}: {e}"
            continue
        elapsed = (time.perf_counter() - t0) * 1000
        if i >= warmup:
            samples.append(elapsed)
    return samples, failed, first_err


# ─── Persistence ─────────────────────────────────────────────────────────


def save_result(result: BenchResult, suite: str) -> Path:
    """Append to a single JSONL file per suite per env. Easy to diff later.

    File: tests/bench/results/<suite>__<env>.jsonl
    """
    fn = RESULTS_DIR / f"{suite}__{result.env_label or 'unknown'}.jsonl"
    with fn.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    return fn


def print_section(title: str) -> None:
    bar = "─" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


__all__ = [
    "BenchResult",
    "RESULTS_DIR",
    "atimer",
    "detect_env_label",
    "percentile",
    "print_section",
    "run_async",
    "run_sync",
    "save_result",
]
