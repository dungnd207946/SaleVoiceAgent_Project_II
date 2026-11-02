"""kb_search backend — agent/rag/kb_service_adapter.

Since the query_rag:8016 retirement this backend runs in-process: embed the query
(dense + BM25 sparse, in parallel) via the embed service, then ONE Qdrant hybrid
query against ``<tenant>_documents``. These tests fake both clients — no network.

The formatter is unchanged from the HTTP era (Qdrant payloads carry the same
text/project_name/updated_at fields), so its tests are kept as-is.
"""

from noble_agent.agent.rag import kb_service_adapter as ad
from noble_agent.data.qdrant_search import SYSTEM_ANCHOR as _SENTINEL

# ── formatter (unchanged behaviour) ──────────────────────────────────────────


def test_format_includes_name_section_and_updated():
    out = ad._format_kb_hits(
        [
            {
                "text": "Bể bơi vô cực tầng 5.",
                "project_name": "Noble Crystal Long Biên",
                "section": "Noble Crystal › tiện ích",
                "updated_at": "2026-07-29T08:00:00Z",
            }
        ]
    )
    assert "Noble Crystal Long Biên › Noble Crystal › tiện ích" in out
    assert "Bể bơi vô cực tầng 5." in out
    assert "cập nhật: 2026-07-29T08:00:00Z" in out


def test_format_omits_missing_optional_fields():
    out = ad._format_kb_hits([{"text": "chỉ có text", "project_name": "Dự án X"}])
    assert "[Dự án X]" in out  # no ' › ' when section absent
    assert "›" not in out
    assert "cập nhật" not in out


def test_format_skips_empty_text_and_empty_hits():
    assert ad._format_kb_hits([]) == ""
    assert ad._format_kb_hits([{"text": "  ", "project_name": "X"}]) == ""


# ── fakes + fixture ──────────────────────────────────────────────────────────


