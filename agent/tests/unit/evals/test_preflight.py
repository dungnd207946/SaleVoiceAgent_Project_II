from __future__ import annotations

from evals.preflight import check_redis


async def test_check_redis_unreachable_returns_message(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # port 1: từ chối ngay
    err = await check_redis(timeout_s=0.5)
    assert err is not None and "Redis" in err
