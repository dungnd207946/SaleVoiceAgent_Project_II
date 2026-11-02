"""_seed_sim_customer — env-driven telephony/app-client simulation seed."""

from __future__ import annotations

import re

from noble_agent.agent.facade import _seed_sim_customer
from noble_agent.storage.models import Customer

_VN = re.compile(r"^(0[35789])\d{8}$")


def test_fixed_phone_number_used():
    c, changed = _seed_sim_customer(Customer(), "0912345678", "")
    assert c.phone == "0912345678"
    assert changed is True


def test_random_phone_when_no_number_or_json():
    c, changed = _seed_sim_customer(Customer(), "", "")
    assert _VN.match(c.phone)
    assert changed is True


def test_app_client_fields_seeded():
    c, changed = _seed_sim_customer(
        Customer(), "0912345678", '{"name":"Hùng","gender":"M","project_interest":"NPTTL"}'
    )
    assert c.phone == "0912345678"
    assert c.name == "Hùng"
    assert c.gender == "M"
    assert c.project_interest == "NPTTL"
    assert changed is True


def test_number_env_wins_over_json_phone():
    c, _ = _seed_sim_customer(Customer(), "0911111111", '{"phone":"0922222222","name":"A"}')
    assert c.phone == "0911111111"
    assert c.name == "A"


def test_json_phone_is_fallback_when_no_number():
    c, _ = _seed_sim_customer(Customer(), "", '{"phone":"0922222222"}')
    assert c.phone == "0922222222"


def test_existing_phone_never_overwritten():
    c, changed = _seed_sim_customer(Customer(phone="0900000000"), "0912345678", "")
    assert c.phone == "0900000000"
    assert changed is False


def test_invalid_json_ignored_phone_still_set():
    c, changed = _seed_sim_customer(Customer(), "0912345678", "{not valid json")
    assert c.phone == "0912345678"
    assert c.name is None
    assert changed is True


def test_empty_values_skipped():
    c, _ = _seed_sim_customer(Customer(), "0912345678", '{"name":"","gender":"M"}')
    assert c.name is None
    assert c.gender == "M"


def test_invalid_field_value_drops_seed_but_keeps_phone():
    # gender must be M/F — an invalid value fails validation → seed ignored.
    c, changed = _seed_sim_customer(Customer(), "0912345678", '{"gender":"X","name":"A"}')
    assert c.phone == "0912345678"
    assert c.name is None
    assert c.gender is None


def test_unknown_fields_ignored():
    c, _ = _seed_sim_customer(Customer(), "0912345678", '{"name":"A","not_a_field":"x"}')
    assert c.name == "A"
    assert not hasattr(c, "not_a_field")
