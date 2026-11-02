# SP-E — Postgres Data Plane — Implementation Plan

Spec: `docs/superpowers/specs/2026-07-30-sp-e-postgres-data-plane-design.md`. Branch `feat/agent`.
N9 = **Fixed store** (Odyssey writes Postgres; no config-driven write seam). DDL/roles
owned **agent-side** (`noble-tenant`). Dev PG = `docker-compose.pg.yml` (local).

## SP-E1 — Postgres foundation ✅ DONE + live-verified

- `pyproject.toml`: `postgres` extra (`asyncpg>=0.29`, import-lazy).
- `config.py`: `POSTGRES_ENABLED` / `POSTGRES_DSN` (runtime, per-tenant role) / `POSTGRES_ADMIN_DSN`
  (provisioning superuser). Left the dead `data_mode`/`POSTGRES_URI` scaffold untouched (surgical;
  it claims external "Luna shared services" use).
- `storage/postgres_client.py`: async asyncpg pool singleton (lazy import, `get_pool`/`healthcheck`/
  `close_pool`/`set_pool_for_tests`) — fail-loud (Postgres is required, unlike the Mongo sink).
- `storage/sql/odyssey_data_plane.sql`: schema `tenant_data` + 3 tables (conversations/appointments/
  contacts) + **RLS ENABLE+FORCE, policy `USING/WITH CHECK (tenant_id = current_user)`** — isolation
  keyed on the connecting ROLE, unspoofable in-session (BR08/BR09). Idempotent.
