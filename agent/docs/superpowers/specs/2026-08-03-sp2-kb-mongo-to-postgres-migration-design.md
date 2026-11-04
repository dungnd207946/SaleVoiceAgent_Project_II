# SP2 — KB backfill: Mongo `nbx_*` → Postgres KB (projects + units) (design)

> Sub-project 2 of the "refactor phần dữ liệu agent theo DB design mới" effort.
> SP1 (done) built the Postgres KB schema + `PostgresKBProvider` (`pg_kb`), which
> reads empty tables until data is loaded. SP2 is a **standalone migration tool**
> that backfills `tenant_data.projects` + `tenant_data.units` for tenant `noble`
> from the live Mongo `nbx_*` mirror, so the agent's structured tools serve real
> data end-to-end. SP3 (later) owns `documents`/`media` + the RAG/Qdrant path.

## 1. Goal & scope

Populate the new Postgres KB `projects` + `units` tables (tenant `noble`,
`status='published'`) from Mongo `nbx_projects` + `nbx_units`, idempotently, via a
self-contained script independent of the `noble_agent` package.

**In scope:** `projects` + `units` migration + transform + idempotent sink + a
CLI with dry-run + transform unit tests + a live dry-run and real run verified by
`PostgresKBProvider` reading the rows back.

**Out of scope (deferred to SP3):** `zones` (no source in `nbx_*`), `documents`
(text knowledge lives in `data/faq/<CODE>.md` + `data/md_v2/ABOUT_*.md`, tied to
the RAG build), `media` (served by the `:8015` media service / Qdrant `media_v2`,
no clean Mongo source). These stay empty after SP2 — the agent degrades to
`ESCALATE_SIGNAL`/`kb_search`, never crashes (proven in SP1).

## 2. Location, independence, connections

- New top-level dir `migration/kb_backfill/` (OUTSIDE `src/noble_agent`; does NOT
  import `noble_agent`). Run as `python -m kb_backfill` from `migration/`, or a
  thin `migration/kb_backfill/__main__.py`.
- **Source:** Mongo via `pymongo` (sync is fine for a batch tool). Reads
  `nbx_projects` + `nbx_units` read-only. Connection from `--mongo-uri` /
  `--mongo-db`, defaulting to the repo `.env`'s `MONGODB_URI` / `MONGODB_DATABASE`
  (the tool loads `.env` itself with `python-dotenv`; it does not read
  `noble_agent.config`).
- **Sink:** Postgres via `asyncpg`, using the **admin/superuser DSN**
  (`--pg-dsn`, default `.env` `POSTGRES_ADMIN_DSN`). A superuser **bypasses RLS**
  (even FORCE), so the tool writes rows with an explicit `tenant_id` column value
  and needs no `set_config('app.current_tenant', …)` — same posture as the
  provisioning path. Assumes the SP1 schema is already applied
  (`noble-tenant pg-apply-schema`); the tool does not create tables.
- CLI flags: `--mongo-uri`, `--mongo-db`, `--pg-dsn`, `--tenant` (default
  `noble`), `--dry-run` (transform + print stats, no writes), `--limit N`
  (optional, for a smoke subset).

## 3. Modules (one responsibility each, transform is the tested core)

- `mongo_source.py` — `read_projects(db)` (skip docs whose `projectCode` is empty —
  matches the ingest contract) and `read_units_by_project(db, project_oid_str)`
  (`nbx_units.find({"projectId": str(nbx_projects._id)})`). Returns raw dicts.
- `transform.py` — **pure functions, no I/O** (unit-tested): `project_row(doc,
  units)` and `unit_row(u, project_code)` returning column→value dicts, plus the
  helpers copied verbatim from the retired `nbx_mongo.py` (`_to_vnd` tỷ×1e9,
  `_to_float`, `_bedrooms`, a `direction` folder, a `sale_status` mapper, a
  `product_type` best-effort mapper). Emits a per-call list of "unmapped" notes
  (direction/product_type/sale_status fallbacks) for the stats roll-up.
