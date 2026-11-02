"""Provider-facing ingress gateway (SaaS slice #2).

Single-domain WS entry (tenant no longer lives in the Host, only in the Bearer
credential, resolved via the Portal runtime-credentials API — see gateway/auth.py
+ gateway/credentials.py):
  /v1/voice   → authorize → bridge provider audio into the tenant's LiveKit room
  /v1/chat    → authorize → reverse-proxy WS to the tenant worker's /chat
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from urllib.parse import urlparse

logger = logging.getLogger("gateway")

# Bound on how long _handle waits for the post-authorize handshake frame
# (identity + call_id JSON) before giving up on an authed-but-silent client.
_HANDSHAKE_TIMEOUT_SEC = 10.0


def route(path: str) -> str | None:
    p = urlparse(path or "/").path
    if p == "/v1/voice":
        return "voice"
    if p == "/v1/chat":
        return "chat"
    return None


def parse_handshake(raw: str) -> dict:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


# Data-channel topics carrying worker UI events. Turn events are published with
# topic="agent-events" (transport/livekit/room_session.py::EVENT_TOPIC) but the
# greeting path publishes with NO topic (room_session._send_livekit_event) — accept
# both. Mirrored as a literal: room_session imports `livekit.rtc` at module level
# and the gateway keeps its livekit imports lazy.
_EVENT_TOPICS = ("", "agent-events")


def enqueue_event(queue, topic, data) -> bool:
    """Filter + enqueue one worker data packet for forwarding to the provider ws.

    Returns True if enqueued. Drops (returns False) foreign topics, undecodable
    payloads, and everything once the queue is full — UI events are best-effort
    and must never block or backlog the audio path.
    """
    import asyncio

    if (topic or "") not in _EVENT_TOPICS:
        return False
    try:
        text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)
    except UnicodeDecodeError:
        return False
    try:
        queue.put_nowait(text)
        return True
    except asyncio.QueueFull:
        return False


# Provider → room audio relay bound. Measured on dev (2026-08-26): audio the
# provider sent before the worker joined the room queued up (websockets
# max_queue → TCP backpressure) and was then drained at exactly real-time by
# `AudioSource.capture_frame`, so a 2–4 s head start became a FIXED lag for the
# whole call (first STT partial +3.4 s vs +1.2 s when the client waited). Browser
# callers start the mic the moment the socket opens, so every real call paid it.
# The relay buffer below is bounded and drops the OLDEST frames: lag can never
# exceed _RELAY_MAX_MS + the AudioSource queue (_SOURCE_QUEUE_MS).
_RELAY_MAX_MS = 300
_SOURCE_QUEUE_MS = 300
_PCM16_16K_BYTES_PER_MS = 32  # 16 kHz * 2 bytes


class AudioRelayBuffer:
    """Bounded FIFO of provider PCM16 frames; overflow drops the OLDEST frame.

    Single asyncio loop, one producer (`push` from the ws reader) and one
    consumer (`pop` from the capture loop). `close()` wakes a waiting consumer
    with None and makes further pushes no-ops.
    """

    def __init__(self, max_ms: int = _RELAY_MAX_MS) -> None:
        self.max_bytes = max_ms * _PCM16_16K_BYTES_PER_MS
        self.dropped = 0
        self._frames: deque[bytes] = deque()
        self._bytes = 0
        self._closed = False
        self._waiter: asyncio.Future | None = None

    def push(self, frame: bytes) -> None:
        if self._closed:
            return
        self._frames.append(frame)
        self._bytes += len(frame)
        while self._bytes > self.max_bytes and len(self._frames) > 1:
            old = self._frames.popleft()
            self._bytes -= len(old)
            self.dropped += 1
        self._wake()

    def pop_nowait(self) -> bytes | None:
        if not self._frames:
            return None
        frame = self._frames.popleft()
        self._bytes -= len(frame)
        return frame

    async def pop(self) -> bytes | None:
        """Next frame, oldest first; waits while empty; None once closed and drained."""
        while True:
            frame = self.pop_nowait()
            if frame is not None:
                return frame
            if self._closed:
                return None
            self._waiter = asyncio.get_running_loop().create_future()
            try:
                await self._waiter
            finally:
                self._waiter = None

    def drain(self) -> list[bytes]:
        out = list(self._frames)
        self._frames.clear()
        self._bytes = 0
        return out

    def close(self) -> None:
        self._closed = True
        self._wake()

    def _wake(self) -> None:
        waiter = self._waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(None)


async def _pump_provider_audio(buffer: AudioRelayBuffer, source, *, frame_factory=None) -> None:
    """Capture loop: relay buffer → `rtc.AudioSource`, one 16 kHz PCM16 frame at a time.

    `capture_frame` paces to real time (it waits when its queue is full); the
    bounded buffer in front of it is what keeps a provider burst from turning
    into lasting lag. Returns when the buffer is closed and drained.
    """
    if frame_factory is None:
        from livekit import rtc

        def frame_factory(pcm: bytes):  # noqa: ANN202 - livekit frame
            return rtc.AudioFrame(data=pcm, sample_rate=16000, num_channels=1, samples_per_channel=len(pcm) // 2)

    try:
        while True:
            pcm = await buffer.pop()
            if pcm is None:
                return
            await source.capture_frame(frame_factory(pcm))
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — source closed mid-call
        logger.debug("gateway: provider-audio pump ended", exc_info=True)


async def _pump_agent_events(queue, ws) -> None:
    """Forward queued worker UI events (JSON) to the provider ws as TEXT frames.

    Sends `str` so the websockets lib emits TEXT frames — the provider tells
    events apart from the binary PCM16 audio frames by frame type alone.
    """
    import asyncio

    try:
        while True:
            msg = await queue.get()
            await ws.send(msg)
            queue.task_done()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — provider ws closed mid-call
        logger.debug("gateway: agent-event pump ended", exc_info=True)


def _extract_request(ws) -> tuple[str, str, str]:
    """Read (path, Host, Authorization) from a modern ``websockets`` (>=13)
    ``ServerConnection``. The request lives on ``ws.request`` (a ``Request``
    with ``.path`` and a ``.headers`` mapping) — the legacy ``ws.path`` /
    ``ws.request_headers`` attributes do not exist on the current API. Pure +
    unit-tested so a version drift in this accessor shape fails offline.

    Browser WebSocket clients cannot set the ``Authorization`` header; when it is
    absent the bearer token is also accepted from a ``?key=`` / ``?token=`` query
    parameter (synthesized into a ``Bearer <token>`` string). The header always
    takes precedence, so header-based callers are unchanged."""
    req = ws.request
    authz = req.headers.get("Authorization", "")
    if not authz:
        from urllib.parse import parse_qs

        q = parse_qs(urlparse(req.path).query)
        tok = (q.get("key") or q.get("token") or [""])[0].strip()
        if tok:
            authz = "Bearer " + tok
    return req.path, req.headers.get("Host", ""), authz


def run_gateway() -> None:  # pragma: no cover — integration entry
    import asyncio

    from noble_agent.config import get_settings
    from noble_agent.gateway.credentials import CredentialsClient

    settings = get_settings()
    credentials_client = CredentialsClient(settings.gateway_credentials_api_url, settings.gateway_cred_cache_ttl_sec)
    asyncio.run(_serve(settings, credentials_client))


async def _serve(settings, credentials_client) -> None:  # pragma: no cover
    import asyncio

    import websockets

    async def handler(ws):
        await _handle(ws, settings, credentials_client)

    async with websockets.serve(handler, settings.gateway_host, settings.gateway_port):
        await asyncio.Future()


async def _handle(ws, settings, credentials_client) -> None:  # pragma: no cover
    import asyncio

    from noble_agent.gateway.auth import authorize

    path, _host, authz = _extract_request(ws)
    mode = route(path)
    if mode is None:
        await ws.close(code=4004, reason="unknown_route")
        return
    result = await authorize(authz, credentials=credentials_client)
    if not result.ok:
        await ws.close(code=4001, reason=result.reason)
        return
    # Phép đối chiếu `credential.kind` vs `mode` ĐÃ BỎ (`0941`): Portal thôi gửi `kind`
    # từ `0919` nên nó luôn rỗng, nhánh cảnh báo chưa từng chạy, và một khoá mở được CẢ
    # chat lẫn voice là thiết kế cố ý (`0919`) chứ không phải thiếu sót cần cảnh báo.
    try:
        first = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT_SEC)
    except TimeoutError:
        await ws.close(code=4008, reason="handshake_timeout")
        return
    hs = parse_handshake(first if isinstance(first, str) else "")
    identity_json = json.dumps(hs.get("identity") or {}, ensure_ascii=False)
    call_id = str(hs.get("call_id") or "call")
    if mode == "voice":
        await _stash_voice_credentials(settings, result.tenant_id, result.credentials)
        await _bridge_voice(ws, settings, result.tenant_id, identity_json, call_id)
    else:
        from noble_agent.gateway.chat_proxy import proxy_chat

        await proxy_chat(ws, settings, result.tenant_id, hs.get("identity") or {}, credentials=result.credentials)


async def _stash_voice_credentials(settings, tenant_id: str, credentials) -> None:
    """Đặt credential PG (mã hoá Fernet) vào Redis nội bộ TRƯỚC khi dispatch voice —
    worker job fetch lúc vào cuộc (storage/credential_stash.py). Best-effort: Redis
    lỗi / secret rỗng / credential thiếu role+password → bỏ qua, cuộc gọi VẪN chạy
    (worker rơi về shared DSN). Không secret nào đi qua LiveKit Cloud."""
    if credentials is None or not credentials.postgres_role or not credentials.postgres_password:
        return
    if not settings.gateway_worker_secret or credentials.expires_at is None:
        return
    try:
        from noble_agent.storage import credential_stash
        from noble_agent.storage.redis_client import get_redis

        redis = await get_redis()
        await credential_stash.stash(
            redis, settings.gateway_worker_secret, tenant_id,
            role=credentials.postgres_role, password=credentials.postgres_password,
            expires_at=credentials.expires_at,
            agent_key_id=getattr(credentials, "agent_key_id", ""),
        )
    except Exception:  # noqa: BLE001 — stash là best-effort, không được rớt cuộc gọi
        logger.warning("gateway: stash voice credential fail (tenant=%s) — voice dùng shared DSN", tenant_id)


async def _bridge_voice(ws, settings, tenant_id: str, identity_json: str, call_id: str) -> None:  # pragma: no cover
    """Join the tenant's LiveKit room as a participant, relaying audio both ways.

    Protocol on `ws` mirrors voice/service/protocol.py: binary frames = raw
    PCM16 audio, text frames = JSON. Outbound text frames carry the worker's UI
    events verbatim (same shapes as the browser transports: `transcript`,
    `agent_speaking`, `tool_start`/`tool_done`, `media`, `agent_interrupted`,
    `agent_done`, `partial_transcript`, `session_ended`, `error`), relayed from
    the LiveKit data channel. Inbound text frames stay reserved/ignored.
    Integration-level (needs a live LiveKit server + real WS client) — covered
    by SMOKE.md, not unit tests.
    """
    import asyncio

    from livekit import rtc

    from noble_agent.gateway.livekit_bridge import build_dispatch_token, session_id_frame

    jwt, url, room = build_dispatch_token(
        tenant_id,
        identity_json,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        url=settings.livekit_url,
        agent_name=settings.livekit_agent_name,
        call_id=call_id,
    )
    logger.info("gateway: bridging voice tenant=%s room=%s", tenant_id, room)

    # Tell the provider which session this call is, BEFORE any audio: the id is the
    # room name minted just above (server-side ms + random suffix), so the client
    # cannot derive it from the `call_id` it sent. `/v1/chat` already pushes the same
    # frame from the worker; voice has no such hop (dispatch goes through LiveKit
    # Cloud), so the gateway is the only place that knows it. Best-effort — a client
    # that already walked away just tears the bridge down below as before.
    with contextlib.suppress(Exception):
        await ws.send(session_id_frame(room))

    room_client = rtc.Room()
    # Strong-ref set for the audio-pump task(s): asyncio.create_task only keeps
    # a weak ref in the event loop, so without holding one here CPython may GC
    # the task mid-call and agent audio silently stops (mirrors the repo's
    # `_bg_tasks` pattern, e.g. server/base_session.py / storage/persist.py).
    pump_tasks: set[asyncio.Task] = set()
    # Set when the LiveKit room drops (worker left / job ended) so the ws→room
    # forward loop stops waiting on the provider socket and the bridge tears down
    # instead of hanging with a half-open connection.
    room_gone = asyncio.Event()

    # Register room event handlers BEFORE connect(): with the default
    # auto_subscribe, the SDK fires `track_subscribed` for tracks it subscribes
    # to during the post-connect sync. If we registered after connect() we could
    # miss the agent's audio track (published as soon as the worker joins) and
    # relay silence back to the provider.
    @room_client.on("track_subscribed")
    def _on_track(track, publication, participant):  # noqa: ANN001 - LiveKit callback signature
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            t = asyncio.create_task(_pump_agent_audio(rtc.AudioStream(track), ws))
            pump_tasks.add(t)
            t.add_done_callback(pump_tasks.discard)

    # Worker UI events (transcript / agent_speaking / tool / media / ...) arrive on
    # the data channel. Bounded queue + drop-when-full: a slow provider loses UI
    # events, never audio. Registered BEFORE connect() for the same reason as
    # track_subscribed above — the greeting events fire as soon as the worker joins.
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=256)

    @room_client.on("data_received")
    def _on_data(packet):  # noqa: ANN001 - LiveKit callback signature
        enqueue_event(event_queue, getattr(packet, "topic", ""), packet.data)

    event_pump = asyncio.create_task(_pump_agent_events(event_queue, ws))
    pump_tasks.add(event_pump)
    event_pump.add_done_callback(pump_tasks.discard)

    @room_client.on("disconnected")
    def _on_disconnected(*_a):  # noqa: ANN002 - LiveKit callback signature
        room_gone.set()

    # Read the provider socket from NOW — before the room connects. Audio that
    # arrives while the room isn't ready is trimmed by the bounded relay instead
    # of piling up in the socket and lagging the whole call (see _RELAY_MAX_MS).
    relay = AudioRelayBuffer()

    async def _read_provider() -> None:
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    relay.push(bytes(msg))
                # text frames = JSON control (reserved; ignored for now)
        finally:
            relay.close()  # provider hung up → capture loop drains and exits

    reader = asyncio.create_task(_read_provider())

    try:
        await room_client.connect(url, jwt)

        source = rtc.AudioSource(sample_rate=16000, num_channels=1, queue_size_ms=_SOURCE_QUEUE_MS)
        track = rtc.LocalAudioTrack.create_audio_track("provider-audio", source)
        await room_client.local_participant.publish_track(track)

        capture = asyncio.create_task(_pump_provider_audio(relay, source))
        pump_tasks.add(capture)
        capture.add_done_callback(pump_tasks.discard)

        # Stop as soon as EITHER the provider hangs up (reader returns) OR the
        # room drops (worker gone → room_gone set).
        gone = asyncio.create_task(room_gone.wait())
        try:
            await asyncio.wait({reader, gone}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            gone.cancel()
    except Exception:
        logger.exception("gateway: voice bridge error tenant=%s room=%s", tenant_id, room)
    finally:
        reader.cancel()
        relay.close()
        for t in list(pump_tasks):
            t.cancel()
        if relay.dropped:
            # Mostly the pre-ready head start (2–4 s ≈ 100–200 frames); a much
            # larger count means the provider streams faster than real time.
            logger.info(
                "gateway: dropped %d provider audio frames to bound lag (tenant=%s room=%s)",
                relay.dropped, tenant_id, room,
            )
        await room_client.disconnect()
        with contextlib.suppress(Exception):
            await ws.close()


async def _pump_agent_audio(stream, ws) -> None:  # pragma: no cover
    """Forward the tenant worker's agent audio (subscribed LiveKit track) back to `ws`."""
    import asyncio

    try:
        async for event in stream:
            await ws.send(bytes(event.frame.data))
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — provider ws closed / track ended mid-pump
        logger.debug("gateway: agent-audio pump ended", exc_info=True)
