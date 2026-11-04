# SP1 — KB Postgres schema + native provider + full-align tool/DTO (design)

> Sub-project 1 of the "refactor phần dữ liệu agent theo DB design mới" effort.
> Decomposition: **SP1** (this doc) → SP2 (standalone Mongo→PG migration tool) →
> SP3 (RAG service 02b + Qdrant `_documents`/`_media`).
> Source of truth for the target schema: `docs/BA-docs/db-design/db-design/`
> (`00-overview.md`, `02-knowledge-base.md`, `02a-real-estate-template.md`,
> `02b-rag-service.md`).

## 1. Goal & scope

Replace the agent's structured-data layer (projects / units / documents / media
that Luna READS — Knowledge Base group **B**) with a native Postgres provider
that reads the **new standardized schema** directly, and full-align the canonical
DTOs, serializer, tool surface, enums, and prompt to that schema.

**In scope (SP1):**
- New Postgres KB schema (DDL) for `projects`/`zones`/`units`/`documents`/`media`.
- New `PostgresKBProvider` reading those tables natively (no translation shim).
- Reshape canonical DTOs (`base.py`) to the new standardized fields.
- Thin the serializer to emit standardized LLM-facing JSON keys.
- Tool surface: **remove** `get_project_financial`; **add** `get_document`;
  re-map `discover_projects`/`get_project_overview`/`search_units`/
  `check_inventory`/`recommend_units` onto new fields; standardize enums.
- **Delete** the three legacy providers (`mongo.py`/`nbx_mongo.py`/`sales_api.py`)
  and their tests; `pg_kb` becomes the sole provider.
- Update `RULES.md` tool catalog + prompt to the new tool set + JSON keys.

**Out of scope (later sub-projects):**
- SP2: the standalone migration tool that fills the new PG from Mongo `nbx_*`.
  Until SP2 runs, the new tables are empty (schema-only). This design does NOT
  populate data.
- SP3: `kb_search`/`send_media` stay on the CURRENT RAG/Mongo path in SP1. Wiring
  them to the new Qdrant `<slug>_documents`/`<slug>_media` collections + the
  embed pipeline (RAG service `02b`) is SP3. `get_document` in SP1 is a plain
  SQL read of the `documents` table (returns `file_url`), independent of Qdrant.

## 2. Target Postgres schema — `storage/sql/kb_real_estate.sql`

Applied ONCE via the existing admin path (`noble-tenant pg-apply-schema`,
admin DSN) — same mechanism as `odyssey_data_plane.sql`. Idempotent
(`CREATE … IF NOT EXISTS`, `ALTER … ADD COLUMN IF NOT EXISTS`).

Every table carries the common columns `id·tenant_id·status·created_at·updated_at`
(`status` ∈ `draft|published|archived`) and the **same two RLS policies** as the
existing `tenant_data.*` tables:
- `tenant_isolation` — `USING/WITH CHECK (tenant_id = current_user)` (Portal/admin
  per-tenant login roles).
- `agent_runtime` — `USING/WITH CHECK (tenant_id = current_setting('app.current_tenant', true))`
  (the shared runtime app role under Option-C pooling — matches the provider's
  `tenant_conn`).
`ENABLE + FORCE ROW LEVEL SECURITY` on all five tables.

FK composite `(tenant_id, project_code)` (and `(tenant_id, project_code, zone_code)`
for units→zones) so Postgres blocks cross-tenant references (§02 anchor pattern).

Tables (fields per `02a`):

- **projects** — `project_code` (`UNIQUE(tenant_id, project_code)`), `name`,
  `category text[]`, `region`, `address`, `investor`, `developer`,
  `total_land_area_m2 numeric`, `floor_area_m2 numeric`, `build_density_pct numeric`,
  `product_scale text`, `amenities text`, `ownership_form text`,
  `handover_standard text`, `total_investment_vnd bigint`,
  `sale_phase text` (`sap_mo_ban|dang_ban|ban_giao|dong_gio_hang`), `overview text`,
  `cover_media_id bigint?`, `map_media_id bigint?`, `link_360 text?`.
- **zones** — `zone_code` (`UNIQUE(tenant_id, project_code, zone_code)`), `name`,
  `category text`, `product_scale`, `overview`, `cover_media_id?`, `map_media_id?`.
- **units** — `unit_code text` (indexed, NOT unique), `zone_code text?`,
  `product_type text`, `bedrooms smallint?`, `block text?`, `floor smallint?`,
  `num_floors smallint?`, `direction text?`, `area_built_m2 numeric`,
  `area_wall_m2 numeric?`, `area_land_m2 numeric?`, `price_vnd numeric`,
  `price_per_m2_vnd numeric?`, `sale_status text` (`available|booked|sold`),
  `image_url text?`.
