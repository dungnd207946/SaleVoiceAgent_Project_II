"""`AgentAudioIO` — LiveKit room-level audio I/O for a single caller.

Responsibilities:
- Subscribe to the caller's remote audio track and expose received PCM16
  frames as an async iterator (`input_stream`).
- Publish a local agent audio track backed by an `AudioSource` and provide a
  one-call sink (`output_sink`) for PCM16 chunks.
- Allow the pipeline to interrupt agent speech instantly via
  `clear_output_queue()` (LiveKit `AudioSource.clear_queue` under the hood).

This class is transport-specific (LiveKit only). The shared pipeline talks to
it through the small `(input_stream, output_sink)` interface that `BaseSession`
consumes in Phase 2.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import numpy as np
from livekit import rtc

logger = logging.getLogger(__name__)

# Telephony defaults (G.711 → PCM16 path).
DEFAULT_SAMPLE_RATE = 8000
DEFAULT_NUM_CHANNELS = 1
# 40 ms matches ~2 frames of FreePBX ulaw at 20 ms each and is the knob the
# plan (§3) recommends for fast interrupt.
DEFAULT_QUEUE_SIZE_MS = 40

# Unique sentinel flushed into the input queue when the caller track ends.
# `None` is used rather than a distinct object because the async iterator
# protocol already treats it as a natural end-of-stream marker.
_INPUT_EOS: bytes | None = None


@dataclass(frozen=True)
class AudioIOConfig:
    # `sample_rate` is the fallback applied to whichever direction doesn't
    # override. Telephony historically runs 8 kHz both ways; browser/LiveKit
    # callers need input≠output (e.g. 16 kHz for STT, 24 kHz for TTS) so
    # LiveKit does the necessary resampling on each side.
    sample_rate: int = DEFAULT_SAMPLE_RATE
    input_sample_rate: int | None = None
    output_sample_rate: int | None = None
    num_channels: int = DEFAULT_NUM_CHANNELS
    queue_size_ms: int = DEFAULT_QUEUE_SIZE_MS
    local_track_name: str = "agent-voice"

    @property
    def in_rate(self) -> int:
        return self.input_sample_rate or self.sample_rate

    @property
    def out_rate(self) -> int:
        return self.output_sample_rate or self.sample_rate


class AgentAudioIO:
    """Bidirectional PCM16 audio I/O backed by a LiveKit Room.

    Lifecycle: construct → `await start()` → iterate `input_stream` and call
    `output_sink()` concurrently → `await stop()`.

    Single-caller assumption: one remote audio track per room. If multiple
    remote tracks exist, the first-supplied track wins.
    """

    def __init__(
        self,
        room: rtc.Room,
        caller_track: rtc.RemoteAudioTrack | rtc.Track,
        config: AudioIOConfig | None = None,
    ) -> None:
        self._room = room
        self._caller_track = caller_track
        self._config = config or AudioIOConfig()

        self._audio_source = rtc.AudioSource(
            sample_rate=self._config.out_rate,
            num_channels=self._config.num_channels,
            queue_size_ms=self._config.queue_size_ms,
        )
        self._local_track = rtc.LocalAudioTrack.create_audio_track(self._config.local_track_name, self._audio_source)
        self._audio_stream = rtc.AudioStream(
            caller_track,
            sample_rate=self._config.in_rate,
            num_channels=self._config.num_channels,
        )
        self._input_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._input_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopped = False
        self._room_disconnect_evt = asyncio.Event()

        # Register room-level hooks once; they stay valid for the room's life.
        @room.on("track_unsubscribed")
        def _on_track_unsubscribed(
            track: rtc.Track,
            _pub,
            _participant,  # type: ignore[no-untyped-def]
        ) -> None:
            if track.sid == getattr(caller_track, "sid", None):
                logger.info("caller track unsubscribed — signaling input EOS")
                self._input_queue.put_nowait(_INPUT_EOS)

        @room.on("disconnected")
        def _on_disconnected(_reason) -> None:  # type: ignore[no-untyped-def]
            logger.info("room disconnected — signaling input EOS")
            self._input_queue.put_nowait(_INPUT_EOS)
            self._room_disconnect_evt.set()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("AgentAudioIO.start() called twice")
        self._started = True
        await self._room.local_participant.publish_track(self._local_track)
        self._input_task = asyncio.create_task(self._read_input_stream(), name="agent-audio-input")

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True

        # Cancel the input pump first so it can't push after we close the stream.
        if self._input_task and not self._input_task.done():
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass

        # Always push EOS to unblock any awaiting input_stream consumer.
        self._input_queue.put_nowait(_INPUT_EOS)

        # Close the audio stream before the source so in-flight callbacks wind down.
        try:
            await self._audio_stream.aclose()
        except Exception:  # noqa: BLE001
            logger.exception("audio_stream.aclose() failed")

        # Unpublish the local track if the room is still around.
        try:
            sid = self._local_track.sid
            if sid:
                await self._room.local_participant.unpublish_track(sid)
        except Exception:  # noqa: BLE001
            logger.exception("unpublish_track failed")

        try:
            await self._audio_source.aclose()
        except Exception:  # noqa: BLE001
            logger.exception("audio_source.aclose() failed")

    # ------------------------------------------------------------------
    # input (caller → agent)
    # ------------------------------------------------------------------

    async def _read_input_stream(self) -> None:
        """Drain the remote track into the internal queue as raw PCM16 bytes."""
        try:
            async for event in self._audio_stream:
                frame_bytes = bytes(event.frame.data)
                if frame_bytes:
                    await self._input_queue.put(frame_bytes)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("audio_stream iteration failed")
        finally:
            await self._input_queue.put(_INPUT_EOS)

    async def input_stream(self) -> AsyncIterator[bytes]:
        """Async iterator yielding PCM16 little-endian frames from the caller.

        Ends cleanly on track unsubscribe, room disconnect, or `stop()`. Does
        NOT raise on natural termination — consumers should treat end-of-iterator
        as "caller hung up."
        """
        while True:
            chunk = await self._input_queue.get()
            if chunk is _INPUT_EOS:
                return
            yield chunk

    # ------------------------------------------------------------------
    # output (agent → caller)
    # ------------------------------------------------------------------

    async def send(self, pcm16_chunk: bytes) -> None:
        """`AudioOutput` protocol: push a PCM16 chunk into the outbound track.

        The chunk must be a whole number of samples (even length). Internally
        chunks are re-wrapped as `rtc.AudioFrame` for LiveKit. Blocks briefly
        if the SDK queue is full — that's the backpressure the caller should
        see.
        """
        if not pcm16_chunk:
            return
        if len(pcm16_chunk) % 2 != 0:
            raise ValueError(f"pcm16 chunk length must be even, got {len(pcm16_chunk)} bytes")

        # Lifecycle guards — bail before capture_frame so we don't spam the
        # log with "InvalidState" from the FFI layer when the source has been
        # closed or the room has disconnected.
        if self._stopped or self._room_disconnect_evt.is_set():
            return
        ffi = getattr(self._audio_source, "_ffi_handle", None)
        if ffi is not None and getattr(ffi, "disposed", False):
            return

        samples = np.frombuffer(pcm16_chunk, dtype=np.int16)
        frame = rtc.AudioFrame(
            data=samples.tobytes(),
            sample_rate=self._config.out_rate,
            num_channels=self._config.num_channels,
            samples_per_channel=len(samples) // self._config.num_channels,
        )
        try:
            await self._audio_source.capture_frame(frame)
        except Exception as e:  # noqa: BLE001
            # Under/over-run or source-in-transition (e.g. racing with
            # clear_queue on interrupt). Downgrade the repeated
            # "InvalidState" case to debug so it doesn't drown the log;
            # anything else keeps the full traceback.
            msg = str(e)
            if "InvalidState" in msg and (self._stopped or self._room_disconnect_evt.is_set()):
                logger.debug("capture_frame dropped (source closing): %s", msg)
            elif "InvalidState" in msg:
                logger.warning("capture_frame InvalidState: %s", msg)
            else:
                logger.exception("capture_frame failed (sample under/over-run?)")

    # Compat alias kept for the Phase 1 integration test and any
    # external caller that built against the original name.
    output_sink = send

    def clear(self) -> None:
        """`AudioOutput` protocol: drop any buffered agent audio for fast interrupt (plan §3)."""
        self._audio_source.clear_queue()

    # Compat alias.
    clear_output_queue = clear

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    @property
    def queued_duration_s(self) -> float:
        """`AudioOutput` protocol: seconds of audio currently queued for playout."""
        return float(self._audio_source.queued_duration)

    @property
    def queued_output_duration_s(self) -> float:
        """Phase 1 name — kept as an alias to avoid breaking existing callers."""
        return self.queued_duration_s

    @property
    def disconnected(self) -> bool:
        return self._room_disconnect_evt.is_set()
