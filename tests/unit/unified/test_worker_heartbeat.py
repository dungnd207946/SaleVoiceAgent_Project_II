"""SP-D heartbeat wiring into the LiveKit worker (`_start_heartbeat`).

Gate-only tests: the emitter loop itself is covered in
`tests/unit/tenant/test_heartbeat.py`; here we only assert the LiveKit
`run_worker` entry starts (or does not start) the daemon thread per the gate,
without spinning up the agents framework.
"""

from __future__ import annotations

import noble_agent.tenant.heartbeat as hb_mod
import noble_agent.transport.livekit.worker as worker_mod


class _ThreadSpy:
    calls: list[dict] = []

    def __init__(self, *, target=None, name=None, daemon=None):
        _ThreadSpy.calls.append({"name": name, "daemon": daemon})
        self.started = False

    def start(self):
        self.started = True


def test_start_heartbeat_noop_when_gate_closed(monkeypatch):
    _ThreadSpy.calls = []
    monkeypatch.setattr(hb_mod, "should_emit", lambda s: False)
    monkeypatch.setattr(worker_mod.threading, "Thread", _ThreadSpy)
    worker_mod._start_heartbeat()
    assert _ThreadSpy.calls == []  # gate closed → no thread started


def test_start_heartbeat_starts_daemon_thread_when_gate_open(monkeypatch):
    _ThreadSpy.calls = []
    monkeypatch.setattr(hb_mod, "should_emit", lambda s: True)
    monkeypatch.setattr(worker_mod.settings, "agent_config_source", "legacy")
    monkeypatch.setattr(worker_mod.threading, "Thread", _ThreadSpy)
    worker_mod._start_heartbeat()
    assert len(_ThreadSpy.calls) == 1
    assert _ThreadSpy.calls[0] == {"name": "sp-d-heartbeat", "daemon": True}


def test_start_heartbeat_skips_main_thread_in_db_mode(monkeypatch):
    """db-mode voice heartbeat runs per-job inside ``entrypoint`` (fork-safe);
    the main-process supervisor can't see a job subprocess's ``mark_active``, so
    ``_start_heartbeat`` must NOT spin the daemon thread in db-mode."""
    _ThreadSpy.calls = []
    monkeypatch.setattr(hb_mod, "should_emit", lambda s: True)
    monkeypatch.setattr(worker_mod.settings, "agent_config_source", "db")
    monkeypatch.setattr(worker_mod.threading, "Thread", _ThreadSpy)
    worker_mod._start_heartbeat()
    assert _ThreadSpy.calls == []


def test_start_job_heartbeat_gate_closed_returns_none(monkeypatch):
    """Gate closed (should_emit False) → no per-job task."""
    monkeypatch.setattr(hb_mod, "should_emit", lambda s: False)
    monkeypatch.setattr(worker_mod.settings, "agent_config_source", "db")
    task, stop = worker_mod._start_job_heartbeat("acme")
    assert task is None and stop is None


def test_start_job_heartbeat_legacy_mode_returns_none(monkeypatch):
    """Legacy (non-db) voice never uses the PG per-job heartbeat."""
    monkeypatch.setattr(hb_mod, "should_emit", lambda s: True)
    monkeypatch.setattr(worker_mod.settings, "agent_config_source", "legacy")
    task, stop = worker_mod._start_job_heartbeat("acme")
    assert task is None and stop is None


async def test_start_job_heartbeat_db_mode_starts_task_for_tenant(monkeypatch):
    """db-mode + gate open → a task beating the given tenant is created."""
    monkeypatch.setattr(hb_mod, "should_emit", lambda s: True)
    monkeypatch.setattr(worker_mod.settings, "agent_config_source", "db")

    seen: dict = {}

    async def _fake_run(tenant_id, kind, agent_version, interval, stop_event, *, writer=None):
        seen["tenant_id"] = tenant_id
        seen["kind"] = kind
        await stop_event.wait()

    import noble_agent.tenant.pg_heartbeat as pg_hb

    monkeypatch.setattr(pg_hb, "run_job_heartbeat", _fake_run)

    task, stop = worker_mod._start_job_heartbeat("acme")
    assert task is not None and stop is not None
    await __import__("asyncio").sleep(0.01)
    assert seen == {"tenant_id": "acme", "kind": "voice"}
    stop.set()
    await task
