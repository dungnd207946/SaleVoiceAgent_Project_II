"""Khách đổ mọi ảnh vào `tong_quan` (đo trên prod 2026-08-25: 96%), nên lọc theo category
hay trả rỗng. Lượt hai không lọc là thứ giữ cho khách không trắng tay."""

import pytest

from noble_agent.data import media_data

HIT = {"media_url": "https://cdn/a.jpg", "content_type": "image", "caption": "Phòng ngủ", "project_id": "P1"}


class Ghi:
    def __init__(self, ket_qua: list[list[dict]]) -> None:
        self.ket_qua = list(ket_qua)
        self.categories: list[str] = []
        self.so_lan_embed = 0

    async def search_hybrid(self, **kw):
        self.categories.append(getattr(kw.get("filter_"), "category_test", ""))
        return self.ket_qua.pop(0) if self.ket_qua else []


@pytest.fixture
def gia(monkeypatch):
    g = Ghi([[HIT], [HIT]])

    async def _embed_dense(texts, side="query"):
        g.so_lan_embed += 1
        return [[0.1] * 1024]

    async def _collection_exists(*a, **kw):
        return True

    def _scope_filter(codes, *, category=None, content_type=None, sentinel=""):
        loc = type("F", (), {})()
        loc.category_test = category or ""
        return loc

    monkeypatch.setattr(media_data.embed_client, "embed_dense", _embed_dense)
    monkeypatch.setattr(media_data.qdrant_client, "build_scope_filter", _scope_filter)
    monkeypatch.setattr(media_data.qdrant_client, "search_hybrid", g.search_hybrid)
    monkeypatch.setattr(media_data.qdrant_client, "collection_exists", _collection_exists)
    return g


async def _tim(category: str):
    return await media_data.search_media(
        "ảnh nội thất", "P1", category, tenant_id="t1", qdrant_url="http://q", cache_ttl=0
    )


async def test_loc_co_ket_qua_thi_khong_roi_ve(gia):
    items = await _tim("noi_that")
    assert len(items) == 1
    assert gia.categories[0] == "noi_that"


async def test_loc_rong_thi_lay_ket_qua_khong_loc(gia):
    gia.ket_qua = [[], [HIT]]
    items = await _tim("noi_that")
    assert len(items) == 1
    assert gia.categories == ["noi_that", ""]


async def test_khong_truyen_category_thi_chi_mot_luot(gia):
    await _tim("")
    assert gia.categories == [""]


async def test_embed_chi_goi_mot_lan(gia):
    gia.ket_qua = [[], [HIT]]
    await _tim("noi_that")
    assert gia.so_lan_embed == 1, "phần đắt là embed, không phải Qdrant"
