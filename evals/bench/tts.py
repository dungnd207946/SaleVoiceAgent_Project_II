"""Bench TTS service remote (WS). Protocol: scripts/load_test/v2/phase_a_tts.py."""

from __future__ import annotations

import contextlib
import json
import time

from evals.bench.results import ComponentResult, aggregate_runs


async def _once(url: str, token: str, text: str, voice: str | None) -> dict[str, float]:
    import websockets  # noqa: PLC0415

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    msg: dict = {"type": "synthesize", "text": text}
    if voice:
        msg["voice"] = voice
    t0 = time.perf_counter()
    ttfb = 0.0
    audio_bytes = 0
    async with websockets.connect(url, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(msg))
        async for raw in ws:
            if isinstance(raw, bytes):
                if not audio_bytes:
                    ttfb = (time.perf_counter() - t0) * 1000.0
                audio_bytes += len(raw)
            elif json.loads(raw).get("type") == "end":
                break
    if not audio_bytes:
        raise ValueError("no PCM received")
    return {"ttfb_ms": ttfb, "total_ms": (time.perf_counter() - t0) * 1000.0, "audio_bytes": float(audio_bytes)}


async def measure_tts(*, url: str, token: str, text: str, voice: str | None, runs: int = 10) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    with contextlib.suppress(Exception):
        await _once(url, token, text, voice)
    for _ in range(runs):
        try:
            samples.append(await _once(url, token, text, voice))
        except Exception:  # noqa: BLE001
            errors += 1
    return aggregate_runs("tts", samples, errors)
