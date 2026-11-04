import os

import pytest

DSN = os.environ.get("KB_BACKFILL_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="KB_BACKFILL_PG_DSN not set")


@pytest.mark.asyncio
async def test_upsert_and_replace_units_idempotent():
    from kb_backfill import pg_sink
    conn = await pg_sink.connect(DSN)
    try:
        proj = {"project_code": "SP2T", "name": "SP2 Test", "category": ["chung_cu"],
                "region": "R", "address": "A", "investor": "I", "product_scale": "s",
                "ownership_form": "o", "overview": "ov", "sale_phase": "dang_ban"}
        units = [{"project_code": "SP2T", "unit_code": "U1", "product_type": "chung_cu",
                  "bedrooms": 2, "direction": "dong_nam", "area_built_m2": 70.0,
                  "area_wall_m2": 75.0, "price_vnd": 3_000_000_000,
                  "price_per_m2_vnd": 42_857_143, "sale_status": "available", "image_url": None}]
        async with conn.transaction():
            await pg_sink.upsert_project(conn, "noble", proj)
            await pg_sink.replace_units(conn, "noble", "SP2T", units)
        # re-run (idempotent): counts stay 1/1
        async with conn.transaction():
            await pg_sink.upsert_project(conn, "noble", {**proj, "name": "SP2 Test v2"})
            await pg_sink.replace_units(conn, "noble", "SP2T", units)
        n_proj = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.projects WHERE tenant_id='noble' AND project_code='SP2T'")
        n_unit = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.units WHERE tenant_id='noble' AND project_code='SP2T'")
        name = await conn.fetchval(
            "SELECT name FROM tenant_data.projects WHERE tenant_id='noble' AND project_code='SP2T'")
        assert n_proj == 1 and n_unit == 1 and name == "SP2 Test v2"
    finally:
        await conn.execute("DELETE FROM tenant_data.projects WHERE tenant_id='noble' AND project_code='SP2T'")
        await conn.close()
