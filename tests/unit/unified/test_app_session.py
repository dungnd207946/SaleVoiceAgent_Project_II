import json as _json_mod

import fakeredis.aioredis
import jwt as _jwt
import pytest

from noble_agent.server import app_session as A
from noble_agent.storage.redis_client import close_redis, set_redis_for_tests


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis()
    set_redis_for_tests(client)
    yield client
    await close_redis()


def test_normalize_gender():
    assert A._normalize_gender("Female") == "F"
    assert A._normalize_gender("Nữ") == "F"
    assert A._normalize_gender(" male ") == "M"
    assert A._normalize_gender("Nam") == "M"
    assert A._normalize_gender("") is None
    assert A._normalize_gender(None) is None
    assert A._normalize_gender("other") is None


def test_derive_session_id_stable_and_shaped():
    uid = "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    sid = A._derive_session_id(uid)
    assert sid == "app-6cb7cc1dd5d0"
    # deterministic → resumable
    assert A._derive_session_id(uid) == sid


def test_compose_noble_info():
    assert A._compose_noble_info({}) is None
    assert A._compose_noble_info({"noble_info": "VIP"}) == "VIP"
    out = A._compose_noble_info({"noble_info": "VIP", "email": "a@b.vn", "birthday": "25/02/1997"})
    assert "VIP" in out and "a@b.vn" in out and "25/02/1997" in out


def test_token_key():
    assert A._token_key("app-x") == "session:app-x:connect_token"


async def test_provision_missing_user_id_returns_400(fake_redis):
    payload, status = await A.provision_session({"identity": {"full_name": "Nga"}})
    assert status == 400
    assert "noble_user_id" in payload["error"]


async def test_provision_seeds_customer_and_mints_token(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "app_connect_token_ttl_seconds", 120)
    monkeypatch.setattr(A.settings, "app_ws_public_base", "wss://agent.noble.vn")

    body = {
        "noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb",
        "channel": "chat",
        "identity": {
            "full_name": "Lê Viết Thúy Nga",
            "phone": "0378764303",
            "gender": "Female",
            "is_noble_customer": False,
            "noble_info": "VIP",
            "email": "ngalvt@noblex.vn",
        },
    }
    payload, status = await A.provision_session(body)
    assert status == 200
    assert payload["session_id"] == "app-6cb7cc1dd5d0"
    assert payload["connect_token"]
    assert payload["expires_in"] == 120
    assert payload["ws_url"] == (f"wss://agent.noble.vn/chat?session=app-6cb7cc1dd5d0&token={payload['connect_token']}")

    # Customer seeded in Redis (same key the runner loads)
    from noble_agent.storage.repo import StateRepo

    repo = StateRepo(redis_client=fake_redis, ttl_seconds=86400)
    _meta, cust, _state = await repo.load("app-6cb7cc1dd5d0")
    assert cust.noble_user_id == "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    assert cust.full_name == "Lê Viết Thúy Nga"
    assert cust.name == "Lê Viết Thúy Nga"
    assert cust.phone == "0378764303"
    assert cust.gender == "F"
    assert cust.is_noble_customer is False
    assert "VIP" in cust.noble_info and "ngalvt@noblex.vn" in cust.noble_info

    # token stored, and verify accepts it / rejects a wrong one
    assert await A.verify_connect_token("app-6cb7cc1dd5d0", payload["connect_token"]) is True
    assert await A.verify_connect_token("app-6cb7cc1dd5d0", "nope") is False
    assert await A.verify_connect_token("app-6cb7cc1dd5d0", None) is False
    assert await A.verify_connect_token("unknown-sid", payload["connect_token"]) is False


async def test_provision_ws_url_is_path_when_no_base(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "app_ws_public_base", "")
    payload, status = await A.provision_session({"noble_user_id": "abc123def4567890"})
    assert status == 200
    assert payload["ws_url"].startswith("/chat?session=app-abc123def456&token=")


async def test_provision_idempotent_merges(fake_redis):
    uid = "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    await A.provision_session({"noble_user_id": uid, "identity": {"full_name": "Nga", "phone": "0378764303"}})
    # second call without phone must not blank the earlier phone
    await A.provision_session({"noble_user_id": uid, "identity": {"full_name": "Nga 2"}})

    from noble_agent.storage.repo import StateRepo

    repo = StateRepo(redis_client=fake_redis, ttl_seconds=86400)
    _m, cust, _s = await repo.load(A._derive_session_id(uid))
    assert cust.full_name == "Nga 2"
    assert cust.phone == "0378764303"  # preserved


