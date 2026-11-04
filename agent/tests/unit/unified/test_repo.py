from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from noble_agent.storage.models import (
    Customer,
    Meta,
    State,
    ThreadMessage,
    ThreadSummary,
)
from noble_agent.storage.repo import StateRepo


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


async def test_load_fresh_session(repo):
    meta, customer, state = await repo.load("sid1")
    assert meta.session_id == "sid1"
    assert customer.name is None
    assert state.history == []
    assert state.summary is None


async def test_save_then_load_round_trip(repo):
    now = datetime.now(UTC)
    meta = Meta(session_id="sid2", started_at=now, last_active=now, phone="0901234567")
    customer = Customer(name="Hùng", project_interest="NCLB")
    state = State(history=[ThreadMessage(role="user", content="hi")])

    await repo.save_all("sid2", meta, customer, state)
    m2, c2, s2 = await repo.load("sid2")

    assert m2.phone == "0901234567"
    assert c2.name == "Hùng"
    assert c2.project_interest == "NCLB"
    assert len(s2.history) == 1
    assert s2.history[0].content == "hi"


async def test_ttl_is_set(repo, redis):
    now = datetime.now(UTC)
    meta = Meta(session_id="sid3", started_at=now, last_active=now)
    await repo.save_all("sid3", meta, Customer(), State())
    ttl = await redis.ttl("session:sid3:meta")
    assert 0 < ttl <= 3600


async def test_update_summary_writes_only_summary(repo):
    now = datetime.now(UTC)
    meta = Meta(session_id="sid4", started_at=now, last_active=now)
    customer = Customer(name="Lan")
    state = State(history=[ThreadMessage(role="user", content="m1")])
    await repo.save_all("sid4", meta, customer, state)

    new_summary = ThreadSummary(text="abc", covers_turns=1, updated_at=now)
    await repo.update_summary("sid4", new_summary)

    _, c2, s2 = await repo.load("sid4")
    assert c2.name == "Lan"
    assert len(s2.history) == 1
    assert s2.summary is not None
    assert s2.summary.text == "abc"
    assert s2.summary.covers_turns == 1


async def test_update_summary_on_missing_session_is_noop(repo):
    new_summary = ThreadSummary(text="x", covers_turns=0, updated_at=datetime.now(UTC))
    await repo.update_summary("never-existed", new_summary)
    _, _, s = await repo.load("never-existed")
    assert s.summary is None


async def test_load_self_heals_on_legacy_meta_schema(repo, redis):
    """Regression: legacy `session_store.upsert_meta` used to write
    `created_at` instead of `started_at`. StateRepo.load must NOT crash on
    that schema mismatch — it falls back to a fresh Meta so the turn still
    proceeds (and self-heals on the next save_all).
    """
    import json

    # Simulate a legacy blob still sitting in Redis from a prior session.
    legacy_meta = {
        "session_id": "legacy-sid",
        "created_at": "2026-06-03T10:00:00",  # legacy field
        "last_active": "2026-06-03T10:00:00",
    }
    await redis.set("session:legacy-sid:meta", json.dumps(legacy_meta))

    meta, customer, state = await repo.load("legacy-sid")
    assert meta.session_id == "legacy-sid"
    assert customer.name is None
    assert state.history == []


async def test_load_self_heals_on_garbage_customer_blob(repo, redis):
    """Regression: a poisoned customer blob (e.g. `gender=""` from the legacy
    gender-detector path) must NOT wedge every subsequent turn.
    """
    import json

    poisoned = {
        "name": "Hùng",
        "gender": "",  # Literal["M","F"]|None — empty string used to crash
    }
    await redis.set("session:poison-sid:customer", json.dumps(poisoned))

    _, customer, _ = await repo.load("poison-sid")
    # Self-heals by resetting to default Customer.
    assert customer.name is None
    assert customer.gender is None
