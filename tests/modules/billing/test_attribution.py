"""Attribution phải không thể sai ở tầng DB.

Hai lỗ trước 0946:
① FK chỉ tham chiếu agent_keys(id) ⇒ gán được khoá của tenant KHÁC cho conversation
   ⇒ usage bị quy sai người, không gì chặn.
② ON DELETE SET NULL ⇒ xoá một khoá là toàn bộ usage quá khứ của nó rơi về
   "chưa phân loại" ⇒ mất lịch sử ai đã dùng. Đã có revoked_at cho việc thu hồi.
"""

import asyncpg
import pytest

from tests.modules.billing.conftest import TENANT


async def test_khong_gan_duoc_khoa_cua_tenant_khac(pool, workspace_billing) -> None:
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO tenant_data.conversations "
                "(tenant_id, session_id, source, agent_key_id) "
                "VALUES ($1, 'sess-lan-tenant', 'chat', $2)",
                TENANT,
                workspace_billing["key_id_khac"],
            )


async def test_khong_xoa_duoc_khoa_da_co_usage(pool, workspace_billing) -> None:
    """SQLSTATE thật là `23001 restrict_violation`, KHÔNG phải `23503
    foreign_key_violation` — hai mã khác nhau cho hai tình huống khác nhau của
    cùng một ràng buộc FK (INSERT/UPDATE trỏ tới cha không tồn tại vs DELETE/UPDATE
    bị chặn bởi RESTRICT). asyncpg map `23001` thành `RestrictViolationError`,
    KHÔNG kế thừa từ `ForeignKeyViolationError` (đã kiểm MRO) — đo được thật lúc
    chạy bài này, khác với dự đoán ban đầu."""
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(asyncpg.exceptions.RestrictViolationError):
            await conn.execute(
                "DELETE FROM control.agent_keys WHERE id = $1",
                workspace_billing["key_id"],
            )


async def test_thu_hoi_van_duoc(pool, workspace_billing) -> None:
    """Thu hồi là đường ĐÚNG — nó giữ lịch sử, khác xoá."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE control.agent_keys SET revoked_at = now() WHERE id = $1",
            workspace_billing["key_id"],
        )
        con = await conn.fetchval(
            "SELECT agent_key_id FROM tenant_data.conversations WHERE tenant_id = $1",
            TENANT,
        )
    assert con == workspace_billing["key_id"], "thu hồi không được làm mất attribution"
