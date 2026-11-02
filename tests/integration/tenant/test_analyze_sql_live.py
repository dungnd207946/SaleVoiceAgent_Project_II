"""analyze_projects live proof — 3 khoá DB thật (spec 2026-08-26 §7).

Requires SPE_PG_ADMIN_DSN (superuser, DB test — KHÔNG chạy trên DB prod).
Run:
    SPE_PG_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey \
      pytest tests/integration/tenant/test_analyze_sql_live.py -q
"""

from __future__ import annotations

import os

import pytest

from noble_agent.tenant import pg_provisioning as PG

ADMIN = os.getenv("SPE_PG_ADMIN_DSN")
pytestmark = [
    pytest.mark.needs_postgres,
    pytest.mark.skipif(not ADMIN, reason="set SPE_PG_ADMIN_DSN to run"),
]

TA, TB = "sqlro_probe_a", "sqlro_probe_b"
APP_ROLE, APP_PW = "sqlro_app_role", "app_pw"
SQL_RO = "agent_sql_ro"


def _dsn(admin: str, role: str, pw: str) -> str:
    head, tail = admin.split("://", 1)
    _cred, hostpart = tail.split("@", 1)
    return f"{head}://{role}:{pw}@{hostpart}"


@pytest.fixture
async def env():
    import asyncpg

    await PG.apply_schema(ADMIN)
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)
    await PG.provision(ADMIN, TA, "pw_a")
    await PG.provision(ADMIN, TB, "pw_b")
    await PG.ensure_app_role(ADMIN, role=APP_ROLE, password=APP_PW)
    await PG.ensure_sql_ro_roles(ADMIN, sql_ro_role=SQL_RO, app_role=APP_ROLE, tenant_roles=(TA, TB))
    root = await asyncpg.connect(ADMIN)
    # seed: TA 1 published + 1 draft project; units published/draft; TB 1 published
    await root.execute(
        "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) VALUES "
        "($1,'PUBA','Pub A','published'), ($1,'DRFA','Draft A','draft'), ($2,'PUBB','Pub B','published') "
        "ON CONFLICT (tenant_id, project_code) DO NOTHING",
        TA, TB,
    )
    await root.execute(
        "INSERT INTO tenant_data.units (tenant_id, project_code, unit_code, product_type, status) VALUES "
        "($1,'PUBA','U1','căn hộ','published'), ($1,'PUBA','U2','shophouse','published'), "
        "($1,'PUBA','U3','biệt thự','draft'), ($1,'DRFA','U4','căn hộ','published')",
        TA,
    )
    yield asyncpg
    await root.close()
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)


async def _scoped(conn, tenant: str) -> None:
    await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant)
    await conn.execute(f'SET LOCAL ROLE "{SQL_RO}"')
    await conn.execute("SET TRANSACTION READ ONLY")
    await conn.execute("SET LOCAL statement_timeout = 2000")


async def test_three_locks(env):
    asyncpg = env
    app = await asyncpg.connect(_dsn(ADMIN, APP_ROLE, APP_PW))
    try:
        # 1) View: published-only + đúng tenant
        async with app.transaction():
            await _scoped(app, TA)
            rows = await app.fetch("SELECT project_code, product_type FROM tenant_data.agent_units_v ORDER BY 2")
            assert {r["product_type"] for r in rows} == {"căn hộ", "shophouse"}  # draft unit + draft project ẩn
        # 2) Cross-tenant: RLS → 0 dòng
        async with app.transaction():
            await _scoped(app, TB)
            assert await app.fetch("SELECT * FROM tenant_data.agent_units_v") == []
        # 3) Bảng gốc + PII: permission denied
        for target in ("tenant_data.units", "tenant_data.contacts", "tenant_data.conversations"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with app.transaction():
                    await _scoped(app, TA)
                    await app.fetch(f"SELECT * FROM {target}")
        # 4) Ghi giấu trong CTE nhắm BẢNG GỐC: bị chặn bởi read-only HOẶC thiếu
        #    GRANT — thứ tự hai check trong executor không thành hợp đồng, cái
        #    nào nổ trước cũng chứng minh "không thể ghi". (Không nhắm vào view:
        #    view có JOIN không auto-updatable, sẽ nổ 'cannot delete from view'
        #    ở tầng rewrite trước khi chạm hai khoá — không chứng minh gì.)
        with pytest.raises((asyncpg.ReadOnlySQLTransactionError, asyncpg.InsufficientPrivilegeError)):
            async with app.transaction():
                await _scoped(app, TA)
                await app.fetch("WITH x AS (DELETE FROM tenant_data.units RETURNING *) SELECT * FROM x")
        # 5) Timeout
        with pytest.raises(asyncpg.QueryCanceledError):
            async with app.transaction():
                await _scoped(app, TA)
                await app.fetch("SELECT pg_sleep(5)")
        # 6) SET LOCAL reset: txn kế theo app role vẫn ghi được bình thường
        async with app.transaction():
            await app.execute("SELECT set_config('app.current_tenant', $1, true)", TA)
            await app.execute(
                "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1, 's-after')", TA
            )
    finally:
        await app.close()
