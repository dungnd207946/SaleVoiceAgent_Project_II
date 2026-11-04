# bench_estate — Hotline Estate-Cert Eval Harness

Regression-eval harness running the **Vietnam real-estate broker certification test bank** (124 cases: 110 MCQ + 5 essay + 9 sales scenarios) through the production v9 hotline pipeline. Grades outputs with a judge LLM (default `gpt-5.4-nano-2026-03-17`) under three rubrics: P1 MCQ, P2 essay, P3 sales.

## Quick start

Activate the project env (the repo's `.venv/` is **not** the working env):

    conda activate test-voice-alt

Set keys (`.env` already loaded by `noble_agent.config`):

    export OPENAI_API_KEY=sk-...

Start Redis (required by the pipeline session store):

    docker compose up -d redis

One-time MCQ → roleplay conversion (only needed if `data/personas_mcq/*.json` is empty):

    python -m tests.bench_estate.scripts.convert_mcq_to_roleplay

List all 124 cases:

    make eval-estate-list

Smoke run (5 Section-A cases, no judge, finishes < 2 min):

    make eval-estate-smoke

Full run (all 124 cases + judge):

    make eval-estate

Compare two runs:

    python -m tests.bench_estate compare runs/<RUN_A>/report.json runs/<RUN_B>/report.json

Re-grade an existing run with a different judge:

    python -m tests.bench_estate regrade runs/<RUN_ID>/report.json --judge-model gpt-4o

## CLI reference

    python -m tests.bench_estate list --section A|B|C|D|S|all
    python -m tests.bench_estate run --section all --judge-model gpt-5.4-nano-2026-03-17
    python -m tests.bench_estate run --case A-1,A-2 --no-judge
    python -m tests.bench_estate run --section A --max-cases 5 --judge-budget-usd 0.50
    python -m tests.bench_estate compare runs/A/report.json runs/B/report.json
    python -m tests.bench_estate regrade runs/A/report.json --judge-model gpt-4o

## Outputs

Every run writes `runs/<RUN_ID>/`:
- `report.json` — full schema (config, totals, sections, latency_ms, tool_stats, judge_stats, cases, failures)
- `report.md` — shareable Markdown view
- `transcript_<CASE_ID>.txt` — per-case turn-by-turn dump

## Interpreting results

| Percent of total points | Verdict |
|-------------------------|---------|
| ≥ 70%                   | ĐẠT |
| 50% – 70%               | CẦN CẢI THIỆN |
| < 50%                   | KHÔNG ĐẠT |

Per-case verdicts: `pass` (≥14/20 essay+sales, or full credit MCQ), `fail` (<10/20 or wrong MCQ), `uncertain` (10–13/20 borderline → review), `refused`, `error`, `judge_error`.

## Tests

    pytest tests/bench_estate/tests/ -q

Lint:

    ruff check tests/bench_estate/

## Architecture (one paragraph)

`loader.py` reads JSON (`data/personas_*.json`) + MD (`docs/estate_cert/DE_THI_NHAN_VIEN.md`) into typed `MCQCase` / `EssayCase` / `ScenarioCase`. `delivery.py` produces user inputs in three modes (literal MCQ, roleplay, scripted multi-turn). `runner.py` runs each case through `noble_agent.agent.llm.streaming.StreamingLLM` with real callbacks for TTFT + tool-call instrumentation, then dispatches to `judge.py` for rubric grading. `reporter.py` aggregates into terminal summary + JSON + Markdown. `differ.py` compares two `report.json` files, classifying cases as fixed / regressed / unchanged / new / removed.