- `pg_sink.py` — `upsert_project(conn, row)` (`INSERT … ON CONFLICT (tenant_id,
  project_code) DO UPDATE`), `replace_units(conn, tenant, project_code, rows)`
  (`DELETE FROM tenant_data.units WHERE tenant_id=$1 AND project_code=$2` then
  batch `INSERT`, all in ONE transaction per project so a project's inventory is
  atomically replaced — idempotent without a `units` unique key, respecting the
  design's "`unit_code` indexed, NOT unique").
- `__main__.py` — orchestrator: load `.env`, connect, loop projects (each in its
  own PG transaction: upsert project → replace units), accumulate stats, print a
  summary table (`projects_migrated`, `units_migrated`, `projects_skipped_no_code`,
  `direction_unmapped`, `product_type_null`, `sale_status_fallback`). `--dry-run`
  runs transform + stats only (no PG writes).

## 4. Field mapping

### 4.1 `projects` ← `nbx_projects` (+ its units for `category`)
| PG column | Source | Note |
|---|---|---|
| `tenant_id` | — | literal `noble` (or `--tenant`) |
| `project_code` | `projectCode` (`.strip()`, canonical upper) | skip doc if empty |
| `name` | `name` | |
| `category` (text[]) | **derived**: sorted DISTINCT `product_type` of this project's migrated units; empty units → best-effort from `type` (`cao_tang`→`{chung_cu}`, `thap_tang`→`{biet_thu}`, `hon_hop`→`{chung_cu,biet_thu}`) | |
| `region` | `areaRegion` | |
| `address` | `location` | district text |
| `investor` | `investor` | |
| `product_scale` | `overview.scale` | text |
| `ownership_form` | `overview.ownership` | text |
| `overview` | `description` | project blurb |
| `sale_phase` | literal `dang_ban` | default (nbx has no per-project phase) |
| `status` | literal `published` | so the agent sees it |
| `developer`, `total_land_area_m2`, `floor_area_m2`, `build_density_pct`, `handover_standard`, `total_investment_vnd`, `amenities`, `link_360`, `cover_media_id`, `map_media_id` | — | **NULL** (no `nbx_*` source) |

`overview` is an embedded object; decode defensively (a doc may still carry a
double-encoded JSON string) — reuse the retired `_overview_obj` logic. Keys used:
`scale`, `ownership` (`units_text`/`product` are not mapped to a column this
phase; they can enrich `overview` text later if wanted).

### 4.2 `units` ← `nbx_units`
| PG column | Source | Note |
|---|---|---|
| `tenant_id` | — | `noble` |
| `project_code` | parent's `projectCode` | |
| `unit_code` | `code` | indexed, not unique |
| `product_type` | best-effort: `STUDIO` name → `studio`; else by project `type` (`cao_tang`→`chung_cu`, `thap_tang`→`biet_thu`, `hon_hop`→`chung_cu`); unresolved → **NULL** (+stat) | |
| `bedrooms` | `_bedrooms(unitType.name)` (`"2PN"`→2, `studio`→0) | smallint |
| `direction` | fold `direction` free-text → the 8-enum (`dong/tay/nam/bac/dong_bac/dong_nam/tay_bac/tay_nam`); unmapped → **NULL** (+stat) | |
| `area_built_m2` | `area` (thông thủy) via `_to_float` | |
| `area_wall_m2` | `areaBuild` via `_to_float` | |
| `price_vnd` | `price` (tỷ) × 1e9 via `_to_vnd` | |
| `price_per_m2_vnd` | **derived**: `round(price_vnd / area_built_m2)` when both present, else NULL | deterministic, no fabrication |
| `sale_status` | map: `available`/`ready`→`available`, `sold`→`sold`, `locked`→`booked`, else→`available` (+stat) | new enum has only available/booked/sold |
| `image_url` | `image` | |
| `status` | literal `published` | |
| `zone_code`, `block`, `floor`, `num_floors`, `area_land_m2` | — | **NULL** (no source) |

Best-effort policy (per the scope decision): map when possible, NULL/default when
not, and **log a count** of each fallback in the run summary. No hard failure on
an unmapped enum value.

## 5. Idempotency & RLS

- Re-runnable: `projects` upserted on `(tenant_id, project_code)`; `units`
  delete-then-insert per project in one transaction. A second run converges to the
  same state (no duplicate units, updated project fields).
- The FK `units → projects (tenant_id, project_code)` is satisfied because each
  project row is upserted before its units in the same per-project flow.
- Superuser DSN bypasses RLS; `tenant_id` is written explicitly. (If a future run
  must use a non-superuser role, it would `SET app.current_tenant='noble'` per txn
  to satisfy the `agent_runtime` WITH CHECK — documented, not implemented now.)

## 6. Testing & verification

1. **Transform unit tests** (`migration/kb_backfill/tests/test_transform.py`,
   pytest, offline): fixtures of representative `nbx_projects`/`nbx_units` docs →
   assert the mapped row dicts: tỷ→VND (`price` `5.62` → `5_620_000_000`),
   `area`→`area_built_m2`, `areaBuild`→`area_wall_m2`, `price_per_m2` derivation,
   `_bedrooms`, direction fold (a known value → enum; a junk value → NULL + note),
   `sale_status` map incl. the fallback, `product_type` studio/cao_tang paths,
   `category` derived from a mixed unit set, empty `projectCode` skipped, defensive
   `overview` string decode.
2. **Live dry-run** against the `.env` Mongo `nbx_*`: `python -m kb_backfill
   --dry-run` → prints real counts + fallback stats (no writes). Confirms the
   source is reachable and the mapping covers the real data shape.
3. **Real run into docker `sp-e-postgres`** (schema pre-applied): run without
   `--dry-run`; then, from a short async check using the SP1 `PostgresKBProvider`
   scoped to `noble` (`use_tenant('noble')` + the pool), assert `get_overview`,
   `search_units`, and `discover_projects` return the migrated rows — the
   end-to-end SP1+SP2 proof. Re-run the tool once more and confirm row counts are
   unchanged (idempotency).

## 7. Dependencies

`pymongo`, `asyncpg`, `python-dotenv` — declared in a `migration/kb_backfill/`
local `requirements.txt` (or `pyproject`), NOT added to the agent's deps (the tool
is independent). `asyncpg`/`python-dotenv` already exist in the agent venv, so a
local dry-run/run works without extra install; `pymongo` may need adding (the
agent uses `motor`, which vendors `pymongo`, so it is importable in the venv).

## 8. Open considerations (resolve during writing-plans / run)

1. Exact `direction` fold table — build from the DISTINCT `direction` values seen
   in the live dry-run (step 6.2), so the map covers real inputs; unknowns → NULL.
2. Whether `overview.units_text`/`product` should be appended into the `overview`
   text column (richer RAG source later) — default NO this phase (keep `overview`
   = `description`).
3. `product_type` mapping is coarse (project-`type`-driven); if `nbx_units`
   carries a finer per-unit type/group signal in the live data, refine the mapper
   during the dry-run. Unresolved → NULL is acceptable (agent still filters on the
   other fields).
4. Confirm `pymongo` import works in the venv; if not, the tool's requirements
   install it.
