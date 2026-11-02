"""Trace format — the eval harness's first-class artifact.

A trace file is JSONL: line 1 is the run header (config that a report needs to
describe itself), every later line is one case. RUN writes it; SCORE reads it.
Because scoring never touches the agent, thresholds and rubrics can change
without spending another agent turn.

Pure: no `noble_agent` import, so scorers and tests stay environment-free.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TracedToolCall:
    name: str
    args: dict
    raw_result: str | None = None


@dataclass(frozen=True)
class TraceTurn:
    user: str
    reply: str
    tool_calls: tuple[TracedToolCall, ...] = ()
    customer_after: dict | None = None
    ttft_ms: float | None = None
    total_ms: float = 0.0
    loop_exhausted: bool = False


@dataclass(frozen=True)
class TraceCase:
    case_id: str
    tags: tuple[str, ...] = ()
    tenant: str = ""
    channel: str = ""
    reviewed: bool = False
    turns: tuple[TraceTurn, ...] = ()
    error: str | None = None
    # Spec §4.2 self-description, captured from the agent that actually ran this
    # case. `pinned_version` = the config version the conversation is pinned to
    # (0 = legacy/package mode); `temperature` = the value the turn loop used
    # (in `legacy` mode that is the bundle's config.json, not settings). `None` =
    # unavailable (e.g. the agent never got built because the case crashed first).
    pinned_version: int | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class TraceHeader:
    run_id: str
    started_at: str
    config: dict


def _turn_to_dict(turn: TraceTurn) -> dict:
    return {
        "user": turn.user,
        "reply": turn.reply,
        "tool_calls": [{"name": tc.name, "args": tc.args, "raw_result": tc.raw_result} for tc in turn.tool_calls],
        "customer_after": turn.customer_after,
        "ttft_ms": turn.ttft_ms,
        "total_ms": turn.total_ms,
        "loop_exhausted": turn.loop_exhausted,
    }


def _turn_from_dict(data: dict) -> TraceTurn:
    return TraceTurn(
        user=data.get("user", ""),
        reply=data.get("reply", ""),
        tool_calls=tuple(
            TracedToolCall(name=tc.get("name", ""), args=tc.get("args") or {}, raw_result=tc.get("raw_result"))
            for tc in data.get("tool_calls") or ()
        ),
        customer_after=data.get("customer_after"),
        ttft_ms=data.get("ttft_ms"),
        total_ms=float(data.get("total_ms") or 0.0),
        loop_exhausted=bool(data.get("loop_exhausted")),
    )


def write_traces(path: Path, header: TraceHeader, cases: Iterable[TraceCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "kind": "header",
                    "run_id": header.run_id,
                    "started_at": header.started_at,
                    "config": header.config,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        for case in cases:
            f.write(
                json.dumps(
                    {
                        "kind": "case",
                        "case_id": case.case_id,
                        "tags": list(case.tags),
                        "tenant": case.tenant,
                        "channel": case.channel,
                        "reviewed": case.reviewed,
                        "error": case.error,
                        "pinned_version": case.pinned_version,
                        "temperature": case.temperature,
                        "turns": [_turn_to_dict(t) for t in case.turns],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def read_traces(path: Path) -> tuple[TraceHeader, list[TraceCase]]:
    with open(path, encoding="utf-8") as f:
        lines = [x for x in (line.strip() for line in f) if x]
    if not lines:
        raise ValueError(f"{path}: empty trace file")
    head = json.loads(lines[0])
    if head.get("kind") != "header":
        raise ValueError(f"{path}: first line must be the header, got kind={head.get('kind')!r}")
    header = TraceHeader(
        run_id=head.get("run_id", ""), started_at=head.get("started_at", ""), config=head.get("config") or {}
    )
    cases: list[TraceCase] = []
    for raw in lines[1:]:
        data = json.loads(raw)
        cases.append(
            TraceCase(
                case_id=data.get("case_id", ""),
                tags=tuple(data.get("tags") or ()),
                tenant=data.get("tenant", ""),
                channel=data.get("channel", ""),
                reviewed=bool(data.get("reviewed")),
                turns=tuple(_turn_from_dict(t) for t in data.get("turns") or ()),
                error=data.get("error"),
                pinned_version=None if data.get("pinned_version") is None else int(data["pinned_version"]),
                temperature=None if data.get("temperature") is None else float(data["temperature"]),
            )
        )
    return header, cases
