"""SQL của kb_index_state + write-back 4 cột cache của M4.

Mọi hàm nhận `conn` đã ở trong `tenant_conn()`. Lỗi store: fail loud, không nuốt
thành "0 hàng".

⚠️ `0909_bo_rls_toan_bo` đã dỡ RLS khỏi `tenant_data`, nên "đã ở trong
`tenant_conn()`" KHÔNG còn tự lọc tenant — nó chỉ còn đặt biến phiên mà
`portal.current_tenant()` đọc. MỌI câu dưới đây phải tự mang vị từ đó.

Ở file này thiếu vị từ tenant là hỏng CHẮC CHẮN chứ không phải hiếm gặp: cả năm
câu định vị hàng bằng `record_id`/`(entity, record_id)`, mà `record_id` là `id`
của bảng nguồn — nó chỉ unique TRONG một tenant. Hai tenant bất kỳ đều có
`documents.id = 1`, nên `WHERE record_id = 1` trần khớp hàng của cả hai.
"""

import asyncpg

from portal.modules.kb.contracts import IndexResult, IndexState, Target

_UPSERT = """
INSERT INTO tenant_data.kb_index_state
       (tenant_id, entity, record_id, doc_type, target, state,
        content_hash, points, error, attempts, project_code, indexed_at, updated_at)
VALUES (portal.current_tenant(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
        CASE WHEN $5 = 'indexed' THEN now() ELSE NULL END, now())
ON CONFLICT (tenant_id, entity, record_id, doc_type) DO UPDATE
   SET target = EXCLUDED.target,
       state = EXCLUDED.state,
       content_hash = EXCLUDED.content_hash,
       points = EXCLUDED.points,
       error = EXCLUDED.error,
       attempts = EXCLUDED.attempts,
       -- COALESCE: caller cũ không truyền project_code, và ghi '' lên giá trị đã có
       -- làm cascade lúc xoá dự án mất dấu record này.
       project_code = COALESCE(NULLIF(EXCLUDED.project_code, ''), kb_index_state.project_code),
       indexed_at = EXCLUDED.indexed_at,
       updated_at = now()
RETURNING id
"""


async def save_state(
    conn: asyncpg.Connection,
    *,
    entity: str,
    record_id: int,
    doc_type: str,
    target: Target,
    state: IndexState,
    result: IndexResult | None = None,
    error: str = "",
    attempts: int = 0,
    project_code: str = "",
) -> int:
    """`indexed_at` do SQL quyết định để dùng cùng đồng hồ với `updated_at`."""
    r = result or IndexResult()
    return await conn.fetchval(
        _UPSERT,
        entity,
        record_id,
        doc_type,
        target,
        state,
        r.content_hash,
        r.points_upserted,
        error,
        attempts,
        project_code,
    )


async def read_state(conn: asyncpg.Connection, *, entity: str, record_id: int) -> list[asyncpg.Record]:
    """`documents` sinh nhiều dòng (mỗi doc_type một dòng) nên trả list."""
    return await conn.fetch(
        """
        SELECT entity, record_id, doc_type, target, state, points,
               content_hash, error, attempts, indexed_at
          FROM tenant_data.kb_index_state
         WHERE tenant_id = portal.current_tenant()
           AND entity = $1 AND record_id = $2
         ORDER BY doc_type
        """,
        entity,
        record_id,
    )


async def saved_hash(conn: asyncpg.Connection, *, entity: str, record_id: int, doc_type: str) -> tuple[str, str] | None:
    row = await conn.fetchrow(
        "SELECT content_hash, state FROM tenant_data.kb_index_state "
        "WHERE tenant_id = portal.current_tenant() AND entity = $1 AND record_id = $2 AND doc_type = $3",
        entity,
        record_id,
        doc_type,
    )
    return (str(row["content_hash"]), str(row["state"])) if row else None


