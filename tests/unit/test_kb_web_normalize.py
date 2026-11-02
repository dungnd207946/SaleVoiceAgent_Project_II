import unicodedata

import pytest

from portal.modules.kb.web.normalize import (
    NON_PROJECT_PREFIXES,
    canonical_url,
    clean_labels,
    contains_word,
    content_hash,
    display_project,
    domain_of,
    fold,
    is_non_project,
    mentions_project,
    norm_project,
    project_labels,
    project_matches,
    project_names,
    same_project,
    strip_accents,
    tag_projects,
    twin_names,
)


def test_bo_tham_so_theo_doi_va_neo():
    u = "https://CafeF.vn/bai-viet.chn/?utm_source=fb&id=3&fbclid=x#top"
    assert canonical_url(u) == "https://cafef.vn/bai-viet.chn?id=3"


def test_domain_bo_www():
    assert domain_of("https://www.savills.com.vn/research") == "savills.com.vn"


def test_bam_khong_phu_thuoc_khoang_trang_va_hoa_thuong():
    assert content_hash("Cầu  Hồng Hà\nkhởi công") == content_hash("cầu hồng hà khởi công")
    assert content_hash("   ") == ""


def test_lam_sach_nhan_nhu_qwen_tra_ve():
    assert clean_labels(["Hà Nội", "Cầu Giấy", "Cầu Giấy", None, "", "null", " Tây Hà Nội "]) == (
        "Hà Nội",
        "Cầu Giấy",
        "Tây Hà Nội",
    )


# --- edge case: canonical_url ---


def test_canonical_url_goc_co_slash_cuoi_giu_nguyen():
    assert canonical_url("https://example.com/") == "https://example.com/"


def test_canonical_url_khong_path_them_slash_goc():
    assert canonical_url("https://example.com") == "https://example.com/"


def test_canonical_url_bo_cong_mac_dinh():
    assert canonical_url("https://example.com:443/foo") == "https://example.com/foo"
    assert canonical_url("http://example.com:80/foo") == "http://example.com/foo"


def test_canonical_url_giu_cong_khong_mac_dinh():
    assert canonical_url("https://example.com:8443/foo") == "https://example.com:8443/foo"


def test_canonical_url_ha_scheme_hoa():
    assert canonical_url("HTTPS://Example.COM/x") == "https://example.com/x"


def test_canonical_url_het_query_sau_khi_loc_thi_khong_con_dau_hoi():
    assert canonical_url("https://example.com/x?utm_source=a") == "https://example.com/x"


def test_canonical_url_utm_khong_phan_biet_hoa_thuong():
    assert canonical_url("https://example.com/x?UTM_Source=a") == "https://example.com/x"


def test_canonical_url_khong_bo_www_o_host():
    # domain_of() mới bỏ "www." — canonical_url() giữ nguyên host, chỉ chuẩn hoá chữ thường.
    assert canonical_url("https://WWW.example.com/x") == "https://www.example.com/x"


def test_canonical_url_input_khong_phai_http_khong_nem():
    assert canonical_url("not a url") == "not a url"


def test_canonical_url_scheme_khac_http_van_chay():
    assert canonical_url("ftp://foo.com/bar/") == "ftp://foo.com/bar"


# --- edge case: fold / contains_word ---


def test_fold_dong_nhat_d_hoa_thuong():
    assert fold("Đ") == fold("đ")


def test_fold_gap_dau_to_hop_va_dau_dung_san():
    to_hop = "Hòa"  # h, o, dấu huyền tổ hợp (U+0300), a
    dung_san = "Hòa"
    assert fold(to_hop) == fold(dung_san)


def test_contains_word_khong_khop_ben_trong_tu_dai_hon():
    hay = fold("đan phượngg")
    assert contains_word(hay, "Đan Phượng") is False


def test_contains_word_khop_dung_ranh_gioi_tu():
    hay = fold("huyện đan phượng, hà nội")
    assert contains_word(hay, "Đan Phượng") is True


def test_contains_word_needle_rong_khong_khop():
    assert contains_word(fold("bất kỳ"), "") is False


def test_contains_word_hay_rong_khong_khop():
    assert contains_word("", "Đan Phượng") is False


# --- edge case: clean_labels ---


def test_clean_labels_danh_sach_rong():
    assert clean_labels([]) == ()
    assert clean_labels(None) == ()


