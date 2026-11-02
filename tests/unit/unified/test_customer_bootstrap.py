from noble_agent.agent.customer_bootstrap import bootstrap_customer_profile
from noble_agent.storage import session_store
from noble_agent.storage.models import Customer


def _patch(monkeypatch, profile: dict, hint: dict):
    async def _prof(phone):
        return profile

    async def _hint(phone):
        return hint

    monkeypatch.setattr(session_store, "load_customer_by_phone", _prof)
    monkeypatch.setattr(session_store, "load_latest_booking_hint_by_phone", _hint)


async def test_no_phone_is_noop(monkeypatch):
    called = {"prof": False}

    async def _prof(phone):
        called["prof"] = True
        return {}

    monkeypatch.setattr(session_store, "load_customer_by_phone", _prof)
    c = Customer()
    await bootstrap_customer_profile(c)
    assert called["prof"] is False
    assert c.name is None


async def test_merges_customers_doc(monkeypatch):
    _patch(monkeypatch, {"name": "Hùng", "gender": "M", "project_interest": "NCLB"}, {})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name == "Hùng"
    assert c.gender == "M"
    assert c.project_interest == "NCLB"
    assert c.phone == "0901234567"  # untouched


async def test_booking_hint_fills_missing_name_and_project(monkeypatch):
    _patch(monkeypatch, {}, {"customer_name": "Lan", "project": "NCLB"})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name == "Lan"
    assert c.project_interest == "NCLB"


async def test_customers_doc_wins_over_booking_hint(monkeypatch):
    _patch(monkeypatch, {"name": "Hùng"}, {"customer_name": "Lan", "project": "SLC"})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name == "Hùng"  # customers doc wins
    assert c.project_interest == "SLC"  # project only in hint → used


async def test_unknown_project_dropped(monkeypatch):
    _patch(monkeypatch, {"project_interest": "not-a-code"}, {})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.project_interest is None


async def test_empty_db_leaves_only_phone(monkeypatch):
    _patch(monkeypatch, {}, {})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name is None
    assert c.phone == "0901234567"
