"""Sổ `shop.kb_index_state` của luồng B — một hàng / (entity, record_id, target).

Hàng `indexed` + `content_hash` là điều kiện DUY NHẤT để bỏ qua một lượt nạp: hash trùng nói
nội dung không đổi, `state` nói point đã thật sự lên Qdrant. Thiếu vế sau thì bản ghi từng
lỗi (hash vẫn được ghi) sẽ bị bỏ qua mãi.
"""

import asyncpg

from portal.modules.kb.contracts import ENTITY_MEDIA


def target_of(entity: str) -> str:
    return "media" if entity == ENTITY_MEDIA else "documents"


async def hash_da_nap(conn: asyncpg.Connection, *, entity: str, record_id: int) -> str | None:
    """`content_hash` nếu bản ghi đang `indexed`, ngược lại None."""
    return await conn.fetchval(
        """SELECT content_hash FROM shop.kb_index_state
            WHERE entity = $1 AND record_id = $2 AND target = $3 AND state = 'indexed'""",
        entity,
        record_id,
        target_of(entity),
    )


async def ghi(
    conn: asyncpg.Connection,
    *,
    entity: str,
    record_id: int,
    state: str,
    content_hash: str | None = None,
    points: int = 0,
    error: str | None = None,
) -> None:
    await conn.execute(
        """INSERT INTO shop.kb_index_state (entity, record_id, target, state, content_hash, points, error, indexed_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, CASE WHEN $4 = 'indexed' THEN now() END)
           ON CONFLICT (entity, record_id, target) DO UPDATE SET
             state = EXCLUDED.state,
             content_hash = EXCLUDED.content_hash,
             points = EXCLUDED.points,
             error = EXCLUDED.error,
             indexed_at = coalesce(EXCLUDED.indexed_at, shop.kb_index_state.indexed_at),
             updated_at = now()""",
        entity,
        record_id,
        target_of(entity),
        state,
        content_hash,
        points,
        (error or "")[:2000] or None,
    )
