"""aiortc/WebSocket transport for a voice-agent session.

Thin subclass over `BaseSession` that owns only the transport layer:
- WebSocket connection (for signaling + SDP + JSON events).
- aiortc `RTCPeerConnection` and the outbound `ServerAudioTrack`.
- Push→pull bridge: legacy `handle_audio(bytes)` pushes into an internal
  queue that `BaseSession.start_pipeline()` pulls from.

Pipeline logic (VAD, STT, VoiceAgent, interrupt, idle, gender, guards) lives
in `BaseSession`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import websockets.asyncio.server
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from noble_agent.config import settings
from noble_agent.server.base_session import AudioOutput, BaseSession
from noble_agent.voice.audio import ServerAudioTrack, consume_incoming_track

logger = logging.getLogger("server")


def _ice_config() -> RTCConfiguration:
    servers: list[RTCIceServer] = []
    if settings.rtc_stun_url:
        servers.append(RTCIceServer(urls=[settings.rtc_stun_url]))
    if settings.rtc_turn_url:
        servers.append(
            RTCIceServer(
                urls=[settings.rtc_turn_url],
                username=settings.rtc_turn_username,
                credential=settings.rtc_turn_credential,
            )
        )
    return RTCConfiguration(iceServers=servers)


class _ServerAudioTrackOutput:
    """`AudioOutput` adapter over the legacy `ServerAudioTrack`.

    The track's internal queue is used to estimate queued playback duration
    for the idle-timer math in `BaseSession._run_agent` — this preserves the
    exact behavior that used to live inline as `len(audio_track._queue) *
    settings.audio_chunk_ms`.
    """

    def __init__(self, track: ServerAudioTrack) -> None:
        self._track = track

    async def send(self, pcm16_bytes: bytes) -> None:
        self._track.push_audio(pcm16_bytes)

    def clear(self) -> None:
        self._track.clear()

    @property
    def queued_duration_s(self) -> float:
        return (len(self._track._queue) * settings.audio_chunk_ms) / 1000


class Session(BaseSession):
    def __init__(
        self,
        ws: websockets.asyncio.server.ServerConnection,
        session_id: str,
    ) -> None:
        super().__init__(session_id)
        self.ws = ws
        self.audio_track = ServerAudioTrack()
        self.pc = RTCPeerConnection(configuration=_ice_config())
        self.pc.addTrack(self.audio_track)
        self.rtc_connected = asyncio.Event()

        self._track_tasks: list[asyncio.Task] = []
        self._incoming_audio: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._pipeline_task: asyncio.Task | None = None

        @self.pc.on("track")
        def on_track(track) -> None:  # type: ignore[no-untyped-def]
            if track.kind == "audio":
                task = asyncio.ensure_future(consume_incoming_track(track, self))
                self._track_tasks.append(task)

        @self.pc.on("connectionstatechange")
        async def on_state_change() -> None:
            state = self.pc.connectionState
            logger.info("RTC connection state: %s (session=%s)", state, session_id)
            if state == "connected":
                self.rtc_connected.set()

    # ------------------------------------------------------------------
    # Lifecycle overrides
    # ------------------------------------------------------------------

    async def start(self) -> None:
        await super().start()
        # Pipeline runs in the background once shared init completes.
        self._pipeline_task = asyncio.create_task(
            self.start_pipeline(
                self._drain_incoming_audio(),
                _ServerAudioTrackOutput(self.audio_track),
                event_sink=self._send_ws_event,
            ),
            name=f"session-{self.session_id}-pipeline",
        )

    async def stop(self) -> None:
        # Unblock the queue drainer so the pipeline task can exit cleanly.
        try:
            self._incoming_audio.put_nowait(None)
        except asyncio.QueueFull:  # queue is unbounded today; defensive only.
            pass

        await super().stop()

        for t in self._track_tasks:
            t.cancel()

        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            try:
                await self._pipeline_task
            except (asyncio.CancelledError, Exception):
                pass

        try:
            await self.pc.close()
        except Exception:  # noqa: BLE001
            logger.exception("pc.close() failed")

    # Idle state machine's final disconnect step — aiortc also closes the WS.
    async def _on_idle_disconnect(self) -> None:
        await self.stop()
        try:
            await self.ws.close(1000, "idle timeout")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Transport-specific entry points
    # ------------------------------------------------------------------

    async def negotiate(self, offer_sdp: str, offer_type: str) -> dict:
        offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
        await self.pc.setRemoteDescription(offer)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        logger.info("RTC SDP negotiation complete for session=%s", self.session_id)
        return {
            "type": "rtc_answer",
            "sdp": self.pc.localDescription.sdp,
            "answer_type": self.pc.localDescription.type,
            "session_id": self.session_id,
        }

    async def handle_audio(self, data: bytes) -> None:
        """Legacy push API used by `consume_incoming_track`.

        Preserved to keep the aiortc audio-ingress wiring unchanged. Pushes
        the frame into the internal queue; `_drain_incoming_audio` hands it
        to `BaseSession.process_audio_frame()`.
        """
        if self._stopping:
            return
        await self._incoming_audio.put(data)

    # ------------------------------------------------------------------
    # Internal plumbing
    # ------------------------------------------------------------------

    async def _drain_incoming_audio(self) -> AsyncIterator[bytes]:
        while True:
            data = await self._incoming_audio.get()
            if data is None:
                return
            yield data

    async def _send_ws_event(self, msg: dict) -> None:
        try:
            await self.ws.send(json.dumps(msg))
        except Exception:  # noqa: BLE001 - best-effort, WS may be gone
            pass


# Preserve the public `audio_output: AudioOutput` protocol export for callers
# that want to adapt a different track.
__all__ = ["AudioOutput", "Session"]
