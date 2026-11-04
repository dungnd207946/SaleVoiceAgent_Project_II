"""load_latest_booking_hint_by_phone delegates to the PG appointment hint (SP-E2)."""

from noble_agent.storage import pg_data_plane, session_store


async def test_hint_delegates_to_pg(monkeypatch):
    async def _read(phone):
        assert phone == "0901234567"
        return {"customer_name": "Hùng", "project": "NCLB"}

    monkeypatch.setattr(pg_data_plane, "read_latest_booking_hint", _read)
    hint = await session_store.load_latest_booking_hint_by_phone("0901234567")
    assert hint == {"customer_name": "Hùng", "project": "NCLB"}


async def test_hint_empty_passthrough(monkeypatch):
    async def _read(phone):
        return {}

    monkeypatch.setattr(pg_data_plane, "read_latest_booking_hint", _read)
    assert await session_store.load_latest_booking_hint_by_phone("0901234567") == {}
