"""Fixture dùng chung cho test của gói kb/web.

`web_tenant` dựng hai tenant (`kbw_a`/`kbw_b`) với một dự án published mỗi bên; trigger
`tenants_tao_kbweb_mac_dinh` seed nguồn/chủ đề/lịch mặc định cho cả hai. `web_pool` nối bằng
`portal_api` (runtime thật) — bảng `tenant_data.web_pages` có RLS FORCE nên mọi câu đọc/ghi
trong test đi qua `tenant_conn(web_pool, TENANT)`.
"""

import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn

TENANT = "kbw_a"
OTHER = "kbw_b"
NPTTL = "Noble Palace Tây Thăng Long"


@pytest.fixture
async def web_tenant(pool):
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = ANY($1::text[])", [TENANT, OTHER])
    await pool.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, OTHER])
    for tid in (TENANT, OTHER):
        await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", tid)
        await pool.execute("INSERT INTO control.tenant_verticals (tenant_id, vertical) VALUES ($1, 'realestate')", tid)
        async with tenant_conn(pool, tid) as conn:
            await conn.execute(
                """INSERT INTO tenant_data.projects (tenant_id, project_code, name, address, region, status)
                   VALUES ($1, 'NPTTL', $2, 'xã Tân Lập, huyện Đan Phượng, Hà Nội', 'Hà Nội', 'published')""",
                tid,
                NPTTL,
            )
    yield TENANT
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = ANY($1::text[])", [TENANT, OTHER])
    await pool.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, OTHER])


@pytest.fixture
async def web_pool(api_dsn, pool, web_tenant):
    p = await create_pool(api_dsn, min_size=1, max_size=4)
    await pool.execute("DELETE FROM tenant_data.web_pages WHERE url LIKE 'https://test.kbweb/%'")
    yield p
    await pool.execute("DELETE FROM tenant_data.web_pages WHERE url LIKE 'https://test.kbweb/%'")
    await p.close()
