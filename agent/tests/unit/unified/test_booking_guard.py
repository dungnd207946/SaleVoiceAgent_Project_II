"""Booking schedule guard: name + phone are both mandatory, confirmed per-booking.

Name mirrors phone exactly:
* ``name="..."``          — caller read out a name for the booking.
* ``use_profile_name=True`` — caller confirmed using the session profile's name.
* ``use_calling_phone=True`` / ``phone="..."`` — the phone equivalents.

The guard asks up to twice; the 3rd attempt auto-proceeds with the profile name
(or "No Name") + the calling number. The booking name is decoupled from the
session ``Customer`` — a name read for the booking never mutates the profile.
"""

from __future__ import annotations

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


def _sched(**extra):
    args = {"project": "NCLB", "preferred_date": "31/12/2030", "preferred_time": "09:00 - 10:00", "confirmed": True}
    args.update(extra)
    return args


async def _run(state, customer, **extra):
    return json.loads(await sv.schedule_viewing(state, customer, _sched(**extra), "sid-g"))


# ── Guard: blocks with a specific guiding message ───────────────────────────


async def test_no_name_no_phone_blocks_case_a():
    state, customer = State(), Customer(phone="0912345678", full_name="Trần Ngọc Dự")  # profile has a name
    out = await _run(state, customer)  # but nothing confirmed for THIS booking
    assert out["success"] is False
    assert out.get("needs_info") is True
    assert "tên" in out["message"].lower() and "số" in out["message"].lower()
    assert not sv._load_bookings(state)  # nothing scheduled
    assert state.scratchpad["booking_guard_attempts"] == 1


async def test_has_name_no_phone_blocks_case_b():
    state, customer = State(), Customer(phone="0912345678")
    out = await _run(state, customer, name="chị Lan")
    assert out.get("needs_info") is True
    assert "số điện thoại" in out["message"].lower()
    assert "tên" not in out["message"].lower()


async def test_phone_confirmed_no_name_blocks_case_c():
    state, customer = State(), Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _run(state, customer, use_calling_phone=True)
    assert out.get("needs_info") is True
    assert "tên" in out["message"].lower()


# ── Guard: proceeds when satisfied ──────────────────────────────────────────


async def test_use_profile_name_and_calling_phone_schedules():
    state, customer = State(), Customer(phone="0912345678", name="Dự", full_name="Trần Ngọc Dự")
    out = await _run(state, customer, use_profile_name=True, use_calling_phone=True)
    assert out["success"] is True
    b = sv._load_bookings(state)[-1]
    assert b["phone"] == "0912345678"
    # full_name-first: matches the CUSTOMER_PROFILE block the agent reads ("Tên: full_name or name"),
    # so what the agent verbalises == what gets stored.
    assert b["customer_name"] == "Trần Ngọc Dự"
    assert state.scratchpad["booking_guard_attempts"] == 0  # reset on success


async def test_given_name_schedules_and_leaves_customer_untouched():
    # Booking for a third party: the read-out name lands on the booking only,
    # never on the session Customer profile.
    state, customer = State(), Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _run(state, customer, name="vợ anh Dự", use_calling_phone=True)
    assert out["success"] is True
    assert sv._load_bookings(state)[-1]["customer_name"] == "vợ anh Dự"
    assert customer.name is None  # profile NOT mutated
    assert customer.full_name == "Trần Ngọc Dự"


async def test_given_phone_with_name_schedules_with_that_number():
    state, customer = State(), Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _run(state, customer, name="chị Lan", phone="0987654321")
    assert out["success"] is True
    b = sv._load_bookings(state)[-1]
    assert b["phone"] == "0987654321"
    assert b["customer_name"] == "chị Lan"


# ── Guard: 2-attempt cap → auto-proceed with profile name + caller number ───


async def test_two_attempt_cap_auto_schedules_profile_name_calling_number():
    state, customer = State(), Customer(phone="0912345678", full_name="Trần Ngọc Dự")  # never confirms
    assert (await _run(state, customer)).get("needs_info") is True  # attempt 1
    assert (await _run(state, customer)).get("needs_info") is True  # attempt 2
    out = await _run(state, customer)  # attempt 3 → auto
    assert out["success"] is True
    b = sv._load_bookings(state)[-1]
    assert b["customer_name"] == "Trần Ngọc Dự"  # fallback to profile name
    assert b["phone"] == "0912345678"  # calling number
    assert state.scratchpad["booking_guard_attempts"] == 0


