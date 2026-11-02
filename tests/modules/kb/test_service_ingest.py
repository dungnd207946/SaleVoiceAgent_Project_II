"""Đường ingest thật trên Postgres thật + fake santa-models.

`/index` ở santa-models chưa tồn tại, nhưng cả đường đọc → resolve → presign → ghi
trạng thái vẫn kiểm được.
"""

from portal.core.db.session import tenant_conn
from portal.modules.kb import service
from portal.modules.kb.contracts import TextDirective
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.state import repo
from tests.modules.kb.fake import FakeIndexClient, FakeObjectStore

from .conftest import OTHER_TENANT, TENANT


async def test_index_mot_tai_lieu_ghi_dung_trang_thai(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        result = await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["nplb"],
            rag=rag,
            store=store,
        )
        rows = await repo.read_state(conn, entity="documents", record_id=doc_ids["nplb"])

    assert result is not None and result.points_upserted == 1
    assert len(rag.indexed) == 1
    d = rag.indexed[0]
    assert isinstance(d, TextDirective)
    assert d.anchor_code == "nplb"
    assert d.section == "Noble Palace Long Biên > Chính sách bán hàng Q3"
    assert d.extract_profile is None, "body đã có nội dung thì KHÔNG được gọi trích PDF"
    assert store.presigned == [], "không có file cần trích thì không presign gì"

    assert len(rows) == 1
    assert rows[0]["state"] == "indexed"
    assert rows[0]["target"] == "documents"
    assert rows[0]["indexed_at"] is not None
    assert rows[0]["content_hash"] == result.content_hash


async def test_body_rong_co_file_thi_presign_va_khai_extract(api_pool, doc_ids):
    """Nhánh §4.2b: trích một lần rồi cache vào documents.body, lần sau gửi text."""
    rag = FakeIndexClient(extracted_text="## Nội dung đã trích")
    store = FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["__ALL__"],
            rag=rag,
            store=store,
        )
        body = await conn.fetchval("SELECT body FROM tenant_data.documents WHERE id = $1", doc_ids["__ALL__"])

    d = rag.indexed[0]
    assert d.extract_profile == "ocr_markdown"
    assert d.source_file_url is not None and "X-Amz-Expires=300" in d.source_file_url
    assert store.presigned == ["tenants/kb_acme/docs/brochure.pdf"], "presign phải nằm dưới prefix tenant"
    assert body == "## Nội dung đã trích", "extracted_text phải được cache lại vào Postgres"


async def test_con_published_duoi_anchor_nhap_VAN_index_nhung_status_la_draft(api_pool, doc_ids):
    """LẬT hành vi cũ (cascade cha chặn con). Nay con VẪN được nạp, nhưng trạng thái hiệu
    lực là `draft` vì luật thật là "chính nó published VÀ dự án cha published".

    Đây là ca quan trọng nhất của phép suy trạng thái: point của một tài liệu KHÔNG BIẾT GÌ
    về hàng dự án, nên nếu phép AND không làm ở phía ghi thì agent không có dữ liệu để kiểm.
    """
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        result = await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["draftpj"],
            rag=rag,
            store=store,
        )
    assert result is not None and result.points_upserted > 0
    assert rag.indexed, "con của dự án nháp vẫn phải được nạp"
    chi_thi = rag.indexed[-1]
    assert chi_thi.status == "published", "trạng thái THÔ của chính tài liệu"
    assert chi_thi.anchor_status == "draft", "trạng thái THÔ của dự án cha"


async def test_khong_doc_duoc_record_cua_tenant_khac(api_pool, doc_ids):
    """Cách ly hàng: cùng id, khác tenant → RLS trả 0 hàng, không phải nội dung của B."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, OTHER_TENANT) as conn:
        result = await service.index_text(
            conn,
            tenant_id=OTHER_TENANT,
            slug=OTHER_TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["nplb"],
            rag=rag,
            store=store,
        )
    assert result is None
    assert rag.indexed == []


async def test_index_lai_khong_sinh_dong_trang_thai_thu_hai(api_pool, doc_ids):
    """UNIQUE → upsert. Không có nó thì index-status trả một danh sách dài vô hạn."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        for _ in range(3):
            await service.index_text(
                conn,
                tenant_id=TENANT,
                slug=TENANT,
                vertical=REAL_ESTATE,
                entity="documents",
                doc_type="tai_lieu",
                record_id=doc_ids["nplb"],
                rag=rag,
                store=store,
            )
        rows = await repo.read_state(conn, entity="documents", record_id=doc_ids["nplb"])
    assert len(rows) == 1


async def test_xoa_index_danh_dau_deleted(api_pool, doc_ids):
    """Title mặc định của fixture không khớp tiền tố nào → sổ ghi doc_type='khac',
    và không truyền doc_type nghĩa là delete_index phải tra đúng giá trị đó (§4.4)."""
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["nplb"],
            rag=rag,
            store=store,
        )
        await service.delete_index(
            conn, slug=TENANT, entity="documents", record_id=doc_ids["nplb"], rag=rag, media=media
        )
        rows = await repo.read_state(conn, entity="documents", record_id=doc_ids["nplb"])

    assert rag.deleted == [(TENANT, doc_ids["nplb"], "khac")]
    assert rows[0]["state"] == "deleted" and rows[0]["points"] == 0


