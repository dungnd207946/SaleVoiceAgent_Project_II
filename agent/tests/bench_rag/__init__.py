"""RAG integration for bench_llm — FAQ inject + FlatStore backend."""

from .faq_inject import clear_faq_cache, inject_faq
from .flat_store_runner import (
    ensure_warmed_up,
    get_flat_store,
    real_noble_search,
    shutdown_flat_store,
)
from .metrics import evaluate_case
from .scenarios_loader import SCENARIO_NAMES, load_scenarios
from .tool_timing import ToolTimingCollector, get_collector, reset_collector
from .warmup import PhaseReport, WarmupConfig, print_report, warmup_all

__all__ = [
    "inject_faq",
    "clear_faq_cache",
    "get_flat_store",
    "ensure_warmed_up",
    "real_noble_search",
    "shutdown_flat_store",
    "load_scenarios",
    "SCENARIO_NAMES",
    "evaluate_case",
    "get_collector",
    "reset_collector",
    "ToolTimingCollector",
    "WarmupConfig",
    "PhaseReport",
    "warmup_all",
    "print_report",
]
