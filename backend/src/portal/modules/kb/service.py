"""Điều phối một lượt nạp — chỗ duy nhất biết thứ tự các bước.

Nhận `conn` (đã trong giao dịch) và client qua tham số, nên test thay được bằng fake.
Thứ tự là hợp đồng: đọc → không còn/không hiển thị thì XOÁ → so hash → nhúng → GHI SỔ
SAU CÙNG. Ghi sổ trước là ghi "đã nạp" cho thứ chưa lên Qdrant.
"""

import logging

import asyncpg

from portal.modules.kb import files_repo, index_state, records
from portal.modules.kb.clients import external_images
from portal.modules.kb.clients.extract import TextExtractor
from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.clients.rag import RagClient
from portal.modules.kb.contracts import (
    DOC_TYPE_KB_FILE,
    ENTITY_MEDIA,
    KIND_INDEX,
    MD_EMPTY_MESSAGE,
    NO_TEXT_MESSAGE,
    ChunkOut,
    DocMeta,
    MediaDoc,
    ObjectStore,
    TextDoc,
)
from portal.modules.kb.index.store import QdrantStore, point_id_of, tach_tien_to

log = logging.getLogger(__name__)

# Sản phẩm đổi tên/thông số ⇒ ảnh, FAQ, bài viết của nó mang tên cũ trong text. Trigger chỉ
# báo cho chính sản phẩm, nên lan sang ở đây — và CHỈ khi sản phẩm thật sự nạp lại (đổi giá
# thì hash không đổi, không lan). Con cũng tự bỏ qua nếu văn bản của nó không đổi.
_CON_CUA_SAN_PHAM = """
SELECT count(shop.enqueue_once($2, 'kb', jsonb_build_object('entity', e, 'id', id)))
  FROM (SELECT 'product_media' AS e, id FROM shop.product_media WHERE product_id = $1
        UNION ALL SELECT 'faq', id FROM shop.faqs WHERE product_id = $1
        UNION ALL SELECT 'article', article_id FROM shop.article_products WHERE product_id = $1) x
"""


def _client(entity: str, rag: RagClient, media: MediaClient) -> RagClient | MediaClient:
    return media if entity == ENTITY_MEDIA else rag


async def delete_record(
    conn: asyncpg.Connection, *, entity: str, record_id: int, rag: RagClient, media: MediaClient
) -> str:
    await _client(entity, rag, media).delete(record_id=record_id, doc_type=entity)
    await index_state.ghi(conn, entity=entity, record_id=record_id, state="deleted")
    return f"{entity}#{record_id}: đã gỡ khỏi kho tri thức"


async def index_record(
    conn: asyncpg.Connection,
    *,
    entity: str,
    record_id: int,
    rag: RagClient,
    media: MediaClient,
    force: bool = False,
) -> str:
    """Nạp MỘT bản ghi của luồng B. Bản ghi không còn / không hiển thị ⇒ xoá khỏi kho."""
    doc = await records.load(conn, entity, record_id)
    if doc is None:
        return await delete_record(conn, entity=entity, record_id=record_id, rag=rag, media=media)

    h = records.content_hash(doc)
    if not force and await index_state.hash_da_nap(conn, entity=entity, record_id=record_id) == h:
        return f"{entity}#{record_id}: nội dung không đổi, bỏ qua"

    client = _client(entity, rag, media)
    await client.ensure_collection()
    if isinstance(doc, MediaDoc):
        result = await media.index(doc, content_hash=h)
    else:
        result = await rag.index(doc, content_hash=h)
    await index_state.ghi(
        conn, entity=entity, record_id=record_id, state="indexed", content_hash=h, points=result.points_upserted
    )
    msg = f"{entity}#{record_id}: +{result.points_upserted} point"
    if entity == "product":
        n = await conn.fetchval(_CON_CUA_SAN_PHAM, record_id, KIND_INDEX)
        if n:
            msg += f" · xếp nạp lại {n} bản ghi con"
    return msg