async def test_kb_index_state_ghi_doc_type_that_khong_phai_hang_cua_spec(api_pool, doc_ids):
    """Sổ ghi phải nói đúng point nào đang tồn tại — nếu không, "CSBH đã index chưa"
    là câu hỏi trả lời sai mà không ai biết."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET title = 'CSBH — Bảng giá đợt 3' WHERE id = $1",
            doc_ids["nplb"],
        )
        await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["nplb"],
            rag=rag,
            store=store,
        )
        rows = await repo.read_state(conn, entity="documents", record_id=doc_ids["nplb"])

    assert [r["doc_type"] for r in rows] == ["csbh"]
    assert rows[0]["state"] == "indexed"
    d = rag.indexed[0]
    assert isinstance(d, TextDirective)
    assert d.doc_type == "csbh"


async def test_xoa_khong_biet_doc_type_thi_tra_so_de_xoa_dung_point(api_pool, doc_ids):
    """Row đã mất thì không suy được loại từ title — sổ kb_index_state là nguồn cuối.
    Xoá bằng doc_type="" sẽ trượt vì point id là uuid5(doc_type:record_id:idx)."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET title = 'Pháp lý — Sổ đỏ' WHERE id = $1",
            doc_ids["nplb"],
        )
        await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["nplb"],
            rag=rag,
            store=store,
        )
        await service.delete_index(conn, slug=TENANT, entity="documents", record_id=doc_ids["nplb"], rag=rag, media=rag)

    assert rag.deleted == [(TENANT, doc_ids["nplb"], "phap_ly")]


async def test_xoa_mot_loai_khong_duoc_danh_dau_dong_cua_loai_khac(api_pool, doc_ids):
    """Job xoá bị retry sau khi tài liệu đã được index lại dưới loại mới: đánh dấu
    theo record sẽ ghi `deleted` cho dòng loại MỚI, trong khi point của nó đang sống."""
    rag = FakeIndexClient()
    record_id = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        for dt in ("csbh", "phap_ly"):
            await repo.save_state(
                conn, entity="documents", record_id=record_id, doc_type=dt, target="documents", state="indexed"
            )
        await service.delete_index(
            conn, slug=TENANT, entity="documents", record_id=record_id, rag=rag, media=rag, doc_type="csbh"
        )
        rows = await repo.read_state(conn, entity="documents", record_id=record_id)

    trang_thai = {r["doc_type"]: r["state"] for r in rows}
    assert trang_thai["csbh"] == "deleted"
    assert trang_thai["phap_ly"] == "indexed", "point phap_ly còn sống mà sổ đã ghi là đã xoá"


async def test_xoa_khong_biet_loai_van_danh_dau_moi_dong_cua_record(api_pool, doc_ids):
    """Không truyền doc_type = xoá mọi point của record, nên sổ cũng phải sạch hết."""
    rag = FakeIndexClient()
    record_id = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        for dt in ("csbh", "phap_ly"):
            await repo.save_state(
                conn, entity="documents", record_id=record_id, doc_type=dt, target="documents", state="indexed"
            )
        await service.delete_index(conn, slug=TENANT, entity="documents", record_id=record_id, rag=rag, media=rag)
        rows = await repo.read_state(conn, entity="documents", record_id=record_id)

    assert {r["state"] for r in rows} == {"deleted"}


async def test_xoa_khi_so_rong_thi_khong_goi_client(api_pool, doc_ids):
    """Sổ không có dòng nào = record chưa từng được index → không có gì để xoá.

    Nhánh cũ rơi về `doc_type=""`; ở `<slug>_documents` vị từ duy nhất còn lại là
    `record_id`, và ba bảng dùng chung collection đó nên nó xoá luôn point của
    `projects`/`zones` cùng số id. `kb_index_state` đang 0 hàng ở mọi tenant, tức MỌI
    record đều rơi vào nhánh này.
    """
    rag = FakeIndexClient()
    async with tenant_conn(api_pool, TENANT) as conn:
        await service.delete_index(conn, slug=TENANT, entity="documents", record_id=doc_ids["nplb"], rag=rag, media=rag)

    assert rag.deleted == [], "sổ rỗng mà vẫn gọi xoá — nhánh doc_type='' quét cả entity khác"


async def test_xoa_luon_khai_entity_cho_client(api_pool, doc_ids):
    """Vị từ thứ hai của lời gọi xoá. Thiếu nó thì `documents#5` cuốn theo `projects#5`."""
    rag = FakeIndexClient()
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh", target="documents", state="indexed"
        )
        await service.delete_index(conn, slug=TENANT, entity="documents", record_id=doc_ids["nplb"], rag=rag, media=rag)

    assert rag.deleted_entities == ["documents"]


async def test_xoa_co_doc_type_tuong_minh_thi_khong_tra_so(api_pool, doc_ids):
    """Caller biết loại cũ (đường §4.4) thì dùng đúng cái đó — sổ lúc đó đã là loại MỚI."""
    rag = FakeIndexClient()
    async with tenant_conn(api_pool, TENANT) as conn:
        await service.delete_index(
            conn,
            slug=TENANT,
            entity="documents",
            record_id=doc_ids["nplb"],
            rag=rag,
            media=rag,
            doc_type="csbh",
        )

    assert rag.deleted == [(TENANT, doc_ids["nplb"], "csbh")]


async def test_file_url_la_url_ngoai_thi_dung_nguyen_van_khong_presign(api_pool, doc_ids):
    """Ảnh CSBH dán link: presign một URL ngoài ra `tenants/<tenant>/https://…` — một URL
    ký hợp lệ trỏ vào object KHÔNG tồn tại, nên không có lỗi nào và trình bóc nhận 404."""
    rag = FakeIndexClient(extracted_text="## Chữ đọc từ ảnh")
    store = FakeObjectStore()
    url = "https://nbx-sales-dev.noble.vn/img/real/proj/bang-gia__csbh.jpg"
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET file_url = $2, body = '' WHERE id = $1",
            doc_ids["__ALL__"],
            url,
        )
        await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["__ALL__"],
            rag=rag,
            store=store,
        )

    assert rag.indexed[0].source_file_url == url
    assert store.presigned == [], "URL ngoài không presign được — phải đi thẳng"
