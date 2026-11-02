"""WebSocket handler — signaling + JSON control messages + rate limiting."""

from __future__ import annotations

import asyncio
import collections
import hmac
import json
import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import websockets
import websockets.asyncio.server

from noble_agent.config import settings
from noble_agent.server.session import Session

logger = logging.getLogger("server")

# ── Rate limiting state ──────────────────────────────────────────────────────
_active_connections: int = 0
_connections_per_ip: dict[str, int] = collections.defaultdict(int)
_rate_lock = asyncio.Lock()


async def _acquire_connection(ip: str) -> bool:
    """Try to acquire a connection slot. Returns False if rate limited."""
    global _active_connections
    async with _rate_lock:
        if _active_connections >= settings.max_ws_connections:
            logger.warning("Rate limit: max connections (%d) reached, rejecting %s", settings.max_ws_connections, ip)
            return False
        if _connections_per_ip[ip] >= settings.max_ws_per_ip:
            logger.warning("Rate limit: max per-IP (%d) reached for %s", settings.max_ws_per_ip, ip)
            return False
        _active_connections += 1
        _connections_per_ip[ip] += 1
        return True


async def _release_connection(ip: str) -> None:
    global _active_connections
    async with _rate_lock:
        _active_connections = max(0, _active_connections - 1)
        _connections_per_ip[ip] = max(0, _connections_per_ip[ip] - 1)
        if _connections_per_ip[ip] == 0:
            del _connections_per_ip[ip]


def _get_client_ip(ws: websockets.asyncio.server.ServerConnection) -> str:
    try:
        return ws.remote_address[0] if ws.remote_address else "unknown"
    except Exception:
        return "unknown"


def _tenant_from_headers(headers) -> str | None:
    """Tenant the gateway injected via X-Tenant-Id (None when absent/blank)."""
    if not headers:
        return None
    val = (headers.get("X-Tenant-Id") or "").strip()
    return val or None


def _register_pg_credentials(headers, tenant_id, configured_secret: str) -> bool:
    """Đăng ký credential PG per-tenant do gateway forward (X-PG-Role/-Password/-Expires).
    CHỈ ingest khi `configured_secret` (GATEWAY_WORKER_SECRET) non-empty — secret rỗng
    nghĩa là _gateway_secret_ok mở cho bất kỳ ai chạm được worker, nên hop đó KHÔNG
    xác thực và không được tin để ghi đè credential per-tenant (poison registry).
    Thiếu/hỏng header nào, hoặc giá trị không phải string, → bỏ qua (worker fallback
    shared DSN) — không phải lỗi; voice + dev local không có các header này.
    X-PG-Deployment/X-PG-Kind KHÔNG còn đọc (Portal `0941`/`0919` bỏ cả hai) — gateway bản
    cũ vẫn gửi thì bỏ qua, không nổ
    chứ không từ chối."""
    if not configured_secret or not headers or not tenant_id:
        return False
    role = str(headers.get("X-PG-Role") or "").strip()
    password = str(headers.get("X-PG-Password") or "")
    raw_exp = str(headers.get("X-PG-Expires") or "").strip()
    if not role or not password or not raw_exp:
        return False
    try:
        expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    # Header `X-PG-Deployment`/`X-PG-Kind` đã bỏ cùng `0941`/`0919` — gateway không gửi
    # nữa và không ai đọc. Nhịp tim khoá theo `tenant_id`, credential chỉ cần role+mật khẩu.
    from noble_agent.storage import tenant_credentials

    tenant_credentials.register(tenant_id, role=role, password=password, expires_at=expires_at)
    return True


def _agent_key_from_headers(headers, configured_secret: str) -> str:
    """agent_key_id gateway forward qua X-Agent-Key-Id — định danh API key Portal
    đã auth ra connection này (không phải secret). Cùng gate với X-PG-*: secret
    rỗng nghĩa là hop không xác thực → không tin, tránh đóng dấu giả vào
    conversations. Thiếu/hỏng → rỗng (cột NULL), không phải lỗi."""
    if not configured_secret or not headers:
        return ""
    try:
        val = headers.get("X-Agent-Key-Id")
    except Exception:  # noqa: BLE001 — headers giả trong test/transport lạ → coi như không có
        return ""
    return val.strip() if isinstance(val, str) else ""


def _gateway_secret_ok(configured_secret: str, headers) -> bool:
    """When a gateway→worker shared secret is configured, require the incoming
    X-Gateway-Secret to match (constant-time). Empty configured secret → open."""
    if not configured_secret:
        return True
    provided = (headers.get("X-Gateway-Secret") or "") if headers else ""
    return hmac.compare_digest(provided, configured_secret)


# ── Handler ──────────────────────────────────────────────────────────────────


async def handler(ws: websockets.asyncio.server.ServerConnection):
    """Handle a single WebSocket connection lifecycle."""
    client_ip = _get_client_ip(ws)

    if not await _acquire_connection(client_ip):
        await ws.close(4029, "Rate limited")
        return

    try:
        await _handle_session(ws, client_ip)
    finally:
        await _release_connection(client_ip)


