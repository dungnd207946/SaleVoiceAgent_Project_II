"""LLM behavior probe — does the model COMPLY with `deferred` instruction?

Standalone test, NO src/ changes. Validates the assumption behind the
"backend-injected narration" pattern (Phương án A) before we commit to
implementing it. Specifically answers 3 questions:

  1. **Filler concurrent with tool_call** — when the system prompt instructs
     the model to emit a filler text alongside `send_media`, does the
     stream actually contain BOTH `delta.content` AND `delta.tool_calls`?
     If not, "fire-and-narrate" pattern breaks regardless of what the tool
     returns.

  2. **Deferred compliance** — when the tool result contains a `deferred=true`
     flag with a "do not add text" instruction, does the model in turn-2 stay
     SILENT (zero or near-zero content tokens)? If model ignores the flag and
     keeps narrating, the backend-injected narration will collide with LLM
     output — UX fail.

  3. **Sync control (sanity)** — same flow but tool returns `{ok:true, channel:"noblex"}`
     WITHOUT `deferred`. Model SHOULD emit a confirm sentence ("Em đã gửi qua app
     NobleX..."). If turn-2 is empty here too, the model is just generally lazy
     and "deferred compliance" was a false positive.

Pass criteria for going ahead with Phương án A:
  - filler   ≥ 80% (model emits filler concurrent with tool_call)
  - deferred ≥ 80% (model stays silent in turn-2)
  - sync     ≥ 80% (model speaks in turn-2 when no deferred flag)

Run:
    python tests/bench_deferred_narration.py
    python tests/bench_deferred_narration.py --runs 10 --providers openai,gemini

The script reads .env for provider keys (OPENAI_API_KEY, GEMINI_API_KEY,
DASHSCOPE_API_KEY, OPENROUTER_API_KEY). No tool execution or src/ imports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Load .env (no src/ dependency — direct file parse)
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


# ─── Provider catalog (mimic bench_llm._env_providers, scoped) ──────────


def _build_providers() -> dict[str, dict]:
    """Pull only providers actually configured in .env."""
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
    if os.environ.get("OPENROUTER_API_KEY"):
        out["openrouter"] = {
            "client": AsyncOpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
                timeout=30,
            ),
            "model": os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku"),
        }
    return out


# ─── Tool def (single tool — send_media only, keep it minimal) ────────

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
                "query": {
                    "type": "string",
                    "description": "Câu hỏi / yêu cầu của khách",
                },
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


# ─── System prompt template (mimic SOUL.md + TOOL.md essentials) ────────

SYSTEM_PROMPT_BASE = (
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
    "{deferred_instruction}\n"
)

# Variants of the deferred instruction we want to test compliance against
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
    "v3_delegation": (
        "Sau khi tool return: nếu result chứa `deferred: true` thì backend đang "
        "đảm nhiệm việc thông báo cho khách — bạn KHÔNG cần nói gì thêm. "
        "Trả lời rỗng (empty content)."
    ),
    "v4_status_based": (
        "Tool send_media có 2 mode:\n"
        "  - status='queued' (deferred): backend sẽ tự push narration. KHÔNG thêm text.\n"
        "  - status='success' (sync): output câu confirm theo channel."
    ),
    "v5_strong_imperative": (
        "RULE: nếu tool result có `deferred: true`, output của bạn PHẢI là chuỗi rỗng. "
        "TUYỆT ĐỐI KHÔNG nói gì thêm. Backend đã được scheduled để gửi câu confirm."
    ),
}


# ─── Mock tool results — what we feed back to LLM in turn-2 ─────────────

DEFERRED_RESULT = {
    "ok": True,
    "deferred": True,
    "note": "Backend will narrate. Do not output additional text.",
}

DEFERRED_RESULT_VI = {
    "ok": True,
    "deferred": True,
    "note": "Backend sẽ tự đọc câu xác nhận. KHÔNG output thêm text.",
}

SYNC_RESULT_NOBLEX = {
    "ok": True,
    "channel": "noblex",
    "trace_id": "test-trace-123",
}


# ─── Result tracking ────────────────────────────────────────────────────


@dataclass
class Probe:
    provider: str
    model: str
    variant: str  # which deferred phrasing
    phase: str  # "filler" | "deferred" | "sync"
    run_idx: int
    # turn-1 (with user message)
    t1_text: str = ""
    t1_tool_called: str = ""
    t1_filler_concurrent: bool = False
    # turn-2 (after tool result fed back)
    t2_text: str = ""
    t2_token_count: int = 0
    error: str = ""

    def passed(self) -> bool:
        if self.error:
            return False
        if self.phase == "filler":
            return self.t1_filler_concurrent and self.t1_tool_called == "send_media"
        if self.phase == "deferred":
            # "Silent" = ≤ 5 tokens (allows model to add a tiny "Ok ạ" at most)
            return self.t2_token_count <= 5
        if self.phase == "sync":
            # Should have a real confirm
            return self.t2_token_count >= 5 and any(
                kw in self.t2_text.lower() for kw in ("đã gửi", "gửi rồi", "noblex", "app")
            )
        return False


@dataclass
class Aggregate:
    provider: str
    model: str
    variant: str
    counts: dict[str, list[bool]] = field(default_factory=lambda: {"filler": [], "deferred": [], "sync": []})

    def add(self, p: Probe) -> None:
        if p.phase in self.counts:
            self.counts[p.phase].append(p.passed())

    def rate(self, phase: str) -> str:
        results = self.counts.get(phase, [])
        if not results:
            return "—"
        return f"{sum(results)}/{len(results)}"


# ─── Stream once + collect ──────────────────────────────────────────────


def _token_limit_key(model: str) -> str:
    """gpt-5.x / o1 / o3 / a few cerebras use `max_completion_tokens`; rest use `max_tokens`."""
    cerebras = {"llama3.1-8b", "qwen-3-235b-a22b-instruct-2507"}
    if model in cerebras or any(model.startswith(p) for p in ("gpt-5", "o1", "o3")):
        return "max_completion_tokens"
    return "max_tokens"


async def _stream_once(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    use_tools: bool,
    timeout_s: float = 30.0,
) -> tuple[str, list[dict], str]:
    """Returns (content_text, tool_calls_list, error_str)."""
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
        stream = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=timeout_s,
        )
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


# ─── Two-phase probe: turn-1 (user) → turn-2 (tool result) ─────────────

USER_QUERY = "Anh xin cho em xem brochure dự án NCLB nha em."


async def _probe_one(
    client: AsyncOpenAI,
    model: str,
    variant: str,
    phase: str,
    run_idx: int,
) -> Probe:
    p = Probe(provider="", model=model, variant=variant, phase=phase, run_idx=run_idx)

    deferred_inst = DEFERRED_VARIANTS[variant]
    system_prompt = SYSTEM_PROMPT_BASE.format(deferred_instruction=deferred_inst)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": USER_QUERY},
    ]

    # Turn 1 — user → expect filler + tool_call
    t1_text, t1_calls, err = await _stream_once(client, model, messages, use_tools=True)
    if err:
        p.error = f"turn1: {err}"
        return p

    p.t1_text = t1_text.strip()
    if t1_calls:
        first = t1_calls[0]
        p.t1_tool_called = first["name"]
        # Filler concurrent = both content AND tool_call in turn-1
        p.t1_filler_concurrent = bool(t1_text.strip()) and first["name"] == "send_media"
    else:
        # No tool call — model didn't follow the instruction at all
        return p

    if p.phase == "filler":
        # Phase 1 only checks turn-1; we're done
        return p

    # Build assistant message with tool_calls (mirror voice agent flow)
    assistant_msg = {
        "role": "assistant",
        "content": t1_text or None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["args"] or "{}"},
            }
            for tc in t1_calls
        ],
    }
    messages.append(assistant_msg)

    # Pick the tool result for this phase
    if phase == "deferred":
        # Use Vietnamese variant for v1 (matches system prompt language)
        tool_payload = DEFERRED_RESULT_VI if variant in ("v1_minimal_flag", "v2_explicit_rule") else DEFERRED_RESULT
    elif phase == "sync":
        tool_payload = SYNC_RESULT_NOBLEX
    else:
        tool_payload = {"ok": True}

    # Append tool result for the FIRST tool call (model usually only calls one)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": t1_calls[0]["id"],
            "content": json.dumps(tool_payload, ensure_ascii=False),
        }
    )

    # Turn 2 — model responds to tool result
    t2_text, _, err = await _stream_once(client, model, messages, use_tools=True)
    if err:
        p.error = f"turn2: {err}"
        return p

    p.t2_text = t2_text.strip()
    # Rough VN token count: 1 token ≈ 1 syllable ≈ space-split word
    p.t2_token_count = len(p.t2_text.split())

    return p


# ─── Test orchestration ─────────────────────────────────────────────────


async def _run_provider(
    name: str,
    pcfg: dict,
    runs: int,
    variants: list[str],
) -> list[Aggregate]:
    aggs: list[Aggregate] = []
    client = pcfg["client"]
    model = pcfg["model"]
    print(f"\n  ── Provider: {name} / {model} ──")

    for variant in variants:
        agg = Aggregate(provider=name, model=model, variant=variant)
        for run_idx in range(runs):
            for phase in ("filler", "deferred", "sync"):
                t0 = time.monotonic()
                p = await _probe_one(client, model, variant, phase, run_idx)
                p.provider = name
                dt = (time.monotonic() - t0) * 1000
                agg.add(p)
                marker = "✓" if p.passed() else "✗"
                err = f"  ERR={p.error}" if p.error else ""
                t2_preview = p.t2_text[:60].replace("\n", " ")
                print(
                    f"    [{variant} #{run_idx + 1}/{runs}] {phase:9s} {marker}  "
                    f"({dt:.0f}ms) t2_tokens={p.t2_token_count:3d}{err}"
                    + (f"  t2='{t2_preview}'" if phase != "filler" and p.t2_text else "")
                )
        aggs.append(agg)
    return aggs


def _print_summary(all_aggs: list[Aggregate]) -> None:
    print("\n" + "=" * 90)
    print(" COMPLIANCE SUMMARY (pass/total per phase)")
    print("=" * 90)
    print(f"  {'Provider':<14s} {'Variant':<22s} {'filler':>10s} {'deferred':>10s} {'sync':>10s} {'verdict':>10s}")
    print("  " + "─" * 78)
    for a in all_aggs:
        f = a.rate("filler")
        d = a.rate("deferred")
        s = a.rate("sync")

        def _ratio(label: str, agg: Aggregate = a) -> float:
            results = agg.counts[label]
            return sum(results) / len(results) if results else 0.0

        # Verdict gates ONLY on deferred + sync. `filler` (concurrent emission
        # with tool_call) is informational — production already has a canned
        # tool_ack fallback path for models that defer content tokens until
        # AFTER the tool_call (gpt-5.x family). Phương án A only needs
        # turn-2 compliance: model stays silent on `deferred`, model speaks
        # on sync.
        ok = _ratio("deferred") >= 0.8 and _ratio("sync") >= 0.8
        verdict = "PASS" if ok else "FAIL"
        print(f"  {a.provider:<14s} {a.variant:<22s} {f:>10s} {d:>10s} {s:>10s} {verdict:>10s}")


# ─── CLI ────────────────────────────────────────────────────────────────


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=int, default=5, help="Runs per (provider, variant, phase)")
    p.add_argument(
        "--providers",
        type=str,
        default="",
        help="Comma list (openai,gemini,qwen,openrouter). Empty = all available.",
    )
    p.add_argument(
        "--variants",
        type=str,
        default="",
        help=f"Comma list of variants ({','.join(DEFERRED_VARIANTS)}). Empty = all.",
    )
    args = p.parse_args()

    providers_avail = _build_providers()
    if not providers_avail:
        print("No providers configured. Set OPENAI_API_KEY / GEMINI_API_KEY / DASHSCOPE_API_KEY in .env")
        return 1

    if args.providers:
        wanted = {x.strip() for x in args.providers.split(",") if x.strip()}
        providers = {k: v for k, v in providers_avail.items() if k in wanted}
        if not providers:
            print(f"None of {wanted} configured in .env. Available: {list(providers_avail)}")
            return 1
    else:
        providers = providers_avail

    if args.variants:
        wanted_v = [x.strip() for x in args.variants.split(",") if x.strip() in DEFERRED_VARIANTS]
        variants = wanted_v or list(DEFERRED_VARIANTS)
    else:
        variants = list(DEFERRED_VARIANTS)

    print(f"Probing {len(providers)} provider(s) × {len(variants)} variant(s) × 3 phases × {args.runs} runs")
    print(f"= {len(providers) * len(variants) * 3 * args.runs} LLM calls total")

    all_aggs: list[Aggregate] = []
    for name, pcfg in providers.items():
        aggs = await _run_provider(name, pcfg, args.runs, variants)
        all_aggs.extend(aggs)

    _print_summary(all_aggs)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
