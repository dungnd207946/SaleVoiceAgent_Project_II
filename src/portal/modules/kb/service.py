"""Điều phối một job ingest — chỗ duy nhất biết thứ tự các bước.

Nhận `conn` đã ở trong tenant_conn() và nhận client qua tham số, nên test được bằng
fake.py. Thứ tự là hợp đồng: đọc → không đủ điều kiện thì xoá → resolve → presign → gọi
service → ghi lại. Đảo "ghi lại" lên trước là ghi "đã index" cho thứ chưa lên Qdrant.
"""

import dataclasses
import logging

import asyncpg

from portal.modules.kb import files_repo, settings
from portal.modules.kb.clients import external_images
from portal.modules.kb.clients.extract import TextExtractor
from portal.modules.kb.contracts import (
    DOC_TYPE_KB_FILE,
    MD_EMPTY_MESSAGE,
    MODE_DELTA,
    MODE_FULL,
    ChunkSpec,
    IndexClient,
    IndexResult,
    MediaDirective,
    NoiDungDoanOut,
    ObjectStore,
    TextDirective,
    VerticalSpec,
)
from portal.modules.kb.directive import profiles, resolve
from portal.modules.kb.index.store import QdrantStore, point_id_of, tach_tien_to
from portal.modules.kb.source import reader
from portal.modules.kb.state import repo
from portal.modules.kb.storage import object_store

log = logging.getLogger(__name__)


async def _can_skip(
    conn: asyncpg.Connection,
    *,
    mode: str,
    entity: str,
    record_id: int,
    doc_type: str,
    new_hash: str,
) -> str | None:
    """Đòi `state == 'indexed'`: record từng lỗi có hash trùng vẫn phải nạp lại —
    hash trùng nói nội dung không đổi, không nói point đã lên Qdrant."""
    if mode != MODE_DELTA or not new_hash:
        return None
    saved = await repo.saved_hash(conn, entity=entity, record_id=record_id, doc_type=doc_type)
    if saved is None:
        return None
    old_hash, state = saved
    return old_hash if state == "indexed" and old_hash == new_hash else None


async def index_text(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    slug: str,
    vertical: VerticalSpec,
    entity: str,
    doc_type: str,
    record_id: int,
    rag: IndexClient,
    store: ObjectStore,
    mode: str = MODE_FULL,
) -> IndexResult | None:
    """Pipeline A (§7.1). None = record không đủ điều kiện → caller chuyển sang xoá."""
    spec = resolve.source_for(vertical, entity, doc_type)
    row = await reader.read_record(conn, vertical=vertical, spec=spec, record_id=record_id)
    if row is None:
        return None

    source_file_url = None
    extract = profiles.extract_profile(
        vertical,
        body=str(row.get("body") or ""),
        file_url=row.get("file_url"),
    )
    if extract is not None:
        tep = str(row["file_url"])
        source_file_url = (
            await object_store.presigned_if_internal(
                store, tenant_id=tenant_id, url_or_key=tep, ttl_sec=settings.PRESIGN_TTL_SEC
            )
            or tep
        )

    directive = resolve.resolve_text(
        workspace_slug=slug,
        row=row,
        anchor_name=str(row.get("anchor_name") or ""),
        spec=spec,
        source_file_url=source_file_url,
        extract_profile=extract,
    )
    # SOI ẢNH TRƯỚC KHI BĂM. `_can_skip` so `content_hash_of(directive)` với dấu tay đã
    # lưu, mà dấu tay lưu lần trước tính trên text ĐÃ soi — soi sau phép so là hai lần
    # băm hai chuỗi khác nhau, và tài liệu được nhúng lại ở MỌI lượt mà không ai thấy.
    new_text, image_warnings = await external_images.mirror_images(directive.text, tenant_id=tenant_id, store=store)
    for c in image_warnings:
        log.warning("soi ảnh %s#%s: %s", entity, record_id, c)
    directive = dataclasses.replace(directive, text=new_text, images_mirrored=True)

    old_hash = await _can_skip(
        conn,
        mode=mode,
        entity=entity,
        record_id=record_id,
        doc_type=directive.doc_type,
        new_hash=rag.content_hash_of(directive),
    )
    if old_hash is not None:
        await repo.mark_skipped(conn, entity=entity, record_id=record_id, doc_type=directive.doc_type)
        return IndexResult(points_upserted=0, content_hash=old_hash, skipped=True)

    await repo.save_state(
        conn,
        entity=entity,
        record_id=record_id,
        doc_type=directive.doc_type,
        target="documents",
        state="indexing",
        project_code=directive.anchor_code,
    )
    result = await rag.index(directive)

    if result.extracted_text:
        await repo.cache_extracted_text(conn, record_id=record_id, text=result.extracted_text)
    await repo.save_state(
        conn,
        entity=entity,
        record_id=record_id,
        doc_type=directive.doc_type,
        target="documents",
        state="indexed",
        result=result,
        project_code=directive.anchor_code,
    )
    return result


