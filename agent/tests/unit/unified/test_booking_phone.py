import json

import pytest

from noble_agent.agent.tools import schedule_viewing as sv
from noble_agent.storage.models import Customer, State


@pytest.fixture(autouse=True)
def _no_mongo(monkeypatch):
    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(sv, "_persist_flat", _noop)
    monkeypatch.setattr("noble_agent.storage.persist.fire_and_forget", lambda coro: coro.close())


async def test_booking_defaults_to_caller_phone():
    state = State()
    customer = Customer(phone="0901234567", full_name="Test")
    out = json.loads(
        await sv.schedule_viewing(
            state, customer,
            {"project": "NCLB", "preferred_date": "31/12/2030", "preferred_time": "09:00 - 10:00",
             "confirmed": True, "use_calling_phone": True, "use_profile_name": True},
            "sid-1",
        )
    )
    assert out["success"] is True
    bookings = json.loads(state.scratchpad["bookings"])
    assert bookings[-1]["phone"] == "0901234567"
    assert customer.phone == "0901234567"


async def test_booking_uses_explicit_phone_without_touching_customer():
    state = State()
    customer = Customer(phone="0901234567", full_name="Test")
    await sv.schedule_viewing(
        state, customer,
        {"project": "NCLB", "preferred_date": "31/12/2030", "preferred_time": "09:00 - 10:00",
         "confirmed": True, "phone": "0912 345 678", "use_profile_name": True},
        "sid-2",
    )
    bookings = json.loads(state.scratchpad["bookings"])
    assert bookings[-1]["phone"] == "0912345678"  # cleaned
    assert customer.phone == "0901234567"  # caller-ID identity untouched


async def test_booking_rejects_invalid_phone():
    state = State()
    customer = Customer(phone="0901234567")
    out = json.loads(
        await sv.schedule_viewing(
            state, customer,
            {"project": "NCLB", "preferred_date": "31/12/2030", "preferred_time": "09:00 - 10:00",
             "confirmed": True, "phone": "123"},
            "sid-3",
        )
    )
    assert out["success"] is False
    assert "điện thoại" in out["error"].lower()


async def test_booking_run_forwards_explicit_phone_to_row():
    from noble_agent.agent.tools import booking

    state = State()
    customer = Customer(phone="0901234567", full_name="Test")
    await booking.run(
        state,
        customer,
        {"action": "schedule", "project_code": "NCLB", "preferred_date": "31/12/2030",
         "preferred_time": "09:00 - 10:00", "confirmed": True, "phone": "0912 345 678",
         "use_profile_name": True},
        session_id="sid-router",
    )
    bookings = json.loads(state.scratchpad["bookings"])
    assert bookings[-1]["phone"] == "0912345678"  # reached the row through the router
    assert customer.phone == "0901234567"  # identity untouched
