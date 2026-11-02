import pytest

from noble_agent.agent.rag import bm25_fallback as fb
from noble_agent.agent.rag.flat_store import Chunk


@pytest.fixture(autouse=True)
def _clear():
    fb.reset_cache()
    yield
    fb.reset_cache()


def _chunks():
    return [
        Chunk(id="p1", project="NCTH", text="Noble Crystal Tây Hồ căn hộ ba phòng ngủ view hồ"),
        Chunk(id="p2", project="SGR", text="Sunshine Grand City tiện ích bể bơi giá gốc"),
        Chunk(id="p3", project="NCTH", text="Noble Crystal Tây Hồ pháp lý sổ hồng lâu dài"),
    ]


def test_build_then_search_returns_hits(tmp_path):
    d = str(tmp_path / "fb")
    fb.build(_chunks(), d)
    hits = fb.search("căn hộ Tây Hồ", project_filter="", top_k=2, out_dir=d)
    assert hits
    assert len(hits) <= 2
    assert all(h.chunk.project for h in hits)


def test_project_filter_restricts_results(tmp_path):
    d = str(tmp_path / "fb")
    fb.build(_chunks(), d)
    hits = fb.search("Noble Crystal", project_filter="NCTH", top_k=5, out_dir=d)
    assert hits
    assert len(hits) >= 2
    assert {h.chunk.project for h in hits} == {"NCTH"}


def test_search_missing_artifact_returns_empty(tmp_path):
    assert fb.search("bất kỳ", project_filter="", top_k=5, out_dir=str(tmp_path / "nonexistent")) == []
