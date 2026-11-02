"""Preflight — fail sớm với thông báo rõ thay vì N case timeout (spec §10). Lazy imports."""

from __future__ import annotations

import asyncio
import os


async def check_redis(timeout_s: float = 3.0) -> str | None:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415 — lazy: unit test không cần lib chạy thật

        client = aioredis.from_url(url)
        try:
            await asyncio.wait_for(client.ping(), timeout=timeout_s)
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001 — mọi lỗi đều là "Redis không sẵn sàng"
        return f"Redis không sẵn sàng tại {url}: {type(e).__name__}: {e}"
    return None
