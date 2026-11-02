"""Terminal REPL for the agent — the real brain, no browser, no audio.

Drives `NobleAgent.stream_response`, the same entrypoint the chat and voice
transports use, so what you see here is what a caller gets: same system prompt, same
tool dispatch, same Redis-backed state across turns.

What it shows that `/chat` does not: every tool call with its arguments and the raw
result string the LLM received, plus TTFT / total latency. That is usually what you
actually want when a reply looks wrong — whether the tool was called at all, what it
was asked, and what came back.

Usage:
    python scripts/chat_repl.py                       # new session
    python scripts/chat_repl.py --session <id>        # resume a session
    python scripts/chat_repl.py -t <tenant_id>        # simulate a request for a tenant
    python scripts/chat_repl.py --raw                 # full tool results, no truncation
    python scripts/chat_repl.py --ask "câu hỏi"       # one-shot, then exit

Commands inside the REPL:
    /quit /exit      thoát
    /reset           xoá history của session
    /customer        xem Customer hiện tại
    /set k=v ...     đặt field Customer (vd: /set phone=0912345678 name=Hải)
    /tools           liệt kê tool đang được offer cho LLM
    /raw             bật/tắt in đầy đủ tool result
    /last            in lại tool result đầy đủ của lượt vừa rồi

Needs what the agent needs: Redis, an LLM key, and — for kb_search/send_media —
QDRANT_URL + EMBED_SERVICE_URL reachable (docs/handoff/qdrant-access.md).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _load_dotenv() -> None:
    """Read .env like the agent entrypoint does (importing config alone doesn't)."""
    env = _ROOT / ".env"
    if not env.is_file():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.split(" #")[0].strip())


_load_dotenv()

from noble_agent.agent.facade import NobleAgent  # noqa: E402
from noble_agent.config import get_settings  # noqa: E402

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
CYAN, GREEN, YELLOW, RED = "\033[36m", "\033[32m", "\033[33m", "\033[31m"

_TRUNC = 600


def _short(s: str, limit: int = _TRUNC) -> str:
    s = s or ""
    return s if len(s) <= limit else s[:limit] + f"{DIM}… (+{len(s) - limit} ký tự, /raw để xem đủ){RESET}"


class Turn:
    """Collects one turn's callback stream so it can be printed as a trace."""

    def __init__(self, raw: bool) -> None:
        self.raw = raw
        self.calls: list[dict] = []
        self.first_token_at: float | None = None
        self.started = time.perf_counter()

    def on_token(self, token: str) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.perf_counter()
            print(f"{GREEN}Luna:{RESET} ", end="", flush=True)
        print(token, end="", flush=True)

    def on_tool_start(self, name: str, args: dict) -> None:
        self.calls.append({"name": name, "args": dict(args or {}), "result": None, "t": time.perf_counter()})
        print(f"\n{CYAN}  ▸ {name}{RESET}({_short(json.dumps(args or {}, ensure_ascii=False), 240)})", flush=True)

    def on_tool_done(self, name: str, result: str) -> None:
        ms = None
        for rec in reversed(self.calls):
            if rec["name"] == name and rec["result"] is None:
                rec["result"] = result or ""
                ms = rec["ms"] = (time.perf_counter() - rec["t"]) * 1000
                break
        body = result or ""
        shown = body if self.raw else _short(body)
        stamp = f" {DIM}{ms:.0f}ms{RESET}" if ms else ""
        # An empty result is the silent-degrade signature — flag it rather than
        # printing a blank line that reads like success.
        marker = f"{YELLOW}∅{RESET}" if not body.strip() else "←"
        print(f"{CYAN}  {marker} {name}{RESET}{stamp} {DIM}{shown}{RESET}", flush=True)

    def summary(self) -> str:
        ttft = f"{(self.first_token_at - self.started) * 1000:.0f}ms" if self.first_token_at else "—"
        parts = [f"TTFT {ttft}", f"total {(time.perf_counter() - self.started) * 1000:.0f}ms"]
        if self.calls:
            parts.append(f"{len(self.calls)} tool: " + ", ".join(c["name"] for c in self.calls))
        empty = [c["name"] for c in self.calls if not (c["result"] or "").strip()]
        if empty:
            parts.append(f"{YELLOW}rỗng: {', '.join(empty)}{RESET}")
        return " · ".join(parts)


def banner(s, session_id: str, tenant: str) -> None:
    warn = "" if (s.qdrant_url and s.embed_service_url) else f"   {RED}← kb_search/send_media sẽ rỗng{RESET}"
    print(f"{BOLD}Noble agent REPL{RESET}  {DIM}(Ctrl-D hoặc /quit để thoát){RESET}")
    print(f"{DIM}  session   {session_id}")
    print(f"  tenant    {tenant}")
    print(f"  model     {s.agent_model or '(chain mặc định)'}")
    print(f"  rag       NOBLE_RAG_BACKEND={s.noble_rag_backend}")
    print(f"  qdrant    {s.qdrant_url or '(unset)'}{warn}")
    print(f"  embed     {s.embed_service_url or '(unset)'}{RESET}\n")


