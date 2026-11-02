"""ROUTER module kb. Đường tương đối — tiền tố /api/v1 do api/app.py gắn.

Module này chủ yếu là worker; route ở đây là kho «Tài liệu tra cứu» (`/kb/files`).
Dùng `catalog.*` chứ không tạo action mới: PQ_01 nhóm 7–8 đã gộp Dự án · Quỹ căn ·
Tài liệu · Media vào một quyền.
"""

import hashlib
import logging
import re
import unicodedata

import asyncpg
from fastapi import APIRouter, Depends, File, UploadFile

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.core.jobs import enqueue
from portal.modules.kb import files_repo, service
from portal.modules.kb.clients.rag import collection_name
from portal.modules.kb.conflicts.router import ROUTER as CONFLICTS_ROUTER
from portal.modules.kb.contracts import (
    DOC_TYPE_KB_FILE,
    KIND_KB_FILE_INDEX,
    LOAI_HO_TRO,
    NoiDungDoanOut,
    TaiLieuOut,
)
from portal.modules.kb.index.store import QdrantStore
from portal.modules.kb.jobs import object_store
from portal.modules.kb.web.router import ROUTER as WEB_ROUTER

log = logging.getLogger(__name__)

ROUTER = APIRouter()
ROUTER.include_router(WEB_ROUTER)
ROUTER.include_router(CONFLICTS_ROUTER)
"""Màn «Dữ liệu ngoài» (`/kb-web/*`) — `api/app.py::ROUTERS` chỉ gắn `router.py`, gói con tự nối vào đây."""


# ─── Kho «Tài liệu tra cứu» — 3 route của màn /kb (spec 2026-08-20) ────────────────

GIOI_HAN_BYTE = 25 * 1024 * 1024
"""⚠️ CON SỐ TẠM — KB_01 BR12 để ngưỡng dung lượng chưa chốt (đầu vào bảng giá).
Giữ nguyên 25 MB của bản M6 gốc. Đặt ở router như bản gốc, KHÔNG đưa vào
settings.py (file đó đang có sửa đổi chưa commit của phiên khác)."""

_FILE = File(...)


def _loai_khong_ho_tro() -> "loi.LoiPortal":
    return loi.LoiPortal("UNSUPPORTED_TYPE", 422, "Chỉ nhận file PDF, DOCX hoặc XLSX")


def _qua_dung_luong() -> "loi.LoiPortal":
    return loi.LoiPortal("FILE_TOO_LARGE", 422, "File vượt dung lượng cho phép (25 MB)")


def _file_rong() -> "loi.LoiPortal":
    return loi.LoiPortal("FILE_TOO_LARGE", 422, "File rỗng — không có gì để nạp")


def _khong_co_tai_lieu() -> "loi.LoiPortal":
    return loi.LoiPortal("NO_DOCUMENT", 404, "Không tìm thấy tài liệu")


def _ten_lanh(ten: str) -> str:
    """Tên tệp trong key S3 rút về ASCII lành — key là ĐỊNH DANH, không phải tên hiển thị
    (tên gốc nằm ở cột ten_file). Unicode/khoảng trắng trong key bắt mọi chỗ đọc
    (presign, public_url) gánh encoding, và đó là chỗ lệch nhau âm thầm."""
    mo = unicodedata.normalize("NFKD", ten).encode("ascii", "ignore").decode()
    mo = re.sub(r"[^A-Za-z0-9._-]+", "-", mo).strip("-.")
    return mo or "tep"


def _ra_tai_lieu(t: files_repo.HangTaiLieu) -> TaiLieuOut:
    return TaiLieuOut(
        id=t.id,
        tenFile=t.ten_file,
        loai=t.loai,
        kichThuoc=t.kich_thuoc,
        state=t.state,
        chunkCount=t.chunk_count,
        loiMessage=t.loi_message,
        uploadedAt=t.uploaded_at,
        uploadedBy=t.uploaded_by,
    )


