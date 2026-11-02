"""Unit tests for the pure backbone-repo resolver in voice/tts/vieneu.py.

These import only `_resolve_backbone_repo` — they must NOT trigger a vieneu
model load (the heavy `from vieneu import Vieneu` lives inside the loader
functions, never called here).
"""

from noble_agent.voice.tts import vieneu as vieneu_mod
from noble_agent.voice.tts.vieneu import _resolve_backbone_repo


def test_resolve_backbone_local_dir_unchanged(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(vieneu_mod, "snapshot_download", lambda **kw: calls.append(kw))
    out = _resolve_backbone_repo(str(tmp_path), revision="prod", token="tok")
    assert out == str(tmp_path)
    assert calls == []  # local dir → no snapshot


def test_resolve_backbone_hf_repo_snapshots_at_revision(monkeypatch):
    calls = []

    def fake_download(**kw):
        calls.append(kw)
        return "/cache/snap/santa-tts"

    monkeypatch.setattr(vieneu_mod, "snapshot_download", fake_download)
    out = _resolve_backbone_repo("NobleX-AI/santa-tts", revision="prod", token="tok")
    assert out == "/cache/snap/santa-tts"
    assert calls[0]["repo_id"] == "NobleX-AI/santa-tts"
    assert calls[0]["revision"] == "prod"
    assert calls[0]["token"] == "tok"


def test_resolve_backbone_empty_token_passes_none(monkeypatch):
    calls = []
    monkeypatch.setattr(vieneu_mod, "snapshot_download", lambda **kw: calls.append(kw) or "/x")
    _resolve_backbone_repo("NobleX-AI/santa-tts", revision="prod", token="")
    assert calls[0]["token"] is None


def test_resolve_backbone_download_failure_returns_original(monkeypatch, caplog):
    def boom(**kw):
        raise RuntimeError("revision not found")

    monkeypatch.setattr(vieneu_mod, "snapshot_download", boom)
    out = _resolve_backbone_repo("NobleX-AI/santa-tts", revision="prod", token="tok")
    assert out == "NobleX-AI/santa-tts"  # falls back to original → library handles download
