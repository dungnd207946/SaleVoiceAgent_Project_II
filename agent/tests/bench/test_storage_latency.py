"""Storage round-trip latency: Redis / Qdrant.

What this measures:
  - Redis: ping, get/set scratch key
  - Qdrant: get_collections (HTTP keepalive), search top-K (vector workload)

Run from repo root, after `.env` is configured:
    pytest tests/bench/test_storage_latency.py -v -s -m bench

Lower runs (smoke):  BENCH_N_RUNS=20 pytest ...
Custom env label:    BENCH_ENV_LABEL=mac-home pytest ...

Result file: tests/bench/results/storage__<env>.jsonl  (append-only, JSONL)
"""

from __future__ import annotations

import os
import secrets

import numpy as np
import pytest

from tests.bench._helpers import (
    BenchResult,
    print_section,
    run_async,
    save_result,
)

pytestmark = [pytest.mark.bench, pytest.mark.asyncio(loop_scope="session")]

SUITE = "storage"


# ─── Redis ───────────────────────────────────────────────────────────────


@pytest.mark.needs_redis
async def test_redis_ping(n_runs, warmup):
    import redis.asyncio as aioredis

    client = aioredis.from_url(os.environ["REDIS_URL"], socket_timeout=5)

    async def op():
        await client.ping()

    samples, failed, err = await run_async(op, n_runs, warmup)
    await client.aclose()

    res = BenchResult.from_samples("redis.ping", samples, failed, first_error=err)
    print_section(f"Redis ping ({res.env_label})")
    print(res.pretty())
    save_result(res, SUITE)


@pytest.mark.needs_redis
async def test_redis_get_set(n_runs, warmup, bench_session_id):
    import redis.asyncio as aioredis

    client = aioredis.from_url(os.environ["REDIS_URL"], socket_timeout=5)
    key = f"bench:scratch:{bench_session_id}"
    payload = secrets.token_hex(64)

    async def op():
        await client.set(key, payload, ex=60)
        await client.get(key)

    samples, failed, err = await run_async(op, n_runs, warmup)
    await client.delete(key)
    await client.aclose()

    res = BenchResult.from_samples("redis.get_set", samples, failed, first_error=err)
    print(res.pretty())
    save_result(res, SUITE)


# ─── Qdrant ──────────────────────────────────────────────────────────────


@pytest.mark.needs_qdrant
async def test_qdrant_get_collections(n_runs, warmup):
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY"),
        timeout=10,
    )

    async def op():
        await client.get_collections()

    samples, failed, err = await run_async(op, n_runs, warmup)
    await client.close()

    res = BenchResult.from_samples("qdrant.get_collections", samples, failed, first_error=err)
    print_section(f"Qdrant ({res.env_label})")
    print(res.pretty())
    save_result(res, SUITE)


@pytest.mark.needs_qdrant
async def test_qdrant_search(n_runs, warmup):
    """Top-5 cosine search on the configured collection. Skips if collection
    missing (degraded backend) — measured against shared lightrag VDB."""
    from qdrant_client import AsyncQdrantClient

    coll_name = os.environ.get("QDRANT_COLLECTION", "lightrag_vdb_entities_baai_bge_m3_1024d")
    client = AsyncQdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY"),
        timeout=10,
    )

    # Probe collection — handle both unnamed and named-vector configs (LightRAG
    # collections often use named vectors, plain `search()` then needs a tuple).
    try:
        info = await client.get_collection(coll_name)
        vectors_cfg = info.config.params.vectors
        # vectors_cfg is either VectorParams (unnamed) or dict[str, VectorParams] (named)
        if isinstance(vectors_cfg, dict):
            vec_name, vp = next(iter(vectors_cfg.items()))
            dim = int(getattr(vp, "size", 0) or 1024)
        else:
            vec_name = None
            dim = int(getattr(vectors_cfg, "size", 0) or 1024)
    except Exception as e:
        await client.close()
        pytest.skip(f"collection {coll_name} unavailable: {e}")

    rng = np.random.default_rng(seed=42)
    qvec = rng.standard_normal(dim).astype(np.float32)
    qvec /= float(np.linalg.norm(qvec) or 1.0)
    qvec_list = qvec.tolist()

    # Use modern `query_points` API (qdrant-client >=1.10). `using=` selects the
    # named vector when collection has multiple; None falls back to unnamed.
    async def op():
        await client.query_points(
            collection_name=coll_name,
            query=qvec_list,
            using=vec_name,
            limit=5,
        )

    samples, failed, err = await run_async(op, n_runs, warmup)
    await client.close()

    res = BenchResult.from_samples(
        "qdrant.query_points_top5",
        samples,
        failed,
        extra={"collection": coll_name, "dim": int(dim), "vec_name": vec_name or ""},
        first_error=err,
    )
    print(res.pretty())
    save_result(res, SUITE)
