import json
from datetime import UTC, datetime

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.conflicts import repo
from portal.modules.kb.conflicts.repo import Row, Side

from .conftest import OTHER

DOC = Side(entity="documents", record_id=1, field=None, label="CSBH tháng 7", quote="đến 30/11/2026")
FIELD = Side(entity="projects", record_id=9, field="investor", label="Chủ đầu tư", quote="Noble")


def _open(left="c:a", right="c:b", project="nplb"):
    return Row(project, left, right, "open", "Thời hạn khác nhau", DOC, FIELD)


@pytest.fixture
async def tenant(pool, seed_conflict_tenant):
    async with tenant_conn(pool, seed_conflict_tenant) as c:
        await c.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)"
            " VALUES (portal.current_tenant(), 'nplb', 'Noble Palace Long Biên', 'published')"
        )
    return seed_conflict_tenant


async def test_mot_cap_chi_ghi_mot_lan(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        assert await repo.insert_rows(c, [_open(), _open()]) == 1
        assert await repo.insert_rows(c, [Row("nplb", "c:a", "c:b", "none")]) == 0
        assert len(await repo.list_open(c, "nplb")) == 1


async def test_cap_da_phan_gom_ca_none_va_dismissed(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        await repo.insert_rows(c, [_open(), Row("nplb", "c:x", "c:y", "none")])
        got = await repo.judged_pairs(c, [("c:a", "c:b"), ("c:x", "c:y"), ("c:m", "c:n")])
    assert got == {("c:a", "c:b"), ("c:x", "c:y")}


async def test_dismissed_khong_mo_lai(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        await repo.insert_rows(c, [_open()])
        cid = (await repo.list_open(c, "nplb"))[0]["id"]
        assert await repo.dismiss(c, cid, "u_1") is not None
        assert await repo.dismiss(c, cid, "u_1") is None
        await repo.insert_rows(c, [_open()])
        assert await repo.list_open(c, "nplb") == []


async def test_resolve_hash_khong_con_va_bo_dismissed(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        await repo.insert_rows(c, [_open("c:a", "c:b"), _open("c:a", "c:c"), _open("c:d", "c:e")])
        keep = await repo.list_open(c, "nplb")
        did = next(r["id"] for r in keep if r["left_hash"] == "c:d")
        await repo.dismiss(c, did, "u_1")
        assert await repo.resolve_stale(c, "nplb", {"c:a", "c:b"}) == 1
        left = {(r["left_hash"], r["right_hash"]) for r in await repo.list_open(c, "nplb")}
        status = await c.fetchval("SELECT status FROM tenant_data.data_conflicts WHERE id = $1", did)
    assert left == {("c:a", "c:b")}
    assert status == "dismissed"


async def test_xoa_none_mo_coi(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        await repo.insert_rows(c, [Row("nplb", "c:a", "b:old", "none"), Row("nplb", "c:a", "c:b", "none")])
        assert await repo.drop_stale_none(c, "nplb", {"c:a", "c:b"}) == 1


async def _job(pool, tenant, state, kind="kb_conflict_check", finished=None):
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload, state, finished_at)"
            " VALUES ($1, $2, 't', $3::jsonb, $4, $5)",
            tenant,
            kind,
            json.dumps({"project_code": "nplb", "entity": "documents", "record_id": 1}),
            state,
            finished,
        )


async def test_summary_tra_moi_du_an_tru_all(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        await c.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) VALUES"
            " (portal.current_tenant(), 'slc', 'Sunshine Legend City', 'published'),"
            " (portal.current_tenant(), '__ALL__', 'Toàn workspace', 'published')"
            " ON CONFLICT DO NOTHING"
        )
        await repo.insert_rows(c, [_open("c:a", "c:b"), Row("nplb", "c:x", "c:y", "none")])
        rows = await repo.summary(c)
    got = [(r["project_code"], r["open"], r["checking"], r["failed"], r["checked_at"]) for r in rows]
    assert got == [("nplb", 1, False, False, None), ("slc", 0, False, False, None)]


async def test_summary_va_check_lay_luot_xong_gan_nhat(pool, tenant):
    t1 = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
    await _job(pool, tenant, "success", finished=t1)
    await _job(pool, tenant, "failed", finished=t2)
    async with tenant_conn(pool, tenant) as c:
        assert await repo.check_status(c, "nplb") == (False, True, t2)
        row = (await repo.summary(c))[0]
    assert (row["failed"], row["checked_at"]) == (True, t2)
    await _job(pool, tenant, "queued")
    async with tenant_conn(pool, tenant) as c:
        assert await repo.check_status(c, "nplb") == (True, True, t2)
        row = (await repo.summary(c))[0]
    assert (row["checking"], row["failed"]) == (True, True)


async def test_check_thay_job_nap_dang_chay(pool, tenant):
    await _job(pool, tenant, "queued", kind="kb_index")
    async with tenant_conn(pool, tenant) as c:
        assert await repo.check_status(c, "nplb") == (True, False, None)
        assert (await repo.summary(c))[0]["checking"] is False


async def test_tenant_khac_khong_thay(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        await repo.insert_rows(c, [_open()])
    async with tenant_conn(pool, OTHER) as c:
        assert await repo.list_open(c, "nplb") == []
        assert await repo.judged_pairs(c, [("c:a", "c:b")]) == set()
