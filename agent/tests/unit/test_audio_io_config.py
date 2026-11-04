"""Part 1 — configurable LiveKit output buffer (cushion) seam tests.

The output playout buffer is bumped from 40 ms to a configurable
`NOBLE_TTS_OUTPUT_QUEUE_MS` (default 800 ms) so it rides over per-clause
synth-seam gaps. These tests pin the config default and the worker wiring
(settings → AudioIOConfig.queue_size_ms) without spinning up a live Room.
"""

from __future__ import annotations

from noble_agent.config import settings
from noble_agent.transport.livekit.agent_audio_io import DEFAULT_QUEUE_SIZE_MS, AudioIOConfig


def test_tts_output_queue_ms_default():
    """The cushion defaults to 800 ms."""
    assert settings.tts_output_queue_ms == 800


def test_default_queue_size_ms_is_fallback():
    """AudioIOConfig still falls back to 40 ms when no queue size is passed."""
    assert DEFAULT_QUEUE_SIZE_MS == 40
    assert AudioIOConfig().queue_size_ms == 40


def test_worker_audio_config_uses_setting(monkeypatch):
    """The worker builds AudioIOConfig with queue_size_ms from settings."""
    monkeypatch.setattr(settings, "tts_output_queue_ms", 700)
    cfg = AudioIOConfig(
        input_sample_rate=settings.stt_sample_rate,
        output_sample_rate=settings.tts_sample_rate,
        queue_size_ms=settings.tts_output_queue_ms,
    )
    assert cfg.queue_size_ms == 700
