# SP-D — Heartbeat — Implementation Plan (TDD)

Spec: `docs/superpowers/specs/2026-07-30-sp-d-heartbeat-design.md`. Branch `feat/agent`.

Contract C3 (`docs/api/odyssey-agent-interface-contract.md`). Agent WRITE side only.

## Tasks (each: RED → GREEN → refactor)

1. **Store heartbeat primitives.** `read_heartbeat`/`write_heartbeat` on Protocol +
   `FakeTenantStore` + `MinioTenantStore` (`<t>/_heartbeat.json`); add `_HEARTBEAT`
   to `read_bundle` skip-set. Tests: `tests/unit/tenant/test_store.py`
   (`test_fake_store_heartbeat_roundtrip`, `test_minio_store_heartbeat_roundtrip`,
   `test_minio_read_bundle_excludes_heartbeat`).

2. **Config.** `NOBLE_HEARTBEAT_ENABLED` (True), `NOBLE_HEARTBEAT_SEC` (20).

3. **Facade warm helper.** `ensure_version_built(version)` → `_get_runner_for_version`
   (shared lock/cache). Test: `test_facade_version_pinning.py::
   test_ensure_version_built_goes_through_shared_cache`.

4. **Emitter.** `tenant/heartbeat.py`: `build_heartbeat` (pure) + `HeartbeatEmitter`
   (`_resolve_published`, `beat`, `run`). Tests: `tests/unit/tenant/test_heartbeat.py`
   (10) — shape, versioned-serving+write, running-advances-on-publish, checksum→degraded
   (keep running), build-error→degraded, legacy-inplace-no-build, absent→degraded,
   store-down→skip, started_at-stable/ts-advances, run-loop-beats-then-stops.

5. **Boot wiring (both transports).** Shared `heartbeat.should_emit` + `build_materialize_fn`.
   aiortc `server/http.py::_run_server_async`: task on the main loop (default full-runner
   build_fn); cancel in `finally` (`contextlib.suppress`). LiveKit
   `transport/livekit/worker.py::_start_heartbeat` (before `cli.run_app`): daemon thread +
   own loop, materialize-only build_fn. Gate tests `test_worker_heartbeat.py` (2).

6. **Docs.** CLAUDE.md changelog + config table; contract C3 status ◑ + N7 chốt;
   `SMOKE.md` recipe; memory.

## Verification (DONE)

- New tests: 13 heartbeat + 3 store + 1 facade + 2 worker-gate = **19, all green**.
- Full unit gate: **1672 passed / 9 failed / 1 skipped** — all 9 match the documented
  baseline (2 USD-normalize, project_financial_mongo, prompt 'Tên:', 2 qdrant_adapter,
  qdrant_store, send_media local-.env, snapshot_short_term). **0 new failures.**
- Ruff clean on all new/touched files (pre-existing E501×3 + SIM108 in
  `http.py`/`config.py` left untouched per surgical rule).
- **Live MinIO (10.50.13.220):** (a) `beat()` for `noble` + `demo_acme` (both legacy
  in-place) → `serving 1/1`, no build, roundtrip MATCH, **`read_bundle('noble')` = 7
  persona files, NO `_heartbeat.json` leak** (the critical skip-set fix, verified live);
  (b) self-cleaning **versioned probe** → materialize-only build_fn (real boto3
  download+checksum) wrote the version to disk + `serving 1/1` + readback MATCH; all 9
  probe objects deleted (store back to original). Both legacy AND versioned branches +
  both aiortc (full-runner) and LiveKit (materialize-only) build_fns are live-covered.

## Follow-ups

- **SP-E:** move transport to Postgres `platform` (same shape); **blocked on N9**.
