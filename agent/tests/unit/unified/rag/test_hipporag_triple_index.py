"""Tests for the HippoRAG triple-embedding index (sparse triple-seed source)."""

from __future__ import annotations

import numpy as np

from noble_agent.agent.rag.hipporag import triple_index


def test_search_returns_both_entity_keys_ranked_by_cosine():
    s_keys = ["phrase::a", "phrase::c"]
    o_keys = ["phrase::b", "phrase::d"]
    emb = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    idx = triple_index.TripleIndex(s_keys, o_keys, emb)
    res = idx.search([1.0, 0.0, 0.0], top_m=2)
    assert res[0][0] == "phrase::a" and res[0][1] == "phrase::b"  # closest triple, both keys
    assert res[0][2] > res[1][2]  # ranked by cosine


def test_empty_or_zero_query_returns_empty():
    idx = triple_index.TripleIndex([], [], np.zeros((0, 3), dtype=np.float32))
    assert idx.search([1.0, 0.0, 0.0], top_m=3) == []
    idx2 = triple_index.TripleIndex(["phrase::a"], ["phrase::b"], np.array([[1.0, 0.0]], dtype=np.float32))
    assert idx2.search([0.0, 0.0], top_m=3) == []


def test_save_load_round_trip(tmp_path):
    graph_path = str(tmp_path / "graph.json")
    triple_index.save_triple_index(
        graph_path, ["phrase::x"], ["phrase::y"], np.array([[0.0, 1.0]], dtype=np.float32)
    )
    idx = triple_index.load_triple_index(graph_path)
    assert idx is not None
    assert idx.s_keys == ["phrase::x"] and idx.o_keys == ["phrase::y"]
    res = idx.search([0.0, 1.0], top_m=1)
    assert res[0][0] == "phrase::x" and res[0][1] == "phrase::y"


def test_sidecar_path_derived_from_graph_path(tmp_path):
    p = triple_index.triple_emb_path(str(tmp_path / "graph.json"))
    assert p.endswith(".triple_emb.npz")


def test_load_missing_returns_none(tmp_path):
    assert triple_index.load_triple_index(str(tmp_path / "absent.json")) is None
