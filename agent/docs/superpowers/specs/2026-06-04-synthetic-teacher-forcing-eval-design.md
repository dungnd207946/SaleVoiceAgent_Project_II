# Teacher-Forcing Eval for the Synthetic SFT Data — Design

**Date:** 2026-06-04
**Status:** Approved (design phase)
**Scope:** New top-level package `src/eval/` in `santa-hotline-agent` that replicates the
two-phase teacher-forcing evaluation from `santa-post-training`, adapted to the unified
Noble agent (Luna) and the synthetic reference file `data/synthetic_sft/eval_sft.jsonl`.

---

## 1. Goal & parity

Port the idea of the `santa-post-training` multiturn eval pipeline
(`src/post_training/eval/multiturn_runner.py`) to this repo:

- **Same two phases:** `run` (generate predictions via teacher forcing) → `score`
  (compute metrics + aggregate report).
- **Same output files / shapes:** `predictions.jsonl`, `details.jsonl`,
  `eval_manifest.json`, `report.json`.
- **Same metric families:** rule-based tool-call metrics, rule-based response axes,
  and an optional LLM-as-judge.

What differs from the original:

- **Prediction model = the Noble agent's own LLM**, i.e. the provider chain configured
  in `santa-hotline-agent/.env` (`NOBLE_AGENT_MODEL=claude-sonnet-4-6` primary, fallback
  openai → gemini). This is the same model path the agent uses when generating synthetic
  data, so the eval measures the production model.
- **Reference file:** `data/synthetic_sft/eval_sft.jsonl` (26 conversations as of writing),
  each record `{conversation_id, prompt_variant, messages, tools, persona, ended_naturally, turns}`.
- **Single agent:** only Luna exists, so there is a single rubric (no per-agent registry).

---

## 2. Why teacher forcing (the core idea)

For every **assistant** message in a reference conversation, take the exact prefix of
messages that precede it and ask the model to produce *its* next assistant message —
**one completion, no tool-execution loop**. The model's output (`content` + `tool_calls`)
is then compared against the reference assistant message.

This isolates per-turn quality: given identical context (including reference tool results
already in the prefix), did the model call the right tool with the right arguments, and
did it say the right thing? It deliberately does **not** run the agent's 5-iteration tool
loop, Redis state, or storage — the prefix is replayed verbatim from the record, exactly
as `santa-post-training` does.

The reference system prompt is whatever sits at `messages[0]` of the record
(`prompt_variant: "general"`). The eval **never rebuilds** the system prompt; it replays
the prefix as-is for fidelity to the reference.

---

## 3. Module layout — new top-level `src/eval/`

```
src/eval/
  __init__.py
  __main__.py          # CLI: `python -m eval run|score ...`
  config.py            # EvalSettings (pydantic-settings): paths, critic cfg, workers, temp, thresholds
  data.py              # load_eval_file() + enumerate_turns() -> TurnSample
  predict.py           # teacher forcing: build StreamingClient, one stream_completion per turn
  tool_metrics.py      # rule-based FC pairing + classification (dependency-free)
  response_rules.py    # 6-axis Luna rule scoring
  response_llm.py      # LLM-as-judge (critic client + rubric), criteria + weights inline
  report.py            # aggregation -> report.json
  prompts/
    critic_multiturn_luna.txt
  README.md
```

Results are written to `data/eval_results/<slug>/`:
`predictions.jsonl`, `details.jsonl`, `eval_manifest.json`, `report.json` — mirroring the
post-training layout (which nests under `…/eval_results/<agent>/<slug>/`; here there is one
agent so we drop the agent level).

`src` is already a source root (the repo runs `python -m synthetic` and installs
`noble_agent` from `src/`), so `python -m eval` resolves without packaging changes.
Note: a top-level package literally named `eval` shadows nothing at runtime (the builtin
`eval()` is a function, not a module); chosen per explicit user request.

---

## 4. `run` phase — teacher forcing

### 4.1 Turn enumeration (`data.py`)

`enumerate_turns(record)` walks `record["messages"]`. For each message with
`role == "assistant"` at index `i`, emit:

```python
TurnSample(
    conversation_id,           # from record
    turn_idx,                  # number of role=="user" messages seen so far
    step_idx_in_turn,          # assistant-step counter within the current user turn
    is_first_assistant,        # first assistant message in the conversation
    is_final_assistant,        # last assistant message in the conversation
    user_message,              # text of the most recent preceding user message
    prefix=messages[:i],       # everything before this assistant message
    reference_response=messages[i],   # {role, content, tool_calls?}
    tools=record["tools"],
)
```

`step_idx_in_turn` resets to 0 on each new user message and increments per assistant
message, so multi-step turns (an assistant tool-call step followed by an assistant
answer step after the tool result) are distinguished. Dedup key for resume:
`(conversation_id, turn_idx, step_idx_in_turn)`.

