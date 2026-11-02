"""Action `audit.read` phải có mặt ở CẢ code LẪN bảng control.actions.

Thiếu ở code: endpoint không khai được (`require()` ném ValueError lúc import).
Thiếu ở DB: `require()` trả 403 cho mọi người vì `action not in q.actions`, và
thông điệp nói về VAI TRÒ nên người dùng đi xin thêm quyền cho một action không
tồn tại. Khuôn y hệt `tests/modules/billing/test_action.py`.
"""

import asyncpg

from portal.core.auth.actions import ACTIONS, ALL_ACTIONS, NHAN_HANH_DONG


def test_action_co_trong_code() -> None:
    assert ACTIONS.AUDIT_READ == "audit.read"
    assert ACTIONS.AUDIT_READ in ALL_ACTIONS
    assert ACTIONS.AUDIT_READ in NHAN_HANH_DONG


async def test_action_co_trong_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        hang = await conn.fetchrow("SELECT group_name, sort_order FROM control.actions WHERE code = 'audit.read'")
        assert hang is not None, "0956_audit_action chưa chạy — hoặc chạy mà không INSERT"
        assert hang["group_name"] == "configure"
        assert hang["sort_order"] == 15, "nối CUỐI (15), không chen giữa như 0945"
        # `role_id` là `r_<md5>` sinh ra — JOIN qua `control.roles` rồi xét theo TÊN.
        ten_vai_tro = await conn.fetch(
            """SELECT r.name FROM control.role_actions ra
               JOIN control.roles r ON r.id = ra.role_id
               WHERE ra.action_code = 'audit.read'"""
        )
    assert {r["name"] for r in ten_vai_tro} == {"Quản trị"}, (
        "chỉ Quản trị được cấp audit.read (spec §2 #1) — thiếu thì không ai xem được "
        "nhật ký, thừa (Biên tập/CSKH/Người xem) là lộ «ai làm gì» cho người không có "
        "trách nhiệm giám sát"
    )
