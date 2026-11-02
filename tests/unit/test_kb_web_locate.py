"""Địa danh dự án lấy từ `address` (3 phần cuối) và nhãn so khớp đã chuẩn hoá."""

import pytest

from portal.modules.kb.web.locate import (
    address_parts,
    levels,
    location_text,
    match_labels,
    norm_place,
    old_names,
    place_labels,
)

# ─── address_parts: ví dụ người dùng chốt ────────────────────────────────────


def test_bo_phan_trung_giu_lan_cuoi():
    got = address_parts("Xã Nghĩa Trụ, Tỉnh Hưng Yên, Xã Nghĩa Trụ, Tỉnh Hưng Yên")
    assert got == ("Xã Nghĩa Trụ", "Tỉnh Hưng Yên")


def test_bo_trung_theo_ten_chuan_hoa_roi_lay_3_phan_cuoi():
    address = "Khu Đô Thị Vinhomes Ocean Park 1, Trâu Quỳ, Gia Lâm, TP Hà Nội., Xã Gia Lâm, Thành phố Hà Nội"
    assert address_parts(address) == ("Trâu Quỳ", "Xã Gia Lâm", "Thành phố Hà Nội")


def test_bo_so_nha_dau_phan():
    assert address_parts("Số 88 đường Nguyễn Văn Linh, Quận 7, TP.HCM") == ("đường Nguyễn Văn Linh", "Quận 7", "TP.HCM")


def test_dia_chi_khong_so_nha_giu_nguyen_3_phan():
    assert address_parts("Đường Lê Văn Lương, Nam Từ Liêm, Hà Nội") == ("Đường Lê Văn Lương", "Nam Từ Liêm", "Hà Nội")


# ─── address_parts: edge case ────────────────────────────────────────────────


def test_so_nha_khong_kem_chu_so_va_nhieu_khoang_trang():
    assert address_parts("97  Võ Nguyên Giáp, Hải Châu, Đà Nẵng") == ("Võ Nguyên Giáp", "Hải Châu", "Đà Nẵng")


@pytest.mark.parametrize("house", ["12A", "12/3B", "45-47", "số 9", "SỐ 9"])
def test_phan_chi_co_so_nha_bi_bo_han(house):
    assert address_parts(f"{house}, Phường Bến Nghé, Quận 1") == ("Phường Bến Nghé", "Quận 1")


def test_so_nha_dang_ghep_chu_bo_ca_khoi():
    assert address_parts("12/3B Nguyễn Trãi, Thanh Xuân, Hà Nội")[0] == "Nguyễn Trãi"


def test_khong_bo_so_nam_trong_ten_dia_danh():
    assert address_parts("Phường 7, Quận 3, TP.HCM") == ("Phường 7", "Quận 3", "TP.HCM")


def test_tach_theo_gach_ngang_co_khoang_trang():
    assert address_parts("KĐT Dương Nội - Hà Đông, Hà Nội") == ("KĐT Dương Nội", "Hà Đông", "Hà Nội")


def test_gach_noi_lien_chu_khong_tach():
    assert address_parts("Phường Hà-Đông, Hà Nội") == ("Phường Hà-Đông", "Hà Nội")


# ─── tách thêm ` - ` / ` – ` / ` & ` — địa chỉ thật từ lượt chạy 2026-10-01 ───


def test_tach_gach_ngang_mot_cap():
    assert address_parts("Xã Nghĩa Trụ - Tỉnh Hưng Yên") == ("Xã Nghĩa Trụ", "Tỉnh Hưng Yên")


def test_tach_gach_ngang_nhieu_khoang_trang():
    assert address_parts("Xã Cổ Loa -  TP Hà Nội") == ("Xã Cổ Loa", "TP Hà Nội")


def test_tach_dau_va():
    """Phần sau `&` vẫn còn dính "TP. Hải Phòng" (địa chỉ không có dấu phẩy trước tỉnh) — chấp nhận.
    Khoảng trắng được gộp và "1 " đầu phần bị coi là số nhà như mọi phần khác."""
    got = address_parts("Phường Dương Kinh & 1 phần xã Kiến Minh  TP. Hải Phòng")
    assert got == ("Phường Dương Kinh", "phần xã Kiến Minh TP. Hải Phòng")


def test_tach_gach_ngang_ba_phan():
    assert address_parts("KĐT Alluvia City - Văn Giang - Hưng Yên") == ("KĐT Alluvia City", "Văn Giang", "Hưng Yên")


