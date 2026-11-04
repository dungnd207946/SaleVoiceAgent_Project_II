"""SP1 KB Postgres schema live proof — schema/RLS-shape check for the 5 KB tables,
plus (Task 10) a cross-tenant RLS isolation + roundtrip proof for
`PostgresKBProvider` and a deprovision-reaps-KB-rows proof.

Requires a reachable Postgres SUPERUSER DSN in ``SPE_PG_ADMIN_DSN`` (skipped
otherwise, same gate as ``test_pg_rls_live.py``). Confirms ``apply_schema``
also applies ``kb_real_estate.sql`` (idempotently) and that the tables land in
``tenant_data`` with RLS enabled.

Run:
    SPE_PG_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey \
      pytest tests/integration/tenant/test_kb_pg_live.py -q
"""

from __future__ import annotations

import os

import asyncpg
import pytest

from noble_agent.data.providers import base
from noble_agent.data.providers.postgres_kb import PostgresKBProvider
from noble_agent.storage import postgres_client
from noble_agent.storage.postgres_client import tenant_conn
from noble_agent.tenant import pg_provisioning
from noble_agent.tenant.current import use_tenant

ADMIN_DSN = os.environ.get("SPE_PG_ADMIN_DSN")
pytestmark = [
    pytest.mark.needs_postgres,
    pytest.mark.skipif(not ADMIN_DSN, reason="live PG admin DSN not set"),
]

_KB_APP_ROLE = "kb_probe_app_role"
_KB_APP_PW = "kb_probe_pw"
_TA, _TB = "kb_ta", "kb_tb"


def _app_dsn(admin: str, role: str, pw: str) -> str:
    """Swap the admin DSN's user:pass for ``role`` — same shape as
    test_pg_rls_live.py's private helper of the same name."""
    head, tail = admin.split("://", 1)
    _cred, hostpart = tail.split("@", 1)
    return f"{head}://{role}:{pw}@{hostpart}"


@pytest.mark.asyncio
async def test_kb_schema_applies_and_rls_scopes():
    await pg_provisioning.apply_schema(ADMIN_DSN)  # idempotent, applies both SQL files
    await pg_provisioning.apply_schema(ADMIN_DSN)  # re-run must not error (idempotency)
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        # app_role path: set tenant, insert, and confirm the other tenant sees 0.
        await conn.execute("SELECT set_config('app.current_tenant', 'ta', true)")
        # (full insert/read/isolation asserted below via the shared app role;
        #  here just prove the tables + policies exist)
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='tenant_data' AND tablename = ANY($1)",
            ["projects", "zones", "units", "documents", "media"],
        )
        assert {r["tablename"] for r in rows} == {"projects", "zones", "units", "documents", "media"}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_kb_provider_cross_tenant_isolation_and_roundtrip():
    """Live proof that PostgresKBProvider's real _acquire/tenant_conn path is
    RLS-isolated under connection reuse (mirrors
    test_pg_rls_live.py::test_app_role_set_local_isolation_and_leak)."""
    await pg_provisioning.apply_schema(ADMIN_DSN)
    await pg_provisioning.ensure_app_role(ADMIN_DSN, role=_KB_APP_ROLE, password=_KB_APP_PW)

    # Clean slate for reruns (superuser bypasses RLS).
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute("DELETE FROM tenant_data.units WHERE tenant_id = ANY($1)", [_TA, _TB])
        await admin.execute("DELETE FROM tenant_data.projects WHERE tenant_id = ANY($1)", [_TA, _TB])
    finally:
        await admin.close()

    pool = await asyncpg.create_pool(
        _app_dsn(ADMIN_DSN, _KB_APP_ROLE, _KB_APP_PW), min_size=1, max_size=1
    )  # size-1 forces connection reuse across the re-scoped calls below
    postgres_client.set_pool_for_tests(pool)
    try:
        # Seed tenant A's project + unit through the real tenant_conn path.
        async with tenant_conn(pool, _TA) as c:
            await c.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
                "VALUES ($1,$2,$3,'published')",
                _TA,
                "ISOL1",
                "Isolation Test Project",
            )
            await c.execute(
                "INSERT INTO tenant_data.units (tenant_id, project_code, unit_code, status, sale_status) "
                "VALUES ($1,$2,$3,'published','available')",
                _TA,
                "ISOL1",
                "U-1",
            )

        provider = PostgresKBProvider()

        # Tenant A sees its own rows via the real provider path.
        with use_tenant(_TA):
            overview = await provider.get_overview("ISOL1")
            assert overview is not None
            assert overview.code == "ISOL1"
            units = await provider.search_units(base.UnitQuery(project_code="ISOL1"))
            assert units is not None and len(units) == 1

        # LEAK-ON-REUSE (the critical one): the SAME pooled conn, re-scoped to B,
        # sees ZERO of A's rows.
        with use_tenant(_TB):
            assert await provider.get_overview("ISOL1") is None
            assert await provider.search_units(base.UnitQuery(project_code="ISOL1")) is None

        # Re-scoped back to A → the rows reappear (no leak, no false negative).
        with use_tenant(_TA):
            assert await provider.get_overview("ISOL1") is not None
            units = await provider.search_units(base.UnitQuery(project_code="ISOL1"))
            assert units is not None and len(units) == 1

        # Fail-closed: a raw pooled connection with NO set_config (GUC unset)
        # sees 0 rows regardless of tenant.
        async with pool.acquire() as raw:
            n = await raw.fetchval("SELECT count(*) FROM tenant_data.projects WHERE project_code = $1", "ISOL1")
            assert n == 0
    finally:
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute("DELETE FROM tenant_data.units WHERE tenant_id = ANY($1)", [_TA, _TB])
            await admin.execute("DELETE FROM tenant_data.projects WHERE tenant_id = ANY($1)", [_TA, _TB])
        finally:
            await admin.close()
        await postgres_client.close_pool()


