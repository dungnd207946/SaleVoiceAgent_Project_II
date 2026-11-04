"""Chat reverse-proxy: verify at the gateway, then pipe the provider WS to the
tenant worker's existing /chat handler. Identity is seeded by sending the
worker's own `set_customer` message first — so the worker's chat path needs no
change for slice #2."""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger("gateway")


def worker_chat_url(tenant_id: str, settings) -> str:
    """The shared worker chat WebSocket URL (tenant travels in the X-Tenant-Id
    header now, not the DNS). `tenant_id` kept for call-site compatibility."""
    return settings.worker_chat_internal_url_template


def proxy_headers(settings, tenant_id: str, credentials=None) -> dict:
    """Headers the gateway sends to the worker /chat: tenant + shared-secret (nếu có)
    + PG credential per-tenant (X-PG-*) để worker dựng pool bằng chính role tenant."""
    headers = {"X-Tenant-Id": tenant_id}
    if settings.gateway_worker_secret:
        headers["X-Gateway-Secret"] = settings.gateway_worker_secret
    if credentials is not None and getattr(credentials, "agent_key_id", ""):
        # Độc lập với PG credential: key không kèm role vẫn đóng dấu được conversations.
        headers["X-Agent-Key-Id"] = credentials.agent_key_id
    if credentials is not None and credentials.postgres_role and credentials.postgres_password:
        headers["X-PG-Role"] = credentials.postgres_role
        headers["X-PG-Password"] = credentials.postgres_password
        if credentials.expires_at is not None:
            headers["X-PG-Expires"] = credentials.expires_at.isoformat()
    return headers


def first_messages(identity: dict) -> list[str]:
    """Return the initial messages to send to the worker before relaying client traffic.

    If identity is non-empty, returns a single JSON-encoded set_customer message.
    Otherwise returns an empty list.
    """
    if not identity:
        return []
    return [
        json.dumps(
            {"type": "set_customer", "identity": identity}, ensure_ascii=False
        )
    ]


async def proxy_chat(
    client_ws, settings, tenant_id: str, identity: dict, credentials=None
) -> None:  # pragma: no cover
    """Bi-directional relay: connect to the worker's /chat, seed identity, relay traffic.

    This is an integration function that opens a WebSocket to the tenant worker,
    sends the initial set_customer message (if identity is non-empty), then
    relays all traffic bi-directionally.

    Args:
        client_ws: The client WebSocket connection from the gateway.
        settings: Configuration object with worker_chat_internal_url_template and gateway_worker_secret.
        tenant_id: The tenant ID to pass to worker_chat_url.
        identity: Identity dict to seed via set_customer; passed as-is under the "identity" key.
        credentials: RuntimeCredentials from gateway auth; forwarded to the worker as
            X-PG-* headers so it can register a per-tenant PG credential.
    """
    import websockets

    url = worker_chat_url(tenant_id, settings)
    headers = proxy_headers(settings, tenant_id, credentials=credentials)

    async with websockets.connect(url, additional_headers=headers) as worker_ws:
        # Send initial messages (set_customer if identity is non-empty)
        for msg in first_messages(identity):
            await worker_ws.send(msg)

        # Bi-directional relay
        async def c2w():
            """Relay messages from client to worker."""
            async for m in client_ws:
                await worker_ws.send(m)

        async def w2c():
            """Relay messages from worker to client."""
            async for m in worker_ws:
                await client_ws.send(m)

        # Either leg ending must tear down BOTH: the worker only persists the
        # conversation in its on-close finally, so waiting for both directions
        # (gather) left the worker /chat socket open forever after the provider
        # disconnected — the session never ended and nothing was persisted.
        tasks = {
            asyncio.create_task(c2w(), name="client_to_worker"),
            asyncio.create_task(w2c(), name="worker_to_client"),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            if not t.cancelled() and t.exception() is not None:
                logger.warning("proxy_chat relay failed (%s): %s", t.get_name(), t.exception())
