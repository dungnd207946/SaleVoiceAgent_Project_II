"""Head-to-head: FlatStore (in-process) vs Qdrant (cloud) for the same queries.

This validates (or refutes) the claim that pushing FlatStore embeddings to
Qdrant would hurt RAG latency. Both paths share:
  - Same e5-large encoder (in-process, ~5-10ms warm)
  - Same chunk corpus (Qdrant collection seeded from FlatStore.embeddings)
  - Same top-K = 5

Differences measured:
  - Local: encode + numpy `embeddings @ q_vec` (no network)
  - Cloud: encode + Qdrant.query_points (1 RTT VN→SG ~40ms p50)

Setup (run ONCE, idempotent):
    python -m scripts.bench.seed_qdrant_flatstore

Run:
    pytest tests/bench/test_compare_flatstore_qdrant.py -v -s -m bench

Result: tests/bench/results/compare__<env>.jsonl  +  printed diff at end
"""

from __future__ import annotations

import os
import time

import pytest

from tests.bench._helpers import (
    BenchResult,
    print_section,
    save_result,
)

pytestmark = [
    pytest.mark.bench,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.needs_qdrant,
]

SUITE = "compare"
QDRANT_COLLECTION = "noble_flat_compare"

QUERIES = [
    ("Noble Crystal Long Biên có bao nhiêu căn hộ?", "NCLB"),
    ("Tiện ích Noble Crystal Tây Hồ là gì?", "NCTH"),
    ("Pháp lý Noble Palace Long Biên thế nào", "NPLB"),
    ("Noble Palace Tây Thăng Long có bể bơi không?", "NTTL"),
    ("Sunshine Legend City vị trí ở đâu", "SSLC"),
    ("Giá căn hai phòng ngủ Tây Hồ bao nhiêu", ""),
    ("So sánh Noble Crystal Long Biên và Tây Hồ", ""),
    ("Dự án nào gần trung tâm nhất", ""),
    ("Noble có chính sách trả góp không", ""),
    ("Bàn giao thô hay full nội thất", ""),
]


# Module-scoped: load FlatStore once, share across both tests.
@pytest.fixture(scope="module")
def flatstore():
    from noble_agent.agent.rag.flat_store import FlatStore

    s = FlatStore()
    s.load()
    if s.embeddings is None or len(s.embeddings) == 0:
        pytest.skip("FlatStore artifacts missing — run setup first")
    return s


# ─── 1. Local FlatStore (dense, no BM25 — pure apples-to-apples) ─────────


async def test_local_flatstore_dense(flatstore, n_runs, warmup):
    """Same backend Qdrant uses (cosine over numpy vectors).

    Cache cleared between iterations: FlatStore.search() has an LRU query cache
    that returns 0ms on repeat queries. Without this, p50 reads as 0ms and
    misrepresents the cold-path cost vs the cloud (which has no local cache).
    """
    samples: list[float] = []
    fail = 0
    first_err = None
    for i in range(n_runs + warmup):
        q, proj = QUERIES[i % len(QUERIES)]
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
        "compare.flat_store_local_dense",
        samples,
        fail,
        extra={"top_k": 5, "n_chunks": int(len(flatstore.embeddings))},
        first_error=first_err,
    )
    print_section("FlatStore vs Qdrant — same queries, same encoder")
    print(res.pretty())
    save_result(res, SUITE)


# ─── 2. Cloud Qdrant (encode locally + 1 RTT to EC2) ─────────────────────


async def test_cloud_qdrant_dense(flatstore, n_runs, warmup):
    """Encode query locally (same e5-large), search via Qdrant cloud."""
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    qurl = os.environ["QDRANT_URL"]
    client = AsyncQdrantClient(url=qurl, api_key=os.environ.get("QDRANT_API_KEY"), timeout=10)

    # Confirm collection seeded (gives clear error if user forgot setup step)
    try:
        info = await client.get_collection(QDRANT_COLLECTION)
        if not info.points_count:
            await client.close()
            pytest.skip(f"{QDRANT_COLLECTION} empty — run scripts/bench/seed_qdrant_flatstore.py")
    except Exception as e:
        await client.close()
        pytest.skip(f"{QDRANT_COLLECTION} missing: {e}")

    samples: list[float] = []
    fail = 0
    first_err = None
    for i in range(n_runs + warmup):
        q, proj = QUERIES[i % len(QUERIES)]
        t0 = time.perf_counter()
        try:
            qvec = flatstore.embedder.encode_query(q)
            qfilter = Filter(must=[FieldCondition(key="project", match=MatchValue(value=proj))]) if proj else None
            await client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=qvec.tolist(),
                query_filter=qfilter,
                limit=5,
            )
        except Exception as e:
            fail += 1
            if first_err is None:
                first_err = f"{type(e).__name__}: {e}"
            continue
        elapsed = (time.perf_counter() - t0) * 1000
        if i >= warmup:
            samples.append(elapsed)

    await client.close()
    res = BenchResult.from_samples(
        "compare.flat_store_qdrant_cloud",
        samples,
        fail,
        extra={"top_k": 5, "collection": QDRANT_COLLECTION},
        first_error=first_err,
    )
    print(res.pretty())
    save_result(res, SUITE)


# ─── 3. Local hybrid (BM25 + dense RRF) — what production ACTUALLY uses ──


async def test_local_flatstore_hybrid(flatstore, n_runs, warmup):
    """Reference baseline — full noble_search retrieval cost."""
    samples: list[float] = []
    fail = 0
    first_err = None
    for i in range(n_runs + warmup):
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
        "compare.flat_store_local_hybrid",
        samples,
        fail,
        extra={"top_k": 5, "with_bm25": True},
        first_error=first_err,
    )
    print(res.pretty())
    save_result(res, SUITE)
