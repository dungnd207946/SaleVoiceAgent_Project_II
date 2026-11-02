"""SQL của `tenant_data.kb_files` — sổ DUY NHẤT của kho «Tài liệu tra cứu».

KHÔNG ghi `kb_index_state` cho kho này (spec 2026-08-20 §5): CHECK `entity` của bảng
đó không nhận 'kb_files', reconcile chưa có thân, và vị từ xoá không cần tra sổ vì
`doc_type='kb_file'` là hằng. Hàng `san_sang` nghĩa là point ĐÃ lên Qdrant — service
đánh dấu SAU CÙNG, đúng thứ tự bốn-bước của bản M6 gốc (commit 0390d86).
"""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

_COT = "id, ten_file, s3_key, kich_thuoc, loai, state, chunk_count, loi_message, uploaded_at, uploaded_by"


@dataclass(frozen=True, slots=True)
class HangTaiLieu:
    id: int
    ten_file: str
    s3_key: str
    kich_thuoc: int
    loai: str
    state: str
    chunk_count: int
    loi_message: str
    uploaded_at: datetime
    uploaded_by: str | None


def _hang(r: asyncpg.Record) -> HangTaiLieu:
    return HangTaiLieu(
        id=r["id"],
        ten_file=r["ten_file"],
        s3_key=r["s3_key"],
        kich_thuoc=r["kich_thuoc"],
        loai=r["loai"],
        state=r["state"],
        chunk_count=r["chunk_count"],
        loi_message=r["loi_message"],
        uploaded_at=r["uploaded_at"],
        uploaded_by=r["uploaded_by"],
    )


async def them(
    conn: asyncpg.Connection, *, ten_file: str, s3_key: str, kich_thuoc: int, loai: str, uploaded_by: str | None
) -> HangTaiLieu:
    r = await conn.fetchrow(
        "INSERT INTO tenant_data.kb_files (tenant_id, ten_file, s3_key, kich_thuoc, loai, uploaded_by) "
        f"VALUES (portal.current_tenant(), $1, $2, $3, $4, $5) RETURNING {_COT}",
        ten_file,
        s3_key,
        kich_thuoc,
        loai,
        uploaded_by,
    )
    return _hang(r)


async def liet_ke(conn: asyncpg.Connection) -> list[HangTaiLieu]:
    """Mới nhất trước — khớp index `kb_files_tenant_moi_idx` (tenant_id, uploaded_at DESC)."""
    rows = await conn.fetch(
        f"SELECT {_COT} FROM tenant_data.kb_files "
        "WHERE tenant_id = portal.current_tenant() ORDER BY uploaded_at DESC, id DESC"
    )
    return [_hang(r) for r in rows]


async def doc(conn: asyncpg.Connection, record_id: int) -> HangTaiLieu | None:
    r = await conn.fetchrow(
        f"SELECT {_COT} FROM tenant_data.kb_files WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
    return None if r is None else _hang(r)


async def xoa(conn: asyncpg.Connection, record_id: int) -> None:
    await conn.execute(
        "DELETE FROM tenant_data.kb_files WHERE tenant_id = portal.current_tenant() AND id = $1", record_id
    )


async def danh_dau_san_sang(conn: asyncpg.Connection, *, record_id: int, chunk_count: int) -> bool:
    """True = đã đánh dấu; False = hàng đã biến mất giữa lúc nạp (race với DELETE) —
    caller phải GỠ point vừa ghi, nếu không chúng mồ côi ở status published vĩnh viễn
    (reconcile chưa có thân, không ai dọn hộ)."""
    r = await conn.fetchrow(
        "UPDATE tenant_data.kb_files SET state = 'san_sang', chunk_count = $2, loi_message = '' "
        "WHERE tenant_id = portal.current_tenant() AND id = $1 RETURNING id",
        record_id,
        chunk_count,
    )
    return r is not None


async def danh_dau_loi(conn: asyncpg.Connection, *, record_id: int, loi_message: str) -> None:
    await conn.execute(
        "UPDATE tenant_data.kb_files SET state = 'loi', loi_message = $2 "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
        loi_message,
    )
