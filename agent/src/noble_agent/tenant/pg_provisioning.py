"""SP-E1 Postgres provisioning (agent-side, per N9 = agent owns DDL + roles).

`noble-tenant pg-apply-schema` applies the shared data-plane schema once (admin
DSN); `pg-provision <tenant>` creates the per-tenant LOGIN role (name = tenant_id
so RLS `current_user` matching works) + grants CRUD on the 3 tables, all-or-nothing
(native: CREATE ROLE + GRANT run inside one transaction that rolls back on error);
`pg-deprovision <tenant>` drops the role's owned objects + rows + the role.

``asyncpg`` is imported lazily inside the async fns so this module (and the CLI that
imports it) collects without the driver installed.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_SQL_PATH = Path(__file__).resolve().parent.parent / "storage" / "sql" / "odyssey_data_plane.sql"
_KB_SQL_PATH = Path(__file__).resolve().parent.parent / "storage" / "sql" / "kb_real_estate.sql"


def role_name(tenant_id: str) -> str:
    """The Postgres role for a tenant = the tenant_id itself (RLS keys on it).

    Validated to a safe identifier so it can be quoted into DDL without injection
    (asyncpg cannot parameterize identifiers). Raises ``ValueError`` otherwise.
    """
    if not _ROLE_RE.match(tenant_id or ""):
        raise ValueError(f"tenant_id {tenant_id!r} is not a safe Postgres role name (^[a-z][a-z0-9_-]{{0,62}}$)")
    return tenant_id


def read_ddl() -> str:
    """The shared data-plane DDL (schema + 3 tables + RLS)."""
    return _SQL_PATH.read_text(encoding="utf-8")


def read_kb_ddl() -> str:
    """SP1 KB data-plane DDL (schema + projects/zones/units/documents/media + RLS)."""
    return _KB_SQL_PATH.read_text(encoding="utf-8")


def _pw_literal(password: str) -> str:
    """Single-quoted SQL string literal for a role password (escape quotes)."""
    if not password:
        raise ValueError("empty Postgres role password")
    return "'" + password.replace("'", "''") + "'"


_TABLES = (
    "conversations",
    "conversation_messages",
    "appointments",
    "contacts",
    "escalations",
    "projects",
    "zones",
    "units",
    "documents",
    "media",
)


async def apply_schema(admin_dsn: str) -> None:
    """Apply the shared data-plane DDL (idempotent). Superuser/owner conn.

    Applies both the Odyssey data plane (conversations/appointments/contacts)
    AND the SP1 KB data plane (projects/zones/units/documents/media).
    """
    import asyncpg

    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(read_ddl())
        await conn.execute(read_kb_ddl())
    finally:
        await conn.close()


async def provision(admin_dsn: str, tenant_id: str, password: str, *, sql_ro_role: str = "agent_sql_ro") -> str:
    """Create the tenant's LOGIN role + grants (all-or-nothing). Returns role name.

    Raises if the role already exists (deprovision first). CREATE ROLE + GRANT run
    in one transaction so a mid-way failure leaves nothing behind (BR12).
    """
    role = role_name(tenant_id)
    pw = _pw_literal(password)
    import asyncpg

    conn = await asyncpg.connect(admin_dsn)
    try:
        async with conn.transaction():
            await conn.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD {pw}')
            await conn.execute(f'GRANT USAGE ON SCHEMA tenant_data TO "{role}"')
            await conn.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tenant_data TO "{role}"'
            )
            if _ROLE_RE.match(sql_ro_role) and await conn.fetchval(
                "SELECT 1 FROM pg_roles WHERE rolname=$1", sql_ro_role
            ):
                await conn.execute(f'GRANT "{sql_ro_role}" TO "{role}"')
    finally:
        await conn.close()
    return role


def assert_app_role_distinct(role: str, tenant_ids) -> None:
    """The shared runtime app role must be a valid slug AND differ from every
    tenant_id — else the current_user clause of tenant_isolation matches it by
    accident (memo §6 trap)."""
    if not _ROLE_RE.match(role):
        raise ValueError(f"invalid app role name: {role!r}")
    collisions = {t for t in tenant_ids if t == role}
    if collisions:
        raise ValueError(f"app role {role!r} collides with tenant id(s): {sorted(collisions)}")


async def ensure_app_role(admin_dsn: str, *, role: str, password: str) -> None:
    """Create (idempotently) the ONE shared runtime app role: LOGIN, non-owner,
    non-superuser, NOT BYPASSRLS (so RLS FORCE still binds it), with CRUD on the
    3 tables. Called once at bootstrap, NOT per tenant."""
    import asyncpg

    if not _ROLE_RE.match(role):
        raise ValueError(f"invalid app role name: {role!r}")
    pw = _pw_literal(password)
    conn = await asyncpg.connect(admin_dsn)
    try:
        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            if not exists:
                await conn.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD {pw} NOBYPASSRLS')
            await conn.execute(f'GRANT USAGE ON SCHEMA tenant_data TO "{role}"')
            await conn.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tenant_data TO "{role}"'
            )
    finally:
        await conn.close()


VIEW_OWNER_ROLE = "agent_kb_view_owner"
AGENT_VIEWS = ("agent_projects_v", "agent_units_v")


async def ensure_sql_ro_roles(
    admin_dsn: str, *, sql_ro_role: str, app_role: str, tenant_roles: tuple = ()
) -> None:
    """Idempotent: tạo owner NOBYPASSRLS cho 2 view analyze_projects + role
    `agent_sql_ro` CHỈ có SELECT trên 2 view đó, rồi grant membership cho app
    role VÀ các role tenant đang tồn tại (đường gateway per-tenant credential
    kết nối bằng role tenant, không phải app role — thiếu grant này thì
    `SET LOCAL ROLE agent_sql_ro` fail trên đường đó). Đòi view đã tồn tại
    (chạy `pg-apply-schema` trước). NOLOGIN cả hai — không cần password."""
    for r in (sql_ro_role, app_role, VIEW_OWNER_ROLE):
        if not _ROLE_RE.match(r):
            raise ValueError(f"invalid role name: {r!r}")
    import asyncpg

    conn = await asyncpg.connect(admin_dsn)
    try:
        async with conn.transaction():
            for view in AGENT_VIEWS:
                ok = await conn.fetchval(
                    "SELECT 1 FROM pg_views WHERE schemaname='tenant_data' AND viewname=$1", view
                )
                if not ok:
                    raise RuntimeError(
                        f"view tenant_data.{view} chưa tồn tại — chạy `noble-tenant pg-apply-schema` trước"
                    )
            for role, opts in ((VIEW_OWNER_ROLE, "NOLOGIN NOBYPASSRLS"), (sql_ro_role, "NOLOGIN")):
                if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role):
                    await conn.execute(f'CREATE ROLE "{role}" {opts}')
            await conn.execute(f'GRANT USAGE ON SCHEMA tenant_data TO "{VIEW_OWNER_ROLE}", "{sql_ro_role}"')
            await conn.execute(f'GRANT SELECT ON tenant_data.projects, tenant_data.units TO "{VIEW_OWNER_ROLE}"')
            for view in AGENT_VIEWS:
                await conn.execute(f'ALTER VIEW tenant_data.{view} OWNER TO "{VIEW_OWNER_ROLE}"')
                await conn.execute(f'GRANT SELECT ON tenant_data.{view} TO "{sql_ro_role}"')
            for member in dict.fromkeys((app_role, *tenant_roles)):  # dedupe, giữ thứ tự
                if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", member):
                    await conn.execute(f'GRANT "{sql_ro_role}" TO "{member}"')
    finally:
        await conn.close()


async def deprovision(admin_dsn: str, tenant_id: str) -> None:
    """Drop the tenant's rows + owned objects + role (idempotent-ish).

    Superuser bypasses RLS, so it deletes the tenant's rows across the Odyssey
    (conversations/appointments/contacts) AND SP1 KB
    (projects/zones/units/documents/media) tables, then ``DROP OWNED`` (grants)
    and ``DROP ROLE IF EXISTS``. `projects` is deleted before its FK children
    (zones/units/documents/media cascade on it) — harmless either way since each
    DELETE is independently filtered by `tenant_id`, but deleting the parent
    first means the child DELETEs are usually no-ops.
    """
    role = role_name(tenant_id)
    import asyncpg

    conn = await asyncpg.connect(admin_dsn)
    try:
        for t in _TABLES:
            await conn.execute(f"DELETE FROM tenant_data.{t} WHERE tenant_id = $1", role)
        # DROP OWNED / DROP ROLE only if the role exists (else DROP OWNED errors).
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        if exists:
            await conn.execute(f'DROP OWNED BY "{role}"')
            await conn.execute(f'DROP ROLE IF EXISTS "{role}"')
    finally:
        await conn.close()
