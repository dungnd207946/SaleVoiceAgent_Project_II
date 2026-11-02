"""Xếp một job kiểm im lặng cho MỖI tenant đang hoạt động.

Cron không có phiên đăng nhập, và `core/jobs.run_once` chạy mọi handler trong
`tenant_conn()` — nên «quét mọi tenant» phải là N job, không phải một job lặp.
Ba thứ đổi được nhờ khuôn này: mỗi job chịu RLS của chính tenant nó, worker chạy
song song được, và «tenant nào lỗi» nhìn thấy trong bảng `control.jobs`.
"""

import asyncpg

from portal.core.db.session import tenant_conn
from portal.core.jobs import enqueue


async def xep_moi_tenant(pool: asyncpg.Pool, *, kind: str, actor: str = "cron") -> int:
    """Xếp job `kind` cho mỗi tenant đang hoạt động. Trả số job đã xếp.

    NHẬN `pool`, KHÔNG nhận `conn` — và đó là ràng buộc, không phải sở thích:
    `core.jobs.enqueue()` suy tenant từ CHÍNH KẾT NỐI (`portal.current_tenant()`)
    và ném nếu lệch tham số, vì `control.jobs` không có RLS nên một lời gọi chéo
    tenant sẽ ghi được và worker về sau chạy job đó bằng ngữ cảnh tenant kia. Nên
    xếp việc cho N tenant = mở N lượt `tenant_conn`, không phải một vòng lặp trên
    một kết nối.

    CHỈ tenant `active`: một workspace suspended/closed không đẩy dữ liệu và không
    gửi bản kê là ĐÚNG — xếp việc bảo trì hay cảnh báo cho nó là sinh việc cho
    người trực về một thứ đã được quyết định dừng.
    """
    async with pool.acquire() as conn:
        hang = await conn.fetch("SELECT id FROM control.tenants WHERE lifecycle = 'active' ORDER BY id")
    for r in hang:
        async with tenant_conn(pool, r["id"]) as c:
            await enqueue(c, tenant_id=r["id"], kind=kind, actor=actor, payload={})
    return len(hang)
