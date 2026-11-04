"""Unit tests for voice.audio_guard (not integrated into session yet)."""

from __future__ import annotations

import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from noble_agent.voice.audio_guard import (  # noqa: E402
    ConsecutiveFramesGate,
    EchoCooldown,
    RepetitionDetector,
    WhisperHallucinationFilter,
)


def test_echo_cooldown_blocks_then_releases():
    g = EchoCooldown(min_tts_ms=50_000, min_tts_bytes=10_000_000, cooldown_sec=0.05)
    g.on_tts_start()
    assert g.allow_stt() is False
    g.on_tts_done()
    assert g.allow_stt() is False
    time.sleep(0.08)
    assert g.allow_stt() is True


def test_consecutive_frames_gate_confirms_loud_speech():
    # 320 samples int16 little-endian = 640 bytes = one frame at 16kHz 20ms
    loud = struct.pack("<320h", *([12000] * 320))
    gate = ConsecutiveFramesGate(min_rms=100.0, required_consecutive=3)
    chunk = loud * 4
    assert gate.feed(chunk) is True
    assert gate.confirmed is True


def test_consecutive_frames_gate_reset_on_silence():
    loud = struct.pack("<320h", *([12000] * 320))
    quiet = b"\x00\x00" * 320
    gate = ConsecutiveFramesGate(min_rms=100.0, required_consecutive=3)
    gate.feed(loud * 2)
    gate.feed(quiet)
    assert gate.confirmed is False


def test_whisper_hallucination_filter():
    f = WhisperHallucinationFilter()
    assert f.is_hallucination("Thank you.") is True
    assert f.is_hallucination("Cảm ơn.") is True
    assert f.is_hallucination("Noble Crystal Long Biên giá bao nhiêu ạ?") is False


def test_repetition_detector():
    d = RepetitionDetector(threshold=0.9, window=5)
    text = "Noble Crystal Long Biên có nhiều tiện ích cho cư dân"
    assert d.is_repetition(text) is False
    d.record(text)
    assert d.is_repetition(text) is True
    d.reset()
    assert d.history_size == 0