- **documents** — `title text`, `body text`, `file_url text?` (project_code may be
  the `"__ALL__"` sentinel for tenant-wide docs).
- **media** — `zone_code text?`, `unit_code text?`, `content_type text`
  (`image|video`), `category text` (`tong_quan|ngoai_that|noi_that|tien_ich|
  mat_bang|vi_tri|tien_do`), `caption text`, `media_url text`, `thumb_url text?`,
  `content_hash text`, `uploaded_by text?`.

**Seed:** one system row `projects(project_code='__ALL__', name='Chung / toàn
tenant', status='published')` per tenant (for tenant-wide documents/media) — seeded
by the provisioning path / a one-liner in the SQL for the current tenant.

Index every table leading with `tenant_id`; `units (tenant_id, project_code)`,
`documents (tenant_id, project_code)`, `media (tenant_id, project_code, category)`.

## 3. `PostgresKBProvider` — `data/providers/postgres_kb.py`

- Source key `pg_kb`. Registered in `data/providers/__init__.py` (new branch);
  `tenants/noble/manifest.toml` `data_source = "pg_kb"`; `config.noble_data_source`
  default → `pg_kb`.
- Reads via `storage.postgres_client.get_pool()` + `tenant_conn(current_tenant())`
  — RLS `agent_runtime` scopes every read to the current tenant automatically
  (reuses the Plan-2 shared-app-role infra, no new connection identity).
- Implements the `DataProvider` Protocol natively — SQL row → DTO 1:1 on the new
  field names. No NBX→canonical translation.
- `warm()` / `warm_if_stale(ttl)` / `cached_codes()` / `code_to_name()` /
  `registry_rows()` load the roster from `projects` (published rows) — feeds
  `find_project`'s `ProjectNameIndex` and `catalog.normalize`'s validation
  fallback. `warm()` runs a single `SELECT project_code, name, region, category
  FROM tenant_data.projects WHERE status='published' AND project_code <> '__ALL__'`.
- `pg_kb` is import-lazy behind `POSTGRES_ENABLED` like the rest of the PG stack;
  when Postgres is unconfigured the provider raises loudly on first use (KB is
  required, mirroring `get_pool`).

## 4. DTO reshape — `data/providers/base.py`

Align DTOs to the standardized fields; drop NBX-only fields.

- **Unit** → `project_code`, `project_name`, `zone_code`, `unit_code`,
  `product_type`, `bedrooms`, `block`, `floor`, `num_floors`, `direction`,
  `area_built_m2`, `area_wall_m2`, `area_land_m2`, `price_vnd`,
  `price_per_m2_vnd`, `sale_status`, `image_url`.
  **Removed:** `unit_type`/`unit_type_group` (→ `product_type`), `area_m2`
  (→ `area_built_m2`), `wall_area_m2` (→ `area_wall_m2`), `view`,
  `max_discount_pct`, `price_early_vnd`/`price_progress_vnd`/`price_loan_vnd`,
  `extras`.
- **ProjectOverview** → new project fields (`region`, `address`, `investor`,
  `developer`, `total_land_area_m2`, `floor_area_m2`, `build_density_pct`,
  `product_scale`, `amenities`, `ownership_form`, `handover_standard`,
  `total_investment_vnd`, `sale_phase`, `overview`, `link_360`). Numeric quick-facts
  are real `numeric`/`bigint`, not strings.
- **ProjectSummary** (discover) → `code`, `name`, `region`, `category` (list),
  `investor`, `price_from_vnd` (= `min(units.price_vnd)`), `sale_phase`.
  **Removed:** `hot` (no hot flag in the new schema).
- **New `Document`** DTO → `project_code`, `title`, `body`, `file_url`.
- **Removed DTOs / capability paths:** `UnitTypePricing`, `PricingTable`, and the
  `get_pricing`/`get_payment_plans`/`get_loan_policies`/`get_promotions`/
  `get_project_fees` Protocol methods + `Capability.PRICING/PAYMENT_PLANS/…`
  (financial info now lives in `documents`, answered via `kb_search`).
- **`ExtraFieldSpec` / `ToolParamSpec` / `extras`** — removed. The new schema
  models every field explicitly (design principle: no `custom_fields`). This drops
  the `custom_params` machinery (`agent/tools/custom_params.py`) and the
  `active_extra_specs`/`active_tool_params`/`build_schemas` extras plumbing;
  `schemas_for` returns the static schema directly.
