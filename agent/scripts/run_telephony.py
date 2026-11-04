"""Run the telephony stack (AudioSocket + ARI + admin HTTP) as a standalone process.

Why standalone: `TelephonyManager` is only wired into the aiortc app loop
(`agent/app.py:main`). When `TRANSPORT_BACKEND=livekit`, the LiveKit worker
takes over and telephony never starts. This script gives you both without
forcing a transport switch — run it in a separate terminal:

    # Terminal 1 — LiveKit WebRTC worker (web demo)
    python -m noble_agent dev

    # Terminal 2 — Telephony (AudioSocket :8090 + ARI + admin :8767)
    python scripts/run_telephony.py

Admin HTTP (port `TELEPHONY_ADMIN_PORT`, default 8767):
  GET  /                 → serve static/livekit.html (includes "Gọi cho tôi" card)
  GET  /static/<file>    → static asset
  POST /api/call-me      → JSON body `{"phone": "09xxxxxxxx"}` → ARI originate
  GET  /api/health       → {"ok": true, "audiosocket": true, "ari": bool}

Requires `TELEPHONY_ENABLED=true` and `ASTERISK_ARI_PASSWORD=...` in `.env`.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aiohttp import web  # noqa: E402

from noble_agent.config import settings  # noqa: E402
from noble_agent.telephony.ari_client import ARIClient  # noqa: E402
from noble_agent.telephony.session import TelephonyManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("telephony.runner")

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


# ── Admin HTTP handlers ─────────────────────────────────────────────────────

async def _handle_index(_request: web.Request) -> web.Response:
    """Serve the LiveKit demo page — which also hosts the 'Gọi cho tôi' UI."""
    fp = STATIC_DIR / "livekit.html"
    if not fp.exists():
        return web.Response(status=404, text="livekit.html not found")
    return web.Response(
        body=fp.read_bytes(),
        content_type="text/html",
        charset="utf-8",
    )


async def _handle_static(request: web.Request) -> web.Response:
    """Serve any file under `static/` — used for favicons, css, etc."""
    rel = request.match_info.get("filename", "")
    fp = (STATIC_DIR / rel).resolve()
    # Prevent directory traversal.
    if not str(fp).startswith(str(STATIC_DIR.resolve())) or not fp.is_file():
        return web.Response(status=404, text="not found")
    return web.FileResponse(fp)


async def _handle_health(_request: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "audiosocket_port": settings.audiosocket_port,
        "ari_configured": bool(settings.asterisk_ari_password),
        "trunk": settings.asterisk_sip_trunk,
        "outbound_context": settings.asterisk_outbound_context,
    })


async def _handle_call_me(request: web.Request) -> web.Response:
    """POST /api/call-me  body: {"phone": "09xxxxxxxx"}

    Originates a call through FreePBX via `Local/<phone>@from-internal` so
    that FreePBX Outbound Routes handle CID substitution (direct PJSIP dial
    with a 1800 CID is rejected by VN carriers). On answer the channel runs
    the `asterisk_outbound_context` dialplan which must call AudioSocket to
    this process.
    """
    if not settings.asterisk_ari_password:
        return web.json_response(
            {"error": "ARI not configured (ASTERISK_ARI_PASSWORD missing)"},
            status=503,
        )
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    phone = (data.get("phone") or "").strip()
    if not phone:
        return web.json_response({"error": "phone required"}, status=400)

    client = ARIClient()
    try:
        result = await client.originate_channel(phone)
    finally:
        await client.stop()

    if not result:
        return web.json_response(
            {"error": "originate failed — check agent log + ARI credentials"},
            status=502,
        )
    return web.json_response({
        "status": "calling",
        "phone": phone,
        "channel_id": result.get("id"),
        "state": result.get("state"),
        "message": f"Calling {phone} — pick up to hear the agent.",
    })


def _build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", _handle_index)
    app.router.add_get("/livekit.html", _handle_index)
    app.router.add_get("/api/health", _handle_health)
    app.router.add_post("/api/call-me", _handle_call_me)
    app.router.add_get("/static/{filename:.*}", _handle_static)
    return app


async def _start_admin_server(stop_event: asyncio.Event) -> None:
    """Run the admin HTTP server until stop_event fires."""
    if not settings.telephony_admin_enabled:
        logger.info("Admin HTTP disabled (TELEPHONY_ADMIN_ENABLED=false)")
        return
    runner = web.AppRunner(_build_app())
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=settings.telephony_admin_host,
        port=settings.telephony_admin_port,
    )
    await site.start()
    logger.info(
        "Admin HTTP listening on http://%s:%s  (open in browser for 'Gọi cho tôi')",
        settings.telephony_admin_host, settings.telephony_admin_port,
    )
    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()


# ── Main ────────────────────────────────────────────────────────────────────

async def main() -> int:
    if not settings.telephony_enabled:
        print("TELEPHONY_ENABLED=false — set it to true in .env first",
              file=sys.stderr)
        return 1

    manager = TelephonyManager()
    await manager.start()
    logger.info(
        "Telephony running  — AudioSocket :%s, ARI %s  (Ctrl-C to stop)",
        settings.audiosocket_port, settings.asterisk_host,
    )

    stop_event = asyncio.Event()

    def _shutdown(*_):
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _shutdown)

    admin_task = asyncio.ensure_future(_start_admin_server(stop_event))
    try:
        await stop_event.wait()
    finally:
        admin_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await admin_task
        await manager.stop()
        logger.info("Telephony stopped cleanly")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
