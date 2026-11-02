"""Bench STT service remote (WS). Protocol + no-eos rationale: scripts/load_test/v2/phase_a_stt.py."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

from evals.bench.results import ComponentResult, aggregate_runs

_FRAME_BYTES = 640  # 20 ms @ 16 kHz PCM16


async def _once(url: str, token: str, pcm: bytes, timeout_s: float = 20.0) -> dict[str, float]:
    import websockets  # noqa: PLC0415

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    t0 = time.perf_counter()
    ttfb: list[float] = []
    done = asyncio.Event()

    async with websockets.connect(url, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        async def recv() -> None:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                if not ttfb:
                    ttfb.append((time.perf_counter() - t0) * 1000.0)
                if json.loads(raw).get("type") == "final":
                    done.set()
                    return

        rx = asyncio.create_task(recv())
        for off in range(0, len(pcm), _FRAME_BYTES):
            await ws.send(pcm[off:off + _FRAME_BYTES])
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout_s)
        finally:
            rx.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await rx
    return {"ttfb_ms": ttfb[0] if ttfb else 0.0, "total_ms": (time.perf_counter() - t0) * 1000.0}


async def measure_stt(*, url: str, token: str, pcm: bytes, runs: int = 10) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    with contextlib.suppress(Exception):
        await _once(url, token, pcm)  # warm-up, bỏ kết quả
    for _ in range(runs):
        try:
            samples.append(await _once(url, token, pcm))
        except Exception:  # noqa: BLE001 — một run lỗi là một điểm error_rate, không crash bench
            errors += 1
    return aggregate_runs("stt", samples, errors)