### 4.2 Prediction (`predict.py`)

- Build the provider chain once via `noble_agent.agent.facade.build_llm_providers`
  and wrap in `StreamingClient`. Resolve the primary provider from `NOBLE_AGENT_MODEL`
  via `noble_agent.config.primary_for`, and pass `model=provider_model_map(settings)`
  so each provider is asked with its own `<P>_MODEL` (identical to the live agent).
- `predict_turn(sample)`:
  ```python
  content, tool_calls = await client.stream_completion(
      messages=sample.prefix,
      tools=sample.tools,
      model=provider_model_map(settings),
      temperature=cfg.temperature,
      max_tokens=cfg.max_tokens,
      on_token=_noop,                 # async no-op; we only want the final aggregate
      primary=primary_provider,
  )
  predicted_response = {"role": "assistant", "content": content or "", "tool_calls": tool_calls or []}
  ```
- This is a pure LLM call — **no Redis, no Mongo, no tool dispatch, no agent state.**

### 4.3 Orchestration

- `asyncio` with `asyncio.Semaphore(workers)` (mirrors `src/synthetic/__main__.py`).
- Append-flush to `predictions.jsonl` under an `asyncio.Lock`; resume-friendly (skip
  samples whose dedup key already exists in the file).
- Default `temperature = 0.2`, `max_tokens = 1024`, `workers = 8` — all overridable.
- Write `eval_manifest.json` (append an entry): `started_at` (ISO; injected, not
  `Date.now()`), `slug`, `eval_file`, `agent_model`, `primary_provider`, `n_conv`,
  `resume_skipped`, `temperature`, `workers`.

---

## 5. `score` phase

Reads `predictions.jsonl`; writes `details.jsonl` (one row per turn, all metrics) and
`report.json` (aggregated). `--response-eval {rule,llm,both}`, default **both**.

### 5.1 Tool-call metrics — always, rule-based (`tool_metrics.py`)

Per turn, extract predicted and expected tool calls (`function.name` + parsed
`function.arguments` JSON). Greedy-pair by tool name in predicted order; leftover
predicted → `(pred, None)`, leftover expected → `(None, exp)`. Classify each pair:

