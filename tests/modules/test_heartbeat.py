"""agent_heartbeats — đường agent GHI. M1 sở hữu cả hai chiều của seam agent:
agent_api view là chiều ĐỌC, bảng này là chiều GHI.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def hb_tenant(pool):
    """Hai tenant có role agent thật.

    KHÔNG còn trả `deployment_id`: `0941` bỏ `control.deployments` và đổi khoá
    `agent_heartbeats` sang `tenant_id`. Fixture cũ tồn tại chỉ vì `deployments.id` là
    bigserial dùng chung cả session nên test không đoán được id — nay không có id nào để
    đoán.
    """
    async with pool.acquire() as conn, conn.transaction():
        for t in ("hb1", "hb2"):
            await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", t)
            await conn.execute("SELECT control.create_agent_role($1, 'agentdev')", t)
    yield
    async with pool.acquire() as conn:
        for t in ("hb1", "hb2"):
            await conn.execute(f"DROP OWNED BY agent_{t}")
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")
        async with conn.transaction():
            await conn.execute("DELETE FROM control.tenants WHERE id IN ('hb1', 'hb2')")


async def _agent_conn(pg_dsn, tenant):
    from tests.conftest import dsn_as

    return await asyncpg.connect(dsn_as(pg_dsn, f"agent_{tenant}", "agentdev"))


async def test_agent_upsert_duoc_heartbeat_cua_minh(hb_tenant, pg_dsn):
    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        await conn.execute(
            """INSERT INTO control.agent_heartbeats
                   (tenant_id, running_version, bundle_sha, agent_version)
               VALUES ('hb1', 3, 'sha256:abc', '1.4.2')
               ON CONFLICT (tenant_id) DO UPDATE
                   SET running_version = excluded.running_version,
                       last_seen_at    = now()"""
        )
        got = await conn.fetchval("SELECT running_version FROM control.agent_heartbeats WHERE tenant_id = 'hb1'")
        assert got == 3
    finally:
        await conn.close()


async def test_agent_khong_ghi_duoc_heartbeat_cua_tenant_khac(hb_tenant, pg_dsn):
    """Policy hb_agent_own_tenant (TO agent_all) chặn WITH CHECK sang tenant khác."""
    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("""INSERT INTO control.agent_heartbeats (tenant_id) VALUES ('hb2')""")
    finally:
        await conn.close()


async def test_agent_khong_doc_duoc_heartbeat_cua_tenant_khac(hb_tenant, pg_dsn):
    """USING của policy chặn chiều đọc — agent không biết workspace khác tồn tại."""
    admin = await _agent_conn(pg_dsn, "hb2")
    try:
        await admin.execute("INSERT INTO control.agent_heartbeats (tenant_id) VALUES ('hb2')")
    finally:
        await admin.close()

    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        rows = await conn.fetch("SELECT tenant_id FROM control.agent_heartbeats")
        assert [r["tenant_id"] for r in rows] == []
    finally:
        await conn.close()


async def test_portal_api_doc_duoc_heartbeat_moi_workspace(hb_tenant, pg_dsn, api_dsn):
    """Policy hb_portal_all: admin nền tảng xem tình trạng vận hành là quyền
    control plane, KHÔNG phải quyền đọc dữ liệu tenant."""
    from portal.core.db.pool import create_pool

    for t in ("hb1", "hb2"):
        c = await _agent_conn(pg_dsn, t)
        try:
            await c.execute("INSERT INTO control.agent_heartbeats (tenant_id) VALUES ($1)", t)
        finally:
            await c.close()

    p = await create_pool(api_dsn, min_size=1, max_size=2)
    try:
        async with p.acquire() as conn:
            rows = await conn.fetch(
                "SELECT tenant_id FROM control.agent_heartbeats WHERE tenant_id IN ('hb1', 'hb2') ORDER BY tenant_id"
            )
        assert [r["tenant_id"] for r in rows] == ["hb1", "hb2"]
    finally:
        await p.close()


async def test_agent_khong_doc_duoc_bang_control_khac(hb_tenant, pg_dsn):
    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT id FROM control.tenants")
    finally:
        await conn.close()