def _wire(monkeypatch, *, tenant="noble-homes_k3n7_retail", exists=True, points=None, capture=None):
    """Point the adapter at fake embed + Qdrant clients and a fixed tenant."""
    cap = capture if capture is not None else {}

    async def fake_dense(texts, **kw):
        cap["dense"] = (texts, kw)
        return [[0.1, 0.2]]

    async def fake_sparse(texts, **kw):
        cap["sparse"] = (texts, kw)
        return [{"indices": [10, 20], "values": [1.0, 1.0]}]

    async def fake_exists(base_url, api_key, collection):
        cap["exists"] = (base_url, api_key, collection)
        return exists

    async def fake_search(**kw):
        cap["search"] = kw
        return points if points is not None else [{"text": "hit", "project_name": "N"}]

    monkeypatch.setattr(ad.embed_client, "embed_dense", fake_dense)
    monkeypatch.setattr(ad.embed_client, "embed_sparse", fake_sparse)
    monkeypatch.setattr(ad.qdrant_client, "collection_exists", fake_exists)
    monkeypatch.setattr(ad.qdrant_client, "search_hybrid", fake_search)
    monkeypatch.setattr(ad, "current_tenant", lambda: tenant)
    monkeypatch.setattr(ad.settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(ad.settings, "qdrant_api_key", "qkey")
    return cap


# ── happy path ───────────────────────────────────────────────────────────────


async def test_queries_tenant_documents_collection(monkeypatch):
    cap = _wire(monkeypatch)
    out = await ad.query_kb_service_for_noble_kb("tiện ích", "NCLB", top_k=7)
    assert cap["search"]["collection"] == "noble-homes_k3n7_retail_documents"
    assert cap["search"]["limit"] == 7
    assert "hit" in out


async def test_embeds_query_side_for_both_branches(monkeypatch):
    """E5 is prefix-asymmetric; the agent only ever queries, never indexes."""
    cap = _wire(monkeypatch)
    await ad.query_kb_service_for_noble_kb("tiện ích", "")
    assert cap["dense"][0] == ["tiện ích"]
    assert cap["dense"][1]["side"] == "query"
    assert cap["sparse"][0] == ["tiện ích"]
    assert cap["sparse"][1]["side"] == "query"


async def test_embed_config_is_the_embed_modules_business(monkeypatch):
    """The adapter passes only `side` — backend/model/url live in data/embed_client."""
    cap = _wire(monkeypatch)
    await ad.query_kb_service_for_noble_kb("q", "")
    assert set(cap["dense"][1]) == {"side"}
    assert set(cap["sparse"][1]) == {"side"}


async def test_builds_dense_and_sparse_prefetch_branches(monkeypatch):
    cap = _wire(monkeypatch)
    await ad.query_kb_service_for_noble_kb("q", "")
    branches = cap["search"]["prefetches"]
    assert len(branches) == 2
    assert isinstance(branches[0], ad.qdrant_client.DensePrefetch)
    assert branches[0].using == "dense"
    assert branches[0].vector == [0.1, 0.2]
    assert isinstance(branches[1], ad.qdrant_client.SparsePrefetch)
    assert branches[1].using == "bm25"
    assert branches[1].indices == [10, 20]


async def test_project_filter_scopes_and_unions_sentinel(monkeypatch):
    from noble_agent.data import qdrant_search as sq

    cap = _wire(monkeypatch)
    await ad.query_kb_service_for_noble_kb("q", "NCLB")
    conds = {c.key: c for c in cap["search"]["filter_"].must}
    assert conds["project_id"].match.any == ["NCLB", "__ALL__"]
    assert conds[sq.CHI_HIEN_KHI].match.value == sq.TRANG_THAI_HIEN


async def test_empty_filter_searches_whole_tenant(monkeypatch):
    """Không có project scope = tìm cả tenant — nhưng VẪN có mệnh đề trạng thái.

    Trước 2026-08-14 filter là `None` ở ca này. `None` bây giờ nghĩa là tìm cả nội dung
    nháp: Portal đã ghi point cho hàng nháp, và mệnh đề `status == 'published'` là thứ duy
    nhất ngăn nó tới khách.
    """
    from noble_agent.data import qdrant_search as sq

    cap = _wire(monkeypatch)
    await ad.query_kb_service_for_noble_kb("q", "")
    flt = cap["search"]["filter_"]
    assert flt is not None
    assert [c.key for c in flt.must] == [sq.CHI_HIEN_KHI]
    assert flt.must[0].match.value == sq.TRANG_THAI_HIEN


async def test_min_score_forwarded_only_when_positive(monkeypatch):
    cap = _wire(monkeypatch)
    monkeypatch.setattr(ad.settings, "kb_search_min_score", 0.4)
    await ad.query_kb_service_for_noble_kb("q", "")
    assert cap["search"]["score_threshold"] == 0.4

    cap2 = _wire(monkeypatch)
    monkeypatch.setattr(ad.settings, "kb_search_min_score", 0.0)
    await ad.query_kb_service_for_noble_kb("q", "")
    assert cap2["search"]["score_threshold"] is None


async def test_empty_hits_format_to_empty_string(monkeypatch):
    _wire(monkeypatch, points=[])
    assert await ad.query_kb_service_for_noble_kb("q", "") == ""


# ── degrade / guard paths ────────────────────────────────────────────────────


async def test_empty_query_returns_empty():
    assert await ad.query_kb_service_for_noble_kb("  ", "NCLB") == ""


async def test_unconfigured_qdrant_returns_empty(monkeypatch):
    cap = _wire(monkeypatch)
    monkeypatch.setattr(ad.settings, "qdrant_url", "")
    assert await ad.query_kb_service_for_noble_kb("tiện ích", "NCLB") == ""
    assert "search" not in cap  # never touched Qdrant


async def test_unconfigured_qdrant_skips_embedding(monkeypatch):
    cap = _wire(monkeypatch)
    monkeypatch.setattr(ad.settings, "qdrant_url", "")
    assert await ad.query_kb_service_for_noble_kb("tiện ích", "NCLB") == ""
    assert "dense" not in cap


async def test_missing_collection_fails_closed_before_embedding(monkeypatch):
    """An unprovisioned tenant must cost no embed round-trip."""
    cap = _wire(monkeypatch, exists=False)
    assert await ad.query_kb_service_for_noble_kb("tiện ích", "NCLB") == ""
    assert cap["exists"][2] == "noble-homes_k3n7_retail_documents"
    assert "dense" not in cap
    assert "search" not in cap


async def test_errors_propagate_for_noble_kb_to_degrade(monkeypatch):
    """The adapter does not catch — noble_kb._query_via_kb_service owns degrade."""
    import pytest

    _wire(monkeypatch)

    async def boom(**kw):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(ad.qdrant_client, "search_hybrid", boom)
    with pytest.raises(RuntimeError):
        await ad.query_kb_service_for_noble_kb("q", "")


# ─── _du_an_duy_nhat: mã dự án suy từ hits ────────────────────────────────────


def _h(pid):
    return {"project_id": pid}


def test_du_an_duy_nhat_moi_hit_cung_du_an():
    assert ad._du_an_duy_nhat([_h("VOP3"), _h("VOP3")]) == "VOP3"


def test_du_an_duy_nhat_hai_du_an_thi_rong():
    assert ad._du_an_duy_nhat([_h("VOP3"), _h("VRI")]) == ""


def test_du_an_duy_nhat_bo_qua_sentinel_toan_tenant():
    """Brochure dùng chung (`__ALL__`) lọt vào gần như mọi phép tìm. Tính nó là
    một dự án thì mọi câu hỏi đều hoá "hai dự án" và sticky không bao giờ được đặt."""
    hits = [_h("VOP3"), _h(_SENTINEL), _h("VOP3")]

    assert ad._du_an_duy_nhat(hits) == "VOP3"


def test_du_an_duy_nhat_chi_co_sentinel_thi_rong():
    """Tài liệu toàn tenant không nói về dự án nào cụ thể — không có gì để ghim."""
    assert ad._du_an_duy_nhat([_h(_SENTINEL)]) == ""


def test_du_an_duy_nhat_hits_rong_hoac_thieu_khoa():
    assert ad._du_an_duy_nhat([]) == ""
    assert ad._du_an_duy_nhat([{}, {"project_id": ""}, {"project_id": "  "}]) == ""


# ─── Cờ đính kèm tệp nguồn — TẮT mặc định (2026-08-26) ───────────────────────


def _hit_co_tep(pid="VOP3"):
    return {
        "project_id": pid,
        "text": "nội dung",
        "file_public_url": "https://x/csbh.pdf",
        "file_name": "Chính sách bán hàng",
    }


async def test_mac_dinh_la_TAT():
    """Đo trên `Settings` thật, không trên bản đã monkeypatch — một mặc định bật
    thì mọi tenant nhận thẻ tài liệu ngay lần deploy."""
    from noble_agent.config import UnifiedSettings

    assert UnifiedSettings().kb_search_attach_source_files is False


async def test_co_tat_thi_khong_dinh_kem_gi(monkeypatch):
    """kb_search đính kèm tệp của MỌI hit có tệp, không xét hit đó có góp chữ nào
    vào câu trả lời. Đo aina_prod: 107/111 chunk của một dự án thuộc 3 tệp CSBH, nên
    gần như mọi câu hỏi đều gửi kèm một thẻ tài liệu không ai xin."""
    _wire(monkeypatch, points=[_hit_co_tep()])
    monkeypatch.setattr(ad.settings, "kb_search_attach_source_files", False)
    bon: list[dict] = []

    ra = await ad.query_kb_service_for_noble_kb("vị trí ở đâu", "", dinh_kem=bon)

    assert bon == []
    assert ra, "context vẫn phải về — tắt đính kèm không được làm mất câu trả lời"


async def test_bat_len_thi_dinh_kem_lai(monkeypatch):
    """Cờ chứ không xoá code: đường đưa tệp qua `items[]` vẫn đúng, chỉ việc đính
    kèm VÔ ĐIỀU KIỆN là sai."""
    _wire(monkeypatch, points=[_hit_co_tep()])
    monkeypatch.setattr(ad.settings, "kb_search_attach_source_files", True)
    bon: list[dict] = []

    await ad.query_kb_service_for_noble_kb("cho em xin chính sách", "", dinh_kem=bon)

    assert [m["url"] for m in bon] == ["https://x/csbh.pdf"]


async def test_du_an_van_duoc_bao_khi_tat_dinh_kem(monkeypatch):
    """Hai bồn chứa độc lập: tắt đính kèm không được làm mất sticky project, vì đó
    là thứ `send_media` cần để gửi được ảnh."""
    _wire(monkeypatch, points=[_hit_co_tep()])
    monkeypatch.setattr(ad.settings, "kb_search_attach_source_files", False)
    bon: list[dict] = []
    du_an: list[str] = []

    await ad.query_kb_service_for_noble_kb("vị trí ở đâu", "", dinh_kem=bon, du_an=du_an)

    assert bon == []
    assert du_an == ["VOP3"]


# ─── Mốc `[ảnh N]` và `items` phải cùng một cờ — không thì mốc trỏ vào hư không ──


def _hit_co_anh(pid="VOP3"):
    return {"project_id": pid, "text": "Xem ảnh mẫu.\n\n![Phối cảnh](https://x/mau.png)"}


async def test_tat_dinh_kem_thi_KHONG_thay_url_anh_bang_moc(monkeypatch):
    """Cờ tắt phải giữ nguyên markdown ảnh — mốc `[ảnh 1]` mà `items` không gửi là
    một tham chiếu rỗng, tệ hơn URL thô mà khách nhận trước nhánh đánh số này."""
    _wire(monkeypatch, points=[_hit_co_anh()])
    monkeypatch.setattr(ad.settings, "kb_search_attach_source_files", False)

    ra = await ad.query_kb_service_for_noble_kb("xem ảnh", "")

    assert "https://x/mau.png" in ra
    assert "[ảnh 1" not in ra


async def test_bat_dinh_kem_thi_thay_url_anh_bang_moc(monkeypatch):
    _wire(monkeypatch, points=[_hit_co_anh()])
    monkeypatch.setattr(ad.settings, "kb_search_attach_source_files", True)
    bon: list[dict] = []

    ra = await ad.query_kb_service_for_noble_kb("xem ảnh", "", dinh_kem=bon)

    assert "[ảnh 1 — Phối cảnh]" in ra
    assert "https://x/mau.png" not in ra
    assert bon and bon[0]["url"] == "https://x/mau.png"


# ── tách hits_for / render (nền của backend hipporag_kb) ─────────────────────


def test_render_chi_can_text():
    from noble_agent.agent.rag import kb_service_adapter as ksa

    out = ksa.render([{"text": "Noble Crystal ở Tây Hồ"}], None, None, None)
    assert "Noble Crystal ở Tây Hồ" in out


def test_render_do_vao_bon_dinh_kem_va_du_an():
    from noble_agent.agent.rag import kb_service_adapter as ksa
    from noble_agent.config import settings

    hits = [{"text": "abc", "project_id": "nplb", "file_public_url": "https://x.test/a.pdf", "file_name": "a.pdf"}]
    dinh_kem: list[dict] = []
    du_an: list[str] = []
    ksa.render(hits, dinh_kem, du_an, {})
    if settings.kb_search_attach_source_files:
        assert dinh_kem and dinh_kem[0]["url"] == "https://x.test/a.pdf"
    assert du_an == ["nplb"]


async def test_hits_for_query_rong_ra_rong():
    from noble_agent.agent.rag import kb_service_adapter as ksa

    assert await ksa.hits_for("  ", "", 5) == []


async def test_hits_for_khong_co_qdrant_url_ra_rong(monkeypatch):
    from noble_agent.agent.rag import kb_service_adapter as ksa
    from noble_agent.config import settings

    monkeypatch.setattr(settings, "qdrant_url", "")
    assert await ksa.hits_for("bể bơi", "", 5) == []


async def test_query_kb_service_van_di_qua_hai_ham_moi(monkeypatch):
    """Hợp đồng của lần tách: đường cũ phải là `render(await hits_for(...))`."""
    from noble_agent.agent.rag import kb_service_adapter as ksa

    goi: dict = {}

    async def fake_hits(query, project_filter, limit):
        goi["hits_for"] = (query, project_filter, limit)
        return [{"text": "abc"}]

    def fake_render(hits, dinh_kem, du_an, numbers):
        goi["render"] = len(hits)
        return "DA_RENDER"

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(ksa, "render", fake_render)
    out = await ksa.query_kb_service_for_noble_kb("bể bơi", "nplb", top_k=3)
    assert out == "DA_RENDER"
    assert goi["hits_for"] == ("bể bơi", "nplb", 3)
    assert goi["render"] == 1
