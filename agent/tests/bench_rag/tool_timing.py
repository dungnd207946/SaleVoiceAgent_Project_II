"""Per-tool timing collector for bench_llm."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    args_preview: str
    ms: float
    project: str = ""
    turn_index: int = -1


@dataclass
class ToolTimingCollector:
    calls: list[ToolCall] = field(default_factory=list)
    turn_index: int = 0

    def new_turn(self) -> None:
        self.turn_index += 1

    def record(self, name: str, args: dict[str, Any], ms: float) -> None:
        proj = args.get("project_filter") or args.get("project_code") or args.get("project") or ""
        preview = str({k: v for k, v in args.items() if k not in ("query",)})[:80]
        self.calls.append(
            ToolCall(name=name, args_preview=preview, ms=ms, project=str(proj), turn_index=self.turn_index)
        )

    def last_turn_calls(self) -> list[ToolCall]:
        return [c for c in self.calls if c.turn_index == self.turn_index]

    def print_turn_breakdown(self, color_mod: Any = None) -> None:
        last = self.last_turn_calls()
        if not last:
            return
        head = f"{color_mod.DIM}[Tool Breakdown]{color_mod.RESET}" if color_mod else "[Tool Breakdown]"
        print(f"  {head}")
        total = 0.0
        for c in last:
            proj_tag = f" project={c.project}" if c.project else ""
            print(f"    {c.name}({c.args_preview}){proj_tag}: {c.ms:.0f}ms")
            total += c.ms
        if total > 0:
            print(f"    Total tool time: {total:.0f}ms")

    def summary(self) -> dict[str, dict[str, Any]]:
        by_name: dict[str, list[float]] = {}
        for c in self.calls:
            by_name.setdefault(c.name, []).append(c.ms)
        out: dict[str, dict[str, Any]] = {}
        for name, mss in by_name.items():
            mss_sorted = sorted(mss)
            out[name] = {
                "count": len(mss),
                "p50": statistics.median(mss),
                "p95": mss_sorted[int(len(mss_sorted) * 0.95)] if len(mss_sorted) > 1 else mss_sorted[0],
                "total_ms": sum(mss),
            }
        return out

    def print_summary(self, color_mod: Any = None) -> None:
        summ = self.summary()
        if not summ:
            return
        if color_mod:
            print(f"\n{color_mod.CYAN}{color_mod.BOLD}Tool Performance Summary{color_mod.RESET}")
        else:
            print("\nTool Performance Summary")
        print(f"  {'tool':<28} {'count':>6} {'p50':>8} {'p95':>8} {'total':>9}")
        print("  " + "-" * 62)
        for name in sorted(summ):
            s = summ[name]
            print(f"  {name:<28} {s['count']:>6} {s['p50']:>7.0f}ms {s['p95']:>7.0f}ms {s['total_ms']:>8.0f}ms")

    def reset(self) -> None:
        self.calls.clear()
        self.turn_index = 0


# Module-level singleton
_COLLECTOR: ToolTimingCollector | None = None


def get_collector() -> ToolTimingCollector:
    global _COLLECTOR
    if _COLLECTOR is None:
        _COLLECTOR = ToolTimingCollector()
    return _COLLECTOR


def reset_collector() -> None:
    global _COLLECTOR
    if _COLLECTOR is not None:
        _COLLECTOR.reset()
