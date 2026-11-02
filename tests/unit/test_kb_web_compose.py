from datetime import UTC, datetime

from portal.modules.kb.web.compose import (
    MAX_CARD_LOCATION,
    card_id,
    card_location,
    carry_dropped,
    digest_ids,
    dossier_ids,
    drop_negative,
    heading_of,
    is_near_item,
    item_from_payload,
    merge_same_heading,
    near_id,
    near_item,
    number_sources,
    parse_items,
    payload_of,
    point_kind,
    renumber,
    searchable,
    source_of,
    split_near,
    strip_written,
    with_near,
    with_written,
    without_negative,
)
from portal.modules.kb.web.contracts import (
    DIGEST_REGION,
    MAX_DIGEST_ITEMS,
    MAX_DOSSIER_ITEMS,
    POINT_CARD,
    POINT_DIGEST,
    POINT_DOSSIER,
    Item,
    Page,
    Source,
)

PAYLOAD_KEYS = {"kind", "text", "location", "projects", "sources", "published_at", "updated_at"}
T1 = datetime(2026, 1, 13, tzinfo=UTC)
T2 = datetime(2026, 9, 15, tzinfo=UTC)
A = Source("https://cafef.vn/a", "CafeF", T1)
B = Source("https://vnexpress.net/b", "VnExpress", T2)
C = Source("https://baoxaydung.vn/c", "Báo Xây dựng", T2)
D = Source("https://tuoitre.vn/d", "Tuổi Trẻ", T1)
E = Source("https://thanhnien.vn/e", "Thanh Niên", T2)
F = Source("https://dantri.com.vn/f", "Dân Trí", T1)


def _page(url, domain, when, text="nội dung"):
    return Page(url, domain, "tiêu đề", when, when, text, (), ())


# ---- brief tests ----------------------------------------------------------


def test_id_tat_dinh_va_khong_trung_giua_cac_loai():
    assert dossier_ids("X")[0] == dossier_ids("X")[0]
    total = set(dossier_ids("X")) | {card_id("X")} | set(digest_ids("toan_quoc"))
    assert len(total) == len(dossier_ids("X")) + 1 + len(digest_ids("toan_quoc"))


def test_danh_so_lai_item_cu_theo_danh_sach_moi():
    cu = Item("Đại lộ 10 làn [1], đã thông xe [2].", (A, B), ("X",), ())
    moi = _page("https://baoxaydung.vn/c", "baoxaydung.vn", T2)
    block, sources, texts = number_sources([moi], [cu], {"baoxaydung.vn": "Báo Xây dựng"})
    assert [s.url for s in sources] == [A.url, B.url, moi.url]
    assert texts == ["Đại lộ 10 làn [1], đã thông xe [2]."]
    assert "[3] Báo Xây dựng" in block


def test_renumber_bo_so_khong_hop_le():
    assert renumber("a [2] b [9]", (A, B), {B.url: 1}) == "a [1] b"


def test_loai_item_trich_so_ngoai_danh_sach_hoac_khong_trich():
    raw = {"items": [{"text": "đúng [1] [2]", "cites": [1, 2]}, {"text": "bịa [7]", "cites": [7]}, {"text": "trống"}]}
    items = parse_items(raw, [A, B], projects=("X",), location=("Hà Nội",), limit=10)
    assert [i.text for i in items] == ["đúng [1] [2]"]
    assert items[0].sources == (A, B)


def test_payload_dung_6_khoa_va_published_at_la_nguon_moi_nhat():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    p = payload_of(Item("x [1]", (A, B), ("X",), ("Hà Nội",)), now, kind=POINT_DOSSIER)
    assert set(p) == PAYLOAD_KEYS
    assert p["published_at"] == T2.isoformat()
    back = item_from_payload(p)
    assert back.sources == (A, B) and back.updated_at == now


# ---- ids: stability, distinctness, length, name sensitivity ----------------


def test_dossier_ids_on_dinh_qua_nhieu_lan_goi():
    assert dossier_ids("Du an X") == dossier_ids("Du an X")


