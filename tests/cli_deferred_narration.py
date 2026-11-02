"""Interactive CLI to feel out the deferred-narration pattern end-to-end.

What this is: a REPL that simulates the production voice flow WITHOUT touching
src/. Each turn shows you, in real time, every event Phương án A would emit:

    [USER]      what you typed
    [LLM-1 turn-1]   filler text + tool_call detected
    [TOOL]      send_media dispatched, backend fired async
    [LLM-1 turn-2]   compliance check — did the model stay silent on deferred?
    [BACKEND]   async HTTP simulator: which RTT, retry, ok/fail/channel
    [INJECT]    narration that the production code would push into tts_queue
    [TTS-PLAYBACK] simulated speak order: filler → injected narration

You can configure the fake backend's behavior at the prompt to stress-test
each failure mode (success / sms / failed once retry success / hard fail /
slow / timeout). Useful for catching cases where the LLM ignores the
`deferred: true` flag, or where retry logic produces double-narration, etc.

Run:
    python tests/cli_deferred_narration.py
    python tests/cli_deferred_narration.py --provider openai --variant v5_strong_imperative

Type a real customer-style ask, e.g.:
    "Anh xin cho em xem brochure NCLB nha em"
    "Cho mình xem map quy hoạch dự án Tây Hồ"
    "Bản vẽ mặt bằng căn 2PN gửi qua app cho mình"

Then type one of these to set the next backend simulation:
    /backend success_noblex   — ok=true, channel=noblex (default)
    /backend success_sms      — ok=true, channel=sms
    /backend retry_then_ok    — fail once, retry, then ok
    /backend hard_fail        — ok=false, fallback_narration
    /backend slow             — 800ms delay (stress filler timing)
    /backend timeout          — 3s, then fallback
    /variant v5_strong_imperative   — switch deferred-instruction phrasing
    /reset                          — clear conversation
    /quit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Auto-load .env (no src/ dep)
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.is_file():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

try:
    from openai import AsyncOpenAI
except ImportError:
    print("openai package missing — pip install openai")
    sys.exit(1)


# ─── ANSI colors (mirror bench_llm.C minimal subset) ────────────────────


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GRAY = "\033[37m"


def _ts() -> str:
    """Wallclock ms since CLI start, padded for column alignment."""
    return f"{(time.monotonic() - _T0) * 1000:>7.0f}ms"


def _log(tag: str, color: str, msg: str) -> None:
    print(f"  {C.DIM}{_ts()}{C.RESET}  {color}[{tag:<14s}]{C.RESET} {msg}")


_T0 = time.monotonic()


# ─── Provider catalog (subset of bench_llm._env_providers) ──────────────


def _build_providers() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if os.environ.get("OPENAI_API_KEY"):
        out["openai"] = {
            "client": AsyncOpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                base_url=os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
                timeout=30,
            ),
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        }
    if os.environ.get("GEMINI_API_KEY"):
        out["gemini"] = {
            "client": AsyncOpenAI(
                api_key=os.environ["GEMINI_API_KEY"],
                base_url=os.environ.get("GEMINI_BASE_URL")
                or "https://generativelanguage.googleapis.com/v1beta/openai/",
                timeout=30,
            ),
            "model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        }
    if os.environ.get("DASHSCOPE_API_KEY"):
        out["qwen"] = {
            "client": AsyncOpenAI(
                api_key=os.environ["DASHSCOPE_API_KEY"],
                base_url=os.environ.get("DASHSCOPE_BASE_URL")
                or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                timeout=30,
            ),
            "model": os.environ.get("DASHSCOPE_MODEL", "qwen-plus"),
        }
    return out


def _token_limit_key(model: str) -> str:
    if any(model.startswith(p) for p in ("gpt-5", "o1", "o3")):
        return "max_completion_tokens"
    return "max_tokens"


# ─── Tool spec + system prompt (same as bench) ──────────────────────────

SEND_VIA_APP_TOOL = {
    "type": "function",
    "function": {
        "name": "send_media",
        "description": (
            "Gửi tài liệu (ảnh, brochure, bản vẽ, map quy hoạch) tới khách qua "
            "app NobleX hoặc SMS. Backend tự RAG content + chọn channel + push."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Câu hỏi / yêu cầu của khách"},
                "project_code": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Mã dự án (NCLB, NCTH, NPLB, NTTL, SSLC)",
                },
            },
            "required": ["query"],
        },
    },
}


DEFERRED_VARIANTS = {
    "v1_minimal_flag": (
        "Sau khi tool return: nếu tool result có field `deferred: true`, "
        "DỪNG ngay, KHÔNG output thêm text. Backend sẽ tự đọc câu xác nhận."
    ),
    "v2_explicit_rule": (
        "Sau khi tool return:\n"
        "- Nếu result.deferred == true → KHÔNG output thêm text. Kết thúc lượt.\n"
        "- Nếu result.deferred == false (hoặc thiếu) → output câu confirm theo channel."
    ),
    "v5_strong_imperative": (
        "RULE: nếu tool result có `deferred: true`, output của bạn PHẢI là chuỗi rỗng. "
        "TUYỆT ĐỐI KHÔNG nói gì thêm. Backend đã được scheduled để gửi câu confirm."
    ),
}


def _build_system_prompt(variant: str) -> str:
    return (
        "Bạn là Luna, trợ lý voice của Noble Real Estate. "
        "Trả lời ngắn gọn, tự nhiên kiểu nói chuyện điện thoại — "
        "KHÔNG markdown, KHÔNG bullet.\n\n"
        "Khách quan tâm: dự án Noble Crystal Long Biên (NCLB).\n\n"
        "QUAN TRỌNG về tool send_media:\n"
        "- Khách xin ảnh, brochure, bản vẽ, map → GỌI send_media NGAY.\n"
        "- LUÔN output text FILLER CÙNG LÚC khi gọi tool: "
        '"Dạ em gửi cho anh/chị nha, chờ em chút ạ."\n'
        "- Filler là câu duy nhất bạn nói TRƯỚC khi tool return. "
        "KHÔNG mô tả tài liệu bằng lời.\n\n"
        "Sau khi tool return — đọc kết quả và phản hồi theo channel:\n"
        '- channel == "noblex" → nói: "Em đã gửi qua ứng dụng NobleX rồi ạ."\n'
        '- channel == "sms"    → nói: "Em đã gửi qua tin nhắn điện thoại rồi ạ."\n'
        "- ok == false → đọc nguyên văn fallback_narration trong kết quả.\n\n"
        f"{DEFERRED_VARIANTS[variant]}\n"
    )


# ─── Fake backend simulator ─────────────────────────────────────────────
#
# Mirrors the production hotline_outreach_service.py contract: takes (phone,
# query, project_codes), returns OutreachResult-shaped dict. Configurable
# per next-call so each failure mode can be exercised on demand.


@dataclass
class BackendScenario:
    name: str
    latency_ms: tuple[int, int]  # min, max for uniform random
    ok: bool
    channel: str = "noblex"  # ignored if ok=False
    retry_count: int = 0  # how many failed attempts before success
    raise_timeout: bool = False  # simulate full timeout


SCENARIOS: dict[str, BackendScenario] = {
    "success_noblex": BackendScenario("success_noblex", (80, 200), True, "noblex"),
    "success_sms": BackendScenario("success_sms", (80, 200), True, "sms"),
    "retry_then_ok": BackendScenario("retry_then_ok", (80, 200), True, "noblex", retry_count=1),
    "hard_fail": BackendScenario("hard_fail", (60, 150), False),
    "slow": BackendScenario("slow", (700, 1100), True, "noblex"),
    "timeout": BackendScenario("timeout", (3000, 3000), False, raise_timeout=True),
}


async def _fake_backend(scenario: BackendScenario, query: str) -> dict:
    """Simulate the backend HTTP /chat/async endpoint.

    Logs every attempt + final outcome in the exact format prod code would
    write to its own logger so tail latency + retry behavior is visible.
    """
    attempts = 0
    backoff_base = 0.5

    while attempts <= scenario.retry_count:
        attempts += 1
        rtt = random.uniform(*scenario.latency_ms) / 1000
        if scenario.raise_timeout:
            _log("BACKEND", C.RED, f"attempt {attempts} → timeout {rtt * 1000:.0f}ms")
            await asyncio.sleep(rtt)
            return {
                "ok": False,
                "code": "timeout",
                "fallback_narration": "Dạ hệ thống đang quá tải, anh/chị check lại app trong vài phút giúp em nha.",
                "attempts": attempts,
            }

        is_final_attempt = attempts > scenario.retry_count
        if attempts <= scenario.retry_count and not is_final_attempt:
            # Forced fail this attempt
            _log("BACKEND", C.YELLOW, f"attempt {attempts} → simulated 5xx (will retry)")
            await asyncio.sleep(rtt)
            backoff = backoff_base * (2 ** (attempts - 1))
            _log("BACKEND", C.GRAY, f"  backoff {backoff * 1000:.0f}ms before retry")
            await asyncio.sleep(backoff)
            continue

        # Final attempt
        _log("BACKEND", C.CYAN, f"attempt {attempts} → HTTP roundtrip {rtt * 1000:.0f}ms")
        await asyncio.sleep(rtt)
        if scenario.ok:
            return {
                "ok": True,
                "channel": scenario.channel,
                "trace_id": f"trace-{uuid.uuid4().hex[:8]}",
                "attempts": attempts,
            }
        return {
            "ok": False,
            "code": "http_4xx",
            "fallback_narration": (
                "Em xin lỗi, đang lỗi gửi tài liệu cho anh/chị, vui lòng thử lại sau ít phút giúp em ạ."
            ),
            "attempts": attempts,
        }

    # unreachable
    return {"ok": False, "code": "exhausted", "fallback_narration": "Lỗi không xác định ạ.", "attempts": attempts}


# ─── Result narration builder (this is what production code would do) ──


def _build_narration(result: dict) -> str:
    if result.get("ok"):
        ch = result.get("channel", "")
        return {
            "noblex": "Em đã gửi qua ứng dụng NobleX rồi ạ.",
            "sms": "Em đã gửi qua tin nhắn điện thoại rồi ạ.",
        }.get(ch, "Em đã gửi cho anh chị rồi ạ.")
    return result.get("fallback_narration") or (
        "Dạ em đang gặp lỗi gửi tài liệu, anh/chị vui lòng thử lại sau giúp em ạ."
    )


# ─── LLM streaming (collect content + tool_calls) ───────────────────────


async def _stream_once(client, model: str, messages: list[dict], use_tools: bool) -> tuple[str, list[dict], str]:
    tok_key = _token_limit_key(model)
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        tok_key: 300,
    }
    if use_tools:
        kwargs["tools"] = [SEND_VIA_APP_TOOL]

    text_parts: list[str] = []
    tool_call_parts: dict[int, dict] = {}

    try:
        stream = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=30)
        async for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            if delta and delta.content:
                text_parts.append(delta.content)
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    if idx not in tool_call_parts:
                        tool_call_parts[idx] = {"id": "", "name": "", "args": []}
                    if tc.id:
                        tool_call_parts[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_call_parts[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_call_parts[idx]["args"].append(tc.function.arguments)
    except Exception as exc:
        return "".join(text_parts), [], f"{type(exc).__name__}: {exc}"

    full_text = "".join(text_parts)
    calls = []
    for idx in sorted(tool_call_parts):
        tc = tool_call_parts[idx]
        calls.append(
            {
                "id": tc["id"] or f"call_{uuid.uuid4().hex[:12]}",
                "name": tc["name"],
                "args": "".join(tc["args"]),
            }
        )
    return full_text, calls, ""


# ─── REPL state ─────────────────────────────────────────────────────────


@dataclass
class ReplState:
    provider: str
    client: object
    model: str
    variant: str = "v5_strong_imperative"
    next_scenario: str = "success_noblex"
    history: list[dict] = field(default_factory=list)

    def reset_history(self) -> None:
        self.history = [{"role": "system", "content": _build_system_prompt(self.variant)}]


# ─── Per-turn driver — the meat of the simulation ───────────────────────


async def _process_turn(state: ReplState, user_text: str) -> None:
    state.history.append({"role": "user", "content": user_text})
    _log("USER", C.GREEN + C.BOLD, f'"{user_text}"')

    # Turn 1 — LLM emits filler + tool_call (or just direct text if no tool)
    t0 = time.monotonic()
    t1_text, t1_calls, err = await _stream_once(state.client, state.model, state.history, use_tools=True)
    t1_ms = (time.monotonic() - t0) * 1000

    if err:
        _log("LLM-1", C.RED, f"error: {err}")
        return

    if t1_text.strip():
        _log("LLM-1", C.BLUE, f'({t1_ms:.0f}ms) content: "{t1_text.strip()}"')
    if t1_calls:
        for tc in t1_calls:
            _log("LLM-1", C.MAGENTA, f"({t1_ms:.0f}ms) tool_call: {tc['name']}({tc['args']})")
    if not t1_text.strip() and not t1_calls:
        _log("LLM-1", C.YELLOW, "(empty turn-1 — no content, no tool)")
        return

    # No tool call → direct chat reply, append and stop
    if not t1_calls:
        state.history.append({"role": "assistant", "content": t1_text})
        return

    # Append assistant turn-1 message (the tool_call boundary)
    assistant_msg = {
        "role": "assistant",
        "content": t1_text or None,
        "tool_calls": [
            {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["args"] or "{}"}}
            for tc in t1_calls
        ],
    }
    state.history.append(assistant_msg)

    # Find send_media calls — these are the ones we defer
    deferred_calls = [tc for tc in t1_calls if tc["name"] == "send_media"]
    other_calls = [tc for tc in t1_calls if tc["name"] != "send_media"]

    # Other tools (none in this CLI) would synchronously execute here.
    for tc in other_calls:
        _log("TOOL", C.GRAY, f"non-deferred tool {tc['name']} — would run sync (not implemented in CLI)")
        state.history.append(
            {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps({"ok": True, "stub": True}),
            }
        )

    if not deferred_calls:
        return

    # Phương án A flow — for each send_media:
    #   1) feed LLM a placeholder so it knows tool was dispatched
    #   2) fire async backend call
    #   3) when backend done, simulate injecting narration into TTS queue
    backend_tasks: list[asyncio.Task] = []
    for tc in deferred_calls:
        try:
            args_obj = json.loads(tc["args"] or "{}")
        except Exception:
            args_obj = {}
        scenario = SCENARIOS[state.next_scenario]
        _log("DISPATCH", C.YELLOW, f"send_media deferred → fire async (scenario={scenario.name})")

        # Feed LLM the placeholder result IMMEDIATELY
        placeholder = {
            "ok": True,
            "deferred": True,
            "note": "backend will narrate when done",
        }
        state.history.append(
            {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(placeholder, ensure_ascii=False),
            }
        )

        # Fire async backend — task collects its result later. Bind scenario
        # + query as default args so the closure doesn't see a mutated late
        # iteration value, and pre-extract `query` outside the lambda to keep
        # ruff happy (B008 forbids function calls in defaults).
        scenario_for_task = scenario
        query_for_task = args_obj.get("query", "")

        async def _runner(scn=scenario_for_task, q=query_for_task):
            t_b = time.monotonic()
            res = await _fake_backend(scn, q)
            res["_runtime_ms"] = (time.monotonic() - t_b) * 1000
            return res

        backend_tasks.append(asyncio.create_task(_runner()))

    # Turn 2 — LLM reacts to placeholder. Should stay silent if v5 compliance.
    t1b = time.monotonic()
    t2_text, t2_calls, err = await _stream_once(state.client, state.model, state.history, use_tools=True)
    t2_ms = (time.monotonic() - t1b) * 1000
    if err:
        _log("LLM-2", C.RED, f"error: {err}")
    else:
        token_count = len(t2_text.split())
        if token_count <= 5:
            _log("LLM-2", C.GREEN, f"({t2_ms:.0f}ms) ✓ silent ({token_count} tokens) — compliance OK")
        else:
            _log("LLM-2", C.RED, f'({t2_ms:.0f}ms) ✗ NOT silent ({token_count} tokens): "{t2_text[:80]}"')
        if t2_text:
            # We must still record the assistant turn-2 to keep history consistent
            state.history.append({"role": "assistant", "content": t2_text})

    # Wait for backend tasks to complete and inject narration
    for task in backend_tasks:
        result = await task
        rt = result.pop("_runtime_ms", 0.0)
        ok = result.get("ok")
        attempts = result.get("attempts", 1)
        ch = result.get("channel", "")

        color = C.GREEN if ok else C.RED
        _log(
            "BACKEND-DONE",
            color,
            f"({rt:.0f}ms, attempts={attempts}) ok={ok} channel={ch or '-'}",
        )

        narration = _build_narration(result)
        _log("INJECT-TTS", C.CYAN + C.BOLD, f'"{narration}"')

    print()  # blank line between turns


# ─── REPL loop ──────────────────────────────────────────────────────────

WELCOME = """
{bold}{cyan}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{reset}
  {bold}Deferred Narration CLI — Phương án A simulator{reset}
{bold}{cyan}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{reset}

  Provider: {prov} / {model}
  Variant : {variant}
  Backend : {scenario}

  Commands:
    /backend <name>   — set next backend scenario
                          {scenarios}
    /variant <name>   — switch deferred-instruction phrasing
                          {variants}
    /reset            — clear conversation
    /quit             — exit

  Otherwise, type any customer-style ask:
    "Anh xin cho em xem brochure NCLB nha"
    "Cho mình xem map quy hoạch dự án Tây Hồ"
