"""Chặng bóc chữ từ tệp: luật chỉ-ghi-khi-rỗng, và van duyệt cho chữ do OCR đọc.

Luật chỉ-ghi-khi-rỗng là thứ quan trọng nhất ở đây: một job retry sau khi biên tập viên đã
sửa nội dung sẽ im lặng xoá công sức của họ — không lỗi, không log, và họ chỉ biết khi tình
cờ đọc lại.

NHÁNH ẢNH/VIDEO ĐÃ BỎ khỏi chặng này (2026-08-14): model chỉ sinh mô tả một lần, lúc tải tệp
lên, qua đường mô tả nháp (`test_caption_preview.py`). Phần sinh ảnh thu nhỏ tách sang
`test_thumb_job.py`.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs
from portal.modules.kb.clients.extract import ExtractResult
from portal.modules.kb.state import repo
from tests.modules.kb.fake import FakeObjectStore

TENANT = "kb_acme"


class _FakeVlm:
    def __init__(self) -> None:
        self.goi: list[tuple[str, str]] = []
        self.goi_byte: list[tuple[int, str, str]] = []

    async def caption(self, image_url: str, *, profile: str) -> str:
        self.goi.append((image_url, profile))
        return "caption do VLM giả sinh"

    async def caption_bytes(self, data: bytes, *, mime: str, profile: str) -> str:
        self.goi_byte.append((len(data), mime, profile))
        return "caption do VLM giả sinh"


def _anh_gia(w: int = 900, h: int = 600) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (w, h), "green").save(buf, format="JPEG")
    return buf.getvalue()


async def _tai_gia(url: str) -> bytes:
    """Chặng thumb tải ảnh thật. Không tiêm hàm này thì MỌI test enrich ảnh đi ra DNS."""
    return _anh_gia()


class _FakeVideoClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key

    async def describe(self, media_url: str, *, profile: str = "video_describe") -> str:
        return f"mô tả video giả cho {media_url}"


class _FakeTextExtractor:
    def __init__(self, *, vlm=None) -> None:
        self.vlm = vlm

    async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
        return ExtractResult(text=f"nội dung bóc từ {len(data)} byte")


@pytest.fixture
async def media_id(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        return await conn.fetchval(
            """INSERT INTO tenant_data.media
                      (tenant_id, project_code, content_type, category, media_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'image', 'tong_quan',
                       'https://cdn.test/a.jpg', 'published')
               RETURNING id"""
        )


async def test_ghi_caption_khi_o_dang_rong(pool, media_id):
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="do máy sinh")
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "do máy sinh"


async def test_khong_de_len_caption_user_da_sua(pool, media_id):
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="bản máy")
        await conn.execute(
            "UPDATE tenant_data.media SET caption = $2 WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
            "bản người sửa",
        )
        await repo.cache_caption(conn, record_id=media_id, caption="bản máy lần hai")
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "bản người sửa", "job retry đã xoá công sức của biên tập viên"


async def test_force_moi_de_duoc(pool, media_id):
    """Nút "Tạo lại mô tả" — người dùng chủ động, có hộp xác nhận ở giao diện."""
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="bản người sửa")
        await repo.cache_caption(conn, record_id=media_id, caption="bản tạo lại", force=True)
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "bản tạo lại"


# ─── Cùng ba luật, cho `documents.body` ─────────────────────────────────────
# Bộ ba trên chỉ đo `media.caption`. Mutation-test cho thấy luật của `body` không
# được đo gì: đổi `($3 OR body = '')` thành `($3 OR body IS NOT NULL)` — tức xoá
# hẳn luật "user thắng" — mà toàn bộ test vẫn xanh. Đường bóc chữ Docling ghi vào
# đúng cột người dùng đang gõ, nên nó cần cùng mức canh.


async def test_ghi_body_khi_o_dang_rong(pool, doc_ids):
    """`__ALL__` seed sẵn `body=''` — đúng ô rỗng mà Docling được phép ghi vào."""
    record_id = doc_ids["__ALL__"]
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_extracted_text(conn, record_id=record_id, text="chữ Docling bóc ra")
        ra = await conn.fetchval(
            "SELECT body FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert ra == "chữ Docling bóc ra"


async def test_khong_de_len_body_user_da_sua(pool, doc_ids):
    """Job retry sau khi biên tập viên đã gõ nội dung sẽ im lặng xoá công sức của họ."""
    record_id = doc_ids["__ALL__"]
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_extracted_text(conn, record_id=record_id, text="bản máy")
        await conn.execute(
            "UPDATE tenant_data.documents SET body = $2 WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
            "bản người sửa",
        )
        await repo.cache_extracted_text(conn, record_id=record_id, text="bản máy lần hai")
        ra = await conn.fetchval(
            "SELECT body FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert ra == "bản người sửa", "job retry đã xoá công sức của biên tập viên"


async def test_force_moi_de_duoc_body(pool, doc_ids):
    """Nút "Bóc lại nội dung" — người dùng chủ động, có hộp xác nhận ở giao diện."""
    record_id = doc_ids["__ALL__"]
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_extracted_text(conn, record_id=record_id, text="bản người sửa")
        await repo.cache_extracted_text(conn, record_id=record_id, text="bản bóc lại", force=True)
        ra = await conn.fetchval(
            "SELECT body FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert ra == "bản bóc lại"


async def test_khong_dung_toi_media_cua_tenant_khac(pool, media_id):
    """RLS đã dỡ ở 0909 — vị từ tenant nay là quy ước của code, phải có test canh."""
    async with tenant_conn(pool, "kb_other") as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="xuyên tenant")
    async with tenant_conn(pool, TENANT) as conn:
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "", "câu UPDATE thiếu vị từ tenant_id"


async def test_enrich_KHONG_con_lam_gi_cho_anh(pool, media_id):
    """Nhánh ảnh và nhánh video của chặng này ĐÃ BỎ (2026-08-14, chốt 2).

    Mô tả do model sinh chạy đúng MỘT lần, lúc tải tệp lên, qua đường mô tả nháp — nó điền
    vào ô mô tả TRONG FORM và người dùng đọc/sửa rồi mới bấm Thêm, nên cú bấm đó là cú duyệt.
    Sau đó không đường nào gọi model cho ảnh đó nữa.
    """
    async with tenant_conn(pool, TENANT) as conn:
        ra = await jobs.handle_enrich(conn, {"entity": "media", "record_id": media_id})
    assert ra.count == 0
    assert "chỉ áp cho tài liệu" in ra.message


async def test_enrich_media_khong_con_tra_count_0(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        result = await jobs.handle_enrich(conn, {"entity": "media", "record_id": 999_999})
    assert result.count == 0


async def test_enrich_document_khong_co_file_url_tra_count_0(pool, doc_ids):
    async with tenant_conn(pool, TENANT) as conn:
        result = await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_ids["nplb"]})
    assert result.count == 0


async def test_enrich_document_boc_chu_tu_store_va_ghi_body(pool, doc_ids, monkeypatch):
    """`__ALL__` seed sẵn `body=''` + `file_url='docs/brochure.pdf'` — đúng nhánh cần trích."""
    store = FakeObjectStore()
    monkeypatch.setattr(jobs, "object_store", lambda: store)
    monkeypatch.setattr(jobs, "_vlm", lambda: None)
    monkeypatch.setattr("portal.modules.kb.clients.extract.TextExtractor", _FakeTextExtractor)
    record_id = doc_ids["__ALL__"]
    async with tenant_conn(pool, TENANT) as conn:
        khoa = store.key(tenant_id=TENANT, path="docs/brochure.pdf")
        store.stored[khoa] = b"noi dung pdf gia"
        result = await jobs.handle_enrich(conn, {"entity": "documents", "record_id": record_id})
        ra = await conn.fetchval(
            "SELECT body FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert result.count == 1
    assert ra == "nội dung bóc từ 16 byte"


async def test_enrich_document_tai_tep_qua_http_khi_file_url_la_url_ngoai(pool, doc_ids, monkeypatch):
    """Ảnh CSBH là link dán, không phải tệp tải lên — `0927` di trú giữ nguyên URL đó vào
    `file_url`. Ghép nó thành khoá kho ra `tenants/<tenant>/https://…` và S3 trả NoSuchKey,
    nên OCR không bao giờ chạy (đo được trên dev 2026-08-17)."""
    store = FakeObjectStore()
    monkeypatch.setattr(jobs, "object_store", lambda: store)
    monkeypatch.setattr(jobs, "_vlm", lambda: None)
    monkeypatch.setattr("portal.modules.kb.clients.extract.TextExtractor", _FakeTextExtractor)
    tai_ve: list[str] = []

    async def _tai(url: str) -> bytes:
        tai_ve.append(url)
        return b"byte anh csbh tai qua http"

    monkeypatch.setattr(jobs, "_tai_anh", _tai)
    record_id = doc_ids["__ALL__"]
    url = "https://nbx-sales-dev.noble.vn/img/real/proj/bang-gia__csbh.jpg"
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET file_url = $2, body = '' "
            " WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
            url,
        )
        result = await jobs.handle_enrich(conn, {"entity": "documents", "record_id": record_id})
        ra = await conn.fetchval(
            "SELECT body FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert tai_ve == [url], "phải tải qua HTTP, không hỏi object store"
    assert result.count == 1
    assert ra == "nội dung bóc từ 26 byte"
