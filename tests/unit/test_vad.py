"""Unit tests for SileroVAD (mocked model, no torch / silero-vad weights needed)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from unittest.mock import MagicMock

import numpy as np
import pytest

# Mock torch + the silero-vad loader before touching the VAD
mock_torch = MagicMock()
mock_model = MagicMock()
mock_model.eval = MagicMock(return_value=mock_model)
mock_model.return_value = MagicMock(item=MagicMock(return_value=0.1))
mock_torch.hub.load.return_value = (mock_model, None)
mock_torch.from_numpy = MagicMock(side_effect=lambda x: x)
mock_torch.no_grad.return_value.__enter__ = MagicMock(return_value=None)
mock_torch.no_grad.return_value.__exit__ = MagicMock(return_value=False)
mock_loader = MagicMock(return_value=mock_model)  # stands in for silero_vad.load_silero_vad

# NOTE: We do NOT swap `sys.modules['torch']` at import time — that was
# the pre-Phase-3 approach and is inherently fragile (it only works if
# `noble_agent.voice.vad.silero` hasn't been imported yet by any sibling
# test, which Phase 3+ imports broke). Instead, keep `sys.modules` stable
# and patch the `torch` reference on the already-loaded `silero` module
# via the `_mocked_silero_torch` autouse fixture below.

from noble_agent.config import settings
from noble_agent.voice.vad import silero as _silero_mod
from noble_agent.voice.vad.silero import SileroVAD, VADState


@pytest.fixture(autouse=True)
def _mocked_silero_torch(monkeypatch):
    """Swap `silero.torch` + the model loader to mocks *only* for this module.
    Keeps `sys.modules['noble_agent.voice.vad']` stable so the enum class
    `VADState` retains its identity for every other test that imports it.
    """
    real_torch = _silero_mod.torch
    _silero_mod.torch = mock_torch
    monkeypatch.setattr(_silero_mod, "load_silero_vad", mock_loader, raising=False)
    mock_loader.reset_mock()
    mock_torch.hub.load.reset_mock()
    _silero_mod._load_shared_model.cache_clear()  # never reuse a model loaded by another module
    try:
        yield
    finally:
        _silero_mod._load_shared_model.cache_clear()
        _silero_mod.torch = real_torch


def _make_pcm(duration_ms: int = 32, sample_rate: int = 16000, amplitude: int = 0) -> bytes:
    """Constant-valued int16 PCM — RMS equals `amplitude` exactly."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return np.full(n_samples, amplitude, dtype=np.int16).tobytes()


LOUD = 3000  # well above settings.barge_in_rms_threshold (1500)
QUIET = 500  # below it — echo-residual territory


@pytest.fixture
def vad():
    v = SileroVAD()
    v._model = mock_model
    # Reset default to no speech
    mock_model.return_value = MagicMock(item=MagicMock(return_value=0.1))
    v.set_idle()
    return v


def _set_speech(prob: float):
    mock_model.return_value = MagicMock(item=MagicMock(return_value=prob))


