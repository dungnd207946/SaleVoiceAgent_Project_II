"""santa-tts loader config→kwargs wiring (Step 4).

vieneu/torch/neucodec are heavy + the import is function-local in the loader, so
we inject a fake `vieneu` module into sys.modules whose `Vieneu` is a Mock. No
real model is loaded. The module singleton is reset before each test.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from noble_agent.config import settings
from noble_agent.voice.tts import vieneu as vieneu_mod


@pytest.fixture
def fake_vieneu(monkeypatch):
    """Inject a fake `vieneu` module + reset the loader singleton."""
    monkeypatch.setattr(vieneu_mod, "_tts_instance", None)
    monkeypatch.setattr(vieneu_mod, "_voice_data", None)

    fake_tts = MagicMock(name="fake_tts")
    fake_tts.use_chat_format = False
    fake_tts.get_preset_voice.return_value = {"codes": [1, 2, 3], "text": "Xin chào"}

    fake_factory = MagicMock(name="Vieneu", return_value=fake_tts)
    fake_module = MagicMock(name="vieneu_module")
    fake_module.Vieneu = fake_factory
    monkeypatch.setitem(sys.modules, "vieneu", fake_module)

    monkeypatch.setattr(settings, "vieneu_backbone_repo", "NobleX-AI/santa-tts")
    monkeypatch.setattr(settings, "vieneu_backbone_device", "cuda")
    monkeypatch.setattr(settings, "vieneu_codec_repo", "neuphonic/neucodec-onnx-decoder-int8")
    monkeypatch.setattr(settings, "vieneu_codec_device", "cpu")
    monkeypatch.setattr(settings, "vieneu_voice_id", "luna")
    monkeypatch.setattr(settings, "vieneu_use_chat_format", None)
    monkeypatch.setattr(settings, "vieneu_presets_path", "")
    monkeypatch.setattr(settings, "hf_token", "hf_test_token")
    # Disable the out-of-band revision snapshot so backbone_repo passes through
    # unchanged (no network call; deterministic) — see _resolve_backbone_repo.
    monkeypatch.setattr(vieneu_mod, "snapshot_download", None)

    return fake_factory, fake_tts


def test_santa_loader_wires_kwargs_and_voice(fake_vieneu):
    fake_factory, fake_tts = fake_vieneu

    tts, voice = vieneu_mod._load_tts()

    assert tts is fake_tts
    # Vieneu(...) kwargs assembled from settings — the seam. The santa loader now
    # prefers lmdeploy "fast" mode (incremental streaming); the mock factory never
    # raises, so the fast branch wins and standard is the fallback.
    _, kwargs = fake_factory.call_args
    assert kwargs["mode"] == "fast"
    assert kwargs["backbone_repo"] == "NobleX-AI/santa-tts"
    assert kwargs["backbone_device"] == "cuda"
    assert kwargs["memory_util"] == 0.3  # fast-mode only
    assert "gguf_filename" not in kwargs  # gguf_filename is a standard-mode kwarg
    assert kwargs["codec_repo"] == "neuphonic/neucodec-onnx-decoder-int8"
    assert kwargs["codec_device"] == "cpu"
    assert kwargs["hf_token"] == "hf_test_token"

    # presets.json loaded from the module-relative reference dir.
    fake_tts._load_voices_from_file.assert_called_once()
    presets_arg = Path(fake_tts._load_voices_from_file.call_args[0][0])
    assert presets_arg.name == "presets.json"
    assert presets_arg.parent.name == "reference"

    # voice resolved via get_preset_voice("luna").
    fake_tts.get_preset_voice.assert_called_once_with("luna")
    assert voice == {"codes": [1, 2, 3], "text": "Xin chào"}

    # use_chat_format=None → library default untouched.
    assert fake_tts.use_chat_format is False


def test_santa_loader_presets_path_override(monkeypatch, fake_vieneu, tmp_path):
    _, fake_tts = fake_vieneu
    custom = tmp_path / "custom_presets.json"
    monkeypatch.setattr(settings, "vieneu_presets_path", str(custom))

    vieneu_mod._load_tts()

    assert Path(fake_tts._load_voices_from_file.call_args[0][0]) == custom


def test_santa_loader_use_chat_format_override(monkeypatch, fake_vieneu):
    _, fake_tts = fake_vieneu
    monkeypatch.setattr(settings, "vieneu_use_chat_format", True)

    vieneu_mod._load_tts()

    assert fake_tts.use_chat_format is True


def test_santa_loader_voice_fallback_on_missing(monkeypatch, fake_vieneu):
    _, fake_tts = fake_vieneu
    fake_tts.get_preset_voice.side_effect = [
        ValueError("not found"),  # requested "luna" missing
        {"codes": [9], "text": "fallback"},  # fallback to first available
    ]
    fake_tts.list_preset_voices.return_value = [("desc", "gemini")]

    _, voice = vieneu_mod._load_tts()

    assert voice == {"codes": [9], "text": "fallback"}
    # second resolution uses the first listed voice id.
    assert fake_tts.get_preset_voice.call_args_list[-1].args == ("gemini",)
