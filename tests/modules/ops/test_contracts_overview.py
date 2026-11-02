"""Cổng hình dạng hợp đồng overview — chạy không cần DB.

Kiểm những thứ mà một lỗi ở đó không làm test khác đỏ mà chỉ làm màn hiện
`undefined`: tên field camelCase, và bất biến "tổng = tổng các phần".
"""

from datetime import date

from portal.modules.ops.contracts import (
    SO_NGAY,
    DanhGiaOut,
    HoiThoaiOut,
    KenhOut,
    KienThucOut,
    MocOut,
    MucKienThucOut,
    NgayOut,
    OverviewOut,
)


def test_field_dto_dat_camel_case():
    """Field snake_case lọt ra JSON là màn đọc `undefined` — không nổ, không ai thấy."""
    khoa = set(OverviewOut.model_fields)
    assert khoa == {"moc", "hoiThoai", "chuyenSale", "danhGia", "kienThuc"}
    assert set(HoiThoaiOut.model_fields) == {"tong", "truoc", "theoNgay", "theoKenh"}
    assert set(MucKienThucOut.model_fields) == {"khoa", "thay", "tong"}


def test_ngay_out_tu_tinh_tong():
    """`tong` là tổng ba nhánh, KHÔNG nhận từ ngoài: hai nguồn cho một con số
    là hai chỗ để lệch, và biểu đồ vẽ theo nhánh còn nhãn đọc theo tổng.

    `computed_field` KHÔNG nằm trong `model_fields` — nó ở
    `model_computed_fields`. Kiểm cả hai chỗ để không ai "sửa" nó thành field
    nhận-từ-ngoài rồi thấy test vẫn xanh."""
    assert set(NgayOut.model_fields) == {"ngay", "chat", "voice", "khac"}
    assert set(NgayOut.model_computed_fields) == {"tong"}

    n = NgayOut(ngay=date(2026, 8, 13), chat=20, voice=13, khac=4)
    assert n.tong == 37
    # Và nó phải RA JSON — biểu đồ đọc `tong` từ đó.
    assert n.model_dump()["tong"] == 37


def test_so_ngay_la_bay():
    assert SO_NGAY == 7


def test_khoa_kien_thuc_du_nam_muc():
    kt = KienThucOut(
        muc=[MucKienThucOut(khoa=k, thay=1, tong=2) for k in ("duAn", "phanKhu", "can", "taiLieuTraCuu", "kyNang")]
    )
    assert [m.khoa for m in kt.muc] == [
        "duAn",
        "phanKhu",
        "can",
        "taiLieuTraCuu",
        "kyNang",
    ]


def test_danh_gia_truoc_cho_phep_none():
    """Kỳ trước chưa có lượt đánh giá nào ⇒ `truoc = None`, KHÔNG phải 0.0.
    0.0 vẽ ra mũi tên «giảm 4,33» trên một kỳ chưa từng có số."""
    d = DanhGiaOut(trungBinh=4.33, truoc=None, tong=190, theoSao={"1": 4, "2": 8, "3": 20, "4": 48, "5": 110})
    assert d.truoc is None


def test_moc_va_kenh_giu_nguon_tho():
    m = MocOut(tuNgay=date(2026, 8, 7), tinhDen=date(2026, 8, 13))
    assert m.tuNgay < m.tinhDen
    # `kenh=None` = agent bản cũ chưa gửi `source`. Giữ None, không đổi thành "".
    assert KenhOut(kenh=None, n=8).kenh is None
