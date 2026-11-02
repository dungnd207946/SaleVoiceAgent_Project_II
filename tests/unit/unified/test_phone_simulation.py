"""Phone simulation + session-start (facade.ensure_session_started).

Covers _random_vn_mobile format and the "simulate only when empty" rule that
leaves a telephony-seeded real number intact.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest

from noble_agent.agent import facade
from noble_agent.storage.models import Customer, Meta, State
from noble_agent.storage.repo import StateRepo

_PHONE_RE = re.compile(r"^(0[35789])\d{8}$")


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


def _agent(repo):
    return facade.NobleAgent(session_id="sid-P", runner=MagicMock(_repo=repo))


def _settings(simulate: bool):
    # simulate_phone_number / simulate_customer default to "" (their real
    # config defaults); an unset MagicMock attr would be a MagicMock, not a str.
    return MagicMock(noble_simulate_phone=simulate, simulate_phone_number="", simulate_customer="")


def test_random_vn_mobile_matches_regex():
    for _ in range(200):
        p = facade._random_vn_mobile()
        assert _PHONE_RE.match(p), f"bad phone: {p}"


async def test_ensure_session_started_simulates_when_empty(repo, monkeypatch):
    monkeypatch.setattr(facade, "get_settings", lambda: _settings(True))

    await _agent(repo).ensure_session_started()

    meta, customer, _ = await repo.load("sid-P")
    assert customer.phone and _PHONE_RE.match(customer.phone)
    assert meta.phone == customer.phone


async def test_ensure_session_started_preserves_seeded_phone(repo, monkeypatch):
    monkeypatch.setattr(facade, "get_settings", lambda: _settings(True))
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    await repo.save_all(
        "sid-P",
        Meta(session_id="sid-P", started_at=now, last_active=now, phone="0912345678"),
        Customer(phone="0912345678"),
        State(),
    )

    await _agent(repo).ensure_session_started()

    meta, customer, _ = await repo.load("sid-P")
    assert customer.phone == "0912345678"
    assert meta.phone == "0912345678"


async def test_ensure_session_started_noop_when_disabled(repo, monkeypatch):
    monkeypatch.setattr(facade, "get_settings", lambda: _settings(False))

    await _agent(repo).ensure_session_started()

    _, customer, _ = await repo.load("sid-P")
    assert not customer.phone