- `tenant/pg_provisioning.py`: `role_name` (validates safe slug), `read_ddl`, `apply_schema`,
  `provision` (CREATE ROLE + GRANT in ONE tx = all-or-nothing, BR12), `deprovision` (delete rows +
  DROP OWNED + DROP ROLE). Password quoted safely (asyncpg can't parameterize DDL).
- CLI: `noble-tenant pg-apply-schema` / `pg-provision <t> [--password]` / `pg-deprovision <t>`.
- `docker-compose.pg.yml` (local dev PG) + `.env.example` block + `needs_postgres` marker.

**Verification (DONE):**
- Unit: `tests/unit/tenant/test_pg_provisioning.py` (9) — role_name valid/rejects-injection, DDL
  declares tables + FORCE RLS + `current_user`, pw-literal escaping. `tests/unit/tenant` 120 green.
- **Live Postgres 16 (docker):** `tests/integration/tenant/test_pg_rls_live.py::test_rls_cross_tenant_isolation`
  (guarded by `SPE_PG_ADMIN_DSN`, marker `needs_postgres`) PASS — A writes its row, A **cannot** write
  a B-tagged row (WITH CHECK), B sees **0** of A's rows (USING), A sees exactly its own. Plus CLI e2e:
  apply-schema → provision (role+pw) → role connects+inserts → deprovision → role gone.
- Ruff clean on all new files (pre-existing `config.py:487` E501 untouched, surgical).

## SP-E2 — Write plane ◑

### Increment 1 — PG write DAO layer ✅ DONE + live-verified

`storage/pg_data_plane.py` — the Odyssey agent WRITE DAOs for the 3 tables, run under the
tenant role so RLS `(tenant_id = current_user)` isolates inherently:
- `upsert_contact` / `get_contact` (← `user_snapshots`).
- `record_conversation` — **merge-upsert** by (tenant, session): partial writes (call-end summary,
  then a separate handoff update) never null out omitted fields (COALESCE), `transferred_to_sales`
  is sticky-true, `skill_calls` preserved when the incoming set is empty (← `call_summaries` + the
  skill-call log folded from `call_events`). Carries `running_version` (from `NobleAgent.pinned_version`).
- `insert_appointment` / `update_appointment_status` (← `bookings_flat`).
- `db` = pool-or-connection (testable); DAOs raise on error, call sites keep best-effort.

Verified LIVE (Postgres 16): `tests/integration/tenant/test_pg_data_plane_live.py` (3) — contacts
upsert+read+isolation, conversation merge-upsert (no dup, skill_calls/running_version preserved across
a partial 2nd write), appointment insert/update + a second tenant sees/updates NONE of the first's rows.

### Increment 2 — Call-site cutover (per-table, keep-green each step)

Decision (user): **cutover toàn bộ trên feat/agent** (PG-only writes). Done per-table so each
table stays consistent write+read (never split store), verifying + keeping the gate green each step.

**Table `contacts` ✅ DONE + verified.** Best-effort wrappers `pg_data_plane.persist_contact` /
`read_contact_snapshot` (acquire pool + swallow → no-op when PG unconfigured, e.g. noble w/o a role).
Flipped: `memory.update_snapshot_after_call` write+read (`save_snapshot`/`load_snapshot`→wrappers),
`snapshot.build_short_term_context` read. `user_snapshots.py` DAO left in place (now uncalled — not
deleted per surgical rule; its unit test still green). Tests `test_snapshot_short_term` +
`test_snapshot_entry_helpers` repointed to the PG wrappers (read now returns a str, persist drops the
sid arg). Full gate **1682 passed / 8 failed (baseline, −1: fixed a stale header assertion) / 0 new**.

**Table `appointments` ✅ DONE + live-verified.** Key finding: the agent hot path (`list`/`modify`/
dup-check) reads **Redis scratchpad**, NOT Mongo — only `load_latest_booking_hint_by_phone` (bootstrap)
and the dashboard read the flat store. `save_bookings` (embedded `bookings`) + `update_booking_status`
are DEAD (no callers). DDL: added `appointment_id text` + `UNIQUE(tenant_id, appointment_id)` (idempotent
ALTER for the already-applied table) so `modify` re-upserts the SAME row (mirrors Mongo `upsert_booking`).
DAO: `insert_appointment`→`upsert_appointment` (ON CONFLICT), `get_latest_appointment_by_phone`; wrappers
`persist_appointment` (project→project_code) / `read_latest_booking_hint`. Flipped
`schedule_viewing._persist_flat`→PG + `session_store.load_latest_booking_hint_by_phone`→PG. Tests repointed
(test_booking_persist / test_booking_hint) + new test_pg_appointment (8). `bookings_flat.py` DAO left in
place (uncalled, surgical).

**Table `conversations` ✅ DONE + live-verified.** `record_conversation` had NO caller — built the write.
Key findings: NO `skill_calls` producer (old `agent_path` always []) → left to DAO default; `call_events`
has no live reader after the dashboard drop → goes inert (Mongo None → no-op), NOT migrated; escalate does
NOT persist to the summary (only the dashboard /handoff did). New wrappers `persist_conversation`
(summary_doc→row, project_code→project, `running_version` from `NobleAgent.pinned_version` via VoiceAgent/
llm) / `list_conversation_hints` + DAO `list_conversations_by_phone`. Flipped the 3 call-end sites
(base_session / text_chat / telephony: `save_call_summary`→`persist_conversation`) + memory read
`snapshot._latest_prior_session`→PG. Tests repointed (test_text_chat_persist / test_snapshot_short_term —
the latter was a baseline failure, now GREEN) + new test_pg_conversation (7). `call_summaries.py` DAO +
its persist/dualwrite tests left in place (uncalled, surgical).

**Table `contacts.profile` (customers fold) ✅ DONE + live-verified.** The structured `customers`
collection (name/gender/project_interest/budget/…) — NOT one of the 3 C4 tables — folded into a new
`contacts.profile` jsonb (idempotent `ADD COLUMN`). snapshot vs profile are upserted independently on the
same (tenant,phone) row, neither clobbering the other. DAO `upsert_contact_profile` (shallow jsonb merge
`profile || incoming`; `insert_default` `{"name":"No Name"}` insert-only underneath incoming) + `get_contact`
extended to SELECT profile; wrappers `persist_customer_profile` (truthy-merge clean) / `read_customer_profile`
(parses jsonb text). Flipped `session_store.load_customer_by_phone` + `save_customer_persistent`→PG (public
names kept → bootstrap/update_customer/text_chat tests unchanged). test_customers_persist repointed + new
test_pg_customer_profile (9).

**Dashboard endpoints ✅ RETIRED (D1 = Drop/stub, Portal-owned).** `http._handle_sales_api` now 410s the
migrated-data routes (handoff / summaries* / bookings* / stats* / customers[360|search|history]) —
Portal reads PG directly. `outbound/*` and `noble/profile` (separate subsystems, still Mongo) fall through
untouched. The route handlers below the gate are unreachable-but-kept (surgical stub). No unit tests hit
these endpoints (only the opt-in `-m bench` `test_dashboard_latency`, which calls the DAOs directly).

**Verification (increments 2+3 + dashboard):** full unit gate **1702 passed / 8 failed (all baseline:
2 USD-normalize, project_financial, prompt 'Tên:', 2 qdrant_adapter, qdrant_store, send_media local-.env)
/ 0 new** (snapshot_short_term, a prior baseline failure, is now GREEN). Ruff clean on all authored code
(pre-existing SIM/E501 in touched files verified HEAD==now). **Live Postgres 16 (docker sp-e-postgres):
`test_pg_data_plane_live.py` 5/5** — appointments upsert-idempotency + COALESCE partial + latest-by-phone
hint + RLS; conversations merge-upsert + list-by-phone; contacts profile/snapshot coexistence + jsonb
merge + No-Name-overwritten-by-real-name + RLS; DDL ALTERs applied to the pre-existing tables.

**Out of scope / remaining (NOT SP-E2's 3 C4 tables):** `outbound_*` calling subsystem + `noble_profiles`
service still on Mongo; a live `/chat` end-to-end smoke needs a provisioned `noble` PG role +
`POSTGRES_ENABLED=true` (today the wrappers no-op for noble → PG writes skipped). **Sequencing:** feat/agent
going PG-only should coincide with Santa/Mongo moving to its frozen branch.

## SP-E3 — Read plane ○

`postgres` data provider reading `VIEW agent_*` (projects/units/doc-meta), column-gated by the pinned
version's `field_policy` (needs `version.json.field_policy` concrete shape — currently `None`). Wire into
`data/providers/get_provider` (Odyssey → postgres).

## SP-E4 — Qdrant per-tenant + provisioning all-or-nothing ○

`<QDRANT_PREFIX>_<tenant_id>` collection; fold Postgres role + seed row + Qdrant collection into
`noble-tenant` create/disable as the C5.1 all-or-nothing set with rollback.

## Open items feeding SP-E2/E3

- `field_policy` concrete shape (SP-C1 reserved it as `None`).
- Retention job (conversations 6 months) + NĐ13 delete-by-phone — owner/cron TBD.