"""


async def _repl(state: ReplState):
    state.reset_history()
    print(
        WELCOME.format(
            bold=C.BOLD,
            cyan=C.CYAN,
            reset=C.RESET,
            prov=state.provider,
            model=state.model,
            variant=state.variant,
            scenario=state.next_scenario,
            scenarios=" / ".join(SCENARIOS),
            variants=" / ".join(DEFERRED_VARIANTS),
        )
    )

    loop = asyncio.get_event_loop()
    while True:
        try:
            text = await loop.run_in_executor(None, input, f"\n{C.BOLD}you ▸{C.RESET} ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        text = text.strip()
        if not text:
            continue

        if text.startswith("/"):
            parts = text[1:].split(maxsplit=1)
            cmd = parts[0]
            arg = parts[1].strip() if len(parts) > 1 else ""
            if cmd == "quit":
                return
            if cmd == "reset":
                state.reset_history()
                _log("STATE", C.GREEN, "history cleared")
                continue
            if cmd == "backend":
                if arg in SCENARIOS:
                    state.next_scenario = arg
                    _log("STATE", C.GREEN, f"next backend scenario = {arg}")
                else:
                    _log("STATE", C.RED, f"unknown scenario; valid: {list(SCENARIOS)}")
                continue
            if cmd == "variant":
                if arg in DEFERRED_VARIANTS:
                    state.variant = arg
                    state.reset_history()
                    _log("STATE", C.GREEN, f"variant = {arg} (history reset to apply new system prompt)")
                else:
                    _log("STATE", C.RED, f"unknown variant; valid: {list(DEFERRED_VARIANTS)}")
                continue
            _log("STATE", C.RED, f"unknown command /{cmd}")
            continue

        await _process_turn(state, text)


# ─── CLI ────────────────────────────────────────────────────────────────


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--provider", default=None, help="Provider key from .env (openai / gemini / qwen). Default = first available."
    )
    p.add_argument(
        "--variant",
        default="v5_strong_imperative",
        choices=list(DEFERRED_VARIANTS),
        help="Deferred-instruction phrasing variant.",
    )
    p.add_argument(
        "--scenario",
        default="success_noblex",
        choices=list(SCENARIOS),
        help="Initial backend scenario (changeable mid-session via /backend).",
    )
    args = p.parse_args()

    providers = _build_providers()
    if not providers:
        print("No provider configured. Set OPENAI_API_KEY / GEMINI_API_KEY / DASHSCOPE_API_KEY in .env")
        return 1

    if args.provider:
        if args.provider not in providers:
            print(f"Provider '{args.provider}' not configured. Available: {list(providers)}")
            return 1
        prov_name = args.provider
    else:
        prov_name = next(iter(providers))

    pcfg = providers[prov_name]
    state = ReplState(
        provider=prov_name,
        client=pcfg["client"],
        model=pcfg["model"],
        variant=args.variant,
        next_scenario=args.scenario,
    )

    await _repl(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