- **Query objects** re-aligned: `UnitQuery` (`product_type`, `min_area_built_m2`,
  `sale_status`, `block` instead of `unit_type`/`min_area_m2`/`status`/`tower`,
  drop `custom_params`); `DiscoverQuery` (+ `sale_phase`); `RecommendQuery`
  unchanged in shape (filters on `direction` still).

## 5. Serializer — `data/providers/_serialize.py` (thinned, new keys)

Emit standardized LLM-facing JSON keys directly (the "no transfer layer" goal):
`unit_json` → `unit_code`, `product_type`, `bedrooms`, `direction`,
`area_built_m2`, `area_wall_m2`, `area_land_m2`, `price_vnd`,
`price_per_m2_vnd`, `sale_status`, `block`, `floor`, `num_floors`,
`image_url`, `project_code`, `project_name`. Overview/discover/inventory JSON
likewise use the new field names. Drop `labeled_extras` (no extras). Update
`RULES.md` so Luna reads the new keys.

## 6. Tool surface

| Tool | Change |
|---|---|
| `get_project_financial` | **Removed** (tool + `project_financial.get_project_financial`). Financial/CSBH answered via `kb_search`. |
| `get_document` | **New.** `get_document(project_code, query?)` → SQL read of `documents` (scope `project_code` + `"__ALL__"`), returns `{title, body, file_url}` for the customer's file request. Registered in `builtins.py` + `schemas.py` + `manifest.enabled` + RULES. |
| `search_units` | Re-map to new fields; `tower`→`block`, `min_area`→`area_built_m2`, `status`→`sale_status`, `unit_type`→`product_type`. Drop `custom_params` path. |
| `check_inventory` | Count by `sale_status` + by `product_type` + by `direction`. |
| `discover_projects` | Filter `region`/`product_type`/`investor`/`sale_phase`; rank stable by `sale_phase` (dang_ban→sap_mo_ban→ban_giao→dong_gio_hang) then `name`. `budget_max` now filters at project level via `price_from_vnd = min(units.price_vnd)` (PG makes this cheap — an improvement over the mongo path that ignored it). |
| `get_project_overview` | Map to new project fields incl. `sale_phase`, `amenities`, `link_360`. |
| `recommend_units` | New unit fields; feng-shui soft-rank on `direction` unchanged. |
| Enums (`schemas.py`) | Standardize `product_type`, `direction`, `sale_status`, `category`, `sale_phase`, media `category` per `02a §3`. |

`kb_search` / `send_media` executors unchanged in SP1 (SP3 rewires their backend).

## 7. Provider cleanup

Delete `data/providers/{mongo,nbx_mongo,sales_api}.py`, `_name_code_map.py`
(NBX name→code map, unused once NBX is gone), and their unit tests. Remove the
`nbx`/`sales_api`/`mongo` branches + related settings (`nbx_sales_api_*`) from the
factory/config where they become dead. `db_project_registry.py` facade stays
(delegates to the active provider — now always `pg_kb`).

## 8. Catalog / find_project

`catalog.normalize` stays a validation gate but its authoritative code list comes
from the provider (`cached_codes()`), populated from the migrated `projects` rows
(SP2). The 15 hardcoded Noble aliases in `catalog.py` may be stale after
migration — SP2/SP3 reconcile them against the real migrated codes; SP1 keeps the
provider-cached-codes fallback so any live code validates. `find_project`'s
`ProjectNameIndex` rebuilds from `registry_rows()` at bootstrap as today.

## 9. Testing

- Provider unit tests against a fake/in-memory PG (or the `sp-e-postgres` docker
  gate used by the existing PG tests) covering each DataProvider method + RLS
  scoping.
- Tool tests updated to the new JSON keys + removed `get_project_financial` +
  new `get_document`.
- Cross-tenant isolation test (tenant A cannot read tenant B's KB rows) — mandatory
  per `02 §5`.
- `find_project` / `db_project_registry` tests repointed to the PG roster.
- Delete legacy-provider tests.

## 10. Open considerations (resolve during writing-plans)

1. Exact `schemas.py` JSON-schema wording + `RULES.md` tool-catalog rewrite.
2. Whether the `__ALL__` seed row is emitted by the SQL file (current tenant) or
   the provisioning path (all tenants) — likely provisioning; SQL seeds the
   current tenant for dev.
3. `catalog.py` — whether to strip the 15 hardcoded Noble aliases now or after SP2
   confirms the migrated code set.
4. `cover_media_id`/`map_media_id` FK to `media` create a cycle
   (media→project, project→media); model as nullable bigint WITHOUT a hard FK
   (soft ref) to avoid the insert-order cycle. Confirm.
5. Live PG gate: the current tenant needs a provisioned role + `POSTGRES_ENABLED=true`
   for the provider to serve real data end-to-end (wrappers no-op otherwise).
