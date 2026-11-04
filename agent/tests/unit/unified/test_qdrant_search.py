"""KB Qdrant client — data/qdrant_search.

Generic hybrid search shared by kb_search (`<tenant>_documents`, dense+sparse) and
send_media (`<tenant>_media`, text+visual). Pins the pipeline shape the retired
query_rag / query_media services ran: one query_points call, one Prefetch per
branch carrying the SAME filter, server-side RRF fusion, limit + score_threshold
applied AFTER the fuse (so the threshold is on the RRF scale, not cosine).

Fakes `_get_client` — no Qdrant. Mirrors tests/unit/unified/rag/test_qdrant_store.py.
"""
from __future__ import annotations

import pytest

from noble_agent.data import qdrant_search as sq


class _FakePoint:
    def __init__(self, id, payload, score=0.0):
        self.id = id
        self.payload = payload
        self.score = score


class _FakeResp:
    def __init__(self, points):
        self.points = points


class _FakeClient:
    def __init__(self, points=None, exists=True):
        self.last_kwargs = None
        self.checked = None
        self._points = points if points is not None else []
        self._exists = exists

    async def query_points(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp(self._points)

    async def collection_exists(self, name):
        self.checked = name
        return self._exists


@pytest.fixture(autouse=True)
def _clear_client_cache():
    sq._clients.clear()
    yield
    sq._clients.clear()


def _fake(monkeypatch, **kw):
    c = _FakeClient(**kw)
    monkeypatch.setattr(sq, "_get_client", lambda base_url, api_key: c)
    return c


# ── collection_name ──────────────────────────────────────────────────────────


def test_collection_name_joins_tenant_and_suffix():
    assert sq.collection_name("noble-homes_k3n7_retail", "documents") == "noble-homes_k3n7_retail_documents"
    assert sq.collection_name("noble-homes_k3n7_retail", "media") == "noble-homes_k3n7_retail_media"


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_collection_name_rejects_empty_tenant(bad):
    """An empty tenant must never resolve to a real-looking collection name."""
    with pytest.raises(ValueError):
        sq.collection_name(bad, "documents")


# ── build_scope_filter ───────────────────────────────────────────────────────


def _keys(flt) -> list[str]:
    """Bỏ mệnh đề trạng thái ra để các test dưới nói về CHIỀU LỌC, không về thứ tự."""
    return [c.key for c in flt.must if c.key != sq.CHI_HIEN_KHI]


def test_scope_filter_LUON_co_menh_de_trang_thai():
    """Đây là mệnh đề DUY NHẤT ngăn nội dung nháp tới khách.

    Portal ghi point cho cả hàng nháp từ 2026-08-14, nên trước đó "nháp không tới khách" là
    một bảo đảm cấu trúc (point không tồn tại), còn bây giờ nó phụ thuộc đúng dòng này. Không
    test nào ở repo Portal bắt được nếu nó biến mất — đây là chỗ duy nhất.

    Import hằng số từ production chứ không tự khai lại chuỗi: một bản sao trong test chỉ
    chứng minh "Qdrant lọc được", không chứng minh "production có lọc".
    """
    for flt in (
        sq.build_scope_filter([]),
        sq.build_scope_filter(None),
        sq.build_scope_filter(["NPLB"]),
        sq.build_scope_filter(["NPLB"], category="tien_ich", content_type="video"),
    ):
        assert flt is not None, "không lọc gì = tìm cả nội dung nháp"
        dieu_kien = [c for c in flt.must if c.key == sq.CHI_HIEN_KHI]
        assert len(dieu_kien) == 1, [c.key for c in flt.must]
        assert dieu_kien[0].match.value == sq.TRANG_THAI_HIEN


def test_menh_de_trang_thai_la_SO_BANG_khong_phai_khac_draft():
    """`!= 'draft'` để `archived` lọt ra khách, và nó cũng nhận point THIẾU khoá — tức
    fail-open. So bằng là thứ giữ tính fail-closed."""
    cond = next(c for c in sq.build_scope_filter([]).must if c.key == sq.CHI_HIEN_KHI)
    assert cond.match is not None and getattr(cond.match, "value", None) == "published"
    assert getattr(cond.match, "except_", None) is None, "MatchExcept = fail-open"


def test_scope_filter_khong_them_dieu_kien_nao_khi_khong_co_scope():
    assert _keys(sq.build_scope_filter([])) == []
    assert _keys(sq.build_scope_filter(None)) == []


def test_scope_filter_project_unions_all_sentinel():
    """Tenant-wide docs (project_id="__ALL__") stay visible under a project scope."""
    flt = sq.build_scope_filter(["NPLB"])
    assert _keys(flt) == ["project_id"]
    cond = next(c for c in flt.must if c.key == "project_id")
    assert cond.match.any == ["NPLB", "__ALL__"]


def test_scope_filter_dedupes_explicit_sentinel():
    flt = sq.build_scope_filter(["__ALL__", "NPLB"])
    cond = next(c for c in flt.must if c.key == "project_id")
    assert cond.match.any == ["NPLB", "__ALL__"]


def test_scope_filter_category_only():
    flt = sq.build_scope_filter([], category="tien_ich")
    assert _keys(flt) == ["category"]
    cond = next(c for c in flt.must if c.key == "category")
    assert cond.match.value == "tien_ich"


def test_scope_filter_project_and_category_are_anded():
    assert _keys(sq.build_scope_filter(["NPLB"], category="tien_ich")) == ["project_id", "category"]


def test_scope_filter_ignores_blank_category():
    assert _keys(sq.build_scope_filter([], category="")) == []
    assert _keys(sq.build_scope_filter([], category="  ")) == []


def test_scope_filter_content_type_only():
    flt = sq.build_scope_filter([], content_type="video")
    assert _keys(flt) == ["content_type"]
    cond = next(c for c in flt.must if c.key == "content_type")
    assert cond.match.value == "video"


def test_scope_filter_project_category_content_type_are_all_anded():
    flt = sq.build_scope_filter(["NPLB"], category="tien_do", content_type="video")
    assert _keys(flt) == ["project_id", "category", "content_type"]


def test_scope_filter_content_type_without_category():
    """Khách xin video chung: content_type lọc, category không — đây là ca chính."""
    assert _keys(sq.build_scope_filter(["MEL"], content_type="video")) == ["project_id", "content_type"]


def test_scope_filter_ignores_blank_content_type():
    assert _keys(sq.build_scope_filter([], content_type="")) == []
    assert _keys(sq.build_scope_filter([], content_type="  ")) == []


# ── collection_exists ────────────────────────────────────────────────────────


async def test_collection_exists_passes_through(monkeypatch):
    c = _fake(monkeypatch, exists=True)
    assert await sq.collection_exists("http://q", "", "t_documents") is True
    assert c.checked == "t_documents"

    c2 = _fake(monkeypatch, exists=False)
    assert await sq.collection_exists("http://q", "", "nope") is False
    assert c2.checked == "nope"


# ── search_hybrid ────────────────────────────────────────────────────────────


async def test_search_hybrid_dense_plus_sparse(monkeypatch):
    c = _fake(
        monkeypatch,
        points=[
            _FakePoint("p1", {"project_id": "NPLB", "text": "hồ bơi"}, 1.0),
            _FakePoint("p2", {"project_id": "NPLB", "text": "view"}, 0.667),
        ],
    )
    flt = sq.build_scope_filter(["NPLB"])
    out = await sq.search_hybrid(
        base_url="http://q",
        api_key="",
        collection="t_documents",
        prefetches=[
            sq.DensePrefetch("dense", [0.1, 0.2]),
            sq.SparsePrefetch("bm25", [10, 20], [1.0, 1.0]),
        ],
        limit=5,
        filter_=flt,
    )
    # payload flattened + id/score merged in
    assert out == [
        {"project_id": "NPLB", "text": "hồ bơi", "id": "p1", "score": 1.0},
        {"project_id": "NPLB", "text": "view", "id": "p2", "score": 0.667},
    ]
    kw = c.last_kwargs
    assert kw["collection_name"] == "t_documents"
    assert kw["limit"] == 5
    assert kw["with_payload"] is True
    assert len(kw["prefetch"]) == 2
    assert kw["prefetch"][0].using == "dense"
    assert kw["prefetch"][1].using == "bm25"
    # every branch carries the same filter; no redundant top-level query_filter
    assert all(p.filter is flt for p in kw["prefetch"])
    assert "query_filter" not in kw


async def test_search_hybrid_two_dense_branches_for_media(monkeypatch):
    c = _fake(monkeypatch, points=[])
    await sq.search_hybrid(
        base_url="http://q",
        api_key="",
        collection="t_media",
        prefetches=[sq.DensePrefetch("text", [0.1]), sq.DensePrefetch("visual", [0.2, 0.3])],
        limit=10,
    )
    kw = c.last_kwargs
    assert [p.using for p in kw["prefetch"]] == ["text", "visual"]
    assert kw["prefetch"][0].query == [0.1]
    assert kw["prefetch"][1].query == [0.2, 0.3]


async def test_search_hybrid_uses_rrf_fusion(monkeypatch):
    from qdrant_client import models

    c = _fake(monkeypatch, points=[])
    await sq.search_hybrid(
        base_url="http://q", api_key="", collection="c",
        prefetches=[sq.DensePrefetch("dense", [0.1])], limit=3,
    )
    assert c.last_kwargs["query"].fusion == models.Fusion.RRF


async def test_prefetch_limit_defaults_to_wider_candidate_pool(monkeypatch):
    """Each branch prefetches max(limit*4, 20) so RRF has candidates to fuse."""
    c = _fake(monkeypatch, points=[])
    await sq.search_hybrid(
        base_url="http://q", api_key="", collection="c",
        prefetches=[sq.DensePrefetch("dense", [0.1])], limit=2,
    )
    assert c.last_kwargs["prefetch"][0].limit == 20  # max(8, 20)

    c2 = _fake(monkeypatch, points=[])
    await sq.search_hybrid(
        base_url="http://q", api_key="", collection="c",
        prefetches=[sq.DensePrefetch("dense", [0.1])], limit=10,
    )
    assert c2.last_kwargs["prefetch"][0].limit == 40  # max(40, 20)


async def test_prefetch_limit_explicit_override(monkeypatch):
    c = _fake(monkeypatch, points=[])
    await sq.search_hybrid(
        base_url="http://q", api_key="", collection="c",
        prefetches=[sq.DensePrefetch("dense", [0.1])], limit=5, prefetch_limit=7,
    )
    assert c.last_kwargs["prefetch"][0].limit == 7


async def test_score_threshold_applied_after_fuse(monkeypatch):
    c = _fake(monkeypatch, points=[])
    await sq.search_hybrid(
        base_url="http://q", api_key="", collection="c",
        prefetches=[sq.DensePrefetch("dense", [0.1])], limit=5, score_threshold=0.4,
    )
    # on the fused query, NOT on the prefetch branches (different score scale)
    assert c.last_kwargs["score_threshold"] == 0.4
    assert getattr(c.last_kwargs["prefetch"][0], "score_threshold", None) is None


async def test_no_threshold_passes_none(monkeypatch):
    c = _fake(monkeypatch, points=[])
    await sq.search_hybrid(
        base_url="http://q", api_key="", collection="c",
        prefetches=[sq.DensePrefetch("dense", [0.1])], limit=5,
    )
    assert c.last_kwargs["score_threshold"] is None


async def test_search_hybrid_rejects_empty_prefetches(monkeypatch):
    _fake(monkeypatch, points=[])
    with pytest.raises(ValueError):
        await sq.search_hybrid(base_url="http://q", api_key="", collection="c", prefetches=[], limit=5)


async def test_search_hybrid_tolerates_missing_payload(monkeypatch):
    c = _fake(monkeypatch, points=[_FakePoint("p1", None, 0.5)])
    out = await sq.search_hybrid(
        base_url="http://q", api_key="", collection="c",
        prefetches=[sq.DensePrefetch("dense", [0.1])], limit=1,
    )
    assert out == [{"id": "p1", "score": 0.5}]
    assert c.last_kwargs is not None


async def test_search_hybrid_raises_on_qdrant_error(monkeypatch):
    class _Boom:
        async def query_points(self, **kwargs):
            raise RuntimeError("qdrant down")

    monkeypatch.setattr(sq, "_get_client", lambda base_url, api_key: _Boom())
    with pytest.raises(RuntimeError):
        await sq.search_hybrid(
            base_url="http://q", api_key="", collection="c",
            prefetches=[sq.DensePrefetch("dense", [0.1])], limit=1,
        )


# ── client cache ─────────────────────────────────────────────────────────────


def test_client_cached_per_url_and_key(monkeypatch):
    made: list[tuple] = []

    class _Stub:
        def __init__(self, url=None, api_key=None):
            made.append((url, api_key))

    monkeypatch.setattr(sq, "_import_async_client", lambda: _Stub)
    a1 = sq._get_client("http://q", "k1")
    a2 = sq._get_client("http://q", "k1")
    b1 = sq._get_client("http://other", "k1")
    c1 = sq._get_client("http://q", "k2")
    assert a1 is a2  # persistent channel reused across turns
    assert b1 is not a1 and c1 is not a1
    assert len(made) == 3


def test_empty_api_key_becomes_none(monkeypatch):
    made: list[tuple] = []

    class _Stub:
        def __init__(self, url=None, api_key=None):
            made.append((url, api_key))

    monkeypatch.setattr(sq, "_import_async_client", lambda: _Stub)
    sq._get_client("http://q", "")
    assert made == [("http://q", None)]


async def test_close_all_clears_cache(monkeypatch):
    closed: list[str] = []

    class _Stub:
        def __init__(self, url=None, api_key=None):
            self.url = url

        async def close(self):
            closed.append(self.url)

    monkeypatch.setattr(sq, "_import_async_client", lambda: _Stub)
    sq._get_client("http://q", "")
    sq._get_client("http://q2", "")
    await sq.close_all()
    assert sorted(closed) == ["http://q", "http://q2"]
    assert sq._clients == {}
