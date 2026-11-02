"""Xoá phân khu vẫn phải purge point `phan_khu` CŨ — cửa sổ trước khi `drop_zone_points` chạy.

Đợt 2026-08-19 bỏ doc `phan_khu`, nên `_enqueue_purge_zone` đổi sang nạp lại dự án. Nhưng
tenant nào chưa chạy `python -m portal.cli.drop_zone_points` thì Qdrant CÒN point
`phan_khu` (đo trên dev: 66 point ở 3 workspace), và nạp lại dự án không chạm chúng —
point của một phân khu ĐÃ XOÁ sống sót vĩnh viễn và agent vẫn kể về nó.

Việc purge là vô hại khi không còn point: worker tra `kb_index_state`, không có dòng thì
không xoá gì.
"""

import json

import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


async def _jobs(conn, kind: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = portal.current_tenant() AND kind = $1 ORDER BY id",
        kind,
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def test_xoa_phan_khu_xep_ca_purge_zone_va_nap_lai_du_an(client_re, workspace_re, pool):
    await client_re.post("/api/v1/projects", json={"projectCode": "zpz1", "name": "Dự án zpz1"})
    r = await client_re.post("/api/v1/projects/zpz1/zones", json={"zoneCode": "PK1", "name": "Phân khu 1"})
    assert r.status_code == 201, r.text
    zone_id = r.json()["id"]
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute("DELETE FROM control.jobs WHERE tenant_id = portal.current_tenant()")

    r = await client_re.delete("/api/v1/projects/zpz1/zones/PK1")
    assert r.status_code == 204, r.text

    async with tenant_conn(pool, workspace_re) as conn:
        purge = await _jobs(conn, "kb_delete")
        index = await _jobs(conn, "kb_index")

    assert {"entity": "zones", "record_id": zone_id} in [
        {"entity": p["entity"], "record_id": p["record_id"]} for p in purge
    ], "thiếu việc purge point phan_khu cũ của chính phân khu vừa xoá"
    assert [p["entity"] for p in index] == ["projects"], "phải nạp lại dự án cha, không nạp lại zones"
