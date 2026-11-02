# Global LLM thinking-mode toggle

**Date:** 2026-06-04
**Branch:** feat/unify-agent
**Status:** Approved (brainstorm) → TDD

## Problem

Running the base model `Qwen/Qwen3-0.6B` via vLLM (through the **OpenAI provider
slot**, `OPENAI_BASE_URL=http://localhost:8000/v1`) produces reasoning output that
leaks into the response content:

```
<think>
Okay, the user just said "hi"...
</think>

Chào anh/chị! Em là nhân viên Noble Real Estate...
```

Those `<think>...</think>` spans flow into the streamed `on_token` callback (and
thus TTS) and into stored conversation history. There is no way to disable
thinking. Two settings that *look* like they should control this —
`openai_reasoning_effort` and `dashscope_enable_thinking` ([config.py](../../../src/noble_agent/config.py)) —
are **dead**: `StreamingClient` never passes `extra_body`/`reasoning_effort` to any
provider.

## Goal

One env toggle that enables/disables thinking, working across all three active
providers (anthropic → openai → gemini), so a thinking-capable model can be run
with thinking off.

## Decisions (from brainstorm)

| Decision | Choice |
|---|---|
| Toggle shape | **One global flag**, translated per provider |
| Default | **OFF** (`false`) — voice agent, latency + leaked tokens |
| Defensive strip | **Yes** — strip `<think>` even when the flag is off |
| Gemini | send `reasoning_effort="none"` when disabled |
| Process | short spec + direct TDD this session |

## Design — two defense layers

### Single flag, attached to the shared client

`NOBLE_LLM_ENABLE_THINKING: bool = false` added to `UnifiedSettings`.

All three LLM paths (main agent, summary, semcache) share **one**
`StreamingClient` built in [facade.py](../../../src/noble_agent/agent/facade.py).
So the flag lives on the client:

```python
StreamingClient(providers, enable_thinking: bool = True)
```

Facade passes `enable_thinking=settings.llm_enable_thinking`. The param defaults
to `True` so existing call sites/tests (`StreamingClient(providers=...)`) keep the
exact current behavior — **no change to runner, summarizer, or semcache**.

### Layer 1 — send the disable param to the provider (saves generation cost)

Only when `enable_thinking is False`, `_stream_once` / `complete_once` merge a
provider-specific kwarg, keyed by the provider **name** already available in the
fallback loop:

| Provider slot | Disable kwarg |
|---|---|
| `openai` (vLLM/Qwen/DashScope-style) | `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` |
| `gemini` | `reasoning_effort="none"` |
| `anthropic` | none — Claude never emits `<think>` into content; extended thinking is off by default |

When `enable_thinking is True` → no extra kwargs at all (pure passthrough).

**Trade-off (documented in `.env.example`):** `chat_template_kwargs` is the
vLLM/Qwen convention. If the `openai` slot is ever pointed at the real OpenAI API,
the default-off path would attach this `extra_body` and OpenAI may reject it (400).
This repo is configured for vLLM/Qwen, so it is acceptable; Layer 2 is the
universal guarantee regardless.

### Layer 2 — strip `<think>...</think>` from output (hard guarantee)

A base model may ignore the flag and still emit `<think>`. So when thinking is
**disabled**, run a stateful `_ThinkStripper` over the token stream.

`_ThinkStripper` (new module `agent/llm/thinking.py`):

- `feed(piece: str) -> str` — returns the cleaned text safe to emit now.
- `flush() -> str` — returns any trailing buffered text at stream end.
- Tolerates tags split across chunks (`<thi` + `nk>`, `</thin` + `k>`).
- States: **outside** (emit, but hold back any suffix that is a prefix of
  `<think>`); **inside** (suppress everything, hold back any suffix that is a
  prefix of `</think>`).
- On `flush()`: if still **inside** (unterminated `<think>`) → return `""`
  (discard incomplete reasoning); if **outside** → return the buffered remainder
  (it was real text).

Integration:

- `_stream_once`: build a stripper iff `not self._enable_thinking`. For each
  chunk content piece: `clean = stripper.feed(piece)`; if `clean`, append to
  `content_parts` and `await on_token(clean)`. After the loop:
  `tail = stripper.flush()`; if `tail`, append + emit. Tool-call handling is
  unchanged. When thinking is enabled, the current code path runs untouched.
- `complete_once` (non-streaming, summary path): if `not self._enable_thinking`,
  apply `re.sub(r"<think>.*?</think>", "", content, flags=re.S)` to the result.

Strip applies to **both** the returned `content` (→ history) and `on_token`
(→ TTS), so both are always clean.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `agent/llm/thinking.py` :: `_ThinkStripper` | Streaming `<think>` removal across chunk boundaries | nothing |
| `agent/llm/thinking.py` :: `disable_thinking_kwargs(name)` | Map provider name → disable kwargs | nothing |
| `StreamingClient` (`client.py`) | Hold `enable_thinking`; inject kwargs + apply stripper | thinking.py |
| `UnifiedSettings` (`config.py`) | `llm_enable_thinking` env field | — |
| `build_runner` / `StreamingClient` ctor (`facade.py`) | Wire setting → client | config |

## Testing (TDD, `tests/unit/unified/`)

`_ThinkStripper` (table-driven):
- No tags → passthrough.
- Whole `<think>...</think>` in one piece → removed.
- Tags split across chunks (open and close) → removed.
- Content before and after the block preserved.
- Multiple blocks.
- Unterminated `<think>` → suppressed, `flush()` returns `""`.
- Partial-`<think>`-prefix at stream end that never completes → emitted on flush.

`StreamingClient`:
- `enable_thinking=False` + `openai` provider → call kwargs include
  `extra_body={"chat_template_kwargs":{"enable_thinking":False}}`; `<think>`
  stripped from streamed content + returned content.
- `enable_thinking=False` + `gemini` → `reasoning_effort="none"` passed.
- `enable_thinking=False` + `anthropic` → no extra kwargs.
- `enable_thinking=True` (default) → no extra kwargs, no stripping (regression
  guard).
- `complete_once` with `enable_thinking=False` strips `<think>` from result.

Run: `make test-unified`, `make lint`. Then SMOKE.md turn-loop check.

## Out of scope

- Removing the dead `openai_reasoning_effort` / `dashscope_enable_thinking`
  settings (pre-existing; leave untouched).
- Per-provider thinking flags.
- Enabling Anthropic extended thinking (`thinking` param) — only disabling is
  requested.
- Stripping when thinking is explicitly enabled (user opted in).
