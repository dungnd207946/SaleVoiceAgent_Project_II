"""Defaults for the remote STT/TTS service config (Task 1)."""

from __future__ import annotations


def test_voice_service_defaults():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)
    assert s.stt_service_url == "ws://127.0.0.1:8770/stt"
    assert s.tts_service_url == "ws://127.0.0.1:8771/tts"
    assert s.stt_service_host == "0.0.0.0"
    assert s.stt_service_port == 8770
    assert s.tts_service_host == "0.0.0.0"
    assert s.tts_service_port == 8771
    assert s.voice_service_auth_token == ""


def test_voice_service_env_override(monkeypatch):
    monkeypatch.setenv("STT_SERVICE_URL", "ws://10.0.0.5:9000/stt")
    monkeypatch.setenv("TTS_SERVICE_PORT", "9999")
    monkeypatch.setenv("VOICE_SERVICE_AUTH_TOKEN", "secret123")
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings()
    assert s.stt_service_url == "ws://10.0.0.5:9000/stt"
    assert s.tts_service_port == 9999
    assert s.voice_service_auth_token == "secret123"


def test_voice_service_empty_url_falls_back_to_default(monkeypatch):
    # Explicitly-empty env vars must NOT yield "" (which would break the client);
    # they fall back to the built-in defaults.
    monkeypatch.setenv("STT_SERVICE_URL", "")
    monkeypatch.setenv("TTS_SERVICE_URL", "   ")  # whitespace-only also counts as blank
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)
    assert s.stt_service_url == "ws://127.0.0.1:8770/stt"
    assert s.tts_service_url == "ws://127.0.0.1:8771/tts"


def test_voice_service_url_is_trimmed(monkeypatch):
    monkeypatch.setenv("STT_SERVICE_URL", "  ws://gpu-host:8770/stt  ")
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)
    assert s.stt_service_url == "ws://gpu-host:8770/stt"
