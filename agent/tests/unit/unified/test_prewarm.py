"""Unit tests for the shared startup pre-warm helper.

`prewarm_voice_models()` eagerly loads the configured STT (sherpa) + TTS
(vieneu) singletons at boot. It must swallow per-backend failures (log +
continue) so the server still boots. The heavy loaders are stubbed here — these
tests never touch sherpa-onnx / vieneu.
"""

import logging

import pytest

import noble_agent.voice.stt.sherpa as sherpa_mod
import noble_agent.voice.tts.vieneu as vieneu_mod
from noble_agent.voice.prewarm import prewarm_voice_models


@pytest.fixture(autouse=True)
def _stub_silero(monkeypatch):
    """prewarm now also warms Silero — never let a unit test hit torch.hub."""
    from noble_agent.voice.vad import silero as silero_mod

    monkeypatch.setattr(silero_mod, "_load_shared_model", lambda: None)


def _force_backends(monkeypatch):
    from noble_agent.voice import prewarm as prewarm_mod

    monkeypatch.setattr(prewarm_mod.settings, "stt_backend", "sherpa")
    monkeypatch.setattr(prewarm_mod.settings, "tts_backend", "vieneu")


def test_prewarm_calls_both_loaders(monkeypatch):
    _force_backends(monkeypatch)
    called = {"stt": False, "tts": False}
    monkeypatch.setattr(sherpa_mod, "_get_recognizer", lambda: called.__setitem__("stt", True))
    monkeypatch.setattr(vieneu_mod, "_load_tts", lambda: called.__setitem__("tts", True))

    prewarm_voice_models()
    assert called == {"stt": True, "tts": True}


def test_prewarm_swallows_stt_failure(monkeypatch, caplog):
    _force_backends(monkeypatch)
    called = {"tts": False}

    def boom():
        raise RuntimeError("stt cold-load failed")

    monkeypatch.setattr(sherpa_mod, "_get_recognizer", boom)
    monkeypatch.setattr(vieneu_mod, "_load_tts", lambda: called.__setitem__("tts", True))

    with caplog.at_level(logging.WARNING):
        prewarm_voice_models()  # must NOT raise

    assert called["tts"] is True  # TTS still attempted
    assert any("STT" in r.message for r in caplog.records)


def test_prewarm_swallows_tts_failure(monkeypatch, caplog):
    _force_backends(monkeypatch)
    called = {"stt": False}

    def boom():
        raise RuntimeError("tts cold-load failed")

    monkeypatch.setattr(sherpa_mod, "_get_recognizer", lambda: called.__setitem__("stt", True))
    monkeypatch.setattr(vieneu_mod, "_load_tts", boom)

    with caplog.at_level(logging.WARNING):
        prewarm_voice_models()  # must NOT raise

    assert called["stt"] is True
    assert any("TTS" in r.message for r in caplog.records)


def test_prewarm_skips_non_configured_backends(monkeypatch):
    from noble_agent.voice import prewarm as prewarm_mod

    monkeypatch.setattr(prewarm_mod.settings, "stt_backend", "soniox")
    monkeypatch.setattr(prewarm_mod.settings, "tts_backend", "elevenlabs")
    called = {"stt": False, "tts": False}
    monkeypatch.setattr(sherpa_mod, "_get_recognizer", lambda: called.__setitem__("stt", True))
    monkeypatch.setattr(vieneu_mod, "_load_tts", lambda: called.__setitem__("tts", True))

    prewarm_voice_models()
    assert called == {"stt": False, "tts": False}  # neither configured → neither warmed


def _cloud_backends(monkeypatch):
    """Skip the sherpa/vieneu blocks — only the Silero block is under test."""
    from noble_agent.voice import prewarm as prewarm_mod

    monkeypatch.setattr(prewarm_mod.settings, "stt_backend", "soniox")
    monkeypatch.setattr(prewarm_mod.settings, "tts_backend", "elevenlabs")


def test_prewarm_loads_silero_shared_model(monkeypatch):
    """Silero is built per session via deepcopy of a process-wide model — the
    HTTP/WS + telephony boot path must warm it too, not just the LiveKit prewarm."""
    _cloud_backends(monkeypatch)
    from noble_agent.voice.vad import silero as silero_mod

    called = []
    monkeypatch.setattr(silero_mod, "_load_shared_model", lambda: called.append(True))

    prewarm_voice_models()
    assert called == [True]


def test_prewarm_swallows_silero_failure(monkeypatch, caplog):
    _cloud_backends(monkeypatch)
    from noble_agent.voice.vad import silero as silero_mod

    def boom():
        raise RuntimeError("hub cache missing")

    monkeypatch.setattr(silero_mod, "_load_shared_model", boom)
    with caplog.at_level(logging.WARNING):
        prewarm_voice_models()  # must NOT raise
    assert any("Silero" in r.getMessage() for r in caplog.records)
