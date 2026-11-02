"""Config wiring for the VieNeu santa-tts backend (Step 1)."""

from noble_agent.config import UnifiedSettings


def test_vieneu_settings_defaults():
    """The 6 new VieNeu fields exist with the documented defaults."""
    # _env_file=None → assert the code defaults, not whatever .env happens to set.
    s = UnifiedSettings(_env_file=None)

    assert s.vieneu_backbone_device == "cuda"
    assert s.vieneu_codec_repo == "neuphonic/neucodec-onnx-decoder-int8"
    assert s.vieneu_codec_device == "cpu"
    assert s.vieneu_presets_path == ""
    assert s.vieneu_use_chat_format is None
    # Reused/existing fields stay addressable.
    assert hasattr(s, "vieneu_backbone_repo")
    assert hasattr(s, "vieneu_voice_id")
    assert hasattr(s, "hf_token")


def test_tts_streaming_default_true():
    """Token-level streaming is ON by default; NOBLE_TTS_STREAMING=false rolls back."""
    assert UnifiedSettings(_env_file=None).tts_streaming is True
    assert UnifiedSettings(_env_file=None, tts_streaming=False).tts_streaming is False


def test_vieneu_vllm_settings_defaults():
    """Phase 2: the vLLM-client TTS backend fields exist with documented defaults."""
    s = UnifiedSettings(_env_file=None)

    assert s.vieneu_vllm_url == "http://localhost:8000"
    assert s.vieneu_vllm_model == "NobleX-AI/santa-tts"
    assert s.vieneu_vllm_temperature == 1.0
    assert s.vieneu_vllm_top_k == 50
    assert s.vieneu_vllm_max_tokens == 1024
    assert s.vieneu_vllm_max_model_len == 2048
    assert s.vieneu_vllm_min_tokens == 50
