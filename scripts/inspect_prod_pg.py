#!/usr/bin/env python3
"""Inspect a Postgres (structure only — NO secret values) so we can align the
local sim to production. Safe to paste into the EC2 host: runs only SELECTs and
pg_get_* introspection; never reads passwords, API-key hashes, or config content.

Run on the EC2 (agent venv has asyncpg), pass the admin DSN explicitly:
    python inspect_prod_pg.py "postgresql://USER:PASS@HOST:5432/DBNAME"
or rely on env:
    python inspect_prod_pg.py            # uses $POSTGRES_ADMIN_DSN, else $POSTGRES_DSN

Then paste the whole output back.
"""
from __future__ import annotations

import os
import sys

SCHEMAS = ("tenant_data", "control", "agent_api", "public", "portal")
_S = "','".join(SCHEMAS)
IN_SCHEMAS = f"('{_S}')"

# (title, sql). Structure only. Nothing selects a secret value.
QUERIES: list[tuple[str, str]] = [
    ("server / connection",
     "SELECT version() AS v, current_database() AS db, current_user AS usr, "
     "current_setting('server_version_num') AS version_num"),
    ("roles (NO passwords)",
     r"SELECT rolname, rolcanlogin AS login, rolsuper AS super, rolcreaterole AS createrole, "
     r"rolcreatedb AS createdb, rolbypassrls AS bypassrls, rolreplication AS repl "
     r"FROM pg_roles WHERE rolname NOT LIKE 'pg\_%' ORDER BY rolname"),
    ("role memberships",
     "SELECT m.rolname AS member, g.rolname AS is_member_of "
     "FROM pg_auth_members am JOIN pg_roles m ON m.oid=am.member "
     "JOIN pg_roles g ON g.oid=am.roleid ORDER BY 1,2"),
    ("schemas + owner",
     r"SELECT n.nspname AS schema, pg_get_userbyid(n.nspowner) AS owner FROM pg_namespace n "
     rf"WHERE n.nspname NOT LIKE 'pg\_%' AND n.nspname<>'information_schema' ORDER BY 1"),
    ("tables: owner, RLS on/forced, approx rows",
     "SELECT n.nspname AS schema, c.relname AS table, pg_get_userbyid(c.relowner) AS owner, "
     "c.relrowsecurity AS rls_on, c.relforcerowsecurity AS rls_forced, c.reltuples::bigint AS approx_rows "
     "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
     f"WHERE c.relkind='r' AND n.nspname IN {IN_SCHEMAS} ORDER BY 1,2"),
    ("columns (interesting schemas)",
     "SELECT table_schema AS schema, table_name AS \"table\", ordinal_position AS pos, "
     "column_name AS col, data_type AS type, is_nullable AS nullable, column_default AS default_ "
     f"FROM information_schema.columns WHERE table_schema IN {IN_SCHEMAS} ORDER BY 1,2,3"),
    ("CHECK / UNIQUE / FK constraints",
     "SELECT n.nspname AS schema, rel.relname AS table, con.conname AS name, "
     "CASE con.contype WHEN 'c' THEN 'check' WHEN 'u' THEN 'unique' WHEN 'p' THEN 'pkey' "
     "WHEN 'f' THEN 'fkey' ELSE con.contype::text END AS kind, "
     "pg_get_constraintdef(con.oid) AS def "
     "FROM pg_constraint con JOIN pg_class rel ON rel.oid=con.conrelid "
     f"JOIN pg_namespace n ON n.oid=rel.relnamespace WHERE n.nspname IN {IN_SCHEMAS} ORDER BY 1,2,4"),
    ("views (list)",
     f"SELECT schemaname AS schema, viewname AS view FROM pg_views WHERE schemaname IN {IN_SCHEMAS} ORDER BY 1,2"),
    ("VIEW DEFINITIONS",
     "SELECT schemaname AS schema, viewname AS view, "
     "pg_get_viewdef((quote_ident(schemaname)||'.'||quote_ident(viewname))::regclass, true) AS definition "
     f"FROM pg_views WHERE schemaname IN {IN_SCHEMAS} ORDER BY 1,2"),
    ("FUNCTION DEFINITIONS (portal/agent_api/control)",
     "SELECT n.nspname AS schema, p.proname AS func, pg_get_function_identity_arguments(p.oid) AS args, "
     "pg_get_functiondef(p.oid) AS definition FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
     "WHERE n.nspname IN ('portal','agent_api','control') ORDER BY 1,2"),
    ("RLS POLICIES",
     "SELECT schemaname AS schema, tablename AS table, policyname AS policy, permissive, roles, cmd, "
     "qual, with_check FROM pg_policies "
     "WHERE schemaname IN ('tenant_data','control','public') ORDER BY 1,2,3"),
    ("table grants (per grantee)",
     "SELECT grantee, table_schema AS schema, table_name AS table, "
     "string_agg(privilege_type, ',' ORDER BY privilege_type) AS privs "
     f"FROM information_schema.role_table_grants WHERE table_schema IN {IN_SCHEMAS} "
     "GROUP BY 1,2,3 ORDER BY 1,2,3"),
    # `agent_api.*` bỏ ở Portal 0917, `control.deployments` ở 0941 — GIỮ trong danh sách
    # CỐ Ý: cột `present` của chúng phải là false, và một `true` nghĩa là DB đó chưa
    # migrate tới nơi. Bỏ khỏi danh sách là mất luôn phép kiểm đó.
    ("CONTRACT presence check (what the agent reads)",
     "SELECT obj, to_regclass(obj) IS NOT NULL AS present FROM (VALUES "
     "('tenant_data.agent_config'),('agent_api.tenant_status'),('agent_api.tenant_keys'),"
     "('agent_api.deployments'),('control.tenants'),('control.deployments'),('control.agent_keys'),"
     "('control.agent_heartbeats'),('public.agent_published_config'),('public.agent_config_versions'),"
     "('public.agent_config_pointer')) v(obj) "
     "UNION ALL SELECT 'portal.current_tenant()', to_regproc('portal.current_tenant') IS NOT NULL"),
]

