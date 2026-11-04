"""Bench speaker-embedding service (HTTP). Contract: POST /embed {"audio_b64"} → {"embedding": [...]}
(src/noble_agent/voice/service/speaker_server.py docstring)."""

from __future__ import annotations

import base64
import contextlib
import time

from evals.bench.results import ComponentResult, aggregate_runs


async def _once(url: str, pcm: bytes) -> dict[str, float]:
    import httpx  # noqa: PLC0415

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{url.rstrip('/')}/embed", json={"audio_b64": base64.b64encode(pcm).decode()})
        resp.raise_for_status()
        if not resp.json().get("embedding"):
            raise ValueError("no embedding in response")
    return {"total_ms": (time.perf_counter() - t0) * 1000.0}


async def measure_speaker(*, url: str, pcm: bytes, runs: int = 10) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    with contextlib.suppress(Exception):
        await _once(url, pcm)
    for _ in range(runs):
        try:
            samples.append(await _once(url, pcm))
        except Exception:  # noqa: BLE001
            errors += 1
    return aggregate_runs("speaker", samples, errors)
