"""Bốn mã lỗi của luồng mời hai nhánh. Test THUẦN — không cần Docker.

Canh MÃ và STATUS, không canh câu chữ: FE rẽ nhánh theo `code`, còn thông điệp là
thứ đổi được mà không ai phải sửa code.

⚠ Brief gốc viết `e.status` — thuộc tính thật trên `LoiPortal` là `.http` (xem
`portal/api/loi.py::LoiPortal.__init__`). Sửa test theo tên thật trước khi viết
code, theo đúng chỉ dẫn của task-3-brief.md §Step 2.
"""

from portal.modules.auth import loi


def test_user_already_member_la_ma_tung_dong_khong_phai_ngoai_le():
    """Mời 40 người mà một người đã là thành viên thì 39 người kia vẫn phải vào được."""
    assert loi.USER_ALREADY_MEMBER == "USER_ALREADY_MEMBER"
    assert isinstance(loi.USER_ALREADY_MEMBER, str)


def test_email_da_co_tai_khoan_la_409():
    e = loi.email_da_co_tai_khoan()
    assert (e.ma, e.http) == ("EMAIL_DA_CO_TAI_KHOAN", 409)


def test_can_mat_khau_la_422():
    e = loi.can_mat_khau()
    assert (e.ma, e.http) == ("INVITE_PASSWORD_REQUIRED", 422)


def test_khong_nhan_mat_khau_la_422():
    e = loi.khong_nhan_mat_khau()
    assert (e.ma, e.http) == ("INVITE_PASSWORD_NOT_ALLOWED", 422)


def test_loi_moi_khong_ton_tai_la_404_va_khac_ma_voi_invite_invalid():
    """Hai câu hỏi khác nhau: «token này chết» (người nhận hỏi, INVITE_INVALID) và
    «email này không có lời mời nào ở workspace của tôi» (admin hỏi). Gộp một mã là
    bắt FE hiện câu «hãy xin link mới» cho một admin vừa bấm Thu hồi hai lần."""
    e = loi.loi_moi_khong_ton_tai()
    assert (e.ma, e.http) == ("INVITE_NOT_FOUND", 404)
    assert e.ma != loi.loi_moi_khong_hop_le().ma
