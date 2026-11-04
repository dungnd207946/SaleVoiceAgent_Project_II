"""SQL của `shop.kb_files` — sổ DUY NHẤT của kho «Tài liệu tra cứu» (không ghi `kb_index_state`).

Hàng `ready` nghĩa là point ĐÃ lên Qdrant: service đánh dấu SAU CÙNG.
"""

from collections.abc import Sequence
from typing import Any

import asyncpg

from portal.core import crud

COT = (
    "id, file_name, s3_key, size_bytes, file_type, product_id, brand_id, state, chunk_count, error_message, uploaded_at"
)


async def them(
    conn: asyncpg.Connection,
    *,
    file_name: str,
    s3_key: str,
    size_bytes: int,
    file_type: str,
    product_id: int | None,
    brand_id: int | None,
) -> asyncpg.Record:
    return await conn.fetchrow(
        f"""INSERT INTO shop.kb_files (file_name, s3_key, size_bytes, file_type, product_id, brand_id)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING {COT}""",
        file_name,
        s3_key,
        size_bytes,
        file_type,
        product_id,
        brand_id,
    )


async def liet_ke(
    conn: asyncpg.Connection,
    *,
    dieu_kien: Sequence[str],
    tham_so: Sequence[Any],
    limit: int,
    offset: int,
) -> tuple[list[asyncpg.Record], int]:
    """Mới nhất trước."""
    return await crud.liet_ke(
        conn,
        "kb_files",
        dieu_kien=dieu_kien,
        tham_so=tham_so,
        sap_xep="uploaded_at DESC, id DESC",
        limit=limit,
        offset=offset,
    )


async def lay(conn: asyncpg.Connection, file_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(f"SELECT {COT} FROM shop.kb_files WHERE id = $1", file_id)


async def lay_kem_nhan(conn: asyncpg.Connection, file_id: int) -> asyncpg.Record | None:
    """Kèm tên hãng/ngành để payload lọc được như dữ liệu sản phẩm. Gắn sản phẩm thì hãng/ngành
    suy từ sản phẩm (cột `brand_id` của tệp chỉ dùng khi tài liệu là của cả hãng)."""
    return await conn.fetchrow(
        """SELECT f.id, f.file_name, f.s3_key, f.file_type, f.product_id,
                  coalesce(p.brand_id, f.brand_id) AS brand_id, b.name AS brand, c.name AS category
             FROM shop.kb_files f
             LEFT JOIN shop.products p ON p.id = f.product_id
             LEFT JOIN shop.brands b ON b.id = coalesce(p.brand_id, f.brand_id)
             LEFT JOIN shop.categories c ON c.id = p.category_id
            WHERE f.id = $1""",
        file_id,
    )


async def co_khoa(conn: asyncpg.Connection, s3_key: str) -> int | None:
    return await conn.fetchval("SELECT id FROM shop.kb_files WHERE s3_key = $1", s3_key)


async def xoa(conn: asyncpg.Connection, file_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(f"DELETE FROM shop.kb_files WHERE id = $1 RETURNING {COT}", file_id)


async def dat_lai(conn: asyncpg.Connection, file_id: int) -> asyncpg.Record | None:
    """Về `processing` trước khi nạp lại — giao diện thấy ngay là đang làm."""
    return await conn.fetchrow(
        f"""UPDATE shop.kb_files SET state = 'processing', error_message = NULL
             WHERE id = $1 RETURNING {COT}""",
        file_id,
    )


async def danh_dau_san_sang(conn: asyncpg.Connection, *, file_id: int, chunk_count: int) -> bool:
    """False = hàng đã biến mất giữa lúc nạp (race với DELETE) — caller phải GỠ point vừa ghi."""
    r = await conn.fetchval(
        """UPDATE shop.kb_files SET state = 'ready', chunk_count = $2, error_message = NULL
            WHERE id = $1 RETURNING id""",
        file_id,
        chunk_count,
    )
    return r is not None


async def danh_dau_loi(conn: asyncpg.Connection, *, file_id: int, message: str) -> None:
    await conn.execute(
        "UPDATE shop.kb_files SET state = 'error', chunk_count = 0, error_message = $2 WHERE id = $1",
        file_id,
        message[:2000],
    )
