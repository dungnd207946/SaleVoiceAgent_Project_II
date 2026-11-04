#!/usr/bin/env python3
"""LLM Provider Benchmark CLI.

Supports all OpenAI-compatible endpoints: cloud providers (.env) and local
servers (Ollama, vLLM, SGLang, LM Studio, etc.) via --url/--model flags.

Usage:
    # Interactive menu (picks from .env providers)
    python tests/bench_llm.py

    # Specific .env provider
    python tests/bench_llm.py --provider groq
    python tests/bench_llm.py --provider groq,openai --case all --runs 3

    # Local servers (any OpenAI-compatible endpoint)
    python tests/bench_llm.py --url http://localhost:11434/v1 --model llama3.2          # Ollama
    python tests/bench_llm.py --url http://localhost:8000/v1 --model meta-llama/Llama-3.2-3B  # vLLM
    python tests/bench_llm.py --url http://localhost:30000/v1 --model meta-llama/Llama-3.2-3B # SGLang
    python tests/bench_llm.py --url http://localhost:1234/v1 --model loaded-model       # LM Studio

    # Compare local vs cloud
    python tests/bench_llm.py --provider groq --url http://localhost:11434/v1 --model llama3.2

    # Options
    --case 1,3,5       Run specific cases
    --case all          Run all 8 cases
    --runs 3            Average over N runs
    --json              Output raw JSON
    --no-tools          Skip tool-calling cases (for models that don't support it)
    --max-tokens N      Override max output tokens (default: 2048)
    --name my-server    Label for custom endpoint in results

Measures: TTFT (ms), total latency (ms), output tok/s, token counts, tool accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from openai import AsyncOpenAI

# RAG harness (lazy import — zero overhead when --rag off)
_BENCH_RAG_AVAILABLE = False
_BENCH_RAG_ERR = ""
try:
    sys.path.insert(0, os.path.dirname(__file__))
    from bench_rag import (
        SCENARIO_NAMES,
        WarmupConfig,
        ensure_warmed_up,
        evaluate_case,
        inject_faq,
        load_scenarios,
        real_noble_search,
        warmup_all,
    )
    from bench_rag import (
        get_collector as get_timing_collector,
    )
    from bench_rag import (
        print_report as print_warmup_report,
    )
    from bench_rag import (
        reset_collector as reset_timing,
    )

    _BENCH_RAG_AVAILABLE = True
except Exception as _rag_exc:
    _BENCH_RAG_ERR = str(_rag_exc)

# Global flag — set True when --rag on or interactive RAG mode chosen
_RAG_ENABLED = False

# Try loading project config; not required for --url mode
try:
    from noble_agent.config import settings as _settings
except Exception:
    _settings = None

# ── Test cases ────────────────────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Tìm kiếm thông tin dự án Noble từ knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Câu hỏi tìm kiếm"},
                    "project_filter": {"type": "string", "enum": ["", "NCLB", "NPLB", "NCTH", "NTTL", "SSLC"]},
                },
                "required": ["query"],
            },
        },
    }
]

CASES: list[dict] = [
    {
        "id": 1,
        "name": "Greeting (short)",
        "desc": "Baseline latency — short reply",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý tư vấn bất động sản Noble, trả lời ngắn gọn bằng tiếng Việt."},
            {"role": "user", "content": "Xin chào"},
        ],
    },
    {
        "id": 2,
        "name": "Project info (medium)",
        "desc": "Knowledge + medium output",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý tư vấn bất động sản Noble, trả lời bằng tiếng Việt."},
            {
                "role": "user",
                "content": "Cho tôi biết thông tin về dự án Noble Crystal Long Biên, giá bao nhiêu, diện tích bao nhiêu?",
            },
        ],
    },
    {
        "id": 3,
        "name": "Tool calling",
        "desc": "Function call accuracy",
        "messages": [
            {
                "role": "system",
                "content": "Bạn là trợ lý tư vấn bất động sản Noble. Dùng tool noble_search để tìm thông tin.",
            },
            {"role": "user", "content": "Tìm cho tôi thông tin tiện ích nội khu của dự án Noble Crystal"},
        ],
        "tools": True,
    },
    {
        "id": 4,
        "name": "Long output",
        "desc": "Sustained throughput — 2K+ tokens",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý tư vấn bất động sản Noble, trả lời chi tiết bằng tiếng Việt."},
            {
                "role": "user",
                "content": "So sánh chi tiết ưu nhược điểm giữa việc mua căn hộ ở Long Biên và Tây Hồ, phân tích về giá cả, giao thông, tiện ích, tiềm năng tăng giá trong 5 năm tới.",
            },
        ],
    },
    {
        "id": 5,
        "name": "Multi-turn (3 turns)",
        "desc": "Context window handling",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý tư vấn bất động sản Noble, trả lời ngắn gọn bằng tiếng Việt."},
            {"role": "user", "content": "Tôi đang tìm căn hộ 2 phòng ngủ ở Hà Nội"},
            {
                "role": "assistant",
                "content": "Dạ em chào anh/chị. Noble có nhiều dự án căn hộ 2PN tại Hà Nội. Anh/chị quan tâm khu vực nào ạ? Long Biên hay Tây Hồ?",
            },
            {"role": "user", "content": "Long Biên, ngân sách khoảng 3 tỷ"},
            {
                "role": "assistant",
                "content": "Với ngân sách 3 tỷ tại Long Biên, em gợi ý dự án Noble Crystal Long Biên. Căn 2PN diện tích 65-75m2. Anh/chị muốn em tư vấn chi tiết hơn không ạ?",
            },
            {"role": "user", "content": "Cho tôi biết chính sách thanh toán và ưu đãi hiện tại"},
        ],
    },
    {
        "id": 6,
        "name": "Vietnamese numbers",
        "desc": "Number/price formatting",
        "messages": [
            {
                "role": "system",
                "content": "Bạn là trợ lý tư vấn bất động sản Noble. Viết SỐ BẰNG CHỮ (ví dụ: ba tỷ hai trăm triệu). Trả lời bằng tiếng Việt.",
            },
            {
                "role": "user",
                "content": "Giá căn hộ 75m2 là bao nhiêu? Thanh toán đợt 1 bao nhiêu phần trăm? Số hotline tư vấn là gì?",
            },
        ],
    },
    {
        "id": 7,
        "name": "Reasoning",
        "desc": "Analysis quality",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý tư vấn bất động sản Noble, trả lời bằng tiếng Việt."},
            {
                "role": "user",
                "content": "Nếu tôi có 5 tỷ, nên mua 1 căn lớn hay 2 căn nhỏ để đầu tư? Phân tích lợi nhuận cho thuê vs tăng giá.",
            },
        ],
    },
    {
        "id": 8,
        "name": "Interruption recovery",
        "desc": "Coherence after mid-sentence cut",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý tư vấn bất động sản Noble, trả lời ngắn gọn bằng tiếng Việt."},
            {"role": "user", "content": "Nói cho tôi về dự án Noble"},
            {"role": "assistant", "content": "Dạ Noble có nhiều dự án—"},
            {"role": "user", "content": "Khoan, tôi chỉ quan tâm cái nào gần metro nhất thôi"},
        ],
    },
]

# ── Provider setup ────────────────────────────────────────────────────────────


def _env_providers() -> dict[str, dict]:
    """Build providers from .env config."""
    if _settings is None:
        return {}
    providers = {}
    if _settings.openai_api_key:
        providers["openai"] = {
            "client": AsyncOpenAI(api_key=_settings.openai_api_key, base_url=_settings.openai_base_url, timeout=30),
            "model": _settings.openai_model,
        }
    if _settings.gemini_api_key:
        providers["gemini"] = {
            "client": AsyncOpenAI(api_key=_settings.gemini_api_key, base_url=_settings.gemini_base_url, timeout=30),
            "model": _settings.gemini_model,
        }
    if _settings.openrouter_api_key:
        providers["openrouter"] = {
            "client": AsyncOpenAI(
                api_key=_settings.openrouter_api_key, base_url=_settings.openrouter_base_url, timeout=30
            ),
            "model": _settings.openrouter_model,
        }
    if _settings.groq_api_key:
        providers["groq"] = {
            "client": AsyncOpenAI(api_key=_settings.groq_api_key, base_url=_settings.groq_base_url, timeout=30),
            "model": _settings.groq_model,
        }
    if _settings.dashscope_api_key:
        providers["qwen"] = {
            "client": AsyncOpenAI(
                api_key=_settings.dashscope_api_key, base_url=_settings.dashscope_base_url, timeout=30
            ),
            "model": _settings.dashscope_model,
        }
    if _settings.cerebras_api_key:
        providers["cerebras"] = {
            "client": AsyncOpenAI(api_key=_settings.cerebras_api_key, base_url=_settings.cerebras_base_url, timeout=30),
            "model": _settings.cerebras_model,
            "max_tokens_key": "max_completion_tokens",  # Cerebras requires this for all models
        }
    return providers


def _custom_provider(url: str, model: str, api_key: str, name: str) -> dict[str, dict]:
    """Build a single provider from CLI args."""
    return {
        name: {
            "client": AsyncOpenAI(api_key=api_key, base_url=url, timeout=60),
            "model": model,
        }
    }


async def _test_model_connection(client: AsyncOpenAI, model: str, max_tokens_key: str | None = None) -> bool:
    """Send a tiny request to verify model name is valid and reachable."""
    tok_key = max_tokens_key or _token_limit_key(model)
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            **{tok_key: 10},
            stream=True,
        )
        async for _ in stream:
            pass
        return True
    except Exception as e:
        print(f"  {C.RED}✗ Connection failed: {e}{C.RESET}")
        return False


async def _customize_provider_model(name: str, prov: dict) -> dict:
    """Let user change model name for a provider, validate connection.
    Returns updated provider dict (same object if unchanged).
    """
    current = prov["model"]
    print(f"\n{C.CYAN}  {name}{C.RESET} current model: {C.YELLOW}{current}{C.RESET}")
    new_model = input(f"  Enter model name [{current}]: ").strip()

    mtk = prov.get("max_tokens_key")
    if not new_model or new_model == current:
        # Keep current — still validate connection
        print(f"  {C.DIM}Testing {current}...{C.RESET}", end=" ", flush=True)
        if await _test_model_connection(prov["client"], current, mtk):
            print(f"{C.GREEN}✓{C.RESET}")
            return prov
        # Current model failed — force user to enter a new one
        print(f"  {C.YELLOW}Default model not reachable. Enter a different model.{C.RESET}")
        new_model = ""

    while True:
        if not new_model:
            try:
                new_model = input("  Model name: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return prov
            if not new_model:
                return prov

        print(f"  {C.DIM}Testing {new_model}...{C.RESET}", end=" ", flush=True)
        if await _test_model_connection(prov["client"], new_model, mtk):
            print(f"{C.GREEN}✓{C.RESET}")
            prov["model"] = new_model
            return prov

        print(f"  {C.YELLOW}Try another model name or press Enter to skip.{C.RESET}")
        new_model = ""


# ── Ollama integration ───────────────────────────────────────────────────────

import shutil
import subprocess

_ollama_model_loaded: str | None = None  # track what we loaded


def _ollama_is_running() -> bool:
    """Check if Ollama server is reachable."""
    try:
        import urllib.request

        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


def _ollama_list_models() -> list[str]:
    """Get list of locally available Ollama models."""
    try:
        import json as _json
        import urllib.request

        resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
        data = _json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _ollama_pull_and_load(model: str) -> bool:
    """Pull model if needed and warm it up with a tiny request."""
    print(f"{C.CYAN}  Loading {model} into Ollama...{C.RESET}", flush=True)
    try:
        # Pull (no-op if already downloaded)
        subprocess.run(
            ["ollama", "pull", model], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600
        )
        # Warm up — send a tiny request to load into memory
        import json as _json
        import urllib.request

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=_json.dumps({"model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 1}}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=120)
        print(f"{C.GREEN}  ✓ {model} loaded{C.RESET}")
        return True
    except Exception as e:
        print(f"{C.RED}  ✗ Failed to load {model}: {e}{C.RESET}")
        return False


def _ollama_stop_model(model: str):
    """Unload model from Ollama memory."""
    try:
        import json as _json
        import urllib.request

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=_json.dumps({"model": model, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def _ollama_interactive_setup() -> dict[str, dict] | None:
    """Interactive Ollama setup: list models, let user pick or enter new one."""
    if not shutil.which("ollama"):
        return None
    if not _ollama_is_running():
        print(f"{C.YELLOW}  Ollama is installed but not running. Start with: ollama serve{C.RESET}")
        return None

    models = _ollama_list_models()
    print(f"\n{C.CYAN}  📦 Ollama models available locally:{C.RESET}")
    if models:
        for i, m in enumerate(models, 1):
            print(f"    [{i}] {m}")
    else:
        print("    (no models downloaded yet)")
    print("    [0] Enter model name manually (will pull if needed)")
    print()

    choice = input("  Select model: ").strip()
    if choice == "0" or (not choice and not models):
        model = input("  Model name (e.g. qwen3:4b): ").strip()
        if not model:
            return None
    elif choice.isdigit() and 1 <= int(choice) <= len(models):
        model = models[int(choice) - 1]
    elif choice and not choice.isdigit():
        model = choice  # user typed model name directly
    else:
        return None

    global _ollama_model_loaded
    if _ollama_pull_and_load(model):
        _ollama_model_loaded = model
        return {
            "ollama": {
                "client": AsyncOpenAI(api_key="not-needed", base_url="http://localhost:11434/v1", timeout=120),
                "model": model,
            }
        }
    return None


def _ollama_cleanup():
    """Ask user if they want to unload/stop Ollama model on exit."""
    global _ollama_model_loaded
    if not _ollama_model_loaded:
        return
    try:
        choice = (
            input(f"\n{C.YELLOW}Unload {_ollama_model_loaded} from Ollama memory? [Y/n]: {C.RESET}").strip().lower()
        )
        if choice in ("", "y", "yes"):
            _ollama_stop_model(_ollama_model_loaded)
            print(f"{C.GREEN}  ✓ {_ollama_model_loaded} unloaded{C.RESET}")
        _ollama_model_loaded = None
    except (EOFError, KeyboardInterrupt):
        pass


# ── Benchmark runner ──────────────────────────────────────────────────────────


@dataclass
class RunResult:
    provider: str
    model: str
    case_id: int
    case_name: str
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    output_tokens: int = 0
    input_tokens: int = 0
    tok_per_sec: float = 0.0
    tool_called: str = ""
    output_preview: str = ""
    error: str = ""
    # RAG scenario eval fields (None when not a scenario case)
    tool_accuracy: bool | None = None
    keyword_match: float | None = None
    faq_hit: bool | None = None


def _token_limit_key(model: str) -> str:
    """Returns correct token limit param for each model family."""
    # Cerebras always requires max_completion_tokens
    _cerebras_models = {"llama3.1-8b", "qwen-3-235b-a22b-instruct-2507"}
    if model in _cerebras_models or any(model.startswith(p) for p in ("gpt-5", "o1", "o3")):
        return "max_completion_tokens"
    return "max_tokens"


async def _run_case(
    client: AsyncOpenAI,
    model: str,
    case: dict,
    provider_name: str,
    max_tokens: int,
    use_tools: bool,
    max_tokens_key: str | None = None,
) -> RunResult:
    result = RunResult(
        provider=provider_name,
        model=model,
        case_id=case["id"],
        case_name=case["name"],
    )

    tok_key = max_tokens_key or _token_limit_key(model)
    kwargs: dict = {
        "model": model,
        "messages": case["messages"],
        "stream": True,
        tok_key: max_tokens,
    }
    # Only request usage if not a local server (many don't support it)
    kwargs["stream_options"] = {"include_usage": True}

    if case.get("tools") and use_tools:
        kwargs["tools"] = TOOL_DEFS

    t0 = time.monotonic()
    try:
        ttft_set = False
        chunks: list[str] = []
        tool_calls: list[str] = []

        stream = await client.chat.completions.create(**kwargs)
        async for event in stream:
            # Usage info (may not be available on all providers)
            if not event.choices:
                if hasattr(event, "usage") and event.usage:
                    result.input_tokens = event.usage.prompt_tokens or 0
                    result.output_tokens = event.usage.completion_tokens or 0
                continue

            delta = event.choices[0].delta
            if delta and delta.content:
                if not ttft_set:
                    result.ttft_ms = (time.monotonic() - t0) * 1000
                    ttft_set = True
                chunks.append(delta.content)

            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.function and tc.function.name:
                        tool_calls.append(tc.function.name)
                    if not ttft_set:
                        result.ttft_ms = (time.monotonic() - t0) * 1000
                        ttft_set = True

        result.total_ms = (time.monotonic() - t0) * 1000
        full_text = "".join(chunks)
        result.output_preview = full_text[:150].replace("\n", " ")
        result.tool_called = ", ".join(dict.fromkeys(tool_calls)) if tool_calls else ""

        # Estimate tokens from text if usage not provided
        if result.output_tokens == 0 and full_text:
            result.output_tokens = max(1, len(full_text) // 3)

        if result.output_tokens > 0 and result.total_ms > 0:
            result.tok_per_sec = result.output_tokens / (result.total_ms / 1000)

        # RAG scenario evaluation
        if "_scenario" in case and _BENCH_RAG_AVAILABLE:
            eval_result = evaluate_case(case["_scenario"], result.tool_called, full_text)
            result.tool_accuracy = eval_result["tool_accuracy"]
            result.keyword_match = eval_result["keyword_match"]
            result.faq_hit = eval_result["faq_hit"]

    except Exception as e:
        result.error = str(e)[:200]
        result.total_ms = (time.monotonic() - t0) * 1000

    return result


# ── Display ───────────────────────────────────────────────────────────────────


def _print_result(r: RunResult):
    if r.error:
        print(f"  ❌ ERROR: {r.error}")
        return
    tool_str = f"  🔧 tool: {r.tool_called}" if r.tool_called else ""
    print(
        f"  TTFT: {r.ttft_ms:>7.0f}ms | Total: {r.total_ms:>7.0f}ms | "
        f"Tokens: {r.input_tokens:>4}in/{r.output_tokens:>4}out | "
        f"Speed: {r.tok_per_sec:>6.1f} tok/s{tool_str}"
    )
    if r.output_preview:
        print(f"  📝 {r.output_preview[:120]}...")


def _print_summary(results: list[RunResult]):
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)

    by_provider: dict[str, list[RunResult]] = {}
    for r in results:
        by_provider.setdefault(r.provider, []).append(r)

    for prov, runs in by_provider.items():
        ok = [r for r in runs if not r.error]
        if not ok:
            print(f"\n  {prov}: all failed")
            continue
        avg_ttft = sum(r.ttft_ms for r in ok) / len(ok)
        avg_total = sum(r.total_ms for r in ok) / len(ok)
        avg_tps = sum(r.tok_per_sec for r in ok) / len(ok)
        total_out = sum(r.output_tokens for r in ok)
        tool_cases = [r for r in ok if CASES[r.case_id - 1].get("tools")]
        tool_ok = sum(1 for r in tool_cases if r.tool_called)

        print(f"\n  📊 {prov} ({ok[0].model})")
        print(f"     Avg TTFT:     {avg_ttft:>7.0f} ms")
        print(f"     Avg Total:    {avg_total:>7.0f} ms")
        print(f"     Avg Speed:    {avg_tps:>7.1f} tok/s")
        print(f"     Total output: {total_out:>5} tokens across {len(ok)} cases")
        if tool_cases:
            print(f"     Tool accuracy: {tool_ok}/{len(tool_cases)}")
        errors = len(runs) - len(ok)
        if errors:
            print(f"     Errors: {errors}/{len(runs)}")

        # RAG scenario aggregate metrics
        scenario_runs = [r for r in ok if r.tool_accuracy is not None]
        if scenario_runs:
            ta_ok = sum(1 for r in scenario_runs if r.tool_accuracy)
            faq_hits = sum(1 for r in scenario_runs if r.faq_hit)
            kw_runs = [r for r in scenario_runs if r.keyword_match is not None]
            avg_kw = sum(r.keyword_match for r in kw_runs) / len(kw_runs) if kw_runs else None
            print(f"     Tool accuracy:   {ta_ok}/{len(scenario_runs)} ({100 * ta_ok // len(scenario_runs)}%)")
            print(f"     FAQ hit:         {faq_hits}/{len(scenario_runs)}")
            if avg_kw is not None:
                print(f"     Avg keyword match: {avg_kw * 100:.0f}%")

    # Side-by-side comparison
    if len(by_provider) > 1:
        print(f"\n{'─' * 80}")
        header = f"  {'Case':<28}"
        for prov in by_provider:
            header += f" | {prov:>14} t/s"
        print(header)
        print(f"  {'─' * 26}", end="")
        for _ in by_provider:
            print(f" | {'─' * 14}", end="")
        print()
        case_ids = sorted(set(r.case_id for r in results))
        for cid in case_ids:
            cname = next(c["name"] for c in CASES if c["id"] == cid)
            line = f"  {cname:<28}"
            for prov in by_provider:
                match = [r for r in by_provider[prov] if r.case_id == cid and not r.error]
                if match:
                    avg = sum(r.tok_per_sec for r in match) / len(match)
                    line += f" | {avg:>12.1f} t/s"
                else:
                    line += f" | {'ERR':>14}"
            print(line)


# ── Interactive menu ──────────────────────────────────────────────────────────


def _select_cases(skip_tools: bool) -> list[dict]:
    available = [c for c in CASES if not (skip_tools and c.get("tools"))]
    print("\n📋 Test Cases:")
    print("─" * 65)
    for c in available:
        tools_tag = " [tools]" if c.get("tools") else ""
        print(f"  [{c['id']}] {c['name']:<28} — {c['desc']}{tools_tag}")
    print("  [0] Run ALL")
    print("─" * 65)

    choice = input("\nSelect case(s) (comma-separated, e.g. 1,3,5): ").strip()
    if not choice or choice == "0":
        return available

    ids = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
    selected = [c for c in available if c["id"] in ids]
    return selected or available


# ── Local server setup ────────────────────────────────────────────────────────

_LOCAL_SERVERS = [
    {"key": "ollama", "label": "Ollama", "default_port": 11434, "path": "/v1"},
    {"key": "mlx-lm", "label": "MLX-LM", "default_port": 8080, "path": "/v1"},
    {"key": "vllm", "label": "vLLM", "default_port": 8000, "path": "/v1"},
    {"key": "sglang", "label": "SGLang", "default_port": 30000, "path": "/v1"},
    {"key": "lmstudio", "label": "LM Studio", "default_port": 1234, "path": "/v1"},
]


def _probe_local_server(port: int, path: str = "/v1") -> bool:
    """Check if a local OpenAI-compatible server is reachable."""
    try:
        import urllib.request

        urllib.request.urlopen(f"http://localhost:{port}{path}/models", timeout=2)
        return True
    except Exception:
        return False


def _setup_local_server(server: dict, available: dict) -> str | None:
    """Interactive setup for a local server — enter port, model, connect."""
    key = server["key"]
    label = server["label"]
    default_port = server["default_port"]
    path = server["path"]

    # Special case: Ollama has its own richer setup
    if key == "ollama":
        result = _ollama_interactive_setup()
        if result:
            available.update(result)
            return "ollama"
        return None

    # Port
    port_input = input(f"  {label} port [{default_port}]: ").strip()
    port = int(port_input) if port_input.isdigit() else default_port

    base_url = f"http://localhost:{port}{path}"

    # Check connectivity
    if not _probe_local_server(port, path):
        print(f"  {C.RED}✗ Cannot reach {base_url}{C.RESET}")
        print(f"  {C.DIM}  Start server first, e.g.:{C.RESET}")
        if key == "mlx-lm":
            print(f"  {C.DIM}  mlx_lm.server --model <model> --port {port}{C.RESET}")
        elif key == "vllm":
            print(f"  {C.DIM}  vllm serve <model> --port {port}{C.RESET}")
        elif key == "sglang":
            print(f"  {C.DIM}  python -m sglang.launch_server --model <model> --port {port}{C.RESET}")
        elif key == "lmstudio":
            print(f"  {C.DIM}  Open LM Studio → Start Server on port {port}{C.RESET}")
        return None

    # List models from server
    models = []
    try:
        import json as _json
        import urllib.request

        resp = urllib.request.urlopen(f"http://localhost:{port}{path}/models", timeout=5)
        data = _json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
    except Exception:
        pass

    if models:
        print(f"  {C.CYAN}Models on server:{C.RESET}")
        for i, m in enumerate(models, 1):
            print(f"    [{i}] {m}")
        print("    [0] Enter manually")
        mc = input("  Select model: ").strip()
        if mc.isdigit() and 1 <= int(mc) <= len(models):
            model = models[int(mc) - 1]
        elif mc and not mc.isdigit():
            model = mc
        else:
            model = input("  Model name: ").strip()
    else:
        model = input("  Model name: ").strip()

    if not model:
        return None

    print(f"  {C.GREEN}✓ {label} ({model}) at port {port}{C.RESET}")

    available[key] = {
        "client": AsyncOpenAI(api_key="not-needed", base_url=base_url, timeout=120),
        "model": model,
    }
    return key


def _select_providers(available: dict[str, dict]) -> list[str]:
    names = list(available.keys())

    # Detect which local servers are available
    local_options: list[dict] = []
    for srv in _LOCAL_SERVERS:
        if srv["key"] not in available:
            local_options.append(srv)

    print("\n🔌 Available providers:")
    for i, name in enumerate(names, 1):
        model = available[name]["model"]
        print(f"  [{i}] {name:<14} → {model}")

    # Local server options
    local_start_idx = len(names) + 1
    if local_options:
        print(f"  {'─' * 40}")
        print(f"  {C.DIM}Local servers:{C.RESET}")
        for j, srv in enumerate(local_options):
            idx = local_start_idx + j
            running = _probe_local_server(srv["default_port"], srv["path"])
            status = f"{C.GREEN}●{C.RESET}" if running else f"{C.GRAY}○{C.RESET}"
            print(f"  [{idx}] {status} {srv['label']:<12} (port {srv['default_port']})")

    print("  [0] ALL (cloud only)")
    print()

    choice = input("Select provider(s) (comma-separated, e.g. 1,2): ").strip()
    if not choice or choice == "0":
        return names

    indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]

    selected = []
    for i in indices:
        # Cloud provider
        if 0 <= i < len(names):
            selected.append(names[i])
        # Local server
        elif local_options:
            local_idx = i - (local_start_idx - 1)
            if 0 <= local_idx < len(local_options):
                key = _setup_local_server(local_options[local_idx], available)
                if key:
                    selected.append(key)

    return selected or names


# ── ANSI colors ───────────────────────────────────────────────────────────────


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
    GRAY = "\033[90m"


# ── Web UI ───────────────────────────────────────────────────────────────────

import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Bench LLM Monitor</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1117; color: #e2e8f0; font-family: 'Courier New', monospace; font-size: 13px; }
  #header { background: #1a1d27; border-bottom: 1px solid #2d3148; padding: 10px 20px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  #header h1 { font-size: 14px; color: #7c8cf8; white-space: nowrap; }
  .badge { background: #2d3148; border-radius: 4px; padding: 2px 8px; font-size: 11px; }
  .badge.agent { color: #a78bfa; }
  .badge.provider { color: #34d399; }
  .badge.model { color: #fbbf24; }
  .badge.version { color: #f472b6; }
  #status-dot { width: 8px; height: 8px; border-radius: 50%; background: #6b7280; margin-left: auto; flex-shrink: 0; }
  #status-dot.connected { background: #34d399; box-shadow: 0 0 6px #34d399; }
  #layout { display: grid; grid-template-columns: 360px 1fr; height: calc(100vh - 45px); }
  /* Sidebar with tabs */
  #sidebar { background: #13151f; border-right: 1px solid #2d3148; display: flex; flex-direction: column; }
  .tabs { display: flex; border-bottom: 1px solid #1e2035; flex-shrink: 0; }
  .tab { padding: 7px 14px; font-size: 11px; color: #6b7280; cursor: pointer; border-bottom: 2px solid transparent; text-transform: uppercase; letter-spacing: 0.5px; }
  .tab.active { color: #7c8cf8; border-bottom-color: #7c8cf8; }
  .tab-panel { display: none; flex: 1; overflow-y: auto; }
  .tab-panel.active { display: block; }
  #prompt-box, #context-box { padding: 12px 14px; white-space: pre-wrap; font-size: 11px; line-height: 1.6; color: #94a3b8; word-break: break-word; }
  /* Context sections */
  .ctx-section { margin-bottom: 10px; }
  .ctx-role { font-size: 10px; font-weight: bold; letter-spacing: 1px; padding: 3px 8px; border-radius: 3px; margin-bottom: 4px; display: inline-block; }
  .ctx-role.system { background: #1e2a1e; color: #4ade80; }
  .ctx-role.user { background: #1e2535; color: #60a5fa; }
  .ctx-role.assistant { background: #1e1a2e; color: #a78bfa; }
  .ctx-role.tool { background: #1e1a1e; color: #f472b6; }
  .ctx-content { color: #94a3b8; font-size: 11px; white-space: pre-wrap; word-break: break-word; }
  .ctx-divider { border: none; border-top: 1px solid #1e2035; margin: 8px 0; }
  #ctx-count { padding: 6px 14px; font-size: 10px; color: #4b5563; border-bottom: 1px solid #1e2035; flex-shrink: 0; }
  /* Main */
  #main { display: flex; flex-direction: column; }
  #conv { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .msg { border-radius: 6px; padding: 10px 14px; max-width: 90%; line-height: 1.6; }
  .msg.user { background: #1e2a3a; border-left: 3px solid #3b82f6; align-self: flex-end; color: #93c5fd; }
  .msg.bot { background: #1a1f2e; border-left: 3px solid #7c8cf8; align-self: flex-start; color: #e2e8f0; }
  .msg.tool { background: #1c1f2b; border-left: 3px solid #a78bfa; font-size: 11px; color: #c4b5fd; }
  .msg.tool-result { background: #151a1f; border-left: 3px solid #374151; font-size: 11px; color: #6b7280; }
  .msg.system { background: #1a1d27; border-left: 3px solid #f59e0b; font-size: 11px; color: #fbbf24; align-self: center; }
  .msg-label { font-size: 10px; color: #6b7280; margin-bottom: 4px; }
  .msg-time { font-size: 10px; color: #4b5563; margin-top: 4px; }
  .streaming::after { content: '▋'; animation: blink 0.8s infinite; color: #7c8cf8; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  #metrics { background: #13151f; border-top: 1px solid #2d3148; padding: 8px 16px; font-size: 11px; color: #6b7280; display: flex; gap: 20px; flex-wrap: wrap; }
  #metrics span { color: #94a3b8; }
</style>
</head>
<body>
<div id="header">
  <h1>⚡ Bench LLM Monitor</h1>
  <span class="badge provider" id="h-provider">—</span>
  <span class="badge model" id="h-model">—</span>
  <span class="badge agent" id="h-agent">—</span>
  <span class="badge version" id="h-version" style="display:none"></span>
  <div id="status-dot" title="SSE connection"></div>
</div>
<div id="layout">
  <div id="sidebar">
    <div class="tabs">
      <div class="tab active" onclick="switchTab('prompt')">System Prompt</div>
      <div class="tab" onclick="switchTab('context')">Full Context <span id="ctx-badge" style="color:#4b5563"></span></div>
    </div>
    <div id="tab-prompt" class="tab-panel active">
      <div id="prompt-box"><span style="color:#4b5563">Waiting for session...</span></div>
    </div>
    <div id="tab-context" class="tab-panel">
      <div id="ctx-count" style="display:none"></div>
      <div id="context-box"><span style="color:#4b5563">No context yet — send a message</span></div>
    </div>
  </div>
  <div id="main">
    <div id="conv"></div>
    <div id="metrics">
      <div>TTFT: <span id="m-ttft">—</span></div>
      <div>Total: <span id="m-total">—</span></div>
      <div>Speed: <span id="m-speed">—</span></div>
      <div>Turns: <span id="m-turns">0</span></div>
    </div>
  </div>
</div>
<script>
const conv = document.getElementById('conv');
let currentBotMsg = null, turns = 0;

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', ['prompt','context'][i] === name));
  document.getElementById('tab-prompt').classList.toggle('active', name === 'prompt');
  document.getElementById('tab-context').classList.toggle('active', name === 'context');
}

function addMsg(cls, label, text) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.innerHTML = `<div class="msg-label">${label}</div><div class="msg-body">${escHtml(text)}</div>`;
  conv.appendChild(d);
  conv.scrollTop = conv.scrollHeight;
  return d;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>');
}

function renderContext(text, count) {
  const box = document.getElementById('context-box');
  const sections = text.split('\\n\\n─────\\n\\n');
  box.innerHTML = sections.map(sec => {
    const roleMatch = sec.match(/^\\[([A-Z]+)\\]\\n?/);
    const role = roleMatch ? roleMatch[1].toLowerCase() : 'unknown';
    const content = roleMatch ? sec.slice(roleMatch[0].length) : sec;
    return `<div class="ctx-section">
      <span class="ctx-role ${role}">${role.toUpperCase()}</span>
      <div class="ctx-content">${escHtml(content)}</div>
    </div>`;
  }).join('<hr class="ctx-divider">');
  const countEl = document.getElementById('ctx-count');
  countEl.style.display = '';
  countEl.textContent = `${count} messages in context`;
  document.getElementById('ctx-badge').textContent = ` (${count})`;
}

const es = new EventSource('/events');
es.onopen = () => document.getElementById('status-dot').className = 'connected';
es.onclose = () => document.getElementById('status-dot').className = '';
es.onerror = () => document.getElementById('status-dot').className = '';

es.addEventListener('session', e => {
  const d = JSON.parse(e.data);
  document.getElementById('h-provider').textContent = d.provider || '—';
  document.getElementById('h-model').textContent = d.model || '—';
  document.getElementById('h-agent').textContent = d.agent || '—';
  if (d.version) {
    const v = document.getElementById('h-version');
    v.textContent = d.version; v.style.display='';
  }
  document.getElementById('prompt-box').textContent = d.prompt || '(no prompt)';
});

es.addEventListener('messages_context', e => {
  const d = JSON.parse(e.data);
  renderContext(d.text, d.count);
});

es.addEventListener('user', e => {
  const d = JSON.parse(e.data);
  currentBotMsg = null;
  addMsg('user', 'You', d.text);
  turns++;
  document.getElementById('m-turns').textContent = turns;
});

es.addEventListener('token', e => {
  const d = JSON.parse(e.data);
  if (!currentBotMsg) {
    currentBotMsg = addMsg('bot streaming', 'Agent', '');
  }
  const body = currentBotMsg.querySelector('.msg-body');
  body.innerHTML += escHtml(d.tok);
  conv.scrollTop = conv.scrollHeight;
});

es.addEventListener('turn_end', e => {
  const d = JSON.parse(e.data);
  if (currentBotMsg) {
    currentBotMsg.classList.remove('streaming');
    const t = document.createElement('div');
    t.className = 'msg-time';
    t.textContent = `${(d.total_ms/1000).toFixed(2)}s · TTFT ${(d.ttft_ms/1000).toFixed(2)}s · ${d.tok_s.toFixed(0)} tok/s`;
    currentBotMsg.appendChild(t);
    currentBotMsg = null;
  }
  document.getElementById('m-ttft').textContent = d.ttft_ms.toFixed(0) + 'ms';
  document.getElementById('m-total').textContent = (d.total_ms/1000).toFixed(2) + 's';
  document.getElementById('m-speed').textContent = d.tok_s.toFixed(0) + ' tok/s';
});

es.addEventListener('tool_call', e => {
  const d = JSON.parse(e.data);
  addMsg('tool', '🔧 Tool Call', d.name + '(' + d.args + ')');
});

es.addEventListener('tool_result', e => {
  const d = JSON.parse(e.data);
  addMsg('tool-result', '↳ Result', d.result);
});

es.addEventListener('agent_switch', e => {
  const d = JSON.parse(e.data);
  document.getElementById('h-agent').textContent = d.agent;
  addMsg('system', '⚡ Agent Switch', '→ ' + d.agent);
  if (d.prompt) document.getElementById('prompt-box').textContent = d.prompt;
});

es.addEventListener('prompt_update', e => {
  const d = JSON.parse(e.data);
  document.getElementById('prompt-box').textContent = d.prompt;
  document.getElementById('h-agent').textContent = d.agent || document.getElementById('h-agent').textContent;
});
</script>
</body>
</html>"""


