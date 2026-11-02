"""`redis_client._redis_url` — nguồn URL của client Redis standalone.

Bug live 2026-08-19: hàm chỉ đọc os.getenv("REDIS_URL") nên khi biến chỉ nằm
trong .env (không export), gateway stash + livekit fetch rơi về localhost:6379
→ connection refused → credential/agent_key_id voice mất im lặng, trong khi
session state vẫn chạy (đi đường settings) nên không ai nhận ra.
"""

from types import SimpleNamespace

from noble_agent.storage import redis_client as rc


def test_env_var_wins(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://tu-env:6379/0")
    assert rc._redis_url() == "redis://tu-env:6379/0"


def test_falls_back_to_settings_when_env_unset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: SimpleNamespace(redis_url="redis://tu-dotenv:6379/0"),
    )
    assert rc._redis_url() == "redis://tu-dotenv:6379/0"


def test_localhost_default_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(
        "noble_agent.config.get_settings", lambda: SimpleNamespace(redis_url="")
    )
    assert rc._redis_url() == "redis://localhost:6379/0"


def test_settings_error_degrades_to_default(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    def _boom():
        raise RuntimeError("settings boom")

    monkeypatch.setattr("noble_agent.config.get_settings", _boom)
    assert rc._redis_url() == "redis://localhost:6379/0"
