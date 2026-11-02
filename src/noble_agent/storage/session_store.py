"""Async session persistence — Redis hot state.

Redis keys (TTL = REDIS_SESSION_TTL_HOURS):
  session:{sid}:meta      — JSON: started_at, last_active
  session:{sid}:customer  — JSON: customer fields
  session:{sid}:state     — JSON: history + optional summary + scratchpad

Cross-session (by phone) profile reads/writes delegate to the Postgres data
plane (``storage/pg_data_plane.py``); Redis holds only the live session.

Fallback: if Redis is unavailable, returns safe defaults (empty dicts/lists).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger("session_store")


def _conn():
    from noble_agent.storage.connection import get_connection_manager

    return get_connection_manager()


def _ttl_seconds() -> int:
    from noble_agent.config import settings

    return settings.redis_session_ttl_hours * 3600


# ── Redis helpers ────────────────────────────────────────────────────────────


async def _redis_get(key: str) -> dict:
    r = _conn().redis
    if not r:
        return {}
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else {}
    except Exception as exc:
        logger.warning("Redis GET %s failed: %s", key, exc)
        return {}


async def _redis_mget(keys: list[str]) -> list[dict]:
    """Batch-GET multiple Redis keys in a single round-trip (pipeline)."""
    r = _conn().redis
    if not r or not keys:
        return [{} for _ in keys]
    try:
        async with r.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.get(key)
            results = await pipe.execute()
        return [json.loads(raw) if raw else {} for raw in results]
    except Exception as exc:
        logger.warning("Redis MGET %s failed: %s", keys, exc)
        return [{} for _ in keys]


async def _redis_set(key: str, data: dict) -> None:
    r = _conn().redis
    if not r:
        return
    try:
        await r.set(key, json.dumps(data, ensure_ascii=False), ex=_ttl_seconds())
    except Exception as exc:
        logger.warning("Redis SET %s failed: %s", key, exc)


# ── Meta ─────────────────────────────────────────────────────────────────────


async def upsert_meta(session_id: str, **kwargs) -> None:
    """Upsert Redis meta blob in the unified Meta schema.

    Writes `started_at` (set once via setdefault) + `last_active` so the same
    Redis key parses cleanly through `storage.repo.StateRepo` which validates
    against `storage.models.Meta`. Extra kwargs (e.g. legacy `label`) are
    accepted but pydantic v2 ignores unknown fields on read.
    """
    key = f"session:{session_id}:meta"
    meta = await _redis_get(key)
    now_iso = datetime.now(UTC).isoformat()
    meta["session_id"] = session_id
    meta["last_active"] = now_iso
    # New canonical field is `started_at`. Migrate legacy blobs that still
    # carry `created_at` so we don't lose the original timestamp.
    if "started_at" not in meta:
        meta["started_at"] = meta.get("created_at", now_iso)
    meta.pop("created_at", None)
    meta.update(kwargs)
    await _redis_set(key, meta)


async def load_meta(session_id: str) -> dict:
    meta = await _redis_get(f"session:{session_id}:meta")
    if not meta:
        return {"session_id": session_id}
    return meta


# ── History (Redis state key) ───────────────────────────────────────────────


async def load_history_from_state(session_id: str) -> list[dict]:
    """Return the unified turn history from the Redis state key.

    The unified agent stores conversation history in Redis
    (``session:{sid}:state`` via ``StateRepo``). Session-end summary generation
    must read from here to see real turns. System messages are excluded (they
    carry the prompt, not dialog). Safe defaults to ``[]`` on any read/parse error.
    """
    state = await _redis_get(f"session:{session_id}:state")
    history = state.get("history", []) if isinstance(state, dict) else []
    return [m for m in history if isinstance(m, dict) and m.get("role") != "system"]


# ── Customer (Redis) ────────────────────────────────────────────────────────

_CUSTOMER_DEFAULTS: dict = {
    "name": "",
    "full_name": "",
    "gender": "",
    "phone": "",
    "project_interest": "",
    "purpose": "",
    "budget": "",
    "preferred_area": "",
    "bedroom_count": "",
    "is_buyer": False,
    "is_noble_customer": False,
    "noble_info": "",
    # Part 7: Noble enrichment (appended — load_customer merge stays backward-compat)
    "email": "",
    "noble_user_id": "",
    "source": "",  # "noble_api" | "speech" | "seed" | "manual" | "legacy"
    "enriched_at": "",  # ISO datetime string, empty if not enriched
    "birthday": "",  # DD/MM/YYYY from Noble SearchUser (plaintext; PII — see spec §10)
}


async def save_customer(
    session_id: str,
    customer: dict,
    _existing: dict | None = None,
) -> None:
    """Merge `customer` into the Redis JSON blob.

    Truthy filter (`isinstance(v, bool) or v`) keeps name/gender/etc. safe from
    overwrite by empty strings out of partial calls — preserved verbatim.

    Persisted blob holds ONLY truthy fields (or explicit bools). Empty-string
    defaults from `_CUSTOMER_DEFAULTS` are stripped before write so the same
    Redis key parses cleanly through `storage.models.Customer` (which has
    e.g. `gender: Literal["M","F"] | None` — empty strings would crash
    `StateRepo.load`).

    `_existing` is an optional caller-supplied snapshot of the current customer
    dict. Pass it when the caller already loaded the customer earlier in the
    same turn — saves one Redis GET (~RTT). Stale-read risk is bounded: per-
    session writes are sequential (single voice call) except the existing
    Noble-enrich background task, which had this race even before this kwarg.
    """
    key = f"session:{session_id}:customer"
    # Read RAW (no defaults-merge) so we don't bake defaults into the persisted
    # blob. The defaults-merge in `load_customer` is for legacy in-memory
    # readers only.
    if _existing is not None:
        existing = dict(_existing)
    else:
        existing = await _redis_get(key)
    for k, v in customer.items():
        if isinstance(v, bool) or v:
            existing[k] = v
    # Strip empty-string defaults — Customer model rejects "" for Literal
    # fields (gender, etc.). Keeps False booleans (is_buyer / is_noble_customer).
    clean = {k: v for k, v in existing.items() if isinstance(v, bool) or v}
    await _redis_set(key, clean)


async def load_customer(session_id: str) -> dict:
    data = await _redis_get(f"session:{session_id}:customer")
    return {**_CUSTOMER_DEFAULTS, **data} if data else dict(_CUSTOMER_DEFAULTS)


# ── Cross-session customer profile (Postgres, keyed by phone) ───────────────


async def load_customer_by_phone(phone: str) -> dict:
    """Look up the structured customer profile by phone (cross-session, SP-E2 Postgres).

    Used at call start to preload profile so agent greets by name. Returns empty
    dict if phone unknown or Postgres unavailable — callers must tolerate.
    """
    from noble_agent.storage.pg_data_plane import read_customer_profile

    return await read_customer_profile(phone)


async def load_latest_booking_hint_by_phone(phone: str) -> dict:
    """Most-recent appointment for ``phone`` → ``{customer_name, project}`` (SP-E2, Postgres).

    Fallback profile source at call start when the contact profile lacks a
    name/project. Empty dict if none or Postgres unavailable — callers tolerate.
    """
    from noble_agent.storage.pg_data_plane import read_latest_booking_hint

    return await read_latest_booking_hint(phone)


async def save_customer_persistent(phone: str, data: dict) -> None:
    """Upsert the structured customer profile by phone (SP-E2, Postgres contacts.profile).

    Delegates to the PG wrapper, which truthy-merges (only truthy/explicit-bool
    fields) so an incomplete call never overwrites existing name/gender, and applies
    a "No Name" display default insert-only. Called at end of each call.
    """
    from noble_agent.storage.pg_data_plane import persist_customer_profile

    await persist_customer_profile(phone, data)


# ── Agent state (Redis) ─────────────────────────────────────────────────────


async def save_state(session_id: str, updates: dict) -> None:
    key = f"session:{session_id}:state"
    state = await _redis_get(key)
    state.update(updates)
    await _redis_set(key, state)


async def load_state(session_id: str) -> dict:
    return await _redis_get(f"session:{session_id}:state")


async def load_session_context(session_id: str) -> tuple[dict, dict, dict]:
    """Load customer, state, and meta in a single Redis round-trip.

    Returns (customer, state, meta) dicts — used during session init and
    prompt building to avoid sequential Redis calls.
    """
    keys = [
        f"session:{session_id}:customer",
        f"session:{session_id}:state",
        f"session:{session_id}:meta",
    ]
    customer_raw, state, meta = await _redis_mget(keys)
    customer = {**_CUSTOMER_DEFAULTS, **customer_raw} if customer_raw else dict(_CUSTOMER_DEFAULTS)
    if not meta:
        meta = {"session_id": session_id}
    return customer, state, meta
