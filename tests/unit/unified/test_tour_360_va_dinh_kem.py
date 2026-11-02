"""Hai đường mới của pha 2: thẻ tour 360 và tệp kèm từ kb_search.

Cả hai tồn tại vì CÙNG MỘT lý do: khi một đường dẫn nằm trong `text`, LLM phải CHÉP LẠI nó
để trả lời khách, và một URL dài nhiều tham số thì chép sai là chuyện sẽ xảy ra. Đưa đường
dẫn vào payload/`items` thì client tự render và LLM không bao giờ chạm vào chuỗi.
"""

import json

from noble_agent.agent.rag import kb_service_adapter as ad
from noble_agent.agent.tools import noble_search
from noble_agent.agent.tools.dispatcher import _strip_display_items
from noble_agent.data import media_data as md

_LINK_TOUR = "https://kuula.co/share/collection/7l8Rt?logo=1&info=1&fs=1&vr=0&sd=1&thumbs=1"


# ── thẻ tour 360 ─────────────────────────────────────────────────────────────


def test_tour_360_thanh_the_tour_chu_khong_bi_loai():
    """Link kuula KHÔNG có đuôi ảnh và KHÔNG phải host YouTube, nên trước 2026-08-14 nó rơi
    vào nhánh cuối của `_hit_to_item` và bị loại IM LẶNG — đúng lý do thiết kế cũ đã loại
    đường media cho tour 360."""
    item = md._hit_to_item({"media_url": _LINK_TOUR, "content_type": "tour_360", "caption": "Tour ABC"})
    assert item == {"kind": "tour", "url": _LINK_TOUR, "label": "Tour ABC"}


def test_tour_nhan_theo_content_type_khong_theo_hinh_dang_url():
    """Nhận theo hình dạng URL là đoán; host tour có thể là kuula, matterport, hay gì khác."""
    item = md._hit_to_item({"media_url": "https://my.matterport.com/show/?m=abc", "content_type": "tour_360"})
    assert item is not None and item["kind"] == "tour"


def test_url_tour_ma_content_type_la_video_thi_KHONG_ra_the_tour():
    """Phép đo phải phân biệt được "nhận theo content_type" với "nhận mọi URL lạ".

    Từ 2026-08-25 một `content_type="video"` không còn bị bỏ — nó ra `video{url}`. Điều
    bài này canh vẫn NGUYÊN: nó KHÔNG được ra thẻ `tour`, vì tour nhận theo
    `content_type` chứ không theo hình dạng URL. Đổi `is None` thành `!= "tour"` giữ
    đúng ý định gốc thay vì neo vào một hệ quả đã thay đổi.
    """
    item = md._hit_to_item({"media_url": _LINK_TOUR, "content_type": "video"})
    assert item is not None
    assert item["kind"] == "video" and "video_id" not in item


def test_link_tour_bi_gan_nham_content_type_image_thi_ra_ANH_VO():
    """Ghim một bẫy DỮ LIỆU, không phải một hành vi mong muốn.

    `content_type == "image"` buộc thành thẻ ảnh bất kể URL, nên một link tour bị gán nhầm
    `image` sẽ ra `<img src="https://kuula.co/…">` — icon ảnh vỡ ở cả lưới lẫn lightbox, và
    không bấm ra link được. Đây đúng là điều thiết kế 2026-08-07 dự đoán khi loại đường
    media cho tour 360, và là lý do Portal phải ghi `content_type = "tour_360"` cho đúng.
    """
    item = md._hit_to_item({"media_url": _LINK_TOUR, "content_type": "image"})
    assert item is not None and item["kind"] == "image", "ghi nhầm content_type ⇒ ảnh vỡ, không phải bị loại"


def test_tour_dung_dau_va_co_ro_rieng_khong_canh_tranh_slot_anh():
    """Một dự án nhiều ảnh không được đẩy tour ra khỏi kết quả đúng lúc khách hỏi tour."""
    hits = [{"media_url": f"https://x/a{i}.jpg", "content_type": "image"} for i in range(md.MAX_IMAGES + 3)]
    hits.append({"media_url": _LINK_TOUR, "content_type": "tour_360", "caption": "Tour"})
    items = md._map_items(hits)
    assert items[0]["kind"] == "tour"
    assert sum(1 for i in items if i["kind"] == "tour") == md.MAX_TOURS
    assert sum(1 for i in items if i["kind"] == "image") == md.MAX_IMAGES


def test_tour_360_la_gia_tri_hop_le_cua_tham_so_cong_cu():
    """Bộ giá trị này được kiểm NGUYÊN VĂN ở tầng tool, nên thiếu nó là mọi lượt khách xin
    tour đều bị trả về lỗi tham số."""
    from noble_agent.agent.tools.schemas import SEND_MEDIA_CONTENT_TYPES

    assert "tour_360" in SEND_MEDIA_CONTENT_TYPES


# ── tệp kèm từ kb_search ─────────────────────────────────────────────────────


def _hit(**kw) -> dict:
    return {"text": "nội dung", "project_name": "Dự án A", **kw}


def test_dinh_kem_lay_url_ten_thumb_va_trang():
    ra = ad._dinh_kem(
        [
            _hit(
                file_public_url="https://x/api/v1/public/files/t/csbh.pdf",
                file_name="CSBH quý 3.pdf",
                thumb_url="https://x/thumb.webp",
                page=2,
            )
        ]
    )
    assert ra == [
        {
            "kind": "file",
            "url": "https://x/api/v1/public/files/t/csbh.pdf",
            "label": "CSBH quý 3.pdf",
            "thumb": "https://x/thumb.webp",
            "page": 2,
        }
    ]


