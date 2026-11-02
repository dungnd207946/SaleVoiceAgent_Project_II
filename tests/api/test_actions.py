"""Danh mục hành động — nguồn ở đây, FE đọc từ đây (spec §1 quyết định 5)."""

from portal.core.auth.actions import ACTIONS, ALL_ACTIONS


def test_dung_17_nhom():
    """13 nhóm gốc của PQ_01 §3.1 + `billing.read` (`0945_billing_action`,
    2026-08-20) + `audit.read` (`0956_audit_action`, 2026-08-25) + `kb_web.read`/`kb_web.write`
    (`0972_kb_web_actions`, 2026-10-05). Đếm để bắt
    việc thêm/xoá vô ý."""
    assert len(ALL_ACTIONS) == 17


def test_khong_trung_gia_tri():
    """Hai hằng số cùng giá trị = hai chỗ tưởng khác quyền mà thật ra cùng quyền."""
    gia_tri = [v for k, v in vars(ACTIONS).items() if not k.startswith("_")]
    assert len(gia_tri) == len(set(gia_tri))


def test_moi_action_dang_nhom_diem_nhom():
    """Dạng '<nhóm>.<việc>' — require() và log dựa vào dạng này để đọc được."""
    assert all("." in a and a == a.lower() for a in ALL_ACTIONS), ALL_ACTIONS
