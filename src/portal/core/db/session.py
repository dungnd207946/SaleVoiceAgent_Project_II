"""Cửa DUY NHẤT để truy vấn tenant_data.

VÌ SAO PHẢI LÀ SET LOCAL, KHÔNG BAO GIỜ LÀ SET TRẦN:
SET LOCAL chỉ sống trong một giao dịch; SET trần sống cả kết nối. Kết nối được
tái dùng từ pool, nên với SET trần:

    request A (anphu)   -> lấy kết nối #7 -> SET app.tenant_id='anphu' -> trả #7 về pool
    request B (sunrise) -> lấy kết nối #7 -> quên set -> KẾ THỪA 'anphu'
                                                     -> đọc dữ liệu của An Phú

Lỗi này CHỈ hiện khi có tải thật. Cổng 4 (tests/isolation/test_pool_leak.py)
canh đúng nó.

set_config(..., is_local => true) là dạng hàm của SET LOCAL, dùng được với tham
số bind — nên tenant_id không bao giờ nối chuỗi vào SQL.

tenant_id PHẢI đến từ membership đã xác thực (M2a), KHÔNG BAO GIỜ từ path param,
query string, hay body. Nếu bạn thấy mình đang đọc tenant_id từ request rồi
truyền thẳng vào đây — dừng lại, đó là lỗ hổng.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg


@asynccontextmanager
async def tenant_conn(pool: asyncpg.Pool, tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    if not tenant_id:
        raise ValueError("tenant_id rỗng — tenant_conn() luôn cần tenant tường minh")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
        # Chốt lại: portal.current_tenant() ưu tiên tên role (agent_<tenant>) TRƯỚC biến
        # phiên. Nên nếu ai đó gọi tenant_conn() trên pool nối bằng agent_<khác>, SET LOCAL
        # bị bỏ qua âm thầm và câu truy vấn đọc dữ liệu của tenant khác mà không có lỗi nào.
        # Một roundtrip rẻ đổi lấy việc biến lỗi im lặng đó thành lỗi to.
        hieu_luc = await conn.fetchval("SELECT portal.current_tenant()")
        if hieu_luc != tenant_id:
            raise RuntimeError(
                f"tenant hiệu lực là {hieu_luc!r} nhưng caller yêu cầu {tenant_id!r} — "
                "pool này có phải đang nối bằng role agent_* không?"
            )
        yield conn
