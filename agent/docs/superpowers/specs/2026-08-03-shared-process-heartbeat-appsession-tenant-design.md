# Shared-process heartbeat multi-tenant + app_session per-request tenant — Design

**Date:** 2026-08-03
**Branch:** `feat/share-agent`
**Status:** approved (brainstorm)

## Problem

Plan 1 (tenant contextvar spine, 2026-07-31) de-globalized the request/data path so one
shared process can serve N tenants, but **deliberately left three things process-level**
(bound once at boot/job-start, keyed on `settings.tenant_id`): the LiveKit worker's
agent-dispatch registration, the SP-D heartbeat emitter, and `app_session`'s LiveKit
token minting.

The 2026-08-03 shared-worker-routing feature already fixed the first (agent-dispatch now
registers the shared `settings.livekit_agent_name`; tenant travels in the request). This
design closes the remaining two:

1. **Heartbeat (SP-D, contract C3).** `server/http.py` and `transport/livekit/worker.py`
   each start ONE `HeartbeatEmitter` for exactly `settings.tenant_id`. In a shared process
   serving N tenants, the other N−1 tenants get no `<tenant>/_heartbeat.json`, so the
   Dashboard shows them "Mất kết nối" forever even though the process is serving them.
2. **app_session voice mint.** `_mint_livekit_token` (called by `POST /api/v1/app/session
   channel=voice`, the NobleX mobile-app → agent path) does NOT put `tenant_id` into the
   LiveKit participant metadata, so a voice call provisioned there resolves to
   `settings.tenant_id` in the worker's `_job_tenant`, not the caller's tenant.

Both are **inert on the live Noble/Santa deployment** (`TENANT_STORE_ENABLED=false` gates
the heartbeat; single-tenant deploys have exactly one tenant), so this work prepares the
Odyssey shared-process path with **zero impact on the current live deployment**.

## Principles

- **Tenant resolved per-tenant / per-request, not `settings.tenant_id` at process scope.**
- **Single-tenant / direct paths stay byte-identical:** absent tenant → fall back to
  `settings.tenant_id`; store disabled → heartbeat inert.
- **Surgical / additive.** No change to RAG / `send_media` / `kb_search`, the turn loop,
  the gateway (just-shipped), or the Redis key shape.

---

## Part A — Heartbeat multi-tenant (`HeartbeatSupervisor`)

### Why a supervisor
`HeartbeatEmitter` carries **per-tenant** state (`started_at`, `_running`, `_last_error`).
Looping one emitter over N tenants would clobber that state, so each tenant needs its own
emitter. A supervisor owns the set and reuses `HeartbeatEmitter.beat()` unchanged.

### `HeartbeatSupervisor` (new, in `tenant/heartbeat.py`)

Interface:
```
HeartbeatSupervisor(store, settings, *, build_fn_factory=None, now_iso=_utc_iso)
  async run(stop_event: asyncio.Event) -> None
```

- Owns `self._emitters: dict[str, HeartbeatEmitter]`.
- `build_fn_factory(tenant_id) -> build_fn`: defaults to
  `build_materialize_fn(store, settings, tenant_id)` — **materialize-only for every
  tenant** (prove the published version is fetchable + checksum-valid (E04), warm the
  on-disk materialized dir; NO full LLM runner). This unifies both transports. It replaces
  the aiortc process's previous `ensure_version_built` (full-runner) warm — accepted
  trade-off: the first conversation still builds the runner lazily.
- `_active_tenants() -> list[str]`: `store.list_ids()` filtered to
  `store.read_meta(t).status == "active"` (both reads via `asyncio.to_thread`). On a store
  read error, **keep the current known set and skip the refresh** (an emitter that can no
  longer read its version already emits `degraded`/skips; a stale `ts` is the honest
  "disconnected" signal).
- `run(stop_event)` per cycle:
  1. Refresh the active set (best-effort; store error → keep prior set).
  2. Reconcile `self._emitters`: create an emitter for each newly-active tenant (lazy);
     drop the emitter for any tenant no longer active (just stop beating it — its `ts` goes
     stale → the Dashboard infers disconnected/inactive; no explicit "disabled" beat).
  3. `await asyncio.gather(*(em.beat() for em in self._emitters.values()),
     return_exceptions=True)` — beat all active tenants concurrently (each beat does its own
     `to_thread` store reads/writes; `beat()` already swallows its own exceptions, and
     `return_exceptions=True` guards the gather regardless).
  4. `await asyncio.wait_for(stop_event.wait(), timeout=heartbeat_sec)` (cancel-safe;
     mirror the existing `HeartbeatEmitter.run` sleep).

