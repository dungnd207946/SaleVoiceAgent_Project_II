# bench_estate — Acceptance Criteria Walkthrough (M5.4)

Source: `docs/superpowers/specs/2026-05-04-bench-estate-eval-harness-design.md` §6.4.

Two classes of checks:

- **Code-verifiable** — confirmed by reading the implementation + tests. Does not require live OpenAI/Redis.
- **Live-run** — requires `OPENAI_API_KEY`, Redis, and actual LLM/RAG round-trips. Documented as a single-line user-runnable command. The user runs and confirms.

## Status

| # | Criterion | Type | Status | Evidence |
|---|---|---|---|---|
| 1 | `run --section all --provider openai` runs all 124 cases without crash | live-run | pending user | `make eval-estate` |
| 2 | `report.json` validates against §5.3 schema | code-verifiable | ✅ pass | `reporter.py:build_report` returns dict with all top-level keys (`schema_version`, `run_id`, `started_at`, `finished_at`, `total_seconds`, `config`, `totals`, `sections`, `topic_breakdown`, `latency_ms`, `tool_stats`, `judge_stats`, `cases`, `failures`); `_result_to_dict` produces per-case keys (`case_id`, `section`, `topic`, `delivery_mode`, `user_inputs`, `agent_outputs`, `tool_calls`, `ttft_ms`, `total_ms`, `stage_ms`, `agent_switches`, `judge.{model,rationale,verdict,rubric_breakdown}`, `score_raw`, `score_max`, `verdict`, `error`). Verified by `test_reporter.py` (12 tests). |
| 3 | Terminal has color, per-case lines, end summary blocks | code-verifiable | ✅ pass | `print_case_line` uses `status_icon` + ANSI palette; `print_summary` prints 6 blocks (Header, Sections, Weak topics, Latency, Tools, Judge). |
| 4 | `report.md` renders on GitHub | code-verifiable | ✅ pass | `render_markdown` produces standard GFM tables (`\| col \| col \|` + `\|---\|---\|` separator) for Sections + Latency + Failures; verified by `test_reporter.py::test_render_markdown_basic`. |
| 5 | `compare A.json B.json` produces FIXED/REGRESSED/UNCHANGED | code-verifiable | ✅ pass | `differ.py::compare` returns `Diff` with `fixed`, `regressed`, `unchanged_pass`, `unchanged_fail`, `new_cases`, `removed_cases` lists. `print_diff` renders the spec §5.5 layout. Verified by `test_differ.py` (3 tests including `test_compare_classifies_fixed_regressed_unchanged`). |
| 6 | Re-running same cases shows judge cache hits, cost ~$0 | live-run | pending user | Run twice: `python -m tests.bench_estate run --section A --max-cases 5` then repeat. Cache impl confirmed at `judge.py::_cache_get/_cache_put` keyed by SHA1(case_id\|agent_output\|model\|rubric); `judge_stats.cached_hits` exposed in report. |
| 7 | Cost in report ±10% of OpenAI dashboard | live-run | pending user | `judge.py::_PRICING` table: `gpt-5.4-nano-2026-03-17` $0.05/1M input, $0.40/1M output. Compare `runs/<id>/report.json:judge_stats.cost_usd` against OpenAI billing dashboard at https://platform.openai.com/usage |
| 8 | `pytest tests/bench_estate/tests/ -v -m "not slow"` 100% green | code-verifiable | ✅ pass | **60/60 passed** at tip `917df7c`: test_delivery (5) + test_differ (3) + test_judge (14) + test_loader (14) + test_reporter (12) + test_runner_grade (3) + test_runner_smoke (9). |
| 9 | `pytest -m slow` green when Redis + OPENAI_API_KEY available | live-run | pending user | No `slow`-marked tests currently; M5+ hasn't added any. Noop-pass acceptable for v1. |
| 10 | `--section A --max-cases 5 --no-judge` finishes < 2 min | live-run | pending user | `make eval-estate-smoke` |
| 11 | README quick-start works as written | live-run | pending user | Walk through `tests/bench_estate/README.md` Quick start section step-by-step. |
| 12 | `--case C-1 --verbose` dumps full transcript + tool calls per turn | code-verifiable | ✅ pass (after M5.4 fix) | `cli.py:_cmd_run` writes `runs/<id>/transcript_<case>.txt` with turn-by-turn `USER:` / `AGENT:` / `--- tool calls ---` blocks unconditionally. `--verbose` now additionally echoes the same body to stdout (fixed in this commit). |

## Manual verification commands (single-line each, run sequentially)

Activate env:

    conda activate test-voice-alt

Repeat baseline tests:

    pytest tests/bench_estate/tests/ -q

Lint:

    ruff check tests/bench_estate/

Smoke (criterion #10, < 2 min):

    make eval-estate-smoke

Verbose single case (criterion #12):

    python -m tests.bench_estate run --case A-1 --no-judge --verbose

Repeat-run cache hits (criterion #6 — run twice, second call should reuse cache):

    python -m tests.bench_estate run --section A --max-cases 3 --judge-budget-usd 0.10

    python -m tests.bench_estate run --section A --max-cases 3 --judge-budget-usd 0.10

Compare two runs (criterion #5):

    python -m tests.bench_estate compare runs/<RUN_A>/report.json runs/<RUN_B>/report.json

Re-grade with new judge (regrade):

    python -m tests.bench_estate regrade runs/<RUN_ID>/report.json --judge-model gpt-4o

Full eval (criterion #1, ~30 min, ~$0.05 USD judge cost):

    make eval-estate

## Outcome

Code-verifiable criteria (#2, #3, #4, #5, #8, #12): **6/6 ✅**

Live-run criteria (#1, #6, #7, #9, #10, #11): **pending user** — gated on real OpenAI/Redis access; not blocking handoff.

No criterion is `fail`. M5.4 considered complete on Claude's end. User performs the live-run sweep and reports any deltas.
