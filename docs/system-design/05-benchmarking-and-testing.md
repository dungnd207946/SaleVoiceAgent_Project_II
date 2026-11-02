# 05 — Benchmarking & Testing

> Four distinct bench harnesses, plus the pytest pyramid. Each measures a different dimension: LLM provider quality (`bench_llm`), end-to-end agent quality (`bench_estate`), retrieval quality + speed (`bench_rag`), TTS first-byte (`bench_tts`). Use the right harness for the question you're asking.

Read [`02-llm-and-agents.md`](02-llm-and-agents.md) and [`04-rag-and-knowledge.md`](04-rag-and-knowledge.md) first.

---

## 1. The pyramid

```
                    ┌─────────────────────────────┐
                    │  tests/bench_estate/  (slow) │  124-case end-to-end against
                    │  real OpenAI + RAG + tools   │  production v9 pipeline.
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┴────────────────────────┐
              ▼                                             ▼
    ┌─────────────────────┐                    ┌────────────────────────────┐
    │  tests/bench_llm.py  │                    │  tests/bench_rag/          │
    │  Provider compare    │                    │  faq_inject + flat_store   │
    │  TTFT / tok-s        │                    │  hits / misses / latency   │
    └──────────────────────┘                    └────────────────────────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    ▼                              ▼
            ┌──────────────────┐          ┌─────────────────────────────┐
            │ tests/bench_tts/ │          │ tests/bench_deferred_       │
            │ first-byte       │          │ narration.py                │
            │ characters/s     │          │ tool-ack timing             │
            └──────────────────┘          └─────────────────────────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    ▼                              ▼
            ┌──────────────────┐          ┌──────────────────┐
            │  tests/unit/     │          │  tests/integration/ │
            │  pure functions  │          │  Redis/Mongo/HTTP   │
            │  + mocked deps   │          │  requires_docker    │
            └──────────────────┘          └──────────────────┘
```

Run order in CI:

1. `tests/unit/` (~5 s) — every PR
2. `tests/bench_estate/tests/` (~9 s, mocked) — every PR (regression)
3. `tests/integration/` (with Docker) — every PR if Docker available
4. `tests/bench_llm.py --case all --runs 1 --no-tools` — nightly
5. `tests/bench_estate/ run --section all` — weekly + post-release (real $$$)
6. `tests/bench_rag/` — when retrieval changes

---

## 2. `tests/bench_estate/` — agent quality regression

**Question answered:** "Does the production v9 pipeline pass the Vietnam real-estate broker certification test bank?"

**What it does:** Runs 124 cases (50 Section A + 40 Section B + 20 Section D MCQ + 5 Section C essay + 9 sales scenarios) through the **real** `StreamingLLM`, **real** RAG, **real** tool loop. A judge LLM (`gpt-5.4-nano-2026-03-17` by default) grades outputs under three rubrics:

| Rubric | Cases | Scale |
|---|---|---|
| P1 MCQ | 110 | 0/1/2 → scaled to case.points |
| P2 essay | 5 | 5 axes × 4 = 20 |
| P3 sales | 9 | 5 axes × 4 = 20 |

Threshold: `pass ≥ 14`, `needs_human_review 10–13`, `fail < 10`.

**Outputs per run:** `runs/<run_id>/report.json` (full schema), `report.md` (shareable view), `transcript_<case>.txt` (turn-by-turn dump).

**Quick start:**

```bash
conda activate test-voice-alt
make eval-estate-list           # 124 cases listed
make eval-estate-smoke          # 5 Section-A cases, no judge, < 2 min
make eval-estate                # full run + judge ~30 min, ~$0.05
make eval-estate-test           # pytest tests/bench_estate/tests/ (60 mocked)
```

**Compare two runs:**

```bash
python -m tests.bench_estate compare runs/<A>/report.json runs/<B>/report.json
```

Outputs FIXED / REGRESSED / UNCHANGED_PASS / UNCHANGED_FAIL / NEW / REMOVED bucket counts + per-case rows + section + latency deltas.

**Re-grade with a different judge** (reuses cached agent_outputs — costs only judge tokens):

```bash
python -m tests.bench_estate regrade runs/<RUN_ID>/report.json --judge-model gpt-4o
```

**Cost cap:**

```bash
python -m tests.bench_estate run --section all --judge-budget-usd 0.50
```

When cumulative judge spend ≥ cap, raises `BudgetExceeded` and aborts the judge phase (run-phase results are still saved). The retry loop does NOT swallow this — see commit `c457210`.

