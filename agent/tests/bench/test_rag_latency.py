"""RAG retrieval latency: FlatStore (e5-large + BM25 RRF), full noble_kb.

What this measures (in-process, no cloud DB):
  - FlatStore cold load (first .load() — encodes or pulls .npy from disk)
  - FlatStore warm hybrid search (single pass after artifacts cached)
  - Full noble_kb e2e (what `noble_search` tool calls under the hood)

Run:
    pytest tests/bench/test_rag_latency.py -v -s -m bench

This suite does NOT need cloud DB — only `data/flat_store/` artifacts and the
e5-large model (downloaded automatically on first run if missing).
Result file: tests/bench/results/rag__<env>.jsonl
"""

from __future__ import annotations

import time

import pytest

from tests.bench._helpers import (
    BenchResult,
    atimer,
    print_section,
    run_async,
    save_result,
)

pytestmark = [pytest.mark.bench, pytest.mark.asyncio(loop_scope="session")]

SUITE = "rag"

# Realistic Vietnamese queries hitting different projects + intents.
# FlatStore tolerates an empty project_filter (broadens search), so this
# 5×projects×2 pattern is safe across the measured call paths.
QUERIES = [
    ("Noble Crystal Long Biên có bao nhiêu căn hộ?", "NCLB"),
    ("Tiện ích Noble Crystal Tây Hồ là gì?", "NCTH"),
    ("Pháp lý Noble Palace Long Biên thế nào", "NPLB"),
    ("Noble Palace Tây Thăng Long có bể bơi không?", "NTTL"),
    ("Sunshine Legend City vị trí ở đâu", "SSLC"),
    ("Giá căn hai phòng ngủ bao nhiêu", "NCTH"),
    ("So sánh diện tích các loại căn", "NCLB"),
    ("Dự án có gần trung tâm không", "SSLC"),
    ("Có chính sách trả góp không", "NPLB"),
    ("Bàn giao thô hay full nội thất", "NTTL"),
]


# ─── FlatStore ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def flatstore():
    """Module-scoped FlatStore — load once, share across warm tests."""
    from noble_agent.agent.rag.flat_store import FlatStore

    store = FlatStore()
    return store


async def test_flatstore_cold_load(flatstore):
    """One-shot timing of the very first .load(). Does NOT participate in
    percentile maths — single sample. Useful for tracking startup regressions."""
    async with atimer() as box:
        # FlatStore.load is sync — wrap to keep the timing API uniform.
        flatstore.load()
    if flatstore.embeddings is None or len(flatstore.embeddings) == 0:
        pytest.skip("FlatStore artifacts missing — run flat_store build first")

    n_chunks = int(len(flatstore.embeddings))
    res = BenchResult.from_samples(
        "flat_store.cold_load",
        [box[0]],
        extra={"n_chunks": n_chunks},
    )
    print_section(f"FlatStore cold-load ({res.env_label})")
    print(res.pretty())
    save_result(res, SUITE)


async def test_flatstore_warm_search_hybrid(flatstore, n_runs, warmup):
    """Hybrid (BM25 + dense RRF) — what noble_search uses by default."""
    flatstore.load()
    if flatstore.embeddings is None or len(flatstore.embeddings) == 0:
        pytest.skip("FlatStore artifacts missing")
    # search_hybrid auto-loads BM25 from disk on first call; no need to rebuild.

    samples: list[float] = []
    fail = 0
    first_err: str | None = None
    n_total = max(n_runs, len(QUERIES))
    for i in range(n_total + warmup):
        q, proj = QUERIES[i % len(QUERIES)]
        t0 = time.perf_counter()
        try:
            flatstore.search_hybrid(q, project_filter=proj or "", top_k=5)
        except Exception as e:
            fail += 1
            if first_err is None:
                first_err = f"{type(e).__name__}: {e}"
            continue
        elapsed = (time.perf_counter() - t0) * 1000
        if i >= warmup:
            samples.append(elapsed)

    res = BenchResult.from_samples(
        "flat_store.search_hybrid",
        samples,
        fail,
        extra={"top_k": 5, "n_chunks": int(len(flatstore.embeddings))},
        first_error=first_err,
    )
    print(res.pretty())
    save_result(res, SUITE)


async def test_flatstore_warm_search_dense(flatstore, n_runs, warmup):
    """Dense-only — used by SemanticCache + memory_router fallback path."""
    flatstore.load()
    if flatstore.embeddings is None or len(flatstore.embeddings) == 0:
        pytest.skip("FlatStore artifacts missing")

    samples: list[float] = []
    fail = 0
    first_err: str | None = None
    n_total = max(n_runs, len(QUERIES))
    for i in range(n_total + warmup):
        q, proj = QUERIES[i % len(QUERIES)]
        # Clear LRU query cache — repeated queries would otherwise return 0ms.
        flatstore.clear_cache()
        t0 = time.perf_counter()
        try:
            flatstore.search(q, project_filter=proj or "", top_k=5)
        except Exception as e:
            fail += 1
            if first_err is None:
                first_err = f"{type(e).__name__}: {e}"
            continue
        elapsed = (time.perf_counter() - t0) * 1000
        if i >= warmup:
            samples.append(elapsed)

    res = BenchResult.from_samples(
        "flat_store.search_dense",
        samples,
        fail,
        extra={"top_k": 5},
        first_error=first_err,
    )
    print(res.pretty())
    save_result(res, SUITE)


# ─── noble_kb (full path of `noble_search` tool) ─────────────────────────


async def test_noble_kb_query(n_runs, warmup):
    """End-to-end retrieval that the LLM actually triggers via tool call."""
    from noble_agent.agent.rag.noble_kb import query_noble_kb

    counter = {"i": 0}

    async def op():
        q, proj = QUERIES[counter["i"] % len(QUERIES)]
        counter["i"] += 1
        await query_noble_kb(q, proj)

    samples, failed, err = await run_async(op, n_runs, warmup)
    res = BenchResult.from_samples("noble_kb.query", samples, failed, first_error=err)
    print_section("noble_kb (full noble_search path)")
    print(res.pretty())
    save_result(res, SUITE)