def test_tach_gach_en_dash_lan_dau_phay():
    address = "Khu đô thị Vinhomes Ocean Park 3, xã Lương Tài – Nghĩa Trụ, huyện Văn Giang"
    assert address_parts(address) == ("xã Lương Tài", "Nghĩa Trụ", "huyện Văn Giang")


def test_match_labels_dia_chi_gach_ngang():
    assert match_labels(address_parts("Xã Nghĩa Trụ - Tỉnh Hưng Yên")) == ("nghĩa trụ",)


def test_bo_phan_rong_va_dau_cham_cuoi():
    assert address_parts(" , Tân Lập ,, Đan Phượng. , ") == ("Tân Lập", "Đan Phượng")


def test_it_hon_3_phan_lay_het():
    assert address_parts("Hà Nội") == ("Hà Nội",)


def test_dia_chi_rong_dung_region():
    assert address_parts("", "Hà Nội") == ("Hà Nội",)
    assert address_parts("   ", "Huyện Đan Phượng, Hà Nội") == ("Huyện Đan Phượng", "Hà Nội")


@pytest.mark.parametrize("region", ["mien_bac", "mien_nam", "mien_trung", " MIEN_BAC "])
def test_region_mien_bi_bo_qua(region):
    assert address_parts("", region) == ()


def test_dia_chi_co_thi_khong_dung_region():
    assert address_parts("Tân Lập, Đan Phượng", "Hà Nội") == ("Tân Lập", "Đan Phượng")


def test_ca_hai_rong_thi_khong_co_dia_danh():
    assert address_parts("", "") == ()
    assert address_parts(None, None) == ()  # cột DB có thể NULL


def test_dia_chi_chi_co_so_nha_thi_dung_region():
    assert address_parts("88", "Hà Nội") == ("Hà Nội",)


def test_location_text_noi_bang_dau_phay():
    assert location_text("xã Tân Lập, huyện Đan Phượng, Hà Nội") == "xã Tân Lập, huyện Đan Phượng, Hà Nội"
    assert location_text("", "mien_bac") == ""


# ─── norm_place ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("P.Long Biên", "long biên"),
        ("p. Long Biên", "long biên"),
        ("TP.HCM", "hcm"),
        ("TP HCM", "hcm"),
        ("Thành phố Hà Nội", "hà nội"),
        ("TP. Thành phố Hà Nội", "hà nội"),
        ("Quận 7", "quận 7"),
        ("Q.7", "quận 7"),
        ("H.Đan Phượng", "đan phượng"),
        ("huyện  Đan   Phượng", "đan phượng"),
        ("TX. Sơn Tây", "sơn tây"),
        ("Thị xã Sơn Tây", "sơn tây"),
        ("Thị trấn Trâu Quỳ", "trâu quỳ"),
        ("Tỉnh Hưng Yên", "hưng yên"),
        ("Xã Nghĩa Trụ", "nghĩa trụ"),
        ("Phường Bến Nghé", "bến nghé"),
        ("Phố Huế", "huế"),
        ("Đại lộ Thăng Long", "thăng long"),
        ("Khu đô thị Vinhomes Ocean Park", "vinhomes ocean park"),
        ("KĐT Dương Nội", "dương nội"),
        ("Hà Nội", "hà nội"),
    ],
)
def test_norm_place_bo_tien_to_va_ha_chu(raw, want):
    assert norm_place(raw) == want


def test_norm_place_duong_va_khong_duong_bang_nhau():
    assert norm_place("đường Lê Văn Lương") == norm_place("Lê Văn Lương") == "lê văn lương"
    assert norm_place("ĐƯỜNG LÊ VĂN LƯƠNG") == "lê văn lương"


def test_norm_place_giu_dau_tieng_viet_va_nfc():
    to_hop = "Hoài Đức"  # Hoài Đức dạng tổ hợp
    assert norm_place(to_hop) == norm_place("Hoài Đức") == "hoài đức"


def test_norm_place_khong_bo_tien_to_dung_mot_minh_hay_dinh_lien_khong_cham():
    assert norm_place("Phường") == "phường"
    assert norm_place("Phường.") == "phường"
    assert norm_place("Tphcm") == "tphcm"
    assert norm_place("Xãhội") == "xãhội"
    assert norm_place("Quảng Ninh") == "quảng ninh"  # "q" không phải tiền tố khi không có dấu chấm
    assert norm_place("Phúc Thọ") == "phúc thọ"