`should_emit(settings)` gate is unchanged and checked **before** starting the supervisor.

### Behavior equivalence
- Store disabled → `should_emit` false → supervisor never starts (live Noble unchanged).
- Store enabled with exactly one active tenant → one emitter → same as today (except the
  aiortc warm switches to materialize-only, per above).
- Store enabled with N active tenants → N heartbeat files, one per tenant (the fix).

### Wiring
- `server/http.py` (~L1024-1060): replace the single
  `HeartbeatEmitter(store, settings, settings.tenant_id)` + task with
  `HeartbeatSupervisor(store, settings)` run as an asyncio task; cancel on shutdown
  (unchanged pattern).
- `transport/livekit/worker.py` (`_start_heartbeat`, ~L263-304): replace the single
  materialize-only emitter with the supervisor, still on the daemon thread + its own event
  loop (the framework owns the main loop via `cli.run_app`). The worker already used
  materialize-only, so the `build_fn_factory` default matches.

---

## Part B — app_session per-request tenant

### Changes in `server/app_session.py`
1. `provision_session(body)`: resolve
   `tenant_id = str(body.get("tenant_id") or "").strip() or settings.tenant_id`, and wrap
   the provision body in `with use_tenant(tenant_id):` (scopes every tenant-keyed read/write
   via `current_tenant()`; cheap, future-proof).
2. `_mint_livekit_token(session_id, identity, name, *, tenant_id=None,
   empty_timeout=_ROOM_EMPTY_TIMEOUT_S)`: resolve `tid = tenant_id or settings.tenant_id`
   and add `.with_metadata(json.dumps({"tenant_id": tid}, ensure_ascii=False))` so the
   worker's `_job_tenant` reads the caller's tenant. Pass `tenant_id=tenant_id` from the
   `provision_session` voice branch.
3. `GET /livekit/token` (dev tester, shares `_mint_livekit_token`): passes no `tenant_id`
   → falls back to `settings.tenant_id` → unchanged.

### Byte-identical single-tenant
No `tenant_id` in the body → `tenant_id = settings.tenant_id`. The participant now carries
`{"tenant_id":"noble"}` metadata where before it had none, but `_job_tenant` still resolves
`"noble"`, and `identity_to_fields` is a strict whitelist (full_name / phone / gender /
is_noble_customer / noble_info) that ignores the `tenant_id` key → no `Customer` pollution.
Behavior-equivalent; purely additive.

---

## Testing (both parts)

- **`HeartbeatSupervisor`** (extend `tests/unit/tenant/test_heartbeat.py` or a new file):
  Fake store (reuse the existing test Fake) with `list_ids` / `read_meta` / `read_pointer` /
  `write_heartbeat`. Assert: emits one heartbeat per active tenant; a `draft`/`disabled`
  tenant gets no beat; a store-read error keeps the prior set and skips the refresh
  (no crash); reconcile adds/drops emitters when the active set changes; each emitter keeps
  its own `started_at`/`running`/`last_error`.
- **`provision_session` / `_mint_livekit_token`** (extend
  `tests/unit/unified/test_app_session.py`): body `tenant_id` → minted token metadata JSON
  carries that tenant, and the provision runs under `use_tenant(that_tenant)`; body without
  `tenant_id` → falls back to `settings.tenant_id`; the dev `/livekit/token` path still
  mints with `settings.tenant_id`.
- **Full gate:** `make test-unit` — **zero new failures** vs the documented baseline
  (~9-11 pre-existing red: 2 USD-normalize, `test_tool_ack` flaky, vieneu_vllm, prompt
  'Tên:', qdrant_adapter×2, qdrant_store, send_media local-.env; project_financial_mongo /
  snapshot_short_term vary). ruff `E,F,W,I,UP,B,SIM`, line-length 120.

## Files touched

- `src/noble_agent/tenant/heartbeat.py` — add `HeartbeatSupervisor` (keep `HeartbeatEmitter`
  + `build_materialize_fn` + `should_emit` as-is).
- `src/noble_agent/server/http.py` — supervisor wiring in the aiortc boot path.
- `src/noble_agent/transport/livekit/worker.py` — supervisor wiring in `_start_heartbeat`.
- `src/noble_agent/server/app_session.py` — per-request tenant in `provision_session` +
  `_mint_livekit_token`.
- Tests as above.

## Out of scope

- The gateway (already multi-tenant from the 2026-08-03 shared-worker-routing feature).
- Redis session-key tenant scoping (`session:{sid}:*` keys are effectively globally unique
  via `noble_user_id`-derived session ids; not part of this slice).
- Live smoke against a real MinIO store + LiveKit — deferred to the Odyssey shared-process
  rollout.