class BenchUI:
    """Minimal SSE web UI server for real-time benchmark/chat monitoring."""

    # Events whose latest value should be replayed to new SSE clients
    _STICKY_EVENTS = {"session", "prompt_update", "messages_context", "agent_switch"}

    def __init__(self, port: int = 8930):
        self.port = port
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        # Cache latest value of sticky events (event_name -> sse_msg)
        self._sticky: dict[str, str] = {}

    def _push(self, event: str, data: dict):
        """Broadcast SSE event to all connected clients, cache sticky events."""
        msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        with self._lock:
            if event in self._STICKY_EVENTS:
                self._sticky[event] = msg
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.remove(q)

    def start(self):
        ui = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass  # suppress access logs

            def do_GET(self):
                if self.path == "/":
                    body = _UI_HTML.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    client_q: queue.Queue = queue.Queue(maxsize=200)
                    with ui._lock:
                        ui._clients.append(client_q)
                        # Replay sticky events so new clients see current state
                        for _ev, _msg in ui._sticky.items():
                            try:
                                client_q.put_nowait(_msg)
                            except queue.Full:
                                pass
                    try:
                        while True:
                            try:
                                msg = client_q.get(timeout=15)
                                self.wfile.write(msg.encode())
                                self.wfile.flush()
                            except queue.Empty:
                                self.wfile.write(b": ping\n\n")
                                self.wfile.flush()
                    except Exception:
                        pass
                    finally:
                        with ui._lock:
                            if client_q in ui._clients:
                                ui._clients.remove(client_q)
                else:
                    self.send_response(404)
                    self.end_headers()

        self._server = HTTPServer(("localhost", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"{C.CYAN}  🌐 UI: http://localhost:{self.port}{C.RESET}")

    def stop(self):
        if self._server:
            self._server.shutdown()

    # Convenience event emitters
    def session(self, provider: str, model: str, agent: str, prompt: str, version: str = ""):
        self._push(
            "session", {"provider": provider, "model": model, "agent": agent, "prompt": prompt, "version": version}
        )

    def user_msg(self, text: str):
        self._push("user", {"text": text})

    def token(self, tok: str):
        self._push("token", {"tok": tok})

    def turn_end(self, ttft_ms: float, total_ms: float, tok_s: float):
        self._push("turn_end", {"ttft_ms": ttft_ms, "total_ms": total_ms, "tok_s": tok_s})

    def tool_call(self, name: str, args: str):
        self._push("tool_call", {"name": name, "args": args})

    def tool_result(self, name: str, result: str):
        self._push("tool_result", {"name": name, "result": result[:300]})

    def agent_switch(self, agent: str, prompt: str = ""):
        self._push("agent_switch", {"agent": agent, "prompt": prompt})

    def prompt_update(self, agent: str, prompt: str):
        self._push("prompt_update", {"agent": agent, "prompt": prompt})

    def messages_context(self, messages: list[dict]):
        """Push the full messages array being sent to the model this turn."""
        lines = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content") or ""
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            lines.append(f"[{role.upper()}]\n{content}")
        self._push("messages_context", {"text": "\n\n─────\n\n".join(lines), "count": len(messages)})


# Global UI instance (None = disabled)
_bench_ui: BenchUI | None = None


# ── Chat mode ─────────────────────────────────────────────────────────────────

CHAT_SYSTEM_PROMPT = (
    "Bạn là trợ lý tư vấn bất động sản Noble, trả lời bằng tiếng Việt. "
    "Viết SỐ BẰNG CHỮ (ví dụ: ba tỷ hai trăm triệu). "
    "Trả lời ngắn gọn, thân thiện, tự nhiên như đang nói chuyện điện thoại. "
    "Dùng tool khi cần tìm kiếm thông tin hoặc thực hiện hành động."
)

# Fake tool responses for chat mode
_FAKE_TOOL_RESPONSES: dict[str, str] = {
    "kb_search": '{"results": [{"title": "Noble Crystal Long Biên", "content": "Dự án căn hộ cao cấp tại Long Biên, Hà Nội. Diện tích 65-150m2, giá từ 55-75 triệu/m2. Tiện ích: hồ bơi, gym, công viên 2ha, trường học quốc tế."}]}',
    "list_projects": '{"projects": [{"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"}, {"code": "NPLB", "name": "Noble Pearl Long Biên", "region": "Long Biên"}, {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"}]}',
    "discover_projects": '{"project": "Noble Crystal Long Biên", "location": "Phúc Đồng, Long Biên",'
    ' "type": "Căn hộ + Biệt thự", "units": 1200,'
    ' "highlights": ["View sông Hồng", "Metro line 1", "Công viên 2ha"]}',
    "get_project_financial": '{"pricing": {"2PN": "3.5-4.8 tỷ", "3PN": "5.2-7.5 tỷ"}, "payment": "30% ký HĐ, 70% theo tiến độ", "promotion": "CK 8% thanh toán sớm"}',
    "search_units": '{"units": [{"code": "A-12-05", "type": "2PN", "area": 72.5, "price": 4200000000, "direction": "Đông Nam", "status": "available"}]}',
    "match_projects": '{"recommendations": [{"code": "NCLB", "name": "Noble Crystal Long Biên", "match_score": 92, "reason": "Phù hợp ngân sách, khu vực Long Biên"}]}',
    "schedule_viewing": '{"success": true, "booking_id": "APT-20260416-001", "message": "Đã đặt lịch thành công"}',
    "update_customer": '{"success": true, "message": "Đã cập nhật thông tin khách hàng"}',
    "update_booking_info": '{"success": true, "message": "Đã lưu thông tin đặt lịch"}',
    "get_booking_state": '{"collected": {}, "missing": ["customer_name", "phone_number", "project_interest", "preferred_date", "preferred_slot"]}',
    "validate_phone": '{"valid": true, "formatted": "0942 866 939"}',
    "check_availability": '{"available_slots": ["09:00-10:00", "10:00-11:00", "14:00-15:00", "15:00-16:00"]}',
    "switch_agent": '{"success": true, "message": "Đã chuyển sang agent consultant"}',
    "list_bookings": '{"bookings": []}',
    "escalate": '{"status": "pending", "message": "Chưa có yêu cầu chuyển tiếp nào"}',
    "send_media": '{"ok": true, "channel": "noblex", "delivery_id": "out-mock-001"}',
}


def _load_full_tools() -> list[dict]:
    """Load real tool schemas from the project."""
    try:
        from noble_agent.agent.tools.schemas import TOOL_DEFINITIONS

        return TOOL_DEFINITIONS
    except Exception:
        return TOOL_DEFS  # fallback to bench's minimal defs


async def _chat_loop(client: AsyncOpenAI, model: str, provider_name: str, use_tools: bool, max_tokens: int):
    """Interactive chat with colored output, tool calls, and timing."""
    tools = _load_full_tools() if use_tools else []
    messages: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]

    tool_names = [t["function"]["name"] for t in tools]
    print(f"\n{C.CYAN}{C.BOLD}╭─ Chat Mode ─────────────────────────────────────────╮{C.RESET}")
    print(f"{C.CYAN}│{C.RESET} Provider: {C.GREEN}{provider_name}{C.RESET} ({C.YELLOW}{model}{C.RESET})")
    if tools:
        print(
            f"{C.CYAN}│{C.RESET} Tools: {C.DIM}{', '.join(tool_names[:6])}{'...' if len(tool_names) > 6 else ''}{C.RESET}"
        )
    print(f"{C.CYAN}│{C.RESET} Type {C.BOLD}/quit{C.RESET} or {C.BOLD}Ctrl+C{C.RESET} to exit")
    print(f"{C.CYAN}╰─────────────────────────────────────────────────────╯{C.RESET}\n")

    if _bench_ui:
        _bench_ui.session(provider_name, model, "simple", CHAT_SYSTEM_PROMPT)

    while True:
        try:
            user_input = input(f"{C.YELLOW}{C.BOLD}You:{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.DIM}Bye!{C.RESET}")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            print(f"{C.DIM}Bye!{C.RESET}")
            break

        messages.append({"role": "user", "content": user_input})
        if _bench_ui:
            _bench_ui.user_msg(user_input)

        # LLM loop (may have multiple rounds for tool calls)
        turn_start = time.monotonic()
        ttft_set = False
        turn_ttft = 0.0

        while True:
            kwargs: dict = {
                "model": model,
                "messages": messages,
                "stream": True,
                _token_limit_key(model): max_tokens,
                "stream_options": {"include_usage": True},
            }
            if tools:
                kwargs["tools"] = tools

            t0 = time.monotonic()
            text_parts: list[str] = []
            tool_call_parts: dict[int, dict] = {}  # idx -> {name, args_chunks}
            input_tokens = 0
            output_tokens = 0

            if _bench_ui:
                _bench_ui.messages_context(messages)

            try:
                stream = await client.chat.completions.create(**kwargs)
                bot_printed = False

                async for event in stream:
                    if not event.choices:
                        if hasattr(event, "usage") and event.usage:
                            input_tokens = event.usage.prompt_tokens or 0
                            output_tokens = event.usage.completion_tokens or 0
                        continue

                    delta = event.choices[0].delta

                    # Text content — stream print
                    if delta and delta.content:
                        if not ttft_set:
                            turn_ttft = (time.monotonic() - turn_start) * 1000
                            ttft_set = True
                        if not bot_printed:
                            print(f"{C.GREEN}{C.BOLD}Bot:{C.RESET} ", end="", flush=True)
                            bot_printed = True
                        print(delta.content, end="", flush=True)
                        text_parts.append(delta.content)
                        if _bench_ui:
                            _bench_ui.token(delta.content)

                    # Tool calls
                    if delta and delta.tool_calls:
                        if not ttft_set:
                            turn_ttft = (time.monotonic() - turn_start) * 1000
                            ttft_set = True
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_call_parts:
                                tool_call_parts[idx] = {"id": "", "name": "", "args": []}
                            if tc.id:
                                tool_call_parts[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_call_parts[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_call_parts[idx]["args"].append(tc.function.arguments)

            except Exception as e:
                print(f"\n  {C.RED}❌ ERROR: {e}{C.RESET}")
                break

            full_text = "".join(text_parts)
            turn_total = (time.monotonic() - turn_start) * 1000

            # Handle tool calls
            if tool_call_parts:
                if full_text:
                    print()  # newline after streamed text

                # Build assistant message with tool_calls
                assistant_msg: dict = {"role": "assistant", "content": full_text or None, "tool_calls": []}
                for idx in sorted(tool_call_parts):
                    tc = tool_call_parts[idx]
                    args_str = "".join(tc["args"])
                    assistant_msg["tool_calls"].append(
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": args_str},
                        }
                    )

                    # Print tool call
                    print(f"{C.GREEN}{C.BOLD}Bot:{C.RESET}")
                    print(
                        f"  {C.MAGENTA}[Tool Call]{C.RESET} {C.CYAN}{tc['name']}{C.RESET}({C.DIM}{args_str}{C.RESET})"
                    )
                    if _bench_ui:
                        _bench_ui.tool_call(tc["name"], args_str)

                messages.append(assistant_msg)

                # Execute tool responses (real RAG for noble_search when enabled, else fake)
                for tc_msg in assistant_msg["tool_calls"]:
                    fn_name = tc_msg["function"]["name"]
                    import time as _t

                    _t0 = _t.monotonic()
                    if _RAG_ENABLED and fn_name == "kb_search" and _BENCH_RAG_AVAILABLE:
                        try:
                            parsed_args = json.loads(tc_msg["function"]["arguments"] or "{}")
                            tool_result_str = await real_noble_search(parsed_args)
                        except Exception as exc:
                            tool_result_str = json.dumps({"error": f"RAG search failed: {exc}"}, ensure_ascii=False)
                    else:
                        tool_result_str = _FAKE_TOOL_RESPONSES.get(fn_name, '{"result": "ok"}')
                    _tool_ms = (_t.monotonic() - _t0) * 1000
                    if _BENCH_RAG_AVAILABLE:
                        try:
                            _parsed_args = json.loads(tc_msg["function"]["arguments"] or "{}")
                        except Exception:
                            _parsed_args = {}
                        get_timing_collector().record(fn_name, _parsed_args, _tool_ms)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_msg["id"],
                            "content": tool_result_str,
                        }
                    )
                    if _bench_ui:
                        _bench_ui.tool_result(fn_name, tool_result_str)

                # Print timing for tool call round
                elapsed = (time.monotonic() - turn_start) * 1000
                print(f"  {C.GRAY}[{elapsed / 1000:.2f}s total, TTFT {turn_ttft / 1000:.2f}s]{C.RESET}")

                # Continue loop — LLM will process tool results
                continue

            else:
                # No tool calls — end of turn
                if full_text:
                    print()  # newline after streamed text

                    # Estimate tokens if not provided
                    if output_tokens == 0:
                        output_tokens = max(1, len(full_text) // 3)
                    tok_s = output_tokens / (turn_total / 1000) if turn_total > 0 else 0

                    print(
                        f"  {C.GRAY}[{turn_total / 1000:.2f}s total, TTFT {turn_ttft / 1000:.2f}s, "
                        f"{tok_s:.0f} tok/s]{C.RESET}"
                    )
                    if _bench_ui:
                        _bench_ui.turn_end(turn_ttft, turn_total, tok_s)

                    messages.append({"role": "assistant", "content": full_text})
                break

        if _BENCH_RAG_AVAILABLE:
            get_timing_collector().print_turn_breakdown(C)
            get_timing_collector().new_turn()
        print()  # blank line between turns


# ── Prompt version support ────────────────────────────────────────────────────

_VERSIONS_DIR = os.path.join(os.path.dirname(__file__), "prompt_versions")
_VERSIONS_REGISTRY = os.path.join(_VERSIONS_DIR, "registry.json")


def _load_version_registry() -> dict:
    """Load prompt version registry if available."""
    if os.path.exists(_VERSIONS_REGISTRY):
        with open(_VERSIONS_REGISTRY) as f:
            return json.load(f)
    return {"versions": {}, "default": "v0"}


def _patch_prompt_version(version: str) -> bool:
    """Monkey-patch agent.registry to read from a test prompt version.
    Returns True if patched, False if version not found.

    For v7-bench: also applies code patches A1+A2+A3+A4 via bench_rag.version_patches.v7.
    """
    from pathlib import Path

    version_dir = Path(_VERSIONS_DIR) / version
    if not version_dir.exists():
        print(f"{C.RED}  Version '{version}' not found at {version_dir}{C.RESET}")
        return False

    import noble_agent.agent.registry as _reg

    _reg._REGISTRY_DIR = version_dir
    if hasattr(_reg._load_config, "cache_clear"):
        _reg._load_config.cache_clear()
    if hasattr(_reg._load_project_faq, "cache_clear"):
        _reg._load_project_faq.cache_clear()

    # v7-bench: apply runtime patches A1+A2+A3+A4 (no src/ change)
    if version == "v7-bench":
        try:
            from bench_rag.version_patches.v7 import apply_v7_patches

            apply_v7_patches()
            print(f"{C.GREEN}  v7 runtime patches applied (A1+A2+A3+A4){C.RESET}")
        except Exception as e:
            print(f"{C.YELLOW}  v7 patches unavailable: {e}{C.RESET}")

    # v8-bench: apply runtime patches A2+A3+A4+A5 (A1 removed, FAQ via search at tail)
    if version == "v8-bench":
        try:
            from bench_rag.version_patches.v8 import apply_v8_patches

            apply_v8_patches()
            print(f"{C.GREEN}  v8 runtime patches applied (A2+A3+A4+A5){C.RESET}")
        except Exception as e:
            print(f"{C.YELLOW}  v8 patches failed: {e}{C.RESET}")

    return True


def _unpatch_prompt_version():
    """Restore registry to production path + revert v7/v8 patches if applied."""
    # Revert v7 patches first (if any)
    try:
        from bench_rag.version_patches.v7 import revert_v7_patches

        revert_v7_patches()
    except Exception:
        pass
    # Revert v8 patches (if any)
    try:
        from bench_rag.version_patches.v8 import revert_v8_patches

        revert_v8_patches()
    except Exception:
        pass

    from pathlib import Path

    import noble_agent.agent.registry as _reg

    _reg._REGISTRY_DIR = Path(_reg.__file__).resolve().parent / "definitions"
    if hasattr(_reg._load_config, "cache_clear"):
        _reg._load_config.cache_clear()
    if hasattr(_reg._load_project_faq, "cache_clear"):
        _reg._load_project_faq.cache_clear()


def _select_prompt_version() -> str | None:
    """Interactive prompt version selector. Returns version string or None for production."""
    reg = _load_version_registry()
    versions = list(reg.get("versions", {}).keys())
    if not versions:
        return None

    print(f"\n{C.CYAN}📋 Prompt version:{C.RESET}")
    print(f"  [0] {C.GREEN}production{C.RESET} (src/agent/definitions/ — no patching)")
    for i, v in enumerate(versions, 1):
        info = reg["versions"][v]
        exists = os.path.exists(os.path.join(_VERSIONS_DIR, v))
        status = f"{C.GREEN}✓{C.RESET}" if exists else f"{C.RED}✗{C.RESET}"
        tok = info.get("expected_tokens", {})
        print(
            f"  [{i}] {status} {v:4} — {info['name']:<32} [R:{tok.get('router', '?')} C:{tok.get('consultant', '?')}]"
        )
    print()
    choice = input("Select [0=production]: ").strip()
    if not choice or choice == "0":
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(versions):
        return versions[int(choice) - 1]
    if choice in versions:
        return choice
    return None


# ── Deferred-narration mode (v9) ──────────────────────────────────────────────
# Wraps `agent.tools.send_media.execute` so the LLM gets a deferred placeholder
# IMMEDIATELY (no HTTP wait), while the real backend call runs in background.
# When backend resolves, build a narration string from the REAL result and queue
# it for injection into history at the start of the next turn — mimicking the
# production design where backend pushes SentenceChunk to tts_queue (LLM-bypass).
#
# This is opt-in via `--deferred`. Real API calls go to the configured
# HOTLINE_OUTREACH_URL with the phone given by `--phone` (default 0942866939).
# DOES NOT modify any file under src/.

_DEFERRED_ENABLED = False
_DEFERRED_ORIGINAL_EXECUTE = None
_DEFERRED_ORIGINAL_READ_FILE = None
_DEFERRED_PENDING: list[dict] = []  # narrations waiting for next turn
_DEFERRED_TASKS: list = []  # in-flight background backend calls
_DEFERRED_LAST_CALL_WAS_SVA = False  # set by tool-done hook
_DEFERRED_COMPLIANCE = {"silent": 0, "premature": 0, "warn": 0, "ok_short": 0}

_DEFERRED_RULE = """

═══ DEFERRED NARRATION RULE (test mode active) ═══
Khi gọi tool send_media:
1. TRƯỚC khi tool trả: nói 1 câu filler ngắn ("Dạ em ghi nhận, đang gửi cho anh ngay nha").
2. Tool sẽ trả về JSON có `deferred: true` — đây KHÔNG phải kết quả cuối, chỉ là ack scheduled.
3. SAU khi nhận `deferred: true`: ngừng nói. Output PHẢI rỗng hoặc tối đa 1 từ ("Dạ ạ").
4. TUYỆT ĐỐI KHÔNG nói "đã gửi", "đã chuyển", "qua NobleX", "qua Zalo", "qua SMS" — vì backend chưa xong, nói trước là sai sự thật.
5. Backend sẽ tự gửi câu confirm sau (qua TTS bypass), không cần bạn phải narrate kết quả.
═══════════════════════════════════════════════════
"""


def _deferred_build_narration(result: dict) -> str:
    """Build the confirm/fallback narration from a REAL OutreachResult dict."""
    if result.get("ok") and not result.get("deferred"):
        ch = (result.get("channel") or "").lower()
        return {
            "noblex": "Em đã gửi qua ứng dụng NobleX rồi ạ, anh kiểm tra giúp em nha.",
            "sms": "Em đã gửi qua tin nhắn điện thoại rồi ạ, anh kiểm tra giúp em.",
        }.get(ch, "Em đã gửi cho anh rồi ạ, anh kiểm tra giúp em nha.")
    fb = result.get("fallback_narration")
    if fb:
        return str(fb)
    return "Dạ em chưa gửi được, em sẽ nhờ chuyên viên CSKH liên hệ anh ạ."


def _deferred_check_compliance(text: str) -> str:
    """Classify LLM-2 output. Returns 'silent' | 'ok_short' | 'premature' | 'warn'."""
    import re as _re

    t = (text or "").strip()
    if not t:
        return "silent"
    PREMATURE = _re.compile(
        r"(đã\s*gửi|đã\s*chuyển|gửi\s*xong|gửi\s*rồi|qua\s*NobleX|qua\s*Zalo|qua\s*SMS|qua\s*app|qua\s*tin\s*nhắn)",
        _re.IGNORECASE,
    )
    if PREMATURE.search(t):
        return "premature"
    if len(t) <= 20:
        return "ok_short"
    return "warn"


async def _deferred_real_call_then_queue(args: dict, session_id: str, tool_call_id: str):
    """Background task: invoke REAL send_media.execute, then enqueue narration."""
    import json as _json

    try:
        assert _DEFERRED_ORIGINAL_EXECUTE is not None
        raw = await _DEFERRED_ORIGINAL_EXECUTE(args, session_id)
        try:
            real_result = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            real_result = {"ok": False, "error_detail": str(raw)[:200]}
    except Exception as exc:
        real_result = {"ok": False, "code": "exception", "error_detail": f"{type(exc).__name__}: {exc}"}

    narration = _deferred_build_narration(real_result)
    _DEFERRED_PENDING.append(
        {
            "tool_call_id": tool_call_id,
            "narration": narration,
            "real_result": real_result,
            "ts": time.monotonic(),
        }
    )
    print(
        f"\n  {C.MAGENTA}[DEFERRED-DONE]{C.RESET} "
        f"ok={real_result.get('ok')} "
        f"channel={real_result.get('channel') or '—'} "
        f"code={real_result.get('code') or '—'} "
        f"attempts={real_result.get('attempts') or 1} "
        f"→ queued: {C.DIM}{narration[:80]}{C.RESET}"
    )


async def _deferred_execute_wrapper(args: dict, session_id: str) -> str:
    """Replacement for agent.tools.send_media.execute. Returns deferred ack
    immediately, fires real backend call in background. Real call_id is unknown
    to us here (dispatcher doesn't pass it), so we generate a synthetic one."""
    import json as _json
    import uuid as _uuid

    fake_id = f"deferred-{_uuid.uuid4().hex[:8]}"
    task = asyncio.create_task(_deferred_real_call_then_queue(dict(args), session_id, fake_id))
    _DEFERRED_TASKS.append(task)
    payload = {
        "ok": True,
        "deferred": True,
        "channel": "pending",
        "ack": "scheduled",
        "tool_call_id": fake_id,
        "hint": (
            "Yêu cầu đã được scheduled. KHÔNG nói 'đã gửi' — backend sẽ tự gửi "
            "narration confirm sau khi xong. Hãy ngừng nói (output rỗng)."
        ),
    }
    return _json.dumps(payload, ensure_ascii=False)


def _deferred_drain_pending(llm, *, label: str = "INJECT-TTS") -> int:
    """Inject queued narrations into llm._history as assistant messages and
    print them as bot output (mimicking production tts_queue push)."""
    drained = 0
    while _DEFERRED_PENDING:
        item = _DEFERRED_PENDING.pop(0)
        narr = item["narration"]
        try:
            llm._history.append({"role": "assistant", "content": narr})
        except Exception:
            pass
        print(f"  {C.CYAN}Bot (deferred):{C.RESET} {C.BOLD}{narr}{C.RESET} {C.DIM}[{label} → tts_queue]{C.RESET}")
        drained += 1
    return drained


async def _deferred_wait_and_drain(llm, timeout: float = 3.0) -> int:
    """Same-turn drain: await in-flight backend calls (up to `timeout`),
    then drain. This matches production behavior where the narration is
    pushed to tts_queue in the same turn the tool fired."""
    if not _DEFERRED_TASKS:
        return _deferred_drain_pending(llm, label="SAME-TURN")
    pending = [t for t in _DEFERRED_TASKS if not t.done()]
    _DEFERRED_TASKS.clear()
    if pending:
        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"  {C.YELLOW}[DEFERRED] backend slow (>{timeout}s) — narration will appear next turn{C.RESET}")
    return _deferred_drain_pending(llm, label="SAME-TURN")


