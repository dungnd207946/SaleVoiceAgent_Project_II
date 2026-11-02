"""Singleton FlatStore wrapper — load once, warmup, provide async noble_search handler."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

logger = logging.getLogger(__name__)

_store = None
_warmed = False
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_flat_store():
    global _store
    if _store is not None:
        return _store
    async with _get_lock():
        if _store is not None:
            return _store
        from noble_agent.agent.rag.flat_store import FlatStore

        logger.info("[RAG] Loading FlatStore...")
        s = FlatStore()
        s.load()
        try:
            s.load_bm25(build_if_missing=False)
            logger.info("[RAG] BM25 index loaded")
        except Exception as exc:
            logger.warning("[RAG] BM25 not loaded (%s) — dense-only fallback", exc)
        _store = s
        return _store


async def ensure_warmed_up() -> None:
    global _warmed
    if _warmed:
        return
    s = await get_flat_store()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: s.embedder.encode_query("warmup"))
    _warmed = True
    logger.info("[RAG] Warmup done")


def _format_hits(hits, max_text: int = 400) -> str:
    """Format hit list as text the LLM can consume. Mirrors production noble_kb format_hits style."""
    if not hits:
        return "Không tìm thấy thông tin liên quan."
    lines = [f"Tìm thấy {len(hits)} đoạn thông tin liên quan:\n"]
    for i, h in enumerate(hits, 1):
        chunk = getattr(h, "chunk", h)  # SearchHit or Chunk
        score = getattr(h, "score", None)
        text = chunk.text[:max_text] + ("…" if len(chunk.text) > max_text else "")
        proj = chunk.project or "?"
        score_str = f" [{score:.3f}]" if score is not None else ""
        lines.append(f"{i}. [{proj}]{score_str}\n{text}")
    return "\n\n".join(lines)


async def real_noble_search(args: dict) -> str:
    s = await get_flat_store()
    await ensure_warmed_up()
    query = (args.get("query") or "").strip()
    project = (args.get("project_filter") or "").strip()

    if not query:
        return "Câu truy vấn rỗng."

    loop = asyncio.get_event_loop()

    def _search():
        has_bm25 = getattr(s, "bm25_retriever", None) is not None
        if has_bm25:
            try:
                return s.search_hybrid(query, project_filter=project, top_k=5)
            except Exception as exc:
                logger.warning("[RAG] search_hybrid failed (%s) — fallback dense", exc)
        # dense-only fallback
        q_vec = s.embedder.encode_query(query)
        if project and project in s.project_idx:
            idx = s.project_idx[project]
            scores = s.embeddings[idx] @ q_vec
            k = min(5, len(scores))
            top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(k)
            top = top[np.argsort(-scores[top])]
            from noble_agent.agent.rag.flat_store import SearchHit

            return [SearchHit(chunk=s.chunks[int(idx[i])], score=float(scores[i])) for i in top[:5]]
        else:
            scores = s.embeddings @ q_vec
            k = min(5, len(scores))
            top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(k)
            top = top[np.argsort(-scores[top])]
            from noble_agent.agent.rag.flat_store import SearchHit

            return [SearchHit(chunk=s.chunks[int(i)], score=float(scores[i])) for i in top[:5]]

    hits = await loop.run_in_executor(None, _search)
    return _format_hits(hits)


async def shutdown_flat_store() -> None:
    global _store, _warmed
    _store = None
    _warmed = False