async def index_media(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    slug: str,
    vertical: VerticalSpec,
    record_id: int,
    media: IndexClient,
    store: ObjectStore,
    mode: str = MODE_FULL,
) -> IndexResult | None:
    """Pipeline B (§7.2). Hai nhánh file: S3 (presign) và URL ngoài (file_url=None)."""
    row = await reader.read_media(conn, vertical=vertical, record_id=record_id)
    if row is None:
        return None

    if not profiles.should_index_media(vertical, str(row["category"])):
        await repo.save_state(
            conn,
            entity="media",
            record_id=record_id,
            doc_type="",
            target="media",
            state="deleted",
            project_code=str(row[vertical.media_anchor_col]),
        )
        return None

    media_url = str(row["media_url"])
    file_url = await object_store.presigned_if_internal(
        store, tenant_id=tenant_id, url_or_key=media_url, ttl_sec=settings.PRESIGN_TTL_SEC
    )

    directive: MediaDirective = profiles.resolve_media(
        workspace_slug=slug,
        row=row,
        vertical=vertical,
        file_url=file_url,
    )
    old_hash = await _can_skip(
        conn,
        mode=mode,
        entity="media",
        record_id=record_id,
        doc_type="",
        new_hash=media.content_hash_of(directive),
    )
    if old_hash is not None:
        await repo.mark_skipped(conn, entity="media", record_id=record_id, doc_type="")
        return IndexResult(points_upserted=0, content_hash=old_hash, skipped=True)

    await repo.save_state(
        conn,
        entity="media",
        record_id=record_id,
        doc_type="",
        target="media",
        state="indexing",
        project_code=directive.anchor_code,
    )
    result = await media.index(directive)

    if result.caption:
        await repo.cache_caption(conn, record_id=record_id, caption=result.caption)
    await repo.save_thumb_and_hash(
        conn,
        record_id=record_id,
        thumb_url=directive.thumb_url or "",
        content_hash=result.content_hash,
    )
    await repo.save_state(
        conn,
        entity="media",
        record_id=record_id,
        doc_type="",
        target="media",
        state="indexed",
        result=result,
        project_code=directive.anchor_code,
    )
    return result


async def delete_index(
    conn: asyncpg.Connection,
    *,
    slug: str,
    entity: str,
    record_id: int,
    rag: IndexClient,
    media: IndexClient,
    doc_type: str = "",
) -> None:
    """Xoá point của một record. Cascade cây con là việc của delete_cascade().

    `doc_type=""` nghĩa là caller KHÔNG BIẾT — row có thể đã bị xoá nên không suy
    được loại từ nội dung. Sổ `kb_index_state` là nguồn duy nhất còn lại, và một
    record có thể có nhiều dòng (documents đổi loại vài lần).

    Sổ RỖNG thì không xoá gì: không dòng nào nghĩa là record chưa từng được index.
    Nhánh cũ rơi về `doc_type=""`, và ở `<slug>_documents` vị từ duy nhất còn lại là
    `record_id` — nó cuốn theo point của `projects`/`zones` cùng số id (ba bảng, ba
    sequence riêng). `entity` đi kèm mọi lời gọi để nhánh nào cũng có vị từ thứ hai.
    """
    client = media if entity == "media" else rag
    if doc_type or entity == "media":
        doc_types = [doc_type]
    else:
        rows = await repo.read_state(conn, entity=entity, record_id=record_id)
        doc_types = [str(r["doc_type"]) for r in rows]
    for dt in doc_types:
        await client.delete(workspace_slug=slug, record_id=record_id, doc_type=dt, entity=entity)
    await repo.mark_deleted(conn, entity=entity, record_id=record_id, doc_types=doc_types)