def test_dossier_ids_du_do_dai_max_dossier_items():
    assert len(dossier_ids("X")) == MAX_DOSSIER_ITEMS
    assert len(set(dossier_ids("X"))) == MAX_DOSSIER_ITEMS


def test_digest_ids_du_do_dai_max_digest_items():
    assert len(digest_ids("toan_quoc")) == MAX_DIGEST_ITEMS
    assert len(set(digest_ids("toan_quoc"))) == MAX_DIGEST_ITEMS


def test_dossier_ids_khac_nhau_giua_hai_ten_du_an():
    assert set(dossier_ids("X")).isdisjoint(set(dossier_ids("Y")))


def test_card_id_khac_dossier_id_cung_ten():
    assert card_id("X") not in set(dossier_ids("X"))


def test_ten_du_an_duoc_chuan_hoa_hoa_thuong_va_khoang_trang():
    """Tên chuẩn hoá qua casefold + gộp khoảng trắng trước khi hash, nên "X" / "x" /
    " X " / "  x  " cùng trỏ một bộ id — tránh việc đổi cách gõ tên tạo id mới."""
    assert dossier_ids("X") == dossier_ids("x") == dossier_ids(" X ") == dossier_ids("  x  ")
    assert card_id("X") == card_id(" x ")


def test_id_dung_ten_chuan_hoa_du_an_ngoac_khong_tao_ho_id_moi():
    assert dossier_ids("VINHOMES GLOBAL GATE (TMDV)") == dossier_ids("Vinhomes Global Gate")
    assert card_id("VINHOMES GLOBAL GATE (TMDV)") == card_id("vinhomes global gate")
    assert card_id("Dự án X.") == card_id("dự án x")
    assert card_id("VINHOMES GOLDEN CITY") != card_id("Vinhomes Golden City Dương Kinh")


def test_payload_projects_da_chuan_hoa_ten_du_an():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    item = Item("x [1]", (A,), ("VINHOMES GLOBAL GATE (TMDV)", "Vinhomes Global Gate", "Wonder City"), ())
    assert payload_of(item, now, kind=POINT_DOSSIER)["projects"] == ["vinhomes global gate", "wonder city"]


def test_ten_vung_digest_cung_duoc_chuan_hoa_vo_hai():
    assert digest_ids("Toan Quoc") == digest_ids(" toan quoc ") == digest_ids("TOAN QUOC")


# ---- source_of --------------------------------------------------------------


def test_source_of_dung_ten_tra_ve_tu_map_khi_co():
    s = source_of(_page("https://cafef.vn/a", "cafef.vn", T1), {"cafef.vn": "CafeF"})
    assert s == Source("https://cafef.vn/a", "CafeF", T1)


def test_source_of_fallback_ve_domain_khi_khong_co_trong_map():
    s = source_of(_page("https://unknown.vn/a", "unknown.vn", T1), {"cafef.vn": "CafeF"})
    assert s.name == "unknown.vn"


# ---- number_sources: dedup, order, content body -----------------------------


def test_number_sources_khong_co_carried_van_danh_so_dung():
    p1 = _page("https://a.vn/1", "a.vn", T1)
    p2 = _page("https://b.vn/2", "b.vn", T2)
    block, sources, texts = number_sources([p1, p2], [], {})
    assert [s.url for s in sources] == [p1.url, p2.url]
    assert texts == []
    assert "[1]" in block and "[2]" in block


def test_number_sources_gop_url_trung_giua_carried_va_pages_dung_mot_so():
    cu = Item("mốc [1]", (A,), ("X",), ())
    moi_trung = _page(A.url, "cafef.vn", T1, text="nội dung thật của trang")
    block, sources, texts = number_sources([moi_trung], [cu], {"cafef.vn": "CafeF"})
    # cùng URL không được nhân đôi trong danh sách nguồn
    assert [s.url for s in sources] == [A.url]
    assert texts == ["mốc [1]"]
    # nội dung khối nguồn lấy từ Page thật (đã fetch), không rơi vào câu dự phòng
    assert "nội dung thật của trang" in block
    assert "nguồn đã dùng trong nội dung hiện có" not in block


