"""Handler job — điểm vào thật của module. Worker tự gom file này.

Payload phải có `vertical`, nếu không thì vertical thứ hai dùng rag_config của BĐS.
`dependencies()` là chỗ nối dây duy nhất; test gọi thẳng service.* với fake.py.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import asyncpg
import httpx

from portal.core.jobs import JobResult, enqueue, register
from portal.modules.kb import files_repo, service, settings
from portal.modules.kb.conflicts.enqueue import queue_check
from portal.modules.kb.contracts import (
    CATEGORY_TONG_QUAN,
    KIND_CAPTION,
    KIND_CAPTION_PREVIEW,
    KIND_DELETE_INDEX,
    KIND_DOI_CO,
    KIND_DOI_NHAN,
    KIND_ENRICH,
    KIND_INDEX,
    KIND_KB_FILE_INDEX,
    KIND_PROVISION,
    KIND_SYNC_PROJECT,
    KIND_THUMB,
    LANE_CAPTION,
    LANE_ENRICH,
    LANE_INDEX,
    LANE_THUMB,
    MODE_DELTA,
    MODE_FULL,
    RETRY_CAPTION,
    RETRY_VIEC_KB,
    IndexClient,
    ObjectStore,
    TemporaryError,
    VerticalSpec,
    normalize_caption,
)
from portal.modules.kb.directive import profiles
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.settings import get_env
from portal.modules.kb.state import repo

log = logging.getLogger(__name__)

KIND_DELETE = KIND_DELETE_INDEX
PROFILE_CAPTION_CATEGORY = "caption_danh_muc"


def dependencies() -> tuple[IndexClient, IndexClient, ObjectStore]:
    """(rag, media, store) thật. Dựng mới mỗi job: worker chạy nhiều làn, và một client
    sống lâu giữ kết nối HTTP qua các job là chỗ lỗi khó truy khi tunnel của embed
    service đổi URL."""
    from portal.core.config import get_settings
    from portal.modules.kb.clients.embed import EmbedClient
    from portal.modules.kb.clients.media import MediaClient
    from portal.modules.kb.clients.rag import RagClient
    from portal.modules.kb.index.store import QdrantStore

    env = get_env()
    cfg = get_settings()
    kho = object_store()
    embed = EmbedClient(base_url=env.embed_url, token=env.santa_models_token, objects=kho)
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    return (
        RagClient(embed=embed, store=store),
        MediaClient(embed=embed, store=store),
        kho,
    )


@asynccontextmanager
async def open_dependencies() -> AsyncIterator[tuple[IndexClient, IndexClient, ObjectStore]]:
    """`dependencies()` có khối dọn. MỌI handler phải đi qua đây, không gọi thẳng.

    Worker là tiến trình sống dài và `dependencies()` dựng client MỚI mỗi job: một lần
    bấm "Đồng bộ tri thức" cho dự án 116 record là 116 job, mỗi job một `httpx.AsyncClient`
    (embed) và một `AsyncQdrantClient` — không đóng thì cả 116 cặp nằm chờ GC, và job lỗi
    (worker retry) là lúc rò rỉ nhanh nhất.
    """
    bo = dependencies()
    try:
        yield bo
    finally:
        for obj in bo:
            aclose = getattr(obj, "aclose", None)
            if aclose is not None:
                await aclose()


def object_store() -> ObjectStore:
    """Kho tệp RIÊNG, không đi qua `dependencies()`: `EmbedClient.__init__` raise khi
    thiếu `KB_SANTA_MODELS_TOKEN`, và chặng enrich không dùng embed một dòng nào — nó
    không được chết vì token của một client nó không gọi."""
    from portal.core.storage import kho_tep_tu_cai_dat
    from portal.modules.kb.storage.object_store import S3Store

    return S3Store(kho_tep_tu_cai_dat())


def _vlm():
    from portal.modules.kb.clients.vlm import VlmClient

    env = get_env()
    return VlmClient(base_url=env.vlm_base_url, api_key=env.vlm_api_key)


@asynccontextmanager
async def _mo_vlm() -> AsyncIterator[object]:
    """VLM client CÓ khối dọn — dùng cái này, đừng gọi `_vlm()` trần.

    `_vlm()` dựng một `httpx.AsyncClient` (xem `VlmClient.__init__`), và trước 2026-08-14
    có BỐN chỗ gọi nó trần rồi không bao giờ `aclose()`: hai lời gọi mô tả ảnh, một lời gọi
    bóc chữ, và (qua `_mo_video`) hai lời gọi mô tả video. Worker là tiến trình sống dài, nên
    đó đúng là kiểu rò mà `open_dependencies` được viết ra để chặn — docstring của nó ghi
    rõ: 116 job mỗi job bỏ lại một client là cách nó từng chết.
    """
    c = _vlm()
    try:
        yield c
    finally:
        # `getattr` vì test tiêm client giả không giữ kết nối nào.
        aclose = getattr(c, "aclose", None)
        if aclose is not None:
            await aclose()


@asynccontextmanager
async def _mo_video() -> AsyncIterator[object]:
    """Cùng lý do `_mo_vlm`: `VideoClient` cũng giữ một `httpx.AsyncClient`."""
    from portal.modules.kb.clients.video import VideoClient

    c = VideoClient(api_key=get_env().gemini_api_key)
    try:
        yield c
    finally:
        aclose = getattr(c, "aclose", None)
        if aclose is not None:
            await aclose()


def workspace_slug(tenant_id: str) -> str:
    """control.tenants.id đã là slug (CHECK ở migration 0002) nên không cần cột riêng."""
    return tenant_id


async def _ly_do_bo_qua(conn: asyncpg.Connection, *, vertical: VerticalSpec, entity: str, record_id: int) -> str:
    """Vì sao service trả None. HAI lý do khác nhau hẳn, và chỉ một trong hai đúng.

    Ảnh `csbh` vẫn published nhưng `should_index_media` trả False — nói "không còn
    published" ở đây đẩy người vận hành đi tìm một record đã ẩn không tồn tại. Một
    SELECT thêm, chỉ ở nhánh bỏ qua, không nằm trên đường nạp bình thường.
    """
    if entity == "media":
        category = await conn.fetchval(
            "SELECT category FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
        if category is not None and not profiles.should_index_media(vertical, str(category)):
            return f"media#{record_id}: danh mục {category} ngoài phạm vi nạp → đã xoá point"
    return f"{entity}#{record_id} không còn published → đã xoá point"


_CONFLICT_SOURCES = frozenset({"projects", "documents"})


async def handle_index(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Record không còn đủ điều kiện thì tự chuyển sang xoá, không coi là lỗi."""
    vertical = REAL_ESTATE
    entity = str(payload["entity"])
    record_id = int(payload["record_id"])
    doc_type = str(payload.get("doc_type", ""))
    mode = str(payload.get("mode", MODE_FULL))
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    slug = workspace_slug(tenant_id)
    if entity != "media" and entity not in {s.table for s in vertical.embed_sources}:
        return JobResult(count=0, message=f"{entity}#{record_id}: không còn là nguồn embed, bỏ qua")
    async with open_dependencies() as (rag, media, store):
        if entity == "media":
            result = await service.index_media(
                conn,
                tenant_id=tenant_id,
                slug=slug,
                vertical=vertical,
                record_id=record_id,
                media=media,
                store=store,
                mode=mode,
            )
        else:
            result = await service.index_text(
                conn,
                tenant_id=tenant_id,
                slug=slug,
                vertical=vertical,
                entity=entity,
                doc_type=doc_type,
                record_id=record_id,
                rag=rag,
                store=store,
                mode=mode,
            )

        if result is None:
            await service.delete_index(conn, slug=slug, entity=entity, record_id=record_id, rag=rag, media=media)
            return JobResult(
                count=0, message=await _ly_do_bo_qua(conn, vertical=vertical, entity=entity, record_id=record_id)
            )

    if result.skipped:
        return JobResult(count=0, message=f"{entity}#{record_id}: nội dung không đổi, giữ nguyên")
    project_code = str(payload.get("project_code") or "")
    if entity in _CONFLICT_SOURCES and project_code and result.points_upserted > 0:
        await queue_check(
            conn, tenant_id=tenant_id, actor="kb_index", project_code=project_code, entity=entity, record_id=record_id
        )
    return JobResult(count=result.points_upserted, message=f"{entity}#{record_id}: +{result.points_upserted} point")


