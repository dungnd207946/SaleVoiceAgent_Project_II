"""Task C4 — build_heartbeat_supervisor selects PG vs MinIO supervisor by config source."""
from types import SimpleNamespace

from noble_agent.tenant.heartbeat import build_heartbeat_supervisor
from noble_agent.tenant.pg_heartbeat import PgHeartbeatSupervisor


def test_build_supervisor_db_mode():
    s = SimpleNamespace(agent_config_source="db", heartbeat_sec=20.0, agent_version="1.0")
    sup = build_heartbeat_supervisor(s, "chat")
    assert isinstance(sup, PgHeartbeatSupervisor)


def test_build_supervisor_legacy(monkeypatch):
    monkeypatch.setattr("noble_agent.tenant.loader._build_store", lambda s: object())
    from noble_agent.tenant.heartbeat import HeartbeatSupervisor

    s = SimpleNamespace(agent_config_source="legacy", heartbeat_sec=20.0, tenant_store_enabled=True)
    assert isinstance(build_heartbeat_supervisor(s, "chat"), HeartbeatSupervisor)
