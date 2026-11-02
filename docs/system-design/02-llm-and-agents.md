# 02 — LLM, Multi-Agent Routing, Tool Loop

> What happens between "user said something" and "agent starts speaking". The LLM streams tokens; tool calls block the stream; multi-agent routing swaps the system prompt; the sentence buffer chops tokens into TTS-ready clauses; deferred narration covers tool latency.

Read [`00-architecture-overview.md`](00-architecture-overview.md) and [`01-stt-and-vad.md`](01-stt-and-vad.md) first.

---

## 1. Anatomy of a turn

```
                 STT final transcript
                          │
                          ▼
       ┌──────────────────────────────────────────────────────┐
       │ V6 pre-turn project-name sniff                       │
       │   project_catalog.normalize(text) → maybe set        │
       │   customer.project_interest in Redis (canonical 4-c) │
       └──────────────────────────────────────────────────────┘
                          ▼
       ┌──────────────────────────────────────────────────────┐
       │ Fast-route classifier (router agent intent guess)    │
       │   may pre-switch agent so first stream uses correct  │
       │   system prompt                                      │
       └──────────────────────────────────────────────────────┘
                          ▼
       ┌──────────────────────────────────────────────────────┐
       │ V10 FAQ semantic inject                              │
       │   e5-large cosine over data/faq/<CODE>_faq.json      │
       │   top-K appended to system prompt tail               │
       └──────────────────────────────────────────────────────┘
                          ▼
       ┌──────────────────────────────────────────────────────┐
       │ StreamingLLM.stream_response                         │
       │   provider streaming + tool loop:                    │
       │     while tool_calls in delta:                       │
       │       on_tool_start → execute_tool → on_tool_done    │
       │       (deferred-narration ack so user hears speech)  │
       │     on_token(content) for each text delta            │
       │     on_agent_switch when switch_agent tool fires     │
       └──────────────────────────────────────────────────────┘
                          ▼
       ┌──────────────────────────────────────────────────────┐
       │ Sentence Buffer                                      │
       │   accumulate tokens; flush on . ! ? : ; …            │
       │   minimum chars per chunk so TTS isn't fed 1-word    │
       └──────────────────────────────────────────────────────┘
                          ▼
                  Streaming TTS (see 03)
                          │
                          ▼
       ┌──────────────────────────────────────────────────────┐
       │ V9 post-turn rebuild                                 │
       │   if tool_loop changed customer.project_interest,    │
       │   refresh_system_prompt() so next turn is fresh      │
       └──────────────────────────────────────────────────────┘
```

The numbered steps (V5–V10) are version markers from successive prompt-engineering revisions. They are documented in repo `CLAUDE.md` §RAG Stack — the labels are stable references.

---

## 2. StreamingLLM — entry point

File: `src/noble_agent/agent/llm/streaming.py`. The class is **the only thing** that makes outbound LLM calls in production. All evals (`tests/bench_estate/`, `tests/bench_llm.py`) call the same code path so latency numbers are real.

### 2.1 Public API

```python
async def stream_response(
    self,
    user_input: str,
    *,
    on_token: Callable[[str], None],
    on_tool_start: Callable | None = None,
    on_tool_done: Callable | None = None,
    on_agent_switch: Callable[[], None] | None = None,
) -> str:
    """Run a full turn. Yields tokens via on_token; returns final assembled text."""
```

Callers (`agent/voice.py`, bench harnesses) supply callbacks rather than reading from a queue. This keeps the LLM module dependency-free of asyncio plumbing — the orchestrator owns the I/O.

### 2.2 Provider negotiation

| Provider | Required env | Selected when |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | First-choice; default `OPENAI_MODEL=gpt-5.4-nano-2026-03-17` |
| Gemini | `GEMINI_API_KEY` | OpenAI not configured / failover after N consecutive errors |
| vLLM (local) | `OPENAI_BASE_URL=http://localhost:8000/v1` | RunPod single-pod stack (Qwen3.6) |
| DashScope | proxy via `OPENAI_BASE_URL` | Qwen cloud |

OpenAI's newer models accept `max_completion_tokens` instead of `max_tokens`. The streaming module branches on provider name (line 419-422) — copy that pattern when adding new providers.

### 2.3 Retry + fallback

- Per call: up to 3 retries on connect/timeout, exponential backoff 1 s/3 s.
- Across calls: if **3 consecutive turns fail OpenAI**, the next turn switches to Gemini for the rest of the session. Logged at WARN; counted in `session_metrics.fallback_count`.
- A tool-call failure during streaming returns `{"error": "..."}` to the LLM; the model gets a chance to recover on the next iteration of the tool loop.

