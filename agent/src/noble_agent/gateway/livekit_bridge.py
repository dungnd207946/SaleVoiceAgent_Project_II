"""Bridge helpers: mint a room-join token that (a) dispatches the shared worker
and (b) carries the end-user identity plus tenant_id as participant metadata for
the worker to seed Customer. Pure token/room logic — the actual audio relay is
wired in server.py and covered by smoke tests."""
from __future__ import annotations

import secrets
import time

_ROOM_EMPTY_TIMEOUT_S = 5


def room_name(tenant_id: str, call_id: str) -> str:
    """Scoped room name: tenant-callid-ms-hex. Unique per call via ms + random suffix."""
    return f"{tenant_id}-{call_id}-{int(time.time() * 1000)}-{secrets.token_hex(2)}"


def session_id_frame(room: str) -> str:
    """The `session_id` handshake frame the voice gateway pushes to the provider.

    The voice session id IS the room name — the worker builds
    `RoomSession(session_id=ctx.room.name)` (transport/livekit/worker.py) and that
    string is what lands in `tenant_data.conversations`. The client cannot derive
    it from its own `call_id`: `room_name()` appends a server-side ms + random
    suffix. Without this frame a provider has no way to tie anything (feedback via
    Portal `POST /agent/feedback`, transcript lookups) back to the call it just had.

    Same shape as `/v1/chat` already sends (server/ws_handler.py) — one contract
    for both channels, so a client writes the handler once.
    """
    import json

    return json.dumps({"type": "session_id", "session_id": room}, ensure_ascii=False)


def build_dispatch_token(
    tenant_id: str,
    identity_json: str,
    *,
    api_key: str,
    api_secret: str,
    url: str,
    agent_name: str,
    call_id: str = "call",
    minter=None,
) -> tuple[str, str, str]:
    """Mint a LiveKit room-join token that dispatches the SHARED worker
    (`agent_name`, tenant-independent) and carries the caller identity PLUS
    `tenant_id` as participant metadata — the worker resolves its per-job tenant
    from that metadata. Returns (jwt, url, room)."""
    import json

    from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

    minter = minter or AccessToken
    room = room_name(tenant_id, call_id)
    identity = f"caller-{room}"
    try:
        meta = json.loads(identity_json) if identity_json else {}
        if not isinstance(meta, dict):
            meta = {}
    except (ValueError, TypeError):
        meta = {}
    meta["tenant_id"] = tenant_id
    metadata_json = json.dumps(meta, ensure_ascii=False)
    token = (
        minter(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_metadata(metadata_json)
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(
            RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=agent_name)],
                empty_timeout=_ROOM_EMPTY_TIMEOUT_S,
            )
        )
        .to_jwt()
    )
    return token, url, room