def test_number_sources_hai_item_cu_cung_trich_mot_url_dung_chung_mot_so():
    cu1 = Item("mốc một [1]", (A,), ("X",), ())
    cu2 = Item("mốc hai [1]", (A,), ("Y",), ())
    block, sources, texts = number_sources([], [cu1, cu2], {})
    assert [s.url for s in sources] == [A.url]
    assert texts == ["mốc một [1]", "mốc hai [1]"]


def test_number_sources_khong_co_page_that_dung_cau_du_phong():
    cu = Item("mốc [1]", (A,), ("X",), ())
    block, _sources, _texts = number_sources([], [cu], {})
    assert "(nguồn đã dùng trong nội dung hiện có)" in block


# ---- renumber: extra edge cases --------------------------------------------


def test_renumber_khong_de_lai_khoang_trang_thua_truoc_dau_cau():
    assert renumber("xong [9].", (A,), {}) == "xong."


def test_renumber_trich_lap_lai_cung_mot_nguon_hai_lan():
    out = renumber("a [1] b [1] c", (A,), {A.url: 5})
    assert out == "a [5] b [5] c"


def test_renumber_ky_tu_khong_phai_so_khong_duoc_xem_la_trich_dan():
    # "[a]" không khớp \d nên giữ nguyên văn bản, không gây lỗi
    assert renumber("xem [a] thêm", (A,), {A.url: 1}) == "xem [a] thêm"


def test_renumber_giu_nguyen_xuong_dong_chi_gon_khoang_trang_ngang():
    text = "Dòng một [9].\nDòng hai [2]."
    assert renumber(text, (A, B), {B.url: 1}) == "Dòng một.\nDòng hai [1]."


def test_renumber_don_khoang_trang_thua_quanh_dau_xuong_dong():
    text = "a [9]  \n  b [1]"
    assert renumber(text, (A,), {A.url: 5}) == "a\nb [5]"


# ---- parse_items: edge cases -------------------------------------------------


def test_parse_items_loc_hop_le_truoc_roi_moi_gioi_han_limit():
    """Lọc dòng hỏng TRƯỚC, chỉ đếm dòng HỢP LỆ vào limit — dòng đầu hỏng không
    chiếm chỗ của dòng hợp lệ đứng sau nó."""
    raw = {"items": [{"text": "hỏng [9]"}, {"text": "hợp lệ [1]", "cites": [1]}]}
    items = parse_items(raw, [A], projects=(), location=(), limit=1)
    assert [i.text for i in items] == ["hợp lệ [1]"]


def test_parse_items_dung_lai_dung_luc_du_limit_dong_hop_le():
    raw = {"items": [{"text": "a [1]"}, {"text": "b [1]"}, {"text": "c [1]"}]}
    items = parse_items(raw, [A], projects=(), location=(), limit=2)
    assert [i.text for i in items] == ["a [1]", "b [1]"]


def test_parse_items_danh_so_lai_tu_toan_cuc_sang_cuc_bo_khop_dung_url():
    """Luật thiết kế: [k] trong text của item ĐÃ LƯU phải luôn == item.sources[k-1].
    LLM trích theo số TOÀN CỤC (vào bảng nguồn [1]..[n] đưa cho nó); vì item chỉ giữ
    tập con nguồn đã trích, số phải đổi sang cục bộ theo đúng thứ tự sources lưu lại."""
    raw = {"items": [{"text": "x [2] y [3].", "cites": [2, 3]}]}
    items = parse_items(raw, [A, B, C], projects=(), location=(), limit=10)
    assert len(items) == 1
    assert items[0].text == "x [1] y [2]."
    assert items[0].sources == (B, C)
    # [1] phải trỏ đúng item.sources[0]=B, [2] đúng item.sources[1]=C
    assert items[0].sources[0] is B
    assert items[0].sources[1] is C


def test_parse_items_danh_so_lai_khong_theo_thu_tu_trong_text():
    raw = {"items": [{"text": "x [3] y [1]"}]}
    items = parse_items(raw, [A, B, C], projects=(), location=(), limit=10)
    assert items[0].text == "x [2] y [1]"
    assert items[0].sources == (A, C)