async def handle_kb_file_index(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Nạp một tệp của kho «Tài liệu tra cứu». BẮT RỘNG có chủ ý (spec 2026-08-20 §4):

    hàng treo `dang_xu_ly` vĩnh viễn là chế độ hỏng tệ nhất (spinner quay mãi — bài học
    ghi trong commit 0390d86), nên MỌI thất bại phải kết thúc ở `loi` với message chỉ
    đường. Không re-raise: handler chạy trong giao dịch của worker, ném là rollback luôn
    cú UPDATE `loi` vừa ghi — vì thế phần nạp chạy trong SAVEPOINT (conn.transaction()
    lồng) để lỗi Postgres giữa chừng không đầu độc giao dịch ngoài. Retry transient đã
    nằm trong EmbedClient; đăng ký retries=0.
    """
    record_id = int(payload["record_id"])
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    slug = workspace_slug(tenant_id)
    try:
        async with conn.transaction(), open_dependencies() as (rag, media, store):
            msg = await service.index_kb_file(
                conn, tenant_id=tenant_id, slug=slug, record_id=record_id, rag=rag, media=media, store=store
            )
        # ⚠️ Phân loại bằng SUBSTRING của chính message thành công/thất bại của
        # index_kb_file — mọi return string ở đó (kể cả hậu tố cảnh báo ảnh) phải
        # tránh hai từ này trừ khi thật sự muốn count=0. Xem cảnh báo cạnh `ext` ở
        # service.py::index_kb_file và test_anh_loi_van_la_thanh_cong (pin lại đúng
        # bug đã xảy ra: hậu tố "N ảnh lỗi" từng làm một lượt nạp TỐT bị đếm count=0).
        return JobResult(count=0 if "bỏ qua" in msg or "lỗi" in msg else 1, message=msg)
    except Exception as e:  # noqa: BLE001 — xem docstring
        log.warning("kb_file_index #%s: %s: %s", record_id, type(e).__name__, e)
        await files_repo.danh_dau_loi(
            conn, record_id=record_id, loi_message="Lỗi hệ thống khi nạp tài liệu — thử tải lại tệp."
        )
        return JobResult(count=0, message=f"kb_files#{record_id}: {type(e).__name__}: {e}")


async def handle_delete(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """`anchor_code` có mặt = cascade cả cây con (§7.3).

    Không cần `vertical`: nhánh cascade đọc sổ `kb_index_state` theo `project_code`,
    còn nhánh một-record định vị bằng `(entity, record_id)`. Cả hai không dùng khai
    báo vertical nào.
    """
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    slug = workspace_slug(tenant_id)
    async with open_dependencies() as (rag, media, _store):
        anchor_code = payload.get("anchor_code")
        if anchor_code:
            count = await service.delete_cascade(conn, slug=slug, anchor_code=str(anchor_code), rag=rag, media=media)
            return JobResult(count=count, message=f"cascade {anchor_code}: xoá {count} mục")

        entity = str(payload["entity"])
        record_id = int(payload["record_id"])
        await service.delete_index(
            conn,
            slug=slug,
            entity=entity,
            record_id=record_id,
            doc_type=str(payload.get("doc_type", "")),
            rag=rag,
            media=media,
        )
    return JobResult(count=1, message=f"đã xoá point của {entity}#{record_id}")


async def _tai_anh(url: str) -> bytes:
    """Tách thành hàm module để test `monkeypatch.setattr(jobs, "_tai_anh", …)` được —
    cùng nếp `_vlm`/`object_store`. Nội tuyến nó là mọi test enrich phải đi ra DNS thật.

    Timeout tách theo CHIỀU: ảnh của khách có tấm 47 MB, và 8 làn thumb chia nhau đường
    truyền thì mỗi luồng còn vài trăm KB/s — trần 30 giây phẳng là tự đảm bảo thất bại.

    Kiểm `Content-Length`: byte thiếu đi thẳng vào Pillow và ra «cannot identify image
    file», tức tải hụt đội lốt ảnh hỏng. Đo được 71 lần như vậy trong một đợt nạp.
    """
    import httpx

    from portal.modules.kb.contracts import TemporaryFetchError

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=30.0)
        ) as c:
            r = await c.get(url)
            r.raise_for_status()
            data = r.content
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise TemporaryFetchError(f"{type(e).__name__}: {e}") from e

    khai = r.headers.get("content-length")
    if khai and khai.isdigit() and len(data) != int(khai):
        raise TemporaryFetchError(f"tải hụt: nhận {len(data)}/{khai} byte")
    return data


_CHU_KY_ANH: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP — 4 byte đầu là đủ để phân biệt ở đây
)


def _mime_anh(data: bytes) -> str:
    """Đoán mime từ magic byte. `imghdr` đã bị bỏ khỏi stdlib ở Python 3.13.

    Cần vì `Content-Type` của kho khách không tin được: ảnh làm DashScope trả 400 hôm
    2026-08-18 được S3 phục vụ dưới `binary/octet-stream`, và tên tệp thì không có đuôi
    (28/31 ảnh của tenant đó kết thúc bằng một dấu chấm trần).

    Rơi về `image/jpeg` khi không nhận ra: `_uri_anh` chỉ dùng mime này ở nhánh KHÔNG
    thu nhỏ, còn nhánh thu nhỏ luôn ghi `image/webp` — nên đoán sai chỉ ảnh hưởng ảnh
    nhỏ, và jpeg là phỏng đoán đúng nhất trong tập ảnh bất động sản.
    """
    for chu_ky, mime in _CHU_KY_ANH:
        if data.startswith(chu_ky):
            return mime
    return "image/jpeg"


async def _tai_nhi_phan(url: str, *, tran: int) -> bytes:
    """Tải một tệp nhị phân, DỪNG GIỮA CHỪNG khi vượt trần.

    Khác `_tai_anh` ở đúng chỗ đó, và đó là cả lý do nó tồn tại: video không có trần
    tự nhiên như ảnh. Đọc trọn rồi mới đo là đã giữ 2 GB trong RAM của một worker chạy
    job tuần tự — job đó không chết một mình, nó kéo cả tiến trình.
    """
    dem = bytearray()
    async with (
        httpx.AsyncClient(follow_redirects=True, timeout=settings.HTTP_TIMEOUT_SEC) as c,
        c.stream("GET", url) as r,
    ):
        r.raise_for_status()
        async for khuc in r.aiter_bytes():
            dem.extend(khuc)
            if len(dem) > tran:
                raise ValueError(f"tệp vượt trần {tran} byte, dừng tải: {url}")
    return bytes(dem)


async def _video_byte(*, tenant_id: str, media_url: str) -> bytes:
    """Byte video, từ kho ta hoặc từ URL ngoài. KHÔNG thu nhỏ — Gemini nhận video thô."""
    from portal.modules.kb.storage.object_store import is_internal_key

    if is_internal_key(media_url):
        store = object_store()
        return await store.doc(key=store.key(tenant_id=tenant_id, path=media_url))
    return await _tai_nhi_phan(media_url, tran=settings.VIDEO_MAX_BYTES)


async def _mo_ta_video(*, tenant_id: str, media_url: str) -> str:
    """Mô tả một video. Chọn nhánh theo NGUỒN, không theo đuôi tệp.

    YouTube đi bằng `file_uri` — không tải byte nào, nên rẻ hơn hẳn và là đường của mọi
    video đo được tới hôm nay. Nguồn tệp (mp4/mov/webm/…) phải qua Files API: tải về,
    đẩy lên, chờ Gemini giải mã, rồi mới hỏi.
    """
    from portal.modules.kb.clients.video import mime_video, youtube_watch_url

    async with _mo_video() as video:
        if youtube_watch_url(media_url):
            return await video.describe(media_url)
        data = await _video_byte(tenant_id=tenant_id, media_url=media_url)
        return await video.describe_bytes(data, mime=mime_video(media_url))


async def _anh_trong_kho(*, tenant_id: str, media_url: str) -> bytes | None:
    """Byte ảnh đã thu nhỏ nếu nó nằm trong kho ta; None nếu là URL ngoài.

    Đọc thẳng qua S3 chứ không presign rồi tải lại bằng HTTP: presigned URL chỉ có ích
    cho bên thứ ba, mà bên thứ ba (DashScope) lại không mở được endpoint nội bộ.
    """
    import asyncio

    from portal.modules.kb.storage.object_store import is_internal_key
    from portal.modules.kb.storage.thumbnail import to_webp

    if not is_internal_key(media_url):
        return None
    store = object_store()
    goc = await store.doc(key=store.key(tenant_id=tenant_id, path=media_url))
    return await asyncio.to_thread(to_webp, goc, width=settings.VLM_IMAGE_WIDTH)


async def _thumb_neu_thieu(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    record_id: int,
    tai_ve: "Callable[[], bytes | Awaitable[bytes]]",
    media_url: str,
    content_hash: str,
    da_co: str,
    force: bool,
) -> str | None:
    """Sinh thumbnail cho MỘT ảnh, chỉ khi hàng chưa có (hoặc `force`). Trả LÝ DO thất bại.

    KHÔNG ĐỂ LỖI THUMB LÀM ĐỔ CẢ JOB: caption là sản phẩm chính của chặng này, còn
    thumbnail là tối ưu hiển thị. Một ảnh CDN trả 404 hay một định dạng Pillow không
    đọc được sẽ mất thumb, không mất caption — nên bắt rộng và chỉ ghi nhật ký.
    """
    if da_co and not force:
        return None
    from portal.modules.kb.contracts import TemporaryError
    from portal.modules.kb.storage import thumbnail

    try:
        khoa = await thumbnail.sinh_va_luu(
            object_store(),
            tenant_id=tenant_id,
            media_url=media_url,
            content_hash=content_hash,
            tai_ve=tai_ve,
        )
    except TemporaryError:
        raise
    except Exception as e:  # noqa: BLE001 — xem docstring
        log.warning("thumb media#%s bỏ qua: %s: %s", record_id, type(e).__name__, e)
        return f"{type(e).__name__}: {e}"
    await repo.save_thumb(conn, record_id=record_id, thumb_url=khoa)
    return None


def _profile_caption(category: str) -> str:
    """Ảnh khách để tổng quan thì hỏi VLM thêm danh mục; ảnh đã phân loại thì tin khách."""
    if category == CATEGORY_TONG_QUAN:
        return PROFILE_CAPTION_CATEGORY
    return profiles.caption_profile(REAL_ESTATE, category)


async def _caption_anh(
    *, tenant_id: str, media_url: str, profile: str, thumb_url: str = ""
) -> tuple[str, "Callable[[], bytes | Awaitable[bytes]]"]:
    """Ảnh trong kho ta đi bằng byte, ảnh dán URL ngoài đi bằng URL — DashScope không
    mở được endpoint nội bộ, kể cả khi đã presign. Trả kèm cách lấy byte cho thumb.

    Có thumb thì gửi thumb: ảnh gốc quá cỡ bị DashScope từ chối 400, và đó là 24% ảnh
    của một tenant thật (đo 2026-08-25).
    """
    from portal.modules.kb.storage.object_store import is_internal_key

    if thumb_url and is_internal_key(thumb_url):
        thumb = await object_store().doc(key=thumb_url)
        async with _mo_vlm() as vlm:
            return await vlm.caption_bytes(thumb, mime="image/webp", profile=profile), lambda: thumb

    data = await _anh_trong_kho(tenant_id=tenant_id, media_url=media_url)
    if data is None:
        async with _mo_vlm() as vlm:
            try:
                return await vlm.caption(media_url, profile=profile), lambda: _tai_anh(media_url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    raise
                log.info("caption qua URL bị %s, thử lại bằng byte: %s", e.response.status_code, media_url)
                goc = await _tai_anh(media_url)
                return await vlm.caption_bytes(goc, mime=_mime_anh(goc), profile=profile), lambda: goc
    async with _mo_vlm() as vlm:
        return await vlm.caption_bytes(data, mime="image/webp", profile=profile), lambda: data


async def _noi_sang_nap(conn: asyncpg.Connection, *, tenant_id: str, payload: dict, record_id: int) -> None:
    """Mọi nhánh rời `handle_enrich` đều phải nối sang việc nạp — bỏ qua bóc chữ không
    được biến thành bỏ qua nạp, nếu không tài liệu biến mất khỏi Qdrant."""
    from portal.modules.kb.ops import enqueue as dat

    await dat.dat_viec_nap(
        conn,
        tenant_id=tenant_id,
        actor=str(payload.get("actor", "enrich")),
        entity="documents",
        record_id=record_id,
        project_code=str(payload.get("project_code", "")),
    )


async def handle_enrich(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """CHỈ CÒN bóc chữ từ tệp tài liệu. Ghi vào cột user sửa được.

    NHÁNH ẢNH VÀ NHÁNH VIDEO ĐÃ BỎ (2026-08-14, chốt 2 của spec): mô tả do model sinh chạy
    ĐÚNG MỘT LẦN, lúc tải tệp lên, qua đường mô tả nháp — nó điền vào ô mô tả TRONG FORM và
    người dùng đọc/sửa rồi mới bấm Thêm, nên cú bấm đó chính là cú duyệt. Sau đó không đường
    nào gọi model cho ảnh đó nữa: không nút "Tạo lại mô tả", không tự tả lại khi đổi ảnh.
    Phần sinh ảnh thu nhỏ tách sang `handle_thumb`.

    VAN DUYỆT chỉ áp cho chữ do OCR đọc, không cho mọi chữ bóc: PDF có lớp chữ / docx / xlsx
    do THƯ VIỆN bóc nên chính xác và nạp ngay; PDF scan và ảnh thì model đọc ảnh nên có thể
    sai. Nguyên tắc: *model sinh ⇒ người xem; thư viện bóc ⇒ tự động.*
    """
    entity = str(payload["entity"])
    record_id = int(payload["record_id"])
    force = bool(payload.get("force", False))
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))

    if entity != "documents":
        return JobResult(count=0, message=f"{entity}#{record_id}: chặng bóc chữ chỉ áp cho tài liệu")

    row = await conn.fetchrow(
        "SELECT file_url, body, body_auto, external_id IS NOT NULL AS cua_ngoai FROM tenant_data.documents "
        " WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
    if row is None or not row["file_url"]:
        return JobResult(count=0, message=f"documents#{record_id} không có tệp để bóc")

    # Bản ghi của cổng nạp: chỉ `body_auto` mới nói «đã bóc rồi». `body` của chúng thường
    # là siêu dữ liệu adapter ghi («Phạm vi… Hiệu lực…»), xét nó là bỏ qua PDF vĩnh viễn.
    da_co = row["body_auto"] if row["cua_ngoai"] else (row["body"] or row["body_auto"])
    if not force and da_co:
        await _noi_sang_nap(conn, tenant_id=tenant_id, payload=payload, record_id=record_id)
        return JobResult(count=0, message=f"documents#{record_id}: đã có nội dung, không bóc lại")

    from portal.modules.kb.clients.extract import TextExtractor
    from portal.modules.kb.storage.object_store import is_internal_key

    tep = str(row["file_url"])
    if is_internal_key(tep):
        store = object_store()
        data = await store.doc(key=store.key(tenant_id=tenant_id, path=tep))
    else:
        data = await _tai_anh(tep)
    async with _mo_vlm() as vlm:
        ra = await TextExtractor(vlm=vlm).extract(data, filename=str(row["file_url"]))
    if not ra.text:
        await _noi_sang_nap(conn, tenant_id=tenant_id, payload=payload, record_id=record_id)
        return JobResult(count=0, message="không bóc được chữ từ tệp này, vui lòng dán nội dung")

    da_ghi = await repo.cache_extracted_text(conn, record_id=record_id, text=ra.text, force=force)
    cat = " (đã cắt ở trần số trang)" if ra.da_cat else ""

    # Van duyệt chỉ cho chữ KHÔNG có bản đối chiếu: PDF có lớp chữ thì `pypdf` là bản
    # đối chiếu, và hai bản đã đo khớp 26/26 con số trên dữ liệu thật. Scan thuần mới cần
    # người xem — nguyên tắc «model sinh ⇒ người xem» giữ nguyên, chỉ hẹp lại cho đúng chỗ.
    if da_ghi and ra.da_ocr and not ra.co_lop_chu and not bool(payload.get("tu_duyet", False)):
        await repo.dat_cho_duyet(conn, record_id=record_id, cho_duyet=True)
        return JobResult(count=1, message=f"documents#{record_id}: {len(ra.text)} ký tự đọc từ ảnh, chờ duyệt{cat}")

    await _noi_sang_nap(conn, tenant_id=tenant_id, payload=payload, record_id=record_id)
    return JobResult(count=1, message=f"documents#{record_id}: {len(ra.text)} ký tự{cat}")


async def handle_caption(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Mô tả cho ảnh ĐÃ có hàng `media` mà chưa ai mô tả, rồi TỰ đặt việc nạp.

    ĐÂY LÀ NHÁNH CỦA CỔNG NẠP API, không phải đường đảo quyết định 2026-08-14. Nguyên tắc
    "model sinh ⇒ người xem" cài đặt bằng cách gắn VLM vào FORM tải ảnh: mô tả hiện ra
    trước khi bấm Thêm, nên cú bấm đó là cú duyệt. Ảnh về bằng API không đi qua form nào —
    không có ai để cho xem, và bỏ trống thì nhãn dưới ảnh gửi cho khách là chuỗi rỗng.

    GHI VÀO `caption_auto`, KHÔNG `caption`: `caption` là cột hợp đồng của cổng nạp và bị
    latest-wins đưa về `''` mỗi lần khách đẩy lại bản ghi đó — xem migration `0936`.

    ⚠ MÔ TẢ LÀ BEST-EFFORT, NẠP THÌ KHÔNG. Mọi lỗi VLM đều nuốt tại đây rồi vẫn nối sang
    việc nạp: ảnh không có mô tả vẫn phải tới được agent (đúng như hôm nay), còn để job
    này `failed` là ảnh mất luôn cả đường lên Qdrant vì chuỗi đứt ở đây. Cùng lý lẽ với
    "nối kể cả khi thumb hỏng" ở `handle_thumb`.
    """
    record_id = int(payload["record_id"])
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    row = await conn.fetchrow(
        "SELECT content_type, category, media_url, caption, caption_auto, thumb_url FROM tenant_data.media "
        " WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )

    thong_diep = f"media#{record_id}: không cần mô tả"
    loai = str(row["content_type"]) if row is not None else ""
    if row is not None and loai in ("image", "video") and not (row["caption"] or row["caption_auto"]):
        try:
            if loai == "video":
                caption = await _mo_ta_video(tenant_id=tenant_id, media_url=str(row["media_url"]))
            else:
                profile = _profile_caption(str(row["category"] or ""))
                caption, _ = await _caption_anh(
                    tenant_id=tenant_id,
                    media_url=str(row["media_url"]),
                    profile=profile,
                    thumb_url=str(row["thumb_url"] or ""),
                )
                caption = normalize_caption(caption)
            da_ghi = await repo.cache_caption_auto(conn, record_id=record_id, caption=caption)
            thong_diep = (
                f"media#{record_id}: {len(caption)} ký tự"
                if da_ghi
                else f"media#{record_id}: khách vừa gửi mô tả, giữ bản của họ"
            )
        except TemporaryError:
            raise
        except Exception as e:  # noqa: BLE001 — xem docstring: mô tả hỏng KHÔNG được chặn nạp
            log.warning("caption media#%s bỏ qua: %s: %s", record_id, type(e).__name__, e)
            thong_diep = f"media#{record_id}: không mô tả được ({type(e).__name__})"

    from portal.modules.kb.ops import enqueue as dat

    await dat.dat_viec_nap(
        conn,
        tenant_id=tenant_id,
        actor=str(payload.get("actor", "caption")),
        entity="media",
        record_id=record_id,
        project_code=str(payload.get("project_code", "")),
    )
    return JobResult(count=1, message=thong_diep)


async def handle_thumb(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Sinh ảnh thu nhỏ cho MỘT ảnh (hoặc trang 1 của một tệp), rồi TỰ đặt việc nạp.

    TÁCH khỏi chặng mô tả (2026-08-14): chặng đó làm hai việc không liên quan trong cùng một
    nhánh ảnh — gọi VLM VÀ sinh thumb. Sau khi VLM chỉ chạy một lần lúc tải ảnh lên (mô tả
    hiện trong form TRƯỚC khi lưu), bỏ nhánh đó nguyên khối sẽ làm mọi ảnh mới không có thumb.

    KHÔNG dùng đường ghi thumb-kèm-dấu-tay: hàm đó gán `content_hash` VÔ ĐIỀU KIỆN, và gọi nó
    từ đây — chỗ chưa tính dấu tay chunk — sẽ XOÁ TRẮNG dấu tay của hàng, làm mọi phép so lệch
    sau đó coi point của ảnh là đã trôi.

    Nối chuỗi sang việc nạp ở CUỐI, và nối kể cả khi thumb hỏng: ảnh không có bản nhỏ vẫn phải
    tới được agent, và giao diện đã có đường rơi về ảnh gốc.
    """
    entity = str(payload["entity"])
    record_id = int(payload["record_id"])
    ghi_de = bool(payload.get("ghi_de", False))
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))

    if entity == "media":
        thong_diep = await _thumb_media(conn, tenant_id=tenant_id, record_id=record_id, ghi_de=ghi_de)
    elif entity == "documents":
        thong_diep = await _thumb_tai_lieu(conn, tenant_id=tenant_id, record_id=record_id, ghi_de=ghi_de)
    else:
        thong_diep = f"{entity}#{record_id}: không có ảnh thu nhỏ cho loại này"

    actor = str(payload.get("actor", "thumb"))
    project_code = str(payload.get("project_code", ""))
    if entity == "documents":
        await enqueue(
            conn,
            tenant_id=tenant_id,
            kind=KIND_ENRICH,
            actor=actor,
            payload={
                "vertical": str(payload.get("vertical", "real_estate")),
                "entity": "documents",
                "record_id": record_id,
                "project_code": project_code,
                "actor": actor,
                "force": bool(payload.get("ghi_de", False)),
                "tu_duyet": bool(payload.get("tu_duyet", False)),
            },
        )
        return JobResult(count=1, message=thong_diep)

    if entity == "media":
        await enqueue(
            conn,
            tenant_id=tenant_id,
            kind=KIND_CAPTION,
            actor=actor,
            payload={
                "vertical": str(payload.get("vertical", "real_estate")),
                "record_id": record_id,
                "project_code": project_code,
                "actor": actor,
            },
        )
        return JobResult(count=1, message=thong_diep)

    from portal.modules.kb.ops import enqueue as dat

    await dat.dat_viec_nap(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        entity=entity,
        record_id=record_id,
        project_code=project_code,
    )
    return JobResult(count=1, message=thong_diep)


async def _thumb_media(conn: asyncpg.Connection, *, tenant_id: str, record_id: int, ghi_de: bool) -> str:
    row = await conn.fetchrow(
        "SELECT media_url, content_hash, thumb_url FROM tenant_data.media "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
    if row is None:
        return f"media#{record_id}: không có hàng"
    da_co = str(row["thumb_url"] or "")
    if da_co and not ghi_de:
        return f"media#{record_id}: đã có ảnh thu nhỏ"
    media_url = str(row["media_url"])
    data = await _anh_trong_kho(tenant_id=tenant_id, media_url=media_url)
    tai_ve = (lambda: data) if data is not None else (lambda: _tai_anh(media_url))
    loi = await _thumb_neu_thieu(
        conn,
        tenant_id=tenant_id,
        record_id=record_id,
        tai_ve=tai_ve,
        media_url=media_url,
        content_hash=str(row["content_hash"] or ""),
        da_co=da_co,
        force=ghi_de,
    )
    # Nói THẬT. Bản cũ trả «đã sinh ảnh thu nhỏ» vô điều kiện, nên 47 ảnh mất thumb mà
    # job vẫn xanh với đúng dòng chữ đó — và caption của chúng chết theo, im lặng.
    if loi:
        return f"media#{record_id}: KHÔNG sinh được ảnh thu nhỏ ({loi})"
    return f"media#{record_id}: đã sinh ảnh thu nhỏ"


async def _trang_dau_pdf(data: bytes) -> bytes:
    """Trang 1 của PDF thành PNG. Dùng lại đúng bộ render của đường OCR."""
    import asyncio

    from portal.modules.kb.clients.extract import _render_pages

    trang = await asyncio.to_thread(_render_pages, data, 1)
    if not trang:
        raise ValueError("PDF không render được trang nào")
    return trang[0]


async def _thumb_tai_lieu(conn: asyncpg.Connection, *, tenant_id: str, record_id: int, ghi_de: bool) -> str:
    """Ảnh preview cho tệp đính kèm: trang 1 nếu là PDF, chính nó nếu là ảnh.

    Không có nó thì tệp gửi kèm câu trả lời chỉ là một link trần.
    """
    row = await conn.fetchrow(
        "SELECT file_url, thumb_url FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
    if row is None or not row["file_url"]:
        return f"documents#{record_id}: không có tệp để làm ảnh thu nhỏ"
    da_co = str(row["thumb_url"] or "")
    if da_co and not ghi_de:
        return f"documents#{record_id}: đã có ảnh thu nhỏ"

    from portal.modules.kb.storage import thumbnail
    from portal.modules.kb.storage.object_store import is_internal_key

    khoa_tep = str(row["file_url"])
    store = object_store()
    try:
        if is_internal_key(khoa_tep):
            data = await store.doc(key=store.key(tenant_id=tenant_id, path=khoa_tep))
        else:
            data = await _tai_anh(khoa_tep)
        ten = khoa_tep.split("?", 1)[0].split("#", 1)[0]
        goc = await _trang_dau_pdf(data) if ten.lower().endswith(".pdf") else data
        khoa = await thumbnail.sinh_va_luu(
            store, tenant_id=tenant_id, media_url=khoa_tep, content_hash="", tai_ve=lambda: goc
        )
    except TemporaryError:
        raise
    except Exception as e:  # noqa: BLE001 — thumb hỏng KHÔNG được làm đổ việc nạp
        log.warning("thumb documents#%s bỏ qua: %s: %s", record_id, type(e).__name__, e)
        return f"documents#{record_id}: không sinh được ảnh thu nhỏ ({type(e).__name__})"
    await repo.save_thumb_tai_lieu(conn, record_id=record_id, thumb_url=khoa)
    return f"documents#{record_id}: đã sinh ảnh thu nhỏ từ tệp"


async def handle_doi_co(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Đổi trạng thái hiển thị của MỌI point thuộc một dự án — KHÔNG nhúng lại gì.

    Đây là chỗ chữa cái bẫy lớn nhất của việc cho hàng nháp có point: công bố một dự án không
    đổi một chữ nội dung nào, nên dấu tay giống, nên bước so dấu tay THOÁT SỚM và payload giữ
    nguyên trạng thái cũ — công bố rồi mà agent vẫn không thấy, và mọi thứ báo thành công.

    Nhánh CÔNG BỐ phải giới hạn theo danh sách id: cột `status` per-record vẫn tồn tại và API
    vẫn đặt được, nên một lời gọi phẳng theo dự án sẽ BẬT SAI một hàng con đang nháp.
    """
    project_code = str(payload["project_code"])
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    slug = workspace_slug(tenant_id)

    trang_thai_du_an = await conn.fetchval(
        "SELECT status FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = $1",
        project_code,
    )
    if trang_thai_du_an is None:
        return JobResult(count=0, message=f"{project_code}: dự án không còn")

    if str(trang_thai_du_an) == "published":
        ids = await _id_con_published(conn, project_code)
        gia_tri, chi = {"status": "published"}, ids
    else:
        gia_tri, chi = {"status": str(trang_thai_du_an)}, None

    async with open_dependencies() as (rag, media, _store):
        counts = await asyncio.gather(
            *(
                client.set_payload(workspace_slug=slug, anchor_code=project_code, gia_tri=gia_tri, chi_record_ids=chi)
                for client in (rag, media)
            )
        )
        n = sum(counts)
    log.info("đổi cờ %s → %s: %d point", project_code, gia_tri["status"], n)
    return JobResult(count=n, message=f"{project_code}: {n} point → {gia_tri['status']}")


async def _id_con_published(conn: asyncpg.Connection, project_code: str) -> list[int]:
    """Id mọi hàng `published` thuộc một dự án, gồm cả chính hàng dự án.

    Lấy từ Postgres vì payload KHÔNG còn giữ trạng thái thô (đã bỏ — Postgres là nguồn sự thật
    để soi, xem hợp đồng payload §6).
    """
    rows = await conn.fetch(
        """
        SELECT id FROM tenant_data.projects
         WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND status = 'published'
        UNION ALL
        SELECT id FROM tenant_data.zones
         WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND status = 'published'
        UNION ALL
        SELECT id FROM tenant_data.documents
         WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND status = 'published'
        UNION ALL
        SELECT id FROM tenant_data.media
         WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND status = 'published'
        """,
        project_code,
    )
    return [int(r["id"]) for r in rows]


async def handle_doi_nhan(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Đổi TÊN dự án trong payload của mọi point thuộc dự án — KHÔNG nhúng lại gì.

    Dấu tay nội dung băm trên nội dung THUẦN (không gồm nhãn), nên đổi tên không đổi dấu tay.
    Trước 2026-08-14 tên nằm trong chuỗi được băm, nên đổi tên làm nhúng lại CẢ CÂY CON (một
    dự án có thể 116 record) trong khi nội dung không đổi một chữ.

    Tiền tố tên dự án trong `text` cũng được ghi lại — LLM đọc `text`, nên để nguyên là nó
    đọc thấy tên cũ trong thân bài trong khi tiêu đề khối đã mang tên mới.

    ĐÁNH ĐỔI ĐÃ CHẤP NHẬN: VECTOR vẫn nhúng từ chuỗi mang tên cũ tới lần nội dung thật đổi,
    nên tra cứu BM25 theo tên mới không khớp ngay. Gần như không quan trọng — đường tìm theo
    tên dự án đi qua `find_project` (tên → mã) rồi lọc theo mã, không qua BM25.
    """
    project_code = str(payload["project_code"])
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    slug = workspace_slug(tenant_id)

    ten = await conn.fetchval(
        "SELECT name FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = $1",
        project_code,
    )
    if ten is None:
        return JobResult(count=0, message=f"{project_code}: dự án không còn")

    ten_cu = str(payload.get("ten_cu", ""))

    async def _cap_nhat_mot_client(client: IndexClient) -> int:
        n = await client.set_payload(workspace_slug=slug, anchor_code=project_code, gia_tri={"project_name": str(ten)})
        if ten_cu:
            await client.doi_ten_trong_text(
                workspace_slug=slug, anchor_code=project_code, ten_cu=ten_cu, ten_moi=str(ten)
            )
        return n

    async with open_dependencies() as (rag, media, _store):
        counts = await asyncio.gather(*(_cap_nhat_mot_client(client) for client in (rag, media)))
        n = sum(counts)
    log.info("đổi nhãn %s → %r: %d point", project_code, ten, n)
    return JobResult(count=n, message=f"{project_code}: {n} point mang tên mới")


KIND_RECLAIM_CAPTION = "kb_reclaim_caption"


async def handle_caption_preview(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Mô tả cho ảnh CHƯA có hàng `media` — người dùng vừa tải tệp lên và chưa bấm Lưu.

    Caption về qua `message` (không bảng mới, không cột mới): người gọi đọc nó bằng
    `GET /media/draft-caption/{job_id}`.
    """
    media_url = str(payload["media_url"])
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))

    if str(payload.get("content_type", "image")) == "video":
        async with _mo_video() as video:
            return JobResult(count=1, message=await video.describe(media_url))

    vertical = REAL_ESTATE
    profile = profiles.caption_profile(vertical, str(payload.get("category", "")))
    caption, _ = await _caption_anh(tenant_id=tenant_id, media_url=media_url, profile=profile)
    return JobResult(count=1, message=caption)


async def handle_sync_project(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Nút "Đồng bộ tri thức". Một job mở màn xếp N job con — xem `ops/sync.py`.

    Dựng collection trước khi xếp job: từ 2026-08-18 `workspace.tao()` đã xếp
    `kb_provision` cho workspace MỚI, nhưng workspace tạo TRƯỚC mốc đó thì chưa có
    collection nào — với chúng, nút sync vẫn là đường dựng duy nhất, và thiếu bước này
    thì mọi job con của lần sync đầu nổ 404 ở `delete_by_record`. `collections.create`
    idempotent sẵn nên gọi mỗi lần sync không tốn gì.
    """
    from portal.modules.kb.ops import collections, sync

    vertical = REAL_ESTATE
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    mode = str(payload.get("mode", MODE_DELTA))
    async with open_dependencies() as (rag, media, _store):
        await collections.create(rag=rag, media=media, workspace_slug=workspace_slug(tenant_id))
    n = await sync.enqueue_project(
        conn,
        tenant_id=tenant_id,
        project_code=str(payload["project_code"]),
        vertical=vertical,
        actor=str(payload.get("actor", "sync")),
        mode=mode,
    )
    label = "toàn bộ" if mode == MODE_FULL else "phần đã đổi"
    return JobResult(count=n, message=f"đã xếp {n} mục để nạp ({label})")


async def handle_provision(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Dựng 2 collection của một workspace lúc cấp tenant. Idempotent — `ensure_collection`
    bỏ qua nếu collection đã có.

    Người xếp việc này: `workspace.service.tao()` (từ 2026-08-18) và nút «Đồng bộ tri
    thức» qua `handle_sync_project`."""
    from portal.modules.kb.ops import collections

    _ = payload
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    async with open_dependencies() as (rag, media, _store):
        await collections.create(rag=rag, media=media, workspace_slug=workspace_slug(tenant_id))
    return JobResult(count=2, message=f"đã dựng 2 collection cho {tenant_id}")


async def handle_reclaim_caption(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Thu hồi caption đã sinh ở hệ cũ từ Qdrant về Aurora.

    Chạy MỘT LẦN mỗi tenant, trước lần enrich đầu tiên: sau bước này `kb_enrich` không
    gọi VLM lại cho ảnh đã có caption. Idempotent nhờ luật chỉ-ghi-khi-rỗng của
    `repo.cache_caption`.

    QUÉT CẢ COLLECTION, không lọc theo anchor (spec §9). Point hệ cũ — đúng thứ job này
    tồn tại để thu hồi — KHÔNG có khoá `anchor_code`; khoá đó chỉ có ở point ghi từ
    2026-08-10 trở đi. Lọc theo nó thì job báo "thu hồi 0 caption" rồi `kb_enrich` gọi
    DashScope cho toàn bộ ảnh, đúng phần tiền §9 tồn tại để tiết kiệm. Collection là
    của riêng một workspace nên quét cả không đọc sang tenant khác.

    Lấy caption THẲNG từ payload mà `scroll_points` đã tải sẵn (batch 256/lần), không
    gọi `payload_of()` cho từng point: hàng trăm round-trip Qdrant tuần tự cho thông
    tin mà scroll đã có trong tay.
    """
    from portal.core.config import get_settings
    from portal.modules.kb.clients.media import collection_name
    from portal.modules.kb.index.store import QdrantStore

    _ = payload
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    cfg = get_settings()
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    ten = collection_name(workspace_slug(tenant_id))

    n = 0
    try:
        for p in await store.scroll_points(ten):
            if not p.caption:
                continue
            await repo.cache_caption(conn, record_id=p.record_id, caption=p.caption)
            n += 1
    finally:
        await store.aclose()
    return JobResult(count=n, message=f"thu hồi {n} caption về Aurora")


register(KIND_KB_FILE_INDEX, handle_kb_file_index, retries=0)
register(KIND_INDEX, handle_index, retries=RETRY_VIEC_KB, max_concurrency=LANE_INDEX)
register(KIND_DELETE, handle_delete, retries=RETRY_VIEC_KB)
register(KIND_ENRICH, handle_enrich, retries=RETRY_VIEC_KB, max_concurrency=LANE_ENRICH)
register(KIND_SYNC_PROJECT, handle_sync_project, retries=RETRY_VIEC_KB)
register(KIND_PROVISION, handle_provision, retries=RETRY_VIEC_KB)
register(KIND_RECLAIM_CAPTION, handle_reclaim_caption, retries=RETRY_VIEC_KB)
register(KIND_CAPTION_PREVIEW, handle_caption_preview, retries=RETRY_VIEC_KB)
register(KIND_CAPTION, handle_caption, retries=RETRY_CAPTION, max_concurrency=LANE_CAPTION)
register(KIND_THUMB, handle_thumb, retries=RETRY_VIEC_KB, max_concurrency=LANE_THUMB)
register(KIND_DOI_CO, handle_doi_co, retries=RETRY_VIEC_KB)
register(KIND_DOI_NHAN, handle_doi_nhan, retries=RETRY_VIEC_KB)
