"""Factory pool asyncpg. Không giữ singleton — caller quản vòng đời."""

import asyncpg


async def create_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
