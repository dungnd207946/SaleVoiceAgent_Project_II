"""Cascade phải chạy ĐƯỢC sau khi row nguồn đã bị ON DELETE CASCADE xoá.

Đây là lỗi mà cột `project_code` sửa: worker chạy sau request vài giây, và lúc đó
Postgres không còn con nào để liệt kê nên cách cũ (đọc bảng nguồn) trả rỗng —
point sống mãi, không log nào đỏ.
"""

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs, service
from portal.modules.kb.contracts import IndexResult
from portal.modules.kb.state import repo
from tests.modules.kb.fake import FakeIndexClient, FakeObjectStore

from .conftest import TENANT


async def _ghi_so(conn, *, entity: str, record_id: int, doc_type: str, project_code: str) -> None:
    await repo.save_state(
        conn,
        entity=entity,
        record_id=record_id,
        doc_type=doc_type,
        target="documents" if entity != "media" else "media",
        state="indexed",
        result=IndexResult(points_upserted=2, content_hash="h"),
        project_code=project_code,
    )


async def test_xoa_du_an_roi_van_xoa_du_point(api_pool, doc_ids, pool):
    rag, media = FakeIndexClient(), FakeIndexClient()
    rid = doc_ids["nplb"]

    async with tenant_conn(api_pool, TENANT) as conn:
        await _ghi_so(conn, entity="documents", record_id=rid, doc_type="csbh", project_code="nplb")

    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "DELETE FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = 'nplb'"
        )
        con_lai = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
            rid,
        )
    assert con_lai == 0, "seed sai — FK phải là ON DELETE CASCADE"

    async with tenant_conn(api_pool, TENANT) as conn:
        n = await service.delete_cascade(conn, slug=TENANT, anchor_code="nplb", rag=rag, media=media)

    assert n == 1
    assert rag.deleted == [(TENANT, rid, "csbh")]


async def test_handle_delete_nhanh_anchor_goi_cascade(api_pool, doc_ids, monkeypatch):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (rag, media, store))
    rid = doc_ids["nplb"]

    async with tenant_conn(api_pool, TENANT) as conn:
        await _ghi_so(conn, entity="documents", record_id=rid, doc_type="csbh", project_code="nplb")
        ket_qua = await jobs.handle_delete(conn, {"vertical": "real_estate", "anchor_code": "nplb"})
        rows = await repo.read_state(conn, entity="documents", record_id=rid)

    assert ket_qua.count == 1
    assert rows[0]["state"] == "deleted"


async def test_cascade_khong_cham_du_an_khac(api_pool, doc_ids):
    rag, media = FakeIndexClient(), FakeIndexClient()
    async with tenant_conn(api_pool, TENANT) as conn:
        await _ghi_so(conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh", project_code="nplb")
        await _ghi_so(conn, entity="documents", record_id=doc_ids["__ALL__"], doc_type="khac", project_code="__ALL__")
        await service.delete_cascade(conn, slug=TENANT, anchor_code="nplb", rag=rag, media=media)

    assert [d[1] for d in rag.deleted] == [doc_ids["nplb"]]


async def test_cascade_dung_client_media_cho_entity_media(api_pool, doc_ids):
    """`<slug>_media` là collection khác — gửi lời xoá sang client rag là xoá trượt."""
    rag, media = FakeIndexClient(), FakeIndexClient()
    async with tenant_conn(api_pool, TENANT) as conn:
        await _ghi_so(conn, entity="media", record_id=99, doc_type="", project_code="nplb")
        await service.delete_cascade(conn, slug=TENANT, anchor_code="nplb", rag=rag, media=media)

    assert media.deleted == [(TENANT, 99, "")]
    assert rag.deleted == []


async def test_dong_da_deleted_khong_xoa_lai(api_pool, doc_ids):
    rag, media = FakeIndexClient(), FakeIndexClient()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _ghi_so(conn, entity="documents", record_id=rid, doc_type="csbh", project_code="nplb")
        await repo.mark_deleted(conn, entity="documents", record_id=rid, doc_types=["csbh"])
        n = await service.delete_cascade(conn, slug=TENANT, anchor_code="nplb", rag=rag, media=media)

    assert n == 0
    assert rag.deleted == []
