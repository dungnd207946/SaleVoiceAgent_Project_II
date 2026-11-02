"""Audio resampler for telephony — 8kHz (Asterisk) ↔ 16kHz (STT) ↔ 24kHz (TTS).

Uses soxr (libsoxr bindings) for high-quality resampling with proper
anti-aliasing. Falls back to scipy.signal.resample_poly, then to numpy
linear interpolation as last resort.

Why this matters for telephony:
  24kHz TTS → 8kHz telephony is a 3:1 downsampling. Without an anti-aliasing
  low-pass filter, frequencies above 4kHz fold back as aliasing artifacts
  (buzzing, ringing, metallic sound). soxr applies a steep low-pass filter
  before decimation, producing clean narrowband audio.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("telephony.resampler")

# Sample rates
TELEPHONY_RATE = 8000  # Asterisk slin (narrowband)
STT_RATE = 16000  # STT input
TTS_RATE = 24000  # TTS output

# Select best available resampler
_BACKEND = "numpy"  # fallback

try:
    import soxr

    _BACKEND = "soxr"
except ImportError:
    try:
        from scipy.signal import resample_poly as _scipy_resample

        _BACKEND = "scipy"
    except ImportError:
        pass

logger.info("Telephony resampler backend: %s", _BACKEND)


def _resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample PCM int16 mono with anti-aliasing."""
    if src_rate == dst_rate:
        return pcm
    samples_in = np.frombuffer(pcm, dtype=np.int16)
    if len(samples_in) == 0:
        return b""

    if _BACKEND == "soxr":
        # soxr: highest quality, built-in anti-aliasing
        # HQ = High Quality preset (good balance of speed and quality)
        resampled = soxr.resample(
            samples_in.astype(np.float32),
            src_rate,
            dst_rate,
            quality="HQ",
        )
        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()

    if _BACKEND == "scipy":
        # scipy: polyphase filter with anti-aliasing
        from math import gcd

        g = gcd(src_rate, dst_rate)
        up = dst_rate // g
        down = src_rate // g
        resampled = _scipy_resample(samples_in.astype(np.float32), up, down)
        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()

    # numpy fallback: linear interpolation (no anti-aliasing — lowest quality)
    samples_f = samples_in.astype(np.float32)
    ratio = dst_rate / src_rate
    out_len = int(len(samples_f) * ratio)
    if out_len == 0:
        return b""
    indices = np.arange(out_len) / ratio
    lo = np.floor(indices).astype(np.int64)
    lo = np.clip(lo, 0, len(samples_f) - 1)
    hi = np.clip(lo + 1, 0, len(samples_f) - 1)
    frac = (indices - lo).astype(np.float32)
    resampled = samples_f[lo] * (1 - frac) + samples_f[hi] * frac
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


def resample_8k_to_16k(pcm_8k: bytes) -> bytes:
    """Asterisk 8kHz slin → 16kHz for STT/VAD."""
    return _resample(pcm_8k, TELEPHONY_RATE, STT_RATE)


def resample_tts_to_8k(pcm_tts: bytes, tts_rate: int = TTS_RATE) -> bytes:
    """TTS output (24kHz default) → 8kHz slin for Asterisk."""
    return _resample(pcm_tts, tts_rate, TELEPHONY_RATE)


def resample_16k_to_8k(pcm_16k: bytes) -> bytes:
    """16kHz → 8kHz for Asterisk playback."""
    return _resample(pcm_16k, STT_RATE, TELEPHONY_RATE)
