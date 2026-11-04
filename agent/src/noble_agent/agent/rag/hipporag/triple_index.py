"""Triple-embedding index for the HippoRAG sparse triple-seed (HippoRAG 2 style).

At BUILD time the builder embeds every extracted triple as text ("subject
relation object") and stores the matrix in a numpy sidecar next to the graph
JSON, aligned with the two phrase-node keys (subject, object) of each triple. At
QUERY time (only when ``HIPPORAG_SPARSE_SEED_ENABLED``) the expander cosine-
matches the query vector against these triples and seeds PPR at BOTH phrase nodes
of the top triples — the relational HippoRAG 2 sparse seed, kept LLM-free (cosine
only, no recognition-memory LLM step).

Sidecar path is derived from the graph path: ``<stem>.triple_emb.npz``.
"""

from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger("rag.hipporag.triple_index")


class TripleIndex:
    def __init__(self, s_keys: list[str], o_keys: list[str], emb: np.ndarray) -> None:
        self.s_keys = list(s_keys)
        self.o_keys = list(o_keys)
        emb = np.asarray(emb, dtype=np.float32)
        if emb.ndim != 2 or emb.shape[0] == 0:
            self.emb = np.zeros((0, emb.shape[1] if emb.ndim == 2 else 0), dtype=np.float32)
        else:
            norms = np.linalg.norm(emb, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self.emb = (emb / norms).astype(np.float32)

    def search(self, query_vec, top_m: int = 5) -> list[tuple[str, str, float]]:
        """Return the top-M (subject_key, object_key, cosine) for the query."""
        if self.emb.shape[0] == 0 or top_m <= 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        n = float(np.linalg.norm(q))
        if n == 0.0:
            return []
        q = q / n
        scores = self.emb @ q
        m = min(top_m, scores.shape[0])
        idx = np.argpartition(-scores, m - 1)[:m] if m < scores.shape[0] else np.arange(scores.shape[0])
        idx = idx[np.argsort(-scores[idx])]
        return [(self.s_keys[int(i)], self.o_keys[int(i)], float(scores[int(i)])) for i in idx[:top_m]]


def triple_emb_path(graph_path: str) -> str:
    return os.path.splitext(graph_path)[0] + ".triple_emb.npz"


def save_triple_index(graph_path: str, s_keys: list[str], o_keys: list[str], emb: np.ndarray) -> None:
    p = triple_emb_path(graph_path)
    os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
    np.savez(
        p,
        s_keys=np.array(s_keys, dtype=object),
        o_keys=np.array(o_keys, dtype=object),
        emb=np.asarray(emb, dtype=np.float32),
    )


def load_triple_index(graph_path: str) -> TripleIndex | None:
    p = triple_emb_path(graph_path)
    if not os.path.isfile(p):
        return None
    try:
        d = np.load(p, allow_pickle=True)
        return TripleIndex([str(k) for k in d["s_keys"]], [str(k) for k in d["o_keys"]], d["emb"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.triple_index] load failed at %s: %s", p, exc)
        return None
