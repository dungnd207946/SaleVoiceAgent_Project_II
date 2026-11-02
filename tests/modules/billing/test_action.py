"""Action mới phải có mặt ở CẢ code LẪN bảng control.actions.

Thiếu ở code: endpoint không khai được. Thiếu ở DB: `require()` trả 403 cho mọi
người vì `action not in q.actions`, và thông điệp nói về VAI TRÒ nên người dùng đi
xin thêm quyền cho một action không tồn tại.
"""

import asyncpg

from portal.core.auth.actions import ACTIONS, ALL_ACTIONS, NHAN_HANH_DONG


def test_action_co_trong_code() -> None:
    assert ACTIONS.BILLING_READ == "billing.read"
    assert ACTIONS.BILLING_READ in ALL_ACTIONS
    assert ACTIONS.BILLING_READ in NHAN_HANH_DONG


async def test_action_co_trong_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.actions WHERE code = 'billing.read'") == 1
        # `role_id` là chuỗi md5 sinh ra (`r_<md5>`), không phải hằng ổn định —
        # JOIN qua `control.roles` rồi xét theo TÊN vai trò, đừng assert trên id.
        ten_vai_tro = await conn.fetch(
            """SELECT r.name FROM control.role_actions ra
               JOIN control.roles r ON r.id = ra.role_id
               WHERE ra.action_code = 'billing.read'"""
        )
    assert {r["name"] for r in ten_vai_tro} == {"Quản trị"}, (
        "chỉ Quản trị được cấp billing.read — thiếu thì không ai xem được hoá đơn, "
        "thừa (Biên tập/CSKH/Người xem) là rò rỉ dữ liệu chi phí"
    )
