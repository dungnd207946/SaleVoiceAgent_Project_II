"""Migration `0971_kbweb_theo_tenant` — bảng theo tenant (RLS FORCE), seed mặc định qua trigger."""

import asyncpg
import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.web import config

from . import mac_dinh
from .conftest import OTHER, TENANT

pytestmark = pytest.mark.integration

_URL = "https://test.kbweb/mig"


async def _insert(c, url=_URL, found_via="sitemap", status="ok"):
    await c.execute(
        """INSERT INTO tenant_data.web_pages (tenant_id, url, domain, found_via, status, projects, location)
           VALUES (portal.current_tenant(), $1, 'test.kbweb', $2, $3, '{NPTTL}', '{Hà Nội}')""",
        url,
        found_via,
        status,
    )


async def test_portal_api_ghi_doc_trong_tenant_conn(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _insert(c)
        row = await c.fetchrow("SELECT projects, location FROM tenant_data.web_pages WHERE url = $1", _URL)
    assert row["projects"] == ["NPTTL"] and row["location"] == ["Hà Nội"]


async def test_tenant_khac_khong_thay_va_ngoai_giao_dich_khong_thay(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _insert(c)
    async with tenant_conn(web_pool, OTHER) as c:
        assert await c.fetchval("SELECT count(*) FROM tenant_data.web_pages WHERE url = $1", _URL) == 0
    assert await web_pool.fetchval("SELECT count(*) FROM tenant_data.web_pages WHERE url = $1", _URL) == 0


async def test_cung_url_hai_tenant_la_hai_hang(web_pool):
    for tid in (TENANT, OTHER):
        async with tenant_conn(web_pool, tid) as c:
            await _insert(c)
    async with tenant_conn(web_pool, OTHER) as c:
        with pytest.raises(asyncpg.UniqueViolationError):
            await _insert(c)


@pytest.mark.parametrize(("found_via", "status"), [("crawler_lung_tung", "ok"), ("sitemap", "la")])
async def test_found_via_va_status_la_mien_dong(web_pool, found_via, status):
    async with tenant_conn(web_pool, TENANT) as c:
        with pytest.raises(asyncpg.CheckViolationError):
            await _insert(c, found_via=found_via, status=status)


async def test_found_via_probe_hop_le(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _insert(c, found_via="probe", status="needs_browser")
        row = await c.fetchrow("SELECT * FROM tenant_data.web_pages WHERE url = $1", _URL)
    assert row["source_url"] == "" and row["content_text"] is None and row["fetched_at"] is not None


async def test_khong_con_schema_public_data(pool):
    assert not await pool.fetchval("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'public_data')")


# ─── seed mặc định ───────────────────────────────────────────────────────────


async def test_tenant_moi_duoc_seed_nguon_chu_de_lich_gioi_han(web_pool):
    d = mac_dinh.defaults()
    async with tenant_conn(web_pool, TENANT) as c:
        cfg = await config.load_for_tenant(c)
        sched = await c.fetch(
            """SELECT mode, enabled, at_time::text, weekdays, every_months, day_rule, slices
                 FROM tenant_data.kbweb_schedules ORDER BY mode"""
        )
        limits = await c.fetchrow("SELECT grounding_monthly, browser_daily, asked_days FROM tenant_data.kbweb_limits")
        origins = await c.fetch("SELECT DISTINCT origin FROM tenant_data.kbweb_sources")
    assert cfg == d
    assert [tuple(r) for r in sched] == [
        ("nightly", True, "01:10:00", [], None, None, 1),
        ("rebuild", True, "05:00:00", [], 3, "d1", 1),
        ("weekly", True, "04:00:00", [1, 3, 5], None, None, 3),
    ]
    assert tuple(limits) == (1000, 300, 28)
    assert [r["origin"] for r in origins] == ["default"]


async def test_seed_lai_khong_de_sua_doi_cua_tenant(web_pool, pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await c.execute("UPDATE tenant_data.kbweb_sources SET enabled = false WHERE domain = 'cafef.vn'")
        await c.execute("DELETE FROM tenant_data.kbweb_topics WHERE code = 'legal'")
    await pool.execute("SELECT control.kbweb_seed_defaults($1)", TENANT)
    async with tenant_conn(web_pool, TENANT) as c:
        cfg = await config.load_for_tenant(c)
        n = await c.fetchval("SELECT count(*) FROM tenant_data.kbweb_sources")
    assert cfg.source_of("cafef.vn") is None and n == len(mac_dinh.defaults().sources)
    assert "legal" in {t.code for t in cfg.topics}, "chủ đề đã xoá được seed lại — chỉ bổ sung theo khoá, không ghi đè"


async def test_bo_chu_de_moi_chi_cap_nhat_chu_de_tenant_chua_sua(web_pool, pool):
    zoning_cu_kw = ["quy hoạch", "phân khu", "lên quận", "đô thị vệ tinh", "sáp nhập"]
    zoning_cu_q = ["quy hoạch {location} mới nhất", "{location} lên quận quy hoạch đô thị", "{project} quy hoạch 1/500"]
    async with tenant_conn(web_pool, TENANT) as c:
        await c.execute("UPDATE tenant_data.kbweb_topics SET queries = ARRAY['{project} riêng'] WHERE code = 'legal'")
        await c.execute(
            "UPDATE tenant_data.kbweb_topics SET keywords = $1, queries = $2 WHERE code = 'zoning'",
            zoning_cu_kw,
            zoning_cu_q,
        )
        await c.execute("DELETE FROM tenant_data.kbweb_topics WHERE code = 'liquidity'")
    await pool.execute("SELECT control.kbweb_seed_topics_v2($1)", TENANT)
    async with tenant_conn(web_pool, TENANT) as c:
        rows = {r["code"]: r for r in await c.fetch("SELECT code, queries FROM tenant_data.kbweb_topics")}
    d = {t.code: t for t in mac_dinh.defaults().topics}
    assert rows["legal"]["queries"] == ["{project} riêng"], "câu tìm workspace đã sửa giữ nguyên"
    assert rows["zoning"]["queries"] == list(d["zoning"].queries)
    assert {"price_potential", "liquidity"} <= set(rows)


async def test_load_for_tenant_chi_lay_hang_dang_bat_cua_tenant_minh(web_pool):
    async with tenant_conn(web_pool, OTHER) as c:
        await c.execute("UPDATE tenant_data.kbweb_sources SET enabled = false")
        await c.execute("UPDATE tenant_data.kbweb_topics SET enabled = false WHERE code <> 'road'")
        other = await config.load_for_tenant(c)
    async with tenant_conn(web_pool, TENANT) as c:
        mine = await config.load_for_tenant(c)
    assert other.sources == () and [t.code for t in other.topics] == ["road"]
    assert mine == mac_dinh.defaults()


async def test_xoa_tenant_cascade_sach_cau_hinh(pool):
    await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('kbw_tmp', 'tmp', 'u_seed_test')")
    assert await pool.fetchval("SELECT count(*) FROM tenant_data.kbweb_sources WHERE tenant_id = 'kbw_tmp'") == 16
    assert await pool.fetchval(
        "SELECT bool_and(probe_status = 'ok' AND probe_at IS NOT NULL) FROM tenant_data.kbweb_sources"
        " WHERE tenant_id = 'kbw_tmp'"
    ), "nguồn mặc định đã đo trước, ra đời với tình trạng hoạt động"
    await pool.execute("DELETE FROM control.tenants WHERE id = 'kbw_tmp'")
    for t in ("kbweb_sources", "kbweb_topics", "kbweb_schedules", "kbweb_limits"):
        assert await pool.fetchval(f"SELECT count(*) FROM tenant_data.{t} WHERE tenant_id = 'kbw_tmp'") == 0


async def test_portal_api_tao_tenant_van_co_seed(api_pool, pool):
    """RLS FORCE áp cả chủ bảng: trigger phải tự đặt `app.tenant_id` — đo bằng role runtime thật."""
    await pool.execute("DELETE FROM control.tenants WHERE id = 'kbw_api'")
    try:
        await api_pool.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('kbw_api', 'x', 'u_seed_test')"
        )
        async with tenant_conn(api_pool, "kbw_api") as c:
            assert await c.fetchval("SELECT count(*) FROM tenant_data.kbweb_topics") == len(mac_dinh.defaults().topics)
    finally:
        await pool.execute("DELETE FROM control.tenants WHERE id = 'kbw_api'")
