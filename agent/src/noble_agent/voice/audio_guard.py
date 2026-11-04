"""Audio guard mechanisms — ported from aural-oss server/openai-voice-relay.

STATUS: EchoCooldown + WhisperHallucinationFilter → INTEGRATED (session.py).
        ConsecutiveFramesGate + RepetitionDetector → chưa tích hợp (dự phòng).

Four mechanisms:
  1. EchoCooldown          — block STT triggers while TTS is playing + cooldown window
  2. ConsecutiveFramesGate — require N consecutive loud frames before treating as real speech
  3. WhisperHallucinationFilter — drop known Whisper hallucination transcripts
  4. RepetitionDetector    — detect agent repeating the same response

Reference: aural-oss/server/openai-voice-relay-helpers.ts
"""

from __future__ import annotations

import logging
import math
import re
import struct
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. EchoCooldown
# ---------------------------------------------------------------------------

# Minimum TTS playback before barge-in is allowed (ms and bytes at 16kHz 16-bit)
_MIN_TTS_MS = 400
_MIN_TTS_BYTES = 32_000  # ~1 second at 16kHz 16-bit mono

# How long (seconds) to block STT after TTS finishes (agent echo window)
_ECHO_COOLDOWN_SEC = 0.6


class EchoCooldown:
    """Tracks TTS playback state and blocks STT during echo window.

    Usage (future):
        guard = EchoCooldown()
        guard.on_tts_start()               # called when first TTS chunk is sent
        guard.on_tts_chunk(len(pcm_bytes)) # called for each TTS audio chunk
        guard.on_tts_done()                # called when TTS stream ends

        # In STT on_final callback — gate before triggering agent:
        if not guard.allow_stt():
            return  # block — agent still playing or in echo cooldown

    Not thread-safe; designed for single asyncio event loop.
    """

    def __init__(
        self,
        min_tts_ms: int = _MIN_TTS_MS,
        min_tts_bytes: int = _MIN_TTS_BYTES,
        cooldown_sec: float = _ECHO_COOLDOWN_SEC,
    ):
        self._min_tts_ms = min_tts_ms
        self._min_tts_bytes = min_tts_bytes
        self._cooldown_sec = cooldown_sec

        self._tts_playing: bool = False
        self._tts_start_t: float = 0.0
        self._tts_bytes_sent: int = 0
        self._cooldown_until: float = 0.0  # monotonic timestamp

    def on_tts_start(self) -> None:
        self._tts_playing = True
        self._tts_start_t = time.monotonic()
        self._tts_bytes_sent = 0
        logger.debug("[EchoCooldown] TTS started")

    def on_tts_chunk(self, byte_count: int) -> None:
        self._tts_bytes_sent += byte_count

    def on_tts_done(self) -> None:
        self._tts_playing = False
        self._cooldown_until = time.monotonic() + self._cooldown_sec
        logger.debug("[EchoCooldown] TTS done — echo cooldown until +%.2fs", self._cooldown_sec)

    def allow_stt(self) -> bool:
        """Return True if STT final should be passed to the agent."""
        now = time.monotonic()

        if self._tts_playing:
            elapsed_ms = (now - self._tts_start_t) * 1000
            if elapsed_ms < self._min_tts_ms or self._tts_bytes_sent < self._min_tts_bytes:
                logger.debug(
                    "[EchoCooldown] Blocked — TTS playing (%.0fms / %d bytes)",
                    elapsed_ms,
                    self._tts_bytes_sent,
                )
                return False

        if now < self._cooldown_until:
            remaining = self._cooldown_until - now
            logger.debug("[EchoCooldown] Blocked — echo cooldown (%.2fs remaining)", remaining)
            return False

        return True

    @property
    def is_tts_playing(self) -> bool:
        return self._tts_playing


# ---------------------------------------------------------------------------
# 2. ConsecutiveFramesGate
# ---------------------------------------------------------------------------

# PCM frame parameters (16kHz, 16-bit, mono)
_SAMPLE_RATE = 16_000
_FRAME_MS = 20  # VAD-style 20ms frames
_BYTES_PER_FRAME = _SAMPLE_RATE * _FRAME_MS // 1000 * 2  # 640 bytes

