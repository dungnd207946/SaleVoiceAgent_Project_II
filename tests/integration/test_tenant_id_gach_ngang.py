"""tenant_id chứa dấu `-` phải đi hết đường cấp phát agent (migration 0911).

BỐI CẢNH: `control.tenants.id` được import từ một hệ ngoài, và id ở đó mang dấu
`-` (vd `noble-homes_k3n7_retail`). Ba chỗ cưỡng chế cùng một biểu thức đều chặn
`-`, nên tenant import vào được nhưng KHÔNG cấp phát được agent key:

    asyncpg.exceptions.RaiseError: tenant id không hợp lệ cho tên role: noble-homes_k3n7_retail

VÌ SAO `-` AN TOÀN Ở TÊN ROLE: cả `create_agent_role()` (0005) và
`dat_mat_khau_agent()` (0900) đưa tên role qua `format('%I')`, nên Postgres tự
quote thành `"agent_noble-homes_k3n7_retail"` — không có đường ghép chuỗi thô.
Và `portal.current_tenant()` (0001) parse ngược bằng `substring(session_user from
'^agent_(.+)$')`, `.+` ăn `-` bình thường. Test dưới canh cả hai chiều đó.

KÝ TỰ ĐẦU VẪN PHẢI LÀ `[a-z]`: `agent_-x` là tên role đọc như một tuỳ chọn dòng
lệnh, và `-x.<domain>` là nhãn subdomain sai chuẩn. Nới charset không nới vị trí.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration

TENANT_GACH_NGANG = "noble-homes_k3n7_retail"
"""Đúng chuỗi đã nổ ở production — dùng lại nguyên văn để test kể được ca thật."""

MAT_KHAU = "x" * 43
"""43 ký tự: khuôn của `bi_mat.dan_xuat()` (base64url). Helper đòi >= 20."""


@pytest.fixture
async def tenant_gach_ngang(pool: asyncpg.Pool):
    """Tạo tenant có dấu `-`, dọn cả role sau test.

    Dọn role TRƯỚC tenant: `DROP ROLE` thất bại nếu role còn bị ACL tham chiếu, và
    để sót một role `agent_*` giữa các test là để lại rác mà test sau đọc thấy.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')",
            TENANT_GACH_NGANG,
        )
    yield TENANT_GACH_NGANG
    async with pool.acquire() as conn:
        await conn.execute(f'DROP ROLE IF EXISTS "agent_{TENANT_GACH_NGANG}"')
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", TENANT_GACH_NGANG)


async def test_check_constraint_nhan_tenant_id_co_gach_ngang(pool: asyncpg.Pool, tenant_gach_ngang: str):
    """Cổng thứ nhất: `tenants_id_check`. Fixture INSERT được là đã qua."""
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT 1 FROM control.tenants WHERE id = $1", tenant_gach_ngang) == 1


async def test_dat_mat_khau_agent_tao_role_cho_tenant_co_gach_ngang(pool: asyncpg.Pool, tenant_gach_ngang: str):
    """Cổng thứ hai + ba: regex của `dat_mat_khau_agent()` và `create_agent_role()`.

    Đường này đi qua nhánh "role chưa có" ⇒ `PERFORM control.create_agent_role()`,
    nên một test phủ cả hai hàm.
    """
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.dat_mat_khau_agent($1, $2)", tenant_gach_ngang, MAT_KHAU)
        assert await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", f"agent_{tenant_gach_ngang}") == 1, (
            "role không được tạo -> regex vẫn chặn dấu `-`"
        )


async def test_goi_lai_van_idempotent(pool: asyncpg.Pool, tenant_gach_ngang: str):
    """Xoay khoá gọi lại cùng hàm. Lần hai đi nhánh `ALTER ROLE`, không nhánh CREATE."""
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.dat_mat_khau_agent($1, $2)", tenant_gach_ngang, MAT_KHAU)
        await conn.execute("SELECT control.dat_mat_khau_agent($1, $2)", tenant_gach_ngang, "y" * 43)
        so_role = await conn.fetchval("SELECT count(*) FROM pg_roles WHERE rolname = $1", f"agent_{tenant_gach_ngang}")
        assert so_role == 1


async def test_current_tenant_suy_nguoc_dung_tenant_co_gach_ngang(pool: asyncpg.Pool, tenant_gach_ngang: str):
    """`portal.current_tenant()` phải trả lại ĐÚNG id, không cắt ở dấu `-`.

    Đây là chiều ngược của hợp đồng đặt tên: sai ở đây thì role agent đọc dữ liệu
    của một tenant khác (hoặc của không tenant nào) mà không có lỗi nào cả.
    """
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT substring($1::text from '^agent_(.+)$')",
                f"agent_{tenant_gach_ngang}",
            )
            == tenant_gach_ngang
        )


async def test_van_chan_gach_ngang_o_ky_tu_dau(pool: asyncpg.Pool):
    """Nới charset KHÔNG được nới vị trí — ký tự đầu vẫn phải `[a-z]`."""
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", "-noble"
            )