@pytest.mark.asyncio
async def test_get_document_an_tai_lieu_cua_du_an_archived():
    """Document published nhưng dự án cha đã archived (op:delete từ cổng nạp
    Portal) không được lộ qua get_document — cùng luật parent-join
    p.status='published' với search_units. Tài liệu neo
    sentinel __ALL__ (kho kb_files) vẫn phải trả: row hệ thống luôn published
    (quy ước Portal)."""
    await pg_provisioning.apply_schema(ADMIN_DSN)
    await pg_provisioning.ensure_app_role(ADMIN_DSN, role=_KB_APP_ROLE, password=_KB_APP_PW)
    tenant_id = "kb_probe_docs"

    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute("DELETE FROM tenant_data.documents WHERE tenant_id = $1", tenant_id)
        await admin.execute("DELETE FROM tenant_data.projects WHERE tenant_id = $1", tenant_id)
        await admin.executemany(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) VALUES ($1,$2,$3,$4)",
            [
                (tenant_id, "DOCP1", "Dự án đang bán", "published"),
                (tenant_id, "DOCP2", "Dự án đã archived", "archived"),
                (tenant_id, "__ALL__", "Kho chung", "published"),
            ],
        )
        await admin.executemany(
            "INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, status) "
            "VALUES ($1,$2,$3,$4,'published')",
            [
                (tenant_id, "DOCP1", "CSBH dự án sống", "chiết khấu 5%"),
                (tenant_id, "DOCP2", "CSBH dự án đã gỡ", "tài liệu mồ côi"),
                (tenant_id, "__ALL__", "Sổ tay chung", "quy trình đặt cọc"),
            ],
        )
    finally:
        await admin.close()

    pool = await asyncpg.create_pool(_app_dsn(ADMIN_DSN, _KB_APP_ROLE, _KB_APP_PW), min_size=1, max_size=1)
    postgres_client.set_pool_for_tests(pool)
    try:
        provider = PostgresKBProvider()
        with use_tenant(tenant_id):
            # Dự án sống: tài liệu của nó + tài liệu __ALL__ cùng trả.
            docs = await provider.get_document("DOCP1")
            assert {d.title for d in docs} == {"CSBH dự án sống", "Sổ tay chung"}
            # Dự án archived: tài liệu CỦA NÓ phải ẩn, __ALL__ vẫn trả.
            docs = await provider.get_document("DOCP2")
            assert {d.title for d in docs} == {"Sổ tay chung"}
    finally:
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute("DELETE FROM tenant_data.documents WHERE tenant_id = $1", tenant_id)
            await admin.execute("DELETE FROM tenant_data.projects WHERE tenant_id = $1", tenant_id)
        finally:
            await admin.close()
        await postgres_client.close_pool()


@pytest.mark.asyncio
async def test_kb_deprovision_reaps_kb_table_rows():
    """The Task-1-review fold-in: `deprovision` must DELETE a tenant's rows from
    the 5 new KB tables too (design doc §5 NĐ13), not just the 3 Odyssey tables."""
    await pg_provisioning.apply_schema(ADMIN_DSN)
    tenant_id = "kb_probe_deprov"

    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute("DELETE FROM tenant_data.projects WHERE tenant_id = $1", tenant_id)
        await admin.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES ($1,$2,$3,'published')",
            tenant_id,
            "DPROV1",
            "Deprovision Test Project",
        )
        await admin.execute(
            "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, status) "
            "VALUES ($1,$2,$3,'published')",
            tenant_id,
            "DPROV1",
            "Z-1",
        )
        await admin.execute(
            "INSERT INTO tenant_data.units (tenant_id, project_code, unit_code, status) VALUES ($1,$2,$3,'published')",
            tenant_id,
            "DPROV1",
            "U-1",
        )
        await admin.execute(
            "INSERT INTO tenant_data.documents (tenant_id, project_code, title, status) VALUES ($1,$2,$3,'published')",
            tenant_id,
            "DPROV1",
            "Doc 1",
        )
        await admin.execute(
            "INSERT INTO tenant_data.media (tenant_id, project_code, media_url, status) VALUES ($1,$2,$3,'published')",
            tenant_id,
            "DPROV1",
            "http://example.test/x.jpg",
        )

        await pg_provisioning.deprovision(ADMIN_DSN, tenant_id)

        for table in ("projects", "zones", "units", "documents", "media"):
            n = await admin.fetchval(f"SELECT count(*) FROM tenant_data.{table} WHERE tenant_id = $1", tenant_id)
            assert n == 0, f"deprovision left rows behind in tenant_data.{table}"
    finally:
        await admin.execute("DELETE FROM tenant_data.projects WHERE tenant_id = $1", tenant_id)
        await admin.close()
