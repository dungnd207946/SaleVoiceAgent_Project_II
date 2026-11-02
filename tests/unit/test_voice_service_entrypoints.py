"""main() của 2 service tồn tại và callable; module __main__ chạy được (Task 8)."""

from __future__ import annotations


def test_stt_server_main_callable():
    from noble_agent.voice.service.stt_server import main

    assert callable(main)


def test_tts_server_main_callable():
    from noble_agent.voice.service.tts_server import main

    assert callable(main)


def test_pyproject_declares_service_scripts():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    scripts = data["project"]["scripts"]
    assert scripts["noble-stt-service"] == "noble_agent.voice.service.stt_server:main"
    assert scripts["noble-tts-service"] == "noble_agent.voice.service.tts_server:main"
