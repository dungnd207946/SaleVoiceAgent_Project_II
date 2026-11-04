# Design — Background prompt-cache warm after summary

Date: 2026-07-03 · Branch: `feat/connect-db`

## Problem

The async summary is injected into the **system prompt** (via
`builder.build_system_prompt` → `PROMPT_TEMPLATE.md`). The system prompt sits at
the very front of every LLM request. When a summary lands, that prefix text
changes, so the provider's prompt cache is invalidated **from the summary token
onward**. The next live turn then reprocesses the whole system prompt (SOUL +
RULES + 15-project table + customer + summary) plus its messages — a visible
latency spike right after every summary event.

The live main-agent provider is DashScope/Qwen (`NOBLE_AGENT_MODEL=qwen3.6-flash`),
which — like OpenAI, Gemini, and vLLM — does **automatic implicit prefix
caching**. Anthropic caches only the explicit `cache_control` system block
(already set in `anthropic_provider.py`). Either way, the summary bust is real.

## Goal

After a summary is persisted, pay the reprocessing cost **in the background**
so the next user-facing turn hits a warm cache. Must work with **every**
provider without provider-specific cache logic.

## Approach — replay the next turn's request as a throwaway warm call

Key idea for provider-agnosticism: do **not** implement any per-provider cache
handling. Instead fire one LLM request **byte-identical in its cacheable prefix**
to what the next turn will send, through the same `stream_completion` path with
the same `model` map, `primary`, `tools`, and `temperature`. Each provider's own
caching (implicit prefix cache for DashScope/OpenAI/Gemini/vLLM; explicit
system-block `cache_control` for Anthropic) then applies naturally. Providers
with no caching → the warm is a harmless discarded no-op (zero regression).

Routing uses the same `primary` + fallback chain, so the warm targets the exact
provider the next turn will hit.

### Flow

```
Turn N done → save_all → (pending_user_turns > K) → bg task:
  _run_summary_then_warm():
    new_summary = await summarize_and_persist(...)      # ALWAYS completes (own task, not cancelled)
    if new_summary is None or not settings.summary_warm_cache: return
    _schedule_warm(sid, history_snapshot, new_summary, customer_snapshot)   # separate, cancellable task

  _warm():
    msgs = [ {"role":"system", "content": build_system_prompt(agent, customer_snapshot, new_summary)} ]
         + [ m.to_openai() for m in history_snapshot[new_summary.covers_turns:] ]
    await llm.stream_completion(messages=msgs, tools=agent.tool_schemas,
                                model=model_map, primary=agent_primary,
                                temperature=agent.temperature,
                                max_tokens=_WARM_MAX_TOKENS(=16), on_token=<no-op>)   # result discarded
```

At the **start of every `handle_turn`**, cancel the in-flight warm task for the
sid (mirrors `semcache.cancel_refresh`). Only the warm is cancelled — the summary
runs in its own task and always finishes. Rationale: a warm still running when
the next live turn starts would contend for LLM bandwidth and *slow* that turn
(the same reason semcache cancels its refresh).

## Changes

1. **`agent/summary/summarizer.py`** — `summarize_and_persist` returns
   `ThreadSummary | None` (None on skip/failure) instead of always None. Existing
   callers only `await` it (ignore the return), so no breakage.

2. **`agent/orchestrator.py`**
   - `__init__`: `self._warm_tasks: dict[str, asyncio.Task] = {}`.
   - `handle_turn` top: cancel `self._warm_tasks.get(sid)` next to the semcache cancel.
   - Replace the summary `create_task` with a task wrapping `_run_summary_then_warm`,
     passing snapshots: `list(state.history)` and `customer.model_copy(deep=True)`
     (snapshot = end-of-turn-N state = exactly what turn N+1 loads from repo).
   - Add `_run_summary_then_warm(...)` and `_schedule_warm(...)` + `_warm(...)`.
   - `_warm` wraps `try/except`: re-raise `CancelledError`, log-and-swallow
     `Exception`. It never touches history/state/repo and never streams to
     callbacks (no-op `on_token`), and never dispatches tools (a stray tool_call
     in the discarded output is ignored).
   - Import `build_system_prompt`.

3. **`config.py`** — `summary_warm_cache: bool = Field(True, alias="NOBLE_SUMMARY_WARM_CACHE")`.
   Module constant `_WARM_MAX_TOKENS = 16` in orchestrator (no env needed).

4. **Tests** (`tests/unit/unified/`)
   - After a summary, warm is called with the right shape: `messages[0]` is a
     system message containing the new summary text; the tail equals
     `history[covers:]`; `tools`, `primary`, and the `model` map are passed.
   - `NOBLE_SUMMARY_WARM_CACHE=false` → no warm.
   - Summary skipped (not enough turns) → no warm.
   - A new `handle_turn` cancels the prior warm task.
   - Warm raising an exception is swallowed; summary/turn unaffected.

## Non-goals

No change to prompt structure, no new/moved `cache_control` breakpoints, no
change to the summary trigger logic. Warm is best-effort latency optimization
only.
