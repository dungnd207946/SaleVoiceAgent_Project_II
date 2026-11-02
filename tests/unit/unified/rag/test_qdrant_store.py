import pytest

from noble_agent.agent.rag import qdrant_store as qs


class _FakePoint:
    def __init__(self, id, payload, score=0.0):
        self.id = id
        self.payload = payload
        self.score = score


class _FakeResp:
    def __init__(self, points):
        self.points = points


class _FakeClient:
    def __init__(self):
        self.last_kwargs = None

    async def query_points(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp(
            [
                _FakePoint("p1", {"project_id": "NCTH", "text": "Noble Crystal Tây Hồ"}, 0.9),
                _FakePoint("p2", {"project_id": "NCTH", "text": "view hồ"}, 0.7),
            ]
        )


@pytest.fixture
def fake(monkeypatch):
    c = _FakeClient()
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    return c


async def test_search_hybrid_builds_prefetch_and_maps_payload(fake, monkeypatch):
    monkeypatch.setattr(qs.settings, "qdrant_collection", "clone")
    monkeypatch.setattr(qs.settings, "qdrant_dense_vector_name", "dense")
    monkeypatch.setattr(qs.settings, "qdrant_sparse_vector_name", "bm25")
    out = await qs.search_hybrid([0.1, 0.2], [10, 20], [1.0, 1.0], project_filter="NCTH", top_k=2)
    assert out == [("p1", "NCTH", "Noble Crystal Tây Hồ", 0.9), ("p2", "NCTH", "view hồ", 0.7)]
    kw = fake.last_kwargs
    assert kw["collection_name"] == "clone"
    assert len(kw["prefetch"]) == 2  # dense + sparse
    assert kw["query_filter"] is not None  # project_id filter applied


async def test_search_hybrid_no_filter_omits_query_filter(fake, monkeypatch):
    monkeypatch.setattr(qs.settings, "qdrant_collection", "clone")
    await qs.search_hybrid([0.1], [1], [1.0], project_filter="", top_k=3)
    assert fake.last_kwargs["query_filter"] is None
    assert all(pf.filter is None for pf in fake.last_kwargs["prefetch"])


class _FakeTripleClient:
    def __init__(self):
        self.last = None

    async def query_points(self, **kwargs):
        self.last = kwargs
        return _FakeResp(
            [
                _FakePoint(0, {"s": "A", "o": "B", "text": "A r B"}, 0.9),
                _FakePoint(1, {"s": "C", "o": "D", "text": "C r D"}, 0.4),
            ]
        )


class _FakeAdminClient:
    def __init__(self, exists=True):
        self._exists = exists
        self.created = None
        self.deleted = None
        self.upserted = None

    async def collection_exists(self, name):
        return self._exists

    async def delete_collection(self, name):
        self.deleted = name

    async def create_collection(self, **kwargs):
        self.created = kwargs

    async def upsert(self, **kwargs):
        self.upserted = kwargs


async def test_search_triples_maps_payload(monkeypatch):
    c = _FakeTripleClient()
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    monkeypatch.setattr(qs.settings, "qdrant_triple_collection", "triples")
    out = await qs.search_triples([0.1, 0.2], top_m=2)
    assert out == [("A", "B", 0.9), ("C", "D", 0.4)]
    assert c.last["collection_name"] == "triples"
    assert c.last["limit"] == 2


async def test_recreate_triple_collection_drops_then_creates(monkeypatch):
    from qdrant_client import models

    c = _FakeAdminClient(exists=True)
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    monkeypatch.setattr(qs.settings, "qdrant_triple_collection", "triples")
    await qs.recreate_triple_collection(4)
    assert c.deleted == "triples"
    assert c.created["collection_name"] == "triples"
    vc = c.created["vectors_config"]
    assert vc.size == 4
    assert vc.distance == models.Distance.COSINE


async def test_upsert_triples_targets_triple_collection(monkeypatch):
    c = _FakeAdminClient()
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    monkeypatch.setattr(qs.settings, "qdrant_triple_collection", "triples")
    await qs.upsert_triples([{"id": 0}])
    assert c.upserted["collection_name"] == "triples"
    assert c.upserted["points"] == [{"id": 0}]
