import numpy as np
import pytest

from noble_agent.agent.rag import qdrant_adapter as qa
from noble_agent.agent.rag.flat_store import Chunk


class _FakeEmbedder:
    def encode_query(self, q):
        return np.zeros(4, dtype=np.float32)


class _FakeStore:
    def __init__(self, chunks, sparse):
        self.chunks = chunks
        self.bm25_retriever = object()  # truthy → BM25 considered available
        self.embedder = _FakeEmbedder()
        self._sparse = sparse  # list[(local_index, score)]

    def _bm25_topk(self, query, project_filter, k):
        return self._sparse


@pytest.fixture(autouse=True)
def _reset():
    qa._store = None
    qa._warmed = False
    yield
    qa._store = None
    qa._warmed = False


async def test_rrf_fuses_dense_and_sparse(monkeypatch):
    chunks = [
        Chunk(id="a", project="NCLB", text="alpha"),
        Chunk(id="b", project="NCLB", text="beta"),
        Chunk(id="c", project="NCLB", text="gamma"),
    ]
    # sparse ranks c, then a (local indices 2, 0)
    store = _FakeStore(chunks, sparse=[(2, 5.0), (0, 1.0)])

    async def _ensure():
        return store

    monkeypatch.setattr(qa, "_ensure_local", _ensure)

    async def _dense(q_vec, pf, k):
        return [("a", "NCLB", "alpha", 0.9), ("b", "NCLB", "beta", 0.8)]

    monkeypatch.setattr("noble_agent.agent.rag.qdrant_store.search_dense", _dense)

    out = await qa.query_qdrant_for_noble_kb("q", "NCLB", top_k=3)
    # 'a' appears in BOTH lists → highest RRF → ranked first
    assert out.startswith("[Nguon 1 | Du an: NCLB")
    assert "alpha" in out
    assert "gamma" in out  # 'c' from sparse-only is fused in


async def test_fallback_to_bm25_only_on_qdrant_error(monkeypatch):
    chunks = [Chunk(id="a", project="NCLB", text="alpha")]
    store = _FakeStore(chunks, sparse=[(0, 3.0)])

    async def _ensure():
        return store

    monkeypatch.setattr(qa, "_ensure_local", _ensure)

    async def _boom(q_vec, pf, k):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("noble_agent.agent.rag.qdrant_store.search_dense", _boom)

    out = await qa.query_qdrant_for_noble_kb("q", "NCLB", top_k=3)
    assert "alpha" in out  # BM25-only still returns a result


async def test_empty_query_returns_empty(monkeypatch):
    out = await qa.query_qdrant_for_noble_kb("   ", "NCLB", top_k=3)
    assert out == ""
