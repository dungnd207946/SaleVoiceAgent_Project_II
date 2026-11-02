import json
from contextlib import asynccontextmanager

import pytest

from portal.core import jobs as core_jobs
from portal.core.db.session import tenant_conn
from portal.core.jobs import JobRef, get_handler
from portal.modules.kb import jobs as kb_jobs
from portal.modules.kb.conflicts import jobs as conflict_jobs
from portal.modules.kb.conflicts.enqueue import queue_check
from portal.modules.kb.conflicts.repo import KIND_CONFLICT_CHECK
from portal.modules.kb.contracts import IndexResult
from portal.modules.kb.web import usage


async def _jobs(pool, tenant):
    rows = await pool.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id", tenant, KIND_CONFLICT_CHECK
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


@pytest.fixture
def fake_index(monkeypatch):
    state = {"result": IndexResult(points_upserted=3, content_hash="h")}

    @asynccontextmanager
    async def deps():
        yield object(), object(), object()

    async def index_text(conn, **kw):
        return state["result"]

    monkeypatch.setattr(kb_jobs, "open_dependencies", deps)
    monkeypatch.setattr(kb_jobs.service, "index_text", index_text)
    return state


async def _index(pool, tenant, entity="documents"):
    payload = {"entity": entity, "record_id": 7, "project_code": "nplb", "vertical": "real_estate"}
    async with tenant_conn(pool, tenant) as c:
        return await kb_jobs.handle_index(c, payload)


async def test_nap_co_ghi_point_thi_xep_job_do(pool, seed_conflict_tenant, fake_index):
    await _index(pool, seed_conflict_tenant)
    assert await _jobs(pool, seed_conflict_tenant) == [{"project_code": "nplb", "entity": "documents", "record_id": 7}]


async def test_nap_bao_khong_doi_thi_khong_xep(pool, seed_conflict_tenant, fake_index):
    fake_index["result"] = IndexResult(points_upserted=0, content_hash="h", skipped=True)
    await _index(pool, seed_conflict_tenant)
    assert await _jobs(pool, seed_conflict_tenant) == []


async def test_luu_lien_tiep_chi_mot_job(pool, seed_conflict_tenant):
    async with tenant_conn(pool, seed_conflict_tenant) as c:
        kw = {"tenant_id": seed_conflict_tenant, "actor": "t", "project_code": "nplb"}
        assert await queue_check(c, **kw, entity="documents", record_id=1) is not None
        assert await queue_check(c, **kw, entity="documents", record_id=1) is None
        assert await queue_check(c, **kw, entity="documents", record_id=2) is not None
        assert await queue_check(c, **kw) is not None
        assert await queue_check(c, **kw, entity="documents", record_id=3) is None
        assert await queue_check(c, **kw) is None


async def test_handler_ghi_chi_phi_dung_nhan(api_pool, pool, seed_conflict_tenant, monkeypatch):
    class Llm:
        async def ask(self, profile, user_text):
            usage.meter().llm("dashscope", "qwen3.7-flash", 1000, 100)
            return {"conflicts": []}

    @asynccontextmanager
    async def deps():
        yield object(), Llm()

    async def check_project(conn, *, store, llm, collection, project_code):
        await llm.ask("conflict_check", "x")
        from portal.modules.kb.conflicts.service import CheckResult

        return CheckResult(calls=1)

    monkeypatch.setattr(conflict_jobs, "open_deps", deps)
    monkeypatch.setattr(conflict_jobs.service, "check_project", check_project)
    token = core_jobs._CURRENT_JOB.set(JobRef(id=991, attempt=0, pool=api_pool))
    try:
        async with tenant_conn(api_pool, seed_conflict_tenant) as c:
            res = await get_handler(KIND_CONFLICT_CHECK)(c, {"project_code": "nplb"})
    finally:
        core_jobs._CURRENT_JOB.reset(token)
    assert "1 lượt LLM" in res.message
    rows = await pool.fetch(
        "SELECT channel, purpose, input_tokens FROM billing.usage_events WHERE session_id = 'kbconflict:991'"
    )
    await pool.execute("DELETE FROM billing.usage_events WHERE session_id = 'kbconflict:991'")
    assert [(r["channel"], r["purpose"], r["input_tokens"]) for r in rows] == [("kb_conflict", "conflict_check", 1000)]
