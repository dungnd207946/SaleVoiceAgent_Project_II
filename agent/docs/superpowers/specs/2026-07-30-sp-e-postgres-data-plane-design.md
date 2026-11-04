# SP-E — Postgres Data Plane (Odyssey contract C4 + C5 Postgres bits) — Design

**Slice:** SP-E of the Odyssey SaaS pivot (HT_01 flow B read / C write). Implements
contract **C4** (data plane) + the Postgres parts of **C5** (provisioning) in
`docs/api/odyssey-agent-interface-contract.md`. Follows SP-C (config versioning) +
SP-D (heartbeat). Branch `feat/agent`.

> **This is the largest slice** and is decomposed into vertical sub-slices (SP-E1…E4),
> each with its own plan + TDD, mirroring how SP-C split into C1/C2.

## N9 outcome (unblocks this slice)

**N9 = Fixed store** (chốt 2026-07-30). Santa/Mongo is frozen on a separate branch;
Odyssey (`feat/agent`) migrates **all** agent writes to Postgres. Each branch's code
knows exactly ONE store — **there is NO config-driven mongo↔postgres write seam**.
Consequence: SP-E writes straight to Postgres; we do NOT build a write-provider
abstraction (unlike the read-provider abstraction that exists for pricing/units).

## Current state (what exists / what's missing)

- **Dead scaffold to remove/repurpose:** `config.py` has `data_mode` /
  `postgres_uri_mock` / `postgres_uri_real` / `POSTGRES_URI` — **no usage in `src/`,
  no driver installed, no docker service, `postgres_uri_real` empty**. SP-E1 replaces
  this with a real, used config.
- **No Postgres driver** (asyncpg/psycopg/sqlalchemy absent from `pyproject.toml`).
- **Agent write paths today (all Mongo)** — the migration targets:
  | Contract table (C4.2) | Today (Mongo) | Notes |
  |---|---|---|
  | `conversations` (flattened + skill-call log + config-version pointer) | `storage/call_summaries.py` + `storage/call_events.py` (`hotline_call_summaries`/`hotline_call_events`) | C4.2 wants ONE flattened row (self-carries customer/project/handoff) + skill-call log + `running_version`; 6-month retention; phone for NĐ13 delete. Fixes today's 3 gaps: no skill-call, no index, no delete-by-phone. |
  | `appointments` | `storage/bookings_flat.py` (`hotline_bookings_flat`) | agent-booked + human-edited = one table. |
  | `contacts` | `storage/user_snapshots.py` + `storage/snapshot_lock.py` (`hotline_user_snapshots`) | cumulative per-phone profile (= old "user snapshot"). |
- **Agent read paths today:** `data/providers/{nbx,sales_api,mongo}.py` (projects/units).
  C4.1/C4.2 wants reads for Odyssey via **`VIEW agent_*`** on Postgres (column-gated by
  the pinned version's `field_policy`).
- **Qdrant:** shared clone collection today; C4.3 wants **one collection per tenant**
  (`<QDRANT_PREFIX>_<tenant_id>`).

## Contract invariants SP-E must honor

- **BR01:** agent talks ONLY to Postgres + file store + shared compute services — never
  Portal. Reads are **in-process, one hop** to Postgres (voice-latency reason).
- **BR08/BR09 (isolation, DB-enforced):** per-tenant Postgres **role + password**; the
  container has creds for **exactly one** tenant (`TENANT_ID` frozen). **RLS per-row** +
  `VIEW agent_*` **column-gate** (columns the agent may read come from the pinned
  version's `field_policy`, see C2.2). Agent GHI only 3 tables; never touches config
  tables even if compromised. Verifiable promise: **workspace A cannot read workspace B**.
- **C5.1 BR12 (all-or-nothing provisioning):** creating a tenant creates resources in
  **all** stores or none — bundle + `_meta.json` (done, SP-C1) + `_creds.json` (done,
  slice #2) + **[SP-E] Postgres role + seed `tenant_data` row** + **[SP-E] Qdrant
  collection** — rollback on partial failure.
- **E05/E06 degradation:** Postgres down → tell the truth + offer a human, do NOT
  fabricate; Qdrant down → general answer, no doc citation.

## Vertical sub-slices (each its own plan + TDD)

- **SP-E1 — Postgres foundation.** Add driver (asyncpg) + a small async pool/connection
  module (mirrors `storage/mongo_client.py` seam), real config (kill the dead scaffold),
  a **local dev Postgres** (docker-compose service) + a DDL/migration runner. Deliver the
  DDL for the 3 write tables + `VIEW agent_*` + RLS policies + per-tenant role template.
  Gated on the DDL-ownership decision (agent-side vs Backend/ops).
- **SP-E2 — Write plane.** Migrate `conversations`/`appointments`/`contacts` writes from
  Mongo to Postgres (rewrite `call_summaries`+`call_events` → `conversations` incl.
  skill-call log + `running_version` from `NobleAgent.pinned_version`; `bookings_flat` →
  `appointments`; `user_snapshots` → `contacts`), under RLS with the tenant role.
  E05 degradation on the turn/call-end paths.
- **SP-E3 — Read plane.** A `postgres` data provider reading `VIEW agent_*`
  (projects/units/doc-meta), column-gated by the pinned version's `field_policy`. Wire
  into `data/providers/get_provider` (Odyssey → postgres).
- **SP-E4 — Qdrant per-tenant + provisioning wiring.** `<QDRANT_PREFIX>_<tenant_id>`
  collection; extend `noble-tenant` provisioning to the all-or-nothing set (Postgres role
  + seed row + Qdrant collection) with rollback (C5.1).

## Hard prerequisites (gate coding SP-E1)

1. **A real Postgres to build+verify against.** Options: (a) stand up a local docker
   Postgres for dev/TDD now; (b) an ops-provided endpoint. `postgres_uri_real` is empty.
2. **DDL + per-tenant role ownership (C5.1 BR12):** does the **agent** own the DDL +
   `CREATE ROLE`/RLS (via `noble-tenant`), or does **Backend/ops** provision the schema +
   roles and the agent only connects? This changes whether SP-E1/E4 include DDL+role
   creation code or just a connection contract.
3. **`field_policy` source:** SP-C1 reserved `version.json.field_policy` (currently
   `None`). SP-E3's column-gate needs its concrete shape (which columns per version).

## Non-goals

- Santa/Mongo migration (frozen on its own branch per N9).
- Removing the read-provider abstraction (still used by the frozen Santa branch).
