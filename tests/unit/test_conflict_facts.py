from portal.modules.kb.conflicts.facts import (
    block_hash,
    chunk_hash,
    field_hash,
    has_checkable_fact,
    ordered,
    quote_found,
    same_kind,
    strip_label,
    value_in_quote,
    value_kind,
)


def test_doan_co_so_lieu_thi_kiem_duoc():
    assert has_checkable_fact("Chiết khấu 2% khi thanh toán đúng hạn")
    assert has_checkable_fact("Hiệu lực đến hết 30/11/2026")
    assert has_checkable_fact("Chủ đầu tư: Công ty Cổ phần Kinh doanh Bất động sản Noble")
    assert has_checkable_fact("Quyết định số 1499/QĐ-UBND")


def test_van_quang_cao_khong_kiem():
    assert not has_checkable_fact("Không gian sống đẳng cấp, hài hoà cùng thiên nhiên.")
    assert not has_checkable_fact("")


def test_dau_tay_khong_doi_theo_khoang_trang_va_chu_hoa():
    assert chunk_hash("Chiết  khấu 2%") == chunk_hash("chiết khấu 2%")
    assert chunk_hash("**Chiết khấu** 2%") == chunk_hash("chiết khấu 2%")
    assert chunk_hash("a").startswith("c:")


def test_dau_tay_truong_gan_dung_truong():
    assert field_hash("projects", 1, "investor", "Noble") != field_hash("projects", 1, "region", "Noble")
    assert field_hash("projects", 1, "investor", "Noble") != field_hash("projects", 2, "investor", "Noble")
    assert field_hash("projects", 1, "investor", "Noble").startswith("f:")


def test_dau_tay_khoi_khong_phu_thuoc_thu_tu():
    assert block_hash(["f:1", "f:2"]) == block_hash(["f:2", "f:1"])
    assert block_hash(["f:1"]).startswith("b:")


def test_cap_xep_thu_tu():
    assert ordered("c:b", "c:a") == ("c:a", "c:b")
    assert ordered("c:a", "c:b") == ("c:a", "c:b")


def test_trich_dan_phai_co_that():
    src = "Hiệu lực: từ 17/07/2026 đến hết **30/11/2026**"
    assert quote_found("đến hết 30/11/2026", src)
    assert not quote_found("đến hết 31/12/2026", src)
    assert not quote_found("  ", src)
    assert not quote_found("đến", src)


def test_loai_dai_luong_cua_gia_tri():
    assert value_kind("24 tháng") == "time"
    assert value_kind("12.000 đồng/m²/tháng") == "money"
    assert value_kind("70%") == "percent"
    assert value_kind("4,3 ha") == "area"
    assert value_kind("Công ty CP Bách Giang") is None


def test_cung_loai_hoac_khong_xac_dinh_thi_giu():
    assert not same_kind("24 tháng", "12.000 đồng/m²/tháng")
    assert same_kind("2 tỷ", "2.000 triệu")
    assert same_kind("Noble", "Sunshine Group")
    assert not same_kind("miễn phí", "12.000 đồng/m²/tháng")
    assert same_kind("Xây thô", "Nội thất đầy đủ")
    assert same_kind("Xây thô, hoàn thiện mặt ngoài", "Sàn gỗ chịu ẩm 12 mm, đá thạch anh khổ lớn, sảnh 40 m² ốp đá")


def test_gia_tri_phai_nam_trong_trich_dan():
    assert value_in_quote("Noblex", "CÔNG TY CỔ PHẦN TẬP ĐOÀN CÔNG NGHỆ & TÀI CHÍNH NOBLEX")
    assert value_in_quote("Xây thô, hoàn thiện mặt ngoài", "Tiêu chuẩn bàn giao: Xây thô, hoàn thiện mặt ngoài.")
    assert not value_in_quote("Noblex", "Chủ đầu tư có quyền điều chỉnh chính sách")
    assert not value_in_quote("", "bất kỳ")
    assert not value_in_quote("0 tháng", "Phí quản lý (đồng/m²/tháng): 12.000")
    assert value_in_quote("12.000 đồng/m²/tháng", "Phí quản lý (đồng/m²/tháng): 12.000")


def test_bo_nhan_truong_khoi_trich_dan():
    assert strip_label("Chủ đầu tư: Sunshine Group", "Chủ đầu tư") == "Sunshine Group"
    assert strip_label("Sunshine Group", "Chủ đầu tư") == "Sunshine Group"
