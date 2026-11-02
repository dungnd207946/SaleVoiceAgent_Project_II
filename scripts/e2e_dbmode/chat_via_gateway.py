"""FULL provider ingress: provider user → gateway (/v1/chat) → worker.
Exercises the single-domain gateway auth (gateway POSTs the Bearer API key to
GATEWAY_CREDENTIALS_API_URL, gets back tenant_id + per-tenant PG role/password)
then the reverse-proxy to the worker.

Host is now meaningless to the gateway — tenant comes entirely from the API
key via the runtime-credentials API, not from a Host subdomain. Kept as
noble-saas.lvh.me (public wildcard → 127.0.0.1, no /etc/hosts needed) to
reflect the shared single domain every tenant now connects through.
Run:  python chat_via_gateway.py "your question here"
"""
import asyncio
import json
import ssl
import sys
import random
import websockets

# Test script hitting prod whose TLS cert doesn't cover this subdomain yet.
# Skip cert verification for this manual e2e only — do NOT copy into app code.
_INSECURE_SSL = ssl.create_default_context()
_INSECURE_SSL.check_hostname = False
_INSECURE_SSL.verify_mode = ssl.CERT_NONE

TOKEN = "ody_ag_3xmbzbUfySxdrug0xNRORRg8Kosw5rMWIC2d5W1DwC4"  # matches control.agent_keys seed
QUESTION = sys.argv[1] if len(sys.argv) > 1 else "Chào em, dự án nào đang mở bán ạ?"
numb = random.randint(100,999)

async def main() -> None:
    async with websockets.connect(
        "ws://localhost:9201/v1/chat",
        additional_headers={"Authorization": "Bearer " + TOKEN},
        # ssl=_INSECURE_SSL,
    ) as ws:
        # 1) gateway handshake frame: identity (seeds set_customer) + call_id
        await ws.send(json.dumps({"identity": {"name": "Anh Duy", "phone": f"0912010{numb}"}, "call_id": "c1"}))
        # 2) wait for worker session_id (relayed through the proxy), then ask
        asked = False
        print("ACME> ", end="", flush=True)
        while True:
            ev = json.loads(await ws.recv())
            t = ev.get("type")
            if t == "session_id" and not asked:
                asked = True
                await ws.send(json.dumps({"type": "user_text", "text": QUESTION}))
                print(f"\nUSER> {QUESTION}\nACME> ", end="", flush=True)
            elif t == "token":
                print(ev["text"], end="", flush=True)
            elif t == "tool_start":
                print(f"\n  [tool {ev['tool']}]\n  ", end="", flush=True)
            elif t == "done":
                print("\n[done]")
                break
            elif t == "error":
                print("\n[error]", ev)
                break


asyncio.run(main())
