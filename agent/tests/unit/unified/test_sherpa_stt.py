"""Unit tests for the pure helpers in voice/stt/sherpa.py.

These import only the pure functions (`_compose_model_paths`,
`_discover_model_stem`, `_ensure_model_present`, `_postprocess_text`) — they
must NOT trigger a sherpa-onnx model load (the heavy load lives inside
`_get_recognizer`, never called here).
"""

import pytest

from noble_agent.voice.stt import sherpa as sherpa_mod
from noble_agent.voice.stt.sherpa import (
    _compose_model_paths,
    _discover_model_stem,
    _ensure_model_present,
    _postprocess_text,
)


def test_compose_model_paths_builds_triplet_and_tokens():
    paths = _compose_model_paths("models/hynt-bilingual", "epoch-20-avg-5-chunk-16-left-128")
    assert paths == {
        "encoder": "models/hynt-bilingual/encoder-epoch-20-avg-5-chunk-16-left-128.onnx",
        "decoder": "models/hynt-bilingual/decoder-epoch-20-avg-5-chunk-16-left-128.onnx",
        "joiner": "models/hynt-bilingual/joiner-epoch-20-avg-5-chunk-16-left-128.onnx",
        "tokens": "models/hynt-bilingual/tokens.txt",
    }


def test_compose_model_paths_int8_variant():
    paths = _compose_model_paths("models/hynt-bilingual", "epoch-20-avg-5-chunk-16-left-128.int8")
    assert paths["encoder"] == "models/hynt-bilingual/encoder-epoch-20-avg-5-chunk-16-left-128.int8.onnx"
    assert paths["decoder"] == "models/hynt-bilingual/decoder-epoch-20-avg-5-chunk-16-left-128.int8.onnx"
    assert paths["joiner"] == "models/hynt-bilingual/joiner-epoch-20-avg-5-chunk-16-left-128.int8.onnx"
    assert paths["tokens"] == "models/hynt-bilingual/tokens.txt"


def test_postprocess_preserve_case_keeps_punct_and_casing():
    assert _postprocess_text("  Hello iPhone, xin chào. ", preserve_case=True) == "Hello iPhone, xin chào."


def test_postprocess_legacy_lowercases():
    assert _postprocess_text("  Hello iPhone, xin chào. ", preserve_case=False) == "Hello iphone, xin chào."


# ── _discover_model_stem (pure glob over a filename list) ───────────────────────

_LISTING = [
    "encoder-epoch-20-avg-5.onnx",
    "decoder-epoch-20-avg-5.onnx",
    "joiner-epoch-20-avg-5.onnx",
    "encoder-epoch-20-avg-5.int8.onnx",
    "decoder-epoch-20-avg-5.int8.onnx",
    "joiner-epoch-20-avg-5.int8.onnx",
    "tokens.txt",
]


def test_discover_stem_fp32_excludes_int8():
    assert _discover_model_stem(_LISTING, quantize=False) == "epoch-20-avg-5"


def test_discover_stem_int8_selects_int8():
    assert _discover_model_stem(_LISTING, quantize=True) == "epoch-20-avg-5.int8"


def test_discover_stem_none_when_no_match():
    # int8 family requested but only fp32 encoders present → None (triggers download).
    listing = ["encoder-epoch-20-avg-5.onnx", "tokens.txt"]
    assert _discover_model_stem(listing, quantize=True) is None


def test_discover_stem_ambiguous_raises():
    listing = [
        "encoder-epoch-10-avg-3.onnx",
        "encoder-epoch-20-avg-5.onnx",
    ]
    with pytest.raises(ValueError, match="epoch-10-avg-3"):
        _discover_model_stem(listing, quantize=False)


# ── _ensure_model_present (glob → download@revision → re-glob → raise) ──────────


def test_ensure_present_skips_download_when_stem_found(tmp_path, monkeypatch):
    name = "epoch-20-avg-5"
    for f in (f"encoder-{name}.onnx", f"decoder-{name}.onnx", f"joiner-{name}.onnx", "tokens.txt"):
        (tmp_path / f).write_text("x")

    calls = []
    monkeypatch.setattr(sherpa_mod, "snapshot_download", lambda **kw: calls.append(kw))

    stem = _ensure_model_present(
        str(tmp_path), quantize=False, repo_id="NobleX-AI/santa-stt", token="tok", revision="prod"
    )
    assert stem == name
    assert calls == []  # stem found → no download


def test_ensure_present_downloads_with_revision_then_reglobs(tmp_path, monkeypatch):
    name = "epoch-20-avg-5"
    calls = []

    def fake_download(**kw):
        calls.append(kw)
        for f in (f"encoder-{name}.onnx", f"decoder-{name}.onnx", f"joiner-{name}.onnx", "tokens.txt"):
            (tmp_path / f).write_text("x")

    monkeypatch.setattr(sherpa_mod, "snapshot_download", fake_download)

    stem = _ensure_model_present(
        str(tmp_path), quantize=False, repo_id="NobleX-AI/santa-stt", token="tok", revision="prod"
    )
    assert stem == name
    assert len(calls) == 1
    assert calls[0]["repo_id"] == "NobleX-AI/santa-stt"
    assert calls[0]["local_dir"] == str(tmp_path)
    assert calls[0]["token"] == "tok"
    assert calls[0]["revision"] == "prod"


def test_ensure_present_int8_family(tmp_path, monkeypatch):
    name = "epoch-20-avg-5"
    for f in (
        f"encoder-{name}.onnx",
        f"decoder-{name}.onnx",
        f"joiner-{name}.onnx",
        f"encoder-{name}.int8.onnx",
        f"decoder-{name}.int8.onnx",
        f"joiner-{name}.int8.onnx",
        "tokens.txt",
    ):
        (tmp_path / f).write_text("x")

    calls = []
    monkeypatch.setattr(sherpa_mod, "snapshot_download", lambda **kw: calls.append(kw))

    stem = _ensure_model_present(
        str(tmp_path), quantize=True, repo_id="NobleX-AI/santa-stt", token="tok", revision="prod"
    )
    assert stem == f"{name}.int8"
    assert calls == []


def test_ensure_present_raises_when_still_missing_after_download(tmp_path, monkeypatch):
    monkeypatch.setattr(sherpa_mod, "snapshot_download", lambda **kw: None)  # writes nothing
    with pytest.raises(FileNotFoundError, match=str(tmp_path)):
        _ensure_model_present(
            str(tmp_path), quantize=False, repo_id="NobleX-AI/santa-stt", token="tok", revision="prod"
        )


def test_ensure_present_empty_token_passes_none(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sherpa_mod, "snapshot_download", lambda **kw: calls.append(kw))
    with pytest.raises(FileNotFoundError):
        _ensure_model_present(str(tmp_path), quantize=False, repo_id="repo/x", token="", revision="prod")
    assert calls[0]["token"] is None  # empty token → None (anonymous / env-based)
