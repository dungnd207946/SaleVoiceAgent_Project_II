"""booking schedule/modify write name+phone through the PG appointment persist + emit booking_created."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from noble_agent.agent.tools import booking
from noble_agent.storage import persist, pg_data_plane
from noble_agent.storage.models import Customer, State


def _future_date() -> str:
    return (date.today() + timedelta(days=3)).strftime("%d/%m/%Y")


async def _drain():
    await asyncio.sleep(0)
    tasks = [t for t in persist._bg_tasks if not t.done()]
    if tasks:
        await asyncio.gather(*tasks)


@pytest.fixture
def persisted(monkeypatch):
    """Capture every booking dict handed to the PG appointment persist."""
    rows: list[dict] = []

    async def _persist(booking, session_id):
        rows.append({**booking, "_session_id": session_id})

    monkeypatch.setattr(pg_data_plane, "persist_appointment", _persist)
    return rows


async def _schedule(customer):
    return await booking.run(
        State(),
        customer,
        {
            "action": "schedule",
            "project_code": "NCLB",
            "preferred_date": _future_date(),
            "preferred_time": "09:00 - 10:00",
            "confirmed": True,
            "use_calling_phone": True,
            "use_profile_name": True,
        },
        session_id="s1",
    )


async def test_schedule_writes_name_phone_through_pg_persist(persisted):
    customer = Customer(name="Hùng", phone="0912345678", project_interest="NCLB")
    out = await _schedule(customer)
    await _drain()

    assert json.loads(out)["ok"] is True
    assert len(persisted) == 1
    row = persisted[0]
    assert row["phone"] == "0912345678"
    assert row["customer_name"] == "Hùng"
    assert row["project"] == "NCLB"
    assert row["appointment_id"].startswith("APT")
    assert row["_session_id"] == "s1"



async def test_schedule_no_name_defaults_to_no_name(persisted):
    # No name: the guard asks up to twice (shared state carries the counter);
    # the 3rd attempt auto-proceeds and persists "No Name".
    customer = Customer(phone="0987654321", project_interest="NCLB")
    state = State()
    args = {
        "action": "schedule",
        "project_code": "NCLB",
        "preferred_date": _future_date(),
        "preferred_time": "09:00 - 10:00",
        "confirmed": True,
        "use_calling_phone": True,
    }
    for _ in range(3):
        await booking.run(state, customer, args, session_id="s1")
    await _drain()

    assert persisted[-1]["customer_name"] == "No Name"


async def test_modify_carries_phone_and_name(persisted):
    customer = Customer(name="Lan", phone="0912345678", project_interest="NCLB")
    state = State()
    await booking.run(
        state,
        customer,
        {
            "action": "schedule",
            "project_code": "NCLB",
            "preferred_date": _future_date(),
            "preferred_time": "09:00 - 10:00",
            "confirmed": True,
            "use_calling_phone": True,
            "use_profile_name": True,
        },
        session_id="s1",
    )
    await _drain()
    appt_id = persisted[0]["appointment_id"]
    new_date = (date.today() + timedelta(days=5)).strftime("%d/%m/%Y")

    out = await booking.run(
        state,
        customer,
        {
            "action": "modify",
            "booking_id": appt_id,
            "new_preferred_date": new_date,
            "new_preferred_time": "14:00 - 15:00",
        },
        session_id="s1",
    )
    await _drain()

    assert json.loads(out)["ok"] is True
    # modify re-persists the SAME appointment_id (idempotent upsert, no dup row)
    last = persisted[-1]
    assert last["appointment_id"] == appt_id
    assert last["phone"] == "0912345678"
    assert last["customer_name"] == "Lan"
    assert last["preferred_date"] == new_date
