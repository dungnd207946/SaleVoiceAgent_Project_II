import json

import jwt as _jwt

from noble_agent.config import settings
from noble_agent.server import http as H

_LK_SECRET = "devsecret_change_me_for_prod_1234567890abcdef"


class _FakeReqHTTP:
    """Minimal stand-in for websockets.http11.Request for process_request."""

    def __init__(self, path, method="GET"):
        self.path = path
        self.method = method
        self.headers = {}  # .get("Upgrade","") → "" (not a websocket upgrade)


async def test_livekit_token_disabled_by_default(monkeypatch):
    monkeypatch.setattr(H.settings, "livekit_token_public", False)
    resp = await H.process_request(None, _FakeReqHTTP("/livekit/token?room=r1"))
    assert resp.status_code == 503
    assert json.loads(resp.body)["error"] == "livekit_token_disabled"


async def test_livekit_token_enabled_mints_with_dispatch(monkeypatch):
    monkeypatch.setattr(H.settings, "livekit_token_public", True)
    monkeypatch.setattr(H.settings, "livekit_api_key", "devkey")
    monkeypatch.setattr(H.settings, "livekit_api_secret", _LK_SECRET)
    monkeypatch.setattr(H.settings, "tenant_id", "noble")
    monkeypatch.setattr(H.settings, "livekit_public_url", "wss://lk.noble.vn")
    resp = await H.process_request(None, _FakeReqHTTP("/livekit/token?room=r1&identity=i1"))
    assert resp.status_code == 200
    data = json.loads(resp.body)
    assert data["room"] == "r1" and data["identity"] == "i1" and data["url"] == "wss://lk.noble.vn"
    claims = _jwt.decode(data["token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["video"]["room"] == "r1"
    # /livekit/token shares _mint_livekit_token with the app provisioning path
    # (server/app_session.py) — dispatch name is the shared settings.livekit_agent_name.
    assert claims["roomConfig"]["agents"][0]["agentName"] == settings.livekit_agent_name
