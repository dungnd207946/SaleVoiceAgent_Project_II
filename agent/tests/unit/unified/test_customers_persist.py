"""save_customer_persistent delegates to the PG contacts.profile wrapper (SP-E2).

The truthy-merge + "No Name" insert-only default now live in
``pg_data_plane.persist_customer_profile`` (see test_pg_customer_profile.py); this
guards that session_store forwards the (phone, data) through to it unchanged.
"""

from __future__ import annotations

from noble_agent.storage import pg_data_plane, session_store


async def test_delegates_to_pg_persist(monkeypatch):
    seen: list[tuple] = []

    async def _persist(phone, data):
        seen.append((phone, data))

    monkeypatch.setattr(pg_data_plane, "persist_customer_profile", _persist)
    await session_store.save_customer_persistent("0912345678", {"budget": "3 tỷ"})
    assert seen == [("0912345678", {"budget": "3 tỷ"})]
