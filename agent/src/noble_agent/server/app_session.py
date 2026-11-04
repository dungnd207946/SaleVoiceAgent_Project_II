"""Provisioning cho phiên agent của NobleX app (Phase 1: chat).

Server-to-server: backend NobleX (sau khi xác thực user) POST danh tính user
vào đây. Ta derive một session_id ổn định, seed Customer state trong Redis (để
Luna biết đang nói với ai TRƯỚC lượt đầu), mint connect-token ngắn hạn, và trả
thứ app cần để mở WS /chat thẳng. Identity là server-authoritative — WS client
không tự set.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import time

from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from noble_agent.config import settings
from noble_agent.storage.redis_client import get_redis
from noble_agent.storage.repo import StateRepo
from noble_agent.tenant.current import use_tenant

logger = logging.getLogger("server")

# Seconds a LiveKit room stays alive after its last participant leaves. Kept
# short so a voice room is freed quickly once the app disconnects — each voice
# call uses a fresh room name anyway, so nothing relies on the room persisting.
_ROOM_EMPTY_TIMEOUT_S = 5

_GENDER_MAP = {
    "m": "M",
    "male": "M",
    "nam": "M",
    "f": "F",
    "female": "F",
    "nữ": "F",
    "nu": "F",
}


def _normalize_gender(raw: object) -> str | None:
    if not raw:
        return None
    return _GENDER_MAP.get(str(raw).strip().lower())


def _derive_session_id(noble_user_id: str) -> str:
    """Stable, resumable session id — 12 hex, khớp shape session-id hiện có."""
    compact = noble_user_id.replace("-", "").lower()
    return "app-" + compact[:12]


def _compose_noble_info(identity: dict) -> str | None:
    """Gộp các field profile phụ Luna dùng được vào một chuỗi. None nếu rỗng."""
    parts: list[str] = []
    if identity.get("noble_info"):
        parts.append(str(identity["noble_info"]))
    if identity.get("email"):
        parts.append(f"email: {identity['email']}")
    if identity.get("birthday"):
        parts.append(f"sinh nhật: {identity['birthday']}")
    return " | ".join(parts) if parts else None


def _token_key(session_id: str) -> str:
    return f"session:{session_id}:connect_token"


def identity_to_fields(identity: dict) -> dict:
    """Map the app/provider `identity` shape onto Customer fields. Pure; shared
    by provision_session (chat), the /chat set_customer handler, and the LiveKit
    worker's voice identity seed."""
    fields: dict = {}
    if identity.get("full_name"):
        fields["full_name"] = identity["full_name"]
        fields["name"] = identity["full_name"]
    if identity.get("phone"):
        fields["phone"] = identity["phone"]
    gender = _normalize_gender(identity.get("gender"))
    if gender:
        fields["gender"] = gender
    if isinstance(identity.get("is_noble_customer"), bool):
        fields["is_noble_customer"] = identity["is_noble_customer"]
    noble_info = _compose_noble_info(identity)
    if noble_info:
        fields["noble_info"] = noble_info
    return fields


