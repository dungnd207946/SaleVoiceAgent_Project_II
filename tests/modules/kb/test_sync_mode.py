"""mode phải đi từ job cha xuống từng job con, và payload phải mang project_code."""

import json

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs
from portal.modules.kb.contracts import MODE_DELTA, MODE_FULL
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.ops import sync
from tests.modules.kb.fake import FakeIndexClient, FakeObjectStore

TENANT = "kb_acme"


@pytest.fixture
def fakes(monkeypatch):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (rag, media, store))
    return rag, media, store


def _payloads(rows) -> list[dict]:
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def _job_index(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = portal.current_tenant() AND kind = 'kb_index' ORDER BY id"
    )
    return _payloads(rows)


async def test_job_con_mang_project_code_va_mode(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test", mode=MODE_DELTA
        )
        ps = await _job_index(conn)

    assert ps, "không xếp job nào"
    assert all(p["project_code"] == "nplb" for p in ps)
    assert all(p["mode"] == MODE_DELTA for p in ps)


async def test_handle_sync_project_truyen_mode_full_xuong(pool, seed_kb, fakes):
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_sync_project(
            conn, {"vertical": "real_estate", "project_code": "nplb", "actor": "test", "mode": MODE_FULL}
        )
        ps = await _job_index(conn)
    assert ps and all(p["mode"] == MODE_FULL for p in ps)


async def test_mac_dinh_cua_job_sync_la_delta(pool, seed_kb, fakes):
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_sync_project(conn, {"vertical": "real_estate", "project_code": "nplb", "actor": "t"})
        ps = await _job_index(conn)
    assert ps and all(p["mode"] == MODE_DELTA for p in ps)


async def test_job_index_le_mac_dinh_full(api_pool, doc_ids, fakes):
    """`POST /kb/{entity}/{id}/reindex` là người dùng chỉ thẳng vào một record — nạp thật."""
    rag, _media, _store = fakes
    async with tenant_conn(api_pool, TENANT) as conn:
        await jobs.handle_index(
            conn,
            {"vertical": "real_estate", "entity": "documents", "record_id": doc_ids["nplb"], "op": "upsert"},
        )
        await jobs.handle_index(
            conn,
            {"vertical": "real_estate", "entity": "documents", "record_id": doc_ids["nplb"], "op": "upsert"},
        )
    assert rag.index_calls == 2


async def test_job_index_mode_delta_bao_khong_doi(api_pool, doc_ids, fakes):
    rag, _media, _store = fakes
    payload = {
        "vertical": "real_estate",
        "entity": "documents",
        "record_id": doc_ids["nplb"],
        "mode": MODE_DELTA,
        "op": "upsert",
    }
    async with tenant_conn(api_pool, TENANT) as conn:
        await jobs.handle_index(conn, payload)
        ket_qua = await jobs.handle_index(conn, payload)

    assert rag.index_calls == 1
    assert "không đổi" in ket_qua.message
