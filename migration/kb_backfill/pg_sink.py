"""asyncpg sink for the KB backfill. Uses the admin/superuser DSN (RLS bypassed);
tenant_id is written explicitly. Units are replaced per-project (delete+insert)
since the units table has no natural unique key."""
from __future__ import annotations

_PROJECT_COLS = ("project_code", "name", "category", "region", "address", "investor",
                 "product_scale", "ownership_form", "overview", "sale_phase")
_UNIT_COLS = ("project_code", "unit_code", "product_type", "bedrooms", "direction",
              "area_built_m2", "area_wall_m2", "price_vnd", "price_per_m2_vnd",
              "sale_status", "image_url")


async def connect(dsn: str):
    import asyncpg
    return await asyncpg.connect(dsn)


async def upsert_project(conn, tenant: str, row: dict) -> None:
    cols = ["tenant_id", "status", *_PROJECT_COLS]
    vals = [tenant, "published", *[row.get(c) for c in _PROJECT_COLS]]
    ph = ", ".join(f"${i+1}" for i in range(len(cols)))
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in ("status", *_PROJECT_COLS) if c != "project_code")
    sql = (
        f"INSERT INTO tenant_data.projects ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT (tenant_id, project_code) DO UPDATE SET {updates}, updated_at=now()"
    )
    await conn.execute(sql, *vals)


async def replace_units(conn, tenant: str, project_code: str, rows: list[dict]) -> None:
    await conn.execute(
        "DELETE FROM tenant_data.units WHERE tenant_id=$1 AND project_code=$2", tenant, project_code)
    if not rows:
        return
    cols = ["tenant_id", "status", *_UNIT_COLS]
    ph = ", ".join(f"${i+1}" for i in range(len(cols)))
    sql = f"INSERT INTO tenant_data.units ({', '.join(cols)}) VALUES ({ph})"
    await conn.executemany(sql, [[tenant, "published", *[r.get(c) for c in _UNIT_COLS]] for r in rows])