async def mark_skipped(conn: asyncpg.Connection, *, entity: str, record_id: int, doc_type: str) -> None:
    """Giữ content_hash/points (lần sau còn so được, point cũ vẫn sống) nhưng PHẢI
    chạm indexed_at — badge so `updated_at > indexed_at`, bỏ ra là nó báo lệch mãi."""
    await conn.execute(
        "UPDATE tenant_data.kb_index_state SET state = 'skipped', indexed_at = now(), updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND entity = $1 AND record_id = $2 AND doc_type = $3",
        entity,
        record_id,
        doc_type,
    )


async def indexed_of_project(conn: asyncpg.Connection, *, project_code: str) -> list[asyncpg.Record]:
    """Đường duy nhất còn dùng được sau khi ON DELETE CASCADE xoá row con — sổ
    không có FK tới bảng nguồn nên dòng của nó sống sót."""
    return await conn.fetch(
        "SELECT entity, record_id, doc_type FROM tenant_data.kb_index_state "
        "WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND state <> 'deleted' "
        "ORDER BY entity, record_id",
        project_code,
    )


async def dat_cho_duyet(conn: asyncpg.Connection, *, record_id: int, cho_duyet: bool) -> None:
    """Cờ "chữ này do OCR đọc, chờ người duyệt" trên một hàng tài liệu.

    Van duyệt cắm ở ĐƯỜNG ĐỌC của pipeline (`source/query.py`), không ở một nhánh riêng: hàng
    mang cờ bị coi như chưa đủ điều kiện, và `handle_index` vốn đã biết xử lý ca đó.
    """
    await conn.execute(
        "UPDATE tenant_data.documents SET body_cho_duyet = $2, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
        cho_duyet,
    )