async def _enable_deferred_mode(session_id: str, phone: str) -> None:
    """Install monkeypatches on send_media.execute + registry._read_file
    (to inject the DEFERRED RULE into the system prompt). Seed customer.phone
    so the real send_media call has a phone to send to."""
    global _DEFERRED_ENABLED, _DEFERRED_ORIGINAL_EXECUTE, _DEFERRED_ORIGINAL_READ_FILE
    if _DEFERRED_ENABLED:
        return

    # 1) Patch tool execute
    import noble_agent.agent.tools.send_media as _sva

    _DEFERRED_ORIGINAL_EXECUTE = _sva.execute
    _sva.execute = _deferred_execute_wrapper  # type: ignore[assignment]

    # 2) Patch registry._read_file to append the RULE to send_media TOOL.md
    import noble_agent.agent.registry as _reg

    _DEFERRED_ORIGINAL_READ_FILE = _reg._read_file

    def _patched_read_file(path):
        content = _DEFERRED_ORIGINAL_READ_FILE(path)
        try:
            p = str(path)
            if p.endswith("send_media/TOOL.md") and content:
                return content + _DEFERRED_RULE
        except Exception:
            pass
        return content

    _reg._read_file = _patched_read_file  # type: ignore[assignment]

    # 3) Seed customer phone so real backend call has where to send
    try:
        from noble_agent.storage import session_store as _ss

        await _ss.save_customer(session_id, {"phone": phone})
    except Exception as exc:
        print(f"  {C.YELLOW}[DEFERRED] phone seed failed (will rely on V7): {exc}{C.RESET}")

    _DEFERRED_ENABLED = True
    print(
        f"  {C.GREEN}[DEFERRED MODE ON]{C.RESET} "
        f"phone={C.BOLD}{phone}{C.RESET} "
        f"send_media → wrapper → real HTTP in background"
    )


