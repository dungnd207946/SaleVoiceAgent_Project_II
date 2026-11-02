"""HTTP request handler — static files + REST API + health check."""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

# Apply websockets POST/OPTIONS patch BEFORE importing websockets internals.
# websockets 16.0 rejects all non-GET methods at parse() level, breaking
# every POST endpoint here (/api/call-me, /api/v1/app/session).
# See _websockets_post_patch.py for full rationale.
from noble_agent.server import _websockets_post_patch  # noqa: F401 E402  # isort: skip

import websockets.asyncio.server
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from noble_agent.config import settings

STATIC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static"
CT_MAP = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}


def _json_default(obj):
    """Serializer for types json doesn't handle natively.

    Datetimes → ISO 8601 with T separator (JS `new Date(str)` friendly).
    ObjectId → str. Anything else → str fallback.
    """
    import datetime as _dt

    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    return str(obj)


def _json_response(data: dict, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False, default=_json_default).encode("utf-8")
    headers = Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return Response(status, "OK" if status == 200 else "Error", headers, body)


async def _read_request_body(request: Request) -> dict:
    """Parse JSON body. Returns empty dict on any failure."""
    try:
        body = getattr(request, "body", None) or b""
        if isinstance(body, memoryview):
            body = body.tobytes()
        if not body:
            return {}
        return json.loads(body)
    except Exception:
        return {}


