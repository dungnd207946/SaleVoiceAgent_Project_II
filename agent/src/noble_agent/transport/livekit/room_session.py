"""LiveKit `RoomSession` — Phase 3 of LIVEKIT_MIGRATION.md.

Thin transport-specific subclass of `BaseSession`:
- Owns a LiveKit `rtc.Room`.
- Waits for the caller's audio track, wraps it in `AgentAudioIO`.
- Hands the caller-audio iterator and `AgentAudioIO` (which implements the
  `AudioOutput` protocol) to `BaseSession.start_pipeline()`.
- Exposes `wait_until_end()` for the worker `entrypoint` to block on.

Per plan §8.3. Keeps hotline conventions: one caller per room, the first
audio track wins, disconnect ends the session.
"""

from __future__ import annotations

import asyncio
import json
import logging

from livekit import rtc

from noble_agent.server.base_session import BaseSession
from noble_agent.transport.livekit.agent_audio_io import AgentAudioIO, AudioIOConfig

logger = logging.getLogger("server")

# Mirror Phase 1 AudioIO defaults — telephony is 8 kHz mono PCM16.
#
# Caller-mic publish timeout: SIP callers publish immediately (≈1s) but
# browser callers via Meet start muted and need the user to click the
# microphone button — give them headroom so the session doesn't abort
# before they hit the button.
TRACK_SUBSCRIBE_TIMEOUT_S = 60.0

# LiveKit data-channel topic the browser tester (static/livekit.html) listens on
# for the live STT/TTS/tool log. Telephony/SIP callers ignore data messages.
EVENT_TOPIC = "agent-events"


