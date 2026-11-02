import pytest

from noble_agent.agent.rag import qdrant_adapter as qa
from noble_agent.agent.rag.flat_store import Chunk, SearchHit


@pytest.fixture(autouse=True)
def _stub_embed(monkeypatch):
    # Avoid loading any embed model in unit tests.
    monkeypatch.setattr(qa, "_embed_query", lambda q: [0.1, 0.2, 0.3])


async def test_happy_path_uses_qdrant_hybrid(monkeypatch):
    async def fake_hybrid(dense, sidx, sval, project_filter, top_k):
        return [("p1", "NCTH", "Noble Crystal Tây Hồ", 0.9)]

    monkeypatch.setattr(qa.qdrant_store, "search_hybrid", fake_hybrid)
    out = await qa.query_qdrant_for_noble_kb("căn hộ Tây Hồ", "NCTH", top_k=3)
    assert "Noble Crystal Tây Hồ" in out
    assert "NCTH" in out


async def test_falls_back_to_local_bm25_on_qdrant_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("qdrant down")

    def fake_fb(query, project_filter, top_k, out_dir):
        return [SearchHit(chunk=Chunk(id="p3", project="NCTH", text="pháp lý sổ hồng"), score=1.2)]

    monkeypatch.setattr(qa.qdrant_store, "search_hybrid", boom)
    monkeypatch.setattr(qa.bm25_fallback, "search", fake_fb)
    out = await qa.query_qdrant_for_noble_kb("pháp lý", "NCTH", top_k=3)
    assert "pháp lý sổ hồng" in out


async def test_empty_query_returns_empty():
    assert await qa.query_qdrant_for_noble_kb("  ", "NCTH") == ""
