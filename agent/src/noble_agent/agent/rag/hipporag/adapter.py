"""HippoRAG backend entrypoint for noble_kb.

Query path (NO LLM):
  1. hybrid search on the Qdrant clone → seed passages (id, project, text, score)
  2. Personalized PageRank over the loaded graph, seeded at those passages
  3. RRF-fuse the PPR ranking with the hybrid ranking (keep hybrid precision,
     add graph recall)
  4. format via the shared _format_hits

Degrades to the plain hybrid result whenever the graph artifact is missing or
anything in the graph path fails — so enabling ``hipporag`` can never do worse
than ``qdrant``.
"""

from __future__ import annotations

import asyncio
import logging

from noble_agent.agent.rag.flat_store import Chunk, SearchHit
from noble_agent.agent.rag.flat_store_adapter import _format_hits
from noble_agent.agent.rag.hipporag import expander
from noble_agent.config import settings

logger = logging.getLogger("rag.hipporag.adapter")

_RRF_K = 60


def _rrf_fuse(
    hybrid_rows: list[tuple[str, str, str, float]],
    ppr_rows: list[tuple[str, float, str, str]],
) -> list[tuple[str, str, str, float]]:
    """Reciprocal-rank fusion of the hybrid list and the PPR list.

    ``hybrid_rows`` = [(id, project, text, score)] (already rank-ordered).
    ``ppr_rows``    = [(id, ppr_score, project, text)] (already rank-ordered).
    Returns [(id, project, text, fused_score)] sorted by fused score desc.
    """
    meta: dict[str, tuple[str, str]] = {}
    fused: dict[str, float] = {}

    for rank, (pid, proj, text, _score) in enumerate(hybrid_rows):
        meta.setdefault(pid, (proj, text))
        fused[pid] = fused.get(pid, 0.0) + 1.0 / (_RRF_K + rank + 1)
    for rank, (pid, _pscore, proj, text) in enumerate(ppr_rows):
        meta.setdefault(pid, (proj, text))
        fused[pid] = fused.get(pid, 0.0) + 1.0 / (_RRF_K + rank + 1)

    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return [(pid, meta[pid][0], meta[pid][1], score) for pid, score in ordered]


def _rows_to_hits(rows: list[tuple[str, str, str, float]]) -> list[SearchHit]:
    return [SearchHit(chunk=Chunk(id=pid, project=proj, text=text), score=sc) for pid, proj, text, sc in rows]


async def _hybrid_rows(query: str, project_filter: str, k: int) -> list[tuple[str, str, str, float]]:
    """Raw hybrid hits from the Qdrant clone (no formatting) — the DENSE seed
    source. Factored out so tests can stub it."""
    from noble_agent.agent.rag import qdrant_store, sparse_encoder
    from noble_agent.agent.rag.qdrant_adapter import _embed_query

    loop = asyncio.get_running_loop()
    dense = await loop.run_in_executor(None, _embed_query, query)
    s_idx, s_val = await loop.run_in_executor(None, sparse_encoder.encode_query, query)
    return await qdrant_store.search_hybrid(dense, s_idx, s_val, project_filter, k)


async def _sparse_seed(query: str, top_m: int) -> dict[str, float]:
    """The SPARSE triple-seed (HippoRAG 2): embed the query and cosine-match against
    the stored TRIPLE embeddings ("subject relation object"); the top triples seed
    PPR at BOTH their phrase nodes → {phrase_key: score}. Runs concurrently with the
    hybrid search (own embed; the two overlap so wall-clock is unaffected).

    Source cascade when HIPPORAG_TRIPLE_STORE="qdrant": Qdrant triple collection →
    (on Qdrant error OR empty result) local npz index → (both empty) {} so
    sparse-seed simply no-ops. An empty (non-error) Qdrant result means the
    collection was dropped mid-sync, so the local npz stays a hot standby.
    Default "local" reads only the npz index, restoring the no-embed short-circuit
    when that index is absent (output-equivalent to the pre-cascade code)."""
    from noble_agent.agent.rag.qdrant_adapter import _embed_query

    loop = asyncio.get_running_loop()
    triples: list[tuple[str, str, float]] = []
    if settings.hipporag_triple_store == "qdrant":
        dense = await loop.run_in_executor(None, _embed_query, query)
        from noble_agent.agent.rag import qdrant_store

        try:
            triples = await qdrant_store.search_triples(dense, top_m)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hipporag.adapter] qdrant triple search failed (%s) — local fallback", exc)
        if not triples:  # error OR empty (collection dropped mid-sync) → local npz hot standby
            idx = expander.load_triple_index()
            if idx is not None:
                triples = await loop.run_in_executor(None, idx.search, dense, top_m)
    else:
        idx = expander.load_triple_index()
        if idx is None:
            return {}
        dense = await loop.run_in_executor(None, _embed_query, query)
        triples = await loop.run_in_executor(None, idx.search, dense, top_m)

    seeds: dict[str, float] = {}
    for s_key, o_key, score in triples:
        if score <= 0:
            continue
        for key in (s_key, o_key):
            if key:
                seeds[key] = max(seeds.get(key, 0.0), score)
    return seeds


async def query_hipporag_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str:
    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return ""

    graph = expander.load()
    seed_k = max(settings.hipporag_seed_k, top_k)
    sparse_on = graph is not None and settings.hipporag_sparse_seed_enabled
    phrase_seeds: dict[str, float] = {}

    try:
        if sparse_on:
            # dense (hybrid) + sparse (phrase cosine) seed discovery IN PARALLEL
            hybrid_rows, phrase_seeds = await asyncio.gather(
                _hybrid_rows(query, project_filter, seed_k),
                _sparse_seed(query, settings.hipporag_sparse_seed_top_m),
            )
        else:
            hybrid_rows = await _hybrid_rows(query, project_filter, seed_k)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.adapter] seed discovery failed (%s) — qdrant fallback", exc)
        from noble_agent.agent.rag.qdrant_adapter import query_qdrant_for_noble_kb

        return await query_qdrant_for_noble_kb(query, project_filter, top_k)

    if graph is None or not hybrid_rows:
        # no graph → behave exactly like the qdrant backend
        return _format_hits(_rows_to_hits(hybrid_rows[:top_k]))

    loop = asyncio.get_running_loop()
    ppr_rows = await loop.run_in_executor(
        None,
        lambda: expander.expand(
            graph,
            hybrid_rows,
            alpha=settings.hipporag_ppr_alpha,
            iters=settings.hipporag_ppr_iters,
            seed_k=settings.hipporag_seed_k,
            top_k=max(top_k * 2, top_k),
            project_filter=project_filter,
            extra_seeds=phrase_seeds,
            sparse_weight=settings.hipporag_sparse_seed_weight if sparse_on else 0.0,
            passage_threshold=settings.hipporag_passage_seed_threshold,
            phrase_threshold=settings.hipporag_phrase_seed_threshold,
        ),
    )
    if not ppr_rows:
        return _format_hits(_rows_to_hits(hybrid_rows[:top_k]))

    fused = _rrf_fuse(hybrid_rows, ppr_rows)
    if project_filter:
        # guard: never let a cross-project passage leak into a project-scoped answer
        fused = [row for row in fused if row[1] == project_filter]
    hits = _rows_to_hits(fused[:top_k])
    logger.info(
        "[hipporag.adapter] fused %d hybrid + %d ppr → %d (project=%s)",
        len(hybrid_rows),
        len(ppr_rows),
        len(hits),
        project_filter or "ALL",
    )
    return _format_hits(hits)
