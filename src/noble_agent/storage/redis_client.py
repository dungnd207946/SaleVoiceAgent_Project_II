"""Standalone async Redis client for noble_agent.

Self-contained: reads REDIS_URL from env (default redis://localhost:6379/0),
builds an aioredis client, caches it as a singleton. No dependency on the
legacy noble_agent.storage.connection module.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger("noble_agent.storage.redis")

_client: Any = None
_lock = asyncio.Lock()


def _redis_url() -> str:
    """Env var thắng (giữ semantics cũ), rồi tới settings (đọc được .env), rồi
    default localhost. Bug live 2026-08-19: chỉ đọc os.getenv nên REDIS_URL nằm
    trong .env không-export bị bỏ qua — gateway stash + livekit fetch credential
    rơi về localhost:6379 và fail im lặng, trong khi session state vẫn chạy
    (đường settings) nên không ai nhận ra."""
    url = os.getenv("REDIS_URL")
    if url:
        return url
    try:
        from noble_agent.config import get_settings

        url = get_settings().redis_url
    except Exception:  # noqa: BLE001 — settings hỏng thì về default, đừng chặn import
        url = ""
    return url or "redis://localhost:6379/0"


async def get_redis() -> Any:
    """Return a singleton async Redis client. Connects lazily.

    Returns ``None`` if redis package is unavailable or connection fails — the
    caller must handle this (StateRepo would crash, so this is a fatal config
    issue at boot; we log loudly and let it propagate at first use).
    """
    global _client
    if _client is not None:
        return _client
    async with _lock:
        if _client is not None:
            return _client
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.error("redis package not installed; install `redis>=5` to use refactor core")
            raise

        url = _redis_url()
        client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            retry_on_timeout=True,
        )
        try:
            await client.ping()
            logger.info("noble_agent: Redis connected (%s)", url)
        except Exception as exc:
            logger.error("noble_agent: Redis ping failed (%s): %s", url, exc)
            raise
        _client = client
        return _client


async def close_redis() -> None:
    """Used by tests to drop the cached client."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None


def set_redis_for_tests(client: Any) -> None:
    """Inject a fake client (e.g. fakeredis.aioredis) without going through env."""
    global _client
    _client = client
