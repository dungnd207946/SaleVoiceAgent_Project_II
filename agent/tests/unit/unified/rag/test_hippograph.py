"""Unit tests for the HippoRAG knowledge-graph core (pure logic, no LLM/Qdrant)."""

from __future__ import annotations

from noble_agent.agent.rag.hipporag.graph import HippoGraph


def _triples_crystal():
    return [
        ("Noble Crystal", "ở", "Tây Hồ"),
        ("Noble Crystal", "có", "bể bơi"),
    ]


def test_add_passage_creates_phrase_and_passage_nodes():
    g = HippoGraph()
    g.add_passage("p1", "Noble Crystal ở Tây Hồ, có bể bơi.", "NCTH", "h1", _triples_crystal())

    # 1 passage node + 3 phrase nodes (Noble Crystal, Tây Hồ, bể bơi)
    assert g.num_passages() == 1
    assert g.num_phrases() == 3
    assert g.has_passage("h1")
    assert g.passage_key_for_id("p1") is not None


def test_add_passage_records_triples():
    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", _triples_crystal())
    assert len(g.triples) == 2
    t = g.triples[0]
    assert t["s"] == g._phrase_key("Noble Crystal")
    assert t["o"] == g._phrase_key("Tây Hồ")
    assert t["rel"] == "ở"
    assert t["text"] == "Noble Crystal ở Tây Hồ"  # full triple text for embedding
    assert t["passage"] == "p1"


def test_remove_passage_drops_its_triples():
    g = HippoGraph()
    g.add_passage("p1", "t1", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "t2", "NPTH", "h2", [("Noble Palace", "ở", "Tây Hồ")])
    assert len(g.triples) == 2
    g.remove_passage("p1")
    assert len(g.triples) == 1
    assert g.triples[0]["passage"] == "p2"


def test_triples_survive_json_round_trip():
    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", _triples_crystal())
    g2 = HippoGraph.from_json(g.to_json())
    assert g2.triples == g.triples


def test_incremental_skip_and_add():
    g = HippoGraph()
    g.add_passage("p1", "t1", "NCTH", "h1", _triples_crystal())
    assert g.has_passage("h1")
    assert not g.has_passage("h2")

    # a genuinely new chunk adds; an already-processed hash is reported present
    g.add_passage("p2", "t2", "NPTH", "h2", [("Noble Palace", "ở", "Tây Hồ")])
    assert g.num_passages() == 2
    # "Tây Hồ" is shared → total distinct phrases = Noble Crystal, Tây Hồ, bể bơi, Noble Palace = 4
    assert g.num_phrases() == 4


def test_remove_passage_prunes_orphan_phrases():
    g = HippoGraph()
    g.add_passage("p1", "t1", "NCTH", "h1", [("Noble Crystal", "có", "bể bơi")])
    g.add_passage("p2", "t2", "NCTH", "h2", [("Noble Crystal", "ở", "Tây Hồ")])
    # Noble Crystal shared by both; bể bơi only in p1, Tây Hồ only in p2
    g.remove_passage("p1")
    assert g.num_passages() == 1
    assert not g.has_passage("h1")
    # "bể bơi" became orphan → pruned; "Noble Crystal" + "Tây Hồ" survive (still linked to p2)
    labels = {g.nodes[k]["label"] for k in g.nodes if g.nodes[k]["type"] == "phrase"}
    assert "bể bơi" not in labels
    assert "Noble Crystal" in labels and "Tây Hồ" in labels


def test_ppr_spreads_from_seed_to_co_entity_passage():
    """A passage sharing entities with the seed passage must outrank an unrelated one."""
    g = HippoGraph()
    # p1 and p2 both about Noble Crystal (share the entity) → linked via that phrase
    g.add_passage("p1", "tổng quan", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "tiện ích", "NCTH", "h2", [("Noble Crystal", "có", "bể bơi")])
    # p3 unrelated project, no shared entity
    g.add_passage("p3", "khác", "SGR", "h3", [("Sun Grand", "ở", "Long Biên")])

    k1 = g.passage_key_for_id("p1")
    scores = g.personalized_pagerank({k1: 1.0}, alpha=0.5, iters=40)

    s2 = scores[g._order_index[g.passage_key_for_id("p2")]]
    s3 = scores[g._order_index[g.passage_key_for_id("p3")]]
    assert s2 > s3  # co-entity passage beats the unrelated one


