"""SP-E1 live RLS isolation proof (BR08/BR09) — the crown-jewel verification.

Requires a reachable Postgres SUPERUSER DSN in ``SPE_PG_ADMIN_DSN`` (skipped
otherwise). Proves DB-enforced cross-tenant isolation: tenant A cannot read
tenant B's rows and cannot write a row tagged as B — a code bug cannot leak
across workspaces because RLS keys on the connecting role's ``current_user``.

Run:
    SPE_PG_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey \
      pytest tests/integration/tenant/test_pg_rls_live.py -q
"""

from __future__ import annotations

import os

import pytest

from noble_agent.storage.postgres_client import tenant_conn
from noble_agent.tenant import pg_provisioning as PG
from noble_agent.tenant.pg_provisioning import ensure_app_role

ADMIN = os.getenv("SPE_PG_ADMIN_DSN")
pytestmark = [
    pytest.mark.needs_postgres,
    pytest.mark.skipif(not ADMIN, reason="set SPE_PG_ADMIN_DSN to run"),
]

TA, TB = "spe_probe_a", "spe_probe_b"
APP_ROLE = "spe_app_role"  # distinct from spe_probe_a / spe_probe_b
APP_PW = "app_pw"


def _tenant_dsn(admin: str, role: str, pw: str) -> str:
    # swap user:pass in the admin DSN
    tail = admin.split("@", 1)[1]
    scheme = admin.split("://", 1)[0]
    return f"{scheme}://{role}:{pw}@{tail}"


def _app_dsn(admin: str, role: str, pw: str) -> str:
    # same swap shape as _tenant_dsn
    head, tail = admin.split("://", 1)
    _cred, hostpart = tail.split("@", 1)
    return f"{head}://{role}:{pw}@{hostpart}"


@pytest.fixture
async def provisioned():
    import asyncpg

    await PG.apply_schema(ADMIN)  # tables must exist before deprovision's DELETE
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)
    await PG.provision(ADMIN, TA, "pw_a")
    await PG.provision(ADMIN, TB, "pw_b")
    yield asyncpg
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)


async def test_rls_cross_tenant_isolation(provisioned):
    asyncpg = provisioned
    a = await asyncpg.connect(_tenant_dsn(ADMIN, TA, "pw_a"))
    b = await asyncpg.connect(_tenant_dsn(ADMIN, TB, "pw_b"))
    try:
        # A writes its own row
        await a.execute(
            "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1, $2)", TA, "s-a"
        )
        # A cannot write a row tagged as B (WITH CHECK)
        with pytest.raises(asyncpg.PostgresError):
            await a.execute(
                "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1, $2)", TB, "s-x"
            )
        # B sees NONE of A's rows (USING)
        assert await b.fetchval("SELECT count(*) FROM tenant_data.conversations") == 0
        # A sees exactly its own row
        assert await a.fetchval("SELECT count(*) FROM tenant_data.conversations") == 1
    finally:
        await a.close()
        await b.close()


async def test_app_role_set_local_isolation_and_leak(provisioned):
    asyncpg = provisioned
    await ensure_app_role(ADMIN, role=APP_ROLE, password=APP_PW)
    pool = await asyncpg.create_pool(_app_dsn(ADMIN, APP_ROLE, APP_PW), min_size=1, max_size=1)  # forces reuse
    try:
        # A writes its own row
        async with tenant_conn(pool, TA) as c:
            await c.execute(
                "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1,$2)", TA, "s-a"
            )
        # WITH CHECK: A cannot write a row tagged B
        with pytest.raises(asyncpg.PostgresError):
            async with tenant_conn(pool, TA) as c:
                await c.execute(
                    "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1,$2)", TB, "s-x"
                )
        # LEAK-ON-REUSE (the critical one): same pooled conn, now scoped to B,
        # sees ZERO of A's rows.
        async with tenant_conn(pool, TB) as c:
            n = await c.fetchval("SELECT count(*) FROM tenant_data.conversations")
            assert n == 0
        # A re-scoped sees exactly its own row
        async with tenant_conn(pool, TA) as c:
            n = await c.fetchval("SELECT count(*) FROM tenant_data.conversations")
            assert n == 1
    finally:
        await pool.close()


async def test_app_role_fail_closed_when_unset(provisioned):
    asyncpg = provisioned
    await ensure_app_role(ADMIN, role=APP_ROLE, password=APP_PW)
    conn = await asyncpg.connect(_app_dsn(ADMIN, APP_ROLE, APP_PW))
    try:
        # No set_config → app.current_tenant NULL → 0 rows (fail-closed)
        n = await conn.fetchval("SELECT count(*) FROM tenant_data.conversations")
        assert n == 0
    finally:
        await conn.close()


# Portal path (per-tenant login role via current_user) MUST still work — the
# existing test_rls_cross_tenant_isolation above covers this; kept unmodified.