class _FakeReq:
    def __init__(self, method="POST", headers=None, body=b""):
        self.method = method
        self.headers = headers or {}
        self.body = body


async def test_handle_app_session_disabled_when_no_key(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "")
    resp = await A.handle_app_session(_FakeReq(headers={"X-Noble-App-Key": "x"}))
    assert resp.status_code == 503


async def test_handle_app_session_rejects_bad_key(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "secret")
    resp = await A.handle_app_session(_FakeReq(headers={"X-Noble-App-Key": "wrong"}))
    assert resp.status_code == 401


async def test_handle_app_session_rejects_non_post(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "secret")
    resp = await A.handle_app_session(_FakeReq(method="GET", headers={"X-Noble-App-Key": "secret"}))
    assert resp.status_code == 405


async def test_handle_app_session_happy_path(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "secret")
    body = _json_mod.dumps({"noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"}).encode()
    resp = await A.handle_app_session(_FakeReq(headers={"X-Noble-App-Key": "secret"}, body=body))
    assert resp.status_code == 200
    data = _json_mod.loads(resp.body)
    assert data["session_id"] == "app-6cb7cc1dd5d0"
    assert data["connect_token"]


_LK_SECRET = "devsecret_change_me_for_prod_1234567890abcdef"


def _lk_settings(monkeypatch, public_url="wss://lk.noble.vn"):
    monkeypatch.setattr(A.settings, "livekit_api_key", "devkey")
    monkeypatch.setattr(A.settings, "livekit_api_secret", _LK_SECRET)
    monkeypatch.setattr(A.settings, "tenant_id", "noble")
    monkeypatch.setattr(A.settings, "livekit_public_url", public_url)
    monkeypatch.setattr(A.settings, "livekit_url", "ws://localhost:7880")