def test_parse_items_trich_khong_lien_tuc_trong_danh_sach_dai_hon():
    sources6 = [A, B, C, D, E, F]
    raw = {"items": [{"text": "mốc một [2] mốc hai [5]."}]}
    items = parse_items(raw, sources6, projects=(), location=(), limit=10)
    assert items[0].text == "mốc một [1] mốc hai [2]."
    assert items[0].sources == (B, E)


def test_parse_items_roundtrip_qua_payload_giu_dung_url_cho_moi_trich_dan():
    raw = {"items": [{"text": "x [2] y [3].", "cites": [2, 3]}]}
    item = parse_items(raw, [A, B, C], projects=("X",), location=(), limit=10)[0]
    now = datetime(2026, 9, 29, tzinfo=UTC)
    back = item_from_payload(payload_of(item, now, kind=POINT_DOSSIER))
    assert back.text == item.text
    assert back.sources == item.sources

    # Carry một item KHÁC đứng TRƯỚC `back` để buộc index dịch số thật (không còn
    # là ánh xạ đồng nhất D->1,B->2,C->3 thay vì B->1,C->2) — nếu renumbering lệch
    # nguồn, phép so [k] dưới đây sẽ bắt được, khác bản trước (identity mapping
    # khiến test xanh dù renumber có sai).
    other = Item("z [1]", (D,), ("Y",), ())
    _block, sources_again, texts_again = number_sources([], [other, back], {})
    assert sources_again == [D, B, C]
    assert texts_again == ["z [1]", "x [2] y [3]."]
    # [2] trong text của back phải trỏ đúng sources_again[1], [3] đúng sources_again[2]
    assert sources_again[1] == back.sources[0] == B
    assert sources_again[2] == back.sources[1] == C


def test_parse_items_cites_chua_ky_tu_so_unicode_khong_phai_thap_phan_khong_lam_no():
    # "²" là chữ số Unicode nhưng KHÔNG phải thập phân (isdecimal() == False) —
    # dùng isdigit() cũ sẽ int("²") ném ValueError; isdecimal() tránh được lỗi đó.
    raw = {"items": [{"text": "chỉ có ký tự lạ", "cites": ["²"]}]}
    assert parse_items(raw, [A, B], projects=(), location=(), limit=10) == []


def test_parse_items_khong_co_cites_van_doc_duoc_tu_regex_trong_text():
    raw = {"items": [{"text": "đúng [1]"}]}
    items = parse_items(raw, [A], projects=("X",), location=(), limit=10)
    assert [i.text for i in items] == ["đúng [1]"]
    assert items[0].sources == (A,)


def test_parse_items_so_0_bi_coi_la_ngoai_pham_vi():
    raw = {"items": [{"text": "sai [0]", "cites": [0]}]}
    assert parse_items(raw, [A, B], projects=(), location=(), limit=10) == []


def test_parse_items_cites_chua_gia_tri_am_bi_bo_qua():
    raw = {"items": [{"text": "chỉ có số âm", "cites": [-1]}]}
    assert parse_items(raw, [A, B], projects=(), location=(), limit=10) == []


def test_parse_items_cites_tron_kieu_so_va_chuoi_khong_phai_so():
    raw = {"items": [{"text": "đúng", "cites": [1, "x", 2]}]}
    items = parse_items(raw, [A, B], projects=(), location=(), limit=10)
    assert items[0].sources == (A, B)


def test_parse_items_raw_khong_phai_dict_items_duoc_bo_qua():
    raw = {"items": [{"text": "đúng [1]"}, "chuoi_khong_hop_le", 123, None]}
    items = parse_items(raw, [A], projects=(), location=(), limit=10)
    assert [i.text for i in items] == ["đúng [1]"]


def test_parse_items_khong_co_khoa_items_dung_raw_lam_mot_dong():
    raw = {"text": "đúng [1]", "cites": [1]}
    items = parse_items(raw, [A], projects=(), location=(), limit=10)
    assert [i.text for i in items] == ["đúng [1]"]


