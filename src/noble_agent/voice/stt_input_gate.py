"""Selectable input gate between caller audio and STT.

Modes: "off" (passthrough), "rms" (energy gate via ConsecutiveFramesGate),
"vad" (Silero is_speech + hangover). A pre-roll deque recovers the lead-in
clipped while the gate was inactive: on the rising edge (inactive -> active)
the withheld chunks are emitted before the current chunk so the recognizer
sees the start of the utterance.
"""

from __future__ import annotations

from collections import deque

from noble_agent.voice.audio_guard import ConsecutiveFramesGate


class SttInputGate:
    def __init__(
        self,
        *,
        mode: str = "off",
        preroll_chunks: int = 3,
        min_rms: float = 160.0,
        required_consecutive: int = 3,
        barge_in_rms: float = 2400.0,
        vad_hangover_chunks: int = 0,
        keepalive_max_bytes: int = 0,
    ) -> None:
        self.mode = mode
        self._preroll: deque[bytes] = deque(maxlen=max(0, int(preroll_chunks)))
        self._was_active = False
        self._frames_gate = (
            ConsecutiveFramesGate(
                min_rms=min_rms,
                barge_in_rms=barge_in_rms,
                required_consecutive=required_consecutive,
            )
            if mode == "rms"
            else None
        )
        self._vad_hangover_chunks = max(0, int(vad_hangover_chunks))
        self._vad_hangover_left = 0
        self._vad_active = False
        # Keepalive: feed synthetic silence to STT while the gate is closed and
        # an utterance is still pending, so the recognizer's trailing-silence
        # endpoint can fire. 0 → disabled.
        self.keepalive_max_bytes = max(0, int(keepalive_max_bytes))
        self._pending = False
        self._keepalive_bytes = 0

    def feed_vad(self, is_speech: bool) -> None:
        """Update the vad-gate flag from one Silero is_speech decision."""
        if is_speech:
            self._vad_active = True
            self._vad_hangover_left = self._vad_hangover_chunks
        elif self._vad_hangover_left > 0:
            self._vad_hangover_left -= 1
        else:
            self._vad_active = False

    def _active(self, data: bytes) -> bool:
        if self.mode == "rms" and self._frames_gate is not None:
            self._frames_gate.feed(data)
            return self._frames_gate.confirmed
        if self.mode == "vad":
            return self._vad_active
        return True  # "off" or unknown → fail open

    def gate(self, data: bytes) -> list[bytes]:
        """Return the chunks to forward to STT for this incoming chunk."""
        active = self._active(data)
        out: list[bytes] = []
        if active:
            if not self._was_active:  # rising edge → flush withheld lead-in
                out.extend(self._preroll)
                self._preroll.clear()
            out.append(data)
            if self.mode != "off":
                self._pending = True  # real audio forwarded → an utterance is in progress
                self._keepalive_bytes = 0
        elif self._preroll.maxlen:
            self._preroll.append(data)
        self._was_active = active
        return out

    def keepalive(self, frame_len: int) -> bytes | None:
        """Silence to feed STT while the gate is closed, so the recognizer's
        endpoint fires on a pending utterance. Returns a zero-filled frame while
        pending and under the cap, else None."""
        if not self._pending or self._keepalive_bytes >= self.keepalive_max_bytes:
            return None
        self._keepalive_bytes += frame_len
        return bytes(frame_len)

    def notify_final(self) -> None:
        """Called when STT emits a final — the utterance ended, stop keepalive."""
        self._pending = False
        self._keepalive_bytes = 0

    @classmethod
    def from_settings(cls, settings) -> SttInputGate:
        import math

        hangover = math.ceil(settings.stt_vad_gate_hangover_ms / max(1, settings.vad_chunk_ms))
        return cls(
            mode=settings.stt_input_gate_mode,
            preroll_chunks=settings.audio_gate_preroll_chunks,
            min_rms=settings.audio_gate_min_rms,
            required_consecutive=settings.audio_gate_required_consecutive,
            barge_in_rms=settings.audio_gate_barge_in_rms,
            vad_hangover_chunks=hangover,
            keepalive_max_bytes=int(settings.stt_gate_keepalive_max_sec * settings.stt_sample_rate * 2),
        )
