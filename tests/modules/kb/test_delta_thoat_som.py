"""Chế độ delta: hash trùng thì KHÔNG gọi embed, nhưng vẫn chạm indexed_at."""

from portal.core.db.session import tenant_conn
from portal.modules.kb import service
from portal.modules.kb.contracts import MODE_DELTA, MODE_FULL
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.state import repo
from tests.modules.kb.fake import FakeIndexClient, FakeObjectStore

from .conftest import TENANT


async def _nap(conn, rag, store, record_id: int, mode: str = MODE_FULL):
    return await service.index_text(
        conn,
        tenant_id=TENANT,
        slug=TENANT,
        vertical=REAL_ESTATE,
        entity="documents",
        doc_type="tai_lieu",
        record_id=record_id,
        rag=rag,
        store=store,
        mode=mode,
    )


async def test_lan_hai_o_che_do_delta_khong_goi_embed(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        assert rag.index_calls == 1

        lan_hai = await _nap(conn, rag, store, rid, mode=MODE_DELTA)
        rows = await repo.read_state(conn, entity="documents", record_id=rid)

    assert rag.index_calls == 1, "hash trùng mà vẫn gọi embed — phép thoát sớm không chạy"
    assert lan_hai is not None and lan_hai.skipped is True
    assert lan_hai.points_upserted == 0

    hang = rows[0]
    assert hang["state"] == "skipped"
    assert hang["points"] == 1, "points phải giữ nguyên — point cũ vẫn còn trên Qdrant"
    assert hang["indexed_at"] is not None


async def test_che_do_full_bo_qua_phep_so(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        await _nap(conn, rag, store, rid, mode=MODE_FULL)
    assert rag.index_calls == 2, "nạp lại toàn bộ phải thật là toàn bộ"


async def test_noi_dung_doi_thi_van_nap_lai_o_che_do_delta(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        await conn.execute(
            "UPDATE tenant_data.documents SET body = 'nội dung đã sửa' "
            "WHERE tenant_id = portal.current_tenant() AND id = $1",
            rid,
        )
        ket_qua = await _nap(conn, rag, store, rid, mode=MODE_DELTA)

    assert rag.index_calls == 2
    assert ket_qua is not None and ket_qua.skipped is False


async def test_dong_so_dang_loi_thi_van_nap_lai_du_hash_trung(api_pool, doc_ids):
    """hash trùng chỉ nói nội dung không đổi — nó KHÔNG nói point đã lên Qdrant."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        await conn.execute(
            "UPDATE tenant_data.kb_index_state SET state = 'error', error = 'embed 500' "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1",
            rid,
        )
        await _nap(conn, rag, store, rid, mode=MODE_DELTA)

    assert rag.index_calls == 2


async def test_ghi_project_code_vao_so(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, doc_ids["nplb"])
        got = await conn.fetchval(
            "SELECT project_code FROM tenant_data.kb_index_state "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1",
            doc_ids["nplb"],
        )
    assert got == "nplb"
