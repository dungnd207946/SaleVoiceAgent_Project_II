import pytest

TENANT = "cf_conflict"
OTHER = "cf_conflict_b"


@pytest.fixture
async def seed_conflict_tenant(pool):
    async with pool.acquire() as conn, conn.transaction():
        for tid in (TENANT, OTHER):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')"
                " ON CONFLICT DO NOTHING",
                tid,
            )
    yield TENANT
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.jobs WHERE tenant_id = ANY($1::text[])", [TENANT, OTHER])
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, OTHER])