async def ask(agent: NobleAgent, text: str, raw: bool) -> Turn:
    t = Turn(raw)
    try:
        reply = await agent.stream_response(
            user_text=text,
            on_token=t.on_token,
            on_tool_start=t.on_tool_start,
            on_tool_done=t.on_tool_done,
        )
        if t.first_token_at is None:  # nothing streamed — show the final reply
            print(f"{GREEN}Luna:{RESET} {reply or f'{YELLOW}(rỗng){RESET}'}", end="")
    except Exception as exc:
        print(f"\n{RED}✗ lượt lỗi: {type(exc).__name__}: {exc}{RESET}", end="")
    print(f"\n{DIM}  {t.summary()}{RESET}\n")
    return t


async def handle_command(agent: NobleAgent, line: str, state: dict) -> bool:
    """False → exit the REPL."""
    cmd, _, rest = line[1:].partition(" ")
    cmd, rest = cmd.strip().lower(), rest.strip()

    if cmd in ("quit", "exit", "q"):
        return False
    if cmd == "reset":
        await agent.reset()
        print(f"{DIM}history đã xoá{RESET}\n")
    elif cmd == "customer":
        print(json.dumps(await agent.get_customer(), ensure_ascii=False, indent=2) + "\n")
    elif cmd == "set":
        fields = {}
        for pair in rest.split():
            k, sep, v = pair.partition("=")
            if sep:
                fields[k.strip()] = v.strip()
        if not fields:
            print(f"{DIM}dùng: /set phone=0912345678 name=Hải{RESET}\n")
        else:
            print(json.dumps(await agent.set_customer_fields(fields), ensure_ascii=False, indent=2) + "\n")
    elif cmd == "tools":
        names = list(getattr(agent._runner._agent, "tool_names", ()) or ())
        print(f"{DIM}{len(names)} tool: {', '.join(names)}{RESET}\n")
    elif cmd == "raw":
        state["raw"] = not state["raw"]
        print(f"{DIM}raw = {state['raw']}{RESET}\n")
    elif cmd == "last":
        last = state.get("last")
        if not last or not last.calls:
            print(f"{DIM}lượt vừa rồi không gọi tool nào{RESET}\n")
        else:
            for c in last.calls:
                print(f"{CYAN}{c['name']}{RESET}({json.dumps(c['args'], ensure_ascii=False)})")
                print((c["result"] or "(rỗng)") + "\n")
    else:
        print(f"{DIM}lệnh lạ: /{cmd} — xem docstring đầu file{RESET}\n")
    return True


async def main() -> int:
    p = argparse.ArgumentParser(description="Terminal REPL cho agent (brain thật, không audio)")
    p.add_argument("--session", default="", help="session_id để resume (mặc định: tạo mới)")
    p.add_argument("-t", "--tenant", default="", help="tenant_id — mô phỏng transport truyền tenant vào request")
    p.add_argument("--channel", choices=("chat", "voice"), default="chat",
                   help="persona channel — 'voice' để test persona thoại từ terminal (mặc định: chat)")
    p.add_argument("--raw", action="store_true", help="in đầy đủ tool result")
    p.add_argument("--ask", default="", help="hỏi 1 câu rồi thoát")
    args = p.parse_args()

    s = get_settings()
    session_id = args.session or f"repl-{uuid.uuid4().hex[:8]}"

    try:
        agent = await NobleAgent.create(session_id=session_id, tenant_id=args.tenant or None, channel=args.channel)
    except Exception as exc:
        print(f"{RED}✗ không khởi tạo được agent: {type(exc).__name__}: {exc}{RESET}")
        print(f"{DIM}  Redis chạy chưa? LLM key set chưa? (REDIS_URL / *_API_KEY trong .env){RESET}")
        return 2

    banner(s, session_id, args.tenant or s.tenant_id)
    state: dict = {"raw": args.raw, "last": None}

    if args.ask:
        await ask(agent, args.ask, state["raw"])
        return 0

    while True:
        try:
            # to_thread chứ KHÔNG input() trần: input() chặn event loop, nên task
            # nền (summary của escalate) không chạy được cho tới lượt hỏi sau —
            # REPL sẽ báo "chưa có tóm tắt" trong khi production đã ghi xong.
            line = (await asyncio.to_thread(input, f"{BOLD}bạn>{RESET} ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if not await handle_command(agent, line, state):
                break
            continue
        state["last"] = await ask(agent, line, state["raw"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
