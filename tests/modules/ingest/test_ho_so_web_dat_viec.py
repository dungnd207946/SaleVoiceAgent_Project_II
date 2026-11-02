"""Cổng nạp chiếu một dự án thành `published` ⇒ xếp việc dựng hồ sơ web; đã published thì thôi."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from portal.modules.ingest import contracts, service

pytestmark = pytest.mark.integration

KIND = "kbweb_project"
PURGE = "kbweb_purge"
LUC = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
DU_AN = {"name": "Khu đô thị Thử", "region": "Hà Nội", "category": ["chung_cu"]}


def _lo(ma: str, data: dict, *, luc: datetime = LUC):
    bg = contracts.BanGhiIn(entity="project", externalId=ma, op="upsert", occurredAt=luc, data=data)
    return contracts.LoNapIn(records=[bg], syncId="test-web")


async def _web_jobs(pool, tenant, kind=KIND):
    rows = await pool.fetch(
        "SELECT payload, actor FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id", tenant, kind
    )
    return [(json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"], r["actor"]) for r in rows]


async def _code(pool, tenant, ma):
    return await pool.fetchval(
        "SELECT project_code FROM tenant_data.projects WHERE tenant_id = $1 AND external_id = $2", tenant, ma
    )


async def test_du_an_moi_mac_dinh_published_xep_viec(api_pool, hai_tenant, pool):
    a, b = hai_tenant
    ra = await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN), dry_run=False)
    assert ra.accepted == 1, ra.results
    code = await _code(pool, a, "P1")
    assert await _web_jobs(pool, a) == [({"project_code": code, "mode": "init"}, "ingest")]
    assert await _web_jobs(pool, b) == []


async def test_du_an_nhap_khong_xep_viec(api_pool, hai_tenant, pool):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN | {"status": "draft"}), dry_run=False)
    assert await _web_jobs(pool, a) == []


async def test_da_published_cap_nhat_lai_khong_xep_them(api_pool, hai_tenant, pool):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN), dry_run=False)
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = $2", a, KIND)
    later = LUC + timedelta(hours=1)
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN | {"region": "Hải Phòng"}, luc=later), dry_run=False)
    assert await _web_jobs(pool, a) == []
    assert await _web_jobs(pool, a, PURGE) == []


async def test_doi_ten_khi_published_don_ten_cu_va_dung_lai(api_pool, hai_tenant, pool):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN), dry_run=False)
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = $2", a, KIND)
    later = LUC + timedelta(hours=1)
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN | {"name": "Tên mới"}, luc=later), dry_run=False)
    assert [j for j, _ in await _web_jobs(pool, a, PURGE)] == [{"project_name": DU_AN["name"]}]
    assert [j for j, _ in await _web_jobs(pool, a)] == [{"project_code": await _code(pool, a, "P1"), "mode": "init"}]


async def test_go_published_va_xoa_mem_deu_don_ho_so(api_pool, hai_tenant, pool):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN), dry_run=False)
    later = LUC + timedelta(hours=1)
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN | {"status": "draft"}, luc=later), dry_run=False)
    assert [j for j, _ in await _web_jobs(pool, a, PURGE)] == [{"project_name": DU_AN["name"]}]
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P2", DU_AN | {"name": "Dự án Hai"}), dry_run=False)
    bg = contracts.BanGhiIn(entity="project", externalId="P2", op="delete", occurredAt=later, data={})
    await service.nap_lo(api_pool, tenant_id=a, lo=contracts.LoNapIn(records=[bg], syncId="test-web"), dry_run=False)
    assert {"project_name": "Dự án Hai"} in [j for j, _ in await _web_jobs(pool, a, PURGE)]


async def test_nhap_roi_published_xep_viec(api_pool, hai_tenant, pool):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN | {"status": "draft"}), dry_run=False)
    later = LUC + timedelta(hours=1)
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN | {"status": "published"}, luc=later), dry_run=False)
    assert [j for j, _ in await _web_jobs(pool, a)] == [{"project_code": await _code(pool, a, "P1"), "mode": "init"}]


async def test_dry_run_khong_xep_viec(api_pool, hai_tenant, pool):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1", DU_AN), dry_run=True)
    assert await _web_jobs(pool, a) == []
