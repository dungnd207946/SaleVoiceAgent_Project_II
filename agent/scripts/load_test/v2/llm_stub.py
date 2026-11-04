"""Minimal OpenAI-compatible streaming chat endpoint for load-test LLM isolation.

Serves POST /v1/chat/completions with stream=true, emitting a canned Vietnamese
answer as chat.completion.chunk SSE deltas at ~--tps tokens/sec. Deterministic,
no external calls. Text-only (does not emit tool_calls)."""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from aiohttp import web

_TEXT = (
    "Dạ em xin phép trả lời câu hỏi của anh chị. Noble hiện có nhiều dự án căn hộ "
    "cao cấp với vị trí đẹp, tiện ích đầy đủ và chính sách thanh toán linh hoạt. "
    "Anh chị quan tâm tới dự án nào để em tư vấn chi tiết hơn ạ."
)
CANNED = _TEXT.split()


def _chunk(model: str, created: int, delta: dict, finish=None) -> str:
    payload = {
        "id": "stub", "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _handler(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    model = body.get("model", "stub")
    request.app["hits"] = request.app.get("hits", 0) + 1
    print(f"[stub] hit #{request.app['hits']} model={model} msgs={len(body.get('messages', []))}", flush=True)
    tps = request.app["tps"]
    created = int(time.time())
    resp = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
    await resp.prepare(request)
    await resp.write(_chunk(model, created, {"role": "assistant"}).encode())
    for i, w in enumerate(CANNED):
        await resp.write(_chunk(model, created, {"content": (w if i == 0 else " " + w)}).encode())
        await asyncio.sleep(1.0 / tps)
    await resp.write(_chunk(model, created, {}, finish="stop").encode())
    await resp.write(b"data: [DONE]\n\n")
    await resp.write_eof()
    return resp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--tps", type=float, default=50.0)
    args = ap.parse_args()
    app = web.Application()
    app["tps"] = args.tps
    app.router.add_post("/v1/chat/completions", _handler)
    web.run_app(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