@ROUTER.get("/kb/files", response_model=list[TaiLieuOut])
async def kb_liet_ke(
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[TaiLieuOut]:
    """Kho rỗng trả [] — đó là trạng thái bình thường của workspace mới (BR04)."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        return [_ra_tai_lieu(t) for t in await files_repo.liet_ke(conn)]


@ROUTER.post("/kb/files", status_code=202, response_model=TaiLieuOut)
async def kb_tai_len(
    file: UploadFile = _FILE,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TaiLieuOut:
    """202 — bóc chữ và nhúng chạy BẤT ĐỒNG BỘ qua job `kb_file_index`.

    Trả về sau khi index xong nghĩa là người dùng nhìn spinner vài phút cho một
    tệp lớn, và request timeout trước khi job xong (KB_01 §I.2, giữ từ bản gốc).
    """
    ten_goc = file.filename or ""
    loai_tep = ten_goc.rsplit(".", 1)[-1].lower()
    if loai_tep not in LOAI_HO_TRO:
        raise _loai_khong_ho_tro()

    noi_dung = await file.read()
    if not noi_dung:
        raise _file_rong()
    if len(noi_dung) > GIOI_HAN_BYTE:
        raise _qua_dung_luong()

    # Lên kho tệp TRƯỚC khi ghi hàng: hàng trỏ tới một s3_key không tồn tại là một
    # tài liệu job không bao giờ nạp được, và nó đứng mãi ở «Đang xử lý» (bài học 0390d86).
    sha = hashlib.sha256(noi_dung).hexdigest()
    store = object_store()
    key = store.key(tenant_id=p.tenant_id, path=f"kb/{sha}/{_ten_lanh(ten_goc)}")
    await store.put(key=key, data=noi_dung, content_type=file.content_type or "application/octet-stream")

    async with tenant_conn(pool, p.tenant_id) as conn:
        t = await files_repo.them(
            conn, ten_file=ten_goc, s3_key=key, kich_thuoc=len(noi_dung), loai=loai_tep, uploaded_by=p.user_id
        )
        await enqueue(
            conn, tenant_id=p.tenant_id, kind=KIND_KB_FILE_INDEX, actor=p.user_id, payload={"record_id": t.id}
        )
        await nhat_ky.ghi(conn, p.tenant_id, "kb.upload", p.user_id, {"file_id": t.id, "ten_file": t.ten_file})
    return _ra_tai_lieu(t)


@ROUTER.get("/kb/files/{file_id}/noi-dung", response_model=list[NoiDungDoanOut])
async def kb_noi_dung(
    file_id: int,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[NoiDungDoanOut]:
    """Bản ĐÃ NẠP của một tài liệu — spec Task 15. Hàng của tenant khác ra `None` ở
    đây (RLS lọc) nên rơi cùng nhánh 404 với id không tồn tại, không phải 403."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        t = await files_repo.doc(conn, file_id)
    if t is None:
        raise _khong_co_tai_lieu()
    if t.chunk_count <= 0:
        return []
    q = _qdrant_store()
    try:
        return await service.noi_dung_da_nap(
            q,
            collection=collection_name(p.tenant_id),
            file_id=t.id,
            ten_file=t.ten_file,
            chunk_count=t.chunk_count,
        )
    finally:
        await q.aclose()


def _qdrant_store() -> QdrantStore:
    """Xoá point KHÔNG đi qua `open_dependencies()`: bộ đó dựng cả EmbedClient (raise
    khi thiếu KB_SANTA_MODELS_TOKEN), mà xoá point không cần embed — cùng lý lẽ
    `ops/collections.xoa_kho_cua_workspace` đã ghi."""
    from portal.core.config import get_settings

    cfg = get_settings()
    return QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)


@ROUTER.delete("/kb/files/{file_id}", status_code=204)
async def kb_xoa(
    file_id: int,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    """BR07 — gỡ khỏi kho tri thức NGAY, trong cùng thao tác. Không thùng rác.

    Thứ tự: đọc/404 → xoá HÀNG (trong giao dịch CHƯA commit) → gỡ point Qdrant →
    commit → tệp S3 (best-effort). Hàng chỉ thật sự biến mất lúc commit — Qdrant
    hỏng thì rollback trả hàng lại nguyên vẹn, không để lộ trạng thái nửa-xoá.

    Xoá hàng TRƯỚC (dù chưa commit) đóng race với worker `kb_file_index`: `DELETE`
    và `UPDATE ... danh_dau_san_sang` của worker cùng khoá một hàng, Postgres tự
    serialize hai giao dịch. Worker khoá trước ⇒ route đợi tới khi worker commit
    xong rồi mới xoá, point đã lên Qdrant thì route gỡ được ngay. Route khoá trước
    ⇒ worker bị chặn tới khi route commit; `danh_dau_san_sang` khi đó UPDATE trúng
    0 hàng, trả `False`, và worker tự gỡ point nó vừa ghi (xem `service.index_kb_file`).
    Mọi interleaving vì thế rơi vào một trong hai nhánh sạch — không còn cửa sổ vài
    giây của thao tác "upload rồi xoá ngay" để lại point mồ côi.

    Đánh đổi: crash ĐÚNG giữa lúc gỡ Qdrant và lúc commit để lại hàng còn `san_sang`
    nhưng đã mất point (giao dịch DB rollback do crash, point Qdrant thì không có gì
    hoàn tác) — hiếm, và tự chữa: bấm Xoá lại là `delete_by_record` gặp point đã mất
    (trả 0 êm) rồi xoá nốt hàng.
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        t = await files_repo.doc(conn, file_id)
        if t is None:
            raise _khong_co_tai_lieu()

        await files_repo.xoa(conn, file_id)

        q = _qdrant_store()
        try:
            await q.delete_by_record(collection_name(p.tenant_id), record_id=file_id, doc_type=DOC_TYPE_KB_FILE)
        finally:
            await q.aclose()

        try:
            await object_store().delete(key=t.s3_key)
        except Exception as e:  # noqa: BLE001 — best-effort, xem docstring
            log.warning("xoá tệp S3 %s bỏ qua: %s: %s", t.s3_key, type(e).__name__, e)
        await nhat_ky.ghi(conn, p.tenant_id, "kb.delete", p.user_id, {"file_id": file_id, "ten_file": t.ten_file})