def test_dinh_kem_loai_trung_theo_url():
    """Một tài liệu 12 chunk mà 3 chunk cùng khớp thì khách không cần nhận cùng tệp ba lần."""
    h = _hit(file_public_url="https://x/a.pdf", file_name="A")
    assert len(ad._dinh_kem([h, dict(h), dict(h)])) == 1


def test_hit_khong_co_tep_thi_khong_sinh_dinh_kem():
    assert ad._dinh_kem([_hit(), _hit(file_public_url="  ")]) == []


def test_dinh_kem_thieu_ten_thi_roi_ve_muc_section():
    ra = ad._dinh_kem([_hit(file_public_url="https://x/a.pdf", section_path=["Chính sách", "Đợt 2"])])
    assert ra[0]["label"] == "Đợt 2"


def test_trang_bang_khong_khong_vao_dinh_kem():
    """`page=0` nghĩa là "không áp dụng" (tài liệu một trang, hay ảnh CSBH), không phải trang số 0."""
    ra = ad._dinh_kem([_hit(file_public_url="https://x/a.pdf", file_name="A", page=0)])
    assert "page" not in ra[0]


# ── section_path ─────────────────────────────────────────────────────────────


def test_format_uu_tien_section_path_lay_phan_tu_cuoi():
    out = ad._format_kb_hits([_hit(section_path=["Chính sách bán hàng", "Đợt 2/2026", "Ưu đãi"])])
    assert "[Dự án A › Ưu đãi]" in out


def test_format_roi_ve_khoa_section_cho_point_cu():
    """Portal ghi CẢ HAI khoá trong một pha rồi mới bỏ `section` — chỗ này phải đọc được cả
    hai, không thì tiêu đề khối mất tên mục trong khoảng giữa hai lần deploy."""
    out = ad._format_kb_hits([_hit(section="Tiện ích")])
    assert "[Dự án A › Tiện ích]" in out


def test_section_path_rong_khong_lam_no():
    out = ad._format_kb_hits([_hit(section_path=[])])
    assert "[Dự án A]" in out


# ── hình dạng trả về của kb_search ───────────────────────────────────────────


class _RagGia:
    def __init__(self, context: str, dinh_kem: list[dict]) -> None:
        self._context = context
        self._dinh_kem = dinh_kem

    async def search(self, *, query, project_filter, dinh_kem=None):
        if dinh_kem is not None:
            dinh_kem.extend(self._dinh_kem)
        return self._context


class _DispatcherGia:
    class _Kh:
        project_interest = None

    customer = _Kh()

    def mark_customer_dirty(self) -> None:
        pass


async def test_khong_co_tep_thi_tra_CHUOI_TRAN(monkeypatch):
    """Hình dạng CÓ CỔNG, cố ý: `kb_search` là tool dùng nhiều nhất và mọi luật prompt về nó
    viết cho một chuỗi ngữ cảnh. Bọc JSON vô điều kiện là đặt 100% câu trả lời vào rủi ro để
    phục vụ thiểu số lượt có tệp."""
    ra = await noble_search.run(_RagGia("ngữ cảnh", []), _DispatcherGia(), {"query": "q"})
    assert ra == "ngữ cảnh"


async def test_co_tep_thi_tra_JSON_co_context_va_items():
    ra = await noble_search.run(
        _RagGia("ngữ cảnh", [{"kind": "file", "url": "https://x/a.pdf", "label": "A"}]),
        _DispatcherGia(),
        {"query": "q"},
    )
    data = json.loads(ra)
    assert data["context"] == "ngữ cảnh"
    assert data["items"][0]["url"] == "https://x/a.pdf"


def test_items_bi_luoc_khoi_ngu_canh_LLM_nhung_context_o_lai():
    """`items` chỉ để client render; giữ nó trong lịch sử là phình mọi lượt sau."""
    goc = json.dumps({"context": "ngữ cảnh", "items": [{"kind": "file", "url": "https://x/a.pdf"}]})
    con_lai = json.loads(_strip_display_items("kb_search", goc))
    assert con_lai == {"context": "ngữ cảnh"}


def test_chuoi_tran_di_qua_bo_luoc_nguyen_van():
    assert _strip_display_items("kb_search", "ngữ cảnh trần") == "ngữ cảnh trần"


# ─── Đính kèm tệp nguồn: TẮT mặc định (2026-08-26) ────────────────────────────


class _RagChiDinhKem:
    """RAG biết `dinh_kem` mà CHƯA biết `du_an` — bậc giữa của thang fallback."""

    def __init__(self, context, dinh_kem):
        self._context, self._dinh_kem = context, dinh_kem

    async def search(self, *, query, project_filter, dinh_kem=None):
        if dinh_kem is not None:
            dinh_kem.extend(self._dinh_kem)
        return self._context


async def test_rag_biet_dinh_kem_ma_chua_biet_du_an_van_giu_tep():
    """Một `except TypeError` bao trọn sẽ làm RAG dạng này mất LUÔN `dinh_kem` —
    tệp nguồn im lặng không tới client. Bậc giữa của thang giữ đúng cái nó biết."""
    ra = await noble_search.run(
        _RagChiDinhKem("ngữ cảnh", [{"kind": "file", "url": "https://x/a.pdf", "label": "A"}]),
        _DispatcherGia(),
        {"query": "q"},
    )

    assert json.loads(ra)["items"][0]["url"] == "https://x/a.pdf"
