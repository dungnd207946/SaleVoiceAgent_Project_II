"""build_short_term_context renders snapshot + last-K prior-session turns."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from noble_agent.agent.memory import snapshot
from noble_agent.storage import pg_data_plane


def _settings(**kw):
    base = dict(user_memory_short_term_turns=2, user_memory_since_days=30)
    base.update(kw)
    return SimpleNamespace(**base)


async def test_renders_snapshot_and_turns(monkeypatch):
    async def _load(phone):
        return "Anh Dự quan tâm NCTH 3PN."

    async def _list(phone, limit=5):
        return [{"session_id": "sid-prev"}, {"session_id": "sid-cur"}]

    async def _msgs(sid):
        return [
            {"role": "caller", "content": "còn suất NCTH không?"},
            {"role": "agent", "content": "dạ còn ạ"},
        ]

    monkeypatch.setattr(pg_data_plane, "read_contact_snapshot", _load)
    monkeypatch.setattr(pg_data_plane, "list_conversation_hints", _list)
    monkeypatch.setattr(pg_data_plane, "read_session_messages", _msgs)

    out = await snapshot.build_short_term_context(_settings(), "sid-cur", "sid-cur")
    assert "Anh Dự quan tâm NCTH 3PN." in out
    assert "còn suất NCTH không?" in out
    assert "Lịch sử trò chuyện của khách hàng" in out  # actual render header


async def test_empty_when_nothing(monkeypatch):
    async def _load(phone):
        return ""

    async def _list(phone, limit=5):
        return []

    monkeypatch.setattr(pg_data_plane, "read_contact_snapshot", _load)
    monkeypatch.setattr(pg_data_plane, "list_conversation_hints", _list)
    out = await snapshot.build_short_term_context(_settings(), "0912345678", "sid-cur")
    assert out == ""


async def test_skips_prior_session_older_than_since_days(monkeypatch):
    old_ended_at = datetime.now(UTC) - timedelta(days=999)

    async def _load(phone):
        return "Anh Dự quan tâm NCTH 3PN."

    async def _list(phone, limit=5):
        return [{"session_id": "sid-prev", "ended_at": old_ended_at}, {"session_id": "sid-cur"}]

    async def _msgs(sid):
        return [
            {"role": "caller", "content": "còn suất NCTH không?"},
            {"role": "agent", "content": "dạ còn ạ"},
        ]

    monkeypatch.setattr(pg_data_plane, "read_contact_snapshot", _load)
    monkeypatch.setattr(pg_data_plane, "list_conversation_hints", _list)
    monkeypatch.setattr(pg_data_plane, "read_session_messages", _msgs)

    out = await snapshot.build_short_term_context(_settings(), "sid-cur", "sid-cur")
    assert "Anh Dự quan tâm NCTH 3PN." in out
    assert "Vài lượt gần nhất" not in out
    assert "còn suất NCTH không?" not in out
