"""Xếp việc hồ sơ web cho MỘT dự án. Gọi trong `tenant_conn` đang mở, cùng giao dịch với lệnh ghi.

Gộp với việc cùng dự án + mode còn `queued` chưa thử lần nào; việc đang chạy hoặc đang chờ thử lại
không chặn — nó có thể đã đọc dữ liệu cũ, hoặc đang lùi hàng phút sau một lỗi.
"""

import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.web.contracts import KIND_PROJECT, KIND_PURGE, MODE_INIT, MODES

_QUEUED = """SELECT 1 FROM control.jobs
              WHERE tenant_id = portal.current_tenant() AND kind = $1 AND state = 'queued' AND attempts = 0
                AND payload->>'project_code' = $2 AND payload->>'mode' = $3
              LIMIT 1"""


async def enqueue_web_project(
    conn: asyncpg.Connection, *, tenant_id: str, actor: str, project_code: str, mode: str = MODE_INIT
) -> int | None:
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} không hợp lệ, phải là một trong {MODES}")
    if await conn.fetchval(_QUEUED, KIND_PROJECT, project_code, mode):
        return None
    return await enqueue(
        conn, tenant_id=tenant_id, kind=KIND_PROJECT, actor=actor, payload={"project_code": project_code, "mode": mode}
    )


async def enqueue_web_purge(conn: asyncpg.Connection, *, tenant_id: str, actor: str, project_name: str) -> int | None:
    """Dọn hồ sơ dữ liệu ngoài của dự án mang TÊN này — hồ sơ khoá theo tên, nên đổi tên/gỡ công bố/xoá
    dự án mà không dọn thì điểm cũ nằm lại trong kho. `None` khi tên rỗng."""
    if not project_name.strip():
        return None
    return await enqueue(
        conn, tenant_id=tenant_id, kind=KIND_PURGE, actor=actor, payload={"project_name": project_name}
    )
