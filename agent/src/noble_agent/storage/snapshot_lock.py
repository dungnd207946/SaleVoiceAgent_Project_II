"""Redis per-phone lock guarding the fire-and-forget snapshot merge.

Cross-process (aiortc / livekit / telephony are separate processes), so the lock
lives in Redis (already the session-state backend). The merge acquires the lock;
the next call from the same phone waits (bounded) for it to clear before it
bootstraps, so it reads the freshest snapshot.

This is an owner-token mutex, not an advisory flag: `acquire` uses `SET NX` so at
most one caller ever holds the lock at a time, and `release` only deletes the key
if it still holds the token that caller was issued (atomic Lua compare-and-delete)
— so a merge can never free a *different* merge's lock (e.g. after its own TTL
expired and a second merge already acquired). All ops log-and-continue: if Redis
is down, acquire returns None, release is a no-op, and wait reports "clear" so a
call is never blocked by a memory concern.
"""

from __future__ import annotations

import asyncio
import logging
import secrets

logger = logging.getLogger("noble_agent.storage.snapshot_lock")

_RELEASE_SCRIPT = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"


def _lock_key(phone: str) -> str:
    return f"snapshot:lock:{phone}"


async def acquire_snapshot_lock(phone: str, ttl_sec: int = 60) -> str | None:
    """Acquire the lock iff free (`SET NX EX`), self-healing via TTL if a merge crashes.

    Returns a random owner token on success, or None if already held by another
    merge (or Redis is unavailable). Best-effort."""
    if not phone:
        return None
    try:
        from noble_agent.storage.redis_client import get_redis

        client = await get_redis()
        if client is None:
            return None
        token = secrets.token_hex(16)
        ok = await client.set(_lock_key(phone), token, nx=True, ex=ttl_sec)
        return token if ok else None
    except Exception as exc:
        logger.warning("acquire_snapshot_lock failed: %s", exc)
        return None


async def release_snapshot_lock(phone: str, token: str) -> None:
    """Delete the lock only if it still holds `token`. Best-effort — safe in a finally."""
    if not phone or not token:
        return
    try:
        from noble_agent.storage.redis_client import get_redis

        client = await get_redis()
        if client is None:
            return
        await client.eval(_RELEASE_SCRIPT, 1, _lock_key(phone), token)
    except Exception as exc:
        logger.warning("release_snapshot_lock failed: %s", exc)


async def wait_snapshot_lock_clear(phone: str, max_wait_sec: float = 10.0, poll_sec: float = 0.5) -> bool:
    """Poll until the lock is absent or `max_wait_sec` elapses.

    Returns True if clear (immediately or after release), False on timeout.
    Redis errors → True (unblock the call). Never waits longer than max_wait_sec.
    """
    if not phone:
        return True
    try:
        from noble_agent.storage.redis_client import get_redis

        client = await get_redis()
        if client is None:
            return True
        waited = 0.0
        while waited < max_wait_sec:
            if not await client.exists(_lock_key(phone)):
                return True
            await asyncio.sleep(poll_sec)
            waited += poll_sec
        logger.warning("wait_snapshot_lock_clear: timeout phone=%s after %.1fs", phone, max_wait_sec)
        return False
    except Exception as exc:
        logger.warning("wait_snapshot_lock_clear failed: %s", exc)
        return True
