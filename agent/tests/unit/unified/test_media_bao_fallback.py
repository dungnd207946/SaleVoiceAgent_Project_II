"""`search_media_detailed` phải NÓI RA rằng nó đã bỏ lọc category.

Hôm nay lượt hai không lọc chạy im lặng, nên `send_media` không phân biệt được
"đây là ảnh nội thất thật" với "không có ảnh nội thất, đây là ảnh gì cũng được".
LLM chỉ nhận `count` nên nó nói "đã gửi ảnh nội thất" cho một rổ ảnh phối cảnh.
"""

import pytest

from noble_agent.data import media_data

ANH = {
    "id": "pt-1",
    "media_url": "https://cdn/a.jpg",
    "content_type": "image",
    "caption": "Phòng ngủ",
    "project_id": "P1",
}
ANH_2 = {**ANH, "id": "pt-2", "media_url": "https://cdn/b.jpg", "caption": "Bể bơi trong nhà"}


class Ghi:
    def __init__(self, ket_qua):
        self.ket_qua = list(ket_qua)
        self.categories: list[str] = []

    async def search_hybrid(self, **kw):
        self.categories.append(getattr(kw.get("filter_"), "category_test", ""))
        return self.ket_qua.pop(0) if self.ket_qua else []


@pytest.fixture
def gia(monkeypatch):
    g = Ghi([[ANH], [ANH]])

    async def _embed_dense(texts, side="query"):
        return [[0.1] * 1024]

    async def _collection_exists(*a, **kw):
        return True

    def _scope_filter(codes, *, category=None, content_type=None, sentinel=""):
        f = type("F", (), {})()
        f.category_test = category or ""
        return f

    monkeypatch.setattr(media_data.embed_client, "embed_dense", _embed_dense)
    monkeypatch.setattr(media_data.qdrant_client, "build_scope_filter", _scope_filter)
    monkeypatch.setattr(media_data.qdrant_client, "search_hybrid", g.search_hybrid)
    monkeypatch.setattr(media_data.qdrant_client, "collection_exists", _collection_exists)
    return g


async def _tim(category: str):
    return await media_data.search_media_detailed(
        "ảnh nội thất", "P1", category, tenant_id="t1", qdrant_url="http://q", cache_ttl=0
    )


async def test_loc_co_ket_qua_thi_khong_bao_fallback(gia):
    kq = await _tim("noi_that")
    assert len(kq.items) == 1
    assert kq.category_fallback is False


async def test_loc_rong_thi_bao_fallback(gia):
    gia.ket_qua = [[], [ANH]]
    kq = await _tim("noi_that")
    assert len(kq.items) == 1
    assert kq.category_fallback is True


async def test_khong_truyen_category_thi_khong_phai_fallback(gia):
    """Không lọc từ đầu khác với bị-gỡ-lọc. Gộp hai cái là bắt LLM rào đón một
    câu trả lời vốn đã đúng ý khách."""
    gia.ket_qua = [[ANH]]
    kq = await _tim("")
    assert kq.category_fallback is False


async def test_ca_hai_luot_rong_thi_khong_bao_fallback(gia):
    """Không có gì để chọn thì không có gì để LLM lọc — đường này phải rơi về
    `no_media` như cũ, không phải rơi vào nhánh candidates rỗng."""
    gia.ket_qua = [[], []]
    kq = await _tim("noi_that")
    assert kq.items == []
    assert kq.category_fallback is False


async def test_item_mang_ref_de_llm_chon_duoc(gia):
    """Candidates cần một khoá ổn định. Dùng vị trí trong mảng thì lượt gửi phải
    tin rằng thứ tự không đổi giữa hai lời gọi — point id thì không cần tin gì."""
    gia.ket_qua = [[], [ANH, ANH_2]]
    kq = await _tim("noi_that")
    assert [i[media_data.KHOA_REF] for i in kq.items] == ["pt-1", "pt-2"]


async def test_search_media_van_tra_list_nhu_cu(gia):
    """Vỏ mỏng: hai call site còn lại (và test cũ) không phải đổi."""
    items = await media_data.search_media(
        "ảnh nội thất", "P1", "noi_that", tenant_id="t1", qdrant_url="http://q", cache_ttl=0
    )
    assert isinstance(items, list)
    assert len(items) == 1