def test_clean_labels_bo_qua_phan_tu_khong_phai_chuoi():
    assert clean_labels(["Hà Nội", 3, {"x": 1}, None, "Hà Nội"]) == ("Hà Nội",)


def test_clean_labels_giu_thu_tu_xuat_hien_dau_tien():
    assert clean_labels(["b", "A", "a", "B"]) == ("b", "A")


# ─── tên dự án: dạng chuẩn hoá và luật khớp (ví dụ thật từ lượt chạy 2026-10-01) ──


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("VINHOMES GOLDEN CITY", "vinhomes golden city"),
        ("VINHOMES GLOBAL GATE (TMDV)", "vinhomes global gate"),
        ("Vinhomes Golden City Dương Kinh", "vinhomes golden city dương kinh"),
        ("Vinhomes Ocean Park 3 - The Crown", "vinhomes ocean park 3 - the crown"),
        ("  [Mới]  Vinhomes   Royal Island ", "vinhomes royal island"),
        ("Wonder City (giai đoạn 2) [Hà Nội]", "wonder city"),
        ("Dự án X.", "dự án x"),
        ("", ""),
    ],
)
def test_norm_project(raw, want):
    assert norm_project(raw) == want


def test_norm_project_nfc_giu_dau():
    decomposed = unicodedata.normalize("NFD", "Vinhomes Golden City Dương Kinh")
    assert norm_project(decomposed) == "vinhomes golden city dương kinh"


def test_project_labels_chuan_hoa_bo_rong_bo_trung():
    got = project_labels(["VINHOMES GOLDEN CITY", "Vinhomes Golden City", "(TMDV)", None, "null", " "])
    assert got == ("vinhomes golden city",)


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("vinhomes golden city", "VINHOMES GOLDEN CITY"),
        ("vinhomes golden city dương kinh", "VINHOMES GOLDEN CITY"),
        ("vinhomes ocean park 3 - the crown", "Vinhomes Ocean Park 3"),
        ("vinhomes global gate", "VINHOMES GLOBAL GATE (TMDV)"),
    ],
)
def test_project_matches_ten_va_bien_the_co_duoi(label, name):
    assert project_matches(label, name)


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("vinhomes ocean park 2", "Vinhomes Ocean Park"),
        ("vinhomes ocean park 3 - the crown", "Vinhomes Ocean Park"),
        ("vinhomes golden cityx", "Vinhomes Golden City"),
        ("vinhomes golden", "Vinhomes Golden City"),
        ("royal island", "Vinhomes Royal Island"),
        ("x", ""),
    ],
)
def test_project_matches_khong_khop(label, name):
    assert not project_matches(label, name)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("royal island", "Vinhomes Royal Island"),
        ("Vinhomes Royal Island", "royal island"),
        ("vinhomes golden city dương kinh", "VINHOMES GOLDEN CITY"),
        ("VINHOMES GOLDEN CITY", "vinhomes golden city dương kinh"),
        ("vinhomes global gate", "VINHOMES GLOBAL GATE (TMDV)"),
    ],
)
def test_same_project_hai_chieu_tien_to_hau_to(a, b):
    assert same_project(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("vinhomes ocean park 2", "Vinhomes Ocean Park"),
        ("Vinhomes Ocean Park", "vinhomes ocean park 2"),
        ("wonder city", "Noble Palace Tây Thăng Long"),
        ("", "Wonder City"),
    ],
)
def test_same_project_du_an_khac(a, b):
    assert not same_project(a, b)


def test_mentions_project_ten_day_du_hoac_bo_tu_dau_khi_co_3_tu():
    assert mentions_project("Vinhomes Royal Island ở Vũ Yên [1].", "vinhomes royal island")
    assert mentions_project("Royal Island có bến du thuyền [1].", "Vinhomes Royal Island")
    assert mentions_project("WONDER CITY bàn giao [1].", "wonder city")
    assert not mentions_project("City mới bàn giao [1].", "Wonder City")
    assert not mentions_project("Vinhomes Golden City bàn giao [1].", "Vinhomes Royal Island")
    assert not mentions_project("Royal Islands [1].", "Vinhomes Royal Island")