async def index_kb_file(conn: asyncpg.Connection, *, file_id: int, rag: RagClient, objects: ObjectStore) -> str:
    """Nạp MỘT tệp «Tài liệu tra cứu». Lỗi NỘI DUNG (không có chữ) tự đánh dấu `error` ở
    đây — người dùng sửa được. Lỗi HẠ TẦNG (S3/embed/Qdrant) ném lên cho handler."""
    row = await files_repo.lay_kem_nhan(conn, file_id)
    if row is None:
        return f"kb_files#{file_id}: hàng không còn, bỏ qua"

    data = await objects.doc(key=row["s3_key"])
    text = (await TextExtractor().extract(data, filename=row["file_name"])).text
    if not text:
        message = MD_EMPTY_MESSAGE if row["file_type"] == "md" else NO_TEXT_MESSAGE
        await files_repo.danh_dau_loi(conn, file_id=file_id, message=message)
        return f"kb_files#{file_id}: không có nội dung, đã đánh dấu lỗi"

    text, canh_bao = await external_images.mirror_images(text, store=objects)
    for c in canh_bao:
        log.warning("ảnh trong kb_files#%s: %s", file_id, c)

    doc = TextDoc(
        doc_type=DOC_TYPE_KB_FILE,
        record_id=file_id,
        title=row["file_name"],
        text=text,
        meta=DocMeta(
            product_id=row["product_id"],
            brand_id=row["brand_id"],
            brand=row["brand"],
            category=row["category"],
            file_id=file_id,
            file_name=row["file_name"],
        ),
    )
    await rag.ensure_collection()
    result = await rag.index(doc)
    if not await files_repo.danh_dau_san_sang(conn, file_id=file_id, chunk_count=result.points_upserted):
        await rag.delete(record_id=file_id, doc_type=DOC_TYPE_KB_FILE)
        return f"kb_files#{file_id}: hàng bị xoá giữa lúc nạp — đã gỡ point"
    ext = f" · {len(canh_bao)} ảnh giữ link gốc" if canh_bao else ""
    return f"kb_files#{file_id}: +{result.points_upserted} point{ext}"


# ─── Xem lại nội dung đã nạp ────────────────────────────────────────────────────

_OVERLAP_MIN = 6
_OVERLAP_MAX = 200


def overlap_with_previous(prev_text: str, text: str) -> bool:
    """`text` mở đầu bằng phần đuôi của `prev_text` — chunker đã mượn lại qua ranh giới.
    Khớp ngắn hơn `_OVERLAP_MIN` coi là trùng ngẫu nhiên."""
    cap = min(len(prev_text), len(text), _OVERLAP_MAX)
    return any(prev_text[-n:] == text[:n] for n in range(cap, _OVERLAP_MIN - 1, -1))


def _tach_doan(text: str, title: str) -> tuple[str, str]:
    """Ngược `rag.text_payload`: bóc tiền tố `<title>[ — <mục>]`, trả (text thuần, mục)."""
    tach = tach_tien_to(text, title)
    if tach is None:
        return text, ""
    head, body = tach
    return body, head[len(title) + 3 :] if head.startswith(f"{title} — ") else ""


async def noi_dung_da_nap(
    store: QdrantStore, *, collection: str, file_id: int, title: str, chunk_count: int
) -> list[ChunkOut]:
    """Dựng lại bản ĐÃ NẠP — thứ agent thật sự đọc. Dựng đúng id bằng `point_id_of` rồi lấy
    MỘT lượt; point thiếu (chunk_count lệch) thì bỏ qua chứ không ném."""
    if chunk_count <= 0:
        return []
    ids = [point_id_of(DOC_TYPE_KB_FILE, file_id, i) for i in range(chunk_count)]
    payloads = await store.payload_many(collection, ids)
    ra: list[ChunkOut] = []
    for idx, pid in enumerate(ids):
        pl = payloads.get(pid)
        if pl is None:
            continue
        text, section = _tach_doan(str(pl.get("text") or ""), title)
        trung = bool(ra) and overlap_with_previous(ra[-1].text, text)
        ra.append(ChunkOut(idx=idx, text=text, section=section, overlaps_prev=trung))
    return ra
