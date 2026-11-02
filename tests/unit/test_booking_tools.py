"""Test booking tool logic (unified single-agent).

``schedule_viewing`` is the callable in ``agent/tools/schedule_viewing.py``
(``agent/tools/booking.py`` is the ``action``-routing module the dispatcher calls,
which forwards ``action="schedule"`` here). Signature is
``(state, customer, args: dict, session_id: str) -> str`` and it returns a JSON
string. On success it mutates the shared ``Customer`` in place (the customer-sync
seam) and records the booking in ``state.scratchpad`` + a best-effort Postgres
appointment row (a no-op when Postgres is unconfigured).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from noble_agent.agent.tools.schedule_viewing import schedule_viewing
from noble_agent.storage.models import Customer, State


class TestScheduleViewing:
    @pytest.mark.asyncio
    async def test_unconfirmed_rejected(self):
        raw = await schedule_viewing(
            State(),
            Customer(),
            {"project": "NCLB", "preferred_date": "01/01/2027", "preferred_time": "10:00", "confirmed": False},
            session_id="test",
        )
        result = json.loads(raw)
        assert result["success"] is False
        assert "xác nhận" in result["error"]

    @pytest.mark.asyncio
    async def test_confirmed_writes_name_phone_from_customer(self):
        state = State()
        customer = Customer(name="Hùng", phone="0912345678")
        with patch("noble_agent.storage.pg_data_plane.persist_appointment", new_callable=AsyncMock):
            raw = await schedule_viewing(
                state,
                customer,
                {"project": "NCLB", "preferred_date": "01/01/2027", "preferred_time": "10:00",
                 "confirmed": True, "use_calling_phone": True, "use_profile_name": True},
                session_id="s1",
            )
        result = json.loads(raw)
        assert result["success"] is True
        assert result["appointment_id"].startswith("APT")
        # Project synced (dirty-signal); name+phone now read from the Customer.
        assert customer.project_interest == "NCLB"
        stored = json.loads(state.scratchpad["bookings"])
        assert len(stored) == 1
        assert stored[0]["project"] == "NCLB"
        assert stored[0]["phone"] == "0912345678"
        assert stored[0]["customer_name"] == "Hùng"

    @pytest.mark.asyncio
    async def test_confirmed_defaults_name_to_no_name_after_two_asks(self):
        # New guard: an empty customer is asked for name/phone up to twice; the
        # 3rd schedule attempt auto-proceeds with "No Name" + the calling number
        # (empty here, since the simulated customer has no phone).
        state = State()
        customer = Customer()
        args = {"project": "NCLB", "preferred_date": "01/01/2027", "preferred_time": "10:00", "confirmed": True}
        with patch("noble_agent.storage.pg_data_plane.persist_appointment", new_callable=AsyncMock):
            assert json.loads(await schedule_viewing(state, customer, args, session_id="s1")).get("needs_info") is True
            assert json.loads(await schedule_viewing(state, customer, args, session_id="s1")).get("needs_info") is True
            raw = await schedule_viewing(state, customer, args, session_id="s1")
        assert json.loads(raw)["success"] is True
        stored = json.loads(state.scratchpad["bookings"])
        assert stored[0]["customer_name"] == "No Name"
        assert stored[0]["phone"] == ""

    @pytest.mark.asyncio
    async def test_project_pulled_from_customer_interest(self):
        state = State()
        customer = Customer(full_name="Test", phone="0912345678")
        customer.project_interest = "SLC"
        with patch("noble_agent.storage.pg_data_plane.persist_appointment", new_callable=AsyncMock):
            raw = await schedule_viewing(
                state,
                customer,
                {"preferred_date": "01/01/2027", "preferred_time": "10:00",
                 "confirmed": True, "use_calling_phone": True, "use_profile_name": True},
                session_id="s2",
            )
        result = json.loads(raw)
        assert result["success"] is True
        assert result["project"] == "SLC"

    @pytest.mark.asyncio
    async def test_missing_project_errors(self):
        raw = await schedule_viewing(
            State(),
            Customer(),
            {"preferred_date": "01/01/2027", "preferred_time": "10:00", "confirmed": True},
            session_id="s3",
        )
        result = json.loads(raw)
        assert result["success"] is False
        blob = (result.get("message", "") + " ".join(result.get("errors", []))).lower()
        assert "dự án" in blob
