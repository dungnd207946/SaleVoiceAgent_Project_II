"""Tests for the HippoRAG noble_kb adapter (RRF fuse + degrade path)."""

from __future__ import annotations

from noble_agent.agent.rag.hipporag import adapter, expander
from noble_agent.agent.rag.hipporag.graph import HippoGraph


def test_rrf_fuse_combines_both_lists():
    hybrid = [("p1", "NCTH", "t1", 0.9), ("p2", "NCTH", "t2", 0.5)]
    ppr = [("p2", 0.8, "NCTH", "t2"), ("p3", 0.4, "SGR", "t3")]
    fused = adapter._rrf_fuse(hybrid, ppr)
    ids = [pid for pid, _p, _t, _s in fused]
    assert set(ids) == {"p1", "p2", "p3"}
    # p2 appears in both lists near the top → should outrank the singletons
    assert ids[0] == "p2"


def _graph():
    g = HippoGraph()
    g.add_passage("p1", "Noble Crystal tổng quan", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "Noble Crystal bể bơi", "NCTH", "h2", [("Noble Crystal", "có", "bể bơi")])
    return g


async def test_query_fuses_when_graph_present(monkeypatch):
    async def fake_rows(query, project_filter, k):
        return [("p1", "NCTH", "Noble Crystal tổng quan", 0.9)]

    monkeypatch.setattr(adapter, "_hybrid_rows", fake_rows)
    monkeypatch.setattr(expander, "load", lambda: _graph())

    out = await adapter.query_hipporag_for_noble_kb("bể bơi tây hồ", "NCTH", top_k=5)
    assert "Noble Crystal" in out
    assert out.startswith("[Nguon 1")  # shared _format_hits shape
    # PPR pulled p2 (co-entity) in alongside the seed p1
    assert "bể bơi" in out


async def test_query_degrades_to_hybrid_when_no_graph(monkeypatch):
    async def fake_rows(query, project_filter, k):
        return [("p1", "NCTH", "chỉ hybrid", 0.9)]

    monkeypatch.setattr(adapter, "_hybrid_rows", fake_rows)
    monkeypatch.setattr(expander, "load", lambda: None)

    out = await adapter.query_hipporag_for_noble_kb("q", "NCTH", top_k=5)
    assert "chỉ hybrid" in out
    assert out.startswith("[Nguon 1")


async def test_query_scopes_output_to_project_filter(monkeypatch):
    g = HippoGraph()
    g.add_passage("p1", "Noble Crystal Tây Hồ", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "Sun Grand Tây Hồ", "SGR", "h2", [("Sun Grand", "ở", "Tây Hồ")])

    async def fake_rows(query, project_filter, k):
        return [("p1", "NCTH", "Noble Crystal Tây Hồ", 0.9)]

    monkeypatch.setattr(adapter, "_hybrid_rows", fake_rows)
    monkeypatch.setattr(expander, "load", lambda: g)

    out = await adapter.query_hipporag_for_noble_kb("tây hồ", "NCTH", top_k=5)
    assert "Noble Crystal" in out
    assert "Sun Grand" not in out  # cross-project passage never leaks when scoped


def _disjoint_graph():
    g = HippoGraph()
    g.add_passage("p1", "tổng quan Noble", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "tiện ích bể bơi", "NCTH", "h2", [("dự án X", "có", "bể bơi")])
    return g


async def test_query_sparse_seed_influences_output_when_enabled(monkeypatch):
    g = _disjoint_graph()
    bo_key = g._phrase_key("bể bơi")

    async def fake_rows(query, project_filter, k):
        return [("p1", "NCTH", "tổng quan Noble", 0.9)]

    async def fake_sparse(query, top_m):
        return {bo_key: 1.0}

    monkeypatch.setattr(adapter, "_hybrid_rows", fake_rows)
    monkeypatch.setattr(adapter, "_sparse_seed", fake_sparse)
    monkeypatch.setattr(expander, "load", lambda: g)
    monkeypatch.setattr(adapter.settings, "hipporag_sparse_seed_enabled", True)
    monkeypatch.setattr(adapter.settings, "hipporag_sparse_seed_weight", 0.5)

    out = await adapter.query_hipporag_for_noble_kb("bể bơi", "NCTH", top_k=5)
    assert "tiện ích bể bơi" in out  # p2 surfaced only via the sparse triple-seed


