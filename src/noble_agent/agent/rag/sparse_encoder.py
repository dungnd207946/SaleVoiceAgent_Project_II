"""Stateless BM25 sparse-vector encoder for Qdrant (pyvi tokenization).

Document weights use a FIXED avgdl so a chunk's sparse vector depends only on
its own text (never stale vs the corpus). IDF is applied by Qdrant at query
time via SparseVectorParams(modifier=Modifier.IDF) — NOT here.

Term ids are a process-stable blake2b hash of the token (never builtin hash()).
"""

from __future__ import annotations

import hashlib
from collections import Counter

from noble_agent.agent.rag.flat_store import _tokenize_vi

AVGDL = 256.0
K1 = 1.5
B = 0.75


def _term_id(token: str) -> int:
    """Stable uint32 id for a token (deterministic across processes/runs)."""
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(), "big")


def encode_document(text: str) -> tuple[list[int], list[float]]:
    """BM25 document-side sparse weights with fixed avgdl. Returns (indices, values)."""
    tokens = _tokenize_vi(text or "")
    if not tokens:
        return [], []
    dl = len(tokens)
    tf: Counter[int] = Counter(_term_id(t) for t in tokens)
    norm = K1 * (1.0 - B + B * dl / AVGDL)
    indices: list[int] = []
    values: list[float] = []
    for tid, f in tf.items():
        indices.append(tid)
        values.append(f * (K1 + 1.0) / (f + norm))
    return indices, values


def encode_query(text: str) -> tuple[list[int], list[float]]:
    """Query-side sparse weights: 1.0 per unique term (IDF applied by Qdrant)."""
    tokens = _tokenize_vi(text or "")
    if not tokens:
        return [], []
    uniq = list(dict.fromkeys(_term_id(t) for t in tokens))
    return uniq, [1.0] * len(uniq)