# ---- payload_of / item_from_payload: round-trip -----------------------------


def test_payload_khong_co_nguon_nao_co_ngay_thi_published_at_la_none():
    c = Source("https://x.vn/1", "X", None)
    now = datetime(2026, 9, 29, tzinfo=UTC)
    p = payload_of(Item("y [1]", (c,), (), ()), now, kind=POINT_DOSSIER)
    assert p["published_at"] is None


def test_item_from_payload_round_trip_giu_nguyen_gio_va_mui_gio():
    now = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)
    item = Item("x [1] [2]", (A, B), ("x", "y"), ("hà nội", "hcm"))
    p = payload_of(item, now, kind=POINT_DOSSIER)
    back = item_from_payload(p)
    assert back.text == item.text
    assert back.sources == item.sources
    assert back.projects == item.projects
    assert back.location == item.location
    assert back.updated_at == now
    assert back.updated_at.tzinfo is not None


def test_payload_of_sources_la_dict_thuan_json():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    p = payload_of(Item("x [1]", (A,), (), ()), now, kind=POINT_DOSSIER)
    assert p["sources"] == [{"url": A.url, "name": A.name, "published_at": T1.isoformat()}]


def test_payload_location_da_chuan_hoa_dia_danh():
    """Payload Qdrant mang nhãn cùng dạng với cột Postgres — bỏ tiền tố hành chính, hạ chữ, bỏ trùng."""
    now = datetime(2026, 9, 29, tzinfo=UTC)
    item = Item("x [1]", (A,), ("X",), ("Huyện Đan Phượng", "Đan Phượng", "TP.HCM", "", "P.Long Biên"))
    assert payload_of(item, now, kind=POINT_DOSSIER)["location"] == ["đan phượng", "hcm", "long biên"]


# ─── dòng "(Cập nhật dd/mm/yyyy)" đầu text ───────────────────────────────────

EVE = datetime(2026, 9, 29, 17, 30, tzinfo=UTC)  # 30/09 giờ VN, 29/09 giờ UTC


def test_payload_them_dong_cap_nhat_theo_ngay_vn_cua_lan_ghi():
    p = payload_of(Item("thân [1]", (A,), (), ()), T1, kind=POINT_DOSSIER, written_at=EVE)
    assert p["text"] == "(Cập nhật 30/09/2026)\nthân [1]"
    assert p["updated_at"] == T1.isoformat()
    assert set(p) == PAYLOAD_KEYS


def test_payload_khong_truyen_written_at_thi_lay_updated_at():
    text = payload_of(Item("x [1]", (A,), (), ()), EVE, kind=POINT_DOSSIER)["text"]
    assert text.startswith("(Cập nhật 30/09/2026)\n")


def test_ghi_lai_text_da_co_dong_cap_nhat_khong_thanh_hai_dong():
    old = "(Cập nhật 01/09/2026)\nthân [1]"
    text = payload_of(Item(old, (A,), (), ()), T1, kind=POINT_DOSSIER, written_at=EVE)["text"]
    assert text == "(Cập nhật 30/09/2026)\nthân [1]"
    assert with_written(with_written("thân", EVE), EVE) == "(Cập nhật 30/09/2026)\nthân"


def test_strip_written_chi_bo_dung_mau():
    assert strip_written("(Cập nhật 30/09/2026)\nthân") == "thân"
    for keep in (
        "(Cập nhật hôm qua)\nthân",
        "(Cập nhật 1/9/2026)\nthân",
        "(Cập nhật 30/09/2026) thân",
        "Cập nhật 30/09/2026\nthân",
        "mở đầu\n(Cập nhật 30/09/2026)\nthân",
    ):
        assert strip_written(keep) == keep


def test_doc_lai_payload_bo_dong_cap_nhat():
    item = Item("thân [1]", (A,), ("X",), ())
    assert item_from_payload(payload_of(item, T1, kind=POINT_DOSSIER, written_at=EVE)).text == "thân [1]"