def test_mentions_project_gach_va_dau_va_coi_nhu_khoang_trang():
    assert mentions_project("Vinhomes Ocean Park 3 – The Crown mở bán [1].", "vinhomes ocean park 3 - the crown")
    assert mentions_project("Vinhomes Ocean Park 3 - The Crown [1].", "Vinhomes Ocean Park 3 — The Crown")
    assert mentions_project("Ocean Park 3 The Crown [1].", "vinhomes ocean park 3 - the crown")
    assert mentions_project("Sun & Moon Tower [1].", "Sun - Moon Tower")
    assert not mentions_project("Vinhomes Ocean Park 3 [1].", "vinhomes ocean park 3 - the crown")


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("VINHOMES GLOBAL GATE (TMDV)", "VINHOMES GLOBAL GATE"),
        ("  Vinhomes   Royal Island [Mới] ", "Vinhomes Royal Island"),
        ("Noble Palace Tây Thăng Long", "Noble Palace Tây Thăng Long"),
    ],
)
def test_display_project_bo_ngoac_giu_hoa_thuong(raw, want):
    assert display_project(raw) == want


def test_tien_to_khong_phai_du_an_dung_danh_sach_da_chot():
    assert NON_PROJECT_PREFIXES == (
        "tuyến",
        "metro",
        "đường sắt",
        "đường",
        "cầu",
        "nút giao",
        "sân bay",
        "ga",
        "khu công nghiệp",
        "kcn",
        "bệnh viện",
        "vinmec",
        "trường",
        "sân golf",
        "vinpearl golf",
        "vinwonders",
        "trung tâm thương mại",
        "công viên",
        "cao tốc",
        "vành đai",
        "quốc lộ",
    )


@pytest.mark.parametrize(
    "name",
    [
        "Tuyến metro số 1",
        "tuyến metro số 14",
        "Metro Bến Thành - Suối Tiên",
        "Đường sắt đô thị Nhổn - Ga Hà Nội",
        "Đường Vành đai 3",
        "Cầu Tứ Liên",
        "Nút giao Mai Dịch",
        "Sân bay Long Thành",
        "Ga Hà Nội",
        "Khu công nghiệp Thủy Nguyên",
        "KCN Đình Vũ",
        "Bệnh viện Bạch Mai",
        "Vinmec Royal Island",
        "Trường Vinschool",
        "Sân golf Long Biên",
        "Vinpearl Golf Hải Phòng",
        "Trung tâm thương mại Aeon Mall",
        "Công viên Thống Nhất",
        "Cao tốc Hà Nội – Hải Phòng",
        "Vành đai 4",
        "Quốc lộ 5",
        "(Dự kiến) Tuyến metro số 2",
        "Metro",
    ],
)
def test_nhan_ha_tang_tien_ich_khong_phai_du_an(name):
    assert is_non_project(name)


@pytest.mark.parametrize(
    "name",
    [
        "Vinhomes Royal Island",
        "Gamuda Gardens",
        "Metropolis Liễu Giai",
        "The Metropole Thủ Thiêm",
        "Garden City",
        "Masteri Waterfront",
        "Noble Palace Tây Thăng Long",
        "Khu đô thị Vinhomes Ocean Park",
        "",
    ],
)
def test_ten_du_an_that_khong_bi_loc(name):
    assert not is_non_project(name)


def test_tag_projects_chuan_hoa_va_bo_ha_tang():
    raw = ["Tuyến metro số 1", "VINHOMES ROYAL ISLAND (Vũ Yên)", "Vinmec Royal Island", "Wonder City", "KCN Đình Vũ"]
    assert tag_projects(raw) == ("vinhomes royal island", "wonder city")
    assert tag_projects(None) == ()
    assert tag_projects(["Vinpearl Golf Hải Phòng", 3, None]) == ()


def test_alias_of_bat_ten_khac_cua_chinh_du_an():
    from portal.modules.kb.web.normalize import alias_of

    assert alias_of("Vinhomes Đan Phượng (tên thương mại Vinhomes Wonder City) là đại đô thị.", "VINHOMES WONDER CITY")
    assert alias_of("Dự án Ocean City (bao gồm Vinhomes Ocean Park 2 và 3) do Vingroup [2].", "VINHOMES OCEAN PARK 2")
    assert alias_of(
        "Vinhomes Global Gate (tên thương mại Vinhomes Cổ Loa) là đại đô thị.", "VINHOMES GLOBAL GATE (TMDV)"
    )
    # nhắc dự án kia nhưng không nói là tên khác/một phần của nó → vẫn là lân cận
    assert not alias_of("Ecopark là khu đô thị ở Văn Giang, gần Vinhomes Ocean Park 2.", "VINHOMES OCEAN PARK 2")
    # cụm "bao gồm" ở câu không nhắc dự án đang xét → không tính
    assert not alias_of("Tiện ích bao gồm bể bơi. Gần Vinhomes Ocean Park 2.", "VINHOMES OCEAN PARK 2")