| Label | Condition |
|---|---|
| `unwanted_function_call` | predicted present, no expected match |
| `missing_function_call` | expected present, no predicted match |
| `incorrect_function_format` | name matches but args fail the schema check (bad type, undeclared key, bad enum) |
| `missing_argument` | a required key (from schema `required`, else expected's keys) present in expected but absent in predicted |
| `wrong_argument_value` | a shared key whose value similarity < `tfidf_threshold` |

**Dependency-free implementations** (per repo "Simplicity first / no new deps"):

- **Schema check** — small hand-rolled validator over the record's `tools` schema:
  required-keys present, no undeclared keys (against `properties`), `enum` membership,
  and basic JSON type match. (Replaces `jsonschema`.)
- **Value similarity** — `difflib.SequenceMatcher(None, str(a), str(b)).ratio()` in
  `[0,1]`, compared to a configurable threshold (default `0.7`). (Replaces sklearn
  TF-IDF cosine; functionally equivalent for short arg strings.) The CLI flag keeps the
  name `--tfidf-threshold` for parity with post-training, documented as a generic
  similarity threshold.

`wrong_tool_name_rate` heuristic = turns containing **both** an unwanted and a missing
call (a name mismatch shows up as one of each).

Aggregate rates mirror the original `report.json.summary.fc_metrics` keys:
`n_turns_with_tool_calls`, `n_total_pairs`, `unwanted_function_call_rate`,
`missing_function_call_rate`, `incorrect_function_format_rate`,
`wrong_argument_value_rate`, `missing_argument_rate`, `wrong_tool_name_rate`.

### 5.2 Response rules — Luna-adapted, 6 axes (`response_rules.py`)

Each axis scores `1` / `0` / `None` (None = not applicable to this turn). Adapted from
the agent's `RULES.md`:

| Axis | Rule |
|---|---|
| `opening_compliance` | first assistant turn starts with `Dạ`/`Vâng` **and** mentions `Luna`/`tư vấn`/`Noble` |
| `closing_compliance` | final assistant turn contains `cảm ơn` **and** `Noble` |
| `forbidden_words` | no `nhé` / `nhá` / `nhỉ` (informal particles banned for TTS) |
| `conciseness_clarity` | 2–3 sentences (RULES.md "2–3 câu max"); split on `.!?…` |
| `politeness_markers` | ≥1 of `dạ`, `vâng`, `vui lòng`, `cảm ơn`, ` ạ` |
| `name_usage` | if a customer name is recoverable from the prefix, predicted must mention it |

Axes that need text are skipped (`None`) when the turn is a pure tool-call step
(empty `content`). Aggregate = per-axis `pass_rate` + `n_evaluated`, plus a mean
`aggregate`.

### 5.3 LLM judge — optional rubric (`response_llm.py`)

Per-turn critic call comparing predicted vs reference. Criteria (id, description, weight)
are defined inline; `tool_correctness` is **excluded** (covered by §5.1). A blocking
`factual_pass` boolean flags fabrication / contradiction of tool results in the prefix.

- Criteria: `clarity`, `informativeness`, `relevance`, `coherence`, `empathy`,
  `engagement` (each 1–5, weighted).
- Prompt template: `prompts/critic_multiturn_luna.txt` (Vietnamese, modeled on
  `critic_multiturn_eval_consultant.txt`), `.format(...)`-filled with
  `criteria_list`, `factual_axis`, `history_block`, `user_message`,
  `reference_response`, `predicted_response`.
- Call: critic client `chat.completions.create(response_format={"type":"json_object"},
  temperature=0.2, max_tokens≈800)`; parse `{scores, rationale, factual_pass, factual_notes}`;
  `aggregate = weighted_mean(scores)`.

### 5.4 Critic (judge) client

A dedicated OpenAI-compatible async client, separate from the candidate to avoid
self-grading bias. Configured via `EVAL_CRITIC_*` env with this resolution order:

1. `EVAL_CRITIC_MODEL` / `EVAL_CRITIC_BASE_URL` / `EVAL_CRITIC_API_KEY` if set.
2. **Default:** the Anthropic provider already in `.env` (`claude-sonnet-4-6` via the
   Meridian proxy at `ANTHROPIC_BASE_URL`) — strong and no per-token cost. Accessed
   through the Anthropic-compatible path (reuse the agent's anthropic provider object
   from `build_llm_providers`, or the `anthropic` SDK directly).

`--critic-model` overrides at the CLI.

### 5.5 Aggregation (`report.py`)

`report.json`:
```json
{
  "slug": "...", "eval_file": "...", "response_eval_mode": "both",
  "n_conversations": 26, "max_turns": <int>, "tfidf_threshold": 0.7,
  "summary": { "n_total_turns": ..., "fc_metrics": {...}, "response_rule": {...}, "response_llm": {...} },
  "per_turn": { "0": {...}, "1": {...} }
}
```
`per_turn` groups by `turn_idx`; `summary` is the global aggregate.

---

## 6. CLI

```bash
python -m eval run \
  --slug myrun \
  [--eval-file data/synthetic_sft/eval_sft.jsonl] \
  [--temperature 0.2] [--max-tokens 1024] [--workers 8] [--limit N]

python -m eval score \
  --slug <YYYYMMDD_HHMMSS>_myrun \
  [--response-eval both] [--critic-model <name>] \
  [--tfidf-threshold 0.7] [--workers 8] [--limit N]
```

`run` prefixes the slug with a UTC timestamp (`YYYYMMDD_HHMMSS_<slug>`) to match the
post-training naming (`20260526_084416_multi_csr_v1`). `score` takes the full stamped slug.

---

## 7. Configuration (`config.py`, `EvalSettings`)

Pydantic-settings reading `.env` (so it picks up the agent's provider config). Fields:
`eval_file` (default `data/synthetic_sft/eval_sft.jsonl`),
`results_dir` (default `data/eval_results`),
`temperature` (0.2), `max_tokens` (1024), `workers` (8),
`tfidf_threshold` (0.7),
`critic_model` / `critic_base_url` / `critic_api_key` (`EVAL_CRITIC_*`, default Anthropic).

---

## 8. Dependencies

**No new dependencies.** Uses stdlib (`asyncio`, `json`, `difflib`, `argparse`,
`datetime`, `pathlib`), existing `pydantic-settings`, the existing `openai`/`anthropic`
SDKs (for the critic), and the in-repo `noble_agent` LLM stack (for prediction).

---

## 9. Out of scope (YAGNI)

- No Redis / Mongo / agent tool execution / voice path.
- No per-agent rubric registry (single agent).
- No fine-tune checkpoint serving (prediction always uses the `.env` provider chain).
- No calibration harness (post-training's `judge_calibration*`); can be added later if
  judge reliability needs validation.

---

## 10. Testing

- `data.enumerate_turns`: unit test on a hand-built record (multi-step turns, first/final
  flags, dedup keys).
- `tool_metrics`: unit tests per error label (unwanted/missing/format/wrong-value/missing-arg)
  and the schema/similarity helpers, with no LLM.
- `response_rules`: unit tests per axis (opening/closing/forbidden/conciseness/politeness/name).
- `predict` / `response_llm`: thin smoke tests with a stubbed client (no network in CI).
- Follow repo conventions: `tests/unit/eval/`, `pytest asyncio_mode=auto`, ruff clean.
