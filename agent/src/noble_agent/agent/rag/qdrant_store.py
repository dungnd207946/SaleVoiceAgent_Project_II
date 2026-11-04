"""Qdrant hybrid retrieval on the app-owned CLONE collection.

Clone stores a named dense vector + a named BM25 sparse vector (IDF applied by
Qdrant). Search fuses both server-side via the Query API (RRF), pre-filtered by
project_id. Also exposes the clone (re)build helpers used by sparse_reconcile.

qdrant-client is imported lazily (optional extra `rag-qdrant`).
"""

from __future__ import annotations

import contextlib
import logging

from noble_agent.config import settings

logger = logging.getLogger("rag.qdrant_store")

_client = None  # AsyncQdrantClient singleton


def _get_client():
    global _client
    if _client is not None:
        return _client
    from qdrant_client import AsyncQdrantClient

    _client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    logger.info("[qdrant_store] client → %s", settings.qdrant_url)
    return _client


def _project_filter(project_filter: str):
    if not project_filter:
        return None
    from qdrant_client import models

    return models.Filter(must=[models.FieldCondition(key="project_id", match=models.MatchValue(value=project_filter))])


async def search_hybrid(
    dense_vec: list[float],
    sparse_idx: list[int],
    sparse_val: list[float],
    project_filter: str,
    top_k: int,
) -> list[tuple[str, str, str, float]]:
    """Dense + sparse prefetch → server-side RRF fusion. Returns [(id, project_id, text, score)]."""
    from qdrant_client import models

    client = _get_client()
    flt = _project_filter(project_filter)
    candidates = max(top_k * 4, 20)
    resp = await client.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            models.Prefetch(
                query=dense_vec,
                using=settings.qdrant_dense_vector_name,
                limit=candidates,
                filter=flt,
            ),
            models.Prefetch(
                query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                using=settings.qdrant_sparse_vector_name,
                limit=candidates,
                filter=flt,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
        query_filter=flt,
        with_payload=True,
    )
    out: list[tuple[str, str, str, float]] = []
    for p in resp.points:
        pl = p.payload or {}
        out.append((str(p.id), pl.get("project_id", "?"), pl.get("text", ""), float(p.score)))
    return out


async def get_root_dense_params() -> tuple[int, object]:
    """Read (dim, distance) from the root collection's dense vector config."""
    client = _get_client()
    info = await client.get_collection(settings.qdrant_collection_root)
    vectors = info.config.params.vectors
    params = next(iter(vectors.values())) if isinstance(vectors, dict) else vectors
    return int(params.size), params.distance


async def recreate_clone(dim: int, distance) -> None:
    """Drop + create the clone with named dense + IDF sparse + project_id index."""
    from qdrant_client import models

    client = _get_client()
    coll = settings.qdrant_collection
    if await client.collection_exists(coll):
        await client.delete_collection(coll)
    await client.create_collection(
        collection_name=coll,
        vectors_config={settings.qdrant_dense_vector_name: models.VectorParams(size=dim, distance=distance)},
        sparse_vectors_config={
            settings.qdrant_sparse_vector_name: models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    await client.create_payload_index(coll, field_name="project_id", field_schema=models.PayloadSchemaType.KEYWORD)
    logger.info("[qdrant_store] recreated clone %s (dim=%d)", coll, dim)


async def iter_root_points(batch: int = 256):
    """Yield (point_id, dense_list, payload) from the root collection."""
    client = _get_client()
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=settings.qdrant_collection_root,
            with_vectors=True,
            with_payload=True,
            limit=batch,
            offset=offset,
        )
        for p in points:
            vec = p.vector
            if isinstance(vec, dict):
                vec = next(iter(vec.values()))
            if vec is None:
                continue
            yield p.id, list(vec), (p.payload or {})
        if offset is None:
            break


async def iter_clone_points(batch: int = 256):
    """Yield (point_id, payload) from the app-owned CLONE collection (payload
    carries content_hash / text / project_id). Used by the HippoRAG graph
    builder — vectors are not needed, so they are not fetched."""
    client = _get_client()
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=settings.qdrant_collection,
            with_vectors=False,
            with_payload=True,
            limit=batch,
            offset=offset,
        )
        for p in points:
            yield p.id, (p.payload or {})
        if offset is None:
            break


async def upsert_clone_points(points: list) -> None:
    """Upsert prepared PointStructs into the clone."""
    client = _get_client()
    await client.upsert(collection_name=settings.qdrant_collection, points=points)


async def recreate_triple_collection(dim: int) -> None:
    """Drop + create the HippoRAG triple collection: one unnamed dense vector,
    Cosine distance (≡ the normalised dot-product TripleIndex uses). Dense-only,
    no sparse, no payload index."""
    from qdrant_client import models

    client = _get_client()
    coll = settings.qdrant_triple_collection
    if await client.collection_exists(coll):
        await client.delete_collection(coll)
    await client.create_collection(
        collection_name=coll,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    logger.info("[qdrant_store] recreated triple collection %s (dim=%d)", coll, dim)


async def upsert_triples(points: list) -> None:
    """Upsert prepared PointStructs into the triple collection."""
    client = _get_client()
    await client.upsert(collection_name=settings.qdrant_triple_collection, points=points)


async def search_triples(query_vec, top_m: int) -> list[tuple[str, str, float]]:
    """Dense search on the triple collection. Returns [(s_key, o_key, score)].
    Raises on Qdrant error / missing collection so the caller can fall back to the
    local npz index."""
    client = _get_client()
    resp = await client.query_points(
        collection_name=settings.qdrant_triple_collection,
        query=query_vec,
        limit=top_m,
        with_payload=True,
    )
    out: list[tuple[str, str, float]] = []
    for p in resp.points:
        pl = p.payload or {}
        out.append((str(pl.get("s", "")), str(pl.get("o", "")), float(p.score)))
    return out


async def close() -> None:
    global _client
    if _client is not None:
        with contextlib.suppress(Exception):
            await _client.close()
        _client = None