---

## 3. Multi-agent registry

The agent isn't a single persona. There are three (`src/noble_agent/agent/definitions/agents/`):

| Agent | Folder | When |
|---|---|---|
| `router` | `definitions/agents/router/` | Default greeting. Classifies intent, holds the conversation until it can switch |
| `consultant` | `definitions/agents/consultant/` | Real-estate sales — units, pricing, viewing schedules |
| `support` | `definitions/agents/support/` | Existing customer issues — bookings, certificates, complaints |

Each agent ships **three files**:

| File | Role |
|---|---|
| `SOUL.md` (or `IDENTITY.md`) | Persona + tone + Vietnamese-Northern dialect cues. Becomes the system prompt header |
| `SKILL.md` (or per-skill MD under `skills/`) | What the agent must do step by step. Becomes the system prompt body |
| `config.json` | Tool whitelist + model overrides + temperature |

The SOUL/SKILL split lets you tune **what the agent is** independently from **what it knows how to do** — switching tone won't break call flows, and updating a skill won't change the persona.

### 3.1 Switching agents mid-call

The `switch_agent` tool (declared in `agent/tools/schemas.py:325`) is the only way to switch:

```jsonc
// Tool call from router after detecting "I want to schedule a viewing"
{"name": "switch_agent", "arguments": {"target": "consultant"}}
```

When the tool fires:

1. `execute_tool` updates Redis session: `current_agent = consultant`.
2. `on_agent_switch` callback fires.
3. The orchestrator rebuilds the system prompt from the new agent's MD files.
4. The streaming continues from the same user input but with the new prompt — the user perceives one continuous turn.

**You cannot switch back to router automatically**. The router only owns the entry, then hands off. To restart routing, drop the session.

---

## 4. Tool loop

Tools are OpenAI function-calling schemas (`agent/tools/schemas.py`) executed in `agent/tools/__init__.py:execute_tool`. The streaming module enters a loop:

```
LLM streams → delta has tool_calls?
    ├── yes → for each tool_call:
    │        on_tool_start(name, args)
    │        result = await execute_tool(name, args, session_id)
    │        on_tool_done(name, result)
    │        append role="tool" message to history
    │        re-call LLM (next iteration)
    └── no  → on_token(content) for each text delta → done
```

### 4.1 Tool catalogue

Names by category (full schemas in `agent/tools/schemas.py`):

**Knowledge** — `noble_search` (RAG), `list_projects`, `get_project_overview`, `get_project_financial`, `match_projects`, `search_units`, `get_certificate_status`

**Customer state** — `update_customer` (writes Redis), `crm_lookup`, `verify_identity`

**Booking** — `schedule_viewing`, `list_bookings`, `modify_booking`, `check_availability`, `get_booking_state`, `update_booking_info`

**Outreach** — `send_media` (push notification), `validate_phone`

**Workflow** — `switch_agent`, `escalate`, `support_ticket`

### 4.2 V7 auto-side-effect: project_interest

`agent/tools/__init__.py:_v7_auto_set_project_interest` watches every tool call's arguments. If the LLM passed `project_filter="NCLB"` (or any other valid code) to `noble_search`, `match_projects`, etc., that gets written into Redis as `customer.project_interest` even though the model didn't explicitly call `update_customer`. This catches the common case where the model "remembers" the project from context but forgets to record it.

The write is idempotent and cheap; it goes through `project_catalog.normalize()` so aliases map to canonical codes.

### 4.3 Deferred narration

Tool calls that hit external services (`crm_lookup`, `noble_search` cold cache) can take 200–800 ms. During that wait the user hears nothing → bad UX. The mitigation lives in the tool runner:

```
on_tool_start fires
    ↓
Schedule deferred-ack task: wait DEFERRED_ACK_DELAY_MS (default 250 ms)
    ↓ if tool still running:
emit narration: "Em đang tra cứu giúp anh chị nhé..." → goes to TTS
    ↓
on_tool_done cancels the ack task if it hasn't fired yet
```

So fast tools (<250 ms) never trigger narration — no double-talking. Slow tools always get covered. Implementation lives near `agent/tools/__init__.py:321` (`_deferred_ack`).

The narration text comes from `agent/prompts/` per tool name; behavior is covered by `tests/unit/test_tool_ack.py`.

---

## 5. Sentence buffer — turning tokens into clauses

