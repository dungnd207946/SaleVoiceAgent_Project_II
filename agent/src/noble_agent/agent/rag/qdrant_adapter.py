"""Qdrant hybrid entrypoint for noble_kb.

Happy path: embed query (remote e5) + sparse-encode query (local pyvi) → one
Qdrant Query-API request (dense+sparse prefetch → server-side RRF), pre-filtered
by project_id. On any Qdrant error → local disk BM25 fallback (sparse-only).
"""

from __future__ import annotations

import asyncio
import logging

from noble_agent.agent.rag import bm25_fallback, qdrant_store, sparse_encoder
from noble_agent.agent.rag.flat_store import Chunk, SearchHit
from noble_agent.agent.rag.flat_store_adapter import _format_hits
from noble_agent.config import settings

logger = logging.getLogger("rag.qdrant_adapter")

_embedder = None


def _embed_query(query: str) -> list[float]:
    """Dense query vector via the shared FlatStore embedder (remote-aware)."""
    global _embedder
    if _embedder is None:
        from noble_agent.agent.rag.flat_store import _Embedder

        _embedder = _Embedder()
    return _embedder.encode_query(query).tolist()


async def query_qdrant_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str:
    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return ""

    loop = asyncio.get_running_loop()
    try:
        dense = await loop.run_in_executor(None, _embed_query, query)
        s_idx, s_val = await loop.run_in_executor(None, sparse_encoder.encode_query, query)
        rows = await qdrant_store.search_hybrid(dense, s_idx, s_val, project_filter, top_k)
        hits = [SearchHit(chunk=Chunk(id=pid, project=proj, text=text), score=score) for pid, proj, text, score in rows]
        return _format_hits(hits)
    except Exception as exc:
        logger.warning("[qdrant_adapter] hybrid failed (%s) — local BM25 fallback", exc)
        hits = await loop.run_in_executor(
            None, bm25_fallback.search, query, project_filter, top_k, settings.qdrant_fallback_dir
        )
        return _format_hits(hits)
