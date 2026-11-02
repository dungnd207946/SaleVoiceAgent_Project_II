"""Bench VAD Silero — import ĐÚNG class worker dùng (cùng model + settings), không sửa src."""

from __future__ import annotations

import os
import time

from evals.bench.results import ComponentResult, aggregate_runs


def iter_chunks(pcm: bytes, chunk_bytes: int) -> list[bytes]:
    """Thuần — cắt pcm thành các chunk đủ size, bỏ tail không đủ chunk_bytes."""
    return [pcm[off : off + chunk_bytes] for off in range(0, len(pcm) - chunk_bytes + 1, chunk_bytes)]


def measure_vad(pcm: bytes) -> ComponentResult:
    os.environ.setdefault("BILLING_METERING_ENABLED", "false")
    from noble_agent.voice.vad.silero import CHUNK_SAMPLES, SileroVAD  # noqa: PLC0415

    vad = SileroVAD()  # load model 1 lần, ngoài vòng đo
    samples: list[dict[str, float]] = []
    chunks = iter_chunks(pcm, CHUNK_SAMPLES * 2)
    t_all = time.perf_counter()
    for chunk in chunks:
        t0 = time.perf_counter()
        vad.process_chunk(chunk)
        samples.append({"chunk_ms": (time.perf_counter() - t0) * 1000.0})
    wall_s = time.perf_counter() - t_all
    result = aggregate_runs("vad", samples, errors=0)
    if wall_s > 0:
        print(f"vad throughput: {len(chunks) / wall_s:.0f} chunks/s ({len(chunks)} chunks)")
    return result