**Detail:** [`tests/bench_estate/README.md`](../../tests/bench_estate/README.md), [`tests/bench_estate/ACCEPTANCE.md`](../../tests/bench_estate/ACCEPTANCE.md).

---

## 3. `tests/bench_llm.py` — provider compare

**Question answered:** "Which LLM provider hits our TTFT + cost target on Noble's prompts?"

**What it does:** 8 fixed cases (smalltalk, RAG-needed, tool-call, multi-turn, Vietnamese long-form, etc.). For each provider × case, measures: TTFT (ms), total latency (ms), output tok/s, input/output token counts, tool accuracy.

**Targets:** any OpenAI-compatible endpoint. Cloud providers from `.env` (`groq`, `openai`, `gemini` via OpenAI-shim), or local servers via `--url/--model`.

**Quick start:**

```bash
conda activate test-voice-alt

# Interactive picker (pulls providers from .env)
python tests/bench_llm.py

# Specific provider + multiple cases + averaging
python tests/bench_llm.py --provider groq --case 1,3,5 --runs 3

# Local Ollama
python tests/bench_llm.py --url http://localhost:11434/v1 --model llama3.2 --no-tools

# Local vLLM (RunPod pod)
python tests/bench_llm.py --url http://localhost:8000/v1 --model Qwen3.6-35B-A3B

# Compare cloud vs local
python tests/bench_llm.py --provider groq --url http://localhost:11434/v1 --model llama3.2

# JSON output for piping
python tests/bench_llm.py --provider openai --case all --json > openai-baseline.json
```

**Workflow:** baseline → swap provider in `.env` → re-run → eyeball deltas. For programmatic compare use `scripts/bench/print_compare.py`:

```bash
python scripts/bench/print_compare.py runs/openai-baseline.json runs/qwen-trial.json
```

`bench_llm` is the **fast iteration loop** for prompt/model changes. It does not validate domain quality (that's `bench_estate`'s job) — it validates the LLM mechanics (TTFT, tool reliability, token economy).

---

## 4. `tests/bench_rag/` — retrieval evaluation

**Question answered:** "Did this prompt change hurt retrieval recall? Did the FAQ inject break paraphrase queries?"

**Modules:**

| File | Measures |
|---|---|
| `flat_store_runner.py` | Recall@K, MRR over scripted queries (`scenarios/*.json`) |
| `faq_inject.py` | V5 static FAQ inject correctness — does the right MD actually land in the prompt? |
| `faq_search.py` | V10 semantic FAQ — recall over paraphrase fixtures |
| `tool_timing.py` | RAG tool latency budget — flags tools >150 ms after warmup |
| `warmup.py` | First-call cold latency vs steady-state |
| `version_patches.py` | Compares prompt versions (V5 vs V9 vs V10) on same query set |

**Quick start:**

```bash
conda activate test-voice-alt

# Smoke: top-K recall over 20 fixtures
python -m tests.bench_rag.flat_store_runner --max 20

# Compare V9 vs V10 on FAQ paraphrases
python -m tests.bench_rag.version_patches --base V9 --target V10

# Tool timing budget check
python -m tests.bench_rag.tool_timing --threshold-ms 150
```

Outputs JSON in `tests/bench_rag/runs/`. Compare via `scripts/bench/print_compare.py`.

---

## 5. `tests/bench_tts/`

**Question:** "First-byte latency on a fresh Vietnamese sentence?"

Measures `time-to-first-audio-byte` and `chars/s` over a fixed sentence set, per backend (vieneu / elevenlabs / both). Use to compare a new TTS clone or model swap before shipping.

```bash
python -m tests.bench_tts --backend vieneu --runs 5
python -m tests.bench_tts --backend elevenlabs --runs 5 --voice-id <ID>
```

---

## 6. `scripts/benchmark.py` + `scripts/benchmark_latency.py` + `scripts/perf_report.py`

Production telemetry roll-ups. Read from MongoDB `session_metrics` rather than running anything.

```bash
make bench               # scripts/benchmark_latency.py — all models, 3 runs each
make bench-component     # scripts/benchmark.py — per-stage breakdown, 5 runs
make perf-report         # scripts/perf_report.py --hours 24 — last 24 h percentiles
```

`perf_report` produces a markdown table — paste into incident reports / weekly Slack.

---

## 7. The pytest pyramid

### 7.1 `tests/unit/`

