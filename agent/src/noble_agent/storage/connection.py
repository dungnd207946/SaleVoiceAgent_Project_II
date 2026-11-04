"""Async connection manager for Redis.

Redis: session state (meta, customer, agent state) — TTL 24h.

Durable storage lives in Postgres (``storage/postgres_client.py`` +
``storage/pg_data_plane.py``), which owns its own pools and is not managed here.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

logger = logging.getLogger("storage.connection")


class Status(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class ConnectionManager:
    """Singleton — call `await initialize()` once at startup."""

    def __init__(self) -> None:
        self._redis = None
        self.redis_status = Status.DISCONNECTED
        self._health_task: asyncio.Task | None = None
        self._init_lock = asyncio.Lock()
        self._initialized = False

    # ── Redis ────────────────────────────────────────────────────────────

    async def connect_redis(self) -> None:
        from noble_agent.config import settings

        if not settings.redis_url:
            logger.warning("REDIS_URL not set — session state will be in-memory only")
            return
        self.redis_status = Status.CONNECTING
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                retry_on_timeout=True,
            )
            await self._redis.ping()
            self.redis_status = Status.CONNECTED
            logger.info("Redis connected: %s", settings.redis_url)
        except Exception as exc:
            self.redis_status = Status.ERROR
            self._redis = None
            logger.error("Redis connection failed: %s", exc)

    @property
    def redis(self):
        return self._redis

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        # Idempotent — safe to call from every entrypoint (LiveKit worker
        # entrypoint runs per-job; without this guard Redis would reconnect
        # on every call).
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self.connect_redis()
            from noble_agent.config import settings

            if settings.health_check_interval > 0:
                self._health_task = asyncio.create_task(self._health_loop())
            self._initialized = True

    async def close(self) -> None:
        if self._health_task:
            self._health_task.cancel()
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        logger.info("All connections closed.")

    # ── Health loop ──────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        from noble_agent.config import settings

        interval = settings.health_check_interval
        while True:
            await asyncio.sleep(interval)
            await self._check_and_reconnect()

    async def _check_and_reconnect(self) -> None:
        if self._redis:
            try:
                await self._redis.ping()
                self.redis_status = Status.CONNECTED
            except Exception:
                logger.warning("Redis health check failed — reconnecting")
                self.redis_status = Status.ERROR
                await self.connect_redis()

    # ── Health report ────────────────────────────────────────────────────

    async def health(self) -> dict:
        """Return per-service health dict for /health endpoint."""
        result: dict = {}
        if self._redis:
            try:
                await self._redis.ping()
                result["redis"] = "ok"
            except Exception as e:
                result["redis"] = f"error: {e}"
        else:
            result["redis"] = "not_configured"
        return result


# Singleton
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
