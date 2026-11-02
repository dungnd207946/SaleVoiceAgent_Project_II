"""Pure-helper transform for the offline vieneu preset builder (Step 2).

`scripts/` isn't a package; load the module by path so the test runs without
any heavy vieneu/torch/neucodec import (build_presets must not import them).
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_vieneu_voices.py"


def _load_build_presets():
    spec = importlib.util.spec_from_file_location("build_vieneu_voices", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_presets


def test_build_presets_shape_and_carry_through():
    build_presets = _load_build_presets()
    voices = {
        "luna": {"wav": "luna.wav", "text": "Xin chào"},
        "gemini": {"wav": "gemini.wav", "text": "Dạ vâng"},
    }
    calls = []

    def encode_fn(wav_path):
        calls.append(wav_path)
        return [1, 2, 3] if "luna" in wav_path else [4, 5, 6]

    out = build_presets(voices, encode_fn, default_voice="luna")

    # meta block present.
    assert out["meta"]["spec"] == "vieneu.voice.presets"
    # default carried through.
    assert out["default_voice"] == "luna"
    # both voices encoded; codes + text carried through.
    assert set(out["presets"]) == {"luna", "gemini"}
    assert out["presets"]["luna"]["codes"] == [1, 2, 3]
    assert out["presets"]["luna"]["text"] == "Xin chào"
    assert out["presets"]["gemini"]["codes"] == [4, 5, 6]
    assert out["presets"]["gemini"]["text"] == "Dạ vâng"
    # encode_fn was actually invoked per wav.
    assert len(calls) == 2


def test_build_presets_unknown_default_raises():
    build_presets = _load_build_presets()
    voices = {"luna": {"wav": "luna.wav", "text": "Xin chào"}}

    with pytest.raises(ValueError, match="default_voice"):
        build_presets(voices, lambda _p: [1], default_voice="nonexistent")
