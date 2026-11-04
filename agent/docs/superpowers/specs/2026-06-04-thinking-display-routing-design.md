# Thinking display routing — hide from UI/TTS/eval, keep in history

**Date:** 2026-06-04
**Branch:** feat/unify-agent
**Status:** Approved (brainstorm) → TDD
**Builds on:** [2026-06-04-llm-thinking-toggle-design.md](2026-06-04-llm-thinking-toggle-design.md)

## Problem

With `NOBLE_LLM_ENABLE_THINKING=true` the model generates `<think>...</think>`
reasoning. Today that is pure passthrough: thinking leaks into the chat UI and
TTS. We want thinking **generated and kept in history** (so the LLM sees its own
reasoning) but **hidden from every human/eval-facing surface**.

## Decisions (from brainstorm)

| Decision | Choice |
|---|---|
| "Keep thinking in history" | **Persist cross-turn** — raw thinking stays in `state.history`; every future turn's LLM call includes it |
| Chat-UI debug view | **Add a separate flag** `NOBLE_LLM_SHOW_THINKING` (default `false`) so the text tester can show thinking; **TTS always strips** |

## Key architectural fact

The two output channels are already separate:

- **History channel** — `StreamingClient.stream_completion` **returns** the
  content; [runner.py](../../../src/noble_agent/agent/runner.py) stores it in
  `state.history` (persisted to Redis, forwarded to the LLM). In enabled mode the
  client returns **raw**, so history keeps thinking. **No runner change.**
- **Display channel** — `on_token` → facade `_Callbacks` → transport
  (voice `buf.add`→TTS; chat → browser). This is where we strip for display.

Because both transports route through `NobleAgent.stream_response` →
`_Callbacks.on_token`, stripping happens in **one place** (the facade), gated by
a per-call `show_thinking`.

## Two independent flags

- `NOBLE_LLM_ENABLE_THINKING` (existing) — does the model generate thinking
  (send the disable kwarg or not). Controls whether history contains thinking.
- `NOBLE_LLM_SHOW_THINKING` (new, default `false`) — does the **chat UI** show
  thinking. The voice transport never passes it (always `false`), so **TTS
  always strips**.

## Behavior matrix (`ENABLE_THINKING=true`)

| Destination | Result | Mechanism |
|---|---|---|
| history (LLM context) | raw, persisted cross-turn | client returns raw → runner (unchanged) |
| TTS (voice) | always stripped | facade `_Callbacks` stripper (voice passes `show_thinking=False`) |
| chat UI | stripped unless `SHOW_THINKING=true` | facade `_Callbacks` stripper, gated by `show_thinking` |
| eval prediction | always stripped | `strip_think` on returned content in `eval/predict.py` |

`ENABLE_THINKING=false` is unchanged from the prior spec: the client sends the
disable kwarg and strips both the stream and the return, so thinking is absent
everywhere including history (consistent — thinking lives in history only when
generation is on).

## Components changed

| Unit | Change |
|---|---|
| `config.py` | add `llm_show_thinking: bool = Field(False, alias="NOBLE_LLM_SHOW_THINKING")` |
| `agent/facade.py` :: `_Callbacks` | optional `ThinkStripper`; `on_token` feeds it (forwards only cleaned text) and a `flush()` drains the tail; `stream_response(..., show_thinking=False)` builds the stripper when `not show_thinking` and calls `flush` after the turn |
| `server/text_chat.py` | pass `show_thinking=get_settings().llm_show_thinking` to `stream_response` |
| `voice/voice_agent.py` | **no change** — default `show_thinking=False` → TTS stripped |
| `eval/predict.py` | `build_predictor` constructs the client with `enable_thinking=settings.llm_enable_thinking`; `predict_turn` applies `strip_think` to the returned content |
| `agent/llm/client.py` | **no change** (already correct: enabled→raw return + raw stream; disabled→stripped both) |

`ThinkStripper` / `strip_think` already exist in `agent/llm/thinking.py`.

## Stripper lifecycle in `_Callbacks`

- One `ThinkStripper` per `stream_response` call (per turn).
- `<think>` opens and closes within a single assistant message; between LLM
  iterations no tokens flow through `on_token` (tool results don't), so the
  stripper is "outside" between messages — a single per-turn instance is correct.
- `stream_response` calls `cb.flush()` after `handle_turn` returns so a trailing
  partial-tag prefix that turned out to be real text is still emitted. Order
  holds: the voice path's `buf.flush()` runs after `stream_response` returns, so
  the flushed tail reaches `buf.add` first.

## Testing (TDD)

`tests/unit/unified/` — `_Callbacks`:
- stripper present (`show_thinking=False`): `<think>...</think>` removed from
  forwarded tokens and from `sink`; tags split across `feed` calls handled;
  trailing real text emitted on `flush`.
- stripper absent (`show_thinking=True`): tokens pass through verbatim.

`tests/unit/eval/test_predict.py`:
- `predict_turn` strips `<think>...</think>` from `content`; `tool_calls`
  untouched.

Run: `make test-unified`, `pytest tests/unit/eval`, `make lint`.

## Out of scope

- Showing thinking in the voice/TTS path (never).
- Changing `enable_thinking=false` behavior.
- Qwen `reasoning_content` separate-field handling (current vLLM setup emits
  `<think>` inline in content).
