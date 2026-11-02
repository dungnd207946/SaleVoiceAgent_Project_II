# SP-D — Heartbeat (Odyssey contract C3) — Design

**Slice:** SP-D of the Odyssey SaaS pivot (HT_01 flow D). Implements the **agent
write side** of contract **C3** in `docs/api/odyssey-agent-interface-contract.md`.
Follows SP-C1 (write) + SP-C2 (read, version-pinned load). Branch `feat/agent`.

## Goal

The agent **proactively pushes** a heartbeat (BR02 — Backend never calls down to
the agent) so Backend/Dashboard can **infer** worker/config status (BR11). No one
polls the agent.

## Contract recap (C3)

- **Shape (C3.1):** `{tenant_id, running_version, published_version_seen,
  status_hint, last_error, started_at, ts}`; `status_hint ∈ {starting, loading,
  serving, degraded}`; `last_error = null | {code, message, ts}`.
- **Transport (C3.2, SP-D):** write `<tenant_id>/_heartbeat.json` on the tenant
  store (MinIO/S3). Overwrite each beat. (SP-E may move it to Postgres `platform`
  with the SAME shape — no contract change.)
- **Cadence/thresholds (C3.3, N7 — chốt here):** emit every ~20 s. Fresh
  `now - ts ≤ 60 s`; stale `> 60 s`. "Applying" `> 2 min` with `running < published`
  → error (E03). **The 60 s / 2 min thresholds are Backend/Dashboard INFERENCE
  (C3.4); the agent only emits every 20 s + the truthful shape.**

## Design

New module `tenant/heartbeat.py`:

- `build_heartbeat(...) -> dict` — pure C3.1 shape assembler.
- `HeartbeatEmitter(store, settings, tenant_id, *, build_fn=None, now_iso=…)`
  - Holds `started_at` (captured once at construct), `_running`, `_last_error`.
  - `beat()` — one emission:
    1. `_resolve_published()` reads the store pointer **directly** (the heartbeat
       IS the ~20 s config poller — not a cache consumer). Returns
       `(version, mode)` where `mode ∈ {versioned, legacy, absent}`. A store
       outage here **raises → beat skips the write** (a stale `ts` is exactly the
       honest "Mất kết nối"/E02 signal; there's nothing to write anyway).
    2. **versioned** → proactively `await build_fn(published)` (default:
       `facade.ensure_version_built` → the SAME locked/cached
       `_get_runner_for_version` path conversations use, so no double-build/race).
       Success → `running = published`, `status = serving`. `ChecksumError` (E04)
       → `degraded` + `last_error{checksum_mismatch}`, **keep last-good running**.
       `FileNotFoundError` → `degraded{version_missing}`. Other → `degraded{load_error}`.
       Proactive build is what lets `running_version` catch up to `published` on an
       **idle** worker — the precondition for the Dashboard's E03 inference.
    3. **legacy in-place** (no pointer, meta present) → `serving` at `version=1`,
       **no versioned build** (there is no `versions/<n>/` to materialize; the
       in-place bundle was already loaded at boot).
    4. **absent** (tenant not in store) → `degraded{tenant_absent}`.
    5. `write_heartbeat` (best-effort; a write failure logs + continues).
  - `run(stop_event)` — beat every `heartbeat_sec`, cancel-safe, never lets a beat
    exception kill the loop.

Store (`tenant/store.py`): `read_heartbeat`/`write_heartbeat` on the Protocol +
`FakeTenantStore` + `MinioTenantStore` (`<t>/_heartbeat.json`). **Critical:**
`_HEARTBEAT` added to `read_bundle`'s skip-set so the sibling heartbeat object
never leaks into a legacy in-place tenant's `bundle.files` (which would corrupt
`materialize_tenant` output + `bundle_hash`).

Facade (`agent/facade.py`): `ensure_version_built(version)` — thin `await
_get_runner_for_version(version)`; propagates `ChecksumError`/`FileNotFoundError`
so the heartbeat can classify degraded.

Config: `NOBLE_HEARTBEAT_ENABLED` (default `true`), `NOBLE_HEARTBEAT_SEC`
(default `20`). Gate = `tenant_store_enabled AND heartbeat_enabled` (no store →
nowhere to write → inert; the live Noble default `TENANT_STORE_ENABLED=false`
means zero behavior change there).

Shared helpers (`heartbeat.py`): `should_emit(settings)` (the gate) +
`build_materialize_fn(store, settings, tenant_id)` (a `build_fn` that only
`materialize_version`s — materialize+checksum, no full runner).

Wiring — **both transports**:

- **aiortc** `server/http.py::_run_server_async` — emitter task on the main event
  loop; default `build_fn = facade.ensure_version_built` (FULL runner → also warms
  the next chat conversation). Holds the ref, cancels in `finally`.
- **LiveKit** `transport/livekit/worker.py::_start_heartbeat` (called before
  `cli.run_app`) — the framework owns the main loop and exposes no persistent-
  coroutine hook, so the emitter runs in a **daemon thread with its own event
  loop**; `build_fn = build_materialize_fn` (materialize+checksum only — the
  dispatch process must not build LLM providers/Redis/tool-registry, but proving
  the version is fetchable+valid advances `running_version` truthfully and warms
  the shared on-disk materialized dir for job subprocesses).

Split deploy (aiortc chat + LiveKit voice, same tenant) → both may write
`<t>/_heartbeat.json` (last-writer-wins each ~20 s; same pointer → converge on the
same published version). The emitter itself is transport-agnostic.

## Degradation (maps E01–E08)

| Case | Beat behavior |
|---|---|
| Store down on read | Skip beat (no write); stale `ts` → Dashboard "Mất kết nối" (E02) |
| Published built OK | `serving`, running=published |
| Checksum mismatch (E04) | `degraded`, keep last-good running, `last_error` set |
| New version published, not yet built | Proactive build each beat → advances within ~20 s (E03 window) |
| Legacy in-place tenant | `serving` v1, no build |

## Non-goals (this slice)

- Backend/Dashboard status inference (C3.4) — their side.
- Postgres `platform` transport (SP-E) — same shape, different location.
