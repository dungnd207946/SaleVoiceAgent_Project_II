"""Warmup orchestration for bench_llm — pre-encode models/caches before measurement."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WarmupConfig:
    need_flat_store: bool = False
    need_faq_search: bool = False
    need_memory_router: bool = False
    providers: list[tuple[str, Any, str]] = field(default_factory=list)  # (name, client, model)


@dataclass
class PhaseReport:
    name: str
    ms: float
    status: str  # "ok" | "skip" | "fail"
    detail: str = ""


async def _phase_flat_store(cfg: WarmupConfig) -> PhaseReport:
    t = time.monotonic()
    if not cfg.need_flat_store:
        return PhaseReport("FlatStore (e5-large ONNX)", 0, "skip", "not required for mode")
    try:
        from bench_rag import ensure_warmed_up

        await ensure_warmed_up()
        return PhaseReport("FlatStore (e5-large ONNX)", (time.monotonic() - t) * 1000, "ok", "loaded + warmed")
    except Exception as e:
        return PhaseReport("FlatStore (e5-large ONNX)", (time.monotonic() - t) * 1000, "fail", str(e))


async def _phase_faq_search(cfg: WarmupConfig) -> PhaseReport:
    t = time.monotonic()
    if not cfg.need_faq_search:
        return PhaseReport("FAQ searcher (e5-large share)", 0, "skip", "not required")
    try:
        from bench_rag.faq_search import get_searcher

        searcher = await get_searcher()
        n_items = await searcher.ensure_indexed()
        return PhaseReport(
            "FAQ searcher (e5-large share)", (time.monotonic() - t) * 1000, "ok", f"indexed {n_items} items"
        )
    except Exception as e:
        return PhaseReport("FAQ searcher (e5-large share)", (time.monotonic() - t) * 1000, "fail", str(e))


async def _phase_memory_router(cfg: WarmupConfig) -> PhaseReport:
    t = time.monotonic()
    if not cfg.need_memory_router:
        return PhaseReport("MemoryRouter (FAISS+Qdrant)", 0, "skip", "not required")
    try:
        from noble_agent.agent.rag.memory_router import get_router

        router = await get_router()
        # quick dummy query
        await router.query_context(text="warmup", project_filter="NCLB")
        return PhaseReport("MemoryRouter (FAISS+Qdrant)", (time.monotonic() - t) * 1000, "ok", "connected")
    except Exception as e:
        return PhaseReport("MemoryRouter (FAISS+Qdrant)", (time.monotonic() - t) * 1000, "fail", str(e))


async def _phase_provider_ping(name: str, client: Any, model: str) -> PhaseReport:
    t = time.monotonic()
    try:
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return PhaseReport(f"LLM {name}/{model}", (time.monotonic() - t) * 1000, "ok", "pinged")
    except Exception as e:
        return PhaseReport(f"LLM {name}/{model}", (time.monotonic() - t) * 1000, "fail", str(e)[:80])


async def warmup_all(cfg: WarmupConfig) -> list[PhaseReport]:
    """Run warmup phases. Serial for GPU/ONNX, parallel for network."""
    # Phase 1-2 serial (share ONNX session)
    p1 = await _phase_flat_store(cfg)
    p2 = await _phase_faq_search(cfg)
    # Phase 3+ parallel
    tasks: list = []
    tasks.append(_phase_memory_router(cfg))
    for n, c, m in cfg.providers:
        if c is not None:
            tasks.append(_phase_provider_ping(n, c, m))
    rest = await asyncio.gather(*tasks, return_exceptions=False)
    return [p1, p2, *rest]


def print_report(phases: list[PhaseReport], color_mod: Any = None) -> None:
    if color_mod:
        print(f"\n{color_mod.CYAN}{color_mod.BOLD}Warmup{color_mod.RESET}")
    else:
        print("\nWarmup")
    total = 0.0
    for p in phases:
        status_icon = {"ok": "[ok]", "skip": "[--]", "fail": "[!!]"}.get(p.status, "[?]")
        color_start = color_end = ""
        if color_mod:
            color_start = {"ok": color_mod.GREEN, "skip": color_mod.DIM, "fail": color_mod.RED}.get(p.status, "")
            color_end = color_mod.RESET
        dim_start = color_mod.DIM if color_mod else ""
        dim_end = color_mod.RESET if color_mod else ""
        if p.status == "skip":
            print(f"  {color_start}{status_icon} {p.name}{color_end}  {dim_start}{p.detail}{dim_end}")
        else:
            print(f"  {color_start}{status_icon} {p.name}{color_end}  {p.ms:.0f}ms  {dim_start}{p.detail}{dim_end}")
        if p.status != "skip":
            total += p.ms
    print(f"  {'-' * 50}")
    print(f"  Total warmup: {total:.0f}ms\n")
