"""Miền giá trị của `kiem()` phải khớp thứ DB thật chấp nhận.

Nguồn: review 2026-08-15 finding #1 #2 #4 #12 — `kiem()` từng cho qua giá trị mà
CHECK/kiểu của Postgres chắc chắn từ chối, nên khách được báo `accepted` rồi lỗi
nổ thành `CheckViolationError` mờ mịt (hoặc 500 cả lô) ở tầng chiếu.
"""

from portal.modules.ingest.hop_dong import kiem


def _loi_cua(truong: str, loi) -> list[str]:
    return [e.ly_do for e in loi if e.truong == truong]


def test_chuoi_chua_nul_bi_tu_choi():
    _, loi = kiem("project", {"name": "a\x00b"})
    assert _loi_cua("name", loi), "NUL lọt qua kiem() sẽ nổ 22P05 lúc cast ::jsonb và giết cả lô"


def test_truong_bat_buoc_chuoi_rong_bi_tu_choi():
    _, loi = kiem(
        "unit",
        {
            "projectExternalId": "P1",
            "zoneExternalId": "Z1",
            "unitCode": "",
            "saleStatus": "available",
            "productType": "chung_cu",
        },
    )
    assert _loi_cua("unitCode", loi), "unit_code có CHECK <> '' ở 0400 — chuỗi rỗng phải chặn từ kiem()"


def test_truong_bat_buoc_toan_khoang_trang_bi_tu_choi():
    _, loi = kiem("document", {"projectExternalId": "P1", "title": "   "})
    assert _loi_cua("title", loi)


def test_enum_nhieu_phan_tu_null_bi_tu_choi():
    _, loi = kiem("project", {"name": "X", "category": ["chung_cu", None]})
    assert _loi_cua("category", loi), "ARRAY chứa NULL làm `<@` ra false → CheckViolation lúc chiếu"


def test_loai_sai_kieu_khong_no_typeerror():
    # Trước bản vá: list không hashable → TypeError thoát kiem() → 500 cả lô.
    _, loi = kiem("document", {"projectExternalId": "P1", "title": "X", "loai": ["csbh"]})
    assert _loi_cua("loai", loi)


def test_loai_sai_gia_tri_bi_tu_choi():
    _, loi = kiem("document", {"projectExternalId": "P1", "title": "X", "loai": "khuyen_mai"})
    assert _loi_cua("loai", loi)


def test_khoa_cha_chuoi_rong_bi_tu_choi():
    # Finding #1: '' qua được `is None` rồi kẹt vĩnh viễn ở trạng thái chờ cha
    # không bao giờ tới (external_id có CHECK <> '' nên cha đó KHÔNG THỂ tồn tại).
    _, loi = kiem("zone", {"name": "X", "projectExternalId": ""})
    assert _loi_cua("projectExternalId", loi)


def test_khoa_cha_gia_tri_falsy_khac_bi_tu_choi():
    for xau in (0, False, "   "):
        _, loi = kiem("zone", {"name": "X", "projectExternalId": xau})
        assert _loi_cua("projectExternalId", loi), f"giá trị {xau!r} phải bị chặn"


def test_khoa_cha_so_nguyen_hop_le_van_qua():
    # ERP gửi mã cha dạng số là chuyện thật — `_giai_cha` vẫn str() nó như cũ.
    _, loi = kiem("zone", {"name": "X", "projectExternalId": 12345})
    assert not loi
