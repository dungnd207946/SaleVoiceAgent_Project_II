import numpy as np
import pytest

from noble_agent.agent.rag import qdrant_store as qs


@pytest.fixture(autouse=True)
def _reset_client():
    qs._client = None
    yield
    qs._client = None


async def test_search_dense_maps_points_to_tuples(monkeypatch):
    class _Pt:
        def __init__(self, pid, payload, score):
            self.id, self.payload, self.score = pid, payload, score

    class _Resp:
        points = [
            _Pt("u1", {"chunk_id": "a", "project": "NCLB", "text": "alpha"}, 0.91),
            _Pt("u2", {"chunk_id": "b", "project": "NCLB", "text": "beta"}, 0.80),
        ]

    class _FakeClient:
        async def query_points(self, **kwargs):
            # project filter must be passed through when project_filter given
            assert kwargs["query_filter"] is not None
            return _Resp()

    monkeypatch.setattr(qs, "_get_client", lambda: _FakeClient())
    out = await qs.search_dense(np.zeros(4, dtype=np.float32), "NCLB", top_k=5)
    assert out == [
        ("a", "NCLB", "alpha", 0.91),
        ("b", "NCLB", "beta", 0.80),
    ]
