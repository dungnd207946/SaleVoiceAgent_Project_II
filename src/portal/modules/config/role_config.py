"""`tenant_data.role_config` — danh sách role người dùng agent của tenant (từ `0967`).

Mỗi role một hàng `(tenant_id, key, ten, icon, thu_tu)`. `key` bất biến (là thứ
`agent_config.role` lưu, FK `ON DELETE CASCADE`), `ten` là tên hiển thị đổi được.
Role `customer` do trigger tạo cùng tenant và trigger khác chặn xoá — code ở đây vẫn kiểm
trước để trả 409 có nghĩa thay vì một `RaiseError` giữa giao dịch.

Cùng luật với `agent_config.py`: bảng RLS + FORCE, mọi câu chạy trong `tenant_conn()` và
mang HAI vị từ tenant (`$1` và `portal.current_tenant()`).
"""

import re
import unicodedata
from dataclasses import dataclass

import asyncpg

_CACH_LY = "tenant_id = $1 AND tenant_id = portal.current_tenant()"


@dataclass(frozen=True)
class Role:
    key: str
    ten: str
    icon: str | None
    thu_tu: int


async def liet_ke(conn: asyncpg.Connection, tenant_id: str) -> list[Role]:
    """Theo `thu_tu` rồi `created_at` — đúng thứ tự tab trên màn `/agent`."""
    rows = await conn.fetch(
        f"SELECT key, ten, icon, thu_tu FROM tenant_data.role_config WHERE {_CACH_LY} ORDER BY thu_tu, created_at, key",
        tenant_id,
    )
    return [Role(r["key"], r["ten"], r["icon"], r["thu_tu"]) for r in rows]


def _bo_dau(s: str) -> str:
    # `đ` không tách được bằng NFD (xem `workspace/service._bo_dau`) — xử lý riêng.
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def key_tu_ten(ten: str, da_co: set[str]) -> str:
    """`"Đối tác môi giới"` -> `"doi_tac_moi_gioi"`. LUÔN khớp CHECK `^[a-z][a-z0-9_]{1,31}$`
    và không trùng `da_co` (thêm `_2`, `_3`… — cắt gốc chứ không cắt hậu tố)."""
    goc = re.sub(r"[^a-z0-9]+", "_", _bo_dau(ten).lower()).strip("_") or "role"
    if not goc[0].isalpha():
        goc = f"r_{goc}"
    goc = goc[:32].rstrip("_")
    if len(goc) < 2:
        goc = f"{goc}_r"
    ung_vien, n = goc, 1
    while ung_vien in da_co:
        n += 1
        hau_to = f"_{n}"
        ung_vien = f"{goc[: 32 - len(hau_to)].rstrip('_')}{hau_to}"
    return ung_vien


async def them(conn: asyncpg.Connection, tenant_id: str, key: str, ten: str, icon: str | None, thu_tu: int) -> None:
    """`UniqueViolationError` nếu tên trùng (index `role_config_ten_key`) — caller dịch 409."""
    await conn.execute(
        "INSERT INTO tenant_data.role_config (tenant_id, key, ten, icon, thu_tu) VALUES ($1, $2, $3, $4, $5)",
        tenant_id,
        key,
        ten,
        icon,
        thu_tu,
    )


async def sua(conn: asyncpg.Connection, tenant_id: str, key: str, ten: str | None, icon: str | None) -> Role | None:
    """Đổi tên và/hoặc icon (None = giữ nguyên). Trả bản CŨ; None = không có role đó.
    `UniqueViolationError` nếu tên trùng."""
    cu = await conn.fetchrow(
        f"SELECT key, ten, icon, thu_tu FROM tenant_data.role_config WHERE {_CACH_LY} AND key = $2 FOR UPDATE",
        tenant_id,
        key,
    )
    if cu is None:
        return None
    await conn.execute(
        f"""UPDATE tenant_data.role_config
               SET ten = COALESCE($3, ten), icon = COALESCE($4, icon), updated_at = now()
             WHERE {_CACH_LY} AND key = $2""",
        tenant_id,
        key,
        ten,
        icon,
    )
    return Role(cu["key"], cu["ten"], cu["icon"], cu["thu_tu"])


async def xoa(conn: asyncpg.Connection, tenant_id: str, key: str) -> str | None:
    """Trả tên của role vừa xoá; None = không có. Hàng `agent_config` của nó đi theo (FK)."""
    return await conn.fetchval(
        f"DELETE FROM tenant_data.role_config WHERE {_CACH_LY} AND key = $2 RETURNING ten",
        tenant_id,
        key,
    )
