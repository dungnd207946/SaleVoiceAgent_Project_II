"""WebRTC audio transport — replaces WebSocket binary audio.

ServerAudioTrack: TTS PCM 24kHz → resample 48kHz → Opus frames → client speaker.
consume_incoming_track: client mic Opus → decode 48kHz → resample 16kHz → STT/VAD.

Self-pacing via asyncio.sleep ensures real-time delivery (no queue accumulation).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from fractions import Fraction

import numpy as np
from aiortc import MediaStreamTrack
from av import AudioFrame, AudioResampler

logger = logging.getLogger("rtc_audio")

# ── Constants ─────────────────────────────────────────────────────────────────
RTC_SAMPLE_RATE = 48000  # WebRTC Opus native rate
RTC_FRAME_DURATION = 0.020  # 20ms per frame
RTC_FRAME_SAMPLES = int(RTC_SAMPLE_RATE * RTC_FRAME_DURATION)  # 960 samples
PTIME = 20  # ms per frame (for av.AudioFrame)

TTS_SAMPLE_RATE = 24000  # VieNeu TTS output rate
STT_SAMPLE_RATE = 16000  # sherpa-onnx input rate


# ── Resampling ────────────────────────────────────────────────────────────────


def resample_linear(pcm_bytes: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample PCM int16 mono via numpy linear interpolation.

    Same algorithm as the AudioWorklet processors being removed.
    """
    if src_rate == dst_rate:
        return pcm_bytes

    samples_in = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    if len(samples_in) == 0:
        return b""

    ratio = dst_rate / src_rate
    out_len = int(len(samples_in) * ratio)
    if out_len == 0:
        return b""

    indices = np.arange(out_len) / ratio
    lo = np.floor(indices).astype(np.int64)
    lo = np.clip(lo, 0, len(samples_in) - 1)
    hi = np.clip(lo + 1, 0, len(samples_in) - 1)
    frac = (indices - lo).astype(np.float32)

    resampled = samples_in[lo] * (1 - frac) + samples_in[hi] * frac
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    return resampled.tobytes()


# ── ServerAudioTrack ──────────────────────────────────────────────────────────


class ServerAudioTrack(MediaStreamTrack):
    """MediaStreamTrack that serves TTS audio to the browser via WebRTC.

    push_audio() accepts PCM int16 @ 24kHz from TTS, resamples to 48kHz,
    chunks into 20ms frames, and queues them. recv() returns frames at
    real-time pace (~50Hz), outputting silence when the queue is empty.
    """

    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue: deque[AudioFrame] = deque()
        self._pts = 0  # presentation timestamp counter

    def push_audio(self, pcm_24khz: bytes) -> None:
        """Accept TTS output (PCM int16, 24kHz mono), resample and enqueue."""
        pcm_48k = resample_linear(pcm_24khz, TTS_SAMPLE_RATE, RTC_SAMPLE_RATE)
        if not pcm_48k:
            return

        samples = np.frombuffer(pcm_48k, dtype=np.int16)

        # Chunk into 20ms frames (960 samples @ 48kHz)
        offset = 0
        while offset + RTC_FRAME_SAMPLES <= len(samples):
            chunk = samples[offset : offset + RTC_FRAME_SAMPLES]
            frame = AudioFrame(format="s16", layout="mono", samples=RTC_FRAME_SAMPLES)
            frame.sample_rate = RTC_SAMPLE_RATE
            frame.pts = self._pts
            frame.time_base = Fraction(1, RTC_SAMPLE_RATE)
            # Copy PCM data into the frame
            frame.planes[0].update(chunk.tobytes())
            self._pts += RTC_FRAME_SAMPLES
            self._queue.append(frame)
            offset += RTC_FRAME_SAMPLES

        # Handle remaining samples (pad with zeros to fill a full frame)
        if offset < len(samples):
            remainder = samples[offset:]
            padded = np.zeros(RTC_FRAME_SAMPLES, dtype=np.int16)
            padded[: len(remainder)] = remainder
            frame = AudioFrame(format="s16", layout="mono", samples=RTC_FRAME_SAMPLES)
            frame.sample_rate = RTC_SAMPLE_RATE
            frame.pts = self._pts
            frame.time_base = Fraction(1, RTC_SAMPLE_RATE)
            frame.planes[0].update(padded.tobytes())
            self._pts += RTC_FRAME_SAMPLES
            self._queue.append(frame)

    def clear(self) -> None:
        """Drain outbound queue on interrupt."""
        self._queue.clear()

    async def recv(self) -> AudioFrame:
        """Return next 20ms frame, or silence. Self-paces at ~50Hz."""
        # Pace at slightly under 20ms to avoid underruns
        await asyncio.sleep(0.018)

        if self._queue:
            return self._queue.popleft()

        # Silence frame
        frame = AudioFrame(format="s16", layout="mono", samples=RTC_FRAME_SAMPLES)
        frame.sample_rate = RTC_SAMPLE_RATE
        frame.pts = self._pts
        frame.time_base = Fraction(1, RTC_SAMPLE_RATE)
        frame.planes[0].update(b"\x00" * RTC_FRAME_SAMPLES * 2)
        self._pts += RTC_FRAME_SAMPLES
        return frame


# ── Incoming track consumer ───────────────────────────────────────────────────


async def consume_incoming_track(track: MediaStreamTrack, session) -> None:
    """Read audio frames from browser mic track, resample 48k→16k, feed to session.

    Runs as a long-lived task for the duration of the RTC connection.
    Uses AudioResampler to normalize any incoming format (fltp/s16, mono/stereo)
    to s16 mono before feeding to STT/VAD.
    """
    logger.info("Started consuming incoming audio track")
    resampler: AudioResampler | None = None
    try:
        while True:
            frame = await track.recv()

            # Lazily create resampler on first frame so we know the actual sample_rate.
            # Normalises format (fltp/s16/s16p) and layout (mono/stereo) → s16 mono.
            if resampler is None:
                resampler = AudioResampler(
                    format="s16",
                    layout="mono",
                    rate=frame.sample_rate,
                )
                logger.info(
                    "Incoming audio: format=%s layout=%s rate=%d",
                    frame.format.name,
                    frame.layout.name,
                    frame.sample_rate,
                )

            out_frames = resampler.resample(frame)
            raw = b"".join(bytes(f.planes[0]) for f in out_frames)
            if not raw:
                continue

            # Resample from WebRTC rate (48kHz) to 16kHz for STT/VAD
            pcm_16k = resample_linear(raw, frame.sample_rate, STT_SAMPLE_RATE)
            if pcm_16k:
                await session.handle_audio(pcm_16k)
    except Exception as e:
        if "MediaStreamError" in type(e).__name__:
            logger.info("Incoming track ended normally.")
        else:
            logger.warning("Incoming track error: %s", e, exc_info=True)
