"""VAD — Silero VAD (pinned `silero-vad` wheel) + the barge-in state machine.

Only barge-in is decided here; utterance endpointing belongs to the STT
backend. States:

    IDLE ──set_speaking()──> SPEAKING ──N speech chunks──> INTERRUPTED
      ▲                         ▲                              │
      └──────── set_idle() ─────┴──────── set_speaking() ──────┘

INTERRUPTED deliberately latches: no audio chunk moves it anywhere, only
`set_speaking()` / `set_idle()` do — sessions re-arm explicitly (see the
comments in server/base_session.py and telephony/session.py).
"""

from __future__ import annotations

import copy
import functools
import logging
from enum import Enum

import numpy as np
import torch
from silero_vad import load_silero_vad

from noble_agent.config import settings

logger = logging.getLogger(__name__)

SAMPLE_RATE = settings.stt_sample_rate
CHUNK_SAMPLES = int(SAMPLE_RATE * settings.vad_chunk_ms / 1000)  # 512 @ 16kHz
INTERRUPT_CONFIRM_CHUNKS = settings.vad_interrupt_confirm_chunks  # consecutive chunks to confirm interrupt

_SILERO_WINDOW = {16000: 512, 8000: 256}  # Silero v5+ accepts exactly this many samples


def _check_chunk_window() -> None:
    """Fail loudly at load/construct time instead of inside every process_chunk."""
    need = _SILERO_WINDOW.get(SAMPLE_RATE)
    if need is None:
        raise ValueError(f"Silero VAD supports 8/16 kHz only; STT_SAMPLE_RATE={SAMPLE_RATE}")
    if need != CHUNK_SAMPLES:
        raise ValueError(
            f"Silero VAD needs VAD_CHUNK_MS={need * 1000 // SAMPLE_RATE} at {SAMPLE_RATE} Hz "
            f"({need} samples); got VAD_CHUNK_MS={settings.vad_chunk_ms} ({CHUNK_SAMPLES} samples)"
        )


@functools.lru_cache(maxsize=1)
def _load_shared_model():
    """Load the Silero JIT weights ONCE per process from the pinned wheel
    (no torch.hub, no network, ~0.3 s blocking).

    Never run inference on this instance — the JIT model carries LSTM state,
    so every `SileroVAD` deepcopies it (~2 ms) instead of reloading per
    session, which used to freeze the event loop for every live call whenever
    a new one connected.
    """
    _check_chunk_window()
    logger.info("Loading Silero VAD model...")
    model = load_silero_vad(onnx=False)
    model.eval()
    logger.info("Silero VAD ready.")
    return model


class VADState(Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"


class SileroVAD:
    """Silero speech probability per 32 ms chunk + the barge-in state machine."""

    def __init__(self):
        _check_chunk_window()
        # Own copy: per-instance LSTM state, no per-session model load.
        self._model = copy.deepcopy(_load_shared_model())
        self.state = VADState.IDLE
        self._interrupt_chunks = 0
        # Set by the session on its first emitted TTS chunk of a turn; cleared by
        # set_idle(). Only while True can echo exist, so only then does the
        # barge-in RMS floor apply (see _clears_rms_floor).
        self.playback_active = False
        self._floor_logged = False

    def process_chunk(self, pcm_bytes: bytes) -> dict:
        """
        Process a 32ms PCM int16 chunk.
        Returns {"speech_prob", "is_speech", "rms", "state", "state_changed"}
        """
        f32 = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(f32 * f32))) if f32.size else 0.0
        samples = f32 / 32768.0
        if len(samples) < CHUNK_SAMPLES:
            samples = np.pad(samples, (0, CHUNK_SAMPLES - len(samples)))
        tensor = torch.from_numpy(samples[:CHUNK_SAMPLES])
        with torch.no_grad():
            prob = self._model(tensor, SAMPLE_RATE).item()

        is_speech = prob >= settings.vad_threshold
        prev_state = self.state
        self._update_state(is_speech, rms)

        return {
            "speech_prob": prob,
            "is_speech": is_speech,
            "rms": rms,
            "state": self.state,
            "state_changed": self.state != prev_state,
        }

    def _update_state(self, is_speech: bool, rms: float):
        if self.state != VADState.SPEAKING:
            return  # IDLE: nothing to decide here; INTERRUPTED: latched until re-armed
        if is_speech and self._clears_rms_floor(rms):
            self._interrupt_chunks += 1
            if self._interrupt_chunks >= INTERRUPT_CONFIRM_CHUNKS:
                self.state = VADState.INTERRUPTED
                self._interrupt_chunks = 0
        else:
            self._interrupt_chunks = 0

    def _clears_rms_floor(self, rms: float) -> bool:
        """Barge-in while agent audio is really playing must also beat the RMS
        floor: quiet speech-like audio then is AEC echo residual, not the caller
        (settings.barge_in_rms_threshold; 0 = off). No floor before playback —
        no echo is possible while the LLM is still thinking."""
        if not self.playback_active:
            return True
        floor = settings.barge_in_rms_threshold
        if rms >= floor:
            return True
        if not self._floor_logged:  # once per turn — enough to tune, never spams
            self._floor_logged = True
            logger.info(
                "VAD: barge-in chunk rejected by RMS floor (rms=%.0f < %.0f) — "
                "lower BARGE_IN_RMS_THRESHOLD if real callers cannot interrupt",
                rms,
                floor,
            )
        return False

    def set_speaking(self):
        # Deliberately keeps playback_active: mid-turn re-arms (addressee /
        # speaker-floor paths) happen while audio is still playing.
        self.state = VADState.SPEAKING
        self._interrupt_chunks = 0

    def set_idle(self):
        self.state = VADState.IDLE
        self._interrupt_chunks = 0
        self.playback_active = False
        self._floor_logged = False
