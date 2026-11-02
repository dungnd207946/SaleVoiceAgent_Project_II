"""Repo SQL của linh_vuc — chạy trên container Postgres thật (fixture pg_dsn)."""

from portal.core.db.session import tenant_conn
from portal.modules.linh_vuc import repo

from .conftest import OTHER_TENANT, TENANT


async def test_doc_bat_tat_vong_tron(api_pool, seed_lv):
    async with api_pool.acquire() as conn:
        assert await repo.doc_verticals(conn, TENANT) == {"realestate"}

        await repo.tat(conn, TENANT, "realestate")
        assert await repo.doc_verticals(conn, TENANT) == set()

        await repo.bat(conn, TENANT, "finance")
        await repo.bat(conn, TENANT, "finance")  # idempotent — ON CONFLICT
        assert await repo.doc_verticals(conn, TENANT) == {"finance"}

        await repo.tat(conn, TENANT, "finance")
        await repo.tat(conn, TENANT, "finance")  # DELETE hụt cũng im lặng
        assert await repo.doc_verticals(conn, TENANT) == set()


async def test_tat_khong_lan_sang_tenant_khac(api_pool, seed_lv):
    """control.* KHÔNG có RLS — cách ly ở đây chỉ nhờ vị từ tenant_id trong
    SQL. Bài này là bằng chứng vị từ đó tồn tại."""
    async with api_pool.acquire() as conn:
        await repo.tat(conn, TENANT, "realestate")
        assert await repo.doc_verticals(conn, OTHER_TENANT) == {"realestate"}


async def test_co_du_lieu_bo_qua_sentinel(api_pool, seed_lv):
    """Chỉ có `__ALL__` (row hệ thống, LUÔN published ở mọi tenant) thì CHƯA
    tính là có dữ liệu — không loại nó thì trường này là hằng true."""
    async with tenant_conn(api_pool, TENANT) as conn:
        assert await repo.co_du_lieu_bds(conn) is False


async def test_co_du_lieu_dem_du_an_published(api_pool, seed_lv):
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES (portal.current_tenant(), 'nplb', 'Noble Palace', 'draft')"
        )
        assert await repo.co_du_lieu_bds(conn) is False  # draft chưa tính

        await conn.execute(
            "UPDATE tenant_data.projects SET status = 'published' "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'nplb'"
        )
        assert await repo.co_du_lieu_bds(conn) is True

    # tenant kia không lây
    async with tenant_conn(api_pool, OTHER_TENANT) as conn:
        assert await repo.co_du_lieu_bds(conn) is False
