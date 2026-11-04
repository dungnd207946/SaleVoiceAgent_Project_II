# E2E Scenario Harness — Design

**Date:** 2026-07-03
**Status:** approved (in-chat), implementing
**Scope:** a lightweight, deterministic, assertion-based conversation-test harness for
the Noble Voice Agent, runnable with one command before every commit/deploy.

## Problem

The repo already has two conversation-level systems, but neither is a fast
regression gate:

- `tests/bench_estate/` — scores replies with an **LLM judge** (fuzzy, costs money,
  slow). Good for *answer quality*, wrong tool for a quick behavioural check.
- `src/synthetic/` — drives full persona conversations but has **no pass/fail**; it
  generates data.

Missing: a **fast, deterministic, no-judge, no-audio** harness where a scripted
conversation asserts *behaviour* (which tools fired, with what args, what the reply
must / must not contain, what customer state resulted) and returns a clear
pass/fail. Runnable every time before commit.

## Non-goals (v1)

- No LLM judge (that stays `bench_estate`).
- No audio / STT / TTS (text-brain only; a voice layer can be added later).
- No per-scenario model switching (the run uses the configured agent; an optional
  run-level `--model` sets `NOBLE_AGENT_MODEL` before the runner is built).

## Layer

Drives the **production agent brain** through the same entrypoint as voice/text:
`NobleAgent.stream_response(user_text=..., on_tool_start=, on_tool_done=)`
(`agent/facade.py`). Tool calls + args + results are captured live via callbacks;
`agent.get_customer()` snapshots customer state after each turn. → exercises
LLM + tools + RAG + Redis exactly like production.

## Determinism

The agent is an LLM, so wording varies run-to-run. Assertions therefore target
**behaviour and forbidden patterns**, not exact phrasing:

- robust: `tool_called`, `tool_arg`, `customer_field`, `escalated`, `reply_not_matches`
  (e.g. block invented prices `\d+\s*(tỷ|triệu)`).
- use sparingly, on stable tokens only: `reply_contains` / `reply_contains_any`
  (project names, "để lại số điện thoại"). Substring matching is case-insensitive.

Set `temperature=0` + a fixed model in `.env` (or `--model`) to reduce variance.

## Scenario file (YAML)

`tests/e2e_scenarios/scenarios/<name>.yaml`:

```yaml
name: coldcall_nclb
description: Khách hỏi NCLB → agent search RAG, nhắc đúng tên, không tự phun giá
customer: { name: null }          # optional: seed customer fields before turn 1
turns:
  - user: "Anh muốn hỏi về dự án Noble Crystal Long Biên"
    expect:
      tool_called: noble_search
      tool_arg: { tool: noble_search, arg: project_filter, equals: NCLB }
      reply_contains_any: ["Noble Crystal Long Biên", "Long Biên"]
      customer_field: { field: project_interest, equals: NCLB }
  - user: "Giá một căn bao nhiêu?"
    expect:
      reply_not_matches: '\d+\s*(tỷ|triệu)'   # giá private → không tự phun số
```

### Assertion vocabulary

| key | meaning | value form |
|---|---|---|
| `tool_called` | tool được dispatch trong turn | str \| list[str] (tất cả phải xuất hiện) |
| `tool_not_called` | tool KHÔNG được gọi | str \| list[str] |
| `tool_arg` | kiểm tra tham số 1 tool | `{tool, arg, equals}` hoặc `{tool, arg, contains}` (hoặc list) |
| `reply_contains` | substring bắt buộc có (mọi phần tử) | str \| list[str] |
| `reply_contains_any` | ít nhất 1 phần tử có | list[str] |
| `reply_not_contains` | substring không được có | str \| list[str] |
| `reply_matches` | regex phải khớp | regex |
| `reply_not_matches` | regex không được khớp | regex |
| `customer_field` | state sau turn | `{field, equals}` hoặc `{field, contains}` (hoặc list) |
| `escalated` | escalate có/không được gọi | bool |

Unknown keys → hard `ValueError` at load time (fail fast).

## Components (all under `tests/e2e_scenarios/`)

- `loader.py` — YAML → frozen `Scenario`/`Turn`; validates structure + expect keys. Pure.
- `assertions.py` — `evaluate(expect, TurnResult) -> list[AssertionResult]`. Pure, no I/O.
- `runner.py` — drives `NobleAgent` per scenario; builds `TurnResult` (reply, tool
  calls, customer snapshot); calls `evaluate`. Async, needs Redis + LLM.
- `__main__.py` — CLI + terminal report. `python -m tests.e2e_scenarios [--scenario N] [--model M] [-v]`.
- `scenarios/*.yaml` — the reusable test bank (ships with 2 examples).
- `tests/test_loader.py`, `tests/test_assertions.py` — pure unit tests (no LLM),
  collected by `make test`.
- `README.md` — how to author + run.

## Run

```bash
docker compose up -d redis        # already provisioned in this env
make e2e                          # all scenarios
python -m tests.e2e_scenarios --scenario coldcall_nclb -v
```

Prereqs are the same as running the agent (≥1 LLM key, Redis, a working RAG backend).
Exit code non-zero if any scenario fails → CI-friendly.

## Testing strategy

The value split keeps the harness itself testable without an LLM:
- `loader` + `assertions` are pure → real unit tests with fabricated `TurnResult`.
- `runner` is the thin live-integration layer, exercised by `make e2e`.