async def _handle_session(ws: websockets.asyncio.server.ServerConnection, client_ip: str):
    # Parse optional session_id from WS path (?session=xxx)
    try:
        raw_path = ws.request.path if hasattr(ws, "request") and ws.request else getattr(ws, "path", "/")
    except Exception:
        raw_path = "/"
    raw_path = raw_path or "/"
    qs = parse_qs(urlparse(raw_path).query)
    requested_session = qs.get("session", [None])[0]

    session_id = requested_session or uuid4().hex[:12]

    # Text-chat tester (/chat/ws) reuses the agent brain without STT/TTS/RTC.
    from noble_agent.server import text_chat

    if text_chat.is_chat_path(raw_path):
        hdrs = ws.request.headers if hasattr(ws, "request") and ws.request else {}
        if settings.chat_ws_require_token:
            from noble_agent.server.app_session import verify_connect_token

            token = qs.get("token", [None])[0]
            if not await verify_connect_token(session_id, token):
                logger.warning("[CHAT] unauthorized connect rejected (session=%s ip=%s)", session_id, client_ip)
                await ws.close(4401, "unauthorized")
                return
        if not _gateway_secret_ok(settings.gateway_worker_secret, hdrs):
            logger.warning("[CHAT] gateway secret mismatch rejected (session=%s ip=%s)", session_id, client_ip)
            await ws.close(4403, "gateway_secret_mismatch")
            return
        _register_pg_credentials(hdrs, _tenant_from_headers(hdrs), settings.gateway_worker_secret)
        # Per-connection (task riêng) nên contextvar tự chảy xuống toàn bộ phiên
        # chat + các fire_and_forget con — không cần reset khi connection đóng.
        akid = _agent_key_from_headers(hdrs, settings.gateway_worker_secret)
        if akid:
            from noble_agent.tenant.current import set_current_agent_key_id

            set_current_agent_key_id(akid)
        await text_chat.handle_text_session(ws, session_id, tenant_id=_tenant_from_headers(hdrs))
        return

    session = Session(ws, session_id=session_id)

    await session._send_json({"type": "session_id", "session_id": session_id})
    logger.info("WS connected, session=%s ip=%s", session_id, client_ip)

    # ── Greeting state ───────────────────────────────────────────────────
    greeted = False
    greet_task: asyncio.Task | None = None

    async def _do_greet():
        nonlocal greeted
        if greeted:
            return
        greeted = True
        try:
            await asyncio.wait_for(session.rtc_connected.wait(), timeout=5.0)
            await session.agent.greet(session_id)
        except asyncio.CancelledError:
            greeted = False
            raise
        except TimeoutError:
            logger.warning("[GREET] Skipped — RTC not connected within 5s")
        except Exception as exc:
            logger.warning("[GREET] Failed: %s", exc)

    try:
        await session.start()

        async for message in ws:
            if not isinstance(message, str):
                continue
            try:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "rtc_offer":
                    answer = await session.negotiate(
                        offer_sdp=data["sdp"],
                        offer_type=data.get("offer_type", "offer"),
                    )
                    await session._send_json(answer)
                    if not greeted and greet_task is None:
                        greet_task = asyncio.ensure_future(_do_greet())

                elif msg_type == "reset":
                    await session.agent.reset_conversation()
                    await session._send_json({"type": "reset_ok"})

                elif msg_type == "set_voice":
                    voice_id = str(data.get("voice_id", ""))
                    if voice_id:
                        session.agent.set_voice(voice_id)
                        await session._send_json({"type": "voice_ok", "voice_id": voice_id})

                elif msg_type == "list_voices":
                    voices = session.agent._tts.list_voices()
                    await session._send_json({"type": "voices", "voices": voices})

                elif msg_type == "set_customer":
                    if greet_task and not greet_task.done():
                        greet_task.cancel()
                        try:
                            await greet_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        greet_task = None

                    customer_data = {
                        k: v for k, v in data.items() if k in ("name", "full_name", "gender", "phone") and v
                    }
                    if customer_data:
                        # Unified: write through the same StateRepo the agent's
                        # prompt is built from. Legacy session_store has an
                        # incompatible schema (empty-string defaults vs. None /
                        # Literal["M","F"]) and would corrupt the next load.
                        try:
                            applied = await session.agent._llm.set_customer_fields(customer_data)
                            logger.info("[WS] Customer set: %s", applied)
                        except Exception as exc:
                            logger.warning("[WS] set_customer_fields failed: %s", exc)
                    await session._send_json({"type": "customer_ok", "customer": customer_data})

                    greet_task = asyncio.ensure_future(_do_greet())

                elif msg_type == "interrupt":
                    logger.warning("[WS] Received client 'interrupt' signal.")
                    if session._agent_task and not session._agent_task.done():
                        session.agent.interrupt()
                        session.audio_track.clear()
                    session.vad.set_idle()

            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosedOK:
        pass
    except websockets.exceptions.ConnectionClosedError:
        pass
    except Exception as exc:
        logger.error("Handler error: %s", exc, exc_info=True)
    finally:
        if greet_task and not greet_task.done():
            greet_task.cancel()
        await session.stop()