async def provision_session(body: dict) -> tuple[dict, int]:
    """Core provisioning (transport-agnostic, testable). Returns (payload, status)."""
    noble_user_id = str(body.get("noble_user_id") or "").strip()
    if not noble_user_id:
        return {"error": "noble_user_id required"}, 400

    tenant_id = str(body.get("tenant_id") or "").strip() or settings.tenant_id
    with use_tenant(tenant_id):
        channel = body.get("channel") or "chat"
        identity = body.get("identity") or {}
        session_id = _derive_session_id(noble_user_id)
        if channel == "voice":
            # Voice: the LiveKit room name IS the session id, and a token's agent
            # dispatch is honored ONLY when the room is first created. A stable name
            # meant a reconnect joined the still-alive prior room → dispatch ignored
            # → no agent joined. Give every voice call a unique room so LiveKit
            # always creates it fresh → agent always dispatched. ms for ordering +
            # a short random suffix so two calls in the same ms can't collide.
            # (No cross-call conversation resume for voice — intended.)
            session_id = f"{session_id}-{int(time.time() * 1000)}-{secrets.token_hex(2)}"

        # Build the seed field set (only truthy values overwrite).
        fields: dict = {"noble_user_id": noble_user_id, **identity_to_fields(identity)}

        # Seed via StateRepo directly (no LLM runner needed) — same 3 keys the turn
        # loop reads. Merge onto existing customer so re-provision doesn't blank
        # fields (mirrors facade.set_customer_fields semantics).
        from noble_agent.storage.models import Customer

        redis = await get_redis()
        repo = StateRepo(redis_client=redis, ttl_seconds=settings.session_ttl_seconds)
        meta, customer, state = await repo.load(session_id)
        merged = customer.model_dump()
        for key, value in fields.items():
            if isinstance(value, bool) or value:
                merged[key] = value
        new_customer = Customer.model_validate(merged)
        await repo.save_all(session_id, meta, new_customer, state)

        if channel == "voice":
            if not (settings.livekit_api_key and settings.livekit_api_secret):
                return {"error": "livekit_not_configured"}, 503
            identity = f"user-{session_id}"
            lk_token, lk_url, room = _mint_livekit_token(
                session_id, identity, fields.get("full_name") or identity, tenant_id=tenant_id
            )
            return (
                {
                    "session_id": session_id,
                    "channel": "voice",
                    "livekit_url": lk_url,
                    "livekit_token": lk_token,
                    "room": room,
                },
                200,
            )

        # Mint a short-lived connect-token for the direct WS handshake.
        token = secrets.token_urlsafe(24)
        ttl = settings.app_connect_token_ttl_seconds
        await redis.set(_token_key(session_id), token, ex=ttl)

        base = (settings.app_ws_public_base or "").rstrip("/")
        ws_path = f"/chat?session={session_id}&token={token}"
        ws_url = f"{base}{ws_path}" if base else ws_path

        return (
            {
                "session_id": session_id,
                "channel": channel,
                "ws_url": ws_url,
                "connect_token": token,
                "expires_in": ttl,
            },
            200,
        )


async def verify_connect_token(session_id: str, token: str | None) -> bool:
    """True iff `token` matches the stored connect-token for `session_id`."""
    if not token:
        return False
    try:
        redis = await get_redis()
        stored = await redis.get(_token_key(session_id))
    except Exception:
        logger.warning("verify_connect_token: redis error", exc_info=True)
        return False
    if not stored:
        return False
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8")
    return hmac.compare_digest(stored, token)


def _json(data: dict, status: int) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return Response(status, "OK" if status < 400 else "Error", headers, body)


async def handle_app_session(request: Request) -> Response:
    """POST /api/v1/app/session — server-to-server, header X-Noble-App-Key."""
    method = getattr(request, "method", "GET").upper()
    if method != "POST":
        return _json({"error": "method_not_allowed"}, 405)
    if not settings.noble_app_api_key:
        return _json({"error": "app_api_disabled", "message": "Set NOBLE_APP_API_KEY to enable."}, 503)
    auth = request.headers.get("X-Noble-App-Key") or request.headers.get("x-noble-app-key", "")
    if not auth or not hmac.compare_digest(auth, settings.noble_app_api_key):
        return _json({"error": "unauthorized"}, 401)

    raw = getattr(request, "body", None) or b""
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    try:
        body = json.loads(raw) if raw else {}
    except Exception:
        body = {}

    payload, status = await provision_session(body)
    return _json(payload, status)


def _mint_livekit_token(
    session_id: str,
    identity: str,
    name: str,
    *,
    tenant_id: str | None = None,
    empty_timeout: int = _ROOM_EMPTY_TIMEOUT_S,
) -> tuple[str, str, str]:
    """Mint a LiveKit access token for `identity` to join room `session_id`,
    with the hotline agent embedded as a dispatched agent so LiveKit brings the
    agent into the room when the participant joins, and the resolved `tenant_id`
    carried as participant metadata so the shared worker's `_job_tenant` resolves
    the caller's tenant (falls back to `settings.tenant_id`). Returns (jwt, url, room).
    Caller must ensure settings.livekit_api_key/secret are set.

    `empty_timeout` is applied to the room LiveKit auto-creates from this token
    (honored only at creation) so the room is released quickly once empty.
    """
    import json

    from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

    tid = tenant_id or settings.tenant_id
    token = (
        AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name or identity)
        .with_metadata(json.dumps({"tenant_id": tid}, ensure_ascii=False))
        .with_grants(
            VideoGrants(
                room_join=True,
                room=session_id,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(
            RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=settings.livekit_agent_name)],
                empty_timeout=empty_timeout,
            )
        )
        .to_jwt()
    )
    url = settings.livekit_public_url or settings.livekit_url
    return token, url, session_id
