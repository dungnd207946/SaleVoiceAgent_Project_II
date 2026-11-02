"""Truy vấn mà require() cần — nó trả lời "người này có được vào workspace này
không, và làm được gì". Ở `core/` vì đó là seam cách ly, cùng hạng với
current_tenant().

M2b gộp `doc_lifecycle` + `doc_membership` (M2a) thành `doc_quyen` — xem
`tests/modules/auth/test_ma_tran_quyen.py` cho các cổng của ma trận role ×
action (owner, viewer thiếu quyền, không cache). File này giữ những kịch bản
KHÔNG trùng ở đó: workspace ngoài org (không cửa owner), và cặp hết hạn/còn hạn
đối xứng bằng `du_lieu` cục bộ của chính nó.
"""

import pytest

from portal.core.auth import repo
from portal.core.auth.actions import ACTIONS

pytestmark = pytest.mark.integration

BAM_GIA = "$argon2id$v=19$m=65536,t=3,p=4$khonglaMhashthat"


@pytest.fixture
async def du_lieu(pool):
    """`cs_haven` không có membership nào — dùng để kiểm cả "ngoài org" (0104
    không seed vai trò trùng tên khiến trigger đụng UNIQUE) và cặp hết hạn/còn
    hạn ở hai test riêng bên dưới."""
    async with pool.acquire() as conn, conn.transaction():
        for tid in ("cs_anphu", "cs_haven"):
            await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", tid)
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ('u_dang', 'd@x.vn', $1, 'Đăng')",
            BAM_GIA,
        )
        r_cskh = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'CSKH'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_dang', 'cs_anphu', $1)",
            r_cskh,
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        # tenants TRƯỚC users: `tenants.created_by` là FK không CASCADE (0106).
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_%' AND created_by <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_%' AND id <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")


async def test_lifecycle_tra_dung(pool, du_lieu):
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, "u_dang", "cs_anphu")
    assert q is not None and q.lifecycle == "active"


async def test_user_khong_co_tra_none(pool, du_lieu):
    async with pool.acquire() as conn:
        assert await repo.doc_quyen(conn, "u_khong_co", "cs_anphu") is None


async def test_membership_tra_role_name_va_actions(pool, du_lieu):
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, "u_dang", "cs_anphu")
    assert q is not None and q.role_name == "CSKH"
    assert ACTIONS.CONVOS_HANDLE in q.actions
    assert ACTIONS.CATALOG_WRITE not in q.actions


async def test_ws_khong_thuoc_tra_actions_rong(pool, du_lieu):
    """`u_dang` không membership ở `cs_haven`, và không phải owner — không cửa
    nào cho vào. Khác None: user CÓ tồn tại, chỉ là actions rỗng."""
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, "u_dang", "cs_haven")
    assert q is not None
    assert q.actions == frozenset()
    assert q.role_name is None


async def test_membership_bo_qua_hang_het_han(pool, du_lieu):
    """Vé hỗ trợ hết hạn phải TỰ mất hiệu lực, không ai phải nhớ thu hồi (YC08)."""
    async with pool.acquire() as conn, conn.transaction():
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            """INSERT INTO control.memberships (user_id, tenant_id, role_id, expires_at)
               VALUES ('u_dang','cs_haven',$1, now() - interval '1 hour')""",
            r_admin,
        )
        q = await repo.doc_quyen(conn, "u_dang", "cs_haven")
    assert q is not None
    assert q.actions == frozenset()


async def test_membership_hang_con_han_van_vao_duoc(pool, du_lieu):
    """Mặt còn lại của test trên. Không có nó thì một phép lọc sai kiểu
    `expires_at < now()` vẫn xanh — nó cũng loại đúng hàng quá hạn, chỉ là loại
    luôn cả hàng còn hạn."""
    async with pool.acquire() as conn, conn.transaction():
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            """INSERT INTO control.memberships (user_id, tenant_id, role_id, expires_at)
               VALUES ('u_dang','cs_haven',$1, now() + interval '1 hour')""",
            r_admin,
        )
        q = await repo.doc_quyen(conn, "u_dang", "cs_haven")
    assert q is not None and q.role_name == "Quản trị"
