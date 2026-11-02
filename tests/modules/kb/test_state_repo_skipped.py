"""saved_hash / mark_skipped — nền của phép thoát sớm ở service."""

from portal.core.db.session import tenant_conn
from portal.modules.kb.contracts import IndexResult
from portal.modules.kb.state import repo

from .conftest import TENANT


async def test_saved_hash_tra_none_khi_chua_co_dong(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        assert await repo.saved_hash(conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh") is None


async def test_saved_hash_tra_hash_va_state(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            result=IndexResult(points_upserted=3, content_hash="abc123"),
            project_code="nplb",
        )
        got = await repo.saved_hash(conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh")
    assert got == ("abc123", "indexed")


async def test_mark_skipped_cham_indexed_at_nhung_giu_hash_va_points(api_pool, doc_ids):
    """Chạm indexed_at là điều kiện để badge về xanh; giữ hash/points để lần sau còn so được."""
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            result=IndexResult(points_upserted=3, content_hash="abc123"),
            project_code="nplb",
        )
        truoc = await conn.fetchval(
            "SELECT indexed_at FROM tenant_data.kb_index_state "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1 AND doc_type = 'csbh'",
            doc_ids["nplb"],
        )
        await repo.mark_skipped(conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh")
        rows = await repo.read_state(conn, entity="documents", record_id=doc_ids["nplb"])

    hang = next(r for r in rows if r["doc_type"] == "csbh")
    assert hang["state"] == "skipped"
    assert hang["content_hash"] == "abc123"
    assert hang["points"] == 3
    assert hang["indexed_at"] is not None and hang["indexed_at"] >= truoc


async def test_save_state_ghi_project_code(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            project_code="nplb",
        )
        got = await conn.fetchval(
            "SELECT project_code FROM tenant_data.kb_index_state "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1",
            doc_ids["nplb"],
        )
    assert got == "nplb"


async def test_upsert_lan_hai_khong_xoa_project_code_da_co(api_pool, doc_ids):
    """Caller cũ không truyền project_code — ghi '' lên giá trị đã có là cascade mất dấu."""
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            project_code="nplb",
        )
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
        )
        got = await conn.fetchval(
            "SELECT project_code FROM tenant_data.kb_index_state "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1",
            doc_ids["nplb"],
        )
    assert got == "nplb"
