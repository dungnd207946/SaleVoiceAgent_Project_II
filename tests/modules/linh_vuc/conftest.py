"""Seed cho test module linh_vuc — hai tenant, trạng thái NHƯ SAU backfill 0944.

Mỗi tenant có sẵn: hàng `('realestate')` trong tenant_verticals (backfill/
them_vertical đều ra thế) + dự án sentinel `__ALL__` published (provisioning
tạo cho MỌI tenant thật — thiếu nó thì bài coDuLieu xanh giả: không có gì
để loại).

Seed hai tenant, không một: bug cách ly trông y hệt chạy đúng nếu chỉ seed
tenant đang test.
"""

import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn

TENANT = "lv_acme"
OTHER_TENANT = "lv_other"


@pytest.fixture
async def seed_lv(pool):
    async with pool.acquire() as conn, conn.transaction():
        for tid, name in [(TENANT, "LV Acme"), (OTHER_TENANT, "LV Other")]:
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", tid, name
            )
            await conn.execute(
                "INSERT INTO control.tenant_verticals (tenant_id, vertical) VALUES ($1, 'realestate')", tid
            )
    for tid in (TENANT, OTHER_TENANT):
        async with tenant_conn(pool, tid) as conn:
            await conn.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
                "VALUES ($1, '__ALL__', 'Chung / toàn tenant', 'published')",
                tid,
            )
    yield
    # ON DELETE CASCADE dọn tenant_verticals + tenant_data + audit_log của hai
    # tenant — cascade chạy ở tầng hệ thống, không bị RLS chặn.
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'lv\\_%'")


@pytest.fixture
async def api_pool(api_dsn):
    """Pool runtime (`portal_api`) — role thật của API. `pool` là migrator/
    superuser, bỏ qua RLS kể cả FORCE, chỉ dùng để seed và đọc đối chứng."""
    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()
