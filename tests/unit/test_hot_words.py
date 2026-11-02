"""Tách hot word (từ không phải tiếng Việt) từ tên dự án (`realestate/hot_words.py`).

Thuật toán đã chốt với người dùng (4 quy tắc ưu tiên, xem docstring
`extract_hot_words`) — mỗi test dưới đây neo lại một quyết định cụ thể trong
buổi thảo luận, không chỉ test hình dạng chung chung:
  - "SƠN" (có dấu) phải loại dù không dấu là "son" cũng trùng tiếng Anh — dấu
    thắng tuyệt đối, không cần tra từ điển Anh.
  - "KHAI" (không dấu, không phải tiếng Anh) phải loại.
  - "THE"/"BAY" (không dấu, VỪA là tiếng Anh VỪA trùng bản không dấu của một từ
    tiếng Việt "Thế"/"bay") phải GIỮ — tiếng Anh thắng tiếng Việt không dấu.
  - "MAGNOLIA"/"LUMIÈRE" (không khớp từ điển nào) phải giữ — mặc định giữ khi
    không xác định được.
"""

from portal.modules.realestate.hot_words import extract_hot_words


def test_vi_co_dau_bi_loai_du_khong_dau_trung_tieng_anh() -> None:
    assert extract_hot_words("THE MAGNOLIA - KHAI SƠN") == ["THE", "MAGNOLIA"]


def test_vi_khong_dau_khong_trung_tieng_anh_bi_loai() -> None:
    assert extract_hot_words("Khu đô thị Trung Hưng") == []


def test_tieng_anh_trung_ban_khong_dau_tieng_viet_van_duoc_giu() -> None:
    # "LONG" cũng mập mờ y hệt "BAY" ("Long" không dấu trùng địa danh "Hạ Long") —
    # cùng một đánh đổi người dùng đã chốt: tiếng Anh thắng, chấp nhận giữ nhầm.
    assert extract_hot_words("Hạ Long Bay") == ["LONG", "BAY"]
    assert extract_hot_words("The Sun City") == ["THE", "SUN", "CITY"]


def test_tu_nuoc_ngoai_khac_khong_xac_dinh_duoc_van_giu() -> None:
    assert extract_hot_words("LUMIÈRE Boulevard") == ["LUMIÈRE", "BOULEVARD"]


def test_khong_trung_lap_trong_cung_ten() -> None:
    assert extract_hot_words("Sun Sun Park") == ["SUN", "PARK"]


def test_ten_rong_tra_ve_danh_sach_rong() -> None:
    assert extract_hot_words("") == []
    assert extract_hot_words("   ") == []


def test_chi_tach_chu_bo_qua_so_va_dau_cau() -> None:
    assert extract_hot_words("Vinhomes Ocean Park 2 - Phân khu S2.03") == ["VINHOMES", "OCEAN", "PARK"]


def test_token_mot_ky_tu_bi_bo_qua() -> None:
    """Mã phân khu kiểu "S2"/"T1" rơi hết số, chỉ còn 1 chữ cái — không phải hot
    word có nghĩa, dù ký tự đó tình cờ nằm trong từ điển Anh (vd "s" = viết tắt)."""
    assert extract_hot_words("S2 - T1") == []