class TestVADStateMachine:
    """Only barge-in is decided here; utterance endpointing belongs to STT.
    So the machine is IDLE (agent silent) / SPEAKING (agent turn armed) /
    INTERRUPTED (latched barge-in) — nothing else."""

    def test_state_machine_has_exactly_three_states(self):
        assert {s.name for s in VADState} == {"IDLE", "SPEAKING", "INTERRUPTED"}

    def test_dead_endpointing_knobs_removed(self):
        # vad_silence_ms / vad_min_speech_ms only ever fed the inert
        # LISTENING→PROCESSING path — keeping them would be a tuning trap.
        assert not hasattr(settings, "vad_silence_ms")
        assert not hasattr(settings, "vad_min_speech_ms")

    def test_initial_state_idle(self, vad):
        assert vad.state == VADState.IDLE

    def test_idle_reports_speech_but_stays_idle(self, vad):
        _set_speech(0.9)
        for _ in range(10):
            result = vad.process_chunk(_make_pcm())
        assert result["is_speech"] is True  # raw verdict still feeds vad-gate / addressee tracker
        assert vad.state == VADState.IDLE

    def test_idle_stays_on_silence(self, vad):
        _set_speech(0.1)
        for _ in range(20):
            vad.process_chunk(_make_pcm())
        assert vad.state == VADState.IDLE

    def test_set_speaking(self, vad):
        vad.set_speaking()
        assert vad.state == VADState.SPEAKING

    def test_speaking_to_interrupted(self, vad):
        vad.set_speaking()
        _set_speech(0.9)
        for _ in range(10):
            vad.process_chunk(_make_pcm())
        assert vad.state == VADState.INTERRUPTED

    def test_speaking_no_interrupt_on_noise_burst(self, vad):
        vad.set_speaking()
        _set_speech(0.9)
        vad.process_chunk(_make_pcm())
        _set_speech(0.1)
        vad.process_chunk(_make_pcm())
        assert vad.state == VADState.SPEAKING

    def test_interrupted_latches_until_rearmed(self, vad):
        # Sessions rely on this latch (see base_session/telephony re-arm comments).
        vad.set_speaking()
        _set_speech(0.9)
        for _ in range(3):
            vad.process_chunk(_make_pcm())
        assert vad.state == VADState.INTERRUPTED
        _set_speech(0.1)
        for _ in range(50):
            vad.process_chunk(_make_pcm())
        assert vad.state == VADState.INTERRUPTED
        vad.set_speaking()
        assert vad.state == VADState.SPEAKING

    def test_set_idle_resets(self, vad):
        vad.set_speaking()
        _set_speech(0.9)
        vad.process_chunk(_make_pcm())
        vad.process_chunk(_make_pcm())
        vad.set_idle()
        assert vad.state == VADState.IDLE
        assert vad._interrupt_chunks == 0

    def test_process_chunk_returns_correct_keys(self, vad):
        result = vad.process_chunk(_make_pcm())
        assert set(result) >= {"speech_prob", "is_speech", "rms", "state", "state_changed"}


