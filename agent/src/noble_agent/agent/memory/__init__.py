"""User-memory subpackage: cumulative per-caller snapshot keyed by phone.

Entry points used by the rest of the app (both guarded — memory must never break
a call):
  - update_snapshot_after_call(...) → merge + persist the snapshot at call end.
  - short_term_block(...)           → bootstrap context (snapshot + last-K turns).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("noble_agent.agent.memory")


async def update_snapshot_after_call(settings, *, phone: str, session_id: str, history: list[dict]) -> None:
    """Fire-and-forget at call end: lock → load old → merge → save → unlock.

    The lock makes the next call from the same phone wait for this merge. Always
    releases in `finally`; swallows all errors."""
    if not phone:
        return
    from noble_agent.agent.memory import snapshot as snap
    from noble_agent.storage import pg_data_plane, snapshot_lock

    ttl = int(getattr(settings, "snapshot_lock_ttl_sec", 60))
    token = await snapshot_lock.acquire_snapshot_lock(phone, ttl_sec=ttl)
    if token is None:
        # Another merge for this phone is already running (or Redis is down) — skip
        # rather than read-merge-write unlocked, which would risk a lost update.
        logger.info("update_snapshot_after_call: merge already in progress for phone, skipping session=%s", session_id)
        return
    try:
        old_text = await pg_data_plane.read_contact_snapshot(phone)
        new_text = await snap.merge_snapshot(old_text, history)
        if new_text:
            await pg_data_plane.persist_contact(phone, new_text)
    except Exception:
        logger.exception("update_snapshot_after_call failed session=%s", session_id)
    finally:
        await snapshot_lock.release_snapshot_lock(phone, token)


async def short_term_block(settings, *, phone: str, session_id: str) -> str:
    """Bootstrap block: wait for any in-flight merge (bounded), then build."""
    if not phone:
        return ""
    from noble_agent.agent.memory import snapshot as snap
    from noble_agent.storage import snapshot_lock

    try:
        wait_sec = float(getattr(settings, "snapshot_lock_wait_sec", 10.0))
        await snapshot_lock.wait_snapshot_lock_clear(phone, max_wait_sec=wait_sec)
        return await snap.build_short_term_context(settings, phone, session_id)
    except Exception:
        logger.exception("short_term_block failed session=%s", session_id)
        return ""


__all__ = ["update_snapshot_after_call", "short_term_block"]
