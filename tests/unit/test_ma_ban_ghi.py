"""`core/ma_ban_ghi.py` — hai hình dạng mã, hàm thuần, không I/O.

`slug_code` trước ở `modules/ingest/chieu.py` tên `ung_vien_ma` và **chưa từng có
một bài test nào** dù docstring tự nhận là test được không cần DB. Nó chuyển sang
`core/` vì Luật 3 cấm `realestate` import ruột `ingest`.

`candidate_code` là hình dạng MỚI cho đường nhập tay (spec 2026-08-21 §3.1): mã
viết tắt từ tên người dùng gõ. HAI hàm chứ không một, vì hai đường vào nhận hai
loại nguồn khác hẳn nhau — tên thương mại là văn xuôi, `external_id` của CRM là
một UUID, và viết tắt một UUID ra chuỗi vô nghĩa.
"""

import pytest

from portal.core.ma_ban_ghi import DAI_MA_TOI_DA, candidate_code, slug_code

# ─── `candidate_code` — viết tắt, đường nhập tay ─────────────────────────────


@pytest.mark.parametrize(
    ("ten", "cho_doi"),
    [
        ("Vinhomes Ocean Park", "VOP"),
        ("Vinhomes Ocean Park 2", "VOP2"),
        ("Noble Palace Tây Thăng Long", "NPTTL"),
        ("Ecopark Grand - The Island", "EGTI"),
        ("Khu căn hộ AINA Demo", "KCHAD"),
        ("Vinhomes Global Gate Hạ Long", "VGGHL"),
    ],
)
def test_viet_tat_lay_chu_dau_moi_tu(ten: str, cho_doi: str) -> None:
    """Đo trên tên dự án THẬT của Aurora dev. Khớp lệ tay đang có trong seed
    (`VHOP2` = Vinhomes Ocean Park 2)."""
    assert candidate_code(ten) == cho_doi


def test_nhom_toan_so_giu_nguyen_khong_rut_thanh_mot_chu() -> None:
    """`"… 2"` phải ra `2`, không phải `2` bị cắt từ một số dài. Số là thứ phân
    biệt hai giai đoạn của cùng một dự án — `VOP` với `VOP2`."""
    assert candidate_code("Vinhomes Ocean Park 2") == "VOP2"
    assert candidate_code("Khu A 12 giai đoạn 3") == "KA12GD3"


def test_ten_hai_tu_ra_ma_hai_chu_va_do_la_du() -> None:
    """KHÔNG có sàn độ dài (quyết định 2026-08-21). Đụng thì đã có hậu tố `_2`,
    và đo trên 95 tên thật thì viết tắt chỉ đụng 10 so với 8 của slug — chênh
    lệch đến từ tên TRÙNG KHÍT, thứ không luật nào cứu được."""
    assert candidate_code("Akari City") == "AC"
    assert candidate_code("Sunshine City") == "SC"
    assert candidate_code("Lumière Riverside") == "LR"


def test_viet_tat_bo_dau_tieng_viet_truoc_khi_lay_chu_dau() -> None:
    """`đ` phải thay TAY: NFD không phân rã nó (một chữ cái riêng, không phải `d`
    cộng dấu), nên chỉ dựa NFD thì "Đông Anh" ra `A` chứ không `DA`."""
    assert candidate_code("Đông Anh") == "DA"
    assert candidate_code("Ước Lễ") == "UL"


def test_viet_tat_mot_tu_lay_chu_dau_cua_tu_do() -> None:
    assert candidate_code("Zurich") == "Z"


@pytest.mark.parametrize("ten", ["", "   ", "!!!", "---"])
def test_viet_tat_nguon_rong_ve_du_phong(ten: str) -> None:
    assert candidate_code(ten) == "DA"


# ─── `slug_code` — đường nạp ngoài, không đổi hình dạng ──────────────────────


@pytest.mark.parametrize(
    ("nguon", "cho_doi"),
    [
        ("ERP-PRJ-14", "ERP_PRJ_14"),
        ("Vinhomes Ocean Park 2", "VINHOMES_OCEAN_PARK_2"),
        ("a/b?c", "A_B_C"),
        ("  cách  lề  ", "CACH_LE"),
    ],
)
def test_slug_giu_tron_tung_tu(nguon: str, cho_doi: str) -> None:
    assert slug_code(nguon) == cho_doi


def test_slug_bo_dau_chu_khong_xoa_chu() -> None:
    """CỐ Ý lệch khỏi `ung_vien_ma` cũ: bản đó không bỏ dấu nên "Khu đô thị" rút
    thành `KHU_TH` — mất chữ, và hai tên khác nhau rút về cùng một mã. Chỉ ảnh
    hưởng mã SINH MỚI; mã đã lưu là bất biến nên không hàng nào đổi."""
    assert slug_code("Khu đô thị Đông Anh") == "KHU_DO_THI_DONG_ANH"


@pytest.mark.parametrize("nguon", ["", "   ", "!!!"])
def test_slug_nguon_rong_ve_du_phong(nguon: str) -> None:
    assert slug_code(nguon) == "DU_AN"


def test_slug_cat_dung_tran_do_dai() -> None:
    ma = slug_code("X" * 200)
    assert len(ma) == DAI_MA_TOI_DA


def test_slug_khong_de_lai_gach_duoi_o_hai_dau() -> None:
    ma = slug_code("-- Dự án A --")
    assert not ma.startswith("_") and not ma.endswith("_")


# ─── Cả hai ──────────────────────────────────────────────────────────────────


def test_khong_ham_nao_sinh_ra_sentinel_all() -> None:
    """`__ALL__` là row hệ thống — `POST /projects` từ chối bằng 409. Mã tự sinh
    phải không với tới được giá trị đó."""
    for f in (candidate_code, slug_code):
        assert f("__ALL__") != "__ALL__"
        assert f("all") != "__ALL__"
