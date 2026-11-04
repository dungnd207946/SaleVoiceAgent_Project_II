"""Unit tests for the μ-law ↔ PCM16 codec helpers (Phase 1)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from noble_agent.transport.livekit.codec_utils import (
    pcm16_to_ulaw,
    ulaw_to_pcm16,
)

SAMPLE_RATE = 8000


def _sine_pcm16(freq_hz: int, duration_s: float, amplitude: int = 10_000) -> bytes:
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n) / SAMPLE_RATE
    samples = (np.sin(2 * math.pi * freq_hz * t) * amplitude).astype(np.int16)
    return samples.tobytes()


class TestLengthRelations:
    def test_ulaw_to_pcm16_doubles_length(self) -> None:
        assert len(ulaw_to_pcm16(b"\x80" * 160)) == 320

    def test_pcm16_to_ulaw_halves_length(self) -> None:
        assert len(pcm16_to_ulaw(b"\x00\x00" * 160)) == 160


class TestEmptyInput:
    def test_empty_ulaw(self) -> None:
        assert ulaw_to_pcm16(b"") == b""

    def test_empty_pcm16(self) -> None:
        assert pcm16_to_ulaw(b"") == b""


class TestOddLengthRejected:
    def test_odd_pcm16_raises(self) -> None:
        with pytest.raises(ValueError, match="length must be even"):
            pcm16_to_ulaw(b"\x00\x00\x00")


class TestSilence:
    def test_ulaw_silence_code_decodes_near_zero(self) -> None:
        # 0xFF is G.711 μ-law silence (positive zero). Decoded PCM16 is a
        # tiny positive sample (~8), not exactly zero.
        pcm = ulaw_to_pcm16(b"\xff" * 10)
        samples = np.frombuffer(pcm, dtype=np.int16)
        assert np.all(np.abs(samples) < 16)

    def test_pcm16_zero_encodes_to_silence_code(self) -> None:
        ulaw = pcm16_to_ulaw(b"\x00\x00" * 10)
        # G.711 μ-law positive zero is 0xFF.
        assert ulaw == b"\xff" * 10


class TestRoundTrip:
    """μ-law is lossy but bounded — round-trip must stay within the quantization
    envelope (~14-bit dynamic range => ~256 LSBs worst case)."""

    def test_sine_440_roundtrip_within_tolerance(self) -> None:
        pcm_in = _sine_pcm16(freq_hz=440, duration_s=0.25)
        ulaw = pcm16_to_ulaw(pcm_in)
        pcm_out = ulaw_to_pcm16(ulaw)
        assert len(pcm_out) == len(pcm_in)

        a = np.frombuffer(pcm_in, dtype=np.int16).astype(np.int32)
        b = np.frombuffer(pcm_out, dtype=np.int16).astype(np.int32)
        max_abs_diff = int(np.max(np.abs(a - b)))
        # G.711 μ-law quantization: worst-case error at high amplitudes is
        # around 1/128 of full-scale ≈ 256 LSBs.
        assert max_abs_diff < 400, f"round-trip diff {max_abs_diff} exceeds envelope"

    def test_ulaw_is_idempotent_under_double_roundtrip(self) -> None:
        """Second roundtrip must not drift further than the first."""
        pcm_in = _sine_pcm16(freq_hz=1000, duration_s=0.1)
        ulaw1 = pcm16_to_ulaw(pcm_in)
        pcm1 = ulaw_to_pcm16(ulaw1)
        ulaw2 = pcm16_to_ulaw(pcm1)
        # After one roundtrip, pcm1 is already on the μ-law grid, so
        # re-encoding must produce the same ulaw bytes.
        assert ulaw1 == ulaw2