async def delete_cascade(
    conn: asyncpg.Connection,
    *,
    slug: str,
    anchor_code: str,
    rag: IndexClient,
    media: IndexClient,
) -> int:
    """Đọc SỔ, không đọc bảng nguồn: FK `projects → con` là ON DELETE CASCADE nên
    khi worker chạy tới đây row con đã biến mất và câu liệt kê trả rỗng."""
    rows = await repo.indexed_of_project(conn, project_code=anchor_code)
    for r in rows:
        entity, record_id, doc_type = str(r["entity"]), int(r["record_id"]), str(r["doc_type"])
        client = media if entity == "media" else rag
        await client.delete(workspace_slug=slug, record_id=record_id, doc_type=doc_type, entity=entity)
        await repo.mark_deleted(conn, entity=entity, record_id=record_id, doc_types=[doc_type])
    log.info("cascade %s: xoá %d mục", anchor_code, len(rows))
    return len(rows)


THONG_DIEP_KHONG_CO_CHU = (
    "Không bóc được chữ từ tệp này — PDF dạng scan chưa hỗ trợ ở kho Tài liệu tra cứu. "
    "Tải bản có lớp chữ, hoặc nạp vào tài liệu của một dự án để đi qua luồng duyệt OCR."
)


async def index_kb_file(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    slug: str,
    record_id: int,
    rag: IndexClient,
    media: IndexClient,
    store: ObjectStore,
) -> str:
    """Nạp MỘT tệp của kho «Tài liệu tra cứu» (spec 2026-08-20 §4).

    Thứ tự là lời hứa — đánh dấu `san_sang` SAU CÙNG: hỏng ở bước nào trước đó thì
    hàng ở `dang_xu_ly`/`loi`, và BR06 nói chỉ hàng `san_sang` là đã lên Qdrant.

    Lỗi NỘI DUNG (không có lớp chữ) tự đánh dấu `loi` tại đây — người dùng sửa được.
    Lỗi HẠ TẦNG (S3/embed/Qdrant) NÉM lên cho handler đánh dấu — phân loại ở một chỗ.

    KHÔNG ghi `kb_index_state`: kb_files là sổ duy nhất (spec §5 — CHECK entity của
    sổ kia không nhận 'kb_files', và vị từ xoá là hằng doc_type nên không cần tra).

    KHÔNG truyền VLM: màn /kb không có UI duyệt, và «model sinh ⇒ người xem» —
    chữ OCR không được tự nạp (KB_01 §I.2 loại trừ scan từ đầu).
    """
    from portal.modules.kb.ops import collections

    row = await files_repo.doc(conn, record_id)
    if row is None:
        return f"kb_files#{record_id}: hàng không còn, bỏ qua"

    # Idempotent — upload có thể là hành động KB đầu tiên của workspace; thiếu bước
    # này job nổ 404 ở delete_by_record (bài học handle_sync_project).
    await collections.create(rag=rag, media=media, workspace_slug=slug)

    data = await store.doc(key=store.key(tenant_id=tenant_id, path=row.s3_key))
    ra = await TextExtractor(vlm=None).extract(data, filename=row.ten_file)
    if not ra.text:
        message = MD_EMPTY_MESSAGE if row.loai == "md" else THONG_DIEP_KHONG_CO_CHU
        await files_repo.danh_dau_loi(conn, record_id=record_id, loi_message=message)
        return f"kb_files#{record_id}: không có nội dung, đã đánh dấu lỗi"

    new_text, image_warnings = await external_images.mirror_images(ra.text, tenant_id=tenant_id, store=store)
    for c in image_warnings:
        log.warning("soi ảnh kb_files#%s: %s", record_id, c)

    directive = TextDirective(
        workspace_slug=slug,
        record_id=record_id,
        doc_type=DOC_TYPE_KB_FILE,
        anchor_code=settings.SYSTEM_ANCHOR,
        anchor_name=row.ten_file,
        section="",
        text=new_text,
        chunk=ChunkSpec(),
        status="published",
        anchor_status="published",
        updated_at=row.uploaded_at,
        file_url=row.s3_key,
        file_name=row.ten_file,
        images_mirrored=True,
    )
    result = await rag.index(directive)
    if not await files_repo.danh_dau_san_sang(conn, record_id=record_id, chunk_count=result.points_upserted):
        # Hàng bị xoá giữa lúc nạp (race với DELETE) — gỡ ngay point vừa ghi.
        await rag.delete(workspace_slug=slug, record_id=record_id, doc_type=DOC_TYPE_KB_FILE)
        return f"kb_files#{record_id}: hàng bị xoá giữa lúc nạp — đã gỡ point, bỏ qua"
    # ⚠️ Đây là một NẠP THÀNH CÔNG, chỉ kèm cảnh báo — hậu tố KHÔNG ĐƯỢC chứa "lỗi"
    # hay "bỏ qua": handle_kb_file_index (jobs.py) phân loại count bằng cách dò hai
    # từ đó TRONG CHÍNH message này, nên một hậu tố vô tình khớp sẽ biến một lượt nạp
    # tốt thành count=0, không phân biệt được với "không làm gì cả" trên `control.jobs`.
    ext = f" · {len(image_warnings)} ảnh không tải được" if image_warnings else ""
    return f"kb_files#{record_id}: +{result.points_upserted} point{ext}"