def test_with_more_specific_lay_ten_cung_tenant_cu_the_hon():
    from portal.modules.kb.web.signal import ProjectRow, with_more_specific

    def row(i, name):
        return ProjectRow(i, f"P{i}", name, "", "", "", ())

    vgg, hl, op, op2 = (
        row(1, "VINHOMES GLOBAL GATE (TMDV)"),
        row(2, "VINHOMES GLOBAL GATE HẠ LONG"),
        row(3, "Vinhomes Ocean Park"),
        row(4, "Vinhomes Ocean Park 2"),
    )
    rows = [vgg, hl, op, op2]
    assert with_more_specific(vgg, rows).more_specific == ("vinhomes global gate hạ long",)
    assert with_more_specific(hl, rows).more_specific == ()
    # "ocean park 2" không phải biến thể của "ocean park" (đuôi mở đầu bằng số)
    assert with_more_specific(op, rows).more_specific == ()


def test_alias_of_bat_dang_ngoac_hai_chieu():
    from portal.modules.kb.web.normalize import alias_of

    text = "Vinhomes Wonder City (Vinhomes Đan Phượng) là đại đô thị [1]."
    assert alias_of(text, "VINHOMES WONDER CITY", "vinhomes đan phượng")
    assert alias_of("Vinhomes Đan Phượng (Vinhomes Wonder City) [1].", "VINHOMES WONDER CITY", "Vinhomes Đan Phượng")
    assert not alias_of(text, "VINHOMES WONDER CITY")  # không biết tên thẻ thì chỉ dựa vào cụm từ
    assert not alias_of("Ecopark gần Vinhomes Wonder City (Hà Nội).", "VINHOMES WONDER CITY", "ecopark")


def test_project_names_lay_ve_dau_ngoac_va_dang_day_du_cua_noxh():
    assert project_names("NOXH Thượng Thanh (Him Lam Thượng Thanh)") == (
        "noxh thượng thanh",
        "nhà ở xã hội thượng thanh",
        "him lam thượng thanh",
    )
    assert project_names("Khu NOXH Tân Lập") == ("khu noxh tân lập", "khu nhà ở xã hội tân lập", "nhà ở xã hội tân lập")


def test_project_names_khong_lay_ve_sau_dau_gach_va_phan_ngoac_mot_tu():
    assert project_names("Masteri West Heights – Vinhomes Smart City") == (
        "masteri west heights – vinhomes smart city",
        "masteri west heights",
    )
    assert project_names("VINHOMES GLOBAL GATE (TMDV)") == ("vinhomes global gate",)
    assert project_names("Noble Palace Tây Thăng Long") == ("noble palace tây thăng long",)


def test_strip_accents_bo_dau_va_d():
    assert strip_accents("Noble Palace Hạ Long Đông Anh") == "Noble Palace Ha Long Dong Anh"


def test_project_matches_khong_phan_biet_dau_ca_hai_phia():
    assert project_matches("noble palace ha long", "NOBLE PALACE HẠ LONG")
    assert project_matches("sunshine bay retreat vũng tàu", "SUNSHINE BAY RETREAT VUNG TAU")
    assert project_matches("noble crystal tay ho worldhotels residences", "Noble Crystal Tây Hồ")
    assert not project_matches("vinhomes ocean park 2", "Vinhomes Ocean Park")


def test_same_project_khong_dau_va_bo_dau_chung_chung():
    assert same_project("khu nhà ở xã hội tân lập", "Khu NOXH Tân Lập")
    assert same_project("noble palace ha long", "NOBLE PALACE HẠ LONG")
    assert same_project("sunrise home", "NOXH Sunrise Home Ngọc Hồi")
    assert not same_project("vinhomes ocean park 2", "Vinhomes Ocean Park 3")


def test_twin_names_chung_dau_hai_tu_va_phan_khac_khong_phai_so():
    assert twin_names("sunrise home thanh trì", "NOXH Sunrise Home Ngọc Hồi")
    assert twin_names("noble palace tây hồ", "noble palace tây thăng long"), "bên gọi còn phải kiểm cùng xã"
    assert not twin_names("vinhomes ocean park 2", "vinhomes ocean park 3")
    assert not twin_names("noble crystal tây hồ", "noble palace tây hồ")
    assert not twin_names("masteri sky quarter", "masteri sky quarter")
