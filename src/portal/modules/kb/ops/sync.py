"""Cascade theo một dự án.

Gọi TỪ WORKER của job `kb_sync_project`, không gọi từ router — một dự án 20 phân khu +
96 media là 116 lần INSERT, và giao dịch của request không được ngồi chờ chuyện đó.
"""

import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.contracts import KIND_CAPTION, KIND_INDEX, MODE_DELTA, VerticalSpec
from portal.modules.kb.source import reader


async def enqueue_project(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    project_code: str,
    vertical: VerticalSpec,
    actor: str,
    mode: str = MODE_DELTA,
) -> int:
    count = 0

    async def _enqueue_one(entity: str, record_id: int, doc_type: str = "") -> None:
        nonlocal count
        await enqueue(
            conn,
            tenant_id=tenant_id,
            kind=KIND_INDEX,
            actor=actor,
            payload={
                "vertical": vertical.key,
                "entity": entity,
                "doc_type": doc_type,
                "record_id": record_id,
                "project_code": project_code,
                "mode": mode,
                "op": "upsert",
            },
        )
        count += 1

    for spec in vertical.embed_sources:
        record_ids = await reader.list_ban_ghi_theo_anchor(conn, vertical=vertical, spec=spec, anchor_code=project_code)
        for record_id in record_ids:
            await _enqueue_one(spec.table, record_id, spec.doc_type)

    chua_mo_ta = await _anh_chua_mo_ta(conn, project_code)
    for record_id in await reader.list_media_theo_anchor(conn, vertical=vertical, anchor_code=project_code):
        if record_id in chua_mo_ta:
            await enqueue(
                conn,
                tenant_id=tenant_id,
                kind=KIND_CAPTION,
                actor=actor,
                payload={
                    "vertical": vertical.key,
                    "record_id": record_id,
                    "project_code": project_code,
                    "actor": actor,
                },
            )
            count += 1
            continue
        await _enqueue_one("media", record_id)

    count += await _mo_chuoi_boc_chu(conn, tenant_id=tenant_id, project_code=project_code, actor=actor)
    return count


_CAU_CHUA_BOC = """SELECT id FROM tenant_data.documents
                    WHERE tenant_id = portal.current_tenant()
                      AND project_code = $1
                      AND coalesce(file_url, '') <> ''
                      AND coalesce(body, '') = ''
                      AND coalesce(body_auto, '') = ''
                    ORDER BY id"""
"""`body_auto` cũng phải rỗng: thiếu vế đó thì mỗi lần bấm đồng bộ lại mở chuỗi bóc chữ
cho tài liệu ta ĐÃ bóc rồi — chữ nằm ở `body_auto` chứ không `body` với bản ghi của cổng
nạp (migration `0937`), nên chỉ nhìn `body` là không bao giờ thấy nó."""


async def _mo_chuoi_boc_chu(conn: asyncpg.Connection, *, tenant_id: str, project_code: str, actor: str) -> int:
    from portal.modules.kb.ops.enqueue import dat_viec_thumb

    n = 0
    for r in await conn.fetch(_CAU_CHUA_BOC, project_code):
        job_id = await dat_viec_thumb(
            conn,
            tenant_id=tenant_id,
            actor=actor,
            entity="documents",
            record_id=int(r["id"]),
            project_code=project_code,
        )
        if job_id is not None:
            n += 1
    return n


_CAU_ANH_CHUA_MO_TA = """SELECT id FROM tenant_data.media
                          WHERE tenant_id = portal.current_tenant()
                            AND project_code = $1
                            AND content_type = 'image'
                            AND caption = '' AND caption_auto = ''"""


async def _anh_chua_mo_ta(conn: asyncpg.Connection, project_code: str) -> set[int]:
    """Id các ảnh chưa có mô tả nào — của khách lẫn của máy.

    MỘT câu cho cả dự án thay vì hỏi từng ảnh: vòng lặp gọi ngay dưới chạy trên tới hàng
    trăm media, và một round-trip mỗi ảnh chỉ để hỏi "đã mô tả chưa" là chỗ dễ thấy nhất
    để một lần bấm đồng bộ hoá thành một phút chờ.
    """
    return {int(r["id"]) for r in await conn.fetch(_CAU_ANH_CHUA_MO_TA, project_code)}