# RMS thresholds (int16 scale 0–32768)
_MIN_SPEECH_RMS = 160  # minimum energy to count as a frame
_BARGE_IN_RMS = 2_400  # high-energy threshold to allow barge-in during TTS
_REQUIRED_CONSECUTIVE = 3  # frames in a row needed before treating as real speech


def _rms_int16(pcm_bytes: bytes) -> float:
    """Compute RMS of raw 16-bit little-endian mono PCM bytes."""
    if len(pcm_bytes) < 2:
        return 0.0
    n = len(pcm_bytes) // 2
    samples = struct.unpack_from(f"<{n}h", pcm_bytes[: n * 2])
    mean_sq = sum(s * s for s in samples) / n
    return math.sqrt(mean_sq)


class ConsecutiveFramesGate:
    """Requires N consecutive frames above RMS threshold to confirm real speech.

    Prevents short noise bursts (clicks, paper rustling) from triggering STT.

    Usage (future):
        gate = ConsecutiveFramesGate()
        for pcm_chunk in audio_stream:
            if gate.feed(pcm_chunk):
                # confirmed speech — pass to STT
                await stt.send(pcm_chunk)

    The gate resets on silence (below min_rms) and on explicit reset().
    """

    def __init__(
        self,
        min_rms: float = _MIN_SPEECH_RMS,
        barge_in_rms: float = _BARGE_IN_RMS,
        required_consecutive: int = _REQUIRED_CONSECUTIVE,
        frame_bytes: int = _BYTES_PER_FRAME,
    ):
        self._min_rms = min_rms
        self._barge_in_rms = barge_in_rms
        self._required = required_consecutive
        self._frame_bytes = frame_bytes

        self._consecutive: int = 0
        self._confirmed: bool = False
        self._buf: bytes = b""

    def feed(self, pcm_chunk: bytes) -> bool:
        """Process a PCM chunk. Returns True when speech is confirmed."""
        self._buf += pcm_chunk
        confirmed_this_call = False

        while len(self._buf) >= self._frame_bytes:
            frame = self._buf[: self._frame_bytes]
            self._buf = self._buf[self._frame_bytes :]
            rms = _rms_int16(frame)

            if rms >= self._min_rms:
                self._consecutive += 1
                if self._consecutive >= self._required:
                    if not self._confirmed:
                        logger.debug(
                            "[ConsecutiveFramesGate] Speech confirmed (rms=%.0f, frames=%d)",
                            rms,
                            self._consecutive,
                        )
                    self._confirmed = True
                    confirmed_this_call = True
            else:
                if self._consecutive > 0:
                    logger.debug("[ConsecutiveFramesGate] Reset (rms=%.0f below threshold)", rms)
                self._consecutive = 0
                self._confirmed = False

        return confirmed_this_call

    def is_high_energy(self, pcm_chunk: bytes) -> bool:
        """True if chunk exceeds barge-in threshold (used alongside EchoCooldown)."""
        return _rms_int16(pcm_chunk) >= self._barge_in_rms

    def reset(self) -> None:
        self._consecutive = 0
        self._confirmed = False
        self._buf = b""

    @property
    def confirmed(self) -> bool:
        return self._confirmed


# ---------------------------------------------------------------------------
# 3. WhisperHallucinationFilter
# ---------------------------------------------------------------------------

# Phrases Whisper commonly emits when there is silence or low-quality audio.
# Source: empirical observations from OpenAI Whisper community + aural-oss.
_HALLUCINATION_EXACT: frozenset[str] = frozenset(
    {
        ".",
        "Thank you.",
        "Thank you!",
        "Thanks.",
        "Thanks!",
        "Bye.",
        "Bye!",
        "Goodbye.",
        "Goodbye!",
        "You're welcome.",
        "OK.",
        "Okay.",
        "Hmm.",
        "Hm.",
        "Uh.",
        "Um.",
        "Mm-hmm.",
        "Yeah.",
        "Yes.",
        "No.",
        # Vietnamese common hallucinations
        "Vâng.",
        "Ừ.",
        "Ừm.",
        "Cảm ơn.",
        "Cảm ơn bạn.",
        "Tạm biệt.",
    }
)

