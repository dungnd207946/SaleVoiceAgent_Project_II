import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.conflicts.fields import fields_block_hash, load_fields, render_block

LONG = "Dự án ven sông. " * 400


@pytest.fixture
async def project(pool, seed_conflict_tenant):
    async with tenant_conn(pool, seed_conflict_tenant) as c:
        pid = await c.fetchval(
            "INSERT INTO tenant_data.projects"
            " (tenant_id, project_code, name, status, investor, product_scale, overview)"
            " VALUES (portal.current_tenant(), 'nplb', 'Noble Palace Long Biên', 'published', 'Noble',"
            " '172 sản phẩm · 4,3 ha', $1) RETURNING id",
            LONG,
        )
        zid = await c.fetchval(
            "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name, status, product_scale)"
            " VALUES (portal.current_tenant(), 'nplb', 'ART', 'Artemis', 'published', '98 sản phẩm') RETURNING id"
        )
        bid = await c.fetchval(
            "INSERT INTO tenant_data.buildings (tenant_id, project_code, zone_code, building_code, name, num_floors)"
            " VALUES (portal.current_tenant(), 'nplb', 'ART', 'A1', 'Toà A1', 25) RETURNING id"
        )
    return seed_conflict_tenant, pid, zid, bid


async def _load(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        return await load_fields(c, "nplb")


async def test_truong_du_an_mang_nhan_va_gia_tri(pool, project):
    tenant, pid, _, _ = project
    fields = {f.ref: f for f in await _load(pool, tenant)}
    f = fields[f"field:projects.{pid}.investor"]
    assert (f.label, f.value) == ("Chủ đầu tư", "Noble")


async def test_van_xuoi_dai_bi_cat(pool, project):
    tenant, pid, _, _ = project
    fields = {f.ref: f for f in await _load(pool, tenant)}
    assert len(fields[f"field:projects.{pid}.overview"].value) == 3000
    assert fields[f"field:projects.{pid}.overview"].label == "Tổng quan"


async def test_phan_khu_va_toa_co_ten_trong_nhan(pool, project):
    tenant, _, zid, bid = project
    fields = {f.ref: f for f in await _load(pool, tenant)}
    assert fields[f"field:zones.{zid}.product_scale"].label == "Artemis · Quy mô"
    assert fields[f"field:buildings.{bid}.num_floors"].value == "25"
    assert fields[f"field:buildings.{bid}.num_floors"].label == "Toà A1 · Số tầng"


async def test_truong_rong_khong_xuat_hien(pool, project):
    tenant, pid, _, _ = project
    refs = {f.ref for f in await _load(pool, tenant)}
    assert f"field:projects.{pid}.region" not in refs


async def test_render_va_dau_tay_khoi(pool, project):
    tenant, pid, _, _ = project
    fields = await _load(pool, tenant)
    assert f"[field:projects.{pid}.investor] Chủ đầu tư: Noble" in render_block(fields)
    before = fields_block_hash(fields)
    async with tenant_conn(pool, tenant) as c:
        await c.execute("UPDATE tenant_data.projects SET investor = 'Sunshine' WHERE project_code = 'nplb'")
    assert fields_block_hash(await _load(pool, tenant)) != before
