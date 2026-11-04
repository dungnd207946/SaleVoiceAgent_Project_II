"""Drift-check tests for voice_agent._load_ack_assets.

The manifest voice comparison must be backend-aware: the elevenlabs backend
compares ELEVENLABS_* settings, every vieneu-family backend (vieneu /
vieneu_vllm / remote) compares VIENEU_VOICE_ID. A manifest generated for the
luna voice must NOT warn while luna is the live voice, and MUST warn after
the live voice changes.
"""

from __future__ import annotations

import json
import logging

import pytest

from noble_agent.config import settings
from noble_agent.voice.voice_agent import _load_ack_assets

_PCM = b"\x00" * 960


@pytest.fixture
def ack_dir(tmp_path, monkeypatch):
    d = tmp_path / "acks"
    d.mkdir()
    (d / "01_test.pcm").write_bytes(_PCM)
    monkeypatch.setattr(settings, "tool_ack_assets_dir", str(d))
    return d


def _write_manifest(d, **kw):
    (d / "manifest.json").write_text(json.dumps(kw), encoding="utf-8")


def test_no_manifest_loads_with_info(ack_dir, caplog):
    with caplog.at_level(logging.INFO):
        assets = _load_ack_assets()
    assert assets == [_PCM]
    assert any("without drift check" in r.message for r in caplog.records)


def test_sample_rate_mismatch_refuses_to_load(ack_dir, monkeypatch):
    monkeypatch.setattr(settings, "tts_sample_rate", 24000)
    _write_manifest(ack_dir, sample_rate=16000, voice_id="luna")
    assert _load_ack_assets() == []


def test_vieneu_voice_match_no_warning(ack_dir, monkeypatch, caplog):
    monkeypatch.setattr(settings, "tts_backend", "remote")
    monkeypatch.setattr(settings, "vieneu_voice_id", "luna")
    monkeypatch.setattr(settings, "tts_sample_rate", 24000)
    _write_manifest(ack_dir, sample_rate=24000, voice_id="luna", backend="remote")
    with caplog.at_level(logging.WARNING):
        assets = _load_ack_assets()
    assert assets == [_PCM]
    assert not any("drift" in r.message for r in caplog.records)


def test_vieneu_voice_mismatch_warns_but_loads(ack_dir, monkeypatch, caplog):
    monkeypatch.setattr(settings, "tts_backend", "remote")
    monkeypatch.setattr(settings, "vieneu_voice_id", "luna")
    monkeypatch.setattr(settings, "tts_sample_rate", 24000)
    _write_manifest(ack_dir, sample_rate=24000, voice_id="old_voice", backend="vieneu")
    with caplog.at_level(logging.WARNING):
        assets = _load_ack_assets()
    assert assets == [_PCM]  # still usable, just may sound off
    drift = [r.getMessage() for r in caplog.records if "drift" in r.message]
    assert drift and "old_voice" in drift[0] and "luna" in drift[0]


def test_backend_family_mismatch_warns(ack_dir, monkeypatch, caplog):
    """Manifest generated with elevenlabs while live runs vieneu-family → warn
    (remote vs vieneu is the SAME family and must not warn — covered above)."""
    monkeypatch.setattr(settings, "tts_backend", "remote")
    monkeypatch.setattr(settings, "vieneu_voice_id", "luna")
    monkeypatch.setattr(settings, "tts_sample_rate", 24000)
    _write_manifest(ack_dir, sample_rate=24000, voice_id="luna", backend="elevenlabs")
    with caplog.at_level(logging.WARNING):
        assets = _load_ack_assets()
    assert assets == [_PCM]
    assert any("drift" in r.message for r in caplog.records)


def test_elevenlabs_backend_still_compares_elevenlabs_fields(ack_dir, monkeypatch, caplog):
    monkeypatch.setattr(settings, "tts_backend", "elevenlabs")
    monkeypatch.setattr(settings, "tts_sample_rate", 24000)
    monkeypatch.setattr(settings, "elevenlabs_tts_voice_id", "live_el_voice")
    _write_manifest(ack_dir, sample_rate=24000, voice_id="other_el_voice", backend="elevenlabs")
    with caplog.at_level(logging.WARNING):
        assets = _load_ack_assets()
    assert assets == [_PCM]
    assert any("drift" in r.message for r in caplog.records)
