.PHONY: test test-unit test-integration test-unified lint format bench-component eval-estate eval-estate-smoke eval-estate-list eval-estate-test e2e eval-list eval-quality eval-quality-smoke eval-quality-full eval-score eval-rag eval-bench eval-load eval-report eval-periodic eval-selftest eval-labeller

test:
	python -m pytest tests/ -v --tb=short

test-unit:
	python -m pytest tests/unit -v --tb=short

test-integration:
	python -m pytest tests/integration -v --tb=short

test-unified:
	pytest tests/unit/unified tests/integration/unified -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

bench-component:
	python scripts/benchmark.py --runs 5

# Live check of kb_search + send_media against the real embed service + Qdrant.
# Needs QDRANT_URL reachable (docs/handoff/qdrant-access.md). ARGS passes flags
# through, e.g. `make test-search ARGS="--list"` or `ARGS="-t <tenant>"`.
test-search:
	python scripts/test_search_tools.py $(ARGS)

e2e:
	python -m tests.e2e_scenarios $(ARGS)

eval-estate:
	python -m tests.bench_estate run --section all --judge-model gpt-5.4-nano-2026-03-17

eval-estate-smoke:
	python -m tests.bench_estate run --section A --max-cases 5 --no-judge

eval-estate-list:
	python -m tests.bench_estate list --section all

eval-estate-test:
	python -m pytest tests/bench_estate/tests/ -q

# ---- Evals harness (evals/) ------------------------------------------------
# Spec: docs/superpowers/specs/2026-08-24-unified-evals-harness-design.md
# quality/rag cần Redis + LLM key + RAG backend; bench/load cần service sống;
# report/selftest không cần gì.
eval-list:
	python -m evals list $(ARGS)

eval-quality:
	python -m evals run $(ARGS)

eval-quality-smoke:
	python -m evals run --case POL-001,TOOL-001,QA-001 --tenant du_test $(ARGS)

eval-quality-full:
	python -m evals run --judge $(ARGS)

eval-score:
	python -m evals score --run-dir evals/reports/$(RUN) $(ARGS)

eval-rag:
	python -m evals rag $(ARGS)

eval-bench:
	python -m evals bench $(ARGS)

eval-load:
	python -m evals load --target chat $(ARGS)

eval-report:
	python -m evals report

# Dành cho cron/CI định kỳ: smoke + bench + report; suite lỗi vẫn chạy suite sau,
# nhưng exit code cuối là OR của các suite (spec §10) — cron/CI vẫn thấy đỏ.
eval-periodic:
	@rc=0; \
	python -m evals run --case POL-001,TOOL-001,QA-001 --tenant du_test || rc=1; \
	python -m evals bench --runs 5 || rc=1; \
	python -m evals report || rc=1; \
	exit $$rc

eval-selftest:
	python -m pytest tests/unit/evals/ -q

eval-labeller:
	python -m evals labeller $(ARGS)
