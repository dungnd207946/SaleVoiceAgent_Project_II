"""Eval case schema v2 + JSONL loader (spec 2026-08-25 §4).

Scorer kích hoạt theo NỘI DUNG block: `expect` → policy, `golden.tools` →
tool_selection, `golden.answer` → judge. `tags` CHỈ để filter/report — không
scorer nào đọc nó để quyết định chấm gì (đó là lý do axis cũ bị bỏ).

Validation strict — unknown key raise tại load time, lỗi kể tên file:line.
Pure: no agent import, no I/O ngoài đọc JSONL được đưa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tests.e2e_scenarios.assertions import KNOWN_KEYS

TAGS: frozenset[str] = frozenset({"policy", "tool", "qa", "multiturn", "smoke"})
ORIGINS: frozenset[str] = frozenset({"structured", "kb", "document", "unanswerable", "handwritten"})
CHANNELS: frozenset[str] = frozenset({"chat", "voice"})

# Key tool bị đuổi khỏi expect: nó sống ở golden.tools/banned_tools để vocabulary
# của policy scorer và tool scorer disjoint (hết double-count, hết cần axis làm
# nguồn sự thật). Chỉ còn `tool_called` vì `tool_not_called`/`tool_arg` đã XOÁ khỏi
# KNOWN_KEYS (2026-08-25, không data nào dùng) — hai key đó giờ rơi vào nhánh
# "unknown expect keys" chung, không còn thông báo migration riêng.
FORBIDDEN_EXPECT_KEYS: frozenset[str] = frozenset({"tool_called"})
EXPECT_KEYS: frozenset[str] = KNOWN_KEYS - FORBIDDEN_EXPECT_KEYS

_CASE_KEYS = {"id", "tenant", "origin", "reviewed", "tags", "channel", "turns", "customer"}
_TURN_KEYS = {"user", "expect", "golden"}
_GOLDEN_KEYS = {"answer", "tools", "banned_tools"}
_TOOL_KEYS = {"name", "args"}
_MATCHER_KEYS = frozenset({"contains", "equals"})


@dataclass(frozen=True)
class GoldenTool:
    name: str
    args: dict  # arg_name -> {"contains": str} | {"equals": <json value>}


@dataclass(frozen=True)
class TurnGolden:
    answer: str = ""
    tools: tuple[GoldenTool, ...] = ()
    banned_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalTurn:
    user: str
    expect: dict
    golden: TurnGolden | None = None


@dataclass(frozen=True)
class EvalCase:
    id: str
    origin: str
    tenant: str
    channel: str
    reviewed: bool
    tags: tuple[str, ...]
    turns: tuple[EvalTurn, ...]
    customer: dict | None = None


def _req_str(data: dict, key: str, source: str) -> str:
    value = data.get(key)
    if not value or not isinstance(value, str):
        raise ValueError(f"{source}: case needs a non-empty string {key!r}")
    return value


def _parse_matcher(raw, *, source: str, where: str) -> dict:
    if not isinstance(raw, dict) or set(raw) - _MATCHER_KEYS or len(raw) != 1:
        raise ValueError(f"{source}: {where} matcher must be exactly one of {sorted(_MATCHER_KEYS)}, got {raw!r}")
    if "contains" in raw and not isinstance(raw["contains"], str):
        raise ValueError(f"{source}: {where} 'contains' must be a string")
    return dict(raw)


def _parse_golden_tool(raw, *, source: str, index: int, ti: int) -> GoldenTool:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] must be a mapping")
    unknown = set(raw) - _TOOL_KEYS
    if unknown:
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] unknown keys {sorted(unknown)}")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] needs a non-empty string 'name'")
    args_raw = raw.get("args") or {}
    if not isinstance(args_raw, dict):
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] 'args' must be a mapping")
    args = {
        arg: _parse_matcher(m, source=source, where=f"turn {index} golden.tools[{ti}].args[{arg!r}]")
        for arg, m in args_raw.items()
    }
    return GoldenTool(name=name, args=args)


def _parse_golden(raw, *, source: str, index: int) -> TurnGolden | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: turn {index} 'golden' must be a mapping")
    unknown = set(raw) - _GOLDEN_KEYS
    if unknown:
        raise ValueError(f"{source}: turn {index} unknown golden keys {sorted(unknown)}")
    tools_raw = raw.get("tools") or []
    if not isinstance(tools_raw, list):
        raise ValueError(f"{source}: turn {index} golden.tools must be a list")
    banned_raw = raw.get("banned_tools") or []
    if not isinstance(banned_raw, list) or not all(isinstance(b, str) and b for b in banned_raw):
        raise ValueError(f"{source}: turn {index} golden.banned_tools must be a list of non-empty strings")
    return TurnGolden(
        answer=str(raw.get("answer", "") or ""),
        tools=tuple(_parse_golden_tool(t, source=source, index=index, ti=i) for i, t in enumerate(tools_raw)),
        banned_tools=tuple(banned_raw),
    )


def _parse_turn(rt, *, source: str, index: int) -> EvalTurn:
    if not isinstance(rt, dict):
        raise ValueError(f"{source}: turn {index} must be a mapping")
    unknown = set(rt) - _TURN_KEYS
    if unknown:
        raise ValueError(f"{source}: turn {index} unknown keys {sorted(unknown)}")
    user = rt.get("user")
    if not user or not isinstance(user, str):
        raise ValueError(f"{source}: turn {index} needs a non-empty string 'user'")
    expect = rt.get("expect") or {}
    if not isinstance(expect, dict):
        raise ValueError(f"{source}: turn {index} 'expect' must be a mapping")
    forbidden = set(expect) & FORBIDDEN_EXPECT_KEYS
    if forbidden:
        raise ValueError(
            f"{source}: turn {index} expect keys {sorted(forbidden)} moved to "
            "golden.tools/golden.banned_tools (schema v2)"
        )
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise ValueError(
            f"{source}: turn {index} unknown expect keys {sorted(unknown)}; allowed: {sorted(EXPECT_KEYS)}"
        )
    return EvalTurn(user=user, expect=expect, golden=_parse_golden(rt.get("golden"), source=source, index=index))


def parse_case(data: dict, *, source: str = "<dict>") -> EvalCase:
    """Validate a parsed-JSON dict into an `EvalCase`. Raises `ValueError`."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: case must be a mapping, got {type(data).__name__}")
    unknown = set(data) - _CASE_KEYS
    if unknown:
        raise ValueError(f"{source}: unknown case keys {sorted(unknown)} (schema v2 — 'axis' đã thay bằng 'tags')")

    case_id = _req_str(data, "id", source)
    tenant = _req_str(data, "tenant", source)

    origin = data.get("origin")
    if origin not in ORIGINS:
        raise ValueError(f"{source}: unknown origin {origin!r}; allowed: {sorted(ORIGINS)}")

    channel = data.get("channel", "chat") or "chat"
    if channel not in CHANNELS:
        raise ValueError(f"{source}: unknown channel {channel!r}; allowed: {sorted(CHANNELS)}")

    tags_raw = data.get("tags") or []
    if not isinstance(tags_raw, list):
        raise ValueError(f"{source}: 'tags' must be a list")
    bad = [t for t in tags_raw if t not in TAGS]
    if bad:
        raise ValueError(f"{source}: unknown tag(s) {bad}; allowed: {sorted(TAGS)}")

    raw_turns = data.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError(f"{source}: case {case_id!r} needs a non-empty 'turns' list")

    customer = data.get("customer")
    if customer is not None and not isinstance(customer, dict):
        raise ValueError(f"{source}: case {case_id!r} 'customer' must be a mapping")

    return EvalCase(
        id=case_id,
        origin=origin,
        tenant=tenant,
        channel=channel,
        reviewed=bool(data.get("reviewed", False)),
        tags=tuple(tags_raw),
        turns=tuple(_parse_turn(rt, source=source, index=i) for i, rt in enumerate(raw_turns)),
        customer=customer,
    )


def load_cases(path: Path) -> list[EvalCase]:
    """Load one JSONL file. Blank lines skipped; errors name `file:line`."""
    out: list[EvalCase] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            source = f"{path.name}:{lineno}"
            try:
                data = json.loads(line)
            except ValueError as e:
                raise ValueError(f"{source}: not valid JSON — {e}") from e
            out.append(parse_case(data, source=source))
    return out


def load_case_dir(directory: Path) -> list[EvalCase]:
    """Load every `*.jsonl` in `directory`, sorted by filename. Ids must be unique."""
    out: list[EvalCase] = []
    seen: dict[str, str] = {}
    for path in sorted(directory.glob("*.jsonl")):
        for case in load_cases(path):
            if case.id in seen:
                raise ValueError(f"duplicate case id {case.id!r} in {path.name} (first seen in {seen[case.id]})")
            seen[case.id] = path.name
            out.append(case)
    return out