Pure functions + mocks. No Docker, no network. Should pass in ~5 seconds.

```bash
make test-unit
pytest tests/unit/voice/stt/test_soniox_handlers.py -v
pytest tests/unit/agent/tools/test_booking.py::test_double_booking_rejected -v
```

### 7.2 `tests/integration/`

Hits real Redis + MongoDB + sometimes Asterisk. Marked with `@pytest.mark.requires_docker` where applicable. Slow (~30 s).

```bash
docker compose up -d redis mongodb       # bring up minimum stack
make test-integration
```

If Docker isn't running, integration tests skip cleanly with `requires_docker`.

### 7.3 `tests/bench_estate/tests/`

61 mocked tests covering loader, delivery, runner, judge (with cache + budget), reporter, differ. **Fast** (~9 s) because `StreamingLLM` is mocked. Use this for PR gates — full real-LLM `eval-estate` is weekly.

```bash
pytest tests/bench_estate/tests/ -q   # 61 passed
```

### 7.4 `tests/eval_scenarios.py` + `tests/interactive/`

Scripted conversation playback (golden transcripts). Use when refactoring agent flow — confirms a fixed input still yields the right tool-call sequence.

---

## 8. Ruff + lint

`ruff check` is the only lint. Lines wrap at 120, target Python 3.11, ruleset `E,F,W,I,UP,B,SIM`.

```bash
make lint     # ruff check src/ tests/
make format   # ruff format src/ tests/
```

CI runs both as a separate step before tests so lint failures don't get masked by test failures.

---

## 9. Workflow recipes

### 9.1 "I changed a prompt — did anything break?"

```bash
# Baseline (before change)
git checkout main
make eval-estate-smoke   # 5-case, no judge — sanity
make eval-estate         # full + judge → runs/A/report.json
git checkout my-branch

# Apply change, re-run
make eval-estate         # → runs/B/report.json

# Diff
python -m tests.bench_estate compare runs/A/report.json runs/B/report.json
```

If REGRESSED bucket is non-empty, investigate. Each regressed row links to a `transcript_<case>.txt` you can read.

### 9.2 "Is this model swap viable?"

```bash
python tests/bench_llm.py --provider openai --case all --runs 3 --json > runs/openai.json
python tests/bench_llm.py --url http://localhost:8000/v1 --model new-model --case all --runs 3 --json > runs/new.json
python scripts/bench/print_compare.py runs/openai.json runs/new.json
```

Then if TTFT + tok-s look good, run `make eval-estate` against the new model to confirm domain quality.

### 9.3 "Production has slow tail latency"

```bash
make perf-report                                                 # 24h percentiles
python -m tests.bench_rag.tool_timing --threshold-ms 150          # check tools
python -m tests.bench_rag.warmup                                  # cold vs warm gap
```

`session_metrics` MongoDB collection has per-turn breakdowns: `sniff_ms`, `llm_ttft_ms`, `llm_total_ms`, `tools_total_ms`, `rebuild_ms`. Filter on `turn_total_ms > p95` to find outliers.

### 9.4 "I want to test a new tool's latency"

```bash
# Add tool + handler
# Then:
pytest tests/unit/agent/tools/test_<my_tool>.py -v
python -m tests.bench_rag.tool_timing --threshold-ms 200 --tool <my_tool>
```

---

## 10. Common debugging

| Symptom | Likely cause |
|---|---|
| `bench_estate` always "judge_error" | `OPENAI_API_KEY` invalid for the judge model. Try `gpt-4o` via `--judge-model` |
| `bench_llm` provider missing | Provider not in `.env`. Use `--url/--model` instead |
| `bench_rag` recall plummets after data update | Forgot to rebuild FlatStore artifacts ([`04-rag-and-knowledge.md`](04-rag-and-knowledge.md) §6) |
| Mocked `bench_estate/tests/` slow | Probably hitting real network; check `conftest.py:mock_streaming_llm` is patched |
| `perf-report` shows TTFT spike | LLM provider latency, not agent. Check OpenAI status page or fall back to Gemini |

---

## 11. References

- `tests/bench_estate/README.md` — eval harness usage
- `tests/bench_estate/ACCEPTANCE.md` — 12 spec criteria + manual verification commands
- `tests/bench_llm.py` docstring — full CLI reference
- `scripts/perf_report.py` — production telemetry rollup

Continue → [`06-infrastructure-and-runpod.md`](06-infrastructure-and-runpod.md) for how to actually deploy this.
