"""Handler job của kho tri thức — worker nạp file này qua `load_handlers()`.

Bốn loại việc:
  kb_index        {entity, id, force?}  — trigger xếp khi bảng nguồn đổi (và reindex_all)
  kb_delete       {entity, id}          — trigger xếp khi hàng gốc bị xoá
  kb_file_index   {file_id}             — upload / nạp lại một «Tài liệu tra cứu»
  kb_reindex_all  {force?}              — xếp kb_index cho MỌI bản ghi của mọi entity
"""

import json
import logging

import asyncpg

from portal.core.jobs import JobResult, current_job, register
from portal.modules.kb import deps, files_repo, index_state, records, service
from portal.modules.kb.contracts import (
    ENTITIES,
    KIND_DELETE,
    KIND_INDEX,
    KIND_KB_FILE_INDEX,
    KIND_REINDEX_ALL,
    LANE_INDEX,
    RETRY_VIEC_KB,
    SYSTEM_ERROR_MESSAGE,
)

log = logging.getLogger(__name__)


def _doc_payload(payload: dict) -> tuple[str, int]:
    entity = str(payload["entity"])
    if entity not in ENTITIES:
        raise ValueError(f"entity lạ trong payload: {entity!r}")
    return entity, int(payload["id"])


async def _ghi_loi_ngoai_giao_dich(entity: str, record_id: int, exc: BaseException) -> None:
    """Ghi `error` vào sổ bằng kết nối RIÊNG: handler ném ⇒ giao dịch của nó rollback, ghi
    bằng `conn` của handler là mất luôn dấu vết — `/kb/status` không bao giờ thấy lỗi."""
    job = current_job()
    if job is None:
        return
    try:
        async with job.pool.acquire() as c:
            await index_state.ghi(
                c, entity=entity, record_id=record_id, state="error", error=f"{type(exc).__name__}: {exc}"
            )
    except Exception:  # noqa: BLE001 — không được che lỗi gốc
        log.warning("không ghi được lỗi vào kb_index_state cho %s#%s", entity, record_id, exc_info=True)


async def handle_index(conn: asyncpg.Connection, payload: dict) -> JobResult:
    entity, record_id = _doc_payload(payload)
    try:
        async with deps.open_clients(deps.object_store()) as (rag, media):
            msg = await service.index_record(
                conn, entity=entity, record_id=record_id, rag=rag, media=media, force=bool(payload.get("force"))
            )
    except Exception as e:
        await _ghi_loi_ngoai_giao_dich(entity, record_id, e)
        raise
    return JobResult(count=0 if "bỏ qua" in msg else 1, message=msg)


async def handle_delete(conn: asyncpg.Connection, payload: dict) -> JobResult:
    entity, record_id = _doc_payload(payload)
    async with deps.open_clients(deps.object_store()) as (rag, media):
        msg = await service.delete_record(conn, entity=entity, record_id=record_id, rag=rag, media=media)
    return JobResult(count=1, message=msg)


async def handle_kb_file_index(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """BẮT RỘNG có chủ ý: hàng treo `processing` vĩnh viễn (spinner quay mãi) là chế độ hỏng
    tệ nhất, nên MỌI thất bại kết thúc ở `error`. Phần nạp chạy trong SAVEPOINT để lỗi Postgres
    giữa chừng không đầu độc giao dịch ngoài — không có nó, cú UPDATE `error` cũng nổ.
    Retry lỗi mạng thoáng qua đã nằm trong EmbedClient; đăng ký retries=0."""
    file_id = int(payload["file_id"])
    try:
        objects = deps.object_store()
        async with conn.transaction(), deps.open_clients(objects) as (rag, _media):
            msg = await service.index_kb_file(conn, file_id=file_id, rag=rag, objects=objects)
        return JobResult(count=0 if "bỏ qua" in msg or "lỗi" in msg else 1, message=msg)
    except Exception as e:  # noqa: BLE001 — xem docstring
        log.warning("kb_file_index #%s: %s: %s", file_id, type(e).__name__, e)
        await files_repo.danh_dau_loi(conn, file_id=file_id, message=SYSTEM_ERROR_MESSAGE)
        return JobResult(count=0, message=f"kb_files#{file_id}: {type(e).__name__}: {e}")


async def handle_reindex_all(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Xếp kb_index cho mọi bản ghi — kể cả bản ghi chỉ còn trong sổ (đã xoá khỏi DB mà point
    còn sót): handler gặp "không còn" sẽ xoá, nên một lượt reindex cũng là một lượt dọn rác.

    `force` = bỏ qua so hash — dùng khi collection Qdrant bị xoá/dựng lại, lúc sổ nói
    "đã nạp" mà kho thật trống. `enqueue_once` chống trùng với việc đang chờ sẵn."""
    them = {"force": True} if payload.get("force") else {}
    tong = 0
    for entity in ENTITIES:
        bang = records.SOURCE_TABLES[entity]
        tong += await conn.fetchval(
            f"""SELECT count(shop.enqueue_once($1, 'reindex',
                                               jsonb_build_object('entity', $2::text, 'id', id) || $3::jsonb))
                  FROM (SELECT id FROM shop.{bang}
                        UNION SELECT record_id FROM shop.kb_index_state WHERE entity = $2 AND state <> 'deleted') x""",
            KIND_INDEX,
            entity,
            json.dumps(them),
        )
    return JobResult(count=tong, message=f"đã xếp {tong} việc kb_index")


register(KIND_INDEX, handle_index, retries=RETRY_VIEC_KB, max_concurrency=LANE_INDEX)
register(KIND_DELETE, handle_delete, retries=RETRY_VIEC_KB, max_concurrency=LANE_INDEX)
register(KIND_KB_FILE_INDEX, handle_kb_file_index, retries=0, max_concurrency=2, stuck_minutes=30)
register(KIND_REINDEX_ALL, handle_reindex_all)
