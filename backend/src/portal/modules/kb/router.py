"""Kho tri thức: «Tài liệu tra cứu» (`/kb/files`), trạng thái + nạp lại toàn bộ (`/kb/status`,
`/kb/reindex`), và đường phát tệp công khai (`/public/files/...`).

⚠️ Route quản trị đang MỞ (chưa có đăng nhập admin) — chỉ chạy ở dev.
"""

import hashlib
import logging
import re
import unicodedata
from typing import Annotated, Literal

import asyncpg
from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from portal.api.loi import LoiPortal, du_lieu_khong_hop_le, khong_tim_thay
from portal.core.crud import LIMIT_MAC_DINH, Limit, Offset, Trang
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.core.jobs import enqueue
from portal.modules.kb import deps, files_repo, service, settings
from portal.modules.kb.contracts import (
    DOC_TYPE_KB_FILE,
    KIND_KB_FILE_INDEX,
    KIND_REINDEX_ALL,
    KINDS,
    LOAI_HO_TRO,
    ChunkOut,
    DemEntityOut,
    DemJobOut,
    DemOut,
    KbFileOut,
    KbStatusOut,
    ReindexOut,
)

log = logging.getLogger(__name__)

ROUTER = APIRouter()

PUBLIC_PREFIXES: tuple[str, ...] = (settings.IMAGES_PREFIX, "media/")
"""Thư mục được phát CÔNG KHAI (agent gửi link cho khách, không có phiên): ảnh đã kéo về
kho (`kb/anh/`, gồm thumb) và ảnh sản phẩm (`media/`). Tài liệu gốc (`kb/files/`) RIÊNG TƯ
có chủ ý — mở thêm thư mục nào thì khai tường minh ở đây, đừng đổi thành `kb/` trần."""

_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "mp4": "video/mp4",
    "pdf": "application/pdf",
}
_MIME_UPLOAD = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown; charset=utf-8",
}

FileState = Literal["processing", "ready", "error"]


def _khong_co_tep() -> LoiPortal:
    return LoiPortal("NOT_FOUND", 404, "Không tìm thấy tệp")


