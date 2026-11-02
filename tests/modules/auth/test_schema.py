"""Schema của M2a: control.users + control.memberships (spec §3.1 · §3.2).

Migration 0104 (M2b) xoá CHECK "role trong 4 giá trị" cùng với cột `role` —
đó chính là điểm của 0104 (spec §1.1: "nhận rủi ro đó để đổi lấy tính linh
hoạt", vai trò giờ là dữ liệu do tổ chức tự định nghĩa). Test canh CHECK đó
(`test_role_ngoai_bon_gia_tri_bi_chan`) bị XOÁ ở Task 2, không sửa — không còn
ràng buộc nào để canh. Ràng buộc mới (role_id phải cùng org với membership) đã
có gate riêng: `tests/modules/auth/test_migration_0104.py::
test_membership_lech_to_chuc_bi_chan_o_postgres`.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration


async def test_users_va_memberships_ton_tai(pool):
    async with pool.acquire() as conn:
        ten = await conn.fetch(
            """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'control' AND c.relname IN ('users', 'memberships')"""
        )
    assert {r["relname"] for r in ten} == {"users", "memberships"}


async def test_email_phai_la_lower(pool):
    """CHECK ở TẦNG DB, không chỉ tầng app: một đường ghi quên chuẩn hoá phải
    là lỗi to ngay lúc INSERT, không phải một hàng lệch phát hiện sáu tháng sau."""
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(asyncpg.IntegrityConstraintViolationError):
            await conn.execute(
                "INSERT INTO control.users (id, email, password_hash, name) VALUES ($1, $2, $3, $4)",
                "u_hoa",
                "Hoa@X.VN",
                "x",
                "Hoa",
            )


async def test_xoa_tenant_keo_theo_membership(pool):
    """ON DELETE CASCADE: xoá workspace không được để lại membership treo trỏ
    vào tenant không còn tồn tại."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_b', 'B', 'u_seed_test')")
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ('u_b', 'b@x.vn', 'x', 'B')"
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_b', 'cs_b', $1)",
            r_admin,
        )
        await conn.execute("DELETE FROM control.tenants WHERE id = 'cs_b'")
        con_lai = await conn.fetchval("SELECT count(*) FROM control.memberships WHERE tenant_id = 'cs_b'")
    assert con_lai == 0


@pytest.fixture(autouse=True)
async def _don(pool):
    """Dọn hàng do module này tạo. `pool` là scope function nhưng container
    Postgres là scope session — hàng không dọn sẽ sống tới hết lượt chạy."""
    yield
    async with pool.acquire() as conn, conn.transaction():
        # tenants TRƯỚC users: `tenants.created_by` là FK không CASCADE (0106).
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_%' AND created_by <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_%' AND id <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")
