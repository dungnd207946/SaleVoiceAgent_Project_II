"""Redis-backed storage for the per-session semantic cache."""

from __future__ import annotations

import json
import logging

from noble_agent.semcache.models import CacheBundle

logger = logging.getLogger("noble_agent.semcache.store")


def _key(sid: str) -> str:
    return f"session:{sid}:semcache"


async def load_bundle(redis, sid: str) -> CacheBundle | None:
    """Return the cached bundle for ``sid`` or ``None`` if absent/corrupt."""
    try:
        raw = await redis.get(_key(sid))
    except Exception:
        logger.exception("semcache.store: redis.get failed")
        return None
    if not raw:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return CacheBundle.model_validate(json.loads(raw))
    except Exception:
        logger.warning("semcache.store: corrupt bundle for %s; dropping", sid)
        return None


async def save_bundle(redis, sid: str, bundle: CacheBundle, ttl_seconds: int) -> None:
    try:
        payload = bundle.model_dump_json()
        await redis.set(_key(sid), payload, ex=ttl_seconds)
    except Exception:
        logger.exception("semcache.store: redis.set failed")


async def delete_bundle(redis, sid: str) -> None:
    try:
        await redis.delete(_key(sid))
    except Exception:
        logger.exception("semcache.store: redis.delete failed")
