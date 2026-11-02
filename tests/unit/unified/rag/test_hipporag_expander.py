"""Tests for the HippoRAG query-time expander (PPR over a loaded graph)."""

from __future__ import annotations

from noble_agent.agent.rag.hipporag import expander
from noble_agent.agent.rag.hipporag.graph import HippoGraph


def _graph():
    g = HippoGraph()
    g.add_passage("p1", "Noble Crystal tổng quan", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "Noble Crystal tiện ích bể bơi", "NCTH", "h2", [("Noble Crystal", "có", "bể bơi")])
    g.add_passage("p3", "Sun Grand Long Biên", "SGR", "h3", [("Sun Grand", "ở", "Long Biên")])
    return g


def test_expand_surfaces_co_entity_passage():
    g = _graph()
    # hybrid found only p1; PPR should pull in p2 (shares "Noble Crystal") above p3
    seed_hits = [("p1", "NCTH", "Noble Crystal tổng quan", 0.9)]
    ranked = expander.expand(g, seed_hits, alpha=0.5, iters=40, seed_k=8, top_k=3)
    ids = [pid for pid, _s, _p, _t in ranked]
    assert "p1" in ids and "p2" in ids
    assert ids.index("p2") < ids.index("p3") if "p3" in ids else True


def test_expand_project_filter_scopes_output():
    g = HippoGraph()
    g.add_passage("p1", "Noble Crystal Tây Hồ", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "Sun Grand Tây Hồ", "SGR", "h2", [("Sun Grand", "ở", "Tây Hồ")])
    ranked = expander.expand(
        g, [("p1", "NCTH", "Noble Crystal Tây Hồ", 0.9)],
        alpha=0.5, iters=40, seed_k=8, top_k=5, project_filter="NCTH",
    )
    ids = [pid for pid, _s, _p, _t in ranked]
    assert ids and "p2" not in ids
    assert all(proj == "NCTH" for _pid, _s, proj, _t in ranked)


def test_expand_no_project_filter_allows_cross_project():
    g = HippoGraph()
    g.add_passage("p1", "Noble Crystal Tây Hồ", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "Sun Grand Tây Hồ", "SGR", "h2", [("Sun Grand", "ở", "Tây Hồ")])
    ranked = expander.expand(
        g, [("p1", "NCTH", "Noble Crystal Tây Hồ", 0.9)],
        alpha=0.5, iters=40, seed_k=8, top_k=5,  # no project_filter
    )
    projects = {proj for _pid, _s, proj, _t in ranked}
    assert "SGR" in projects  # cross-project reachable when unfiltered


def _disjoint_graph():
    """p1 (Noble Crystal / Tây Hồ) and p2 (dự án X / bể bơi) share NO entity —
    passage-seeding p1 alone can never reach p2."""
    g = HippoGraph()
    g.add_passage("p1", "tổng quan", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "tiện ích", "NCTH", "h2", [("dự án X", "có", "bể bơi")])
    return g


def test_passage_only_seed_misses_disconnected_passage():
    g = _disjoint_graph()
    ranked = expander.expand(g, [("p1", "NCTH", "tổng quan", 0.9)], alpha=0.5, iters=40, seed_k=8, top_k=5)
    ids = [pid for pid, _s, _p, _t in ranked]
    assert "p2" not in ids  # unreachable via passage seed alone


def test_sparse_phrase_seed_pulls_disconnected_passage():
    g = _disjoint_graph()
    bo_key = g._phrase_key("bể bơi")  # phrase node linked to p2
    ranked = expander.expand(
        g, [("p1", "NCTH", "tổng quan", 0.9)],
        alpha=0.5, iters=40, seed_k=8, top_k=5,
        extra_seeds={bo_key: 1.0}, sparse_weight=0.5,
    )
    ids = [pid for pid, _s, _p, _t in ranked]
    assert "p2" in ids  # sparse triple-seed reached it


def test_sparse_weight_zero_ignores_extra_seeds():
    g = _disjoint_graph()
    bo_key = g._phrase_key("bể bơi")
    ranked = expander.expand(
        g, [("p1", "NCTH", "tổng quan", 0.9)],
        alpha=0.5, iters=40, seed_k=8, top_k=5,
        extra_seeds={bo_key: 1.0}, sparse_weight=0.0,  # disabled
    )
    ids = [pid for pid, _s, _p, _t in ranked]
    assert "p2" not in ids  # extra seeds ignored when weight is 0


