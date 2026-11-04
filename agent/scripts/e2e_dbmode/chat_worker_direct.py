"""Provider-user chat request straight to the worker /chat (what the gateway
forwards): tenant travels in the X-Tenant-Id header. Exercises db-mode config
load (acme's published config) + per-tenant runner + chat heartbeat.
Run:  python chat_worker_direct.py "your question here"
"""
import asyncio
import json
import sys

import websockets

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "Chào em, bên mình đang mở bán những dự án nào ạ?"


async def main() -> None:
    async with websockets.connect(
        "ws://127.0.0.1:8766/chat", additional_headers={"X-Tenant-Id": "acme"}
    ) as ws:
        first = json.loads(await ws.recv())
        print("[session]", first)
        await ws.send(json.dumps({"type": "user_text", "text": QUESTION}))
        print(f"\nUSER> {QUESTION}\nACME> ", end="", flush=True)
        while True:
            ev = json.loads(await ws.recv())
            t = ev.get("type")
            if t == "token":
                print(ev["text"], end="", flush=True)
            elif t == "tool_start":
                print(f"\n  [tool {ev['tool']} args={ev.get('args')}]\n  ", end="", flush=True)
            elif t == "done":
                print("\n[done]")
                break
            elif t == "error":
                print("\n[error]", ev)
                break


asyncio.run(main())
