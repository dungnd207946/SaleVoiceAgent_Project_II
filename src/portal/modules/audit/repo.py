"""SQL của `GET /audit` — một câu SELECT, dựng vị từ theo tham số có mặt.

VỊ TỪ TENANT LÀ LITERAL trong chuỗi (`a.tenant_id = portal.current_tenant()`),
không phải tham số: `control.audit_log` KHÔNG có RLS, và `tenant_conn()` chỉ đặt
`app.tenant_id` — câu SQL nào quên vị từ này là đọc toàn nền tảng không lỗi nào.
Cùng cách `modules/ingest/jobs.py` đọc bảng này.

LEFT JOIN `users`, KHÔNG INNER: 0201 cố ý không FK `actor → users` để nhật ký sống
lâu hơn tài khoản. INNER JOIN là xoá dấu vết của người đã bị gỡ — đúng thứ nhật ký
tồn tại để giữ.
"""

from datetime import date, datetime

import asyncpg

from portal.modules.audit.contracts import MA_ACTOR_MAY

MUI_GIO = "Asia/Ho_Chi_Minh"
"""`from`/`to` là NGÀY theo giờ người dùng (cùng lý lẽ `_NGAY` của `ops/repo.py`):
một hàng 23:30 giờ VN không được rơi sang ngày UTC hôm sau."""

_COT = "a.id, a.luc, a.hanh_dong, a.actor, a.chi_tiet, u.name AS actor_ten, u.email AS actor_email"


async def liet_ke(
    conn: asyncpg.Connection,
    *,
    limit: int,
    con_tro: tuple[datetime, int] | None,
    nhom: list[str] | None,
    tu: date | None,
    den: date | None,
    may: bool,
) -> list[asyncpg.Record]:
    """`limit` hàng mới nhất trước, sau con trỏ (nếu có). Router xin `limit + 1`
    để biết còn trang sau — xem `router._trang`."""
    dk = ["a.tenant_id = portal.current_tenant()"]
    tham_so: list[object] = []

    def them(gia_tri: object) -> str:
        tham_so.append(gia_tri)
        return f"${len(tham_so)}"

    if not may:
        dk.append(f"a.actor <> {them(MA_ACTOR_MAY)}")
    if nhom:
        dk.append(f"split_part(a.hanh_dong, '.', 1) = ANY({them(nhom)}::text[])")
    if tu is not None:
        dk.append(f"a.luc >= ({them(tu)}::date)::timestamp AT TIME ZONE '{MUI_GIO}'")
    if den is not None:
        dk.append(f"a.luc < ({them(den)}::date)::timestamp AT TIME ZONE '{MUI_GIO}'")
    if con_tro is not None:
        luc, id_ = con_tro
        dk.append(f"(a.luc, a.id) < ({them(luc)}::timestamptz, {them(id_)}::bigint)")

    sql = f"""
        SELECT {_COT}
          FROM control.audit_log a
          LEFT JOIN control.users u ON u.id = a.actor
         WHERE {" AND ".join(dk)}
         ORDER BY a.luc DESC, a.id DESC
         LIMIT {them(limit)}
    """
    return await conn.fetch(sql, *tham_so)
