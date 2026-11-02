"""Hợp đồng của seam `/members` GHI (task-4) — `MoiThanhVienIn`/`DoiVaiTroThanhVienIn`.

KHÔNG cần DB, không cần app: đây là test của HỢP ĐỒNG, cùng khuôn
`test_contracts_user.py`. Phát hiện review round 1: năm contract mới không có
bài nào tham chiếu — validator `_chuan_hoa` (chuẩn hoá · dedup giữ thứ tự ·
`_RE_EMAIL` · `max_length=50`) có thể bị gỡ mà không bài nào trong repo đỏ. File
này là lưới cho đúng validator đó.

`KetQuaMoiOut`/`LoiMoiTungDongOut`/`MoiThanhVienRaOut` KHÔNG có bài ở đây — chúng
là model chỉ mang dữ liệu, không validator; test chúng là test Pydantic.
"""

import pytest
from pydantic import ValidationError

from portal.modules.auth.contracts import DoiVaiTroThanhVienIn, MoiThanhVienIn

ROLE_BIA = "r_bia"


def test_chuan_hoa_strip_va_lower():
    assert MoiThanhVienIn(emails=["  Foo@X.VN  "], roleId=ROLE_BIA).emails == ["foo@x.vn"]


def test_bo_trung_giu_thu_tu_khong_phan_biet_hoa_thuong():
    """`B@X.vn` coi là trùng với `b@x.vn` (so sánh SAU khi lower) — hàng đầu tiên
    thắng, thứ tự còn lại giữ nguyên theo lúc gặp lần đầu."""
    v = MoiThanhVienIn(emails=["b@x.vn", "a@x.vn", "B@X.vn"], roleId=ROLE_BIA)
    assert v.emails == ["b@x.vn", "a@x.vn"]


def test_toan_chuoi_rong_hoac_khoang_trang_bi_tu_choi():
    """Sau khi strip, mọi phần tử thành `''` và bị bỏ qua — danh sách chuẩn hoá
    rỗng, và `_chuan_hoa` từ chối rỗng tường minh ("cần ít nhất một email")."""
    with pytest.raises(ValidationError):
        MoiThanhVienIn(emails=["", "   ", "\t\n"], roleId=ROLE_BIA)


def test_email_sai_dang_bi_tu_choi_va_neu_ten_email_sai():
    with pytest.raises(ValidationError, match="khong-co-a-thuong"):
        MoiThanhVienIn(emails=["a@x.vn", "khong-co-a-thuong"], roleId=ROLE_BIA)


def test_50_email_hop_le_thi_qua():
    ds = [f"u{i}@x.vn" for i in range(50)]
    assert len(MoiThanhVienIn(emails=ds, roleId=ROLE_BIA).emails) == 50


def test_51_email_bi_tu_choi_boi_tran_max_length():
    ds = [f"u{i}@x.vn" for i in range(51)]
    with pytest.raises(ValidationError):
        MoiThanhVienIn(emails=ds, roleId=ROLE_BIA)


def test_truong_la_bi_tu_choi():
    """`extra="forbid"` — một FE cũ gửi thêm `workspaceId` (suy từ Principal, xem
    docstring `MoiThanhVienIn`) phải ăn 422, không bị âm thầm bỏ qua."""
    with pytest.raises(ValidationError):
        MoiThanhVienIn(emails=["a@x.vn"], roleId=ROLE_BIA, workspaceId="cs_anphu")


def test_doi_vai_tro_role_id_rong_bi_tu_choi():
    with pytest.raises(ValidationError):
        DoiVaiTroThanhVienIn(roleId="")
