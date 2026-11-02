"""Backend `hipporag_kb`.

`test_cache_graph_khong_lan_giua_hai_tenant` là bài AN NINH: agent là MỘT tiến trình
phục vụ nhiều workspace, còn `expander.load()` legacy là singleton không khoá.
"""

from __future__ import annotations

import pytest

from noble_agent.agent.rag import kb_service_adapter as ksa
from noble_agent.agent.rag.hipporag import kb_adapter
from noble_agent.agent.rag.hipporag.graph import HippoGraph
from noble_agent.config import settings
from noble_agent.tenant.current import use_tenant


@pytest.fixture(autouse=True)
def _sach():
    kb_adapter.reset_cache_for_tests()
    yield
    kb_adapter.reset_cache_for_tests()


def _graph(*passages) -> HippoGraph:
    g = HippoGraph()
    for pid, text, proj, triples in passages:
        g.add_passage(pid, text, proj, f"h-{pid}", triples)
    return g


def _graph_hai_passage() -> HippoGraph:
    return _graph(
        ("p1", "Noble Crystal tổng quan", "nplb", [("Noble Crystal", "ở", "Tây Hồ")]),
        ("p2", "Noble Crystal bể bơi", "nplb", [("Noble Crystal", "có", "bể bơi")]),
    )


def _pids(g: HippoGraph) -> list[str]:
    return [n.get("point_id") for n in g.nodes.values() if n.get("type") == "passage"]


def _hit(pid: str, text: str, proj: str = "nplb", score: float = 0.5) -> dict:
    return {"id": pid, "text": text, "project_id": proj, "score": score}


def test_thu_tu_rrf_uu_tien_muc_co_o_ca_hai_danh_sach():
    hybrid = [("p1", "nplb", "t1", 0.9), ("p2", "nplb", "t2", 0.5)]
    ppr = [("p2", 0.8, "nplb", "t2"), ("p3", 0.4, "nplb", "t3")]
    assert kb_adapter.thu_tu_rrf(hybrid, ppr)[0] == "p2"
    assert set(kb_adapter.thu_tu_rrf(hybrid, ppr)) == {"p1", "p2", "p3"}


def test_cache_graph_khong_lan_giua_hai_tenant(monkeypatch):
    da_goi: list[str] = []
    graphs = {"t1": _graph(("a", "cua t1", "p", [])), "t2": _graph(("b", "cua t2", "p", []))}

    def tai(tenant_id: str = "") -> str | None:
        da_goi.append(tenant_id)
        return f"/khong/ton/tai/{tenant_id}.json"

    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", tai)
    monkeypatch.setattr(kb_adapter, "_doc_graph", lambda path: graphs["t1" if "t1" in path else "t2"])

    g1 = kb_adapter.load_graph_for_tenant("t1")
    g2 = kb_adapter.load_graph_for_tenant("t2")
    assert g1 is not g2
    assert _pids(g1) == ["a"]
    assert _pids(g2) == ["b"]
    assert da_goi == ["t1", "t2"]


def test_cache_goi_tai_ve_dung_mot_lan_moi_tenant(monkeypatch):
    da_goi: list[str] = []

    def tai(tenant_id: str = "") -> str | None:
        da_goi.append(tenant_id)
        return None

    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", tai)
    kb_adapter.load_graph_for_tenant("t1")
    kb_adapter.load_graph_for_tenant("t1")
    assert da_goi == ["t1"]


def test_thieu_artefact_thi_cache_none(monkeypatch):
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", lambda tenant_id="": None)
    assert kb_adapter.load_graph_for_tenant("t1") is None


async def test_thieu_graph_thi_bang_dung_kb_service(monkeypatch):
    hits = [_hit("p1", "Noble Crystal tổng quan"), _hit("p2", "Noble Crystal bể bơi")]

    async def fake_hits(query, project_filter, limit):
        return list(hits)

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", lambda tenant_id="": None)

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("bể bơi", "nplb", top_k=2)
        mong = ksa.render(hits[:2], None, None, None)
    assert ra == mong


async def test_ppr_rong_thi_bang_dung_kb_service(monkeypatch):
    hits = [_hit("khong-co-trong-graph", "abc")]

    async def fake_hits(query, project_filter, limit):
        return list(hits)

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("abc", "nplb", top_k=1)
        mong = ksa.render(hits[:1], None, None, None)
    assert ra == mong


async def test_passage_chi_co_trong_graph_van_vao_ngu_canh(monkeypatch):
    """Đây là cái LỢI của graph: p2 không có trong hybrid hit, PPR mang nó về."""

    async def fake_hits(query, project_filter, limit):
        return [_hit("p1", "Noble Crystal tổng quan")]

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("bể bơi", "nplb", top_k=5)
    assert "bể bơi" in ra