def _disable_deferred_mode() -> None:
    global _DEFERRED_ENABLED, _DEFERRED_ORIGINAL_EXECUTE, _DEFERRED_ORIGINAL_READ_FILE
    if not _DEFERRED_ENABLED:
        return
    try:
        import noble_agent.agent.tools.send_media as _sva

        if _DEFERRED_ORIGINAL_EXECUTE is not None:
            _sva.execute = _DEFERRED_ORIGINAL_EXECUTE
    except Exception:
        pass
    try:
        import noble_agent.agent.registry as _reg

        if _DEFERRED_ORIGINAL_READ_FILE is not None:
            _reg._read_file = _DEFERRED_ORIGINAL_READ_FILE
    except Exception:
        pass
    _DEFERRED_ENABLED = False
    _DEFERRED_ORIGINAL_EXECUTE = None
    _DEFERRED_ORIGINAL_READ_FILE = None


def _deferred_print_compliance_summary() -> None:
    total = sum(_DEFERRED_COMPLIANCE.values())
    if total == 0:
        return
    print(f"\n{C.CYAN}── Deferred Compliance Summary ──{C.RESET}")
    for k, v in _DEFERRED_COMPLIANCE.items():
        pct = (v / total) * 100
        color = C.GREEN if k in ("silent", "ok_short") else C.RED if k == "premature" else C.YELLOW
        print(f"  {color}{k:10}{C.RESET} {v:3d} / {total} ({pct:5.1f}%)")
    pass_rate = (_DEFERRED_COMPLIANCE["silent"] + _DEFERRED_COMPLIANCE["ok_short"]) / total * 100
    gate = f"{C.GREEN}PASS{C.RESET}" if pass_rate >= 80 else f"{C.RED}FAIL{C.RESET}"
    print(f"  {C.BOLD}Pass rate (silent + ok_short ≥80%): {pass_rate:.1f}% — {gate}{C.RESET}\n")


