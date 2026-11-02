"""Tests for HippoRAG graph build/update logic (pure over injected chunks + extract_fn)."""

from __future__ import annotations

from noble_agent.agent.rag.hipporag import builder
from noble_agent.agent.rag.hipporag.graph import HippoGraph, load_graph, save_graph

CHUNKS_V1 = [
    {"point_id": "p1", "content_hash": "h1", "project": "NCTH", "text": "Noble Crystal ở Tây Hồ"},
    {"point_id": "p2", "content_hash": "h2", "project": "NPTH", "text": "Noble Palace ở Tây Hồ"},
]


def _extract_fn_factory(counter):
    async def fake_extract(text, _complete=None):
        counter["n"] += 1
        # one deterministic triple per chunk
        return [(text.split()[0] + " " + text.split()[1], "ở", "Tây Hồ")]

    return fake_extract


async def test_fresh_build_extracts_every_chunk():
    counter = {"n": 0}
    g = await builder.build_or_update_graph(CHUNKS_V1, _extract_fn_factory(counter))
    assert counter["n"] == 2
    assert g.num_passages() == 2
    assert g.has_passage("h1") and g.has_passage("h2")


async def test_incremental_skips_processed_chunks():
    counter = {"n": 0}
    g = await builder.build_or_update_graph(CHUNKS_V1, _extract_fn_factory(counter))
    assert counter["n"] == 2

    # add one NEW chunk; the two old ones must NOT be re-extracted
    chunks_v2 = CHUNKS_V1 + [
        {"point_id": "p3", "content_hash": "h3", "project": "SGR", "text": "Sun Grand ở Long Biên"}
    ]
    g2 = await builder.build_or_update_graph(chunks_v2, _extract_fn_factory(counter), graph=g)
    assert counter["n"] == 3  # only +1 LLM call for the new chunk
    assert g2.num_passages() == 3


async def test_renew_reextracts_all():
    counter = {"n": 0}
    g = await builder.build_or_update_graph(CHUNKS_V1, _extract_fn_factory(counter))
    assert counter["n"] == 2
    g2 = await builder.build_or_update_graph(CHUNKS_V1, _extract_fn_factory(counter), graph=g, renew=True)
    assert counter["n"] == 4  # all re-extracted from scratch
    assert g2.num_passages() == 2


async def test_changed_text_reextracts_that_chunk():
    counter = {"n": 0}
    g = await builder.build_or_update_graph(CHUNKS_V1, _extract_fn_factory(counter))
    # same point id p1 but new content_hash (text edited) → treated as new
    chunks = [
        {"point_id": "p1", "content_hash": "h1_new", "project": "NCTH", "text": "Noble Crystal có bể bơi"},
        CHUNKS_V1[1],
    ]
    await builder.build_or_update_graph(chunks, _extract_fn_factory(counter), graph=g)
    assert counter["n"] == 3  # p1 re-extracted (hash changed), p2 skipped
    assert g.has_passage("h1_new")
    assert not g.has_passage("h1")  # stale hash gone


async def test_persist_round_trip(tmp_path):
    counter = {"n": 0}
    g = await builder.build_or_update_graph(CHUNKS_V1, _extract_fn_factory(counter))
    path = str(tmp_path / "graph.json")
    save_graph(g, path)
    g2 = load_graph(path)
    assert isinstance(g2, HippoGraph)
    assert g2.num_passages() == 2
    assert g2.processed_hashes == {"h1", "h2"}


def test_load_missing_returns_none(tmp_path):
    assert load_graph(str(tmp_path / "nope.json")) is None


async def test_build_and_save_triple_index(tmp_path):
    import numpy as np

    from noble_agent.agent.rag.hipporag import triple_index

    counter = {"n": 0}
    g = await builder.build_or_update_graph(CHUNKS_V1, _extract_fn_factory(counter))
    n_triples = len(g.triples)  # fake extract → 1 triple per chunk
    assert n_triples == len(CHUNKS_V1)

    def fake_encode(texts):
        assert len(texts) == n_triples  # embeds triple TEXT, one per triple
        return np.ones((len(texts), 4), dtype=np.float32)

    path = str(tmp_path / "graph.json")
    n = builder.build_and_save_triple_index(g, path, fake_encode)
    assert n == n_triples
    idx = triple_index.load_triple_index(path)
    assert idx is not None and len(idx.s_keys) == n_triples and len(idx.o_keys) == n_triples


def test_build_triple_index_swallows_encoder_error(tmp_path):
    def boom(texts):
        raise RuntimeError("embedder down")

    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", [("A", "r", "B")])
    # must not raise; returns 0
    assert builder.build_and_save_triple_index(g, str(tmp_path / "g.json"), boom) == 0


def test_openie_primary_pins_dedicated_model():
    from noble_agent.config import UnifiedSettings

    # HIPPORAG_OPENIE_MODEL set → its provider wins, independent of the agent
    s = UnifiedSettings(_env_file=None, dashscope_model="qwen-x", hipporag_openie_model="qwen-x")
    assert builder._openie_primary(s) == "dashscope"


def test_openie_primary_falls_back_to_agent_model():
    from noble_agent.config import UnifiedSettings

    # empty HIPPORAG_OPENIE_MODEL → fall back to the NOBLE_AGENT_MODEL pin
    s = UnifiedSettings(_env_file=None, anthropic_model="claude-y", **{"NOBLE_AGENT_MODEL": "claude-y"})
    assert builder._openie_primary(s) == "anthropic"


async def test_build_triple_qdrant_upserts(monkeypatch):
    import numpy as np

    from noble_agent.agent.rag import flat_store, qdrant_store

    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", [("A", "r", "B"), ("C", "r2", "D")])

    class FakeEmb:
        def encode_batch(self, texts, show_progress=False):
            return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr(flat_store, "_Embedder", lambda: FakeEmb())

    calls = {}

    async def fake_recreate(dim):
        calls["dim"] = dim

    async def fake_upsert(points):
        calls["points"] = points

    monkeypatch.setattr(qdrant_store, "recreate_triple_collection", fake_recreate)
    monkeypatch.setattr(qdrant_store, "upsert_triples", fake_upsert)

    await builder._build_triple_qdrant(g)
    assert calls["dim"] == 4
    assert len(calls["points"]) == 2  # 2 triples


async def test_build_triple_qdrant_noop_on_empty(monkeypatch):
    from noble_agent.agent.rag import qdrant_store

    called = {"recreate": False}

    async def fake_recreate(dim):
        called["recreate"] = True

    monkeypatch.setattr(qdrant_store, "recreate_triple_collection", fake_recreate)
    await builder._build_triple_qdrant(HippoGraph())  # no passages → no triples
    assert called["recreate"] is False


async def test_build_triple_qdrant_swallows_embedder_error(monkeypatch):
    from noble_agent.agent.rag import flat_store

    def boom():
        raise RuntimeError("embedder down")

    monkeypatch.setattr(flat_store, "_Embedder", boom)
    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", [("A", "r", "B")])
    # must not raise
    await builder._build_triple_qdrant(g)
