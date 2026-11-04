"""Redis per-phone snapshot lock: acquire / release / wait (clear + timeout)."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from noble_agent.storage import redis_client, snapshot_lock


@pytest.fixture(autouse=True)
def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis_for_tests(client)
    yield client
    redis_client.set_redis_for_tests(None)


async def test_acquire_then_release(fake_redis):
    token = await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    assert isinstance(token, str) and token
    assert await fake_redis.get("snapshot:lock:09") == token
    await snapshot_lock.release_snapshot_lock("09", token)
    assert await fake_redis.get("snapshot:lock:09") is None


async def test_acquire_second_while_held_returns_none(fake_redis):
    first_token = await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    second_token = await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    assert second_token is None
    # First token's value must survive untouched (NX did not overwrite it).
    assert await fake_redis.get("snapshot:lock:09") == first_token


async def test_release_with_wrong_token_does_not_delete(fake_redis):
    token = await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    await snapshot_lock.release_snapshot_lock("09", "wrong-token")
    assert await fake_redis.get("snapshot:lock:09") == token
    await snapshot_lock.release_snapshot_lock("09", token)
    assert await fake_redis.get("snapshot:lock:09") is None


async def test_wait_returns_true_when_already_clear():
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=1.0) is True


async def test_wait_times_out_while_held(fake_redis):
    await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    # Lock stays held → wait must time out and return False (bounded, not forever).
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=0.3, poll_sec=0.1) is False


async def test_wait_returns_true_after_release(fake_redis):
    token = await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    await snapshot_lock.release_snapshot_lock("09", token)
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=0.3, poll_sec=0.1) is True


async def test_ops_safe_when_redis_none(monkeypatch):
    # Redis unavailable → never raise; treat lock as clear so a call is never blocked.
    async def _none():
        return None

    monkeypatch.setattr(redis_client, "get_redis", _none)
    assert await snapshot_lock.acquire_snapshot_lock("09") is None
    await snapshot_lock.release_snapshot_lock("09", "tok")  # no raise
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=0.2) is True
