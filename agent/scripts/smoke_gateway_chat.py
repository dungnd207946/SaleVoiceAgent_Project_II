#!/usr/bin/env python3
"""SaaS slice #2 — gateway CHAT smoke client (provider → gateway → worker /chat).

Verified working live 2026-07-30. Drives the exact path a provider backend uses:
open a WS to the per-tenant gateway endpoint with a Bearer credential, send an
identity handshake (which the gateway turns into the worker's `set_customer`),
then a user turn, and print the streamed reply.

Single-domain auth (2026-08-10): tenant no longer lives in the Host/subdomain —
the gateway resolves it from the Bearer API key via the Portal
runtime-credentials API (GATEWAY_CREDENTIALS_API_URL).

Prereqs:
  1. A provider API key issued by the Portal for the tenant under test.
  2. Worker (aiortc, serves /chat on :8766), writable materialize dir:
       mkdir -p "$HOME/.cache/noble/tenants"
       TENANT_MATERIALIZE_DIR="$HOME/.cache/noble/tenants" scripts/run.sh --no-reload
  3. Gateway:
       GATEWAY_CREDENTIALS_API_URL=http://<portal>/api/v1/agent/runtime-credentials \
       WORKER_CHAT_INTERNAL_URL_TEMPLATE='ws://127.0.0.1:8766/chat?session=smoke-{tenant_id}' \
       noble-gateway

Usage:
  python scripts/smoke_gateway_chat.py <credential> [--reject]
    <credential>  the provider API key from the Portal
    --reject      send a BAD credential and expect the gateway to close 4001
"""
import asyncio
import json
import sys

import websockets


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    reject = "--reject" in sys.argv
    if not args:
        print("usage: python scripts/smoke_gateway_chat.py <credential> [--reject]")
        return 2
    cred = args[0]
    if reject:
        cred = "tnt_THIS_IS_A_BOGUS_CREDENTIAL_000000000000"

    uri = "ws://localhost:9200/v1/chat"
    headers = {"Authorization": f"Bearer {cred}"}
    print(f"→ connecting {uri}  (Bearer {cred[:12]}…, tenant resolved server-side from the credential)")

    try:
        async with websockets.connect(uri, additional_headers=headers, open_timeout=10) as ws:
            if reject:
                # The gateway closes with 4001 AFTER the WS handshake (101) completes,
                # so connect() succeeds first; force a recv() to observe the close frame
                # (it surfaces as ConnectionClosed, handled below).
                await ws.recv()
                print("✗ UNEXPECTED: stayed open with a bogus credential (should have closed 4001)")
                return 1
            await ws.send(json.dumps({"identity": {"full_name": "Provider Test", "phone": "0912345629"},
                                      "call_id": "smoke-1"}))
            await ws.send(json.dumps({"type": "user_text", "text": "Chào em, cho anh hỏi dự án nào đang mở bán?"}))

            got_token = False
            async for raw in ws:
                if not isinstance(raw, str):
                    print(f"   [binary {len(raw)}B]")
                    continue
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "token":
                    got_token = True
                    print(msg["text"], end="", flush=True)
                elif t == "session_id":
                    print(f"   [session_id={msg.get('session_id')}]")
                elif t == "customer_ok":
                    print(f"   [customer_ok: {msg.get('customer')}]")
                elif t == "tool_start":
                    print(f"\n   [tool_start {msg.get('tool')} args={msg.get('args')}]")
                elif t == "tool_done":
                    print(f"   [tool_done {msg.get('tool')}]")
                elif t == "done":
                    print(f"\n   [done ttft={msg.get('ttft_ms')}ms tokens={msg.get('tokens')}]")
                    break
                elif t == "error":
                    print(f"\n   [error: {msg.get('message')}]")
                    break
                else:
                    print(f"   [{t}] {msg}")
            print(f"\n✓ chat roundtrip {'OK (got tokens)' if got_token else 'completed (no tokens?)'}")
            return 0 if got_token else 1
    except websockets.exceptions.ConnectionClosed as e:
        code = e.rcvd.code if e.rcvd else "?"
        reason = e.rcvd.reason if e.rcvd else ""
        if reject:
            if code == 4001:
                print(f"✓ REJECTED as expected: close {code} ({reason})")
                return 0
            print(f"✗ closed {code} ({reason}) — expected 4001")
            return 1
        print(f"✗ connection closed {code} ({reason})")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