async def cache_extracted_text(conn: asyncpg.Connection, *, record_id: int, text: str, force: bool = False) -> bool:
    """`AND ($3 OR <cột> = '')` là luật "user thắng", trong CÂU SQL — không ở tầng
    Python: hai worker song song đều đọc thấy "đang rỗng" rồi cùng ghi.

    `force=True` chỉ đến từ nút "Tạo lại mô tả" — người dùng chủ động, có xác nhận.

    HAI CỘT ĐÍCH, CHỌN THEO QUYỀN SỞ HỮU BẢN GHI (migration `0937`):

    · `external_id IS NULL` — tài liệu nhập tay. Ghi vào `body` như cũ: đó là ô người
      dùng sửa, và màn CHỜ DUYỆT đọc đúng cột đó, nên đẩy sang cột phụ là làm màn ấy
      trống trơn.
    · `external_id` khác NULL — bản ghi do hệ ngoài sở hữu. Ghi vào `body_auto`, vì
      `body` là cột hợp đồng của cổng nạp: latest-wins đưa nó về `''` mỗi lần khách đẩy
      lại bản ghi, nên chữ bóc ra nằm ở đó sẽ bị xoá rồi bóc lại mỗi vòng đồng bộ — mà
      OCR một PDF nhiều trang KHÔNG rẻ. Đường nạp đọc `coalesce(nullif(body,''),
      body_auto)` nên hợp nhất lại ngay trong SQL (`source/query.py::_COT_SUY`).

    Bản ghi ngoài KHÔNG còn kiểm `body = ''` (2026-08-25): adapter hay đặt siêu dữ liệu
    vào `body`, và xét nó là PDF không bao giờ được đọc. Hai cột KHÔNG đè nhau — đường
    nạp nối cả hai (`source/query.py::_COT_SUY`), nên chữ khách gửi vẫn giữ nguyên.
    """
    cua_ngoai = await conn.fetchval(
        "SELECT external_id IS NOT NULL FROM tenant_data.documents "
        " WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
    if cua_ngoai is None:
        return False
    if cua_ngoai:
        ghi = await conn.fetchval(
            "UPDATE tenant_data.documents SET body_auto = $2, updated_at = now() "
            "WHERE tenant_id = portal.current_tenant() AND id = $1 "
            "  AND ($3 OR body_auto = '') "
            "RETURNING id",
            record_id,
            text,
            force,
        )
        return ghi is not None
    ghi = await conn.fetchval(
        "UPDATE tenant_data.documents SET body = $2, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1 AND ($3 OR body = '') "
        "RETURNING id",
        record_id,
        text,
        force,
    )
    return ghi is not None


async def cache_caption(conn: asyncpg.Connection, *, record_id: int, caption: str, force: bool = False) -> bool:
    ghi = await conn.fetchval(
        "UPDATE tenant_data.media SET caption = $2, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1 AND ($3 OR caption = '') "
        "RETURNING id",
        record_id,
        caption,
        force,
    )
    return ghi is not None


async def cache_caption_auto(conn: asyncpg.Connection, *, record_id: int, caption: str) -> bool:
    """Mô tả do VLM sinh → `caption_auto`, KHÔNG phải `caption` (xem migration `0936`).

    `AND caption = ''` là luật "người thắng" viết TRONG câu SQL, cùng lý do
    `cache_extracted_text`: hai worker song song đều đọc thấy "đang rỗng" rồi cùng ghi.
    Ở đây nó còn chặn một cuộc đua thật khác — một lô nạp mang caption của khách tới
    trong lúc job VLM đang chạy.

    KHÔNG có `force`: cột này chỉ có một người ghi. Muốn thay mô tả thì gõ vào `caption`,
    nó thắng sẵn.
    """
    ghi = await conn.fetchval(
        "UPDATE tenant_data.media SET caption_auto = $2, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1 AND caption = '' "
        "RETURNING id",
        record_id,
        caption,
    )
    return ghi is not None


async def save_thumb(conn: asyncpg.Connection, *, record_id: int, thumb_url: str) -> None:
    """CHỈ `thumb_url`. Tách khỏi `save_thumb_and_hash` vì hàm đó gán `content_hash`
    VÔ ĐIỀU KIỆN — gọi nó từ chặng enrich (chỗ chưa tính hash chunk) sẽ xoá trắng
    `content_hash` của hàng, và `reconcile` sau đó coi mọi point là đã trôi."""
    from portal.core.public_url import public_url_of

    await conn.execute(
        "UPDATE tenant_data.media SET thumb_url = $2, public_thumb_url = $3, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
        thumb_url,
        public_url_of(thumb_url),
    )


async def save_thumb_tai_lieu(conn: asyncpg.Connection, *, record_id: int, thumb_url: str) -> None:
    """Bản `documents` của `save_thumb` — hai cột cùng hình dạng, thêm ở `0928`."""
    from portal.core.public_url import public_url_of

    await conn.execute(
        "UPDATE tenant_data.documents SET thumb_url = $2, public_thumb_url = $3, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
        thumb_url,
        public_url_of(thumb_url),
    )


async def save_thumb_and_hash(
    conn: asyncpg.Connection,
    *,
    record_id: int,
    thumb_url: str,
    content_hash: str,
) -> None:
    """Hai cột này luôn do ingest ghi — user không sửa được."""
    await conn.execute(
        """
        UPDATE tenant_data.media
           SET thumb_url = COALESCE(NULLIF($2, ''), thumb_url),
               content_hash = $3,
               updated_at = now()
         WHERE tenant_id = portal.current_tenant() AND id = $1
        """,
        record_id,
        thumb_url,
        content_hash,
    )


async def mark_deleted(
    conn: asyncpg.Connection,
    *,
    entity: str,
    record_id: int,
    doc_types: list[str] | None = None,
) -> None:
    """`doc_types=None` = mọi dòng của record. Khai rõ danh sách khi caller chỉ xoá
    một phần: `documents` có N dòng cho một record, và đánh dấu quá tay sẽ ghi
    `deleted` cho một loại mà point của nó đang sống.
    """
    await conn.execute(
        "UPDATE tenant_data.kb_index_state SET state = 'deleted', points = 0, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND entity = $1 AND record_id = $2 "
        "  AND ($3::text[] IS NULL OR doc_type = ANY($3))",
        entity,
        record_id,
        doc_types,
    )