def test_load_triple_index_caches(tmp_path, monkeypatch):
    import numpy as np

    from noble_agent.agent.rag.hipporag import triple_index

    graph_path = str(tmp_path / "graph.json")
    triple_index.save_triple_index(
        graph_path, ["phrase::a"], ["phrase::b"], np.array([[1.0, 0.0]], dtype=np.float32)
    )
    monkeypatch.setattr(expander.settings, "hipporag_graph_path", graph_path)
    expander.reset_cache()
    i1 = expander.load_triple_index()
    i2 = expander.load_triple_index()
    assert i1 is not None and i1 is i2


def test_passage_threshold_drops_low_score_seed_before_mixing():
    g = HippoGraph()
    g.add_passage("p1", "a", "NCTH", "h1", [("A", "r", "B")])  # component A
    g.add_passage("p2", "b", "SGR", "h2", [("C", "r", "D")])  # disconnected component B
    hits = [("p1", "NCTH", "a", 0.9), ("p2", "SGR", "b", 0.2)]  # p2 score below threshold

    kept = expander.expand(g, hits, alpha=0.5, iters=30, seed_k=8, top_k=5, passage_threshold=0.5)
    ids = [pid for pid, _s, _p, _t in kept]
    assert "p1" in ids and "p2" not in ids  # low-score p2 filtered out of the seeds

    allkept = expander.expand(g, hits, alpha=0.5, iters=30, seed_k=8, top_k=5, passage_threshold=0.0)
    assert "p2" in [pid for pid, *_ in allkept]  # kept when threshold disabled


def test_all_passage_seeds_below_threshold_returns_empty():
    g = HippoGraph()
    g.add_passage("p1", "a", "NCTH", "h1", [("A", "r", "B")])
    kept = expander.expand(g, [("p1", "NCTH", "a", 0.2)], seed_k=8, top_k=5, passage_threshold=0.5)
    assert kept == []  # no seed survived → empty (adapter degrades to hybrid)


def test_phrase_threshold_drops_weak_phrase_seed_before_mixing():
    g = HippoGraph()
    g.add_passage("p1", "a", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "b", "NCTH", "h2", [("dự án X", "có", "bể bơi")])  # disjoint from p1
    bo = g._phrase_key("bể bơi")
    hits = [("p1", "NCTH", "a", 0.9)]

    weak = expander.expand(
        g, hits, seed_k=8, top_k=5, extra_seeds={bo: 0.3}, sparse_weight=0.5, phrase_threshold=0.5
    )
    assert "p2" not in [pid for pid, *_ in weak]  # phrase seed below threshold dropped

    strong = expander.expand(
        g, hits, seed_k=8, top_k=5, extra_seeds={bo: 0.8}, sparse_weight=0.5, phrase_threshold=0.5
    )
    assert "p2" in [pid for pid, *_ in strong]  # phrase seed above threshold kept


def test_expand_no_mappable_seed_returns_empty():
    g = _graph()
    ranked = expander.expand(g, [("unknown_id", "X", "t", 0.5)], alpha=0.5, iters=10, seed_k=8, top_k=3)
    assert ranked == []


def test_expand_empty_graph_returns_empty():
    ranked = expander.expand(HippoGraph(), [("p1", "X", "t", 0.5)], alpha=0.5, iters=10, seed_k=8, top_k=3)
    assert ranked == []


def test_load_caches_singleton(tmp_path, monkeypatch):
    from noble_agent.agent.rag.hipporag.graph import save_graph

    g = _graph()
    path = str(tmp_path / "graph.json")
    save_graph(g, path)
    monkeypatch.setattr(expander.settings, "hipporag_graph_path", path)
    expander.reset_cache()

    g1 = expander.load()
    g2 = expander.load()
    assert g1 is not None and g1 is g2  # cached, not reloaded


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(expander.settings, "hipporag_graph_path", str(tmp_path / "absent.json"))
    expander.reset_cache()
    assert expander.load() is None