def test_carried_gui_llm_khong_co_dong_cap_nhat():
    cu = Item("(Cập nhật 30/09/2026)\nmục cũ [1]", (A,), (), ())
    la = Item("(Cập nhật hôm qua)\nmục lạ [1]", (A,), (), ())
    _, _, texts = number_sources([], [cu, la], {})
    assert texts == ["mục cũ [1]", "(Cập nhật hôm qua)\nmục lạ [1]"]


# ─── location của thẻ = vị trí của chính dự án (LLM trả ở cấp gốc) ──────────


def test_card_location_doc_truong_location_cap_goc():
    raw = {"text": "Vinhomes Royal Island ở đảo Vũ Yên [1].", "cites": [1], "location": ["Xã Vũ Yên", "TP. Hải Phòng"]}
    assert card_location(raw) == ("vũ yên", "hải phòng")


def test_card_location_cat_toi_da_4():
    raw = {"location": ["Phường Dương Kinh", "Xã Kiến Minh", "Quận Dương Kinh", "Hải Phòng", "Miền Bắc", "Việt Nam"]}
    assert MAX_CARD_LOCATION == 4
    assert card_location(raw) == ("dương kinh", "kiến minh", "hải phòng", "miền bắc")


def test_card_location_thieu_hoac_sai_kieu_thi_rong():
    assert card_location({"text": "x [1]"}) == ()
    assert card_location({"location": "Hà Nội"}) == ()
    assert card_location({"location": None}) == ()
    assert card_location({"location": {"xa": "Tân Lập"}}) == ()


def test_card_location_bo_gia_tri_rac():
    raw = {"location": [None, 3, {"x": 1}, ["Hà Nội"], "", "null", "  ", "Huyện Đan Phượng", "đan phượng"]}
    assert card_location(raw) == ("đan phượng",)


def test_parse_items_khong_doi_khi_co_truong_location():
    raw = {"text": "Wonder City bàn giao [1].", "cites": [1], "location": ["Đan Phượng"]}
    (item,) = parse_items(raw, [A], projects=("Wonder City",), location=("tân lập",), limit=1)
    assert item.location == ("tân lập",)
    assert set(payload_of(item, T1, kind=POINT_DOSSIER)) == PAYLOAD_KEYS


def test_payload_co_kind_tieng_viet():
    assert payload_of(Item("x [1]", (A,), ("X",), ()), T1, kind=POINT_CARD)["kind"] == "du_an_lan_can"
    assert (POINT_DOSSIER, POINT_DIGEST) == ("ho_so_du_an", "ban_tin_thi_truong")


def test_point_kind_suy_tu_dai_id():
    assert point_kind(card_id("Vinhomes Royal Island"), ("vinhomes royal island",)) == POINT_CARD
    assert point_kind(digest_ids(DIGEST_REGION)[7], ()) == POINT_DIGEST
    assert point_kind(dossier_ids("Vinhomes Royal Island")[0], ("vinhomes royal island",)) == POINT_DOSSIER
    # hồ sơ của dự án A không bị nhận là thẻ dù cùng nhãn projects
    assert point_kind(dossier_ids("A")[0], ("a",)) == POINT_DOSSIER


def test_tieu_de_nam_sau_dong_ngay_duoc_embed_nhung_khong_ve_lai_llm():
    text = with_written("nội dung [1]", EVE, "Dự án VINHOMES ROYAL ISLAND — Đảo Vũ Yên, Hải Phòng")
    assert text == "(Cập nhật 30/09/2026)\n[Dự án VINHOMES ROYAL ISLAND — Đảo Vũ Yên, Hải Phòng]\nnội dung [1]"
    assert searchable(text) == "Dự án VINHOMES ROYAL ISLAND — Đảo Vũ Yên, Hải Phòng\nnội dung [1]"
    assert strip_written(text) == "nội dung [1]"
    p = payload_of(Item("nội dung [1]", (A,), ("X",), ()), T1, kind=POINT_DOSSIER, written_at=EVE, header="Dự án X")
    assert item_from_payload(p).text == "nội dung [1]"


