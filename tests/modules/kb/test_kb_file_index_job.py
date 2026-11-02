"""service.index_kb_file + handler kb_file_index — pipeline kho «Tài liệu tra cứu».

Extraction chạy THẬT trên docx dựng trong test (python-docx là dependency sẵn);
embed/Qdrant là FakeIndexClient; kho tệp là FakeObjectStore.
"""

import io

import docx
import pytest

from portal.core.db.session import tenant_conn
from portal.core.jobs import retries_of
from portal.modules.kb import files_repo, jobs, service
from portal.modules.kb import settings as kb_settings
from portal.modules.kb.clients.extract import ExtractResult
from portal.modules.kb.contracts import DOC_TYPE_KB_FILE, KIND_KB_FILE_INDEX, MD_EMPTY_MESSAGE
from tests.modules.kb.fake import FakeIndexClient, FakeObjectStore

from .conftest import TENANT


def _docx_bytes(doan: str) -> bytes:
    d = docx.Document()
    d.add_heading("Chính sách chung", level=1)
    d.add_paragraph(doan)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


async def _hang_moi(pool, ten: str, data: bytes, store: FakeObjectStore) -> files_repo.HangTaiLieu:
    key = f"tenants/{TENANT}/kb/sha-gia/{ten}"
    store.stored[key] = data
    async with tenant_conn(pool, TENANT) as conn:
        return await files_repo.them(
            conn, ten_file=ten, s3_key=key, kich_thuoc=len(data), loai=ten.rsplit(".", 1)[-1], uploaded_by=None
        )


async def test_nap_docx_thanh_san_sang(api_pool, seed_kb):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    t = await _hang_moi(api_pool, "chinh-sach.docx", _docx_bytes("Ưu đãi thanh toán sớm 3%."), store)

    async with tenant_conn(api_pool, TENANT) as conn:
        msg = await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=t.id, rag=rag, media=media, store=store
        )

    assert "+1 point" in msg
    # Collection được dựng trước (idempotent) — upload có thể là hành động KB đầu tiên.
    assert rag.created_collections == [TENANT] and media.created_collections == [TENANT]

    (d,) = rag.indexed
    assert (d.doc_type, d.anchor_code, d.status, d.anchor_status) == (
        DOC_TYPE_KB_FILE,
        kb_settings.SYSTEM_ANCHOR,
        "published",
        "published",
    )
    assert d.anchor_name == "chinh-sach.docx" and d.file_name == "chinh-sach.docx"
    assert "Ưu đãi thanh toán" in d.text

    async with tenant_conn(api_pool, TENANT) as conn:
        sau = await files_repo.doc(conn, t.id)
    assert sau is not None and (sau.state, sau.chunk_count) == ("san_sang", 1)


async def test_khong_co_chu_thanh_loi_co_chi_duong(api_pool, seed_kb, monkeypatch):
    """PDF scan → ExtractResult(text='') → hàng `loi`, message nói LÝ DO VÀ CÁCH SỬA."""

    class _KhongChu:
        def __init__(self, *, vlm=None) -> None: ...

        async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
            return ExtractResult(text="")

    monkeypatch.setattr(service, "TextExtractor", _KhongChu)
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    t = await _hang_moi(api_pool, "scan.pdf", b"%PDF-fake-scan", store)

    async with tenant_conn(api_pool, TENANT) as conn:
        await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=t.id, rag=rag, media=media, store=store
        )
        sau = await files_repo.doc(conn, t.id)

    assert sau is not None and sau.state == "loi"
    assert "duyệt OCR" in sau.loi_message  # cách sửa phải nằm trong message
    assert rag.indexed == []  # không nhúng gì


async def test_md_rong_thanh_loi_dung_cau_markdown(api_pool, seed_kb, monkeypatch):
    """.md rỗng phải dùng MD_EMPTY_MESSAGE, KHÔNG phải câu PDF-scan «lớp chữ»/«duyệt
    OCR» — người tải lên một tệp .md không hiểu khái niệm đó (finding 2)."""

    class _KhongChu:
        def __init__(self, *, vlm=None) -> None: ...

        async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
            return ExtractResult(text="")

    monkeypatch.setattr(service, "TextExtractor", _KhongChu)
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    t = await _hang_moi(api_pool, "rong.md", b"\n", store)

    async with tenant_conn(api_pool, TENANT) as conn:
        await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=t.id, rag=rag, media=media, store=store
        )
        sau = await files_repo.doc(conn, t.id)

    assert sau is not None and sau.state == "loi"
    assert sau.loi_message == MD_EMPTY_MESSAGE
    assert "duyệt OCR" not in sau.loi_message
    assert rag.indexed == []


async def test_anh_loi_van_la_thanh_cong(api_pool, seed_kb, monkeypatch, bo_gia):
    """Ảnh lỗi/timeout là CẢNH BÁO, không phải thất bại — tài liệu vẫn `san_sang` và
    handler phải đếm nó là THÀNH CÔNG (count=1), không lẫn với «bỏ qua»/«lỗi» thật
    (finding 1: message cũ chứa 'lỗi' làm handle_kb_file_index phân loại count=0)."""

    async def _mirror_voi_canh_bao(text, *, tenant_id, store):
        return text, ["ảnh timeout: https://khach.example/1.png", "ảnh timeout: https://khach.example/2.png"]

    monkeypatch.setattr(service.external_images, "mirror_images", _mirror_voi_canh_bao)
    rag, _media, store = bo_gia
    t = await _hang_moi(api_pool, "co-anh-loi.docx", _docx_bytes("Văn bản có ảnh ngoài."), store)

    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": t.id})
        sau = await files_repo.doc(conn, t.id)

    assert ra.count == 1, f"nạp thành công (có cảnh báo ảnh) bị đếm là thất bại: {ra.message!r}"
    assert sau is not None and sau.state == "san_sang"
    assert len(rag.indexed) == 1


