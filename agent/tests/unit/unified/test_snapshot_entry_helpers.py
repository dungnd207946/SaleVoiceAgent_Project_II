"""Entry helpers: update_snapshot_after_call lock lifecycle + short_term_block wait."""

from __future__ import annotations

from types import SimpleNamespace

from noble_agent.agent import memory as mem
from noble_agent.agent.memory import snapshot as snap_mod
from noble_agent.storage import pg_data_plane, snapshot_lock


def _settings(**kw):
    base = dict(
        user_memory_short_term_turns=4,
        user_memory_since_days=30,
        snapshot_lock_wait_sec=5.0,
        snapshot_lock_ttl_sec=60,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_update_snapshot_acquires_saves_releases(monkeypatch):
    events: list[str] = []
    released_with: list[str] = []

    async def _acq(phone, ttl_sec=60):
        events.append("acquire")
        return "tok"

    async def _rel(phone, token):
        events.append("release")
        released_with.append(token)

    async def _load(phone):
        return "old"

    async def _merge(old, history):
        events.append("merge")
        return "new snapshot"

    async def _save(phone, text):
        events.append(f"save:{text}")

    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", _acq)
    monkeypatch.setattr(snapshot_lock, "release_snapshot_lock", _rel)
    monkeypatch.setattr(pg_data_plane, "read_contact_snapshot", _load)
    monkeypatch.setattr(snap_mod, "merge_snapshot", _merge)
    monkeypatch.setattr(pg_data_plane, "persist_contact", _save)

    await mem.update_snapshot_after_call(
        _settings(), phone="09", session_id="sid", history=[{"role": "user", "content": "hi"}]
    )
    assert events == ["acquire", "merge", "save:new snapshot", "release"]
    assert released_with == ["tok"]


async def test_update_snapshot_releases_even_on_merge_error(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", lambda p, ttl_sec=60: _val("tok"))
    async def _rel(phone, token):
        events.append("release")
    async def _load(phone):
        return ""
    async def _merge(old, history):
        raise RuntimeError("llm boom")
    monkeypatch.setattr(snapshot_lock, "release_snapshot_lock", _rel)
    monkeypatch.setattr(pg_data_plane, "read_contact_snapshot", _load)
    monkeypatch.setattr(snap_mod, "merge_snapshot", _merge)

    # Must NOT raise, and MUST release.
    await mem.update_snapshot_after_call(
        _settings(), phone="09", session_id="sid", history=[{"role": "user", "content": "hi"}]
    )
    assert events == ["release"]


async def test_update_snapshot_skips_save_when_merge_empty(monkeypatch):
    saved: list = []
    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", lambda p, ttl_sec=60: _val("tok"))
    monkeypatch.setattr(snapshot_lock, "release_snapshot_lock", lambda p, token: _none())
    monkeypatch.setattr(pg_data_plane, "read_contact_snapshot", lambda p: _val(""))
    monkeypatch.setattr(snap_mod, "merge_snapshot", lambda o, h: _val(""))
    monkeypatch.setattr(pg_data_plane, "persist_contact", lambda p, t: saved.append(t))
    await mem.update_snapshot_after_call(
        _settings(), phone="09", session_id="sid", history=[{"role": "user", "content": "hi"}]
    )
    assert saved == []


async def test_update_snapshot_noop_without_phone(monkeypatch):
    called = []
    monkeypatch.setattr(
        snapshot_lock, "acquire_snapshot_lock", lambda p, ttl_sec=60: called.append(p) or _val("tok")
    )
    await mem.update_snapshot_after_call(
        _settings(), phone="", session_id="sid", history=[{"role": "user", "content": "x"}]
    )
    assert called == []


async def test_update_snapshot_skips_merge_when_lock_not_acquired(monkeypatch):
    merge_called = []
    save_called = []
    release_called = []

    async def _acq(phone, ttl_sec=60):
        return None

    async def _rel(phone, token):
        release_called.append(token)

    async def _merge(old, history):
        merge_called.append(True)
        return "should not be used"

    async def _save(phone, text):
        save_called.append(text)

    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", _acq)
    monkeypatch.setattr(snapshot_lock, "release_snapshot_lock", _rel)
    monkeypatch.setattr(snap_mod, "merge_snapshot", _merge)
    monkeypatch.setattr(pg_data_plane, "persist_contact", _save)

    # Must NOT raise, must skip merge/save entirely, and must NOT call release
    # (no token was issued, so there is nothing this call owns to free).
    await mem.update_snapshot_after_call(
        _settings(), phone="09", session_id="sid", history=[{"role": "user", "content": "hi"}]
    )
    assert merge_called == []
    assert save_called == []
    assert release_called == []


async def test_short_term_block_waits_then_builds(monkeypatch):
    events: list[str] = []

    async def _wait(phone, max_wait_sec=10.0, poll_sec=0.5):
        events.append("wait")
        return True

    async def _build(settings, phone, sid):
        events.append("build")
        return "## Bối cảnh khách hàng (tích lũy)\nold"

    monkeypatch.setattr(snapshot_lock, "wait_snapshot_lock_clear", _wait)
    monkeypatch.setattr(snap_mod, "build_short_term_context", _build)
    out = await mem.short_term_block(_settings(), phone="09", session_id="sid")
    assert events == ["wait", "build"]
    assert "Bối cảnh" in out


async def test_short_term_block_empty_without_phone():
    assert await mem.short_term_block(_settings(), phone="", session_id="sid") == ""


# ── tiny awaitable helpers for lambda-based monkeypatches ──
async def _true():
    return True


async def _none():
    return None


async def _val(v):
    return v
