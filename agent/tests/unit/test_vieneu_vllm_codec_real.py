"""Real codec-only construction test for the `vieneu_vllm` backend.

Exercises the REAL `_load_codec_only()` — NO GPU, NO server, NO HF download
(the ONNX int8 decoder + santa-tts presets are cached locally). This is the
offline guard for the class of bug where the codec-only construction crashes:
the lib's `__init__` runs `backbone_repo.rstrip("/")` UNCONDITIONALLY before the
`if backbone_repo:` load guard, so `backbone_repo=None` → AttributeError. The fix
passes `backbone_repo=""` (falsy → skips the GPU backbone load, no crash). A
fake-only test cannot catch this because it stubs `_load_codec_only` out entirely.

Runs in `make test-unit` when the codec is cached (the default in this repo /
CI image with the HF cache warmed). If the optional `tts-vieneu` dep or the codec
artifacts are absent, the test SKIPS rather than failing — it must never crash a
clean environment, only guard the real construction when the deps are present.
"""

from __future__ import annotations

import pytest


def _codec_available() -> bool:
    try:
        import vieneu.standard  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _codec_available(), reason="vieneu/codec not installed")
def test_load_codec_only_constructs_with_empty_backbone():
    """Real `_load_codec_only()` constructs the lib instance with `backbone_repo=""`
    (the None→"" fix) and returns a `(tts, voice)` whose voice has `codes` + `text`.

    A regression to `backbone_repo=None` raises `AttributeError: 'NoneType' object
    has no attribute 'rstrip'` inside the lib `__init__`, which this catches offline.
    """
    import noble_agent.voice.tts.vieneu_vllm as mod

    # Reset the module singleton so we exercise the real construction path, not a
    # value cached by an earlier test in this process.
    mod._tts_instance = None
    mod._voice_data = None

    try:
        tts, voice = mod._load_codec_only()
    except (FileNotFoundError, OSError) as exc:
        pytest.skip(f"codec/presets artifacts not cached locally: {exc}")

    assert tts is not None
    assert isinstance(voice, dict)
    assert "codes" in voice
    assert "text" in voice
    assert len(voice["codes"]) > 0
    assert isinstance(voice["text"], str) and voice["text"]