class TestBargeInRmsGate:
    """`barge_in_rms_threshold` — quiet speech-like audio (AEC echo residual)
    must NOT confirm an interrupt while agent audio is actually playing
    (`playback_active`, set by the session on its first emitted TTS chunk).
    Before playback (LLM thinking) there is no echo, so no floor."""

    def test_process_chunk_reports_rms(self, vad):
        result = vad.process_chunk(_make_pcm(amplitude=LOUD))
        assert result["rms"] == pytest.approx(LOUD)

    def test_playback_active_defaults_false(self, vad):
        assert vad.playback_active is False

    def test_floor_not_applied_before_playback_starts(self, vad, monkeypatch):
        monkeypatch.setattr(settings, "barge_in_rms_threshold", 1500.0)
        vad.set_speaking()  # turn armed, LLM still thinking — nothing playing yet
        _set_speech(0.9)
        for _ in range(3):
            vad.process_chunk(_make_pcm(amplitude=QUIET))
        assert vad.state == VADState.INTERRUPTED

    def test_set_idle_clears_playback_active(self, vad):
        vad.playback_active = True
        vad.set_idle()
        assert vad.playback_active is False

    def test_set_speaking_keeps_playback_active(self, vad):
        # Mid-turn re-arms (addressee / speaker-floor paths) happen while audio
        # is still playing — they must not drop the floor.
        vad.playback_active = True
        vad.set_speaking()
        assert vad.playback_active is True

    def test_logs_floor_rejection_once_per_turn(self, vad, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(settings, "barge_in_rms_threshold", 1500.0)
        _set_speech(0.9)
        with caplog.at_level(logging.INFO, logger="noble_agent.voice.vad.silero"):
            vad.set_speaking()
            vad.playback_active = True
            for _ in range(5):
                vad.process_chunk(_make_pcm(amplitude=QUIET))
            vad.set_idle()
            vad.set_speaking()
            vad.playback_active = True
            for _ in range(3):
                vad.process_chunk(_make_pcm(amplitude=QUIET))
        assert sum("RMS floor" in r.getMessage() for r in caplog.records) == 2

    def test_speaking_ignores_quiet_speech_below_threshold(self, vad, monkeypatch):
        monkeypatch.setattr(settings, "barge_in_rms_threshold", 1500.0)
        vad.set_speaking()
        vad.playback_active = True
        _set_speech(0.9)
        for _ in range(10):
            vad.process_chunk(_make_pcm(amplitude=QUIET))
        assert vad.state == VADState.SPEAKING

    def test_speaking_to_interrupted_on_loud_speech(self, vad, monkeypatch):
        monkeypatch.setattr(settings, "barge_in_rms_threshold", 1500.0)
        vad.set_speaking()
        vad.playback_active = True
        _set_speech(0.9)
        for _ in range(3):
            vad.process_chunk(_make_pcm(amplitude=LOUD))
        assert vad.state == VADState.INTERRUPTED

    def test_quiet_chunk_resets_interrupt_debounce(self, vad, monkeypatch):
        monkeypatch.setattr(settings, "barge_in_rms_threshold", 1500.0)
        vad.set_speaking()
        vad.playback_active = True
        _set_speech(0.9)
        vad.process_chunk(_make_pcm(amplitude=LOUD))
        vad.process_chunk(_make_pcm(amplitude=LOUD))
        vad.process_chunk(_make_pcm(amplitude=QUIET))  # breaks the run of 3
        vad.process_chunk(_make_pcm(amplitude=LOUD))
        vad.process_chunk(_make_pcm(amplitude=LOUD))
        assert vad.state == VADState.SPEAKING

    def test_threshold_zero_disables_gate(self, vad, monkeypatch):
        monkeypatch.setattr(settings, "barge_in_rms_threshold", 0.0)
        vad.set_speaking()
        vad.playback_active = True
        _set_speech(0.9)
        for _ in range(3):
            vad.process_chunk(_make_pcm(amplitude=0))
        assert vad.state == VADState.INTERRUPTED

    def test_gate_not_applied_outside_speaking(self, vad, monkeypatch):
        monkeypatch.setattr(settings, "barge_in_rms_threshold", 1500.0)
        vad.playback_active = True
        _set_speech(0.9)
        result = vad.process_chunk(_make_pcm(amplitude=QUIET))
        assert result["is_speech"] is True  # raw Silero verdict untouched (vad-gate, addressee tracker)
        assert vad.state == VADState.IDLE


class TestModelSharing:
    """The Silero weights come from the pinned `silero-vad` wheel (no torch.hub,
    no network), load once per process, and each session gets its own copy
    (the JIT model carries LSTM state, so instances must not share one)."""

    def test_model_loaded_once_per_process_from_pinned_package(self):
        SileroVAD()
        SileroVAD()
        assert mock_loader.call_count == 1
        mock_torch.hub.load.assert_not_called()

    def test_instances_do_not_share_model_object(self):
        a = SileroVAD()
        b = SileroVAD()
        assert a._model is not b._model


class TestChunkWindowValidation:
    """Silero v5+ only accepts a fixed window (512 samples @ 16 kHz). A wrong
    VAD_CHUNK_MS must fail loudly at load/construct time, not inside every
    process_chunk call."""

    def test_construct_rejects_wrong_window(self, monkeypatch):
        monkeypatch.setattr(_silero_mod, "CHUNK_SAMPLES", 320)  # VAD_CHUNK_MS=20
        with pytest.raises(ValueError, match="VAD_CHUNK_MS"):
            SileroVAD()

    def test_shared_loader_rejects_wrong_window(self, monkeypatch):
        monkeypatch.setattr(_silero_mod, "CHUNK_SAMPLES", 320)
        with pytest.raises(ValueError, match="VAD_CHUNK_MS"):
            _silero_mod._load_shared_model()
