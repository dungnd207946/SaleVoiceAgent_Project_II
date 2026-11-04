"""RAG component eval — retrieval TÁCH KHỎI agent (spec §6).

Chỉ module này (trong evals/rag) import noble_agent. Mode `structured` mirror
kb_service_adapter nhưng trả hits thô (id/text) để chấm recall@k theo chunk id;
mode `agent-string` gọi query_noble_kb cho backend bất kỳ (evidence-match only).
KHÔNG truyền project filter ở structured: component eval đo tìm-đúng-chunk trên
toàn corpus tenant, khó hơn và có nghĩa hơn.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from evals.rag.golden import GoldenCase, ranks_of
from evals.rag.metrics import aggregate

SearchFn = Callable[[str, str], Awaitable[list[dict]]]


async def run_rag(golden: list[GoldenCase], *, search: SearchFn, top_k: int = 5) -> dict:
    rows: list[dict] = []
    per_case: list[list[int | None]] = []
    latencies: list[float] = []
    empty = 0
    for case in golden:
        t0 = time.perf_counter()
        error = ""
        try:
            hits = (await search(case.query, case.project_code))[:top_k]
        except Exception as exc:  # noqa: BLE001 — backend chết = case không đo được, không phải harness crash
            hits = []
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - t0) * 1000.0
        ranks = ranks_of(case, hits) if hits else [None] * len(case.chunks)
        if not hits:
            empty += 1
        per_case.append(ranks)
        latencies.append(latency_ms)
        rows.append(
            {
                "id": case.id,
                "ranks": ranks,
                "hit": any(r is not None for r in ranks),
                "latency_ms": latency_ms,
                "n_hits": len(hits),
                "retrieved": [str(h.get("text", "")) for h in hits],
                "error": error,
            }
        )
    metrics = aggregate(per_case, latencies)
    metrics["empty_rate"] = (empty / len(golden)) if golden else None
    if golden and empty / len(golden) > 0.5:
        print(
            f"CẢNH BÁO: {empty}/{len(golden)} case trả rỗng — backend degrade im lặng? "
            "(kiểm tra tunnel/collection/EMBED_BACKEND, xem CLAUDE.md gotchas)"
        )
    return {"rows": rows, "metrics": metrics}


async def search_structured(query: str, project_code: str, *, top_k: int = 5) -> list[dict]:  # noqa: ARG001
    """Qdrant hybrid như kb_service_adapter nhưng trả hits thô. Read-only.

    KHÔNG truyền project filter (component eval đo tìm-đúng-chunk trên toàn
    corpus tenant, xem module docstring) — `project_code` chỉ nằm trong chữ ký
    để khớp `SearchFn`.
    """
    import asyncio

    from noble_agent.config import settings
    from noble_agent.data import embed_client
    from noble_agent.data import qdrant_search as qdrant_client
    from noble_agent.tenant.current import current_tenant

    collection = qdrant_client.collection_name(current_tenant(), "documents")
    if not await qdrant_client.collection_exists(settings.qdrant_url, settings.qdrant_api_key, collection):
        return []

    dense_vecs, sparse_vecs = await asyncio.gather(
        embed_client.embed_dense([query], side="query"),
        embed_client.embed_sparse([query], side="query"),
    )
    if not dense_vecs or not sparse_vecs:
        return []
    sparse = sparse_vecs[0]

    return await qdrant_client.search_hybrid(
        base_url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection=collection,
        prefetches=[
            qdrant_client.DensePrefetch("dense", dense_vecs[0]),
            qdrant_client.SparsePrefetch("bm25", sparse.get("indices", []), sparse.get("values", [])),
        ],
        limit=top_k,
    )


async def search_agent_string(query: str, project_code: str, *, top_k: int = 5) -> list[dict]:  # noqa: ARG001
    from noble_agent.agent.rag.noble_kb import query_noble_kb

    context = await query_noble_kb(query, project_code)
    return [{"id": "", "text": context}] if context else []
