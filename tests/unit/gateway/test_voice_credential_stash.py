"""``gateway/server.py::_stash_voice_credentials`` — stash Fernet-encrypted PG
credential vào Redis nội bộ trước khi dispatch voice. Best-effort: mọi điều
kiện thiếu -> bỏ qua im lặng, mọi exception từ Redis/stash -> nuốt (log warning),
không bao giờ raise trên đường dispatch.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from noble_agent.gateway import server as s
from noble_agent.gateway.credentials import RuntimeCredentials


def _creds(**overrides) -> RuntimeCredentials:
    base = dict(
        tenant_id="acme",
        postgres_role="agent_acme",
        postgres_password="pw",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    base.update(overrides)
    return RuntimeCredentials(**base)


def _settings(secret="topsecret"):
    return SimpleNamespace(gateway_worker_secret=secret)


class _Sentinel:
    """Stand-in redis client returned by the patched get_redis()."""


async def test_stash_voice_credentials_happy_path(monkeypatch):
    calls = []
    redis_obj = _Sentinel()

    async def fake_get_redis():
        return redis_obj

    async def fake_stash(redis, secret, tenant_id, **kwargs):
        calls.append((redis, secret, tenant_id, kwargs))
        return True

    monkeypatch.setattr("noble_agent.storage.redis_client.get_redis", fake_get_redis)
    monkeypatch.setattr("noble_agent.storage.credential_stash.stash", fake_stash)

    creds = _creds()
    await s._stash_voice_credentials(_settings("topsecret"), "acme", creds)

    assert len(calls) == 1
    redis, secret, tenant_id, kwargs = calls[0]
    assert redis is redis_obj
    assert secret == "topsecret"
    assert tenant_id == "acme"
    # `deployment_id`/`kind` rời payload stash ở `0941`/`0919` — xem `credential_stash.stash`.
    assert kwargs == {
        "role": "agent_acme",
        "password": "pw",
        "expires_at": creds.expires_at,
        "agent_key_id": "",
    }


async def test_stash_voice_credentials_forwards_agent_key_id(monkeypatch):
    calls = []

    async def fake_get_redis():
        return _Sentinel()

    async def fake_stash(redis, secret, tenant_id, **kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr("noble_agent.storage.redis_client.get_redis", fake_get_redis)
    monkeypatch.setattr("noble_agent.storage.credential_stash.stash", fake_stash)

    await s._stash_voice_credentials(_settings(), "acme", _creds(agent_key_id="ak_9"))

    assert calls[0]["agent_key_id"] == "ak_9"


@pytest.mark.parametrize(
    "make_args",
    [
        lambda: (_settings(), "acme", None),
        lambda: (_settings(), "acme", _creds(postgres_role="")),
        lambda: (_settings(), "acme", _creds(postgres_password="")),
        lambda: (_settings(secret=""), "acme", _creds()),
        lambda: (_settings(), "acme", _creds(expires_at=None)),
    ],
    ids=[
        "credentials_none",
        "postgres_role_empty",
        "postgres_password_empty",
        "gateway_worker_secret_empty",
        "expires_at_none",
    ],
)
async def test_stash_voice_credentials_returns_early_without_touching_redis(monkeypatch, make_args):
    calls = []

    async def boom_get_redis():
        calls.append("get_redis")
        raise AssertionError("must not touch redis")

    async def boom_stash(*a, **kw):
        calls.append("stash")
        raise AssertionError("must not call stash")

    monkeypatch.setattr("noble_agent.storage.redis_client.get_redis", boom_get_redis)
    monkeypatch.setattr("noble_agent.storage.credential_stash.stash", boom_stash)

    settings, tenant_id, creds = make_args()
    await s._stash_voice_credentials(settings, tenant_id, creds)

    assert calls == []


async def test_stash_voice_credentials_swallows_get_redis_exception(monkeypatch, caplog):
    async def raising_get_redis():
        raise RuntimeError("redis unreachable")

    monkeypatch.setattr("noble_agent.storage.redis_client.get_redis", raising_get_redis)

    with caplog.at_level("WARNING", logger="gateway"):
        await s._stash_voice_credentials(_settings(), "acme", _creds())

    assert any("stash voice credential fail" in rec.message for rec in caplog.records)


async def test_stash_voice_credentials_swallows_stash_exception(monkeypatch, caplog):
    async def fake_get_redis():
        return _Sentinel()

    async def raising_stash(*a, **kw):
        raise RuntimeError("stash failed")

    monkeypatch.setattr("noble_agent.storage.redis_client.get_redis", fake_get_redis)
    monkeypatch.setattr("noble_agent.storage.credential_stash.stash", raising_stash)

    with caplog.at_level("WARNING", logger="gateway"):
        await s._stash_voice_credentials(_settings(), "acme", _creds())

    assert any("stash voice credential fail" in rec.message for rec in caplog.records)