async def test_hang_bi_xoa_giua_luc_nap_thi_go_point(api_pool, seed_kb):
    """Race DELETE-trong-lúc-nạp: hàng biến mất giữa rag.index và danh_dau_san_sang
    ⇒ service phải GỠ point vừa ghi (không thì point published mồ côi vĩnh viễn —
    reconcile chưa có thân). Mô phỏng bằng fake rag mà index() tự xoá hàng."""
    store = FakeObjectStore()
    t = await _hang_moi(api_pool, "race.docx", _docx_bytes("Nội dung sẽ bị xoá giữa chừng."), store)

    class _RagXoaGiuaChung(FakeIndexClient):
        def __init__(self, conn):
            super().__init__()
            self._conn = conn

        async def index(self, directive):
            ra = await super().index(directive)
            await files_repo.xoa(self._conn, t.id)  # hàng biến mất TRƯỚC danh_dau_san_sang
            return ra

    async with tenant_conn(api_pool, TENANT) as conn:
        rag = _RagXoaGiuaChung(conn)
        msg = await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=t.id, rag=rag, media=FakeIndexClient(), store=store
        )
        assert "bỏ qua" in msg
        assert (TENANT, t.id, "kb_file") in rag.deleted
        assert await files_repo.doc(conn, t.id) is None


async def test_hang_da_bi_xoa_thi_bo_qua_em(api_pool, seed_kb):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        msg = await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=987_654, rag=rag, media=media, store=store
        )
    assert "bỏ qua" in msg and rag.indexed == []


class _RagNo(FakeIndexClient):
    async def index(self, directive):
        raise RuntimeError("embed sập giả lập")


@pytest.fixture
def bo_gia(monkeypatch):
    """Handler lấy client qua jobs.dependencies() — patch đúng tên đó; open_dependencies
    bọc quanh và chỉ gọi aclose nếu có (fake không có, getattr trả None)."""
    bo = (FakeIndexClient(), FakeIndexClient(), FakeObjectStore())
    monkeypatch.setattr(jobs, "dependencies", lambda: bo)
    return bo


async def test_handler_duong_thuong(api_pool, seed_kb, bo_gia):
    rag, _media, store = bo_gia
    t = await _hang_moi(api_pool, "qua-job.docx", _docx_bytes("Nội dung đi qua handler."), store)

    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": t.id})
        sau = await files_repo.doc(conn, t.id)

    assert ra.count == 1 and len(rag.indexed) == 1
    assert sau is not None and sau.state == "san_sang"


async def test_handler_loi_ha_tang_khong_treo_hang(api_pool, seed_kb, monkeypatch):
    """Chế độ hỏng tệ nhất của bản M6 gốc là hàng treo `dang_xu_ly` vĩnh viễn (spinner
    quay mãi). Handler phải nuốt lỗi hạ tầng, đánh dấu `loi`, và KHÔNG ném — ném là
    rollback luôn cả cú UPDATE vừa ghi."""
    store = FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (_RagNo(), FakeIndexClient(), store))
    t = await _hang_moi(api_pool, "ha-tang-hong.docx", _docx_bytes("Sẽ không lên được Qdrant."), store)

    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": t.id})
        sau = await files_repo.doc(conn, t.id)

    assert ra.count == 0 and "RuntimeError" in ra.message
    assert sau is not None and sau.state == "loi" and sau.loi_message != ""


async def test_handler_postgres_error_giua_chung_van_ghi_duoc_loi(api_pool, seed_kb, bo_gia, monkeypatch):
    """Chứng minh SAVEPOINT: một PostgresError THẬT bên trong phần nạp đầu độc giao dịch
    trong savepoint; rollback về savepoint xong, nhánh except vẫn ghi được `loi` trên
    giao dịch NGOÀI còn lành. Bỏ `conn.transaction()` khỏi handler là bài này đỏ với
    InFailedSQLTransactionError — khác bài RuntimeError (nổ trước khi chạm Postgres)."""
    _rag, _media, store = bo_gia
    t = await _hang_moi(api_pool, "poison.docx", _docx_bytes("Nội dung sẽ chết ở bước đánh dấu."), store)

    async def _no_postgres(conn, *, record_id, chunk_count):
        await conn.execute("SELECT ham_khong_ton_tai_kb_test()")  # UndefinedFunctionError — PostgresError thật

    monkeypatch.setattr(files_repo, "danh_dau_san_sang", _no_postgres)

    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": t.id})
        sau = await files_repo.doc(conn, t.id)

    assert ra.count == 0 and "Error" in ra.message
    assert sau is not None and sau.state == "loi" and sau.loi_message != ""


async def test_handler_hang_bien_mat_bo_qua(api_pool, seed_kb, bo_gia):
    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": 111_222})
    assert ra.count == 0 and "bỏ qua" in ra.message


def test_kind_dang_ky_khong_retry():
    """retries=0 là CHỦ Ý: handler không bao giờ ném nên retry ở tầng job là vô nghĩa;
    retry transient đã nằm trong EmbedClient."""
    assert retries_of(KIND_KB_FILE_INDEX) == 0
