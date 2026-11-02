from noble_agent import config as cfg
from noble_agent.config import UnifiedSettings


def _default(name: str):
    """Class-level field default — independent of any live `.env` override."""
    return UnifiedSettings.model_fields[name].default


def test_input_gate_defaults():
    assert _default("stt_input_gate_mode") == "off"
    assert _default("audio_gate_preroll_chunks") == 3
    assert _default("audio_gate_min_rms") == 160.0
    assert _default("audio_gate_required_consecutive") == 3
    assert _default("audio_gate_barge_in_rms") == 2400.0
    assert _default("stt_vad_gate_hangover_ms") == 300
    assert _default("stt_gate_keepalive_max_sec") == 2.0


def test_speaker_defaults():
    assert _default("speaker_verification_enabled") is False
    assert _default("speaker_remote_timeout") == 3.0
    assert _default("speaker_model_name") == "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
    assert _default("speaker_hf_repo") == "csukuangfj/speaker-embedding-models"
    assert _default("speaker_hf_revision") == "main"
    assert _default("speaker_match_threshold") == 0.5
    assert _default("speaker_min_enroll_sec") == 1.0


def test_speaker_mode_defaults():
    assert _default("speaker_mode") == "off"


def test_parallel_spv_defaults():
    assert _default("spv_max_centroids") == 10


def test_resolve_speaker_mode_legacy_bool(monkeypatch):
    s = cfg.get_settings()
    monkeypatch.setattr(s, "speaker_mode", "off", raising=False)
    monkeypatch.setattr(s, "speaker_verification_enabled", True, raising=False)
    assert cfg.resolve_speaker_mode() == "single"


def test_resolve_speaker_mode_explicit(monkeypatch):
    s = cfg.get_settings()
    monkeypatch.setattr(s, "speaker_mode", "multi", raising=False)
    monkeypatch.setattr(s, "speaker_verification_enabled", False, raising=False)
    assert cfg.resolve_speaker_mode() == "multi"


def test_resolve_speaker_mode_unknown_falls_off(monkeypatch):
    s = cfg.get_settings()
    monkeypatch.setattr(s, "speaker_mode", "bogus", raising=False)
    monkeypatch.setattr(s, "speaker_verification_enabled", False, raising=False)
    assert cfg.resolve_speaker_mode() == "off"


def test_spv_registry_defaults():
    assert _default("spv_probe_marks_sec") == "0.25,0.4,0.6,0.9,1.3"
    assert _default("spv_probe_bonus") == "0.15,0.1,0.05,0,0"
    assert _default("spv_probe_tail_window_sec") == 1.5
    assert _default("spv_probe_tail_hop_sec") == 1.0
    assert _default("spv_enroll_window_sec") == 1.5
    assert _default("spv_enroll_hop_sec") == 0.75
    assert _default("spv_enroll_consensus_sim") == 0.5
    assert _default("spv_enroll_min_cluster") == 2
    assert _default("spv_adapt_margin") == 0.1
    assert _default("spv_max_identities") == 4
    assert _default("spv_mismatch_streak_max") == 2
    assert _default("spv_utt_cap_sec") == 30.0
    assert _default("spv_max_centroids") == 10
    assert _default("spv_min_match_probe") == 2
    assert _default("spv_min_match_identify") == 1


def test_removed_fields_are_gone():

    for name in ("speaker_interrupt_min_sec", "spv_chunk_sec", "speaker_embed_window_sec"):
        assert name not in UnifiedSettings.model_fields


def test_parse_probe_schedule_applies_bonus_to_base_threshold():
    import pytest

    from noble_agent.config import parse_probe_schedule

    marks, thresholds = parse_probe_schedule("0.25,0.4,0.6", "0.15,0.1,0", 0.5)
    assert marks == (0.25, 0.4, 0.6)
    assert thresholds == pytest.approx((0.65, 0.6, 0.5))


def test_parse_probe_schedule_rejects_length_mismatch():
    import pytest

    from noble_agent.config import parse_probe_schedule

    with pytest.raises(ValueError, match="cùng số phần tử"):
        parse_probe_schedule("0.25,0.4", "0.15", 0.5)


def test_parse_probe_schedule_rejects_non_increasing_marks():
    import pytest

    from noble_agent.config import parse_probe_schedule

    with pytest.raises(ValueError, match="tăng dần"):
        parse_probe_schedule("0.4,0.25", "0,0", 0.5)


def test_parse_probe_schedule_rejects_empty():
    import pytest

    from noble_agent.config import parse_probe_schedule

    with pytest.raises(ValueError, match="rỗng"):
        parse_probe_schedule("", "", 0.5)


def test_parse_probe_schedule_rejects_threshold_out_of_range():
    import pytest

    from noble_agent.config import parse_probe_schedule

    with pytest.raises(ValueError, match="ngoài khoảng"):
        parse_probe_schedule("0.25,0.4", "0.6,0.5", 0.5)  # 0.5+0.6 = 1.1 > 1
