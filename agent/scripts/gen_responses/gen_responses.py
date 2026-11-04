#!/usr/bin/env python3
"""
NobleX Voice Agent — Response Generator

Generates sample responses for all agent/skill/tool combinations
using AI API (Gemini / OpenAI / Qwen). Saves each response as a .txt file.

Usage:
    python scripts/gen_responses/gen_responses.py                    # All scenarios
    python scripts/gen_responses/gen_responses.py --category 01_router  # Only router
    python scripts/gen_responses/gen_responses.py --id 01_greeting      # Single scenario
    python scripts/gen_responses/gen_responses.py --dry-run             # Preview prompts only
    python scripts/gen_responses/gen_responses.py --provider openai     # Use OpenAI
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path so we can import .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scenarios import Scenario, build_all_scenarios
from prompt_builder import build_prompt

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gen_responses")

# ─── Output directory ─────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _load_env():
    """Load .env file from project root."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        log.warning(".env not found at %s", env_path)
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


# ─── AI API Clients ──────────────────────────────────────────────────────────


async def _call_gemini(system: str, user: str, temperature: float = 0.7) -> str:
    """Call Gemini API via OpenAI-compatible endpoint."""
    from openai import AsyncOpenAI

    api_key = os.environ.get("GEMINI_API_KEY", "")
    base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=1500,
    )
    return resp.choices[0].message.content.strip()


async def _call_openai(system: str, user: str, temperature: float = 0.7) -> str:
    """Call OpenAI API."""
    from openai import AsyncOpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=1500,
    )
    return resp.choices[0].message.content.strip()


async def _call_qwen(system: str, user: str, temperature: float = 0.7) -> str:
    """Call Qwen/DashScope API (OpenAI-compatible)."""
    from openai import AsyncOpenAI

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    base_url = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    model = os.environ.get("DASHSCOPE_MODEL", "qwen-turbo")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=1500,
    )
    return resp.choices[0].message.content.strip()


_PROVIDERS = {
    "gemini": _call_gemini,
    "openai": _call_openai,
    "qwen": _call_qwen,
}


# ─── Temperature mapping per agent ──────────────────────────────────────────

_AGENT_TEMP = {
    "router": 0.3,       # Precise routing
    "consultant": 0.6,   # Natural but accurate
    "support": 0.4,      # Empathetic but controlled
}


# ─── Core generation ────────────────────────────────────────────────────────


def _clean_response(text: str) -> str:
    """Post-process: strip markdown artifacts, ensure voice-friendly format."""
    import re
    # Remove markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bullet points
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    # Remove numbered lists
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    # Remove code blocks
    text = re.sub(r"`{1,3}(.*?)`{1,3}", r"\1", text, flags=re.DOTALL)
    # Remove citation brackets (keep for reference but clean up)
    # text = re.sub(r"\[[\w-]+\]", "", text)
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def generate_one(
    scenario: Scenario,
    provider: str,
    variation_idx: int = 0,
    dry_run: bool = False,
) -> tuple[str, str]:
    """
    Generate one response for a scenario.

    Returns:
        (output_path, response_text)
    """
    # Build output filename
    suffix = f"_v{variation_idx + 1}" if variation_idx > 0 else ""
    filename = f"{scenario.id}{suffix}.txt"
    out_dir = OUTPUT_DIR / scenario.category
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    # Build prompt
    system_prompt, user_message = build_prompt(scenario, variation_idx)

    if dry_run:
        # Save prompt preview instead
        preview_path = out_dir / f"{scenario.id}{suffix}_PROMPT.txt"
        preview_path.write_text(
            f"=== SYSTEM PROMPT ===\n{system_prompt}\n\n"
            f"=== USER MESSAGE ===\n{user_message}\n",
            encoding="utf-8",
        )
        log.info("📝 [DRY-RUN] %s → %s", scenario.id, preview_path.name)
        return str(preview_path), "(dry-run)"

    # Call AI API
    call_fn = _PROVIDERS[provider]
    temperature = _AGENT_TEMP.get(scenario.agent, 0.5)
    response = await call_fn(system_prompt, user_message, temperature)

    # Clean response
    response = _clean_response(response)

    # Save
    out_path.write_text(response, encoding="utf-8")
    log.info("✅ [%s] %s → %s (%d chars)", provider.upper(), scenario.id, filename, len(response))

    return str(out_path), response


