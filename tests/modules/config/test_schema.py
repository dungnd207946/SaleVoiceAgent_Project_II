"""Schema của M3 sau `0967`: `tenant_data.agent_config` theo role · `role_config` · nhịp tim.

Cổng quan trọng nhất ở đây là cột `role` do **Postgres** cưỡng chế, không do nội quy:
  · role không có trong `role_config` của tenant ⇒ FK chặn,
  · tạo tenant ⇒ có sẵn role `customer` (trigger), và role đó không xoá được,
  · hai hàng cùng (tenant, role) ⇒ UNIQUE chặn (đích của `ON CONFLICT` trong
    `agent_config.luu()` — mất nó thì UPSERT thành INSERT im lặng),
  · KHÔNG có DEFAULT — một INSERT quên role mà vẫn lọt thành `customer` là hỏng im lặng.

Và ba bảng đã bỏ (`config_drafts` · `config_versions` · `config_live`) thật sự không
còn — một bảng "bỏ" mà vẫn nằm đó là chỗ code mới lỡ ghi vào mà không ai đọc.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration

_CHEN = (
    "INSERT INTO tenant_data.agent_config (tenant_id, role, name, brand_name, tone, reply_length, version)"
    " VALUES ($1, $2, 'Mai', 'An Phú', 'lich_su', 'ngan', 1)"
)


@pytest.fixture
async def tenant_thu(pool: asyncpg.Pool):
    """Một tenant để treo config lên. Dọn sau mỗi test."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cfg_a', 'Cfg A', 'u_seed_test')"
        )
    yield "cfg_a"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cfg\\_%'")


async def test_ba_bang_cu_da_bo(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        con_lai = await conn.fetch(
            """SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'control'
                  AND table_name IN ('config_drafts', 'config_versions', 'config_live')"""
        )
    assert con_lai == []


async def test_tao_tenant_co_san_role_mac_dinh(pool: asyncpg.Pool, tenant_thu: str):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, ten, icon FROM tenant_data.role_config WHERE tenant_id = $1", tenant_thu)
        so_hang_cau_hinh = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.agent_config WHERE tenant_id = $1", tenant_thu
        )
    assert [(r["key"], r["ten"], r["icon"]) for r in rows] == [("customer", "Khách hàng", "khach")]
    assert so_hang_cau_hinh == 0, "chỉ tạo ROLE, không tạo hàng cấu hình — GET trả bộ mặc định"


async def test_tao_tenant_bang_portal_api_van_co_role(api_dsn: str):
    """Trigger chạy dưới RLS FORCE của `role_config` bằng role runtime thật (`portal_api`,
    không BYPASSRLS) — superuser của testcontainer thì không bao giờ đỏ ở đây. Và nó phải
    TRẢ LẠI `app.tenant_id` cũ cho phần còn lại của giao dịch."""
    conn = await asyncpg.connect(api_dsn)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', 'cfg_cu', true)")
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ('cfg_api', 'Cfg API', 'u_seed_test')"
            )
            assert await conn.fetchval("SELECT current_setting('app.tenant_id')") == "cfg_cu"
            await conn.execute("SELECT set_config('app.tenant_id', 'cfg_api', true)")
            assert await conn.fetchval("SELECT key FROM tenant_data.role_config") == "customer"
            raise _HuyGiaoDich
    except _HuyGiaoDich:
        pass
    finally:
        await conn.close()


class _HuyGiaoDich(Exception):
    pass


async def test_role_mac_dinh_khong_xoa_duoc_nhung_xoa_tenant_van_cuon_theo(pool: asyncpg.Pool, tenant_thu: str):
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.RaiseError, match="không xoá được"):
            await conn.execute("DELETE FROM tenant_data.role_config WHERE tenant_id = $1", tenant_thu)
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", tenant_thu)
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.role_config WHERE tenant_id = $1", tenant_thu) == 0


async def test_key_role_bat_bien(pool: asyncpg.Pool, tenant_thu: str):
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.RaiseError, match="bất biến"):
            await conn.execute("UPDATE tenant_data.role_config SET key = 'kh' WHERE tenant_id = $1", tenant_thu)


async def test_role_khong_co_trong_role_config_bi_chan(pool: asyncpg.Pool, tenant_thu: str):
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(_CHEN, tenant_thu, "admin")


async def test_xoa_role_mang_theo_hang_cau_hinh(pool: asyncpg.Pool, tenant_thu: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenant_data.role_config (tenant_id, key, ten) VALUES ($1, 'sale', 'Sale')", tenant_thu
        )
        await conn.execute(_CHEN, tenant_thu, "sale")
        await conn.execute("DELETE FROM tenant_data.role_config WHERE tenant_id = $1 AND key = 'sale'", tenant_thu)
        assert (
            await conn.fetchval("SELECT count(*) FROM tenant_data.agent_config WHERE tenant_id = $1", tenant_thu) == 0
        )


async def test_role_config_bat_rls_force(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = 'tenant_data.role_config'::regclass"
        )
    assert r["relrowsecurity"] and r["relforcerowsecurity"]


async def test_mot_hang_moi_tenant_moi_role(pool: asyncpg.Pool, tenant_thu: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenant_data.role_config (tenant_id, key, ten) VALUES ($1, 'sale', 'Sale')", tenant_thu
        )
        await conn.execute(_CHEN, tenant_thu, "sale")
        await conn.execute(_CHEN, tenant_thu, "customer")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(_CHEN, tenant_thu, "sale")


async def test_role_khong_co_mac_dinh(pool: asyncpg.Pool, tenant_thu: str):
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.NotNullViolationError):
            await conn.execute(
                "INSERT INTO tenant_data.agent_config (tenant_id, name, brand_name, tone, reply_length, version)"
                " VALUES ($1, 'Mai', 'An Phú', 'lich_su', 'ngan', 1)",
                tenant_thu,
            )


async def test_heartbeat_tro_toi_tenant_co_that(pool: asyncpg.Pool, tenant_thu: str):
    """FK về `control.tenants` (từ `0007`) là ràng buộc DUY NHẤT còn lại sau `0941`."""
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute("INSERT INTO control.agent_heartbeats (tenant_id) VALUES ('kh_khong_co_that')")