def test_mint_livekit_token_embeds_room_grants_and_dispatch(monkeypatch):
    _lk_settings(monkeypatch)
    tok, url, room = A._mint_livekit_token("app-6cb7cc1dd5d0", "user-app-6cb7cc1dd5d0", "Nga")
    assert url == "wss://lk.noble.vn"
    assert room == "app-6cb7cc1dd5d0"
    claims = _jwt.decode(tok, _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["sub"] == "user-app-6cb7cc1dd5d0"
    assert claims["video"]["room"] == "app-6cb7cc1dd5d0"
    assert claims["video"]["roomJoin"] is True
    # Dispatch name is the SHARED settings.livekit_agent_name (not tenant-derived) — see
    # test_mint_livekit_token_uses_shared_dispatch_name for the regression lock that
    # keeps this in sync with the worker + gateway.
    assert claims["roomConfig"]["agents"][0]["agentName"] == A.settings.livekit_agent_name
    # Room is auto-created from this token when the app joins; a short empty
    # timeout frees it quickly once everyone leaves.
    assert claims["roomConfig"]["emptyTimeout"] == A._ROOM_EMPTY_TIMEOUT_S


class _FakeToken:
    """Fake AccessToken minter that records .with_*() calls for assertion
    (mirrors tests/unit/gateway/test_livekit_bridge.py's FakeToken)."""

    def __init__(self, *a, **k):
        self.calls = []

    def with_identity(self, v):
        self.calls.append(("identity", v))
        return self

    def with_name(self, v):
        self.calls.append(("name", v))
        return self

    def with_grants(self, v):
        self.calls.append(("grants", v))
        return self

    def with_room_config(self, v):
        self.calls.append(("room_config", v))
        return self

    def with_metadata(self, v):
        self.calls.append(("metadata", v))
        return self

    def to_jwt(self):
        return "JWT"


def test_mint_livekit_token_uses_shared_dispatch_name(monkeypatch):
    """All three sites (worker registration, this app mint, gateway build_dispatch_token)
    use the SHARED settings.livekit_agent_name — NOT a tenant-derived name — so one
    worker pool serves every tenant. Setting a different tenant_id must NOT change it."""
    _lk_settings(monkeypatch)
    monkeypatch.setattr(A.settings, "tenant_id", "acme-corp")
    tok = _FakeToken()
    monkeypatch.setattr("livekit.api.AccessToken", lambda *a, **k: tok)
    A._mint_livekit_token("app-x", "user-app-x", "user-app-x")
    room_config = dict(tok.calls)["room_config"]
    assert room_config.agents[0].agent_name == A.settings.livekit_agent_name


def test_mint_livekit_token_url_falls_back_to_internal(monkeypatch):
    _lk_settings(monkeypatch, public_url="")
    _tok, url, _room = A._mint_livekit_token("app-x", "user-app-x", "user-app-x")
    assert url == "ws://localhost:7880"


async def test_provision_voice_returns_livekit_token_and_seeds(fake_redis, monkeypatch):
    _lk_settings(monkeypatch)
    body = {
        "noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb",
        "channel": "voice",
        "identity": {"full_name": "Lê Viết Thúy Nga", "phone": "0378764303", "gender": "Female"},
    }
    payload, status = await A.provision_session(body)
    assert status == 200
    assert payload["channel"] == "voice"
    # Voice session id / room is per-call unique (base derived id + suffix) so the
    # LiveKit room is always freshly created → token agent-dispatch always fires.
    sid = payload["session_id"]
    assert sid.startswith("app-6cb7cc1dd5d0-")
    assert sid != "app-6cb7cc1dd5d0"
    assert payload["room"] == sid
    assert payload["livekit_url"] == "wss://lk.noble.vn"
    assert "livekit_token" in payload
    # no chat-only fields on the voice payload
    assert "ws_url" not in payload and "connect_token" not in payload
    # token carries the per-call room + dispatch + short empty timeout
    claims = _jwt.decode(payload["livekit_token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["sub"] == f"user-{sid}"
    assert claims["video"]["room"] == sid
    assert claims["roomConfig"]["agents"][0]["agentName"] == A.settings.livekit_agent_name
    assert claims["roomConfig"]["emptyTimeout"] == A._ROOM_EMPTY_TIMEOUT_S
    # Customer seeded under the per-call id (so the worker's turn-1 load finds it)
    from noble_agent.storage.repo import StateRepo

    repo = StateRepo(redis_client=fake_redis, ttl_seconds=86400)
    _m, cust, _s = await repo.load(sid)
    assert cust.noble_user_id == "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    assert cust.full_name == "Lê Viết Thúy Nga"
    assert cust.phone == "0378764303"
    assert cust.gender == "F"


async def test_provision_voice_room_is_unique_per_call(fake_redis, monkeypatch):
    """Two voice provisions for the SAME user must yield different room names —
    this is what guarantees a reconnect creates a fresh room (agent re-dispatched)
    instead of joining the stale prior room where dispatch is ignored.
    """
    _lk_settings(monkeypatch)
    body = {"noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb", "channel": "voice"}
    p1, _ = await A.provision_session(body)
    p2, _ = await A.provision_session(body)
    assert p1["room"] != p2["room"]
    assert p1["room"].startswith("app-6cb7cc1dd5d0-")
    assert p2["room"].startswith("app-6cb7cc1dd5d0-")


async def test_provision_voice_503_when_livekit_unconfigured(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "livekit_api_key", "")
    monkeypatch.setattr(A.settings, "livekit_api_secret", "")
    payload, status = await A.provision_session(
        {"noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb", "channel": "voice"}
    )
    assert status == 503
    assert payload["error"] == "livekit_not_configured"


def test_mint_livekit_token_embeds_tenant_metadata(monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    tok = _FakeToken()
    monkeypatch.setattr("livekit.api.AccessToken", lambda *a, **k: tok)
    A._mint_livekit_token("app-x", "user-app-x", "user-app-x", tenant_id="acme")
    meta = _json_mod.loads(dict(tok.calls)["metadata"])
    assert meta == {"tenant_id": "acme"}


def test_mint_livekit_token_metadata_falls_back_to_settings_tenant(monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    tok = _FakeToken()
    monkeypatch.setattr("livekit.api.AccessToken", lambda *a, **k: tok)
    A._mint_livekit_token("app-x", "user-app-x", "user-app-x")  # no tenant_id
    meta = _json_mod.loads(dict(tok.calls)["metadata"])
    assert meta == {"tenant_id": "noble"}


async def test_provision_voice_uses_body_tenant_in_metadata(fake_redis, monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    body = {"noble_user_id": "u1", "channel": "voice", "tenant_id": "acme", "identity": {}}
    payload, status = await A.provision_session(body)
    assert status == 200
    claims = _jwt.decode(
        payload["livekit_token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )
    assert _json_mod.loads(claims["metadata"]) == {"tenant_id": "acme"}


async def test_provision_voice_tenant_falls_back_to_settings(fake_redis, monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    body = {"noble_user_id": "u1", "channel": "voice", "identity": {}}  # no tenant_id
    payload, status = await A.provision_session(body)
    assert status == 200
    claims = _jwt.decode(
        payload["livekit_token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )
    assert _json_mod.loads(claims["metadata"]) == {"tenant_id": "noble"}
