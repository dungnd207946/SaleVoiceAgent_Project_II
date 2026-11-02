import asyncpg
import pytest

from portal.core.db.session import tenant_conn

_INSERT = (
    "INSERT INTO tenant_data.data_conflicts (tenant_id, project_code, left_hash, right_hash, status)"
    " VALUES (portal.current_tenant(), 'p1', $1, $2, $3)"
)


async def test_bang_ton_tai_va_bat_rls(pool):
    async with pool.acquire() as c:
        r = await c.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE oid = 'tenant_data.data_conflicts'::regclass"
        )
    assert r["relrowsecurity"] and r["relforcerowsecurity"]


async def test_mot_cap_mot_hang(pool, seed_conflict_tenant):
    async with tenant_conn(pool, seed_conflict_tenant) as c:
        await c.execute(_INSERT, "a", "b", "none")
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(_INSERT, "a", "b", "open")


async def test_status_ngoai_danh_sach_bi_chan(pool, seed_conflict_tenant):
    async with tenant_conn(pool, seed_conflict_tenant) as c:
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute(_INSERT, "a", "c", "xxx")


async def test_nhan_billing_tinh_tien(pool):
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT billable FROM billing.purpose WHERE code = 'conflict_check'") is True
