"""Làn worker: nhiều job chạy đồng thời, nhưng không kind nào vượt trần của nó."""

import asyncio

import pytest

from portal.core.db.session import tenant_conn
from portal.core.jobs import JobResult, enqueue, register
from portal.worker.__main__ import run_lane

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _giu_nguyen_so_handler():
    from portal.core import jobs

    handlers, concurrency = dict(jobs._HANDLERS), dict(jobs._CONCURRENCY)
    yield
    jobs._HANDLERS.clear()
    jobs._HANDLERS.update(handlers)
    jobs._CONCURRENCY.clear()
    jobs._CONCURRENCY.update(concurrency)
    jobs._INFLIGHT.clear()


@pytest.fixture
async def tenant(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('lane', 'Lane', 'u_seed_test')")
    yield "lane"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = 'lane'")


@pytest.fixture
async def api_pool_lanes(api_dsn):
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=8)
    yield p
    await p.close()


async def test_ba_job_chay_dong_thoi(tenant, api_pool_lanes):
    """Ba job của một kind trần 3 phải chồng lấn — tuần tự thì tổng ≥ 0.9s."""
    running = 0
    peak = 0

    async def handle(conn, payload):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.3)
        running -= 1
        return JobResult(count=1)

    register("lane_wide", handle, max_concurrency=3)
    async with tenant_conn(api_pool_lanes, tenant) as conn:
        for i in range(3):
            await enqueue(conn, tenant_id=tenant, kind="lane_wide", actor="t", payload={"i": i})

    lanes = [asyncio.create_task(run_lane(api_pool_lanes)) for _ in range(3)]
    await asyncio.sleep(0.9)
    for t in lanes:
        t.cancel()
    assert peak == 3


async def test_khong_vuot_tran_cua_kind(tenant, api_pool_lanes):
    """Trần 1 thì dù có 3 làn rảnh, hai job cùng kind KHÔNG được chạy chồng."""
    running = 0
    peak = 0

    async def handle(conn, payload):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.2)
        running -= 1
        return JobResult(count=1)

    register("lane_narrow", handle, max_concurrency=1)
    async with tenant_conn(api_pool_lanes, tenant) as conn:
        for i in range(3):
            await enqueue(conn, tenant_id=tenant, kind="lane_narrow", actor="t", payload={"i": i})

    lanes = [asyncio.create_task(run_lane(api_pool_lanes)) for _ in range(3)]
    await asyncio.sleep(0.7)
    for t in lanes:
        t.cancel()
    assert peak == 1