async def test_query_sparse_seed_off_by_default(monkeypatch):
    g = _disjoint_graph()
    bo_key = g._phrase_key("bể bơi")
    called = {"sparse": False}

    async def fake_rows(query, project_filter, k):
        return [("p1", "NCTH", "tổng quan Noble", 0.9)]

    async def fake_sparse(query, top_m):
        called["sparse"] = True
        return {bo_key: 1.0}

    monkeypatch.setattr(adapter, "_hybrid_rows", fake_rows)
    monkeypatch.setattr(adapter, "_sparse_seed", fake_sparse)
    monkeypatch.setattr(expander, "load", lambda: g)
    monkeypatch.setattr(adapter.settings, "hipporag_sparse_seed_enabled", False)

    out = await adapter.query_hipporag_for_noble_kb("bể bơi", "NCTH", top_k=5)
    assert called["sparse"] is False  # parallel sparse path not taken when disabled
    assert "tiện ích bể bơi" not in out  # p2 unreachable via passage seed alone


async def test_query_empty_query_returns_empty():
    assert await adapter.query_hipporag_for_noble_kb("   ", "NCTH") == ""


async def test_sparse_seed_qdrant_source(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "qdrant")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1, 0.2])

    async def fake_search(vec, top_m):
        return [("A", "B", 0.9), ("C", "", 0.5)]

    monkeypatch.setattr(qdrant_store, "search_triples", fake_search)
    seeds = await adapter._sparse_seed("q", 5)
    assert seeds == {"A": 0.9, "B": 0.9, "C": 0.5}  # empty o_key skipped


async def test_sparse_seed_qdrant_falls_back_to_local(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "qdrant")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1])

    async def boom(vec, top_m):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(qdrant_store, "search_triples", boom)

    class FakeIdx:
        def search(self, vec, top_m):
            return [("X", "Y", 0.7)]

    monkeypatch.setattr(expander, "load_triple_index", lambda: FakeIdx())
    seeds = await adapter._sparse_seed("q", 5)
    assert seeds == {"X": 0.7, "Y": 0.7}  # served from local npz backup


async def test_sparse_seed_qdrant_empty_falls_back_to_local(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "qdrant")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1])

    async def empty_search(vec, top_m):
        return []  # collection dropped mid-sync — no exception, just empty

    monkeypatch.setattr(qdrant_store, "search_triples", empty_search)

    class FakeIdx:
        def search(self, vec, top_m):
            return [("X", "Y", 0.7)]

    monkeypatch.setattr(expander, "load_triple_index", lambda: FakeIdx())
    seeds = await adapter._sparse_seed("q", 5)
    assert seeds == {"X": 0.7, "Y": 0.7}  # empty qdrant → local npz hot standby


async def test_sparse_seed_qdrant_and_local_empty(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "qdrant")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1])

    async def boom(vec, top_m):
        raise RuntimeError("down")

    monkeypatch.setattr(qdrant_store, "search_triples", boom)
    monkeypatch.setattr(expander, "load_triple_index", lambda: None)
    assert await adapter._sparse_seed("q", 5) == {}  # → sparse-seed no-op (hybrid)


async def test_sparse_seed_local_store_skips_qdrant(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "local")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1])
    called = {"q": False}

    async def spy(vec, top_m):
        called["q"] = True
        return []

    monkeypatch.setattr(qdrant_store, "search_triples", spy)

    class FakeIdx:
        def search(self, vec, top_m):
            return [("X", "Y", 0.6)]

    monkeypatch.setattr(expander, "load_triple_index", lambda: FakeIdx())
    seeds = await adapter._sparse_seed("q", 5)
    assert called["q"] is False  # local store never calls Qdrant
    assert seeds == {"X": 0.6, "Y": 0.6}


async def test_sparse_seed_local_missing_index_skips_embed(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "local")
    called = {"embed": False}

    def spy_embed(q):
        called["embed"] = True
        return [0.1]

    monkeypatch.setattr(qdrant_adapter, "_embed_query", spy_embed)
    monkeypatch.setattr(expander, "load_triple_index", lambda: None)
    seeds = await adapter._sparse_seed("q", 5)
    assert called["embed"] is False  # no-embed short-circuit when local index absent
    assert seeds == {}