_OVERLAP_MIN_CHARS = 6
"""Khớp ngắn hơn mức này bỏ qua — có thể là trùng ngẫu nhiên (một từ ngắn, dấu câu)
chứ không phải phần chunker mượn lại."""
_OVERLAP_MAX_CHARS = 200
"""Trần tìm kiếm — overlap thật của chunker (`ChunkSpec.overlap`) và dòng mượn trước
ảnh (`_muon_cau_dan`) đều không vượt mức này; tìm xa hơn chỉ tốn công vô ích."""


def overlap_with_previous(prev_text: str, text: str) -> bool:
    """`True` nếu `text` mở đầu bằng đúng phần đuôi của `prev_text` — dấu hiệu chunker
    đã mượn lại nội dung qua ranh giới (xem `contracts.NoiDungDoanOut.overlapsPrev`)."""
    cap = min(len(prev_text), len(text), _OVERLAP_MAX_CHARS)
    return any(prev_text[-n:] == text[:n] for n in range(cap, _OVERLAP_MIN_CHARS - 1, -1))


def _tach_doan(text: str, ten_file: str) -> tuple[str, str]:
    """Ngược lại `rag._text_payload`: bóc tiền tố `"<ten_file>[ — <mục>]"` ra khỏi
    `payload["text"]`, trả `(text thuần, section)`. Tiền tố lệch `ten_file` (không nên
    xảy ra — tên tệp bất biến sau khi upload) thì trả nguyên văn, section rỗng."""
    tach = tach_tien_to(text, ten_file)
    if tach is None:
        return text, ""
    head, body = tach
    sep = " — "
    section = head[len(ten_file) + len(sep) :] if head.startswith(ten_file + sep) else ""
    return body, section


async def noi_dung_da_nap(
    store: QdrantStore, *, collection: str, file_id: int, ten_file: str, chunk_count: int
) -> list[NoiDungDoanOut]:
    """Dựng lại bản ĐÃ NẠP của một `kb_files` (spec Task 15) — thứ agent thật sự đọc,
    KHÔNG phải tệp gốc (ảnh trong payload đã là URL của mình, tệp gốc thì không).

    Payload Qdrant không mang số thứ tự đoạn nên không `scroll` rồi sắp — dựng lại
    ĐÚNG id bằng `point_id_of` cho từng `idx` rồi lấy MỘT LƯỢT. `chunk_count` có thể
    lệch DB, point thiếu thì bỏ qua chứ không ném (34/35 đoạn còn hơn một màn lỗi).
    """
    if chunk_count <= 0:
        return []
    ids = [point_id_of(DOC_TYPE_KB_FILE, file_id, i) for i in range(chunk_count)]
    payloads = await store.payload_many(collection, ids)
    ra: list[NoiDungDoanOut] = []
    for idx, point_id in enumerate(ids):
        pl = payloads.get(point_id)
        if pl is None:
            continue
        text, section = _tach_doan(str(pl.get("text") or ""), ten_file)
        trung = bool(ra) and overlap_with_previous(ra[-1].text, text)
        ra.append(NoiDungDoanOut(idx=idx, text=text, sectionPath=section, overlapsPrev=trung))
    return ra