def test_norm_place_dia_danh_danh_so_giu_tien_to_viet_day_du():
    assert norm_place("Quận 7") == norm_place("Q.7") == norm_place("q. 7") == norm_place("QUẬN  7") == "quận 7"
    assert norm_place("Phường 7") == norm_place("P.7") == norm_place("p. 7") == "phường 7"
    assert norm_place("Phường 7") != norm_place("Quận 7")
    assert norm_place("P.7A") == "phường 7a"
    assert norm_place("H.12") == "huyện 12" and norm_place("TX.3") == "thị xã 3"
    assert norm_place("TP. 5") == "thành phố 5"
    assert norm_place("Đường 3") == "đường 3"
    assert norm_place("TP. Quận 7") == "quận 7"


def test_norm_place_ten_chu_van_bo_tien_to():
    assert norm_place("Phường Long Biên") == norm_place("P.Long Biên") == "long biên"
    assert norm_place("Quận 7 Mới") == "7 mới"  # không chỉ là số ⇒ bỏ tiền tố như thường
    assert norm_place("Phường 7AB") == "7ab"


def test_place_labels_phuong_7_khong_trung_quan_7():
    assert place_labels(["Phường 7", "Quận 7", "Q.7"]) == ("phường 7", "quận 7")


def test_norm_place_luy_dang():
    for s in ("TP. Thành phố Hà Nội", "P.Long Biên", "Quận 7", "Q.7", "P.7A", "đường Lê Văn Lương"):
        assert norm_place(norm_place(s)) == norm_place(s)


# ─── place_labels / match_labels / levels ────────────────────────────────────


def test_place_labels_chuan_hoa_bo_rong_bo_trung():
    got = place_labels(["huyện Đan Phượng", "Đan Phượng", "", None, "null", 3, "TP. Hà Nội", " Hà Nội. "])
    assert got == ("đan phượng", "hà nội")


def test_match_labels_bo_phan_cuoi_la_tinh():
    assert match_labels(("đường Lê Văn Lương", "Nam Từ Liêm", "Hà Nội")) == ("lê văn lương", "nam từ liêm")


def test_match_labels_mot_phan_thi_dung_phan_do():
    assert match_labels(("Hà Nội",)) == ("hà nội",)
    assert match_labels(()) == ()


def test_levels_tung_phan_tu_hep_ra_rong():
    labels = match_labels(address_parts("Đường Lê Văn Lương, Nam Từ Liêm, Hà Nội"))
    assert levels(labels) == [("lê văn lương",), ("nam từ liêm",)]


def test_levels_khong_co_tinh():
    labels = match_labels(address_parts("xã Tân Lập, huyện Đan Phượng, Hà Nội"))
    assert levels(labels) == [("tân lập",), ("đan phượng",)]
    assert ("hà nội",) not in levels(labels)


def test_levels_rong():
    assert levels(()) == []


def test_bo_dau_muc_so_n_truoc_dia_danh():
    from portal.modules.kb.web.locate import norm_place

    assert norm_place("số 1: xã nghĩa trụ") == "nghĩa trụ"
    assert norm_place("Số 2 - Huyện Văn Giang") == "văn giang"
    assert norm_place("Quận 7") == "quận 7"


def test_dau_phay_trong_ngoac_khong_tach_dia_chi():
    addr = (
        "Khu nhà ở xã hội Thượng Thanh, phường Bồ Đề (phường Thượng Thanh, Long Biên cũ), "
        "Phường Bồ Đề, Thành phố Hà Nội"
    )
    assert location_text(addr) == "Khu nhà ở xã hội Thượng Thanh, Phường Bồ Đề, Thành phố Hà Nội"


def test_old_names_chi_lay_ngoac_co_chu_cu_hoac_nay_la():
    addr = "Km17 Quốc lộ 32, thôn Đan Hội, xã Ô Diên (xã Tân Lập, Đan Phượng cũ), Xã Ô Diên, Thành phố Hà Nội"
    assert old_names(addr) == ("tân lập", "đan phượng")
    assert old_names("Khu đất số 5 (Huỳnh Tấn Của, Nguyễn Kim), phường Hòa Xuân, Đà Nẵng") == ()
    assert old_names("xã Uy Nỗ (nay là xã Đông Anh), Hà Nội") == ("đông anh",)
