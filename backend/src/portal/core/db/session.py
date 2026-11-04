"""Mở một kết nối trong MỘT giao dịch — cửa chung cho mọi truy vấn ghi.

Không còn tenant: chỉ một cửa hàng, một schema `shop`. Giữ hàm này thay vì để mỗi
route tự `pool.acquire()` + `transaction()` để "ghi nhiều câu" luôn là nguyên tử —
quên `transaction()` thì lỗi giữa chừng để lại dữ liệu nửa vời.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg


@asynccontextmanager
async def tx(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    async with pool.acquire() as conn, conn.transaction():
        yield conn
