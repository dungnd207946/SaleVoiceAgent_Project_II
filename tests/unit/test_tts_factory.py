"""TTS factory seam: settings.tts_backend → the right TTS class (Step 5)."""

import pytest

from noble_agent.config import settings
from noble_agent.voice.tts.elevenlabs import AsyncElevenLabsTTS
from noble_agent.voice.tts.hotline_ws import HotlineWsTTS
from noble_agent.voice.tts.remote import RemoteTTS
from noble_agent.voice.tts.vieneu import AsyncVieNeuTTS
from noble_agent.voice.tts.vieneu_vllm import AsyncVieNeuVLLMTTS
from noble_agent.voice.voice_agent import VoiceAgent


def test_factory_returns_vieneu(monkeypatch):
    monkeypatch.setattr(settings, "tts_backend", "vieneu")
    # Avoid loading the real model — __init__ would call _load_tts.
    monkeypatch.setattr(AsyncVieNeuTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, AsyncVieNeuTTS)


def test_factory_returns_vieneu_vllm(monkeypatch):
    """tts_backend='vieneu_vllm' resolves to the vLLM-client class (no model load)."""
    monkeypatch.setattr(settings, "tts_backend", "vieneu_vllm")
    monkeypatch.setattr(AsyncVieNeuVLLMTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, AsyncVieNeuVLLMTTS)


def test_factory_vieneu_vllm_server_down_falls_back(monkeypatch):
    """vLLM server down (liveness probe raises at construction) → the factory falls
    through to the next backend (elevenlabs) instead of returning a dead vieneu_vllm.

    This is the whole point of the construction-time probe: without it the codec
    load succeeds and vieneu_vllm absorbs the slot ahead of the working backends,
    and there is no mid-session fallback → total TTS outage on a down server.
    """
    import noble_agent.voice.tts.vieneu_vllm as vllm_mod

    monkeypatch.setattr(settings, "tts_backend", "vieneu_vllm")

    def _probe_down():
        raise RuntimeError("vLLM server unreachable")

    def _remote_boom(self):
        raise RuntimeError("remote down")

    monkeypatch.setattr(vllm_mod, "_probe_server_alive", _probe_down)
    # Order is ["vieneu_vllm","remote","elevenlabs","vieneu"]; force remote to fail
    # so the chain reaches elevenlabs.
    monkeypatch.setattr(RemoteTTS, "__init__", _remote_boom)
    monkeypatch.setattr(AsyncElevenLabsTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, AsyncElevenLabsTTS)


def test_factory_returns_elevenlabs(monkeypatch):
    monkeypatch.setattr(settings, "tts_backend", "elevenlabs")
    monkeypatch.setattr(AsyncElevenLabsTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, AsyncElevenLabsTTS)


def test_factory_unknown_backend_defaults_to_vieneu(monkeypatch):
    """Anything not 'elevenlabs' falls through to vieneu (current contract)."""
    monkeypatch.setattr(settings, "tts_backend", "something-else")
    monkeypatch.setattr(AsyncVieNeuTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, AsyncVieNeuTTS)


def test_factory_vieneu_falls_back_to_remote(monkeypatch):
    """vieneu construct fails → next fallback is remote (new chain: vieneu→remote→elevenlabs)."""
    monkeypatch.setattr(settings, "tts_backend", "vieneu")

    def _boom(self):
        raise RuntimeError("model load failed")

    monkeypatch.setattr(AsyncVieNeuTTS, "__init__", _boom)
    monkeypatch.setattr(RemoteTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, RemoteTTS)


def test_factory_vieneu_and_remote_fail_falls_back_to_elevenlabs(monkeypatch):
    """vieneu + remote + vieneu_vllm all fail → elevenlabs is the last resort.

    Resolved order for tts_backend='vieneu' over the chain
    ["remote","vieneu_vllm","elevenlabs","vieneu"] is
    ["vieneu","remote","vieneu_vllm","elevenlabs"]; vieneu_vllm must also raise
    so the chain reaches elevenlabs.
    """
    monkeypatch.setattr(settings, "tts_backend", "vieneu")

    def _boom(self):
        raise RuntimeError("model load failed")

    monkeypatch.setattr(AsyncVieNeuTTS, "__init__", _boom)
    monkeypatch.setattr(RemoteTTS, "__init__", _boom)
    monkeypatch.setattr(AsyncVieNeuVLLMTTS, "__init__", _boom)
    monkeypatch.setattr(AsyncElevenLabsTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, AsyncElevenLabsTTS)


def test_factory_all_raise_reraises_last(monkeypatch):
    """All builders raise → re-raise the LAST exception.

    Order ["vieneu","remote","vieneu_vllm","elevenlabs","hotline_ws"] → the last
    builder is hotline_ws, so its exception is the one re-raised.
    """
    monkeypatch.setattr(settings, "tts_backend", "vieneu")

    def _vieneu_boom(self):
        raise RuntimeError("vieneu down")

    def _remote_boom(self):
        raise RuntimeError("remote down")

    def _vllm_boom(self):
        raise RuntimeError("vieneu_vllm down")

    def _eleven_boom(self):
        raise RuntimeError("elevenlabs down")

    def _hotline_boom(self):
        raise ValueError("hotline_ws down")

    monkeypatch.setattr(AsyncVieNeuTTS, "__init__", _vieneu_boom)
    monkeypatch.setattr(RemoteTTS, "__init__", _remote_boom)
    monkeypatch.setattr(AsyncVieNeuVLLMTTS, "__init__", _vllm_boom)
    monkeypatch.setattr(AsyncElevenLabsTTS, "__init__", _eleven_boom)
    monkeypatch.setattr(HotlineWsTTS, "__init__", _hotline_boom)

    with pytest.raises(ValueError, match="hotline_ws down"):
        VoiceAgent._create_tts()


def test_factory_returns_hotline_ws(monkeypatch):
    monkeypatch.setattr(settings, "tts_backend", "hotline_ws")
    monkeypatch.setattr(HotlineWsTTS, "__init__", lambda self: None)

    tts = VoiceAgent._create_tts()

    assert isinstance(tts, HotlineWsTTS)