File: `src/noble_agent/agent/sentence_buffer.py`. State: a running string + char counter.

Rules:

1. Append every token from `on_token`.
2. Flush when buffer ends in `[.!?]` AND length ≥ `MIN_FLUSH_CHARS` (default 12).
3. Soft-flush on `[,;:…]` if buffer ≥ `SOFT_FLUSH_CHARS` (default 35) — covers long Vietnamese clauses with no terminal punctuation.
4. Hard-flush on `\n` always.
5. On stream end, flush whatever's left.

Why: TTS engines paying per-character (ElevenLabs) hate single-word chunks. Local TTS (VieNeu) gives smoother audio with full clauses. The buffer is the only thing that talks to TTS; LLM token deltas never go straight there.

Detail on TTS-side handling → [`03-tts-and-audio.md`](03-tts-and-audio.md).

---

## 6. Summarization context (long calls)

When a call exceeds a configurable token budget (~ 6k tokens of history), `agent/summary/generator.py` runs in the background:

1. Pick the oldest non-summarized turns (by index).
2. Call `gpt-5.4-nano` with a strict summarization prompt.
3. Replace those turns with a single `system` message: `"[SUMMARY of turns 1-12] ..."`.
4. Drop the original turns from the active prompt window.

This happens **after** a TTS chunk has flushed — never blocks user-facing speech. Tracked metric: `session_metrics.summarization_runs`.

Disable / tune via:

```bash
SUMMARIZATION_ENABLED=true
SUMMARIZATION_TOKEN_THRESHOLD=6000
SUMMARIZATION_MODEL=gpt-5.4-nano-2026-03-17
```

The `feat/summarization-context` branch (current branch) ships this feature; once merged, defaults stay enabled in production.

---

## 7. RAG hooks (cross-link)

`stream_response` calls into RAG at three places:

| When | What | Detail |
|---|---|---|
| **Pre-turn** | `inject_faq_searched()` adds top-K FAQ matches to system prompt tail | [`04-rag-and-knowledge.md`](04-rag-and-knowledge.md) §3 |
| **Mid-turn (tool)** | `noble_search` tool → FlatStore hybrid retrieval | [`04-rag-and-knowledge.md`](04-rag-and-knowledge.md) §2 |
| **Background** | `SlowThinker` predicts 5 next topics, prefetches into `SemanticCache` | [`04-rag-and-knowledge.md`](04-rag-and-knowledge.md) §4 |

---

## 8. Adding a new tool

1. Define the JSON schema in `agent/tools/schemas.py` — match OpenAI's function tool format. Vietnamese descriptions encouraged; the LLM uses them to pick the tool.
2. Add the implementation handler in `agent/tools/__init__.py:execute_tool` — see `_handle_*` examples.
3. Allow-list it in the relevant agent's `config.json` (`router/config.json`, etc.).
4. Add a unit test under `tests/unit/agent/tools/` mocking external services.
5. If the tool can take >150 ms, add a deferred-narration entry in `agent/prompts/`.
6. Add a benchmark case if it changes the LLM choice space (most tools do — bench it via `tests/bench_llm.py --case <new>`).

---

## 9. Common debugging

| Symptom | Likely cause |
|---|---|
| "Em đang tra cứu nhé..." narration plays for fast tools | `DEFERRED_ACK_DELAY_MS` too low. Default 250 ms is the sweet spot |
| Agent uses wrong project after user says "thôi, dự án Bình thì sao" | V6 sniff missed the alias → check `project_catalog._ALIASES` covers the term |
| Tool result not visible in next turn | `_v7_auto_set_project_interest` only writes specific keys; check the tool's args shape |
| Fallback to Gemini on every call | Check `OPENAI_API_KEY` validity. The 3-strike fallback is per-session; restart server to reset |
| TTS chunks too short, choppy audio | `MIN_FLUSH_CHARS` too low or LLM emitting many short bursts. Tune sentence buffer |
| `switch_agent` happens but prompt didn't refresh | `on_agent_switch` callback wasn't wired in caller — check `agent/voice.py:VoiceAgent` setup |

---

## 10. References

- OpenAI streaming + tool calling: https://platform.openai.com/docs/guides/function-calling
- LangGraph (referenced for state checkpointing patterns even though we use a thinner direct loop): https://github.com/langchain-ai/langgraph
- Repo CLAUDE.md §RAG Stack — version markers (V5/V6/V7/V9/V10)

Continue → [`03-tts-and-audio.md`](03-tts-and-audio.md) for what happens after the sentence buffer flushes.
