import pytest

pytestmark = pytest.mark.integration


async def test_ket_noi_duoc_va_migration_da_chay(pool):
    """Harness sống: kết nối được và bảng alembic_version tồn tại."""
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT 1") == 1
        exists = await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        assert exists is True
