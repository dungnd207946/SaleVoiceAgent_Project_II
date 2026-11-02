"""`scheduler.tick` — đọc lịch của từng tenant, xếp `kbweb_run`, tính mốc kế."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.web import scheduler
from portal.modules.kb.web.contracts import KIND_RUN, MODE_NIGHTLY, MODE_WEEKLY

from .conftest import OTHER, TENANT

pytestmark = pytest.mark.integration
VN = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 10, 5, 1, 12, tzinfo=VN)  # thứ Hai


@pytest.fixture(autouse=True)
async def _clean_jobs(pool):
    await pool.execute("DELETE FROM control.jobs WHERE kind = $1", KIND_RUN)
    yield
    await pool.execute("DELETE FROM control.jobs WHERE kind = $1", KIND_RUN)


async def _runs(pool, tenant):
    rows = await pool.fetch(
        "SELECT payload, actor FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id", tenant, KIND_RUN
    )
    return [(json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"], r["actor"]) for r in rows]


# `api_pool` chứ không `pool`: superuser bỏ qua RLS nên một UPDATE thiếu vị từ tenant đè cả hai tenant.
async def _set_next(api_pool, tenant, mode, when):
    async with tenant_conn(api_pool, tenant) as c:
        await c.execute("UPDATE tenant_data.kbweb_schedules SET next_run_at = $2 WHERE mode = $1", mode, when)


async def _sched(api_pool, tenant, mode):
    async with tenant_conn(api_pool, tenant) as c:
        return await c.fetchrow(
            "SELECT last_run_at, next_run_at FROM tenant_data.kbweb_schedules WHERE mode = $1", mode
        )


async def test_lan_dau_chi_tinh_moc_khong_chay(web_tenant, api_pool, pool):
    assert await scheduler.tick(api_pool, NOW) == 0
    assert await _runs(pool, TENANT) == []
    assert (await _sched(api_pool, TENANT, MODE_NIGHTLY))["next_run_at"] == datetime(2026, 10, 6, 1, 10, tzinfo=VN)
    assert (await _sched(api_pool, TENANT, MODE_WEEKLY))["next_run_at"] == datetime(2026, 10, 6, 4, 0, tzinfo=VN)
    assert (await _sched(api_pool, TENANT, "rebuild"))["next_run_at"] == datetime(2027, 1, 1, 5, 0, tzinfo=VN)


async def test_toi_gio_thi_xep_dung_tenant_va_doi_moc(web_tenant, api_pool, pool):
    await _set_next(api_pool, TENANT, MODE_NIGHTLY, NOW - timedelta(minutes=1))
    await _set_next(api_pool, TENANT, MODE_WEEKLY, NOW + timedelta(hours=2))
    await _set_next(api_pool, OTHER, MODE_NIGHTLY, NOW + timedelta(days=1))
    assert await scheduler.tick(api_pool, NOW) == 1
    assert await _runs(pool, TENANT) == [({"mode": MODE_NIGHTLY, "slices": 1}, "lich")]
    assert await _runs(pool, OTHER) == []
    row = await _sched(api_pool, TENANT, MODE_NIGHTLY)
    assert row["last_run_at"] == NOW and row["next_run_at"] == datetime(2026, 10, 6, 1, 10, tzinfo=VN)


async def test_tat_linh_vuc_bat_dong_san_thi_lich_dung(web_tenant, api_pool, pool):
    await _set_next(api_pool, TENANT, MODE_NIGHTLY, NOW - timedelta(minutes=1))
    await pool.execute("DELETE FROM control.tenant_verticals WHERE tenant_id = $1", TENANT)
    assert await scheduler.tick(api_pool, NOW) == 0
    assert await _runs(pool, TENANT) == []


async def test_tuan_mang_slices_cua_lich(web_tenant, api_pool, pool):
    await _set_next(api_pool, TENANT, MODE_WEEKLY, NOW)
    await scheduler.tick(api_pool, NOW)
    assert await _runs(pool, TENANT) == [({"mode": MODE_WEEKLY, "slices": 3}, "lich")]


async def test_lich_tat_khong_chay(web_tenant, api_pool, pool):
    await _set_next(api_pool, TENANT, MODE_NIGHTLY, NOW)
    async with tenant_conn(api_pool, TENANT) as c:
        await c.execute("UPDATE tenant_data.kbweb_schedules SET enabled = false WHERE mode = $1", MODE_NIGHTLY)
    assert await scheduler.tick(api_pool, NOW) == 0


async def test_dang_cho_thi_khong_xep_trung_nhung_van_doi_moc(web_tenant, api_pool, pool):
    async with tenant_conn(api_pool, TENANT) as c:
        await scheduler.enqueue_run(c, tenant_id=TENANT, actor="user:1", mode=MODE_NIGHTLY)
    await _set_next(api_pool, TENANT, MODE_NIGHTLY, NOW)
    assert await scheduler.tick(api_pool, NOW) == 0
    assert len(await _runs(pool, TENANT)) == 1
    assert (await _sched(api_pool, TENANT, MODE_NIGHTLY))["next_run_at"] > NOW


async def test_enqueue_run_mode_sai_thi_nem(web_tenant, api_pool):
    async with tenant_conn(api_pool, TENANT) as c:
        with pytest.raises(ValueError):
            await scheduler.enqueue_run(c, tenant_id=TENANT, actor="x", mode="init")