BLOCK_SECTIONS = {"VIEW DEFINITIONS", "FUNCTION DEFINITIONS (portal/agent_api/control)", "RLS POLICIES"}


def _cell(v: object) -> str:
    return "" if v is None else str(v)


def print_section(title: str, cols: list[str], rows: list[tuple]) -> None:
    print(f"\n########## {title}  ({len(rows)} rows) ##########")
    if not rows:
        print("(none)")
        return
    if title in BLOCK_SECTIONS:
        for r in rows:
            head = "  ".join(f"{c}={_cell(v)}" for c, v in zip(cols[:-1], r[:-1]))
            print(f"\n--- {head} ---")
            print(_cell(r[-1]))
        return
    widths = [len(c) for c in cols]
    srows = [[_cell(v) for v in r] for r in rows]
    for r in srows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], min(len(v), 80))
    print(" | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
    print("-+-".join("-" * widths[i] for i in range(len(cols))))
    for r in srows:
        print(" | ".join(v.ljust(widths[i]) for i, v in enumerate(r)))


def get_dsn() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    dsn = os.getenv("POSTGRES_ADMIN_DSN") or os.getenv("POSTGRES_DSN")
    if not dsn:
        sys.exit("No DSN. Pass it as argv[1] or set POSTGRES_ADMIN_DSN / POSTGRES_DSN.")
    return dsn


async def _run_asyncpg(dsn: str) -> None:
    import asyncpg
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        await conn.execute("SET statement_timeout='30s'")
        for title, sql in QUERIES:
            try:
                recs = await conn.fetch(sql)
                cols = list(recs[0].keys()) if recs else []
                print_section(title, cols, [tuple(r.values()) for r in recs])
            except Exception as exc:  # noqa: BLE001
                print(f"\n########## {title} ##########\n!! query failed: {exc}")
    finally:
        await conn.close()


def _run_psycopg(dsn: str, connect) -> None:
    conn = connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout='30s'")
        for title, sql in QUERIES:
            try:
                cur.execute(sql)
                cols = [d[0] for d in cur.description]
                print_section(title, cols, cur.fetchall())
            except Exception as exc:  # noqa: BLE001
                conn.rollback() if not conn.autocommit else None
                print(f"\n########## {title} ##########\n!! query failed: {exc}")
    finally:
        conn.close()


def main() -> None:
    dsn = get_dsn()
    safe = dsn
    if "@" in dsn:  # never echo the password
        safe = dsn.split("://", 1)[0] + "://***@" + dsn.split("@", 1)[1]
    print(f"# inspecting: {safe}")
    try:
        import asyncio

        import asyncpg  # noqa: F401
        asyncio.run(_run_asyncpg(dsn))
        return
    except ImportError:
        pass
    try:
        import psycopg
        _run_psycopg(dsn, psycopg.connect)
        return
    except ImportError:
        pass
    try:
        import psycopg2
        _run_psycopg(dsn, psycopg2.connect)
        return
    except ImportError:
        sys.exit("Need one of: asyncpg, psycopg (v3), or psycopg2. In the agent venv asyncpg is present.")


if __name__ == "__main__":
    main()
