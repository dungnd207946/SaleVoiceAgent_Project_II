"""Fixture dùng chung cho 6 cổng cách ly."""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from portal.core.db.pool import create_pool
from tests.conftest import dsn_as

pytestmark = pytest.mark.integration


@pytest.fixture
async def seeded(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    """Hai tenant t1/t2, mỗi tenant một project + một zone + một unit. Dọn sau test.

    Seed bằng portal_migrator (owner). Vì FORCE RLS áp cho owner, phải SET LOCAL
    app.tenant_id cho từng tenant — đây chính là luật ghi ở header migration 0003.

    VIẾT LẠI theo schema KB `real_estate` (migration `0400_kb_real_estate.py`,
    Task 1 kế hoạch `2026-08-03-kb-real-estate-viet-lai`): `tenant_data.projects`/
    `units` không còn cột `code` (đổi tên `project_code`/`unit_code`) và
    `units` không còn `commission`/`extras` (trường nội bộ nhạy cảm — bỏ hẳn,
    `02 §1`). `units.zone_code` giờ NOT NULL (FK tới `zones`) nên phải seed thêm
    một zone mặc định cho mỗi tenant.

    `status = 'published'` TƯỜNG MINH trên cả ba (Task 6): mặc định cột là
    `draft`, và lớp đọc mới của agent (`agent_api.*`, `0401_agent_doc_kb.py`)
    cascade lọc `published` cho cả anchor lẫn con — seed mặc định `draft` sẽ làm
    các test dùng `agent_pool` đọc qua view thấy 0 hàng dù đúng tenant, trông như
    một lỗi cách ly trong khi thực ra chỉ là dữ liệu chưa publish.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            for t in ("t1", "t2"):
                await conn.execute(
                    "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", t
                )
        for t, unit_code in (("t1", "A-01"), ("t2", "B-01")):
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", t)
                await conn.execute(
                    "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
                    "VALUES ($1, $2, $2, 'published')",
                    t,
                    f"P-{t}",
                )
                await conn.execute(
                    """INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name, status)
                       VALUES ($1, $2, 'Z1', 'Zone', 'published')""",
                    t,
                    f"P-{t}",
                )
                await conn.execute(
                    """INSERT INTO tenant_data.units
                           (tenant_id, project_code, zone_code, unit_code, product_type, price_vnd, status)
                       VALUES ($1, $2, 'Z1', $3, 'chung_cu', 3500000000, 'published')""",
                    t,
                    f"P-{t}",
                    unit_code,
                )
    yield pool
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id IN ('t1', 't2')")


@pytest.fixture
async def api_pool(api_dsn: str) -> AsyncIterator[asyncpg.Pool]:
    """Pool nối bằng portal_api — role runtime thật, không phải owner.

    DSN lấy từ fixture `api_dsn` chứ không tự ghép: một chỗ duy nhất biết
    "runtime là portal_api", nên không có test nào lỡ mô phỏng runtime bằng owner.
    """
    p = await create_pool(api_dsn, min_size=1, max_size=2)
    yield p
    await p.close()


AGENT_PASSWORD = "agentdev"


@pytest.fixture
async def agent_roles(seeded, pool):
    """Tạo role agent_t1 và agent_t2 bằng đúng hàm mà provisioning dùng."""
    async with pool.acquire() as conn:
        for t in ("t1", "t2"):
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")
            await conn.execute("SELECT control.create_agent_role($1, $2)", t, AGENT_PASSWORD)
    yield
    async with pool.acquire() as conn:
        for t in ("t1", "t2"):
            await conn.execute(f"REASSIGN OWNED BY agent_{t} TO portal_migrator")
            await conn.execute(f"DROP OWNED BY agent_{t}")
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")


@pytest.fixture
async def agent_pool(agent_roles, pg_dsn):
    """Factory: agent_pool('t1') -> pool nối bằng role agent_t1."""
    pools: list[asyncpg.Pool] = []

    async def make(tenant: str) -> asyncpg.Pool:
        p = await create_pool(dsn_as(pg_dsn, f"agent_{tenant}", AGENT_PASSWORD), min_size=1, max_size=2)
        pools.append(p)
        return p

    yield make
    for p in pools:
        await p.close()