def test_ppr_conserves_mass_with_dangling_node():
    """A triple-less passage is a dangling node; its mass must be redistributed to
    the restart vector so the score vector remains a distribution (sum == 1)."""
    g = HippoGraph()
    g.add_passage("p1", "connected", "NCTH", "h1", [("A", "r", "B")])  # p1—A—B component
    g.add_passage("p2", "isolated", "NCTH", "h2", [])  # no triples → dangling passage
    k1 = g.passage_key_for_id("p1")
    k2 = g.passage_key_for_id("p2")
    # seed the dangling node too so it actually holds mass to leak
    scores = g.personalized_pagerank({k1: 0.5, k2: 0.5}, alpha=0.5, iters=80)
    assert abs(float(scores.sum()) - 1.0) < 1e-9  # mass conserved despite the dangling node


def test_ppr_empty_seed_returns_zeros():
    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", [("A", "r", "B")])
    scores = g.personalized_pagerank({}, alpha=0.5, iters=10)
    assert scores.sum() == 0.0


def test_json_round_trip():
    g = HippoGraph()
    g.add_passage("p1", "t1", "NCTH", "h1", _triples_crystal())
    g.add_passage("p2", "t2", "NPTH", "h2", [("Noble Palace", "ở", "Tây Hồ")])

    d = g.to_json()
    g2 = HippoGraph.from_json(d)

    assert g2.num_passages() == g.num_passages()
    assert g2.num_phrases() == g.num_phrases()
    assert g2.processed_hashes == g.processed_hashes
    assert g2.passage_key_for_id("p1") is not None
    # PPR identical after reload
    k1 = g.passage_key_for_id("p1")
    import numpy as np

    a = g.personalized_pagerank({k1: 1.0}, alpha=0.5, iters=20)
    b = g2.personalized_pagerank({g2.passage_key_for_id("p1"): 1.0}, alpha=0.5, iters=20)
    assert np.allclose(a, b)


def test_top_passages_ranks_by_score():
    g = HippoGraph()
    g.add_passage("p1", "tổng quan", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    g.add_passage("p2", "tiện ích", "NCTH", "h2", [("Noble Crystal", "có", "bể bơi")])
    g.add_passage("p3", "khác", "SGR", "h3", [("Sun Grand", "ở", "Long Biên")])
    k1 = g.passage_key_for_id("p1")
    scores = g.personalized_pagerank({k1: 1.0}, alpha=0.5, iters=40)
    ranked = g.top_passages(scores, top_k=2)
    ids = [pid for pid, _score, _proj, _text in ranked]
    assert "p1" in ids  # seed itself ranks high
    assert "p3" not in ids  # unrelated excluded from top-2


def test_top_passages_project_filter_scopes_output():
    g = HippoGraph()
    g.add_passage("p1", "Noble Crystal", "NCTH", "h1", [("Noble Crystal", "ở", "Tây Hồ")])
    # p2 shares the "Tây Hồ" entity so PPR reaches it, but it's a different project
    g.add_passage("p2", "Sun Grand", "SGR", "h2", [("Sun Grand", "ở", "Tây Hồ")])
    k1 = g.passage_key_for_id("p1")
    scores = g.personalized_pagerank({k1: 1.0}, alpha=0.5, iters=40)
    ranked = g.top_passages(scores, top_k=5, project_filter="NCTH")
    ids = [pid for pid, _s, _p, _t in ranked]
    assert "p1" in ids
    assert "p2" not in ids  # cross-project passage filtered out
    assert all(proj == "NCTH" for _pid, _s, proj, _t in ranked)