async def process_request(
    connection: websockets.asyncio.server.ServerConnection,
    request: Request,
) -> Response | None:
    """Handle HTTP requests (static files + API). Return None to upgrade to WebSocket."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None

    path = request.path.split("?")[0]

    # ── Health: liveness ──────────────────────────────────────────────────
    if path == "/health":
        return _json_response({"status": "ok", "ts": time.time()})

    # ── Health: readiness (checks all services) ──────────────────────────
    if path == "/health/ready":
        from noble_agent.storage.connection import get_connection_manager

        cm = get_connection_manager()
        services = await cm.health()

        # Vector store — FlatStore is primary after rev 3 RAG migration.
        # Health is reported via the embeddings entry below (FlatStore singleton
        # readiness). The Qdrant probe only runs when the qdrant dense backend
        # is selected (NOBLE_RAG_BACKEND=qdrant).
        if (settings.noble_rag_backend or "").lower() == "qdrant":
            try:
                from qdrant_client import AsyncQdrantClient

                qc = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
                await qc.get_collections()
                services["qdrant"] = "ok"
                await qc.close()
            except Exception as e:
                services["qdrant"] = f"error: {e}"

        # LLM (lightweight check — list models). Unified uses
        # `agent.llm.client.StreamingClient`; the readiness probe lists models
        # against the first available provider client.
        try:
            from noble_agent.agent.facade import build_llm_providers

            providers = build_llm_providers()
            if not providers:
                services["llm"] = "error: no providers configured"
            else:
                name, client = providers[0]
                # AnthropicProvider has no .models.list(); fall back to a
                # cheap attribute touch in that case.
                if hasattr(client, "models") and hasattr(client.models, "list"):
                    await client.models.list()
                services["llm"] = f"ok ({name})"
        except Exception as e:
            services["llm"] = f"error: {e}"

        # Embeddings — Step 9 rewire: check FlatStore singleton readiness
        try:
            from noble_agent.agent.rag.flat_store_adapter import _store as _flat_store

            if _flat_store is None or _flat_store.embeddings is None:
                services["embeddings"] = "not warmed (call noble_search to init)"
            else:
                n_chunks = len(_flat_store.chunks)
                dim = _flat_store.embeddings.shape[1]
                backend = _flat_store.embedder.backend
                services["embeddings"] = f"ok ({backend}, {n_chunks} chunks, {dim}d)"
        except Exception as e:
            services["embeddings"] = f"error: {e}"

        from noble_agent.server.admission import get_chat_admission

        adm = get_chat_admission().stats()
        all_ok = all("error" not in str(v) for v in services.values()) and not adm["at_capacity"]
        status = "ok" if all_ok else "degraded"
        code = 200 if all_ok else 503
        return _json_response(
            {"status": status, "ts": time.time(), "services": services, "chat_admission": adm}, code
        )

    # ── API: current config ─────────────────────────────────────────────
    if path == "/api/config":
        cfg = {
            "stt": {
                "backend": settings.stt_backend,
                "model": settings.soniox_model if settings.stt_backend == "soniox" else "sherpa",
            },
            "llm": {"model": settings.gemini_model if settings.gemini_api_key else settings.openai_model},
            "tts": {"backend": settings.tts_backend},
            "rag": {"provider": settings.noble_rag_backend},
        }
        return _json_response(cfg)

    # ── API: LiveKit access token (dev browser tester) ────────────────────
    # GET /livekit/token?room=<name>&identity=<name>. Gated: prod mints via
    # POST /api/v1/app/session (channel=voice). Uses the shared minter so the
    # token carries agent dispatch (RoomAgentDispatch) — without it a WebRTC
    # client joins an agent-less room.
    if path == "/livekit/token":
        if not settings.livekit_token_public:
            return _json_response({"error": "livekit_token_disabled"}, 503)
        if not settings.livekit_api_key or not settings.livekit_api_secret:
            return _json_response({"error": "LiveKit not configured"}, 503)
        from urllib.parse import parse_qs, urlparse

        from noble_agent.server.app_session import _mint_livekit_token

        qs = parse_qs(urlparse(request.path).query)
        room = qs.get("room", [f"hotline-{int(time.time())}"])[0]
        identity = qs.get("identity", [f"user-{int(time.time() * 1000)}"])[0]
        token, url, room = _mint_livekit_token(room, identity, identity)
        return _json_response({"token": token, "url": url, "room": room, "identity": identity})

    # ── API: NobleX app session provisioning (server-to-server) ──────────
    # POST /api/v1/app/session — backend seeds identity + gets a connect-token.
    if path == "/api/v1/app/session":
        from noble_agent.server.app_session import handle_app_session

        return await handle_app_session(request)

    # ── API: customer list (fake DB) ─────────────────────────────────────
    if path == "/api/customers":
        fp = Path(__file__).resolve().parent.parent.parent.parent / "data" / "fake_customers.json"
        body = fp.read_bytes() if fp.exists() else b"[]"
        headers = Headers([("Content-Type", "application/json")])
        return Response(200, "OK", headers, body)

    # ── API: "Gọi cho tôi" — outbound call via ARI ───────────────────────
    # Body: {"phone": "09xxxxxxxx"}. Uses `Local/<phone>@from-internal` so
    # FreePBX Outbound Routes substitute the callerID (direct PJSIP dial
    # with a 1800 hotline CID gets rejected by VN mobile carriers).
    if path == "/api/call-me" and request.method.upper() == "POST":
        if not settings.asterisk_ari_password:
            return _json_response({"error": "ARI not configured"}, 503)
        body_data = await _read_request_body(request)
        phone = (body_data.get("phone") or "").strip()
        if not phone:
            return _json_response({"error": "phone required"}, 400)
        from noble_agent.telephony.ari_client import ARIClient

        client = ARIClient()
        try:
            result = await client.originate_channel(phone)
        finally:
            await client.stop()
        if not result:
            return _json_response(
                {"error": "originate failed — check agent log + ARI creds"},
                502,
            )
        return _json_response(
            {
                "status": "calling",
                "phone": phone,
                "channel_id": result.get("id"),
                "state": result.get("state"),
                "message": f"Calling {phone} — pick up to hear the agent.",
            }
        )

    # ── Static files ──────────────────────────────────────────────────────
    # Root redirects to the LiveKit browser test UI. The legacy aiortc WebRTC
    # UI was retired when phase 7 telephony + LiveKit transport replaced it.
    # CRM dashboard moved to santa-agent-cms (separate service).
    if path in ("/", "/index.html"):
        fp = STATIC_DIR / "livekit.html"
    elif path == "/chat":
        fp = STATIC_DIR / "chat.html"
    else:
        fp = STATIC_DIR / path.lstrip("/")

    if not fp.exists() or not fp.is_file():
        return connection.reject(404, "Not Found\n")

    ct = CT_MAP.get(fp.suffix, "application/octet-stream")
    body = fp.read_bytes()
    headers = Headers([("Content-Type", ct), ("Content-Length", str(len(body)))])
    return Response(200, "OK", headers, body)


# ── Entry point ───────────────────────────────────────────────────────────────


async def _maybe_reconcile_qdrant() -> None:
    """Rebuild the Qdrant clone + local BM25 fallback once at server-agent
    startup. Gated on the qdrant backend; failures log and never wedge boot."""
    import logging

    if (settings.noble_rag_backend or "").lower() != "qdrant":
        return
    log = logging.getLogger("server")
    try:
        import asyncio

        from noble_agent.agent.rag.sparse_reconcile import reconcile

        log.info("Reconciling Qdrant hybrid clone (dense+sparse) + local fallback ...")
        n = await asyncio.wait_for(reconcile(), timeout=settings.qdrant_reconcile_timeout_sec)
        log.info("Qdrant reconcile done: %d points", n)
    except Exception as exc:  # noqa: BLE001 — boot must survive a reconcile failure
        log.error("Qdrant reconcile failed (continuing): %s", exc)


def run_server() -> None:
    """Synchronous entry point: initialises the event loop and runs the server."""
    import asyncio

    asyncio.run(_run_server_async())


async def _run_server_async() -> None:
    """Async server startup for the unified package.

    Mirrors noble_agent.agent.app.main() but uses unified server handlers.
    """
    import asyncio
    import logging

    from noble_agent.server.logging_config import setup_logging

    setup_logging()
    log = logging.getLogger("server")

    log.info("=" * 60)
    log.info("Noble Voice Agent (unified)")
    log.info("=" * 60)
    log.info("  Server: ws://%s:%s", settings.ws_host, settings.ws_port)
    log.info("=" * 60)

    from noble_agent.storage.connection import get_connection_manager

    cm = get_connection_manager()
    await cm.initialize()

    from noble_agent.observability.phoenix_tracing import init_tracing

    init_tracing(settings)

    from noble_agent.voice.prewarm import prewarm_voice_models

    log.info("Pre-warming voice models (STT/TTS) ...")
    prewarm_voice_models()

    await _maybe_reconcile_qdrant()

    from noble_agent.data import db_project_registry

    await db_project_registry.warm()

    # SP-D heartbeat (contract C3): proactively push <tenant>/_heartbeat.json to
    # the tenant store so Backend/Dashboard can infer status. Inert unless the
    # tenant store is enabled; a start failure must never abort boot.
    heartbeat_task = None
    hb_stop = None
    from noble_agent.tenant.heartbeat import should_emit

    if should_emit(settings):
        try:
            from noble_agent.tenant.heartbeat import build_heartbeat_supervisor

            hb_stop = asyncio.Event()
            supervisor = build_heartbeat_supervisor(settings, "chat")
            heartbeat_task = asyncio.create_task(supervisor.run(hb_stop))
            log.info("Heartbeat supervisor started (every %.0fs, active tenants)", settings.heartbeat_sec)
        except Exception as exc:  # noqa: BLE001 — heartbeat must never abort boot
            log.error("Heartbeat supervisor failed to start (continuing): %s", exc)

    import websockets.asyncio.server

    from noble_agent.server.ws_handler import handler

    try:
        async with websockets.asyncio.server.serve(
            handler,
            settings.ws_host,
            settings.ws_port,
            process_request=process_request,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=10,
        ):
            log.info("Ready (unified). Open http://localhost:%s in browser.", settings.ws_port)
            await asyncio.Future()
    finally:
        if hb_stop is not None:
            hb_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat_task
        await cm.close()
