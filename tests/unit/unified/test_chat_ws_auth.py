from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from noble_agent.server import ws_handler
from noble_agent.storage.redis_client import close_redis, set_redis_for_tests


class _FakeWS:
    """Minimal ServerConnection double for _handle_session."""

    def __init__(self, path):
        self.request = MagicMock()
        self.request.path = path
        self.remote_address = ("127.0.0.1", 1234)
        self.close = AsyncMock()
        self.send = AsyncMock()

    def __aiter__(self):
        async def _gen():
            return
            yield  # pragma: no cover

        return _gen()


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis()
    set_redis_for_tests(client)
    yield client
    await close_redis()


async def test_chat_ws_closed_when_token_required_and_missing(fake_redis, monkeypatch):
    monkeypatch.setattr(ws_handler.settings, "chat_ws_require_token", True)
    called = False

    async def _fake_handle(ws, sid, *, tenant_id=None):
        nonlocal called
        called = True

    from noble_agent.server import text_chat

    monkeypatch.setattr(text_chat, "handle_text_session", _fake_handle)

    ws = _FakeWS("/chat?session=app-xyz")  # no token
    await ws_handler._handle_session(ws, "127.0.0.1")

    ws.close.assert_awaited_once()
    assert ws.close.call_args.args[0] == 4401
    assert called is False


async def test_chat_ws_allows_valid_token(fake_redis, monkeypatch):
    monkeypatch.setattr(ws_handler.settings, "chat_ws_require_token", True)
    await fake_redis.set("session:app-xyz:connect_token", "good")
    seen = {}

    async def _fake_handle(ws, sid, *, tenant_id=None):
        seen["sid"] = sid

    from noble_agent.server import text_chat

    monkeypatch.setattr(text_chat, "handle_text_session", _fake_handle)

    ws = _FakeWS("/chat?session=app-xyz&token=good")
    await ws_handler._handle_session(ws, "127.0.0.1")

    ws.close.assert_not_awaited()
    assert seen["sid"] == "app-xyz"
