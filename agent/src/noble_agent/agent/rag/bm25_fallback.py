"""Disk-persisted local BM25 fallback for the Qdrant hybrid path.

Built by sparse_reconcile from the SAME root snapshot pushed to Qdrant, so the
fallback describes the same corpus. Used only when the Qdrant query errors.
"""

from __future__ import annotations

import json
import logging
import os

import bm25s

from noble_agent.agent.rag.flat_store import Chunk, SearchHit, _tokenize_vi

logger = logging.getLogger("rag.bm25_fallback")

_CHUNKS_FILE = "chunks.json"

# process-level cache: out_dir -> (retriever, chunks)
_cache: dict[str, tuple[object, list[Chunk]]] = {}


def reset_cache() -> None:
    _cache.clear()


def build(chunks: list[Chunk], out_dir: str) -> None:
    """Index chunks with bm25s and persist index + chunk metadata to out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    tokenized = [_tokenize_vi(c.text) for c in chunks]
    retriever = bm25s.BM25(method="lucene")
    retriever.index(tokenized)
    retriever.save(os.path.join(out_dir, "index"))
    with open(os.path.join(out_dir, _CHUNKS_FILE), "w", encoding="utf-8") as fh:
        json.dump([{"id": c.id, "project": c.project, "text": c.text} for c in chunks], fh, ensure_ascii=False)
    _cache.pop(out_dir, None)
    logger.info("[bm25_fallback] built %d chunks → %s", len(chunks), out_dir)


def _load(out_dir: str) -> tuple[object, list[Chunk]]:
    cached = _cache.get(out_dir)
    if cached is not None:
        return cached
    retriever = bm25s.BM25.load(os.path.join(out_dir, "index"))
    with open(os.path.join(out_dir, _CHUNKS_FILE), encoding="utf-8") as fh:
        rows = json.load(fh)
    chunks = [Chunk(id=r["id"], project=r["project"], text=r["text"]) for r in rows]
    _cache[out_dir] = (retriever, chunks)
    logger.info("[bm25_fallback] loaded %d chunks from %s", len(chunks), out_dir)
    return retriever, chunks


def search(query: str, project_filter: str, top_k: int, out_dir: str) -> list[SearchHit]:
    """BM25-only search, post-filtered by project. Returns [] if artifact missing."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        retriever, chunks = _load(out_dir)
    except Exception as exc:
        logger.warning("[bm25_fallback] load failed (%s) — no fallback available", exc)
        return []
    over_k = min(top_k * 10 if project_filter else top_k, len(chunks))
    if over_k <= 0:
        return []
    q_tokens = _tokenize_vi(query)
    ids_arr, scores_arr = retriever.retrieve([q_tokens], k=over_k)
    ids = ids_arr[0].tolist()
    scores = scores_arr[0].tolist()
    hits: list[SearchHit] = []
    for i, s in zip(ids, scores, strict=False):
        ch = chunks[int(i)]
        if project_filter and ch.project != project_filter:
            continue
        hits.append(SearchHit(chunk=ch, score=float(s)))
        if len(hits) >= top_k:
            break
    return hits