# Regex patterns for repetitive filler hallucinations
_HALLUCINATION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*[\.\,\!\?]+\s*$"),  # punctuation only
    re.compile(r"^(\s*[Hh]m+\s*\.?\s*)+$"),  # Hm / Hmm / Hmmm
    re.compile(r"^(\s*[Uu]h+\s*\.?\s*)+$"),  # Uh / Uhh
    re.compile(r"^(\s*[Uu]m+\s*\.?\s*)+$"),  # Um / Umm
    re.compile(r"^[\s\W]+$"),  # whitespace/symbols only
    re.compile(r"^\[.*\]$"),  # [BLANK_AUDIO] etc.
    re.compile(r"^\(.*\)$"),  # (silence) etc.
]


class WhisperHallucinationFilter:
    """Drops transcript strings that are known Whisper hallucinations.

    Usage (future):
        filt = WhisperHallucinationFilter()
        async def on_final(text: str):
            if filt.is_hallucination(text):
                return  # drop silently
            await handle_real_transcript(text)

    Works for any STT backend, not just Whisper — the phrases are generic enough.
    """

    def __init__(self, extra_phrases: list[str] | None = None):
        self._exact = set(_HALLUCINATION_EXACT)
        if extra_phrases:
            self._exact.update(p.strip() for p in extra_phrases)

    def is_hallucination(self, text: str) -> bool:
        stripped = text.strip()

        if not stripped:
            return True

        if stripped in self._exact:
            logger.debug("[HallucinationFilter] Exact match dropped: %r", stripped)
            return True

        for pat in _HALLUCINATION_PATTERNS:
            if pat.match(stripped):
                logger.debug("[HallucinationFilter] Pattern match dropped: %r", stripped)
                return True

        # Very short transcript (1-2 chars) from non-empty audio is usually noise
        if len(stripped) <= 2 and not stripped.isalnum():
            logger.debug("[HallucinationFilter] Too-short non-alnum dropped: %r", stripped)
            return True

        return False

    def add_phrase(self, phrase: str) -> None:
        """Register an additional hallucination phrase at runtime."""
        self._exact.add(phrase.strip())


# ---------------------------------------------------------------------------
# 4. RepetitionDetector
# ---------------------------------------------------------------------------

_REPETITION_SIMILARITY_THRESHOLD = 0.85  # Jaccard similarity above this = repetition
_REPETITION_WINDOW = 5  # number of recent responses to check against


def _jaccard_similarity(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


class RepetitionDetector:
    """Detects if a new agent response is too similar to a recent one.

    Prevents the agent from looping on the same answer when the conversation
    stalls (e.g. user keeps asking the same thing, or LLM gets stuck in a loop).

    Usage (future):
        detector = RepetitionDetector()
        # In VoiceAgent after LLM generates response text:
        if detector.is_repetition(response_text):
            logger.warning("Repetition detected — suppressing or regenerating")
            return  # or trigger a fallback response
        detector.record(response_text)

    State is per-session; reset() clears history on new conversation.
    """

    def __init__(
        self,
        threshold: float = _REPETITION_SIMILARITY_THRESHOLD,
        window: int = _REPETITION_WINDOW,
    ):
        self._threshold = threshold
        self._window = window
        self._history: list[str] = []

    def is_repetition(self, text: str) -> bool:
        """True if text is too similar to any response in the recent window."""
        if not text.strip():
            return False
        for prev in self._history[-self._window :]:
            sim = _jaccard_similarity(text, prev)
            if sim >= self._threshold:
                logger.warning("[RepetitionDetector] Repetition detected (similarity=%.2f): %r", sim, text[:80])
                return True
        return False

    def record(self, text: str) -> None:
        """Add a response to history after it has been confirmed as non-repetitive."""
        if text.strip():
            self._history.append(text)
            if len(self._history) > self._window * 2:
                self._history = self._history[-self._window :]

    def reset(self) -> None:
        self._history.clear()
        logger.debug("[RepetitionDetector] History cleared")

    @property
    def history_size(self) -> int:
        return len(self._history)
