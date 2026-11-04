"""Fernet stash Redis: cầu nối credential gateway → LiveKit voice worker."""

from datetime import UTC, datetime, timedelta

from noble_agent.storage import credential_stash as cs
from noble_agent.storage import tenant_credentials as tc

SECRET = "motchuoibatky"


def setup_function():
    tc.clear_for_tests()


def _exp(sec=3600):
    return datetime.now(UTC) + timedelta(seconds=sec)


class _FakeRedis:
    """Chỉ mô phỏng set(name, value, ex=...) + get(name) mà stash/fetch dùng."""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def set(self, name, value, ex=None):
        self.store[name] = value
        self.ttls[name] = ex

    async def get(self, name):
        return self.store.get(name)


def test_encrypt_decrypt_roundtrip():
    payload = {"role": "agent_a", "password": "p@ss", "tenant_id": "eco_green"}
    token = cs.encrypt_credential(SECRET, payload)
    assert token != str(payload)  # không phải plaintext
    assert cs.decrypt_credential(SECRET, token) == payload


def test_decrypt_wrong_secret_returns_none():
    token = cs.encrypt_credential(SECRET, {"role": "a"})
    assert cs.decrypt_credential("secret-khac", token) is None


def test_decrypt_garbage_returns_none():
    assert cs.decrypt_credential(SECRET, "not-a-fernet-token") is None
    assert cs.decrypt_credential(SECRET, "") is None


def test_ttl_seconds_clamps_to_one():
    assert cs.ttl_seconds(_exp(120)) in (119, 120)
    assert cs.ttl_seconds(_exp(-50)) == 1


async def test_stash_and_fetch_roundtrip():
    r = _FakeRedis()
    ok = await cs.stash(r, SECRET, "eco_green", role="agent_eco_green", password="pw",
                        expires_at=_exp())
    assert ok is True
    assert list(r.store) == ["noble:pgcred:eco_green"]
    assert r.ttls["noble:pgcred:eco_green"] >= 3599 - 1
    got = await cs.fetch(r, SECRET, "eco_green")
    assert got["role"] == "agent_eco_green"
    # `deployment_id`/`kind` rời payload ở `0941`/`0919`.
    assert "deployment_id" not in got and "kind" not in got


async def test_fetch_missing_key_returns_none():
    assert await cs.fetch(_FakeRedis(), SECRET, "nope") is None


async def test_fetch_and_register_registers():
    r = _FakeRedis()
    await cs.stash(r, SECRET, "eco_green", role="agent_eco_green", password="pw",
                   expires_at=_exp())
    assert await cs.fetch_and_register(r, SECRET, "eco_green") is True
    cred = tc.get("eco_green")
    assert cred is not None
    assert cred.role == "agent_eco_green"


async def test_fetch_and_register_no_key_false():
    assert await cs.fetch_and_register(_FakeRedis(), SECRET, "eco_green") is False
    assert tc.get("eco_green") is None


async def test_fetch_and_register_empty_secret_skips_redis():
    r = _FakeRedis()

    async def boom(name):  # secret rỗng thì không được đụng Redis
        raise AssertionError("must not touch redis")

    r.get = boom
    assert await cs.fetch_and_register(r, "", "eco_green") is False


async def test_fetch_and_register_bad_expires_false():
    r = _FakeRedis()
    token = cs.encrypt_credential(SECRET, {"role": "a", "password": "p",
                                           "expires_at": "hôm-qua", "tenant_id": "eco_green"})
    await r.set(cs.stash_key("eco_green"), token)
    assert await cs.fetch_and_register(r, SECRET, "eco_green") is False


async def test_stash_payload_binds_tenant_id():
    r = _FakeRedis()
    await cs.stash(r, SECRET, "eco_green", role="agent_eco_green", password="pw",
                   expires_at=_exp())
    got = await cs.fetch(r, SECRET, "eco_green")
    assert got["tenant_id"] == "eco_green"
    assert await cs.fetch_and_register(r, SECRET, "eco_green") is True
    cred = tc.get("eco_green")
    assert cred is not None and cred.role == "agent_eco_green"


async def test_stash_and_register_carries_agent_key_id():
    r = _FakeRedis()
    await cs.stash(r, SECRET, "eco_green", role="agent_eco_green", password="pw",
                   expires_at=_exp(), agent_key_id="ak_9")
    assert await cs.fetch_and_register(r, SECRET, "eco_green") is True
    cred = tc.get("eco_green")
    assert cred is not None and cred.agent_key_id == "ak_9"


async def test_register_legacy_payload_without_agent_key_id():
    """Payload cũ (chưa có field) vẫn đăng ký được — agent_key_id rỗng."""
    r = _FakeRedis()
    token = cs.encrypt_credential(SECRET, {"role": "agent_a", "password": "p",
                                           "deployment_id": 1, "kind": "voice",
                                           "expires_at": _exp().isoformat(),
                                           "tenant_id": "eco_green"})
    await r.set(cs.stash_key("eco_green"), token)
    assert await cs.fetch_and_register(r, SECRET, "eco_green") is True
    cred = tc.get("eco_green")
    assert cred is not None and cred.agent_key_id == ""


async def test_adopt_agent_key_sets_contextvar_from_registry():
    from noble_agent.tenant.current import current_agent_key_id

    r = _FakeRedis()
    await cs.stash(r, SECRET, "eco_green", role="agent_eco_green", password="pw",
                   expires_at=_exp(), agent_key_id="ak_9")
    await cs.fetch_and_register(r, SECRET, "eco_green")
    assert cs.adopt_agent_key("eco_green") == "ak_9"
    assert current_agent_key_id() == "ak_9"


def test_adopt_agent_key_without_credential_is_noop():
    from noble_agent.tenant.current import current_agent_key_id

    assert cs.adopt_agent_key("khong_ton_tai") == ""
    assert current_agent_key_id() == ""


async def test_fetch_and_register_rejects_transplanted_ciphertext():
    """Blob stashed for tenant A copied onto B's key must not register for B."""
    r = _FakeRedis()
    await cs.stash(r, SECRET, "tenant_a", role="agent_a", password="pw",
                   expires_at=_exp())
    # Attacker with Redis write access transplants A's ciphertext onto B's key.
    r.store[cs.stash_key("tenant_b")] = r.store[cs.stash_key("tenant_a")]
    assert await cs.fetch_and_register(r, SECRET, "tenant_b") is False
    assert tc.get("tenant_b") is None
