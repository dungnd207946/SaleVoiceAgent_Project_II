"""Helper enforce_tenant_isolation — API mà 8 module còn lại dùng để bật cách ly."""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def probe(pool):
    """Bảng thử trong tenant_data, dọn sau mỗi test."""
    async with pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS tenant_data")
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")
        await conn.execute(
            """CREATE TABLE tenant_data.probe (
                   id        bigserial PRIMARY KEY,
                   tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
                   note      text NOT NULL DEFAULT ''
               )"""
        )
    yield "tenant_data.probe"
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")


async def test_helper_bat_rls_va_force_va_policy(pool, probe):
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.enforce_tenant_isolation($1)", probe)
        row = await conn.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = $1::regclass", probe
        )
        assert row["relrowsecurity"] is True
        assert row["relforcerowsecurity"] is True, "FORCE thiếu -> chủ bảng đi xuyên cách ly"
        pols = await conn.fetch(
            "SELECT policyname FROM pg_policies WHERE schemaname = 'tenant_data' AND tablename = 'probe'"
        )
        assert [p["policyname"] for p in pols] == ["tenant_isolation"]


async def test_helper_grant_cho_portal_api(pool, probe):
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.enforce_tenant_isolation($1)", probe)
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert await conn.fetchval("SELECT has_table_privilege('portal_api', $1, $2)", probe, priv) is True


async def test_helper_tu_choi_bang_ngoai_tenant_data(pool):
    """Thà vỡ lúc migrate hơn vỡ lúc chạy."""
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS control.wrong_place")
        await conn.execute("CREATE TABLE control.wrong_place (tenant_id text)")
        with pytest.raises(Exception, match="chỉ dùng cho bảng trong schema tenant_data"):
            await conn.execute("SELECT control.enforce_tenant_isolation('control.wrong_place')")
        await conn.execute("DROP TABLE control.wrong_place")


async def test_helper_tu_choi_bang_khong_co_cot_tenant_id(pool):
    async with pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS tenant_data")
        await conn.execute("DROP TABLE IF EXISTS tenant_data.no_tenant")
        await conn.execute("CREATE TABLE tenant_data.no_tenant (id bigserial PRIMARY KEY)")
        with pytest.raises(Exception, match="thiếu cột tenant_id"):
            await conn.execute("SELECT control.enforce_tenant_isolation('tenant_data.no_tenant')")
        await conn.execute("DROP TABLE tenant_data.no_tenant")


async def test_portal_api_khong_phai_superuser_khong_bypassrls(pool):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = 'portal_api'"
        )
    assert r is not None, "role portal_api chưa tồn tại"
    assert r["rolsuper"] is False
    assert r["rolbypassrls"] is False
    assert r["rolcreaterole"] is False
    assert r["rolcreatedb"] is False


async def test_role_nhom_agent_all_ton_tai_va_khong_login(pool):
    """Mọi quyền của agent đi qua nhóm này — nên nó không được đăng nhập được."""
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'agent_all'")
    assert r is not None, "role nhóm agent_all chưa tồn tại"
    assert r["rolcanlogin"] is False
    assert r["rolsuper"] is False
    assert r["rolbypassrls"] is False


async def test_khong_co_role_nao_co_bypassrls(pool):
    """Sửa lỗi C3: role BYPASSRLS là role nguy hiểm nhất hệ thống. Không tạo khi chưa cần."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT rolname FROM pg_roles WHERE rolbypassrls AND NOT rolsuper")
    assert [r["rolname"] for r in rows] == []
