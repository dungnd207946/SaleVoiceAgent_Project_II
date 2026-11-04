"""Factory pool asyncpg + dependency lấy pool của app. Không giữ singleton — app quản vòng đời."""

import asyncpg
from fastapi import Request


async def create_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)


def get_pool(request: Request) -> asyncpg.Pool:
    """Dependency FastAPI: pool sống trong `app.state` (dựng ở lifespan của `create_app`)."""
    return request.app.state.pool
