"""SQL của module linh_vuc. CALLER quyết định giao dịch — khuôn `repo.py` chung.

HAI HẠNG KẾT NỐI, đừng trộn:
- `doc_verticals`/`bat`/`tat` chạm `control.tenant_verticals` — schema
  `control` KHÔNG có RLS (cố ý, 0908), cách ly CHỈ nhờ vị từ `tenant_id = $1`
  với tenant lấy từ Principal. Nhận `conn` từ `pool.acquire()` thường.
- `co_du_lieu_bds` chạm `tenant_data.projects` — PHẢI gọi trong
  `tenant_conn()` (RLS FORCE), và vị từ `tenant_id = portal.current_tenant()`
  viết LITERAL trong chuỗi vì cổng cách ly đọc TĨNH f-string.

Bảng `tenant_verticals` có người ghi thứ nhất là `workspace/repo.them_vertical`
(lúc tạo workspace) — module này là người ghi thứ hai (công tắc màn /domains).
"""

import asyncpg


async def doc_verticals(conn: asyncpg.Connection, tenant_id: str) -> set[str]:
    """Tập vertical đang BẬT của workspace — bật = có hàng (nghĩa gốc của 0002)."""
    rows = await conn.fetch("SELECT vertical FROM control.tenant_verticals WHERE tenant_id = $1", tenant_id)
    return {r["vertical"] for r in rows}


async def bat(conn: asyncpg.Connection, tenant_id: str, vertical: str) -> None:
    """Idempotent — bật thứ đang bật là no-op, không có lỗi «đã bật rồi»."""
    await conn.execute(
        "INSERT INTO control.tenant_verticals (tenant_id, vertical) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        tenant_id,
        vertical,
    )


async def tat(conn: asyncpg.Connection, tenant_id: str, vertical: str) -> None:
    """Idempotent — DELETE hụt im lặng. `enabled_at` mất theo hàng; bật lại
    là mốc mới — chấp nhận, không ai đọc mốc đó."""
    await conn.execute(
        "DELETE FROM control.tenant_verticals WHERE tenant_id = $1 AND vertical = $2",
        tenant_id,
        vertical,
    )


async def co_du_lieu_bds(conn: asyncpg.Connection) -> bool:
    """Agent đã có gì để tra chưa — gọi TRONG `tenant_conn()`.

    LOẠI SENTINEL `'__ALL__'` (literal — khớp `SENTINEL_TENANT` của
    realestate, có test neo): row hệ thống đó LUÔN published ở mọi tenant
    (provisioning tạo, `SENTINEL_PROTECTED` chặn xoá) — không loại thì mọi
    tenant đều «đã có dữ liệu» và trường này thành hằng.

    Chỉ xét `projects`: nó neo cả cây (units/zones/documents FK về nó) —
    «có dự án published» là điều kiện cần và đủ để agent tra được gì đó.
    """
    return bool(
        await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM tenant_data.projects"
            " WHERE tenant_id = portal.current_tenant()"
            " AND status = 'published' AND project_code <> '__ALL__')"
        )
    )
