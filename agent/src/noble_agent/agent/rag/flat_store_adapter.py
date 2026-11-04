"""FlatStore -> noble_kb output format adapter.

Bridges FlatStore.search_hybrid output to the text format returned by
MemoryRouter, so LLM prompts/tool-results remain consistent across backends.

Ported from voiceagentrag/src/agent/rag/flat_store_adapter.py (rev 3 step 5).
Only change: import path `agent.rag.flat_store` → `noble_agent.agent.rag.flat_store`.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

_store = None
_warmed = False


async def _ensure_flat_store():
    """Lazy-load FlatStore singleton. Warm on first call."""
    global _store, _warmed
    if _store is not None:
        if not _warmed:
            _store.embedder.encode_query("warmup")
            _warmed = True
        return _store
    from noble_agent.agent.rag.flat_store import FlatStore

    logger.info("[flat_store_adapter] loading FlatStore")
    s = FlatStore()
    s.load()
    try:
        s.load_bm25(build_if_missing=False)
        logger.info("[flat_store_adapter] BM25 index loaded")
    except Exception as exc:
        logger.warning("[flat_store_adapter] BM25 not available: %s -- dense-only", exc)
    s.embedder.encode_query("warmup")
    _store = s
    _warmed = True
    return _store


def _format_hits(hits, max_chars: int = 1200) -> str:
    """Format hits to match MemoryRouter output convention:
    [Nguon N | Du an: X | Diem: 0.YZ] <text>"""
    if not hits:
        return ""
    lines: list[str] = []
    for i, h in enumerate(hits, 1):
        chunk = getattr(h, "chunk", h)
        score = getattr(h, "score", 0.0)
        proj = getattr(chunk, "project", "?") or "?"
        text = (chunk.text or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        lines.append(f"[Nguon {i} | Du an: {proj} | Diem: {score:.2f}] {text}")
    return "\n\n".join(lines)


async def query_flat_store_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str:
    """Called by noble_kb.query_noble_kb when backend == flat_store."""
    s = await _ensure_flat_store()
    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return ""

    import asyncio

    loop = asyncio.get_event_loop()

    def _search():
        has_bm25 = getattr(s, "bm25_retriever", None) is not None
        if has_bm25:
            try:
                return s.search_hybrid(query, project_filter=project_filter, top_k=top_k)
            except Exception as exc:
                logger.warning("[flat_store_adapter] hybrid failed, dense: %s", exc)
        q_vec = s.embedder.encode_query(query)
        if project_filter and project_filter in s.project_idx:
            idx = s.project_idx[project_filter]
            scores = s.embeddings[idx] @ q_vec
            k = min(top_k, len(scores))
            top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(k)
            top = top[np.argsort(-scores[top])]
            from noble_agent.agent.rag.flat_store import SearchHit

            return [SearchHit(chunk=s.chunks[int(idx[i])], score=float(scores[i])) for i in top[:top_k]]
        scores = s.embeddings @ q_vec
        k = min(top_k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(k)
        top = top[np.argsort(-scores[top])]
        from noble_agent.agent.rag.flat_store import SearchHit

        return [SearchHit(chunk=s.chunks[int(i)], score=float(scores[i])) for i in top[:top_k]]

    hits = await loop.run_in_executor(None, _search)
    return _format_hits(hits)
