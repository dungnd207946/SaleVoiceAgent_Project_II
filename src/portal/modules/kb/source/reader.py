"""Chạy câu do query.py sinh, trả dict thuần để tầng directive không cần DB."""

import asyncpg

from portal.modules.kb.contracts import ChildBlockSpec, EntitySpec, VerticalSpec
from portal.modules.kb.source import query


async def read_record(
    conn: asyncpg.Connection,
    *,
    vertical: VerticalSpec,
    spec: EntitySpec,
    record_id: int,
) -> dict | None:
    """None = không đủ điều kiện index (nháp, hoặc anchor cha chưa published).

    None không phải lỗi: unpublish rồi worker mới chạy tới job cũ là chuyện thường.
    """
    record = await conn.fetchrow(query.read_record_sql(vertical, spec), record_id)
    if record is None:
        return None
    row = dict(record)
    if spec.is_anchor:
        row["anchor_name"] = row.get("name") or ""
    if spec.child_block is not None:
        block = spec.child_block
        row["children"] = await read_child_rows(conn, block=block, anchor_code=str(row[spec.anchor_col]))
        if block.child is not None:
            con = await read_child_rows(conn, block=block.child, anchor_code=str(row[spec.anchor_col]))
            cha = {r[block.key_col]: r for r in row["children"]}
            for r in row["children"]:
                r["children"] = []
            row["orphan_children"] = []
            for c in con:
                parent = cha.get(c[block.child.parent_col])
                (parent["children"] if parent is not None else row["orphan_children"]).append(c)
    return row


async def read_child_rows(conn: asyncpg.Connection, *, block: ChildBlockSpec, anchor_code: str) -> list[dict]:
    rows = await conn.fetch(query.read_child_rows_sql(block), anchor_code)
    return [dict(r) for r in rows]


async def list_ban_ghi_theo_anchor(
    conn: asyncpg.Connection, *, vertical: VerticalSpec, spec: EntitySpec, anchor_code: str
) -> list[int]:
    rows = await conn.fetch(query.list_ban_ghi_theo_anchor_sql(vertical, spec), anchor_code)
    return [int(r["id"]) for r in rows]


async def list_media_theo_anchor(conn: asyncpg.Connection, *, vertical: VerticalSpec, anchor_code: str) -> list[int]:
    rows = await conn.fetch(query.list_media_theo_anchor_sql(vertical), anchor_code)
    return [int(r["id"]) for r in rows]


async def read_media(conn: asyncpg.Connection, *, vertical: VerticalSpec, record_id: int) -> dict | None:
    """Lọc category theo media.visual làm ở directive/profiles, không ở SQL.

    Cần phân biệt "không có row" với "có row nhưng category không index" — cái sau phải
    ghi kb_index_state để dashboard hiện "không index" thay vì im lặng.
    """
    record = await conn.fetchrow(query.read_media_sql(vertical), record_id)
    return dict(record) if record is not None else None