def _ten_lanh(ten: str) -> str:
    """Tên trong KHOÁ rút về ASCII lành — khoá là định danh, tên hiển thị nằm ở `file_name`.
    Unicode/khoảng trắng trong khoá bắt mọi chỗ đọc gánh encoding, và đó là chỗ lệch âm thầm."""
    mo = unicodedata.normalize("NFKD", ten.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
    mo = re.sub(r"[^A-Za-z0-9._-]+", "-", mo).strip("-.")
    return mo[:120] or "tep"


def _out(r: asyncpg.Record) -> KbFileOut:
    return KbFileOut.model_validate(dict(r))


async def _lay_tep(conn: asyncpg.Connection, file_id: int) -> asyncpg.Record:
    r = await files_repo.lay(conn, file_id)
    if r is None:
        raise khong_tim_thay("tài liệu", file_id)
    return r


# ─── «Tài liệu tra cứu» ─────────────────────────────────────────────────────────


@ROUTER.get("/kb/files", response_model=Trang[KbFileOut])
async def liet_ke_tep(
    state: FileState | None = None,
    product_id: Annotated[int | None, Query(alias="productId")] = None,
    brand_id: Annotated[int | None, Query(alias="brandId")] = None,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    pool: asyncpg.Pool = Depends(get_pool),
) -> Trang[KbFileOut]:
    dk: list[str] = []
    ts: list[object] = []
    for cot, gt in (("state", state), ("product_id", product_id), ("brand_id", brand_id)):
        if gt is not None:
            ts.append(gt)
            dk.append(f"{cot} = ${len(ts)}")
    async with tx(pool) as conn:
        rows, total = await files_repo.liet_ke(conn, dieu_kien=dk, tham_so=ts, limit=limit, offset=offset)
    return Trang[KbFileOut](items=[_out(r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.post("/kb/files", status_code=status.HTTP_202_ACCEPTED, response_model=KbFileOut)
async def tai_len(
    file: Annotated[UploadFile, File()],
    product_id: Annotated[int | None, Form(alias="productId")] = None,
    brand_id: Annotated[int | None, Form(alias="brandId")] = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> KbFileOut:
    """202 — bóc chữ + nhúng chạy NỀN qua job `kb_file_index`; đợi xong mới trả thì tệp lớn
    làm request timeout trước khi job kịp xong."""
    ten = file.filename or ""
    loai = ten.rsplit(".", 1)[-1].lower() if "." in ten else ""
    if loai not in LOAI_HO_TRO:
        raise LoiPortal("UNSUPPORTED_TYPE", 422, "Chỉ nhận tệp PDF, DOCX, XLSX hoặc Markdown (.md)")
    noi_dung = await file.read()
    if not noi_dung:
        raise LoiPortal("EMPTY_FILE", 422, "Tệp rỗng — không có gì để nạp")
    tran_mb = settings.get_env().file_max_mb
    if len(noi_dung) > tran_mb * 1024 * 1024:
        raise LoiPortal("FILE_TOO_LARGE", 422, f"Tệp vượt dung lượng cho phép ({tran_mb} MB)")

    sha = hashlib.sha256(noi_dung).hexdigest()
    objects = deps.object_store()
    key = objects.key(path=f"{settings.FILES_PREFIX}{sha}/{_ten_lanh(ten)}")

    # Kiểm TRƯỚC khi lên kho: lỗi sau khi đã `put` là để lại object không hàng nào trỏ tới.
    async with tx(pool) as conn:
        if product_id is not None and not await conn.fetchval("SELECT 1 FROM shop.products WHERE id = $1", product_id):
            raise du_lieu_khong_hop_le(f"Không có sản phẩm #{product_id}")
        if brand_id is not None and not await conn.fetchval("SELECT 1 FROM shop.brands WHERE id = $1", brand_id):
            raise du_lieu_khong_hop_le(f"Không có hãng #{brand_id}")
        if (trung := await files_repo.co_khoa(conn, key)) is not None:
            raise LoiPortal("DUPLICATE_FILE", 409, f"Tệp này đã được tải lên (tài liệu #{trung})")

    # Lên kho TRƯỚC khi ghi hàng: hàng trỏ tới khoá chưa tồn tại là tài liệu job không bao giờ
    # nạp được, đứng mãi ở «Đang xử lý».
    await objects.put(key=key, data=noi_dung, content_type=_MIME_UPLOAD[loai])
    async with tx(pool) as conn:
        r = await files_repo.them(
            conn,
            file_name=ten,
            s3_key=key,
            size_bytes=len(noi_dung),
            file_type=loai,
            product_id=product_id,
            brand_id=brand_id,
        )
        await enqueue(conn, kind=KIND_KB_FILE_INDEX, actor="admin", payload={"file_id": r["id"]})
    return _out(r)


@ROUTER.get("/kb/files/{file_id}", response_model=KbFileOut)
async def lay_tep(file_id: int, pool: asyncpg.Pool = Depends(get_pool)) -> KbFileOut:
    async with tx(pool) as conn:
        return _out(await _lay_tep(conn, file_id))


@ROUTER.get("/kb/files/{file_id}/content", response_model=list[ChunkOut])
async def noi_dung(file_id: int, pool: asyncpg.Pool = Depends(get_pool)) -> list[ChunkOut]:
    """Các đoạn ĐÃ NHÚNG (đọc từ Qdrant) — không phải tệp gốc. Rỗng khi chưa `ready`."""
    async with tx(pool) as conn:
        r = await _lay_tep(conn, file_id)
    if r["chunk_count"] <= 0:
        return []
    store = deps.qdrant_store()
    try:
        return await service.noi_dung_da_nap(
            store,
            collection=settings.collection_documents(),
            file_id=file_id,
            title=r["file_name"],
            chunk_count=r["chunk_count"],
        )
    finally:
        await store.aclose()


@ROUTER.post("/kb/files/{file_id}/reindex", status_code=status.HTTP_202_ACCEPTED, response_model=KbFileOut)
async def nap_lai_tep(file_id: int, pool: asyncpg.Pool = Depends(get_pool)) -> KbFileOut:
    async with tx(pool) as conn:
        r = await files_repo.dat_lai(conn, file_id)
        if r is None:
            raise khong_tim_thay("tài liệu", file_id)
        await enqueue(conn, kind=KIND_KB_FILE_INDEX, actor="admin", payload={"file_id": file_id})
    return _out(r)


@ROUTER.delete("/kb/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_tep(file_id: int, pool: asyncpg.Pool = Depends(get_pool)) -> Response:
    """Xoá HÀNG trước (commit), rồi mới dọn Qdrant + S3.

    Thứ tự này để mọi đường hỏng đều về phía an toàn: dọn ngoài hỏng thì còn rác (point/tệp
    mồ côi — log lỗi, `kb_reindex_all` không với tới nhưng không ai đọc nhầm), còn đảo lại thì
    có thể còn HÀNG trỏ vào tệp đã mất. Job đang nạp đúng tệp này: `danh_dau_san_sang` trúng
    0 hàng và job tự gỡ point vừa ghi (xem `service.index_kb_file`).
    """
    async with tx(pool) as conn:
        r = await files_repo.xoa(conn, file_id)
    if r is None:
        raise khong_tim_thay("tài liệu", file_id)

    store = deps.qdrant_store()
    try:
        await store.delete_by_record(settings.collection_documents(), record_id=file_id, doc_type=DOC_TYPE_KB_FILE)
    except Exception as e:  # noqa: BLE001 — hàng đã xoá; dọn hỏng chỉ để lại rác, phải log
        log.error("xoá point kb_file#%s hỏng — còn point mồ côi: %s: %s", file_id, type(e).__name__, e)
    finally:
        await store.aclose()
    try:
        await deps.object_store().delete(key=r["s3_key"])
    except Exception as e:  # noqa: BLE001 — như trên
        log.error("xoá tệp %s hỏng — còn tệp mồ côi: %s: %s", r["s3_key"], type(e).__name__, e)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Luồng B: trạng thái + nạp lại toàn bộ ─────────────────────────────────────


@ROUTER.post("/kb/reindex", status_code=status.HTTP_202_ACCEPTED, response_model=ReindexOut)
async def nap_lai_toan_bo(
    force: bool = Query(False, description="Bỏ qua so hash — dùng khi collection Qdrant bị dựng lại"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ReindexOut:
    async with tx(pool) as conn:
        job_id = await enqueue(conn, kind=KIND_REINDEX_ALL, actor="admin", payload={"force": force})
    return ReindexOut(job_id=job_id)


@ROUTER.get("/kb/status", response_model=KbStatusOut)
async def trang_thai(pool: asyncpg.Pool = Depends(get_pool)) -> KbStatusOut:
    async with tx(pool) as conn:
        rec = await conn.fetch(
            "SELECT entity, state, count(*)::int AS count FROM shop.kb_index_state GROUP BY 1, 2 ORDER BY 1, 2"
        )
        tep = await conn.fetch("SELECT state, count(*)::int AS count FROM shop.kb_files GROUP BY 1 ORDER BY 1")
        viec = await conn.fetch(
            """SELECT kind, state, count(*)::int AS count FROM shop.jobs
                WHERE kind = ANY($1) AND state IN ('queued', 'running', 'failed')
                GROUP BY 1, 2 ORDER BY 1, 2""",
            list(KINDS),
        )
    return KbStatusOut(
        records=[DemEntityOut.model_validate(dict(r)) for r in rec],
        files=[DemOut.model_validate(dict(r)) for r in tep],
        jobs=[DemJobOut.model_validate(dict(r)) for r in viec],
    )


# ─── Phát tệp công khai ─────────────────────────────────────────────────────────


@ROUTER.get("/public/files/{key:path}")
async def phat_tep_cong_khai(key: str) -> Response:
    """Phát ảnh cho khách cuối — URL nằm trong lịch sử chat nên phải sống lâu.

    `key` đến TỪ CLIENT: chỉ thư mục trong `PUBLIC_PREFIXES` được phát, chặn `..`. Chế độ
    `S3_REDIRECT_ENABLED` trả 307 tới URL kho có hạn (byte không chạm tiến trình API).
    """
    from portal.core.config import get_settings
    from portal.core.storage import KhongTimThay, kho_tep_dung_chung

    if ".." in key.split("/") or "\\" in key or not key.startswith(PUBLIC_PREFIXES):
        raise _khong_co_tep()
    cfg = get_settings()
    kho = kho_tep_dung_chung()
    cache = "public, max-age=31536000, immutable"
    if cfg.s3_redirect_enabled:
        url = await kho.presign_get(key, ttl_sec=cfg.s3_redirect_ttl_sec)
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Cache-Control": cache})
    try:
        noi_dung_tep = await kho.doc(key)
    except KhongTimThay as e:
        raise _khong_co_tep() from e
    duoi = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return Response(
        content=noi_dung_tep, media_type=_MIME.get(duoi, "application/octet-stream"), headers={"Cache-Control": cache}
    )
