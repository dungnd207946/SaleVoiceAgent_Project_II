"""SQL đọc của module config: nhịp tim của pod · version hiện tại.

Ghi/đọc cấu hình theo role nằm ở `agent_config.py` — chỗ DUY NHẤT chạm câu SQL của
`tenant_data.agent_config` ngoài hàm đếm của màn Tổng quan (`ops/repo.py`).

Mọi hàm nhận `conn` từ caller, không tự lấy kết nối — caller quyết định giao dịch.
`tenant_id` truyền vào PHẢI đến từ `principal.tenant_id`, KHÔNG BAO GIỜ từ path param,
query string hay body. `agent_config` có RLS + FORCE (`0956`) nên caller phải ở trong
`tenant_conn()`; câu SQL vẫn mang vị từ tường minh (xem `agent_config.py` luật 3).
"""

import asyncpg

from portal.modules.config.service import Heartbeat


async def version_hien_tai(conn: asyncpg.Connection, tenant_id: str) -> int | None:
    """`agent_config.version` hiện tại của tenant. None = chưa lưu lần nào.

    MAX chứ không một hàng bất kỳ: hai role luôn được ghi cùng số (`service.luu_cau_hinh`),
    nhưng MAX vẫn đúng cả khi ai đó sửa tay một hàng.
    """
    return await conn.fetchval(
        "SELECT MAX(version) FROM tenant_data.agent_config"
        " WHERE tenant_id = $1 AND tenant_id = portal.current_tenant()",
        tenant_id,
    )


async def doc_heartbeat(conn: asyncpg.Connection, tenant_id: str) -> Heartbeat | None:
    """Nhịp tim MỚI NHẤT của tenant (`0941`: một hàng mỗi tenant, chat/voice đè nhau)."""
    r = await conn.fetchrow(
        """SELECT running_version, bundle_sha, last_seen_at
             FROM control.agent_heartbeats
            WHERE tenant_id = $1
            ORDER BY last_seen_at DESC LIMIT 1""",
        tenant_id,
    )
    if r is None:
        return None
    return Heartbeat(
        running_version=r["running_version"],
        bundle_sha=r["bundle_sha"],
        last_seen_at=r["last_seen_at"],
    )