async def test_passage_co_trong_hit_dung_chu_moi_cua_qdrant(monkeypatch):
    """Graph là snapshot: passage có trong hit phải dùng chữ của Qdrant."""

    async def fake_hits(query, project_filter, limit):
        return [_hit("p1", "CHỮ MỚI TỪ QDRANT")]

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("tổng quan", "nplb", top_k=5)
    assert "CHỮ MỚI TỪ QDRANT" in ra
    assert "Noble Crystal tổng quan" not in ra


async def test_khong_lot_passage_cua_du_an_khac_khi_da_ghim(monkeypatch):
    async def fake_hits(query, project_filter, limit):
        return [_hit("p1", "Noble Crystal tổng quan")]

    g = _graph(
        ("p1", "Noble Crystal tổng quan", "nplb", [("Noble Crystal", "ở", "Tây Hồ")]),
        ("px", "DỰ ÁN KHÁC", "sgr", [("Sunrise", "ở", "Tây Hồ")]),
    )
    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: g)

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("tây hồ", "nplb", top_k=5)
    assert "DỰ ÁN KHÁC" not in ra


async def test_tai_lieu_dung_chung_toan_tenant_khong_bi_vut(monkeypatch):
    """`build_scope_filter` union sentinel `__ALL__`, nên lọc `== project_filter` trần
    vứt đúng brochure dùng chung — chỗ `adapter.py` legacy làm sai."""
    from noble_agent.data import qdrant_search

    hits = [
        _hit("p1", "Noble Crystal tổng quan", proj="nplb"),
        _hit("pall", "BROCHURE CHUNG", proj=qdrant_search.SYSTEM_ANCHOR),
    ]

    async def fake_hits(query, project_filter, limit):
        return list(hits)

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("tổng quan", "nplb", top_k=5)
    assert "BROCHURE CHUNG" in ra


async def test_seed_k_it_nhat_bang_top_k(monkeypatch):
    da_goi: list[int] = []

    async def fake_hits(query, project_filter, limit):
        da_goi.append(limit)
        return []

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", lambda tenant_id="": None)

    with use_tenant("t1"):
        await kb_adapter.query_hipporag_kb_for_noble_kb("q", "", top_k=20)
    assert da_goi == [max(settings.hipporag_seed_k, 20)]


async def test_loi_bat_ky_trong_duong_graph_thi_degrade(monkeypatch):
    hits = [_hit("p1", "abc")]

    async def fake_hits(query, project_filter, limit):
        return list(hits)

    def no(t):
        raise RuntimeError("graph hỏng")

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", no)

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("abc", "", top_k=1)
        mong = ksa.render(hits[:1], None, None, None)
    assert ra == mong


async def test_khong_bao_gio_tra_qua_top_k(monkeypatch):
    async def fake_hits(query, project_filter, limit):
        return [_hit("p1", "Noble Crystal tổng quan")]

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    ghi: dict = {}

    def bat_render(hits, dinh_kem, du_an, numbers):
        ghi["n"] = len(hits)
        return ""

    monkeypatch.setattr(ksa, "render", bat_render)
    with use_tenant("t1"):
        await kb_adapter.query_hipporag_kb_for_noble_kb("bể bơi", "nplb", top_k=1)
    assert ghi["n"] == 1


async def test_dispatch_noble_kb_vao_dung_nhanh(monkeypatch):
    from noble_agent.agent.rag import noble_kb

    goi: list[str] = []

    async def fake(query, project_filter, top_k=5, dinh_kem=None, du_an=None, numbers=None):
        goi.append(query)
        return "TU_HIPPO_KB"

    monkeypatch.setattr(settings, "noble_rag_backend", "hipporag_kb")
    monkeypatch.setattr(kb_adapter, "query_hipporag_kb_for_noble_kb", fake)
    out = await noble_kb.query_noble_kb("bể bơi", "nplb")
    assert out == "TU_HIPPO_KB" and goi == ["bể bơi"]


async def test_backend_kb_service_khong_doi_duong(monkeypatch):
    from noble_agent.agent.rag import noble_kb

    monkeypatch.setattr(settings, "noble_rag_backend", "kb_service")

    async def no(*a, **kw):
        raise AssertionError("hipporag_kb không được gọi ở backend kb_service")

    monkeypatch.setattr(kb_adapter, "query_hipporag_kb_for_noble_kb", no)

    async def fake_ks(query, project_filter, top_k=5, dinh_kem=None, du_an=None, numbers=None):
        return "TU_KB_SERVICE"

    monkeypatch.setattr(ksa, "query_kb_service_for_noble_kb", fake_ks)
    assert await noble_kb.query_noble_kb("q", "") == "TU_KB_SERVICE"