async def test_two_attempt_cap_no_profile_name_defaults_no_name():
    state, customer = State(), Customer(phone="0912345678")  # no name anywhere
    for _ in range(2):
        assert (await _run(state, customer)).get("needs_info") is True
    out = await _run(state, customer)
    assert out["success"] is True
    assert sv._load_bookings(state)[-1]["customer_name"] == "No Name"


async def test_use_profile_name_without_profile_name_still_asks():
    # Agent sets use_profile_name=true prematurely but the profile has NO name →
    # the flag is meaningless, so the tool must keep asking (NOT short-circuit to
    # "No Name") until the 2-ask cap; only the 3rd attempt auto-proceeds.
    state, customer = State(), Customer(phone="0912345678")  # no name in profile
    assert (await _run(state, customer, use_profile_name=True, use_calling_phone=True)).get("needs_info") is True
    assert (await _run(state, customer, use_profile_name=True, use_calling_phone=True)).get("needs_info") is True
    out = await _run(state, customer, use_profile_name=True, use_calling_phone=True)
    assert out["success"] is True
    assert sv._load_bookings(state)[-1]["customer_name"] == "No Name"


async def test_use_calling_phone_without_calling_number_still_asks():
    # use_calling_phone=true but the profile has no calling number → keep asking.
    state, customer = State(), Customer(full_name="Trần Ngọc Dự")  # name but no phone
    out = await _run(state, customer, use_profile_name=True, use_calling_phone=True)
    assert out.get("needs_info") is True
    assert "số điện thoại" in out["message"].lower()


# ── Invalid phone still rejected up front ───────────────────────────────────


async def test_invalid_given_phone_rejected():
    state, customer = State(), Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _run(state, customer, name="chị Lan", phone="123")
    assert out["success"] is False
    assert "điện thoại" in out["error"].lower()


# ── modify: change only what's given, keep the rest (never wipe) ────────────


async def _seed_booking(state, **over):
    """Schedule one booking and return its appointment_id."""
    customer = Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _run(state, customer, use_profile_name=True, use_calling_phone=True)
    return out["appointment_id"]


async def _modify(state, customer, **args):
    return json.loads(await sv.modify_booking(state, customer, {"action": "modify", **args}))


async def test_modify_name_only_keeps_date_time_phone():
    state = State()
    appt = await _seed_booking(state)
    cust = Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _modify(state, cust, booking_id=appt, name="Linh")
    assert out["success"] is True
    b = sv._load_bookings(state)[-1]
    assert b["customer_name"] == "Linh"  # changed
    assert b["preferred_date"] == "31/12/2030"  # NOT wiped
    assert b["preferred_time"] == "09:00 - 10:00"
    assert b["phone"] == "0912345678"  # kept


async def test_modify_phone_only_validated_and_keeps_rest():
    state = State()
    appt = await _seed_booking(state)
    cust = Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _modify(state, cust, booking_id=appt, phone="0386 081 255")
    assert out["success"] is True
    b = sv._load_bookings(state)[-1]
    assert b["phone"] == "0386081255"  # cleaned + changed
    assert b["customer_name"] == "Trần Ngọc Dự"  # kept
    assert b["preferred_date"] == "31/12/2030"  # NOT wiped


async def test_modify_name_and_phone_together():
    state = State()
    appt = await _seed_booking(state)
    cust = Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _modify(state, cust, booking_id=appt, name="Linh", phone="0386081255")
    assert out["success"] is True
    b = sv._load_bookings(state)[-1]
    assert b["customer_name"] == "Linh"
    assert b["phone"] == "0386081255"
    assert b["preferred_date"] == "31/12/2030"
    # result echoes the STORED values so the agent can't hallucinate
    assert out["customer_name"] == "Linh"
    assert out["phone"] == "0386081255"


async def test_modify_date_only_keeps_name_phone():
    state = State()
    appt = await _seed_booking(state)
    cust = Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _modify(state, cust, booking_id=appt, new_preferred_date="30/12/2030")
    assert out["success"] is True
    b = sv._load_bookings(state)[-1]
    assert b["preferred_date"] == "30/12/2030"  # changed
    assert b["preferred_time"] == "09:00 - 10:00"  # kept
    assert b["customer_name"] == "Trần Ngọc Dự"  # kept
    assert b["phone"] == "0912345678"  # kept


async def test_modify_rejects_invalid_phone():
    state = State()
    appt = await _seed_booking(state)
    cust = Customer(phone="0912345678", full_name="Trần Ngọc Dự")
    out = await _modify(state, cust, booking_id=appt, phone="123")
    assert out["success"] is False
    assert "điện thoại" in out["error"].lower()
    assert sv._load_bookings(state)[-1]["phone"] == "0912345678"  # unchanged