class RoomSession(BaseSession):
    """Per-call session: 1 LiveKit room ↔ 1 caller ↔ 1 agent."""

    def __init__(
        self,
        room: rtc.Room,
        session_id: str,
        caller_identity: str,
        audio_config: AudioIOConfig | None = None,
    ) -> None:
        super().__init__(session_id=session_id)
        self.room = room
        self.caller_identity = caller_identity
        self._audio_config = audio_config or AudioIOConfig()

        self._audio_io: AgentAudioIO | None = None
        self._pipeline_task: asyncio.Task[None] | None = None
        self._greet_task: asyncio.Task[None] | None = None
        self._disconnect_event = asyncio.Event()
        # Strong refs for fire-and-forget data-channel publishes (asyncio only
        # keeps weakrefs to tasks). Best-effort telemetry — see _publish_event.
        self._event_tasks: set[asyncio.Task] = set()
        self._event_published_once = False

        # Caller left → end the session. Matches plan §8.3 reference.
        @room.on("participant_disconnected")
        def _on_participant_left(participant: rtc.RemoteParticipant) -> None:
            if participant.identity == caller_identity:
                logger.info("caller %s disconnected — closing session %s", caller_identity, session_id)
                self._disconnect_event.set()

        @room.on("disconnected")
        def _on_room_disconnected(_reason) -> None:  # type: ignore[no-untyped-def]
            logger.info("room disconnected — closing session %s", session_id)
            self._disconnect_event.set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Run shared init, subscribe caller audio, then kick off the pipeline."""
        await super().start()

        caller = self._get_caller_participant()
        if caller is None:
            raise RuntimeError(f"caller {self.caller_identity!r} not found in room {self.room.name!r}")
        track = await self._wait_for_caller_audio_track(caller)

        self._audio_io = AgentAudioIO(self.room, track, self._audio_config)
        await self._audio_io.start()

        # Install the audio_output hook synchronously so that a stop()
        # racing against start() still finds an AudioOutput to clear.
        # `start_pipeline` will re-assign the same object; redundant but
        # safe.
        self._audio_output = self._audio_io

        # Route pipeline JSON events (transcript / agent_speaking / agent_done +
        # debug metrics / tool_start / …) to the LiveKit data channel so the
        # browser test UI can render them. Set it directly here — BEFORE the
        # greeting task below — so the greeting's first event isn't lost to the
        # default no-op sink (start_pipeline sets it too, but that task may be
        # scheduled after the greeting task).
        self._event_sink = self._send_livekit_event

        # The pipeline runs for the lifetime of the call.
        self._pipeline_task = asyncio.create_task(
            self.start_pipeline(
                self._audio_io.input_stream(),
                self._audio_io,
                event_sink=self._publish_event,
            ),
            name=f"room-{self.session_id}-pipeline",
        )

        # Auto-greet on connect — the caller just dialled in and expects
        # the agent to speak first. aiortc/WS + telephony/Asterisk paths
        # already do this (ws_handler.py / telephony/session.py); LiveKit
        # used to skip it, which left silent callers in silence and left
        # MetricsCollector with no records to aggregate.
        #
        # Run it through `_run_greeting` and register it as `_agent_task` so
        # the caller can barge in over the greeting: `_handle_interrupt` /
        # `_trigger_agent_for_text` both gate on `_agent_task`, and
        # `_run_greeting` arms the VAD (`set_speaking`). Without this the first
        # utterance was un-interruptible (later turns already worked).
        self._agent_task = asyncio.ensure_future(self._run_greeting())
        self._agent_task.set_name(f"room-{self.session_id}-greet")
        self._greet_task = self._agent_task  # named ref for stop() cleanup

    async def _send_livekit_event(self, msg: dict) -> None:
        """Publish a pipeline JSON event to the room data channel.

        The browser client listens on `RoomEvent.DataReceived` and renders
        transcripts + per-turn debug metrics. Best-effort: a publish failure
        (room tearing down, no subscribers) must not break the call.
        `ensure_ascii=False` keeps Vietnamese text compact on the wire.
        """
        try:
            payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
            await self.room.local_participant.publish_data(payload, reliable=True)
        except Exception:  # noqa: BLE001 - best-effort telemetry channel
            logger.debug("publish_data failed (room closing?)", exc_info=True)

    async def wait_until_end(self) -> None:
        """Block until caller disconnects or the room ends."""
        await self._disconnect_event.wait()

    # ------------------------------------------------------------------
    # Event sink → LiveKit data channel (browser live log)
    # ------------------------------------------------------------------

    async def _publish_event(self, msg: dict) -> None:
        """`event_sink` for the shared pipeline: forward a pipeline event
        (STT transcript, TTS `agent_speaking` + ttfb, tool_start/done, …) to the
        browser over the LiveKit data channel so `static/livekit.html` can show a
        detailed live log.

        Fire-and-forget: this runs inline in the TTS pacer right before the first
        audio frame (where any added latency would inflate TTFA), so we schedule
        the publish and return immediately instead of awaiting the round-trip.
        Best-effort — a failed publish is logged at debug and never disturbs the
        call. SIP/telephony callers simply have no data-channel listener.
        """
        task = asyncio.create_task(self._do_publish_event(msg))
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)

    async def _do_publish_event(self, msg: dict) -> None:
        try:
            payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
            await self.room.local_participant.publish_data(payload, reliable=True, topic=EVENT_TOPIC)
            if not self._event_published_once:
                self._event_published_once = True
                logger.info("data-channel events streaming to browser (topic=%s)", EVENT_TOPIC)
        except Exception:  # noqa: BLE001 — telemetry, must never affect the call
            logger.debug("publish_data event failed (type=%s)", msg.get("type"), exc_info=True)

    async def stop(self) -> None:
        """Best-effort teardown.

        Order matters: run shared `BaseSession.stop()` first so it can
        `audio_output.clear()` against a still-live AudioSource; then
        close the `AgentAudioIO` (unpublishes the local track + closes the
        source handle); pipeline task is cancelled last because
        `BaseSession.stop()` sets `_stopping=True` which lets the pipeline
        loop exit on its own.
        """
        await super().stop()

        if self._greet_task and not self._greet_task.done():
            self._greet_task.cancel()
            try:
                await self._greet_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            try:
                await self._pipeline_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        for task in list(self._event_tasks):
            task.cancel()
        self._event_tasks.clear()

        if self._audio_io is not None:
            try:
                await self._audio_io.stop()
            except Exception:  # noqa: BLE001
                logger.exception("audio_io.stop() failed")

    # Idle-state disconnect path (BaseSession._on_idle_timeout → _on_idle_disconnect).
    async def _on_idle_disconnect(self) -> None:
        await self.stop()
        self._disconnect_event.set()

    # ------------------------------------------------------------------
    # Room helpers
    # ------------------------------------------------------------------

    def _get_caller_participant(self) -> rtc.RemoteParticipant | None:
        """Fetch the caller; SDK 1.1.5 exposes `remote_participants` as a mapping
        keyed by identity."""
        participants = self.room.remote_participants
        # Dict-like interface in SDK 1.1.x.
        if hasattr(participants, "get"):
            return participants.get(self.caller_identity)
        # Fallback for future SDK shape changes — linear scan.
        for p in participants:  # type: ignore[attr-defined]
            if getattr(p, "identity", None) == self.caller_identity:
                return p
        return None

    async def _wait_for_caller_audio_track(
        self,
        caller: rtc.RemoteParticipant,
        timeout: float = TRACK_SUBSCRIBE_TIMEOUT_S,
    ) -> rtc.RemoteTrack:
        """Return the caller's first audio track, subscribing if necessary.

        If a track is already published and subscribed at call time, returns
        immediately. Otherwise waits for a `track_subscribed` event.
        """
        # Fast path: already subscribed.
        for pub in caller.track_publications.values():
            if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track is not None:
                return pub.track

        fut: asyncio.Future[rtc.RemoteTrack] = asyncio.get_event_loop().create_future()

        @self.room.on("track_subscribed")
        def _on_subscribed(
            track: rtc.RemoteTrack,
            _pub: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if not fut.done() and participant.identity == caller.identity and track.kind == rtc.TrackKind.KIND_AUDIO:
                fut.set_result(track)

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError as exc:
            raise RuntimeError(
                f"timed out after {timeout}s waiting for caller {caller.identity!r} audio track"
            ) from exc