# ── Full pipeline chat mode ───────────────────────────────────────────────────


async def _chat_loop_full(
    provider_name: str,
    model_label: str,
    version: str | None = None,
    deferred: bool = False,
    deferred_phone: str = "0942866939",
):
    """Interactive chat using the real voiceagentrag pipeline (StreamingLLM + tools + agent registry).
    If version is provided, monkey-patches registry to use that prompt version.
    """
    # Patch prompt version if requested
    patched = False
    if version:
        patched = _patch_prompt_version(version)
        if not patched:
            print(f"{C.YELLOW}  Falling back to production prompts{C.RESET}")

    try:
        from noble_agent.agent.llm.streaming import StreamingLLM
    except ImportError as e:
        print(f"{C.RED}❌ Cannot load pipeline: {e}{C.RESET}")
        print(f"{C.DIM}   Make sure you're in the project venv with all deps installed.{C.RESET}")
        if patched:
            _unpatch_prompt_version()
        return

    # Bring Redis online so session_store writes persist (save_customer,
    # update_booking_info, A4 auto-set, etc.). Without this, all session
    # mutations silently no-op and FAQ injection never sees project_interest.
    try:
        from noble_agent.storage.connection import get_connection_manager

        _conn_mgr = get_connection_manager()
        await _conn_mgr.connect_redis()
        if _conn_mgr.redis is None:
            print(f"  {C.YELLOW}[Redis offline — session state will not persist]{C.RESET}")
    except Exception as _redis_init_exc:
        print(f"  {C.YELLOW}[Redis init failed: {_redis_init_exc}]{C.RESET}")

    session_id = f"bench-{int(time.time())}"
    llm = await StreamingLLM.create(session_id)

    # Deferred-narration mode: install send_media wrapper + RULE injection
    if deferred:
        await _enable_deferred_mode(session_id, deferred_phone)
        # Force prompt rebuild so the patched _read_file (with RULE) takes effect
        if hasattr(llm, "refresh_system_prompt"):
            await llm.refresh_system_prompt()

    # Interactive RAG backend selection (v8 fix) — avoid requiring env var
    # If NOBLE_RAG_BACKEND env is unset, prompt user to pick. Skipped in non-TTY envs.
    if os.environ.get("NOBLE_RAG_BACKEND") is None and sys.stdin.isatty():
        print(f"\n{C.CYAN}🔧 RAG backend for noble_search:{C.RESET}")
        print(f"  [1] memory_router {C.DIM}(FAISS cache + Qdrant, default production){C.RESET}")
        print(f"  [2] flat_store    {C.DIM}(e5-large dense + bm25s, A/B test target){C.RESET}")
        try:
            _b_choice = input("Select backend [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            _b_choice = "1"
        if _b_choice == "2":
            os.environ["NOBLE_RAG_BACKEND"] = "flat_store"
            print(f"  {C.GREEN}→ flat_store selected{C.RESET}")
        else:
            os.environ["NOBLE_RAG_BACKEND"] = "memory_router"
            print(f"  {C.GREEN}→ memory_router selected{C.RESET}")
        # Reload settings so noble_kb picks up new value
        try:
            from noble_agent.config import settings as _settings_reload

            _settings_reload.noble_rag_backend = os.environ["NOBLE_RAG_BACKEND"]
        except Exception:
            pass

        # FAQ search inject toggle (v8-bench only)
        if os.environ.get("NOBLE_FAQ_SEARCH") is None and sys.stdin.isatty() and version == "v8-bench":
            print(f"\n{C.CYAN}🔎 FAQ search inject (v8-bench):{C.RESET}")
            print("  [1] on — search per-project FAQ, inject top-K at prompt tail (default)")
            print("  [2] off — skip FAQ warmup + inject")
            _faq_choice = input("Enable FAQ search [1]: ").strip() or "1"
            os.environ["NOBLE_FAQ_SEARCH"] = "off" if _faq_choice == "2" else "on"

    # Warmup (Sprint 1) — run before first turn to avoid cold-start pollution
    # FAQ searcher shares FlatStore's ONNX session, so need_flat_store is implied when need_faq_search.
    if _BENCH_RAG_AVAILABLE:
        _is_flat_backend = os.environ.get("NOBLE_RAG_BACKEND") == "flat_store"
        _faq_enabled = os.environ.get("NOBLE_FAQ_SEARCH", "on").lower() != "off"
        _need_faq = (version == "v8-bench") and _faq_enabled
        _wucfg = WarmupConfig(
            need_flat_store=(_is_flat_backend or _need_faq),
            need_faq_search=_need_faq,
            need_memory_router=(not _is_flat_backend),
            providers=[],
        )
        if _wucfg.need_flat_store or _wucfg.need_memory_router or _wucfg.need_faq_search:
            _wu_phases = await warmup_all(_wucfg)
            print_warmup_report(_wu_phases, C)

    # Show loaded agent info
    agent = getattr(llm, "_current_agent", "unknown")
    version_label = f"{C.MAGENTA}{version}{C.RESET}" if version and patched else f"{C.DIM}production{C.RESET}"
    print(f"\n{C.CYAN}{C.BOLD}╭─ Full Pipeline Chat ────────────────────────────────╮{C.RESET}")
    print(f"{C.CYAN}│{C.RESET} Provider: {C.GREEN}{provider_name}{C.RESET} ({C.YELLOW}{model_label}{C.RESET})")
    print(f"{C.CYAN}│{C.RESET} Prompt:   {version_label}")
    print(f"{C.CYAN}│{C.RESET} Agent: {C.MAGENTA}{agent}{C.RESET}")
    print(f"{C.CYAN}│{C.RESET} Session: {C.DIM}{session_id}{C.RESET}")
    print(f"{C.CYAN}│{C.RESET} Pipeline: registry → system prompt → tools → agent switch")
    print(
        f"{C.CYAN}│{C.RESET} Commands: {C.BOLD}/quit{C.RESET} {C.BOLD}/agent{C.RESET} {C.BOLD}/prompt{C.RESET} (dump system prompt) {C.BOLD}/history{C.RESET}"
    )
    print(f"{C.CYAN}╰─────────────────────────────────────────────────────╯{C.RESET}\n")

    # Push session info to UI
    if _bench_ui:
        sys_prompt = llm._history[0]["content"] if llm._history else ""
        _bench_ui.session(provider_name, model_label, agent, sys_prompt, version or "")

    while True:
        # Drain any narrations queued by completed background backend calls
        # before the user sees the prompt. Inject as assistant messages so the
        # next turn's history has the post-hoc confirm context.
        if deferred:
            _deferred_drain_pending(llm, label="LATE-TURN-FALLBACK")

        try:
            user_input = input(f"{C.YELLOW}{C.BOLD}You:{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.DIM}Bye!{C.RESET}")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            if deferred:
                _deferred_print_compliance_summary()
                _disable_deferred_mode()
            print(f"{C.DIM}Bye!{C.RESET}")
            break
        if deferred and user_input.lower() == "/compliance":
            _deferred_print_compliance_summary()
            continue
        if user_input.lower() == "/agent":
            agent = getattr(llm, "_current_agent", "unknown")
            print(f"  {C.CYAN}Current agent: {C.MAGENTA}{agent}{C.RESET}\n")
            continue
        if user_input.lower() in ("/prompt", "/sys"):
            sys_msg = next((m for m in llm._history if m.get("role") == "system"), None)
            if not sys_msg:
                print(f"  {C.YELLOW}(no system prompt yet){C.RESET}\n")
                continue
            content = sys_msg.get("content", "") or ""
            faq_present = (
                "═══ FAQ DỰ ÁN" in content
                or "═══ FAQ KHỚP NHẤT" in content
                or "═══ FAQ CHUNG" in content
                or "── FAQ" in content
            )
            print(
                f"\n{C.CYAN}── SYSTEM PROMPT ({len(content)} chars, FAQ={'YES' if faq_present else 'NO'}) ──{C.RESET}"
            )
            print(C.DIM + content + C.RESET)
            print(f"{C.CYAN}── END ──{C.RESET}\n")
            continue
        if user_input.lower() == "/history":
            print(f"\n{C.CYAN}── HISTORY ({len(llm._history)} messages) ──{C.RESET}")
            for i, m in enumerate(llm._history):
                role = m.get("role", "?")
                content = str(m.get("content", ""))[:400]
                color = C.MAGENTA if role == "system" else (C.YELLOW if role == "user" else C.GREEN)
                print(
                    f"{color}[{i}] {role}:{C.RESET} {C.DIM}{content}{'...' if len(str(m.get('content', ''))) > 400 else ''}{C.RESET}"
                )
            print(f"{C.CYAN}── END ──{C.RESET}\n")
            continue

        # Per-turn stage timings (ms). Printed as breakdown at end of turn.
        _stage_ms: dict[str, float] = {
            "sniff": 0.0,
            "faq_search": 0.0,
            "faq_chars": 0,
            "llm_ttft": 0.0,
            "llm_total": 0.0,
            "tools_total": 0.0,
            "tools_n": 0,
            "rebuild": 0.0,
        }
        _stage_t0 = time.monotonic()

        # Pre-turn project sniff — normalize user text via catalog (W4).
        if _BENCH_RAG_AVAILABLE:
            _sniff_t0 = time.monotonic()
            try:
                from noble_agent.agent import project_catalog as _catalog
                from noble_agent.storage import session_store as _ss

                _customer = await _ss.load_customer(session_id)
                _current_pi = _customer.get("project_interest", "")
                _matched = _catalog.normalize(user_input)
                if _matched and _matched != _current_pi:
                    await _ss.save_customer(session_id, {"project_interest": _matched})
                    if hasattr(llm, "refresh_system_prompt"):
                        await llm.refresh_system_prompt()
                    _display = _catalog.by_code(_matched)
                    _name = _display.name_vi if _display else _matched
                    print(
                        f"  {C.YELLOW}[Project inferred: {C.MAGENTA}{_name} ({_matched}){C.RESET}{C.YELLOW}]{C.RESET}"
                    )
            except Exception as _sniff_exc:
                import logging as _logging

                _logging.getLogger("bench").warning("[bench] pre-turn sniff error: %s", _sniff_exc)
            _stage_ms["sniff"] = (time.monotonic() - _sniff_t0) * 1000

        # FAQ search inject (v8-bench only, Sprint 2)
        _faq_enabled_runtime = os.environ.get("NOBLE_FAQ_SEARCH", "on").lower() != "off"
        if _BENCH_RAG_AVAILABLE and version == "v8-bench" and _faq_enabled_runtime:
            _faq_t0 = time.monotonic()
            try:
                from bench_rag.faq_search import inject_faq_searched as _inject_faq_s
                from noble_agent.storage import session_store as _ss2

                _cust2 = await _ss2.load_customer(session_id)
                _proj2 = _cust2.get("project_interest", "")
                if _proj2:
                    _faq_block = await _inject_faq_s(user_input, _proj2, top_k=5, threshold=0.35)
                    if _faq_block and llm._history:
                        import re as _re

                        _sys_content = llm._history[0]["content"] or ""
                        _sys_content = _re.sub(
                            r"\n*═══ FAQ KHỚP NHẤT.*?═══ END FAQ ═══\n*",
                            "\n\n",
                            _sys_content,
                            flags=_re.DOTALL,
                        )
                        _sys_content = _sys_content.rstrip() + "\n\n" + _faq_block
                        llm._history[0] = {"role": "system", "content": _sys_content}
                        _stage_ms["faq_chars"] = len(_faq_block)
                        print(f"  {C.CYAN}[FAQ matched: {len(_faq_block)} chars injected]{C.RESET}")
            except Exception as _faq_exc:
                import logging as _logging

                _logging.getLogger("bench").warning("[bench] faq inject error: %s", _faq_exc)
            _stage_ms["faq_search"] = (time.monotonic() - _faq_t0) * 1000

        if _bench_ui:
            _bench_ui.user_msg(user_input)

        # Callbacks for streaming display
        turn_start = time.monotonic()
        ttft_set = False
        turn_ttft = 0.0
        bot_printed = False
        token_count = 0

        def _on_token(tok: str):
            nonlocal ttft_set, turn_ttft, bot_printed, token_count
            if not ttft_set:
                turn_ttft = (time.monotonic() - turn_start) * 1000
                ttft_set = True
            if not bot_printed:
                print(f"{C.GREEN}{C.BOLD}Bot:{C.RESET} ", end="", flush=True)
                bot_printed = True
            print(tok, end="", flush=True)
            token_count += 1
            if _bench_ui:
                _bench_ui.token(tok)

        _tool_t0: dict[str, float] = {}

        def _on_tool_start(name: str, args: str):
            nonlocal bot_printed
            if bot_printed:
                print()
                bot_printed = False
            _tool_t0[name] = time.monotonic()
            print(f"{C.GREEN}{C.BOLD}Bot:{C.RESET}")
            print(f"  {C.MAGENTA}[Tool Call]{C.RESET} {C.CYAN}{name}{C.RESET}({C.DIM}{args}{C.RESET})")
            if _bench_ui:
                _bench_ui.tool_call(name, args)

        def _on_tool_done(name: str, result: str):
            global _DEFERRED_LAST_CALL_WAS_SVA
            if deferred and name == "send_media":
                _DEFERRED_LAST_CALL_WAS_SVA = True
            _t0 = _tool_t0.pop(name, None)
            _ms = (time.monotonic() - _t0) * 1000 if _t0 is not None else 0.0
            _stage_ms["tools_total"] += _ms
            _stage_ms["tools_n"] += 1
            if _BENCH_RAG_AVAILABLE and _ms > 0:
                try:
                    get_timing_collector().record(name, {}, _ms)
                except Exception:
                    pass
            preview = result[:120].replace("\n", " ") if result else ""
            print(f"  {C.GRAY}[Tool Result] {name} → {preview}... ({_ms:.0f}ms){C.RESET}")
            if _bench_ui:
                _bench_ui.tool_result(name, result or "")

        def _on_agent_switch():
            new_agent = getattr(llm, "_current_agent", "?")
            print(f"  {C.YELLOW}⚡ Agent switched → {C.MAGENTA}{new_agent}{C.RESET}")
            if _bench_ui:
                new_prompt = getattr(llm, "_system_prompt", "") or ""
                _bench_ui.agent_switch(new_agent, new_prompt)

        if _bench_ui:
            _bench_ui.messages_context(llm._history + [{"role": "user", "content": user_input}])

        # Capture project_interest BEFORE turn — so we can detect mid-turn changes (A4)
        try:
            from noble_agent.storage import session_store as _ss_pre

            _pi_before = (await _ss_pre.load_customer(session_id)).get("project_interest", "")
        except Exception:
            _pi_before = ""

        global _DEFERRED_LAST_CALL_WAS_SVA
        if deferred:
            _DEFERRED_LAST_CALL_WAS_SVA = False  # reset per turn

        try:
            full_text = await llm.stream_response(
                user_text=user_input,
                on_token=_on_token,
                on_tool_start=_on_tool_start,
                on_tool_done=_on_tool_done,
                on_agent_switch=_on_agent_switch,
            )
        except Exception as e:
            print(f"\n  {C.RED}❌ ERROR: {e}{C.RESET}")
            print()
            continue

        # Compliance check: after send_media(deferred), did the LLM stay quiet?
        if deferred and _DEFERRED_LAST_CALL_WAS_SVA:
            verdict = _deferred_check_compliance(full_text or "")
            _DEFERRED_COMPLIANCE[verdict] = _DEFERRED_COMPLIANCE.get(verdict, 0) + 1
            color = C.GREEN if verdict in ("silent", "ok_short") else C.RED if verdict == "premature" else C.YELLOW
            print(
                f"  {color}[COMPLIANCE]{C.RESET} verdict={C.BOLD}{verdict}{C.RESET} "
                f"text={C.DIM}{(full_text or '')[:120]!r}{C.RESET}"
            )
            if verdict == "silent":
                print(
                    f"  {C.DIM}(empty LLM response is EXPECTED here per DEFERRED RULE — "
                    f"any retry/empty-response logs from streaming.py are noise){C.RESET}"
                )
            # Same-turn drain: await backend (≤3s) then print narration as Bot,
            # matching production where tts_queue is fed in the same turn.
            await _deferred_wait_and_drain(llm, timeout=3.0)

        _stage_ms["llm_total"] = (time.monotonic() - turn_start) * 1000
        _stage_ms["llm_ttft"] = turn_ttft

        # Post-turn prompt rebuild — if project_interest changed mid-turn
        # (e.g. A4 auto-set after tool call), refresh llm._history[0]
        # so the NEXT turn sees the updated FAQ/customer block.
        _rebuild_t0 = time.monotonic()
        try:
            from noble_agent.agent import project_catalog as _catalog_post
            from noble_agent.storage import session_store as _ss_post

            _pi_after = (await _ss_post.load_customer(session_id)).get("project_interest", "")
            if _pi_after and _pi_after != _pi_before and hasattr(llm, "refresh_system_prompt"):
                await llm.refresh_system_prompt()
                _meta = _catalog_post.by_code(_pi_after)
                _name_after = _meta.name_vi if _meta else _pi_after
                print(
                    f"  {C.YELLOW}[Prompt rebuilt: project {_pi_before or '—'} → {_name_after} ({_pi_after})]{C.RESET}"
                )
        except Exception as _rebuild_exc:
            import logging as _logging

            _logging.getLogger("bench").warning("[bench] post-turn rebuild error: %s", _rebuild_exc)
        _stage_ms["rebuild"] = (time.monotonic() - _rebuild_t0) * 1000

        turn_total = (time.monotonic() - _stage_t0) * 1000
        if full_text:
            if bot_printed:
                print()  # newline after streamed text
            out_tokens = max(1, len(full_text) // 3) if token_count == 0 else token_count
            tok_s = out_tokens / (turn_total / 1000) if turn_total > 0 else 0

            # Detailed per-stage breakdown.
            _pre = _stage_ms["sniff"] + _stage_ms["faq_search"]
            _llm_net = max(0.0, _stage_ms["llm_total"] - _stage_ms["tools_total"])
            _faq_tag = f" ({_stage_ms['faq_chars']}ch)" if _stage_ms["faq_chars"] else ""
            _tools_tag = (
                f" ({_stage_ms['tools_n']} call{'s' if _stage_ms['tools_n'] != 1 else ''})"
                if _stage_ms["tools_n"]
                else ""
            )
            print(
                f"  {C.GRAY}[Timing] "
                f"sniff={_stage_ms['sniff']:.0f}ms "
                f"faq={_stage_ms['faq_search']:.0f}ms{_faq_tag} "
                f"ttft={_stage_ms['llm_ttft']:.0f}ms "
                f"llm={_llm_net:.0f}ms "
                f"tools={_stage_ms['tools_total']:.0f}ms{_tools_tag} "
                f"rebuild={_stage_ms['rebuild']:.0f}ms{C.RESET}"
            )
            print(
                f"  {C.GRAY}[Total]  {turn_total / 1000:.2f}s "
                f"(pre={_pre:.0f}ms, llm+tools={_stage_ms['llm_total']:.0f}ms, "
                f"{tok_s:.0f} tok/s, {out_tokens} tok){C.RESET}"
            )
            if _bench_ui:
                _bench_ui.turn_end(turn_ttft, turn_total, tok_s)

        if _BENCH_RAG_AVAILABLE:
            get_timing_collector().print_turn_breakdown(C)
            get_timing_collector().new_turn()
        print()  # blank line between turns

    # Session end — print tool timing summary
    if _BENCH_RAG_AVAILABLE:
        get_timing_collector().print_summary(C)
        reset_timing()

    # Restore registry if patched
    if patched:
        _unpatch_prompt_version()


# ── Main ──────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(
        description="LLM Provider Benchmark — supports cloud (.env) and local (Ollama/vLLM/SGLang/LM Studio)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                                    # interactive
  %(prog)s --provider groq --case all --runs 3                # Groq, all cases, 3 runs
  %(prog)s --url http://localhost:11434/v1 --model llama3.2   # Ollama
  %(prog)s --url http://localhost:8000/v1 --model Qwen/Qwen3-8B  # vLLM
  %(prog)s --url http://localhost:30000/v1 --model Qwen/Qwen3-8B # SGLang
  %(prog)s --url http://localhost:1234/v1 --model loaded-model   # LM Studio
  %(prog)s --provider groq --url http://localhost:11434/v1 --model llama3.2  # compare
  %(prog)s --chat --provider groq                                         # interactive chat
  %(prog)s --chat --url http://localhost:11434/v1 --model llama3.2        # chat with Ollama
""",
    )
    parser.add_argument("--chat", action="store_true", help="Interactive chat (simple mode, fake tools)")
    parser.add_argument(
        "--chat-full", action="store_true", help="Interactive chat (full pipeline — real agent prompt + real tools)"
    )
    parser.add_argument(
        "--version", type=str, help="Prompt version for full pipeline chat (v0/v1/v2/v3, default: production)"
    )
    parser.add_argument("--case", type=str, help="Case ID(s) comma-separated, or 'all'")
    parser.add_argument("--provider", type=str, help="Provider name(s) from .env, comma-separated or 'all'")
    parser.add_argument("--runs", type=int, default=1, help="Runs per case (default: 1)")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("--no-tools", action="store_true", help="Skip tool-calling cases")
    parser.add_argument("--max-tokens", type=int, default=2048, help="Max output tokens (default: 2048)")
    parser.add_argument("--no-ui", action="store_true", help="Disable web UI (default: auto-start on chat modes)")
    parser.add_argument("--ui-port", type=int, default=8930, help="Web UI port (default: 8930)")

    # RAG harness flags
    _scenario_choices = (
        ", ".join(SCENARIO_NAMES) if _BENCH_RAG_AVAILABLE else "rag_only/faq_only/multi_project/lookalike/all"
    )
    parser.add_argument(
        "--rag",
        type=str,
        choices=["on", "off"],
        default=None,
        help="Enable RAG harness: FAQ inject + real FlatStore for noble_search",
    )
    parser.add_argument(
        "--project", type=str, default=None, help="Project filter for FAQ inject (e.g. NCLB or NCLB,NPLB)"
    )
    parser.add_argument("--scenario", type=str, default=None, help=f"Scenario jsonl to run ({_scenario_choices})")
    parser.add_argument(
        "--faq-position",
        type=str,
        choices=["end", "middle"],
        default="end",
        help="Where to inject FAQ in system prompt (default: end)",
    )
    parser.add_argument("--faq-chars", type=int, default=4000, help="Max chars per FAQ file (default: 4000)")
    parser.add_argument(
        "--faq-no-common", action="store_true", default=False, help="Exclude data/faq/_COMMON.md from FAQ injection"
    )

    # Custom endpoint (Ollama, vLLM, SGLang, LM Studio, etc.)
    parser.add_argument("--url", type=str, help="OpenAI-compatible base URL (e.g. http://localhost:11434/v1)")
    parser.add_argument("--model", type=str, help="Model name for custom endpoint")
    parser.add_argument(
        "--api-key", type=str, default="not-needed", help="API key for custom endpoint (default: not-needed)"
    )
    parser.add_argument("--name", type=str, help="Label for custom endpoint in results (default: auto-detect)")
    parser.add_argument(
        "--deferred",
        action="store_true",
        help="Enable deferred-narration mode (v9): wraps send_media to return ack immediately, fires real backend in background, injects narration into next turn. Works with --chat-full.",
    )
    parser.add_argument(
        "--phone",
        type=str,
        default="0942866939",
        help="Phone for real send_media calls in --deferred mode (default: 0942866939)",
    )

    args = parser.parse_args()

    # Build provider map
    available: dict[str, dict] = {}

    # .env providers
    env_provs = _env_providers()
    if args.provider:
        if args.provider == "all":
            available.update(env_provs)
        else:
            for p in args.provider.split(","):
                p = p.strip()
                if p in env_provs:
                    available[p] = env_provs[p]
                else:
                    print(f"⚠️  Provider '{p}' not found in .env. Available: {', '.join(env_provs.keys()) or 'none'}")
    elif not args.url:
        # Interactive mode — show all .env providers
        available.update(env_provs)

    # Custom endpoint
    if args.url:
        if not args.model:
            print("❌ --model is required when using --url")
            sys.exit(1)
        # Auto-detect name from URL
        if args.name:
            label = args.name
        elif "11434" in args.url:
            label = "ollama"
        elif "1234" in args.url:
            label = "lmstudio"
        elif "30000" in args.url:
            label = "sglang"
        elif "8080" in args.url:
            label = "mlx-lm"
        else:
            label = "custom"
        available.update(_custom_provider(args.url, args.model, args.api_key, label))

    if not available:
        print("❌ No providers. Use --provider (from .env) or --url (custom endpoint).")
        print(f"   .env providers: {', '.join(env_provs.keys()) or 'none configured'}")
        sys.exit(1)

    use_tools = not args.no_tools

    # ── RAG harness setup ──────────────────────────────────────────────────────
    global _RAG_ENABLED
    _rag_project: str = args.project or ""
    _faq_position: str = args.faq_position
    _faq_chars: int = args.faq_chars
    _faq_include_common: bool = not args.faq_no_common
    _chosen_scenario: str | None = args.scenario
    _rag_mode_chosen = False  # set True when interactive RAG mode selected

    if args.rag == "on":
        if not _BENCH_RAG_AVAILABLE:
            print(f"❌ bench_rag not available: {_BENCH_RAG_ERR}")
            sys.exit(1)
        _RAG_ENABLED = True

    # Interactive model customization — skip when --model is explicit from CLI
    is_interactive = not (args.url and args.model)

    # Start web UI for chat modes
    global _bench_ui
    if (args.chat or args.chat_full) and not args.no_ui:
        _bench_ui = BenchUI(port=args.ui_port)
        _bench_ui.start()

    # Chat mode — pick first provider and start interactive loop
    if args.chat or args.chat_full:
        if len(available) > 1 and not (args.provider or args.url):
            prov_name = _select_providers(available)[0]
        else:
            prov_name = list(available.keys())[0]
        prov = available[prov_name]
        if is_interactive:
            prov = await _customize_provider_model(prov_name, prov)
            available[prov_name] = prov
        if args.chat_full:
            version = args.version
            if version is None:
                version = _select_prompt_version()
            await _chat_loop_full(
                prov_name, prov["model"], version=version, deferred=args.deferred, deferred_phone=args.phone
            )
        else:
            await _chat_loop(prov["client"], prov["model"], prov_name, use_tools, args.max_tokens)
        _ollama_cleanup()
        return

    # Select what to run
    if args.provider or args.url:
        providers = list(available.keys())
    else:
        providers = _select_providers(available)

        # Interactive mode selector
        print("\n🎯 Mode:")
        print("  [1] Benchmark (test cases)")
        print("  [2] Chat (simple — custom prompt, fake tools)")
        print("  [3] Chat (full pipeline — real agent prompt, real tools, prompt version select)")
        if _BENCH_RAG_AVAILABLE:
            print("  [4] RAG Benchmark (FAQ inject + real FlatStore)")
        print()
        mode = input("Select mode [1]: ").strip()

        if mode == "4" and _BENCH_RAG_AVAILABLE:
            _RAG_ENABLED = True
            _rag_mode_chosen = True
            # Ask project
            proj_input = input("\n🎯 Project filter (e.g. NCLB, or NCLB,NPLB; blank = _COMMON only) [NCLB]: ").strip()
            _rag_project = proj_input if proj_input else "NCLB"
            # Ask scenario
            sc_list = ", ".join(SCENARIO_NAMES)
            sc_input = input(f"🎯 Scenario [{sc_list}] [all]: ").strip()
            _chosen_scenario = sc_input if sc_input in SCENARIO_NAMES else "all"

        if mode == "2":
            if not args.no_ui:
                _bench_ui = BenchUI(port=args.ui_port)
                _bench_ui.start()
            prov_name = providers[0]
            prov = available[prov_name]
            prov = await _customize_provider_model(prov_name, prov)
            available[prov_name] = prov
            await _chat_loop(prov["client"], prov["model"], prov_name, use_tools, args.max_tokens)
            _ollama_cleanup()
            return
        if mode == "3":
            if not args.no_ui:
                _bench_ui = BenchUI(port=args.ui_port)
                _bench_ui.start()
            prov_name = providers[0]
            prov = available[prov_name]
            prov = await _customize_provider_model(prov_name, prov)
            available[prov_name] = prov
            version = _select_prompt_version()
            await _chat_loop_full(
                prov_name, prov["model"], version=version, deferred=args.deferred, deferred_phone=args.phone
            )
            _ollama_cleanup()
            return

    # ── RAG scenario path ──────────────────────────────────────────────────────
    if _RAG_ENABLED and _BENCH_RAG_AVAILABLE and (_chosen_scenario or _rag_mode_chosen):
        sc_name = _chosen_scenario or "all"
        print(f"\n🔍 Loading scenario: {sc_name} | project: {_rag_project or '(common)'}")
        raw_scenarios = load_scenarios(sc_name)

        def _scenario_to_case(sc: dict) -> dict:
            project = sc.get("project", "") or _rag_project
            faq_block = inject_faq(
                project or None,
                max_chars=_faq_chars,
                include_common=_faq_include_common,
            )
            base_sys = (
                "Bạn là trợ lý tư vấn bất động sản Noble. "
                "Trả lời ngắn gọn, lịch sự bằng tiếng Việt. "
                "Dùng tool khi cần tìm kiếm thông tin cụ thể hoặc thực hiện hành động."
            )
            if _faq_position == "end":
                sys_prompt = base_sys + ("\n\n" + faq_block if faq_block else "")
            else:
                sys_prompt = (faq_block + "\n\n" if faq_block else "") + base_sys
            return {
                "id": sc["id"],
                "name": sc.get("note", sc["id"]),
                "desc": sc["query"][:60],
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": sc["query"]},
                ],
                "tools": True,
                "_scenario": sc,
            }

        cases = [_scenario_to_case(sc) for sc in raw_scenarios]
        print(f"   {len(cases)} scenario cases loaded")

        # Warmup FlatStore before running
        print(f"{C.CYAN}   Warming up FlatStore...{C.RESET}", end=" ", flush=True)
        await ensure_warmed_up()
        print(f"{C.GREEN}ready{C.RESET}")

    elif args.case:
        if args.case == "all":
            cases = [c for c in CASES if not (args.no_tools and c.get("tools"))]
        else:
            ids = [int(x.strip()) for x in args.case.split(",") if x.strip().isdigit()]
            cases = [c for c in CASES if c["id"] in ids]
            if args.no_tools:
                cases = [c for c in cases if not c.get("tools")]
    else:
        cases = _select_cases(args.no_tools)

    # If --rag on but no --scenario, still warmup for inline noble_search override
    if _RAG_ENABLED and _BENCH_RAG_AVAILABLE and not (_chosen_scenario or _rag_mode_chosen):
        print(f"{C.CYAN}   RAG enabled — warming up FlatStore...{C.RESET}", end=" ", flush=True)
        await ensure_warmed_up()
        print(f"{C.GREEN}ready{C.RESET}")

    if not cases:
        print("❌ No cases selected.")
        sys.exit(1)

    runs = args.runs
    all_results: list[RunResult] = []

    print(f"\n🚀 Benchmarking {len(providers)} provider(s) × {len(cases)} case(s) × {runs} run(s)")
    print("=" * 80)

    # Let user customize model names before benchmark starts
    if is_interactive and len(providers) >= 1:
        print(f"\n{C.CYAN}Model configuration (press Enter to keep default):{C.RESET}")
        for prov_name in providers:
            prov = available[prov_name]
            prov = await _customize_provider_model(prov_name, prov)
            available[prov_name] = prov

    for prov_name in providers:
        prov = available[prov_name]
        client = prov["client"]
        model = prov["model"]
        print(f"\n🔌 {prov_name} ({model})")
        print("─" * 60)

        for case in cases:
            print(f"\n  Case {case['id']}: {case['name']}")
            for run_i in range(runs):
                if runs > 1:
                    print(f"    Run {run_i + 1}/{runs}:")
                result = await _run_case(
                    client, model, case, prov_name, args.max_tokens, use_tools, prov.get("max_tokens_key")
                )
                all_results.append(result)
                _print_result(result)

    if args.json:
        print("\n" + json.dumps([asdict(r) for r in all_results], indent=2, ensure_ascii=False))
    else:
        _print_summary(all_results)

    _ollama_cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{C.DIM}Interrupted.{C.RESET}")
        _ollama_cleanup()