def test_ghi_lai_khong_nhan_doi_dong_ngay_va_tieu_de():
    once = with_written("thân [1]", EVE, "Dự án X")
    twice = with_written(once, T1, "Dự án X")
    assert twice.count("(Cập nhật") == 1 and twice.count("[Dự án X]") == 1


def test_khong_tieu_de_thi_khong_them_dong_trong():
    assert with_written("thân [1]", EVE) == "(Cập nhật 30/09/2026)\nthân [1]"
    assert searchable("(Cập nhật 30/09/2026)\nthân [1]") == "thân [1]"


def test_dong_ngoac_vuong_cua_noi_dung_khong_bi_coi_la_tieu_de_khi_khong_co_dong_ngay():
    assert strip_written("[1] mở đầu bằng trích dẫn\nthân") == "[1] mở đầu bằng trích dẫn\nthân"


def test_tach_trich_dan_gop_thanh_tung_so():
    from portal.modules.kb.web.compose import split_cites

    assert split_cites("a [20, 21].") == "a [20][21]."
    assert split_cites("b [2;3] c [3-5] d [1–2, 7]") == "b [2][3] c [3][4][5] d [1][2][7]"
    assert split_cites("khoảng quá rộng [1-40]") == "khoảng quá rộng [1-40]"
    assert split_cites("đã tách [2][3]") == "đã tách [2][3]"


def test_parse_items_trich_dan_gop_van_doi_dung_so_cuc_bo():
    raw = {"items": [{"text": "Trường Hà An [3, 5].", "cites": [3, 5]}]}
    (it,) = parse_items(raw, [A, B, C, D, E], projects=("X",), location=(), limit=5)
    assert it.text == "Trường Hà An [1][2]."
    assert [s.url for s in it.sources] == [C.url, E.url]


def test_muc_chi_khai_nguon_o_cites_duoc_gan_k_cuoi_muc():
    raw = {"items": [{"text": "Vincom Mega Mall khai trương.", "cites": [4, 2]}]}
    (it,) = parse_items(raw, [A, B, C, D], projects=("X",), location=(), limit=5)
    assert it.text == "Vincom Mega Mall khai trương. [1][2]"
    assert [s.url for s in it.sources] == [B.url, D.url]


def test_card_location_tach_dia_danh_ghep_va_bo_tieng_anh_dia_chi_dai():
    raw = {
        "location": [
            "xã Nghĩa Trụ, huyện Văn Giang, tỉnh Hưng Yên",
            "Van Giang town, Van Giang district, Hung Yen province",
            "số 1 đường đại lộ san hô khu đô thị vinhomes ocean park 2",
        ]
    }
    assert card_location(raw) == ("nghĩa trụ", "văn giang", "hưng yên")


def test_dong_gan_cac_du_an_tach_va_ghep_lai():
    text = with_near("Thân thẻ [1].", ["Alumi", "Alluvia City", "Alumi"])
    assert text == "Gần các dự án: Alumi, Alluvia City.\nThân thẻ [1]."
    assert split_near(text) == (("Alumi", "Alluvia City"), "Thân thẻ [1].")
    assert split_near("Thân thẻ [1].") == ((), "Thân thẻ [1].")
    assert with_near(text, []) == "Thân thẻ [1]."


def _src(n):
    return Source(f"https://x/{n}", f"Nguồn {n}", None)


def test_near_item_lay_cau_dau_moi_the_va_danh_so_nguon_chung():
    cards = [
        Item(
            "Gần các dự án: X.\nEcopark rộng 500 ha [2]. Câu sau [1].", (_src(1), _src(2)), ("ecopark",), ("văn giang",)
        ),
        Item("Alumi có 2.000 căn hộ.", (_src(3),), ("alumi",), ("văn giang", "hưng yên")),
    ]
    it = near_item("Alluvia City", "Văn Giang, Hưng Yên", cards, ("văn giang",), "ALLUVIA CITY")
    assert it.text == (
        "Các dự án gần Alluvia City (Văn Giang, Hưng Yên):\n"
        "- Ecopark (gần Alluvia City, văn giang): Ecopark rộng 500 ha [1].\n"
        "- Alumi (gần Alluvia City, văn giang, hưng yên): Alumi có 2.000 căn hộ. [2]"
    )
    assert [s.url for s in it.sources] == ["https://x/2", "https://x/3"]
    assert it.projects == ("ALLUVIA CITY",) and is_near_item(it)
    assert near_item("A", "", [], (), "A") is None


