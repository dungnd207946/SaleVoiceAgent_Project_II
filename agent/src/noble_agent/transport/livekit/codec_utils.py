"""μ-law ↔ linear PCM16 codec helpers for telephony (8 kHz mono).

FreePBX/LiveKit SIP delivers PSTN audio as G.711 μ-law (PCMU). The voice
pipeline (VAD, STT, TTS) works in linear PCM16. This module is the thin
conversion boundary.

Python 3.13 removed the stdlib `audioop` module; we use the `audioop-lts`
community backport which provides a drop-in `audioop` package.
"""

from __future__ import annotations

import audioop  # audioop-lts on Python 3.13+

# G.711 is defined for mono, 8 bits per ulaw sample, 16 bits per pcm16 sample.
PCM16_SAMPLE_WIDTH = 2
ULAW_SAMPLE_WIDTH = 1


def ulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    """Decode G.711 μ-law audio to linear PCM16.

    Args:
        ulaw_bytes: Raw μ-law samples, 1 byte per sample.

    Returns:
        Linear PCM16 samples, 2 bytes per sample, little-endian. Output is
        always 2× the input length. Empty input returns empty output.
    """
    if not ulaw_bytes:
        return b""
    return audioop.ulaw2lin(ulaw_bytes, PCM16_SAMPLE_WIDTH)


def pcm16_to_ulaw(pcm16_bytes: bytes) -> bytes:
    """Encode linear PCM16 audio to G.711 μ-law.

    Args:
        pcm16_bytes: Linear PCM16 samples, 2 bytes per sample, little-endian.
            Must have even length.

    Returns:
        μ-law samples, 1 byte per sample. Output length is input length // 2.
        Empty input returns empty output.

    Raises:
        ValueError: if input length is odd (incomplete PCM16 sample).
    """
    if not pcm16_bytes:
        return b""
    if len(pcm16_bytes) % PCM16_SAMPLE_WIDTH != 0:
        raise ValueError(f"pcm16 input length must be even, got {len(pcm16_bytes)} bytes")
    return audioop.lin2ulaw(pcm16_bytes, PCM16_SAMPLE_WIDTH)
