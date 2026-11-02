"""API cảnh báo mâu thuẫn — workspace `cf_anphu` của fixture `client_cfg` (Quản trị)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.conflicts import repo
from portal.modules.kb.conflicts.repo import KIND_CONFLICT_CHECK, Row, Side
from tests.modules.config.conftest import client_cfg, workspace_cfg  # noqa: F401

TENANT = "cf_anphu"
DOC = Side(entity="documents", record_id=1, field=None, label="CSBH tháng 7", quote="đến 30/11/2026")
FIELD = Side(entity="projects", record_id=9, field="investor", label="Chủ đầu tư", quote="Noble")


@pytest.fixture
async def du_lieu(pool, client_cfg):  # noqa: F811
    async with tenant_conn(pool, TENANT) as c:
        for code, name in (("nplb", "Noble Palace Long Biên"), ("slc", "Sunshine Legend City")):
            await c.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)"
                " VALUES (portal.current_tenant(), $1, $2, 'published')",
                code,
                name,
            )
        await repo.insert_rows(
            c,
            [
                Row("nplb", "c:a", "f:b", "open", "Chủ đầu tư khác nhau", DOC, FIELD),
                Row("nplb", "c:c", "c:d", "open", "Hai CSBH khác thời hạn", DOC, DOC),
                Row("nplb", "c:e", "c:f", "none"),
            ],
        )
    yield client_cfg
    async with pool.acquire() as c:
        await c.execute("DELETE FROM control.jobs WHERE tenant_id = $1", TENANT)
        await c.execute("DELETE FROM control.audit_log WHERE tenant_id = $1", TENANT)


async def test_summary_tra_moi_du_an(du_lieu):
    r = await du_lieu.get("/api/v1/conflicts/summary")
    assert r.status_code == 200, r.text
    rows = {i["projectCode"]: i for i in r.json()}
    assert rows["nplb"] == {
        "projectCode": "nplb",
        "name": "Noble Palace Long Biên",
        "open": 2,
        "checking": False,
        "failed": False,
        "checkedAt": None,
    }
    assert rows["slc"]["open"] == 0


async def test_danh_sach_cua_du_an(du_lieu):
    r = await du_lieu.get("/api/v1/projects/nplb/conflicts")
    assert r.status_code == 200, r.text
    items = r.json()
    assert {i["summary"] for i in items} == {"Chủ đầu tư khác nhau", "Hai CSBH khác thời hạn"}
    field_side = next(s for i in items for s in (i["left"], i["right"]) if s["field"])
    assert field_side == {
        "entity": "projects",
        "recordId": 9,
        "field": "investor",
        "label": "Chủ đầu tư",
        "quote": "Noble",
    }


async def test_check_theo_moc_va_trang_thai_job(pool, du_lieu):
    since = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    r = await du_lieu.get("/api/v1/projects/nplb/conflicts/check", params={"since": since})
    assert r.json() == {"checking": False, "failed": False, "checkedAt": None, "conflicts": []}
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload) VALUES ($1, $2, 't', $3::jsonb)",
            TENANT,
            KIND_CONFLICT_CHECK,
            json.dumps({"project_code": "nplb"}),
        )
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    body = (await du_lieu.get("/api/v1/projects/nplb/conflicts/check", params={"since": old})).json()
    assert body["checking"] is True and len(body["conflicts"]) == 2


async def test_bo_qua_roi_bien_mat_va_ghi_nhat_ky(pool, du_lieu):
    items = (await du_lieu.get("/api/v1/projects/nplb/conflicts")).json()
    cid = items[0]["id"]
    r = await du_lieu.post(f"/api/v1/conflicts/{cid}/dismiss")
    assert r.status_code == 204, r.text
    assert cid not in {i["id"] for i in (await du_lieu.get("/api/v1/projects/nplb/conflicts")).json()}
    assert (await du_lieu.get("/api/v1/conflicts/summary")).json()[0]["open"] == 1
    assert (await du_lieu.post(f"/api/v1/conflicts/{cid}/dismiss")).status_code == 404
    async with pool.acquire() as c:
        n = await c.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'conflict.dismiss'", TENANT
        )
    assert n == 1


async def test_quet_mot_du_an_va_tat_ca(pool, du_lieu):
    r = await du_lieu.post("/api/v1/projects/nplb/conflicts/scan")
    assert r.status_code == 202 and r.json()["jobId"] is not None
    assert (await du_lieu.post("/api/v1/projects/nplb/conflicts/scan")).json() == {"jobId": None}
    r = await du_lieu.post("/api/v1/conflicts/scan")
    assert r.status_code == 202 and r.json() == {"queued": 1}
    async with pool.acquire() as c:
        n = await c.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'conflict.scan'", TENANT
        )
    assert n == 3
