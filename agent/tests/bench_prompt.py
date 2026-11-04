#!/usr/bin/env python3
"""Prompt Version Benchmark CLI.

Tests different prompt versions (v0, v1, v2...) against eval scenarios
WITHOUT modifying any code in src/. Uses monkey-patching of the agent
registry path to load prompt files from tests/prompt_versions/<version>/.

Usage:
    # Interactive mode
    python tests/bench_prompt.py

    # Specific version + provider
    python tests/bench_prompt.py --version v9-bench --provider openai

    # Compare versions side-by-side
    python tests/bench_prompt.py --version v8-bench,v9-bench --compare

    # Specific scenario category
    python tests/bench_prompt.py --version v9-bench --scenario rules

    # Dump assembled prompt (inspect without running LLM)
    python tests/bench_prompt.py --dump-prompt v9-bench --agent consultant

    # List available
    python tests/bench_prompt.py --list-versions
    python tests/bench_prompt.py --list-scenarios
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Add src/ to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from openai import AsyncOpenAI

# ── Paths ────────────────────────────────────────────────────────────────

_TESTS_DIR = Path(__file__).resolve().parent
_VERSIONS_DIR = _TESTS_DIR / "prompt_versions"
_REGISTRY_FILE = _VERSIONS_DIR / "registry.json"

# ── ANSI colors ──────────────────────────────────────────────────────────


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


# ── Version registry ─────────────────────────────────────────────────────


def _load_registry() -> dict:
    if _REGISTRY_FILE.exists():
        return json.loads(_REGISTRY_FILE.read_text("utf-8"))
    return {"versions": {}, "default": "v9-bench"}


def _list_versions():
    reg = _load_registry()
    print(f"\n{C.CYAN}{C.BOLD}Available prompt versions:{C.RESET}")
    print(f"{'─' * 70}")
    for vid, info in reg["versions"].items():
        path = _VERSIONS_DIR / vid
        exists = "✓" if path.exists() else "✗"
        tokens = info.get("expected_tokens", {})
        tok_str = f"R:{tokens.get('router', '?')} C:{tokens.get('consultant', '?')} S:{tokens.get('support', '?')}"
        marker = f" {C.GREEN}← default{C.RESET}" if vid == reg.get("default") else ""
        print(
            f"  {C.GREEN if path.exists() else C.RED}{exists}{C.RESET} "
            f"{C.BOLD}{vid:4}{C.RESET} — {info['name']:<32} [{tok_str}]{marker}"
        )
        if info.get("changes"):
            for ch in info["changes"]:
                print(f"         {C.DIM}• {ch}{C.RESET}")
    print()


def _list_scenarios():
    from eval_scenarios import CATEGORY_LABELS, SCENARIOS

    print(f"\n{C.CYAN}{C.BOLD}Eval scenarios ({len(SCENARIOS)} total):{C.RESET}")
    print(f"{'─' * 70}")
    for cat, label in CATEGORY_LABELS.items():
        items = [s for s in SCENARIOS if s["category"] == cat]
        print(f"\n  {C.YELLOW}{label}{C.RESET} ({len(items)} scenarios)")
        for s in items:
            tool = s.get("expect_tool", "")
            tool_str = f" → {C.MAGENTA}{tool}{C.RESET}" if tool else ""
            no_tool = f" {C.GREEN}(FAQ hit){C.RESET}" if s.get("expect_no_tool") else ""
            print(f"    {C.DIM}{s['id']:5}{C.RESET} {s['name']}{tool_str}{no_tool}")
    print()


# ── Monkey-patch registry ────────────────────────────────────────────────


def _patch_registry(version: str) -> Path:
    """Patch agent.registry to read from a test version directory.
    Returns the version directory path.
    """
    version_dir = _VERSIONS_DIR / version
    if not version_dir.exists():
        print(f"{C.RED}Version '{version}' not found at {version_dir}{C.RESET}")
        sys.exit(1)

    import noble_agent.agent.registry as _reg

    _reg._REGISTRY_DIR = version_dir

    # Clear cached config so it re-reads from new path
    if hasattr(_reg._load_config, "cache_clear"):
        _reg._load_config.cache_clear()
    if hasattr(_reg._load_project_faq, "cache_clear"):
        _reg._load_project_faq.cache_clear()

    return version_dir


def _unpatch_registry():
    """Restore registry to production path."""
    import noble_agent.agent.registry as _reg

    _reg._REGISTRY_DIR = Path(_reg.__file__).resolve().parent / "definitions"
    if hasattr(_reg._load_config, "cache_clear"):
        _reg._load_config.cache_clear()
    if hasattr(_reg._load_project_faq, "cache_clear"):
        _reg._load_project_faq.cache_clear()


# ── Prompt assembly (for inspection and token counting) ──────────────────


async def _build_prompt(version: str, agent_id: str) -> str:
    """Build the full system prompt for a version + agent."""
    _patch_registry(version)
    try:
        from noble_agent.agent.registry import build_agent_prompt

        # Build without session (no customer/FAQ context)
        prompt = await build_agent_prompt(agent_id, session_id="")
        return prompt
    finally:
        _unpatch_registry()


def _count_tokens_approx(text: str) -> int:
    """Approximate token count: Vietnamese ~2.5 chars/tok, English ~4."""
    vi_chars = sum(1 for c in text if ord(c) > 127)
    en_chars = len(text) - vi_chars
    return int(vi_chars / 2.5 + en_chars / 4)


async def _dump_prompt(version: str, agent_id: str):
    """Print the assembled prompt for inspection."""
    prompt = await _build_prompt(version, agent_id)
    tokens = _count_tokens_approx(prompt)
    print(f"\n{C.CYAN}{C.BOLD}═══ Prompt: {version} / {agent_id} ═══{C.RESET}")
    print(f"{C.DIM}Chars: {len(prompt):,} | Approx tokens: {tokens:,}{C.RESET}\n")
    print(prompt)
    print(f"\n{C.DIM}{'─' * 60}")
    print(f"Chars: {len(prompt):,} | Approx tokens: {tokens:,}{C.RESET}\n")


# ── Provider setup ───────────────────────────────────────────────────────


def _get_provider() -> tuple[AsyncOpenAI, str, str]:
    """Get the primary LLM provider from config."""
    try:
        from noble_agent.config import settings
    except Exception:
        print(f"{C.RED}Cannot load config. Run from project root with venv.{C.RESET}")
        sys.exit(1)

    # Try providers in order
    if settings.openai_api_key:
        return (
            AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url, timeout=30),
            settings.openai_model,
            "openai",
        )
    if settings.gemini_api_key:
        return (
            AsyncOpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url, timeout=30),
            settings.gemini_model,
            "gemini",
        )
    if settings.groq_api_key:
        return (
            AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url, timeout=30),
            settings.groq_model,
            "groq",
        )
    print(f"{C.RED}No LLM provider configured in .env{C.RESET}")
    sys.exit(1)


def _get_named_provider(name: str) -> tuple[AsyncOpenAI, str, str]:
    """Get a specific provider by name."""
    from noble_agent.config import settings

    providers = {
        "openai": (settings.openai_api_key, settings.openai_base_url, settings.openai_model),
        "gemini": (settings.gemini_api_key, settings.gemini_base_url, settings.gemini_model),
        "groq": (settings.groq_api_key, settings.groq_base_url, settings.groq_model),
        "openrouter": (settings.openrouter_api_key, settings.openrouter_base_url, settings.openrouter_model),
        "qwen": (settings.dashscope_api_key, settings.dashscope_base_url, settings.dashscope_model),
    }
    if name not in providers or not providers[name][0]:
        print(f"{C.RED}Provider '{name}' not available{C.RESET}")
        sys.exit(1)
    key, url, model = providers[name]
    return AsyncOpenAI(api_key=key, base_url=url, timeout=30), model, name


# ── Auto-graders ─────────────────────────────────────────────────────────


def _grade_xung_ho(response: str, **_) -> tuple[bool, str]:
    has = "Quý Khách" in response or "Anh" in response or "Chị" in response
    return has, "xưng hô present" if has else "missing xưng hô (Quý Khách/Anh/Chị)"


def _grade_xung_ho_unknown(response: str, **_) -> tuple[bool, str]:
    has = "Quý Khách" in response
    return has, "Quý Khách used" if has else "should use 'Quý Khách' for unknown customer"


def _grade_xung_ho_named(response: str, scenario: dict = None, **_) -> tuple[bool, str]:
    name = (scenario or {}).get("expect_name", "")
    if not name:
        return True, "no name to check"
    has = name in response
    return has, f"'{name}' found" if has else f"should address by name '{name}'"


def _grade_so_bang_chu(response: str, **_) -> tuple[bool, str]:
    bad = re.search(r"\d[\d,.]*\s*(tỷ|triệu|m2|mét|%)", response)
    return not bad, "numbers in words" if not bad else f"found digit: '{bad.group()}'"


def _grade_forbidden(response: str, **_) -> tuple[bool, str]:
    forbidden = ["chuyển cuộc gọi", "chuyển sang chuyên viên tư vấn", "chuyển sang bộ phận", "em đã chuyển cuộc gọi"]
    for f in forbidden:
        if f in response.lower():
            return False, f"forbidden phrase: '{f}'"
    return True, "no forbidden phrases"


def _grade_bridge(response: str, **_) -> tuple[bool, str]:
    stripped = response.rstrip()
    has = stripped.endswith("ạ?") or stripped.endswith("ạ!") or stripped.endswith("không ạ")
    return has, "ends with question" if has else "missing bridge response (question at end)"


def _grade_no_markdown(response: str, **_) -> tuple[bool, str]:
    bad = re.search(r"^[\s]*[-*]\s|^\d+\.\s|^\|", response, re.MULTILINE)
    return not bad, "no markdown" if not bad else f"found markdown: '{bad.group().strip()}'"


def _grade_ack_before_tool(response: str, had_tool: bool = False, **_) -> tuple[bool, str]:
    if not had_tool:
        return True, "no tool call"
    has_text = len(response.strip()) > 0
    return has_text, "has ACK text" if has_text else "silent tool call (no ACK)"


def _grade_da_prefix(response: str, **_) -> tuple[bool, str]:
    # Strip voice expression tags like [warmly], [softly] before checking
    cleaned = re.sub(
        r"\[(?:warmly|softly|enthusiastically|reassuringly|pause|short pause|gently|cheerfully|calmly)\]\s*",
        "",
        response.strip(),
    )
    first_sentence = cleaned.split(".")[0].split(",")[0].strip()
    has = first_sentence.lower().startswith("dạ")
    return has, "starts with Dạ" if has else f"should start with 'Dạ', got: '{first_sentence[:30]}'"


def _grade_no_self_switch(response: str, tool_calls: list = None, **_) -> tuple[bool, str]:
    if not tool_calls:
        return True, "no tool calls"
    for tc in tool_calls:
        if tc.get("name") == "switch_agent":
            args = tc.get("args", "")
            if "consultant" in args:
                return False, "consultant called switch_agent(consultant) = self-call"
    return True, "no self-switch"


GRADERS = {
    "xung_ho": _grade_xung_ho,
    "xung_ho_unknown": _grade_xung_ho_unknown,
    "xung_ho_named": _grade_xung_ho_named,
    "so_bang_chu": _grade_so_bang_chu,
    "forbidden": _grade_forbidden,
    "bridge": _grade_bridge,
    "no_markdown": _grade_no_markdown,
    "ack_before_tool": _grade_ack_before_tool,
    "da_prefix": _grade_da_prefix,
    "no_self_switch": _grade_no_self_switch,
}


# ── Fake tool responses ──────────────────────────────────────────────────

_FAKE_TOOL_RESPONSES: dict[str, str] = {
    "kb_search": '{"results": [{"title": "Noble Crystal Long Biên", "content": "Dự án căn hộ cao cấp tại Long Biên. Diện tích 65-150m2, giá từ 55-75 triệu/m2. Tiện ích: hồ bơi, gym, công viên 2ha.", "citation_id": "nclb001"}]}',
    "list_projects": '{"projects": [{"code": "NCLB", "name": "Noble Crystal Long Biên"}, {"code": "NCTH", "name": "Noble Crystal Tây Hồ"}, {"code": "NPLB", "name": "Noble Palace Long Biên"}]}',
    "discover_projects": '{"project": "Noble Crystal Long Biên", "location": "Phúc Đồng, Long Biên",'
    ' "type": "Căn hộ + Biệt thự", "units": 1200, "developer": "NobleX",'
    ' "highlights": ["View sông Hồng", "Metro line 1", "Công viên 2ha"]}',
    "get_project_financial": '{"pricing": {"2PN": "3.5-4.8 tỷ", "3PN": "5.2-7.5 tỷ"}, "payment": "30% ký HĐ, 70% theo tiến độ", "promotion": "CK 8% thanh toán sớm", "price_per_m2": "55-75 triệu/m2"}',
    "search_units": '{"units": [{"code": "A-12-05", "type": "2PN", "area": 72.5, "price": 4200000000, "direction": "Đông Nam", "status": "available"}]}',
    "match_projects": '{"recommendations": [{"code": "NCLB", "name": "Noble Crystal Long Biên", "match_score": 92, "reason": "Phù hợp ngân sách, khu vực"}]}',
    "check_availability": '{"available_dates": ["19/04/2026", "20/04/2026", "21/04/2026"], "slots": ["09:00-10:00", "10:00-11:00", "14:00-15:00"]}',
    "schedule_viewing": '{"success": true, "booking_id": "APT-20260417-001"}',
    "update_customer": '{"success": true}',
    "update_booking_info": '{"success": true}',
    "get_booking_state": '{"collected": {}, "missing": ["customer_name", "phone", "project", "date", "slot"]}',
    "validate_phone": '{"valid": true, "formatted": "0942 866 939"}',
    "switch_agent": '{"success": true, "new_agent": "consultant"}',
    "crm_lookup": '{"customer": {"name": "Nguyễn Văn A", "contract": "HD-2025-001", "project": "NCTH", "unit": "B-15-03"}}',
    "verify_identity": '{"verified": true}',
    "support_ticket": '{"ticket_id": "TK-20260417-001", "status": "created"}',
    "get_certificate_status": '{"status": "processing", "expected": "Q3/2026"}',
    "escalate": '{"status": "pending", "message": "Đã ghi nhận yêu cầu chuyển tiếp"}',
    "list_bookings": '{"bookings": []}',
}


# ── Token limit helper ───────────────────────────────────────────────────


def _token_limit_key(model: str) -> str:
    if any(model.startswith(p) for p in ("gpt-5", "o1", "o3")):
        return "max_completion_tokens"
    return "max_tokens"


# ── Scenario runner ──────────────────────────────────────────────────────


@dataclass
class ScenarioResult:
    version: str
    scenario_id: str
    scenario_name: str
    agent: str
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    output_tokens: int = 0
    input_tokens: int = 0
    prompt_tokens_approx: int = 0
    tok_per_sec: float = 0.0
    response_text: str = ""
    tool_calls: list = field(default_factory=list)
    grades: dict = field(default_factory=dict)  # grader_name -> (pass, reason)
    error: str = ""


async def _run_scenario(
    client: AsyncOpenAI,
    model: str,
    scenario: dict,
    version: str,
    system_prompt: str,
    max_tokens: int = 1024,
) -> ScenarioResult:
    """Run one scenario against the LLM and grade the response."""
    result = ScenarioResult(
        version=version,
        scenario_id=scenario["id"],
        scenario_name=scenario["name"],
        agent=scenario["agent"],
    )

    # Build messages: system prompt + scenario messages
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(scenario["messages"])

    # Load tool schemas
    try:
        from noble_agent.agent.tools.schemas import TOOL_DEFINITIONS

        tools = TOOL_DEFINITIONS
    except Exception:
        tools = []

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        _token_limit_key(model): max_tokens,
        "stream_options": {"include_usage": True},
    }
    if tools:
        kwargs["tools"] = tools

    result.prompt_tokens_approx = _count_tokens_approx(system_prompt)

    t0 = time.monotonic()
    ttft_set = False
    text_parts: list[str] = []
    tool_call_parts: dict[int, dict] = {}
    max_rounds = 3  # tool call rounds

    try:
        for _round in range(max_rounds):
            stream = await client.chat.completions.create(**kwargs)
            round_text: list[str] = []
            round_tools: dict[int, dict] = {}

            async for event in stream:
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
                    round_text.append(delta.content)

                if delta and delta.tool_calls:
                    if not ttft_set:
                        result.ttft_ms = (time.monotonic() - t0) * 1000
                        ttft_set = True
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in round_tools:
                            round_tools[idx] = {"id": "", "name": "", "args": []}
                        if tc.id:
                            round_tools[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                round_tools[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                round_tools[idx]["args"].append(tc.function.arguments)

            text_parts.extend(round_text)

            if not round_tools:
                break  # no tool calls, done

            # Process tool calls
            assistant_msg: dict = {
                "role": "assistant",
                "content": "".join(round_text) or None,
                "tool_calls": [],
            }
            for idx in sorted(round_tools):
                tc = round_tools[idx]
                args_str = "".join(tc["args"])
                assistant_msg["tool_calls"].append(
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": args_str},
                    }
                )
                result.tool_calls.append({"name": tc["name"], "args": args_str})

            messages.append(assistant_msg)
            for tc_msg in assistant_msg["tool_calls"]:
                fn_name = tc_msg["function"]["name"]
                fake = _FAKE_TOOL_RESPONSES.get(fn_name, '{"result": "ok"}')
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_msg["id"],
                        "content": fake,
                    }
                )

            kwargs["messages"] = messages

    except Exception as e:
        result.error = str(e)[:300]

    result.total_ms = (time.monotonic() - t0) * 1000
    result.response_text = "".join(text_parts)

    if result.output_tokens == 0 and result.response_text:
        result.output_tokens = max(1, len(result.response_text) // 3)
    if result.output_tokens > 0 and result.total_ms > 0:
        result.tok_per_sec = result.output_tokens / (result.total_ms / 1000)

    # Run graders
    had_tool = len(result.tool_calls) > 0
    for grader_name in scenario.get("graders", []):
        fn = GRADERS.get(grader_name)
        if fn:
            passed, reason = fn(
                result.response_text,
                had_tool=had_tool,
                tool_calls=result.tool_calls,
                scenario=scenario,
            )
            result.grades[grader_name] = {"pass": passed, "reason": reason}

    # Check expected tool
    if "expect_tool" in scenario and scenario["expect_tool"]:
        expected = scenario["expect_tool"]
        called = [tc["name"] for tc in result.tool_calls]
        if expected in called:
            result.grades["_tool_match"] = {"pass": True, "reason": f"called {expected}"}
        else:
            result.grades["_tool_match"] = {"pass": False, "reason": f"expected {expected}, got {called or 'none'}"}

    if scenario.get("expect_no_tool"):
        if not result.tool_calls:
            result.grades["_no_tool"] = {"pass": True, "reason": "no tool call (FAQ hit)"}
        else:
            called = [tc["name"] for tc in result.tool_calls]
            result.grades["_no_tool"] = {"pass": False, "reason": f"expected no tool, got {called}"}

    return result


# ── Display ──────────────────────────────────────────────────────────────


def _print_scenario_result(r: ScenarioResult, verbose: bool = False):
    status = f"{C.GREEN}✓{C.RESET}" if not r.error else f"{C.RED}✗{C.RESET}"
    grade_pass = sum(1 for g in r.grades.values() if g["pass"])
    grade_total = len(r.grades)
    grade_color = C.GREEN if grade_pass == grade_total else (C.YELLOW if grade_pass > grade_total // 2 else C.RED)

    print(
        f"  {status} {C.DIM}{r.scenario_id:5}{C.RESET} {r.scenario_name:<40} "
        f"TTFT:{r.ttft_ms:>5.0f}ms  Total:{r.total_ms:>6.0f}ms  "
        f"{r.tok_per_sec:>5.1f}t/s  "
        f"Grade: {grade_color}{grade_pass}/{grade_total}{C.RESET}"
    )

    if r.error:
        print(f"        {C.RED}ERROR: {r.error[:100]}{C.RESET}")

    if verbose or grade_pass < grade_total:
        for gname, gresult in r.grades.items():
            icon = f"{C.GREEN}✓{C.RESET}" if gresult["pass"] else f"{C.RED}✗{C.RESET}"
            print(f"        {icon} {gname}: {C.DIM}{gresult['reason']}{C.RESET}")


def _print_version_summary(version: str, results: list[ScenarioResult]):
    ok = [r for r in results if not r.error]
    if not ok:
        print(f"\n  {C.RED}{version}: all scenarios failed{C.RESET}")
        return

    avg_ttft = sum(r.ttft_ms for r in ok) / len(ok)
    avg_total = sum(r.total_ms for r in ok) / len(ok)
    avg_tps = sum(r.tok_per_sec for r in ok) / len(ok)
    avg_prompt = sum(r.prompt_tokens_approx for r in ok) / len(ok)

    total_grades = sum(len(r.grades) for r in ok)
    passed_grades = sum(sum(1 for g in r.grades.values() if g["pass"]) for r in ok)
    adherence = (passed_grades / total_grades * 100) if total_grades > 0 else 0

    tool_expected = [r for r in ok if "_tool_match" in r.grades]
    tool_correct = sum(1 for r in tool_expected if r.grades["_tool_match"]["pass"])

    print(f"\n  {C.CYAN}{C.BOLD}📊 {version}{C.RESET}")
    print(f"     Scenarios:     {len(ok)}/{len(results)} passed")
    print(f"     Avg TTFT:      {avg_ttft:>7.0f} ms")
    print(f"     Avg Total:     {avg_total:>7.0f} ms")
    print(f"     Avg Speed:     {avg_tps:>7.1f} tok/s")
    print(f"     Prompt tokens: {avg_prompt:>7.0f} (approx)")
    print(f"     Rule adherence:{adherence:>6.1f}% ({passed_grades}/{total_grades})")
    if tool_expected:
        print(f"     Tool accuracy: {tool_correct}/{len(tool_expected)}")


def _print_comparison(all_results: dict[str, list[ScenarioResult]]):
    versions = list(all_results.keys())
    if len(versions) < 2:
        return

    print(f"\n{'═' * 80}")
    print(f"{C.BOLD}SIDE-BY-SIDE COMPARISON{C.RESET}")
    print(f"{'═' * 80}")

    header = f"  {'Metric':<25}"
    for v in versions:
        header += f" | {v:>12}"
    print(header)
    print(f"  {'─' * 25}", end="")
    for _ in versions:
        print(f" | {'─' * 12}", end="")
    print()

    metrics = [
        (
            "Avg TTFT (ms)",
            lambda rs: sum(r.ttft_ms for r in rs if not r.error) / max(1, len([r for r in rs if not r.error])),
        ),
        (
            "Avg Total (ms)",
            lambda rs: sum(r.total_ms for r in rs if not r.error) / max(1, len([r for r in rs if not r.error])),
        ),
        (
            "Avg tok/s",
            lambda rs: sum(r.tok_per_sec for r in rs if not r.error) / max(1, len([r for r in rs if not r.error])),
        ),
        (
            "Prompt tokens",
            lambda rs: (
                sum(r.prompt_tokens_approx for r in rs if not r.error) / max(1, len([r for r in rs if not r.error]))
            ),
        ),
        (
            "Rule adherence %",
            lambda rs: (
                sum(sum(1 for g in r.grades.values() if g["pass"]) for r in rs if not r.error)
                / max(1, sum(len(r.grades) for r in rs if not r.error))
                * 100
            ),
        ),
        (
            "Tool accuracy",
            lambda rs: (
                f"{sum(1 for r in rs if not r.error and '_tool_match' in r.grades and r.grades['_tool_match']['pass'])}/{len([r for r in rs if not r.error and '_tool_match' in r.grades])}"
            ),
        ),
    ]

    for label, fn in metrics:
        line = f"  {label:<25}"
        for v in versions:
            val = fn(all_results[v])
            if isinstance(val, str):
                line += f" | {val:>12}"
            else:
                line += f" | {val:>12.1f}"
        print(line)


# ── Main run logic ───────────────────────────────────────────────────────


async def _run_version(
    version: str,
    client: AsyncOpenAI,
    model: str,
    scenarios: list[dict],
    runs: int = 1,
    verbose: bool = False,
) -> list[ScenarioResult]:
    """Run all scenarios against a specific prompt version."""
    results: list[ScenarioResult] = []

    # Group scenarios by agent to minimize prompt rebuilds
    by_agent: dict[str, list[dict]] = {}
    for s in scenarios:
        by_agent.setdefault(s["agent"], []).append(s)

    for agent_id, agent_scenarios in by_agent.items():
        _patch_registry(version)
        try:
            prompt = await _build_prompt(version, agent_id)
        finally:
            _unpatch_registry()

        tokens = _count_tokens_approx(prompt)
        print(f"\n  {C.CYAN}Agent: {agent_id}{C.RESET} ({tokens} tokens, {len(agent_scenarios)} scenarios)")

        for scenario in agent_scenarios:
            best_result = None
            for run_i in range(runs):
                r = await _run_scenario(client, model, scenario, version, prompt)
                if best_result is None or r.ttft_ms < best_result.ttft_ms:
                    best_result = r

            _print_scenario_result(best_result, verbose)
            results.append(best_result)

    return results


# ── Interactive mode ─────────────────────────────────────────────────────


def _interactive_select_versions() -> list[str]:
    reg = _load_registry()
    versions = list(reg["versions"].keys())
    print(f"\n{C.CYAN}{C.BOLD}🎯 Select prompt version(s):{C.RESET}")
    for i, v in enumerate(versions):
        info = reg["versions"][v]
        tok = info.get("expected_tokens", {})
        exists = (_VERSIONS_DIR / v).exists()
        status = f"{C.GREEN}✓{C.RESET}" if exists else f"{C.RED}✗{C.RESET}"
        print(
            f"  [{i + 1}] {status} {v:4} — {info['name']:<32} [R:{tok.get('router', '?')} C:{tok.get('consultant', '?')}]"
        )
    print("  [A] Compare ALL versions")
    print()

    choice = input("Select (comma-separated, e.g. 1,3): ").strip().upper()
    if choice == "A":
        return [v for v in versions if (_VERSIONS_DIR / v).exists()]
    if not choice:
        return [versions[0]]

    indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
    selected = [versions[i] for i in indices if 0 <= i < len(versions)]
    return selected or [versions[0]]


def _interactive_select_scenarios() -> list[dict]:
    from eval_scenarios import CATEGORY_LABELS, SCENARIOS

    cats = list(CATEGORY_LABELS.keys())

    print(f"\n{C.CYAN}{C.BOLD}🎯 Select scenario category:{C.RESET}")
    for i, (cat, label) in enumerate(CATEGORY_LABELS.items(), 1):
        count = len([s for s in SCENARIOS if s["category"] == cat])
        print(f"  [{i}] {label} ({count} scenarios)")
    print(f"  [0] ALL ({len(SCENARIOS)} scenarios)")
    print()

    choice = input("Select: ").strip()
    if not choice or choice == "0":
        return SCENARIOS

    indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
    selected = []
    for i in indices:
        if 0 <= i < len(cats):
            selected.extend([s for s in SCENARIOS if s["category"] == cats[i]])
    return selected or SCENARIOS


def _interactive_select_mode() -> str:
    print(f"\n{C.CYAN}{C.BOLD}🎯 Mode:{C.RESET}")
    print("  [1] Benchmark (run scenarios, measure + grade)")
    print("  [2] Dump prompt (inspect assembled prompt)")
    print("  [3] Chat (interactive chat with version)")
    print()
    return input("Select [1]: ").strip() or "1"


# ── Chat mode with version ───────────────────────────────────────────────


async def _chat_with_version(version: str, agent_id: str, client: AsyncOpenAI, model: str):
    """Interactive chat using a specific prompt version."""
    _patch_registry(version)
    try:
        prompt = await _build_prompt(version, agent_id)
    finally:
        _unpatch_registry()

    tokens = _count_tokens_approx(prompt)

    try:
        from noble_agent.agent.tools.schemas import TOOL_DEFINITIONS

        tools = TOOL_DEFINITIONS
    except Exception:
        tools = []

    tool_names = [t["function"]["name"] for t in tools]
    print(f"\n{C.CYAN}{C.BOLD}╭─ Chat: {version} / {agent_id} ──────────────────────────────╮{C.RESET}")
    print(f"{C.CYAN}│{C.RESET} Prompt: {tokens} tokens")
    if tools:
        print(
            f"{C.CYAN}│{C.RESET} Tools: {C.DIM}{', '.join(tool_names[:6])}{'...' if len(tool_names) > 6 else ''}{C.RESET}"
        )
    print(f"{C.CYAN}│{C.RESET} Type {C.BOLD}/quit{C.RESET} to exit")
    print(f"{C.CYAN}╰─────────────────────────────────────────────────────╯{C.RESET}\n")

    messages = [{"role": "system", "content": prompt}]

    while True:
        try:
            user_input = input(f"{C.YELLOW}{C.BOLD}You:{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.DIM}Bye!{C.RESET}")
            break
        if not user_input or user_input.lower() in ("/quit", "/exit", "/q"):
            break

        messages.append({"role": "user", "content": user_input})
        turn_start = time.monotonic()
        ttft_set = False

        # Multi-round tool loop
        for _round in range(3):
            kwargs = {
                "model": model,
                "messages": messages,
                "stream": True,
                _token_limit_key(model): 1024,
                "stream_options": {"include_usage": True},
            }
            if tools:
                kwargs["tools"] = tools

            text_parts = []
            tc_parts: dict[int, dict] = {}
            bot_printed = False

            try:
                stream = await client.chat.completions.create(**kwargs)
                async for event in stream:
                    if not event.choices:
                        continue
                    delta = event.choices[0].delta
                    if delta and delta.content:
                        if not ttft_set:
                            ttft_ms = (time.monotonic() - turn_start) * 1000
                            ttft_set = True
                        if not bot_printed:
                            print(f"{C.GREEN}{C.BOLD}Bot:{C.RESET} ", end="", flush=True)
                            bot_printed = True
                        print(delta.content, end="", flush=True)
                        text_parts.append(delta.content)
                    if delta and delta.tool_calls:
                        if not ttft_set:
                            ttft_ms = (time.monotonic() - turn_start) * 1000
                            ttft_set = True
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tc_parts:
                                tc_parts[idx] = {"id": "", "name": "", "args": []}
                            if tc.id:
                                tc_parts[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tc_parts[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tc_parts[idx]["args"].append(tc.function.arguments)
            except Exception as e:
                print(f"\n  {C.RED}ERROR: {e}{C.RESET}")
                break

            if text_parts and bot_printed:
                print()

            if not tc_parts:
                full = "".join(text_parts)
                if full:
                    elapsed = (time.monotonic() - turn_start) * 1000
                    print(f"  {C.GRAY}[{elapsed / 1000:.2f}s, TTFT {ttft_ms / 1000:.2f}s]{C.RESET}")
                    messages.append({"role": "assistant", "content": full})
                break

            # Handle tool calls
            asst = {"role": "assistant", "content": "".join(text_parts) or None, "tool_calls": []}
            for idx in sorted(tc_parts):
                tc = tc_parts[idx]
                args_str = "".join(tc["args"])
                asst["tool_calls"].append(
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": args_str},
                    }
                )
                print(f"  {C.MAGENTA}[Tool]{C.RESET} {C.CYAN}{tc['name']}{C.RESET}({C.DIM}{args_str}{C.RESET})")

            messages.append(asst)
            for tc_msg in asst["tool_calls"]:
                fn = tc_msg["function"]["name"]
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_msg["id"],
                        "content": _FAKE_TOOL_RESPONSES.get(fn, '{"result": "ok"}'),
                    }
                )

        print()


# ── Main ─────────────────────────────────────────────────────────────────


async def _main():
    parser = argparse.ArgumentParser(description="Prompt Version Benchmark CLI")
    parser.add_argument("--version", "-v", help="Prompt version(s), comma-separated")
    parser.add_argument("--provider", "-p", help="LLM provider name")
    parser.add_argument("--scenario", "-s", help="Scenario category")
    parser.add_argument("--runs", "-r", type=int, default=1, help="Runs per scenario")
    parser.add_argument("--compare", action="store_true", help="Side-by-side comparison")
    parser.add_argument("--verbose", action="store_true", help="Show all grader details")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--list-versions", action="store_true")
    parser.add_argument("--list-scenarios", action="store_true")
    parser.add_argument("--dump-prompt", metavar="VERSION", help="Dump assembled prompt")
    parser.add_argument("--agent", default="consultant", help="Agent for dump-prompt/chat")
    parser.add_argument("--chat", action="store_true", help="Interactive chat with version")
    args = parser.parse_args()

    if args.list_versions:
        _list_versions()
        return
    if args.list_scenarios:
        _list_scenarios()
        return
    if args.dump_prompt:
        await _dump_prompt(args.dump_prompt, args.agent)
        return

    print(f"\n{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}║  Prompt Version Benchmark                            ║{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}╚══════════════════════════════════════════════════════╝{C.RESET}")

    # Get provider
    if args.provider:
        client, model, prov_name = _get_named_provider(args.provider)
    else:
        client, model, prov_name = _get_provider()
    print(f"  Provider: {C.GREEN}{prov_name}{C.RESET} ({C.YELLOW}{model}{C.RESET})")

    # Interactive or CLI mode
    if not args.version and not args.chat:
        mode = _interactive_select_mode()
        if mode == "2":
            versions = _interactive_select_versions()
            for v in versions:
                for agent in ["router", "consultant", "support"]:
                    await _dump_prompt(v, agent)
            return
        if mode == "3":
            versions = _interactive_select_versions()
            await _chat_with_version(versions[0], args.agent, client, model)
            return
    elif args.chat:
        v = args.version or _load_registry().get("default", "v9-bench")
        await _chat_with_version(v, args.agent, client, model)
        return

    # Select versions
    if args.version:
        versions = [v.strip() for v in args.version.split(",")]
    else:
        versions = _interactive_select_versions()

    # Select scenarios
    from eval_scenarios import SCENARIOS

    if args.scenario:
        cats = [c.strip() for c in args.scenario.split(",")]
        scenarios = [s for s in SCENARIOS if s["category"] in cats]
    elif not args.version:
        scenarios = _interactive_select_scenarios()
    else:
        scenarios = SCENARIOS

    print(f"  Versions: {C.MAGENTA}{', '.join(versions)}{C.RESET}")
    print(f"  Scenarios: {len(scenarios)}")
    print(f"  Runs: {args.runs}")

    # Run
    all_results: dict[str, list[ScenarioResult]] = {}
    for version in versions:
        print(f"\n{'═' * 70}")
        print(f"{C.BOLD}  Version: {version}{C.RESET}")
        print(f"{'═' * 70}")

        results = await _run_version(version, client, model, scenarios, runs=args.runs, verbose=args.verbose)
        all_results[version] = results
        _print_version_summary(version, results)

    # Comparison
    if len(versions) > 1 or args.compare:
        _print_comparison(all_results)

    # JSON output
    if args.json:
        out = {}
        for v, rs in all_results.items():
            out[v] = [asdict(r) for r in rs]
        print(json.dumps(out, indent=2, ensure_ascii=False))


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