async def generate_all(
    scenarios: list[Scenario],
    provider: str,
    dry_run: bool = False,
    concurrency: int = 3,
    delay_ms: int = 500,
):
    """Generate responses for all scenarios with rate limiting."""
    semaphore = asyncio.Semaphore(concurrency)
    results: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []

    async def _run_one(sc: Scenario, var_idx: int):
        async with semaphore:
            try:
                path, text = await generate_one(sc, provider, var_idx, dry_run)
                results.append((path, text))
            except Exception as e:
                err_msg = f"{sc.id}_v{var_idx}: {e}"
                log.error("❌ %s", err_msg)
                errors.append((sc.id, str(e)))
            if not dry_run:
                await asyncio.sleep(delay_ms / 1000)

    tasks = []
    for sc in scenarios:
        for var_idx in range(sc.variations):
            tasks.append(_run_one(sc, var_idx))

    total = len(tasks)
    log.info("🚀 Starting generation: %d tasks, provider=%s, concurrency=%d", total, provider, concurrency)
    start = time.time()

    await asyncio.gather(*tasks)

    elapsed = time.time() - start
    log.info("═" * 60)
    log.info("📊 Done! %d/%d succeeded, %d errors, %.1fs elapsed",
             len(results), total, len(errors), elapsed)

    if errors:
        log.warning("Errors:")
        for sid, err in errors:
            log.warning("  - %s: %s", sid, err)

    # Generate summary manifest
    if results and not dry_run:
        _write_manifest(scenarios, results, errors, provider, elapsed)


def _write_manifest(
    scenarios: list[Scenario],
    results: list[tuple[str, str]],
    errors: list[tuple[str, str]],
    provider: str,
    elapsed: float,
):
    """Write a JSON manifest of all generated files."""
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "total_scenarios": len(scenarios),
        "total_files": len(results),
        "total_errors": len(errors),
        "elapsed_seconds": round(elapsed, 1),
        "categories": {},
    }

    for sc in scenarios:
        cat = sc.category
        if cat not in manifest["categories"]:
            manifest["categories"][cat] = {"count": 0, "scenarios": []}
        manifest["categories"][cat]["count"] += sc.variations
        manifest["categories"][cat]["scenarios"].append({
            "id": sc.id,
            "agent": sc.agent,
            "skill": sc.skill,
            "intent": sc.intent,
            "query": sc.customer_query,
            "variations": sc.variations,
        })

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("📄 Manifest saved: %s", manifest_path)


# ─── CLI ─────────────────────────────────────────────────────────────────────


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate sample voice agent responses using AI API",
    )
    parser.add_argument(
        "--provider", choices=["gemini", "openai", "qwen"],
        default="gemini",
        help="AI provider (default: gemini)",
    )
    parser.add_argument(
        "--category", type=str, default="",
        help="Filter by category folder (e.g. 01_router, 02_consultant_info)",
    )
    parser.add_argument(
        "--id", type=str, default="",
        help="Filter by scenario ID (e.g. 01_greeting)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only save prompts, don't call AI API",
    )
    parser.add_argument(
        "--concurrency", type=int, default=3,
        help="Max concurrent API calls (default: 3)",
    )
    parser.add_argument(
        "--delay", type=int, default=500,
        help="Delay between API calls in ms (default: 500)",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_scenarios",
        help="List all scenarios and exit",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    _load_env()

    all_scenarios = build_all_scenarios()

    # Filter
    scenarios = all_scenarios
    if args.category:
        scenarios = [s for s in scenarios if s.category == args.category]
    if args.id:
        scenarios = [s for s in scenarios if s.id == args.id]

    if not scenarios:
        log.error("No scenarios matched filters. Use --list to see all.")
        sys.exit(1)

    # List mode
    if args.list_scenarios:
        print(f"\n{'ID':<35} {'Agent':<12} {'Skill':<24} {'Intent':<25} {'Cat':<20} {'Vars':>4}")
        print("─" * 125)
        for s in scenarios:
            print(f"{s.id:<35} {s.agent:<12} {s.skill:<24} {s.intent:<25} {s.category:<20} {s.variations:>4}")
        print(f"\nTotal: {len(scenarios)} scenarios, "
              f"{sum(s.variations for s in scenarios)} files to generate")
        return

    # Check API key
    if not args.dry_run:
        key_map = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "qwen": "DASHSCOPE_API_KEY"}
        key_name = key_map[args.provider]
        if not os.environ.get(key_name):
            log.error("Missing %s. Set it in .env or environment.", key_name)
            sys.exit(1)

    total_files = sum(s.variations for s in scenarios)
    log.info("Selected %d scenarios → %d files to generate", len(scenarios), total_files)

    asyncio.run(generate_all(
        scenarios=scenarios,
        provider=args.provider,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
        delay_ms=args.delay,
    ))


if __name__ == "__main__":
    main()
