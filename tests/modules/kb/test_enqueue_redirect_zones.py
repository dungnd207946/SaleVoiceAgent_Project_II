"""`zones` không còn là doc riêng ⇒ sửa phân khu = nạp lại dự án cha.

Chuyển hướng đặt ở `dat_viec_nap` — chỗ DUY NHẤT cả đường UI lẫn đường API ingest đi qua,
nên hai đường giống nhau theo cấu trúc chứ không nhờ chép đúng hai lần.
"""

import json

from portal.core.db.session import tenant_conn
from portal.modules.kb.ops.enqueue import dat_viec_nap


async def _payloads(conn, kind: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = portal.current_tenant() AND kind = $1 ORDER BY id",
        kind,
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def test_zones_ra_job_cua_du_an_cha(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, project_code, project_id, zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="test",
            entity="zones",
            record_id=zone_id,
            project_code=project_code,
        )
        jobs = await _payloads(conn, "kb_index")
    assert len(jobs) == 1
    assert jobs[0]["entity"] == "projects"
    assert jobs[0]["record_id"] == project_id
    assert jobs[0]["project_code"] == project_code


async def test_hai_phan_khu_cung_du_an_gop_thanh_mot_viec(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, project_code, _project_id, zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        for rid in (zone_id, zone_id + 1):
            await dat_viec_nap(
                conn,
                tenant_id=tenant_id,
                actor="test",
                entity="zones",
                record_id=rid,
                project_code=project_code,
            )
        jobs = await _payloads(conn, "kb_index")
    assert len(jobs) == 1


async def test_khong_tim_thay_du_an_cha_thi_khong_xep_gi(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, _project_code, _project_id, zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        ra = await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="test",
            entity="zones",
            record_id=zone_id,
            project_code="KHONG_TON_TAI",
        )
        jobs = await _payloads(conn, "kb_index")
    assert ra is None
    assert jobs == []


async def test_entity_khac_khong_bi_doi(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, project_code, _project_id, _zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="test",
            entity="documents",
            record_id=99,
            project_code=project_code,
        )
        jobs = await _payloads(conn, "kb_index")
    assert jobs[0]["entity"] == "documents"
    assert jobs[0]["record_id"] == 99
