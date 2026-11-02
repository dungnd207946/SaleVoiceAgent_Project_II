"""Seed phải TỪ CHỐI chạy ngoài localhost.

Script này ghi mật khẩu đã hash vào bảng users. Lỡ tay chạy nó với DSN production
là tạo một tài khoản mà mật khẩu nằm trong Makefile. Không có runbook nào bù được.
"""

import pytest
from scripts.dev_seed import MEMBERSHIP, NGUOI_DUNG, WORKSPACE, kiem_localhost

_NGUOI_TAO_WS = {tid: nguoi for tid, _, nguoi in WORKSPACE}
_ID_USER = {uid for uid, _, _, _ in NGUOI_DUNG}


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://portal_api:x@localhost:5442/portal",
        "postgresql://portal_api:x@127.0.0.1:5442/portal",
    ],
)
def test_localhost_thi_cho_chay(dsn):
    kiem_localhost(dsn)  # không raise


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://portal_api:x@db.odyssey.vn:5432/portal",
        "postgresql://portal_api:x@10.0.1.5:5432/portal",
        "postgresql://portal_api:x@localhost.evil.vn:5432/portal",
        "postgresql://portal_api:x@evil.vn/portal?host=localhost",
    ],
    ids=["ten-mien", "ip-noi-bo", "localhost-la-tien-to", "localhost-trong-query"],
)
def test_khong_phai_localhost_thi_chan(dsn):
    with pytest.raises(SystemExit):
        kiem_localhost(dsn)


def test_co_hai_user_thay_hai_bo_workspace_khac_nhau():
    """Toàn bộ ý nghĩa của seed này: đăng nhập bằng hai tài khoản phải thấy hai
    bộ workspace KHÁC NHAU.

    Bản cũ đo điều đó qua `org_id` (hai tổ chức). Tầng tổ chức đã bỏ 2026-08-15 và
    cách ly giờ do `memberships` canh — nên đo thẳng cái người dùng thấy: tập
    workspace suy từ MEMBERSHIP. Seed mà mọi user thấy cùng một bộ thì mọi bug lọc
    đều trông như chạy đúng, và không ai phát hiện ra.
    """
    thay = {}
    for uid, tid, _ in MEMBERSHIP:
        thay.setdefault(uid, set()).add(tid)
    assert len(thay) >= 2, "cần ít nhất hai user có membership"
    assert len(set(map(frozenset, thay.values()))) >= 2, "hai user đang thấy cùng một bộ workspace"


def test_moi_user_deu_thay_it_nhat_mot_workspace():
    """Một user không có membership nào đăng nhập xong rơi vào màn "tạo workspace
    đầu tiên" — hợp lệ từ 2026-08-15, nhưng KHÔNG phải thứ seed dev muốn dựng:
    người chạy `make up` cần vào thẳng một workspace có dữ liệu."""
    co_membership = {u for u, _, _ in MEMBERSHIP}
    thieu = sorted(_ID_USER - co_membership)
    assert thieu == [], f"user không có workspace nào: {thieu}"


def test_moi_membership_tro_toi_user_va_workspace_co_that():
    """THAY test "membership không lệch tổ chức" (composite FK của 0102).

    Tầng tổ chức đã bỏ, nên "lệch tổ chức" không còn là một trạng thái. Phép kiểm
    còn lại — và là phép kiểm thật sự quan trọng — là mọi dòng MEMBERSHIP phải trỏ
    tới một user và một workspace CÓ KHAI trong chính file này. Gõ sai một id ở đó
    thì `dev_seed.chay()` ném RuntimeError giữa chừng, và test này bắt được trước
    khi ai phải chạy `make up`.
    """
    thieu_user = [u for u, _, _ in MEMBERSHIP if u not in _ID_USER]
    thieu_ws = [t for _, t, _ in MEMBERSHIP if t not in _NGUOI_TAO_WS]
    assert thieu_user == [], f"MEMBERSHIP trỏ tới user không khai: {thieu_user}"
    assert thieu_ws == [], f"MEMBERSHIP trỏ tới workspace không khai: {thieu_ws}"


def test_moi_workspace_co_nguoi_tao_co_that():
    """`tenants.created_by` là FK NOT NULL (0106) — người tạo phải khai trước."""
    thieu = [(t, n) for t, _, n in WORKSPACE if n not in _ID_USER]
    assert thieu == [], f"WORKSPACE có created_by không khai trong NGUOI_DUNG: {thieu}"


def test_moi_user_co_mat_khau_rieng_va_khong_rong():
    """Hai tài khoản dùng chung một mật khẩu là mời người ta đăng nhập nhầm rồi
    kết luận sai về những gì mình vừa thấy."""
    mat_khau = [mk for _, _, mk, _ in NGUOI_DUNG]

    assert all(mat_khau) and len(set(mat_khau)) == len(mat_khau)