def test_carry_dropped_giu_muc_cu_bi_lam_roi_bo_muc_da_gop():
    new = [Item("Vị trí: dự án nằm trên đại lộ Thăng Long, cách Mỹ Đình 15 phút [1].", (_src(1),), (), ())]
    kept = Item("Vị trí: nằm trên đại lộ Thăng Long, cách Mỹ Đình 15 phút [1].", (_src(1),), (), ())
    dropped = Item("Mặt bằng giá: biệt thự rao 150 triệu/m² tháng 9/2026 [1].", (_src(2),), (), ())
    assert carry_dropped([kept, dropped], new, 24) == [*new, dropped]
    assert carry_dropped([dropped], new, 1) == new


def test_point_du_an_gan_thuoc_loai_du_an_lan_can():
    assert point_kind(near_id("Alluvia City"), ("ALLUVIA CITY",)) == POINT_CARD
    assert near_id("Alluvia City") not in {card_id("Alluvia City"), *dossier_ids("Alluvia City")}


HEADS = ("Tổng quan", "Tiện ích – Y tế", "Mặt bằng giá")


def test_heading_of_chi_nhan_nhan_trong_danh_sach():
    assert heading_of("Tiện ích – Y tế: Vinmec [1].", HEADS) == "Tiện ích – Y tế"
    assert heading_of("Vinmec là bệnh viện [1].", HEADS) == ""


def test_merge_same_heading_gop_muc_cung_nhan_va_danh_so_lai_nguon():
    items = [
        Item("Tiện ích – Y tế: Bệnh viện Vinmec [1].", (_src(1),), ("x",), ()),
        Item("Mặt bằng giá: 100 triệu/m² [1].", (_src(2),), ("x",), ()),
        Item("Tiện ích – Y tế: Phòng khám quốc tế [1][2].", (_src(3), _src(1)), ("x",), ()),
        Item("Không nhãn A [1].", (_src(4),), ("x",), ()),
        Item("Không nhãn B [1].", (_src(5),), ("x",), ()),
    ]
    got = merge_same_heading(items, HEADS)
    assert [it.text for it in got] == [
        "Tiện ích – Y tế: Bệnh viện Vinmec [1]. Phòng khám quốc tế [2][1].",
        "Mặt bằng giá: 100 triệu/m² [1].",
        "Không nhãn A [1].",
        "Không nhãn B [1].",
    ]
    assert [s.url for s in got[0].sources] == ["https://x/1", "https://x/3"]


def test_merge_same_heading_khong_gop_khi_qua_tran_tu():
    long = "Tiện ích – Y tế: " + "chữ " * 200 + "[1]."
    items = [Item(long, (_src(1),), (), ()), Item(long, (_src(2),), (), ())]
    assert len(merge_same_heading(items, HEADS)) == 2


def test_drop_negative_bo_cau_tin_xau_giu_cau_trung_tinh():
    text = (
        "Tổng diện tích 88 ha [1]. Tuy nhiên, chủ đầu tư chưa hoàn thành nghĩa vụ tài chính khiến nhà đầu tư "
        "chưa nhận được giấy chứng nhận [2]. Chính quyền tập trung tháo gỡ vướng mắc [1].\nGiá giảm sâu [3]."
    )
    assert drop_negative(text) == "Tổng diện tích 88 ha [1]. Chính quyền tập trung tháo gỡ vướng mắc [1]."


def test_without_negative_bo_muc_chi_toan_tin_xau():
    items = [
        Item("Dự án chậm bàn giao 2 năm [1].", (_src(1),), (), ()),
        Item("Mặt bằng giá: 100 triệu/m² [1]. Thị trường đóng băng [1].", (_src(1),), (), ()),
    ]
    assert [it.text for it in without_negative(items)] == ["Mặt bằng giá: 100 triệu/m² [1]."]
