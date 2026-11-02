"""Việc sinh ảnh thu nhỏ (tách khỏi chặng mô tả), van duyệt OCR, và phép gộp việc.

Ba thứ này là phần "tự động" của tab kiến thức. Cái dễ sai nhất KHÔNG phải phần sinh thumb mà
là hai bất biến quanh nó:

1. Việc thumb **tự nối chuỗi tới việc nạp** khi xong, kể cả khi thumb hỏng. Đặt song song từ
   route rồi trông vào thứ tự id là sai: hàng đợi cho phép nhiều worker, nên việc nạp có thể
   chạy TRƯỚC và point mang khoá thumb rỗng — mà không có gì kích hoạt nạp lại.

   ⚠ Với `media` chuỗi có BA mắt từ 2026-08-18: thumb → `kb_caption` → `kb_index`. Chặng mô tả
   chen vào giữa vì `content_hash` của point media là `sha256(media_url␟caption)` — nạp trước
   rồi mô tả sau là hai lượt embed cho cùng một ảnh. Điều phải canh vẫn y nguyên: **chuỗi
   không được đứt ở bất kỳ mắt nào**, kể cả khi mắt đó hỏng.
2. Việc thumb **không được chạm dấu tay nội dung** của hàng. Có hai hàm ghi thumb và hàm thứ
   hai gán `content_hash` vô điều kiện; gọi nó từ đây sẽ xoá trắng dấu tay, làm mọi phép so
   lệch sau đó coi point của ảnh là đã trôi.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs
from portal.modules.kb.clients.extract import ExtractResult
from portal.modules.kb.state import repo

TENANT = "kb_acme"


def _anh_gia(w: int = 900, h: int = 600) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (w, h), "green").save(buf, format="JPEG")
    return buf.getvalue()


async def _tai_gia(url: str) -> bytes:
    return _anh_gia()


class _KhoGia:
    """Kho tệp trong bộ nhớ. Chặng bóc chữ ĐỌC tệp thật trước khi gọi trình bóc, nên tiêm
    trình bóc một mình là chưa đủ — nó vẫn đi ra S3 và nổ NoSuchKey."""

    def __init__(self) -> None:
        self.da_ghi: dict[str, bytes] = {}

    def key(self, *, tenant_id: str, path: str) -> str:
        return f"tenants/{tenant_id}/{path}"

    async def doc(self, *, key: str) -> bytes:
        return b"noi dung tep gia"

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.da_ghi[key] = data
        return f"https://kho/{key}"


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


async def _viec_dang_cho(conn, kind: str, record_id: int) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM control.jobs WHERE tenant_id = portal.current_tenant() "
        "AND kind = $1 AND state = 'queued' AND (payload->>'record_id')::bigint = $2",
        kind,
        record_id,
    )


# ── việc thumb ───────────────────────────────────────────────────────────────


async def test_thumb_ghi_ca_hai_cot_va_NOI_CHUOI_sang_viec_nap(pool, media_id, monkeypatch, kho_tep):
    monkeypatch.setattr(jobs, "_tai_anh", _tai_gia)
    # `public_url_of` trả RỖNG khi chưa cấu hình miền công khai — cố ý, và đúng ở môi trường
    # test. Tiêm hàm đó (không tiêm setting: `get_settings()` được cache và model có thể chặn
    # gán) để test đo được rằng cột thứ hai ĐƯỢC ghi, chứ không đo cách suy URL — việc đó là
    # của test riêng cho `public_url_of`.
    import portal.core.public_url as pu

    monkeypatch.setattr(pu, "public_url_of", lambda k: f"https://portal.test/{k}" if k else "")
    async with tenant_conn(pool, TENANT) as conn:
        ra = await jobs.handle_thumb(conn, {"entity": "media", "record_id": media_id, "project_code": "nplb"})
        hang = await conn.fetchrow("SELECT thumb_url, public_thumb_url FROM tenant_data.media WHERE id = $1", media_id)
        cho = await _viec_dang_cho(conn, "kb_caption", media_id)

    assert ra.count == 1 and "ảnh thu nhỏ" in ra.message
    assert hang["thumb_url"], "chưa ghi khoá ảnh thu nhỏ"
    assert hang["public_thumb_url"], "chưa ghi URL công khai"
    assert not hang["thumb_url"].startswith("http"), "phải lưu KHOÁ, không lưu URL"
    assert cho == 1, "việc thumb phải TỰ nối mắt kế tiếp — không nối chuỗi thì point mang thumb rỗng"


async def test_thumb_hong_VAN_noi_chuoi_sang_viec_nap(pool, media_id, monkeypatch):
    """Ảnh không có bản nhỏ vẫn phải tới được agent; giao diện đã có đường rơi về ảnh gốc."""

    async def _no(url: str) -> bytes:
        raise RuntimeError("CDN 404")

    monkeypatch.setattr(jobs, "_tai_anh", _no)
    async with tenant_conn(pool, TENANT) as conn:
        ra = await jobs.handle_thumb(conn, {"entity": "media", "record_id": media_id, "project_code": "nplb"})
        cho = await _viec_dang_cho(conn, "kb_caption", media_id)
    assert ra.count == 1, "thumb hỏng không được làm đổ việc"
    assert cho == 1
    # Và phải NÓI THẬT. Bản cũ trả «đã sinh ảnh thu nhỏ» vô điều kiện, nên 47 ảnh mất
    # thumb mà job vẫn xanh với đúng dòng đó — caption của chúng chết theo, im lặng.
    assert "KHÔNG sinh được" in ra.message and "CDN 404" in ra.message


async def test_thumb_KHONG_cham_dau_tay_noi_dung(pool, media_id, monkeypatch, kho_tep):
    """Canh cái bẫy hai-hàm-ghi-thumb. Hỏng thì IM LẶNG: dấu tay bị xoá trắng và mọi phép so
    lệch sau đó coi point của ảnh là đã trôi."""
    monkeypatch.setattr(jobs, "_tai_anh", _tai_gia)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.media SET content_hash = 'dau-tay-cu' WHERE id = $1", media_id)
        await jobs.handle_thumb(conn, {"entity": "media", "record_id": media_id, "project_code": "nplb"})
        con_lai = await conn.fetchval("SELECT content_hash FROM tenant_data.media WHERE id = $1", media_id)
    assert con_lai == "dau-tay-cu"


async def test_da_co_thumb_thi_bo_qua_tru_khi_ghi_de(pool, media_id, monkeypatch, kho_tep):
    monkeypatch.setattr(jobs, "_tai_anh", _tai_gia)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.media SET thumb_url = 'co/roi.webp' WHERE id = $1", media_id)
        ra = await jobs.handle_thumb(conn, {"entity": "media", "record_id": media_id, "project_code": "nplb"})
        van_the = await conn.fetchval("SELECT thumb_url FROM tenant_data.media WHERE id = $1", media_id)
    assert "đã có" in ra.message
    assert van_the == "co/roi.webp"

    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_thumb(
            conn, {"entity": "media", "record_id": media_id, "project_code": "nplb", "ghi_de": True}
        )
        moi = await conn.fetchval("SELECT thumb_url FROM tenant_data.media WHERE id = $1", media_id)
    assert moi != "co/roi.webp", "ghi_de phải sinh lại — ảnh đã đổi thì bản nhỏ cũ là sai ảnh"


async def test_thumb_cho_hang_khong_con_van_khong_no(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        ra = await jobs.handle_thumb(conn, {"entity": "media", "record_id": 10**9, "project_code": "nplb"})
    assert ra.count == 1 and "không có hàng" in ra.message


# ── van duyệt OCR ────────────────────────────────────────────────────────────


class _BocQuaOCR:
    def __init__(self, *, vlm=None) -> None:
        pass

    async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
        return ExtractResult(text="chữ do model đọc từ ảnh", da_ocr=True)


class _BocQuaThuVien:
    def __init__(self, *, vlm=None) -> None:
        pass

    async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
        return ExtractResult(text="chữ do pypdf bóc", da_ocr=False)


@pytest.fixture
async def doc_co_tep(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        return await conn.fetchval(
            """INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, file_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'CSBH — Bảng giá', '', 'docs/a.pdf', 'published')
               RETURNING id"""
        )


def _tiem_boc(monkeypatch, lop):
    import portal.modules.kb.clients.extract as ex

    monkeypatch.setattr(ex, "TextExtractor", lop)
    monkeypatch.setattr(jobs, "object_store", _KhoGia)


async def test_chu_do_OCR_doc_thi_bat_co_cho_duyet_va_KHONG_dat_viec_nap(pool, doc_co_tep, monkeypatch, kho_tep):
    """Model đọc ảnh thì có thể sai, và tài liệu là thứ khách được dẫn SỐ LIỆU từ đó."""
    _tiem_boc(monkeypatch, _BocQuaOCR)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.documents SET file_url = $2 WHERE id = $1", doc_co_tep, "docs/a.pdf")
        ra = await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_co_tep})
        co = await conn.fetchval("SELECT body_cho_duyet FROM tenant_data.documents WHERE id = $1", doc_co_tep)
        cho = await _viec_dang_cho(conn, "kb_index", doc_co_tep)
    assert "chờ duyệt" in ra.message
    assert co is True
    assert cho == 0, "chữ chờ duyệt KHÔNG được nạp"


async def test_chu_do_thu_vien_boc_thi_nap_NGAY(pool, doc_co_tep, monkeypatch, kho_tep):
    """pypdf/docx/xlsx bóc ra là chính xác — bắt duyệt ở đây là bắt bấm cho một việc máy làm
    đúng. Nguyên tắc: model sinh ⇒ người xem; thư viện bóc ⇒ tự động."""
    _tiem_boc(monkeypatch, _BocQuaThuVien)
    async with tenant_conn(pool, TENANT) as conn:
        ra = await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_co_tep, "project_code": "nplb"})
        co = await conn.fetchval("SELECT body_cho_duyet FROM tenant_data.documents WHERE id = $1", doc_co_tep)
        cho = await _viec_dang_cho(conn, "kb_index", doc_co_tep)
    assert "chờ duyệt" not in ra.message
    assert co is False
    assert cho == 1


async def test_nguoi_dung_da_go_noi_dung_thi_KHONG_bat_co(pool, doc_co_tep, monkeypatch, kho_tep):
    """Luật "user thắng" nằm trong chính câu lệnh ghi. Không ghi được nghĩa là không có gì để
    duyệt — bật cờ ở đây là chặn nội dung của CHÍNH người dùng."""
    _tiem_boc(monkeypatch, _BocQuaOCR)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.documents SET body = 'người dùng tự gõ' WHERE id = $1", doc_co_tep)
        await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_co_tep, "project_code": "nplb"})
        hang = await conn.fetchrow("SELECT body, body_cho_duyet FROM tenant_data.documents WHERE id = $1", doc_co_tep)
    assert hang["body"] == "người dùng tự gõ"
    assert hang["body_cho_duyet"] is False


async def test_dat_co_roi_tat_co(pool, doc_co_tep):
    async with tenant_conn(pool, TENANT) as conn:
        await repo.dat_cho_duyet(conn, record_id=doc_co_tep, cho_duyet=True)
        assert await conn.fetchval("SELECT body_cho_duyet FROM tenant_data.documents WHERE id = $1", doc_co_tep)
        await repo.dat_cho_duyet(conn, record_id=doc_co_tep, cho_duyet=False)
        assert not await conn.fetchval("SELECT body_cho_duyet FROM tenant_data.documents WHERE id = $1", doc_co_tep)


# ── phép gộp ─────────────────────────────────────────────────────────────────


async def test_gop_viec_dang_CHO_nhung_khong_gop_viec_dang_CHAY(pool, media_id):
    """Việc đã `running` thì nội dung nó đọc là bản CŨ, nên lần Lưu này phải có việc riêng."""
    from portal.modules.kb.ops import enqueue as dat

    async with tenant_conn(pool, TENANT) as conn:
        mot = await dat.dat_viec_nap(
            conn, tenant_id=TENANT, actor="t", entity="media", record_id=media_id, project_code="nplb"
        )
        hai = await dat.dat_viec_nap(
            conn, tenant_id=TENANT, actor="t", entity="media", record_id=media_id, project_code="nplb"
        )
        assert mot is not None and hai is None, "cú Lưu thứ hai phải gộp vào việc đang chờ"

        await conn.execute("UPDATE control.jobs SET state = 'running' WHERE id = $1", mot)
        ba = await dat.dat_viec_nap(
            conn, tenant_id=TENANT, actor="t", entity="media", record_id=media_id, project_code="nplb"
        )
    assert ba is not None, "việc đang chạy đọc bản cũ — lần Lưu này phải có việc riêng"


async def test_gop_khong_lan_sang_record_khac(pool, media_id, seed_kb):
    from portal.modules.kb.ops import enqueue as dat

    async with tenant_conn(pool, TENANT) as conn:
        khac = await conn.fetchval(
            """INSERT INTO tenant_data.media (tenant_id, project_code, content_type, category, media_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'image', 'tong_quan', 'https://cdn.test/b.jpg', 'published')
               RETURNING id"""
        )
        await dat.dat_viec_nap(
            conn, tenant_id=TENANT, actor="t", entity="media", record_id=media_id, project_code="nplb"
        )
        cua_khac = await dat.dat_viec_nap(
            conn, tenant_id=TENANT, actor="t", entity="media", record_id=khac, project_code="nplb"
        )
    assert cua_khac is not None


async def test_thumb_tai_lieu_tai_qua_http_khi_file_url_la_url_ngoai(pool, doc_ids, monkeypatch):
    """Cùng ca với chặng bóc chữ: tệp dán link không nằm trong kho ta."""

    class _KhoChiNhanKhoa:
        def __init__(self) -> None:
            self.da_ghi: dict[str, bytes] = {}

        def key(self, *, tenant_id: str, path: str) -> str:
            return f"tenants/{tenant_id}/{path}"

        async def doc(self, *, key: str) -> bytes:
            raise AssertionError(f"không được hỏi kho cho URL ngoài: {key}")

        async def put(self, *, key: str, data: bytes, content_type: str) -> str:
            self.da_ghi[key] = data
            return f"https://kho/{key}"

    kho = _KhoChiNhanKhoa()
    monkeypatch.setattr(jobs, "object_store", lambda: kho)
    tai_ve: list[str] = []

    async def _tai(url: str) -> bytes:
        tai_ve.append(url)
        return _anh_gia()

    monkeypatch.setattr(jobs, "_tai_anh", _tai)
    record_id = doc_ids["__ALL__"]
    url = "https://nbx-sales-dev.noble.vn/img/real/proj/bang-gia__csbh.jpg"
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET file_url = $2, thumb_url = '' "
            " WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
            url,
        )
        await jobs.handle_thumb(conn, {"entity": "documents", "record_id": record_id, "project_code": "nplb"})
        thumb = await conn.fetchval(
            "SELECT thumb_url FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert tai_ve == [url]
    assert thumb, "phải sinh được ảnh thu nhỏ từ tệp tải qua HTTP"


# ── chặng mô tả ảnh (`kb_caption`) ───────────────────────────────────────────
#
# Nhánh của CỔNG NẠP API. Nguyên tắc "model sinh ⇒ người xem" (2026-08-14) cài đặt bằng cách
# gắn VLM vào FORM tải ảnh: mô tả hiện ra trước khi bấm Thêm, nên cú bấm đó là cú duyệt. Ảnh
# về bằng API không đi qua form nào — không có ai để cho xem.


async def _chay_caption(conn, media_id: int):
    return await jobs.handle_caption(conn, {"record_id": media_id, "project_code": "nplb"})


class _VlmGia:
    def __init__(self, caption: str = "Phối cảnh toà tháp nhìn từ hồ.") -> None:
        self._caption = caption
        self.so_lan = 0

    async def caption(self, image_url: str, *, profile: str) -> str:
        self.so_lan += 1
        return self._caption

    async def caption_bytes(self, data: bytes, *, mime: str, profile: str) -> str:
        self.so_lan += 1
        return self._caption


def _tiem_vlm(monkeypatch, vlm):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mo():
        yield vlm

    monkeypatch.setattr(jobs, "_mo_vlm", _mo)
    # Ảnh "trong kho" đi bằng byte, ảnh URL ngoài đi bằng URL. `media_url` của fixture là URL
    # ngoài, nên nhánh này trả None và `_caption_anh` gọi `vlm.caption(url)`.
    return vlm


async def test_caption_ghi_vao_caption_auto_KHONG_ghi_de_cot_cua_khach(pool, media_id, monkeypatch):
    """Hai cột, không phải một. `caption` là cột HỢP ĐỒNG của cổng nạp: latest-wins đưa nó về
    `''` mỗi lần khách đẩy lại bản ghi, nên mô tả ta sinh mà nằm ở đó sẽ bị xoá ở lần đồng bộ
    kế tiếp rồi sinh lại — vừa mất tiền VLM vừa làm nhãn dưới ảnh nhấp nháy."""
    vlm = _tiem_vlm(monkeypatch, _VlmGia())
    async with tenant_conn(pool, TENANT) as conn:
        ra = await _chay_caption(conn, media_id)
        hang = await conn.fetchrow("SELECT caption, caption_auto FROM tenant_data.media WHERE id = $1", media_id)

    assert vlm.so_lan == 1
    assert hang["caption_auto"] == "Phối cảnh toà tháp nhìn từ hồ."
    assert hang["caption"] == "", "cột của khách phải nguyên vẹn"
    assert ra.count == 1


async def test_caption_KHONG_goi_VLM_khi_khach_da_gui_mo_ta(pool, media_id, monkeypatch):
    vlm = _tiem_vlm(monkeypatch, _VlmGia())
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.media SET caption = 'Mô tả của khách' WHERE id = $1", media_id)
        await _chay_caption(conn, media_id)
        hang = await conn.fetchrow("SELECT caption, caption_auto FROM tenant_data.media WHERE id = $1", media_id)

    assert vlm.so_lan == 0, "khách đã mô tả rồi thì không được tốn một lượt VLM nào"
    assert (hang["caption"], hang["caption_auto"]) == ("Mô tả của khách", "")


async def test_caption_NOI_CHUOI_sang_viec_nap(pool, media_id, monkeypatch):
    _tiem_vlm(monkeypatch, _VlmGia())
    async with tenant_conn(pool, TENANT) as conn:
        await _chay_caption(conn, media_id)
        cho = await _viec_dang_cho(conn, "kb_index", media_id)
    assert cho == 1, "chặng mô tả là mắt GIỮA — không nối tiếp thì ảnh không bao giờ lên Qdrant"


async def test_VLM_hong_VAN_noi_chuoi_sang_viec_nap(pool, media_id, monkeypatch):
    """Mô tả là best-effort, NẠP THÌ KHÔNG.

    Để job này `failed` khi VLM chết là ảnh mất luôn đường lên Qdrant — tệ hơn hẳn một ảnh
    không có nhãn, và đó chính là hồi quy so với hành vi trước bản này.
    """
    from contextlib import asynccontextmanager

    class _VlmChet:
        async def caption(self, image_url: str, *, profile: str) -> str:
            raise RuntimeError("DashScope 503")

        async def caption_bytes(self, data: bytes, *, mime: str, profile: str) -> str:
            raise RuntimeError("DashScope 503")

    @asynccontextmanager
    async def _mo():
        yield _VlmChet()

    monkeypatch.setattr(jobs, "_mo_vlm", _mo)
    async with tenant_conn(pool, TENANT) as conn:
        ra = await _chay_caption(conn, media_id)
        cho = await _viec_dang_cho(conn, "kb_index", media_id)
        hang = await conn.fetchrow("SELECT caption_auto FROM tenant_data.media WHERE id = $1", media_id)

    assert cho == 1, "VLM hỏng không được làm đứt chuỗi nạp"
    assert hang["caption_auto"] == ""
    assert "không mô tả được" in ra.message


async def test_caption_bo_qua_video_nhung_van_noi_chuoi(pool, media_id, monkeypatch):
    """Video đi đường mô tả khác hẳn (Gemini, tốn hơn nhiều) và khách đã gửi sẵn tiêu đề."""
    vlm = _tiem_vlm(monkeypatch, _VlmGia())
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.media SET content_type = 'video' WHERE id = $1", media_id)
        await _chay_caption(conn, media_id)
        cho = await _viec_dang_cho(conn, "kb_index", media_id)

    assert vlm.so_lan == 0
    assert cho == 1


# ── chữ bóc từ tệp: ghi cột nào (migration `0937`) ───────────────────────────


@pytest.fixture
async def doc_cua_cong_nap(pool, seed_kb):
    """Tài liệu do hệ ngoài sở hữu — có `external_id`, tức cổng nạp làm chủ bản ghi."""
    async with tenant_conn(pool, TENANT) as conn:
        return await conn.fetchval(
            """INSERT INTO tenant_data.documents
                      (tenant_id, project_code, external_id, title, body, file_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'CRM-DOC-1', 'CSBH', '', 'docs/a.pdf', 'published')
               RETURNING id"""
        )


async def test_tai_lieu_cua_cong_nap_ghi_chu_vao_body_auto(pool, doc_cua_cong_nap, monkeypatch, kho_tep):
    """`body` là cột HỢP ĐỒNG của cổng nạp: latest-wins đưa nó về `''` mỗi lần khách đẩy
    lại bản ghi. Chữ bóc ra nằm ở đó sẽ bị xoá rồi bóc lại mỗi vòng đồng bộ — mà OCR một
    PDF scan là một lượt VLM cho MỖI trang."""
    _tiem_boc(monkeypatch, _BocQuaThuVien)
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_cua_cong_nap, "project_code": "nplb"})
        hang = await conn.fetchrow("SELECT body, body_auto FROM tenant_data.documents WHERE id = $1", doc_cua_cong_nap)

    assert hang["body_auto"] == "chữ do pypdf bóc"
    assert hang["body"] == "", "cột hợp đồng của khách phải nguyên vẹn"


async def test_tai_lieu_nhap_tay_van_ghi_vao_body(pool, doc_co_tep, monkeypatch, kho_tep):
    """Bản ghi nhập tay không có `external_id`: `body` là ô người dùng sửa, và màn CHỜ
    DUYỆT đọc đúng cột đó — đẩy sang cột phụ là làm màn ấy trống trơn."""
    _tiem_boc(monkeypatch, _BocQuaThuVien)
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_co_tep, "project_code": "nplb"})
        hang = await conn.fetchrow("SELECT body, body_auto FROM tenant_data.documents WHERE id = $1", doc_co_tep)

    assert hang["body"] == "chữ do pypdf bóc"
    assert hang["body_auto"] == ""


async def test_da_co_chu_thi_KHONG_boc_lai_va_thoat_TRUOC_khi_ton_mot_luot(
    pool, doc_cua_cong_nap, monkeypatch, kho_tep
):
    """Thoát trước phép bóc, không dựa vào tầng ghi từ chối: phép bóc là phần ĐẮT, phép
    ghi ở tận cuối. Bản trước bóc xong rồi mới phát hiện đã có chữ — tiền đã tiêu."""
    goi = {"n": 0}

    class _Dem(_BocQuaThuVien):
        async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
            goi["n"] += 1
            return await super().extract(data, filename=filename)

    _tiem_boc(monkeypatch, _Dem)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET body_auto = 'đã bóc từ vòng trước' WHERE id = $1", doc_cua_cong_nap
        )
        ra = await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_cua_cong_nap})

    assert goi["n"] == 0, "không được gọi trình bóc lần nữa"
    assert "đã có nội dung" in ra.message
    # Bỏ qua BÓC không được thành bỏ qua NẠP. Trước 2026-08-25 nhánh này trả sớm mà không
    # xếp việc index — vô hại khi nó hiếm, nhưng từ khi mọi tài liệu có tệp đi qua chặng
    # bóc thì nó là đường thường, và tài liệu sẽ không bao giờ lên Qdrant.
    async with tenant_conn(pool, TENANT) as conn:
        assert await _viec_dang_cho(conn, "kb_index", doc_cua_cong_nap) == 1


async def test_body_cua_khach_khong_con_chan_viec_boc_chu(pool, doc_cua_cong_nap, monkeypatch, kho_tep):
    """ĐẢO luật cũ (2026-08-25). Trước đây `body` khác rỗng là bỏ qua tệp, vì giả định
    «khách gửi body tức là khách gửi nội dung». Adapter của AINA phá giả định đó: nó đặt
    siêu dữ liệu («Phạm vi… Hiệu lực…») vào `body`, nên 27/40 tài liệu có PDF chưa từng
    được đọc. Nay hai cột SỐNG CHUNG — chữ khách giữ nguyên ở `body`, chữ bóc vào
    `body_auto`, và `source/query.py` nối cả hai.
    """
    _tiem_boc(monkeypatch, _BocQuaThuVien)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET body = 'Phạm vi: toàn dự án' WHERE id = $1", doc_cua_cong_nap
        )
        await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_cua_cong_nap})
        hang = await conn.fetchrow("SELECT body, body_auto FROM tenant_data.documents WHERE id = $1", doc_cua_cong_nap)

    assert hang["body"] == "Phạm vi: toàn dự án", "chữ của khách không được đụng vào"
    assert hang["body_auto"], "PDF phải được bóc chữ dù body có siêu dữ liệu"


# ── ảnh URL ngoài quá khổ: thử lại bằng byte ─────────────────────────────────


async def test_anh_ngoai_bi_VLM_tu_choi_thi_tai_ve_roi_gui_byte(pool, monkeypatch):
    """Đo trên dev 2026-08-18: một ảnh 18.2 MB / 19866×14031 làm DashScope trả 400.

    `caption_bytes` thu nhỏ khi quá `VLM_MAX_BYTES` — tức phép mà nhánh ảnh-trong-kho đã
    có sẵn. Dữ liệu về bằng cổng API toàn URL ngoài, nên đây là nhánh CHÍNH của họ.
    """
    from contextlib import asynccontextmanager

    import httpx

    da_goi: list[str] = []

    class _VlmKenBytes:
        async def caption(self, image_url: str, *, profile: str) -> str:
            da_goi.append("url")
            raise httpx.HTTPStatusError("400", request=httpx.Request("POST", "https://x"), response=httpx.Response(400))

        async def caption_bytes(self, data: bytes, *, mime: str, profile: str) -> str:
            da_goi.append(f"bytes:{mime}")
            return "mô tả từ byte đã thu nhỏ"

    @asynccontextmanager
    async def _mo():
        yield _VlmKenBytes()

    monkeypatch.setattr(jobs, "_mo_vlm", _mo)
    monkeypatch.setattr(jobs, "_tai_anh", lambda url: _tai_gia(url))

    caption, _ = await jobs._caption_anh(
        tenant_id=TENANT, media_url="https://cdn.ngoai/qua-kho.jpg", profile="media_tong_quan"
    )

    assert caption == "mô tả từ byte đã thu nhỏ"
    # Mime suy từ magic byte, KHÔNG từ `Content-Type` của kho khách: ảnh gây lỗi hôm đó
    # được S3 phục vụ dưới `binary/octet-stream` và tên tệp không có đuôi.
    assert da_goi == ["url", "bytes:image/jpeg"]


async def test_VLM_loi_5xx_thi_KHONG_tai_ve_thu_lai(pool, monkeypatch):
    """5xx là lỗi phía model, không phải ảnh quá khổ — tải 18 MB về để nhận lại đúng lỗi
    đó là trả băng thông cho một phép thử chắc chắn hỏng."""
    from contextlib import asynccontextmanager

    import httpx

    da_tai = {"n": 0}

    class _VlmChet5xx:
        async def caption(self, image_url: str, *, profile: str) -> str:
            raise httpx.HTTPStatusError("503", request=httpx.Request("POST", "https://x"), response=httpx.Response(503))

        async def caption_bytes(self, data: bytes, *, mime: str, profile: str) -> str:
            raise AssertionError("không được đi tới nhánh byte")

    @asynccontextmanager
    async def _mo():
        yield _VlmChet5xx()

    async def _dem(url: str) -> bytes:
        da_tai["n"] += 1
        return _anh_gia()

    monkeypatch.setattr(jobs, "_mo_vlm", _mo)
    monkeypatch.setattr(jobs, "_tai_anh", _dem)

    with pytest.raises(httpx.HTTPStatusError):
        await jobs._caption_anh(tenant_id=TENANT, media_url="https://cdn.ngoai/a.jpg", profile="media_tong_quan")
    assert da_tai["n"] == 0


def test_mime_suy_tu_magic_byte():
    assert jobs._mime_anh(b"\xff\xd8\xff\xe0abc") == "image/jpeg"
    assert jobs._mime_anh(b"\x89PNG\r\n\x1a\nabc") == "image/png"
    assert jobs._mime_anh(b"RIFF____WEBP") == "image/webp"
    # Không nhận ra thì đoán jpeg — `_uri_anh` chỉ dùng mime này ở nhánh KHÔNG thu nhỏ.
    assert jobs._mime_anh(b"khong-phai-anh") == "image/jpeg"


# ── mô tả video (`kb_caption`, nhánh video) ─────────────────────────────────


@pytest.fixture
async def video_id(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        return await conn.fetchval(
            """INSERT INTO tenant_data.media
                      (tenant_id, project_code, content_type, category, media_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'video', 'tong_quan',
                       'https://www.youtube.com/embed/fSVkxmsjAEw?si=abc', 'published')
               RETURNING id"""
        )


class _VideoGia:
    def __init__(self, mo_ta: str = "Toàn cảnh khu đô thị nhìn từ trên cao.") -> None:
        self.mo_ta = mo_ta
        self.duong: list[str] = []

    async def describe(self, media_url: str, *, profile: str = "video_describe") -> str:
        self.duong.append("youtube")
        return self.mo_ta

    async def describe_bytes(self, data: bytes, *, mime: str, profile: str = "video_describe") -> str:
        self.duong.append(f"bytes:{mime}:{len(data)}")
        return self.mo_ta


def _tiem_video(monkeypatch, v):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mo():
        yield v

    monkeypatch.setattr(jobs, "_mo_video", _mo)
    return v


async def test_video_youtube_mo_ta_qua_file_uri_KHONG_tai_byte(pool, video_id, monkeypatch):
    """Nhánh YouTube không tải một byte nào — rẻ hơn hẳn, và là đường của mọi video đo
    được tới hôm nay (8/8 bản ghi thật của khách)."""
    v = _tiem_video(monkeypatch, _VideoGia())

    async def _khong_duoc_tai(url, *, tran):
        raise AssertionError("nhánh YouTube không được tải byte")

    monkeypatch.setattr(jobs, "_tai_nhi_phan", _khong_duoc_tai)
    async with tenant_conn(pool, TENANT) as conn:
        await _chay_caption(conn, video_id)
        hang = await conn.fetchrow("SELECT caption, caption_auto FROM tenant_data.media WHERE id = $1", video_id)

    assert v.duong == ["youtube"]
    assert hang["caption_auto"] == "Toàn cảnh khu đô thị nhìn từ trên cao."
    assert hang["caption"] == ""


async def test_video_mp4_di_qua_files_api_voi_dung_mime(pool, video_id, monkeypatch):
    v = _tiem_video(monkeypatch, _VideoGia())

    async def _tai(url, *, tran):
        return b"\x00" * 1234

    monkeypatch.setattr(jobs, "_tai_nhi_phan", _tai)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.media SET media_url = 'https://cdn.ngoai/gioi-thieu.MOV?sig=1' WHERE id = $1",
            video_id,
        )
        await _chay_caption(conn, video_id)
        hang = await conn.fetchrow("SELECT caption_auto FROM tenant_data.media WHERE id = $1", video_id)

    # Mime suy từ ĐUÔI, bỏ query string, không phân biệt hoa thường.
    assert v.duong == ["bytes:video/quicktime:1234"]
    assert hang["caption_auto"] == "Toàn cảnh khu đô thị nhìn từ trên cao."


async def test_video_qua_kho_thi_bo_qua_nhung_van_noi_chuoi(pool, video_id, monkeypatch):
    """Trần chặn ở chỗ TẢI VỀ. Worker chạy job tuần tự nên một video 2 GB đọc trọn vào
    RAM không giết riêng job đó mà kéo cả tiến trình."""
    _tiem_video(monkeypatch, _VideoGia())

    async def _qua_kho(url, *, tran):
        raise ValueError(f"tệp vượt trần {tran} byte, dừng tải: {url}")

    monkeypatch.setattr(jobs, "_tai_nhi_phan", _qua_kho)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.media SET media_url = 'https://cdn.ngoai/to.mp4' WHERE id = $1", video_id
        )
        ra = await _chay_caption(conn, video_id)
        cho = await _viec_dang_cho(conn, "kb_index", video_id)
        hang = await conn.fetchrow("SELECT caption_auto FROM tenant_data.media WHERE id = $1", video_id)

    assert cho == 1, "video quá khổ vẫn phải lên Qdrant, chỉ là không có mô tả"
    assert hang["caption_auto"] == ""
    assert "không mô tả được" in ra.message


async def test_video_khach_da_gui_tieu_de_thi_KHONG_goi_Gemini(pool, video_id, monkeypatch):
    """Adapter khách gửi tiêu đề cho video (8/8 bản ghi thật), và Gemini là lời gọi đắt
    nhất hệ — nó không được chạy cho thứ đã có chữ."""
    v = _tiem_video(monkeypatch, _VideoGia())
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.media SET caption = 'HiSale-TEASER' WHERE id = $1", video_id)
        await _chay_caption(conn, video_id)

    assert v.duong == []


def test_mime_video_suy_tu_duoi_tep():
    from portal.modules.kb.clients import video as vc

    assert vc.mime_video("https://cdn/x/a.mp4") == "video/mp4"
    assert vc.mime_video("https://cdn/x/a.MOV?sig=1&t=2") == "video/quicktime"
    assert vc.mime_video("https://cdn/x/a.webm") == "video/webm"
    # Không nhận ra ⇒ mp4, định dạng áp đảo. Sai mime là `INVALID_ARGUMENT` chứ không
    # phải một mô tả tệ, nên mặc định phải là cái phổ biến nhất.
    assert vc.mime_video("https://cdn/x/a.") == "video/mp4"


def test_youtube_watch_url_nhan_moi_dang_link():
    from portal.modules.kb.clients import video as vc

    for u in (
        "https://www.youtube.com/embed/fSVkxmsjAEw?si=x",
        "https://m.youtube.com/watch?v=fSVkxmsjAEw",
        "https://youtube.com/shorts/fSVkxmsjAEw",
        "https://youtu.be/fSVkxmsjAEw",
    ):
        assert vc.youtube_watch_url(u) == "https://www.youtube.com/watch?v=fSVkxmsjAEw", u
    assert vc.youtube_watch_url("https://cdn.ngoai/a.mp4") is None


# ── van duyệt hẹp lại: chỉ chữ KHÔNG có bản đối chiếu (2026-08-25) ──────────


class _BocQuaOCR_CoLopChu:
    def __init__(self, vlm=None) -> None:
        pass

    async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
        return ExtractResult(text="chữ OCR", da_ocr=True, co_lop_chu=True)


async def test_pdf_co_lop_chu_thi_KHONG_bat_van_duyet(pool, doc_co_tep, monkeypatch, kho_tep):
    """`pypdf` đọc được lớp chữ nghĩa là chữ OCR CÓ bản đối chiếu — đo trên dữ liệu thật
    hai bản khớp 26/26 con số. Bắt duyệt ở đây là bắt người dùng duyệt thứ máy đọc đúng."""
    _tiem_boc(monkeypatch, _BocQuaOCR_CoLopChu)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.documents SET file_url = $2 WHERE id = $1", doc_co_tep, "docs/a.pdf")
        await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_co_tep})
        cho = await conn.fetchval(
            "SELECT coalesce(body_cho_duyet, false) FROM tenant_data.documents WHERE id = $1", doc_co_tep
        )
        assert cho is False, "PDF có lớp chữ không cần người duyệt"
        assert await _viec_dang_cho(conn, "kb_index", doc_co_tep) == 1


async def test_pdf_scan_thuan_thi_VAN_bat_van_duyet(pool, doc_co_tep, monkeypatch, kho_tep):
    """Đối chứng: không có lớp chữ thì không có gì đối chiếu, đó mới là chỗ cần người xem."""
    _tiem_boc(monkeypatch, _BocQuaOCR)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.documents SET file_url = $2 WHERE id = $1", doc_co_tep, "docs/a.pdf")
        await jobs.handle_enrich(conn, {"entity": "documents", "record_id": doc_co_tep})
        cho = await conn.fetchval(
            "SELECT coalesce(body_cho_duyet, false) FROM tenant_data.documents WHERE id = $1", doc_co_tep
        )
        assert cho is True


async def test_loi_mang_khi_tai_anh_thi_JOB_THU_LAI_chu_khong_nuot(pool, media_id, monkeypatch):
    """Lỗi TẠM THỜI phải nổi lên để `core.jobs` xếp lại. Nuốt nó nghĩa là mất thumb — và
    từ 2026-08-25 mất thumb là mất luôn caption, vì caption đọc thumb."""
    from portal.modules.kb.contracts import TemporaryFetchError

    async def _het_han(url: str) -> bytes:
        raise TemporaryFetchError("ReadTimeout: quá hạn")

    monkeypatch.setattr(jobs, "_tai_anh", _het_han)
    async with tenant_conn(pool, TENANT) as conn:
        with pytest.raises(TemporaryFetchError):
            await jobs.handle_thumb(conn, {"entity": "media", "record_id": media_id, "project_code": "nplb"})
