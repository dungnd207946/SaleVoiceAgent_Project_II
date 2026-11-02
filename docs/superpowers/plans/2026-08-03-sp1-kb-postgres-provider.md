# SP1 — KB Postgres schema + native provider + full-align tool/DTO — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the agent's structured-data layer (projects/zones/units/documents/media that Luna READS) with a native Postgres provider on the new standardized schema, and full-align the canonical DTOs, serializer, tool surface, enums, and prompt to that schema.

**Architecture:** A new `PostgresKBProvider` (source key `pg_kb`) reads five new `tenant_data` tables directly via the existing shared-app-role pool (`storage/postgres_client.py` + `tenant_conn` + RLS `agent_runtime`), mapping SQL rows 1:1 onto reshaped canonical DTOs (no translation shim). The three legacy providers (mongo/nbx/sales_api) and the `extras`/`custom_params` machinery are deleted; `get_project_financial` is removed and `get_document` is added. `kb_search`/`send_media` keep their current RAG backend (SP3 rewires them).

**Tech Stack:** Python 3.11+, asyncpg (existing lazy dep), Postgres 16 + RLS, pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-08-03-sp1-kb-postgres-provider-design.md`. Target-schema source of truth: `docs/BA-docs/db-design/db-design/02a-real-estate-template.md`.
- Branch: work on the current branch `feat/share-agent`. NEVER touch `develop`. No new branch, no push, no PR without explicit instruction. Local commits on `feat/share-agent` only.
- Reuse the existing PG infra verbatim: `storage/postgres_client.py::get_pool` / `tenant_conn(pool, tenant_id)`; the current-tenant contextvar `noble_agent.tenant.current.current_tenant()`. Do NOT read `settings.tenant_id` on the data path.
- New KB tables live in schema `tenant_data`, carry `id·tenant_id·status·created_at·updated_at`, `ENABLE + FORCE ROW LEVEL SECURITY`, and the SAME two policies as `odyssey_data_plane.sql` (`tenant_isolation` on `current_user`; `agent_runtime` on `current_setting('app.current_tenant', true)`). DDL idempotent.
- Canonical units on the wire: `price_*_vnd` = integer/numeric VND (NOT tỷ); `*_m2` = float; enums are the standardized `02a §3` values. Missing field → `None`, never fabricated.
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Do not fix pre-existing lint in files you don't otherwise touch.
- Run the unit gate with `make test-unit`. The documented baseline red set is ~11-12 known failures (2 USD-normalize, `test_tool_ack` flaky, vieneu_vllm, 2 qdrant_adapter, qdrant_store, prompt_builder, send_media local-.env, project_financial_mongo). "Zero new failures" is measured against that baseline, minus tests this plan deliberately deletes/repoints.
- Live PG gate (Tasks 3, 12): the `sp-e-postgres` docker + `POSTGRES_ADMIN_DSN`, same harness as `tests/integration/tenant/test_pg_rls_live.py` / `test_pg_data_plane_live.py`. Guard live tests behind the same env var those use.

**Red-window note:** Tasks 2→7 form one atomic cutover — the unit suite is RED from Task 2 until the wiring lands in Task 7 (legacy providers deleted, factory/config flipped to `pg_kb`). Each task in that window is still an independently reviewable diff; the full green gate is validated at the END of Task 7. Do not expect `make test-unit` green mid-window.

---

## File Structure

**Created:**
- `src/noble_agent/storage/sql/kb_real_estate.sql` — DDL for the 5 KB tables (Task 1).
- `src/noble_agent/data/providers/postgres_kb.py` — `PostgresKBProvider` (Tasks 3, 8).
- `src/noble_agent/agent/tools/get_document.py` — new `get_document` tool (Task 6).
- `tests/unit/unified/providers/test_postgres_kb_provider.py` — provider unit tests (Task 3).
- `tests/unit/unified/test_get_document.py` — tool test (Task 6).
- `tests/integration/tenant/test_kb_pg_live.py` — live schema/RLS/roundtrip + cross-tenant isolation (Tasks 1, 12).

**Modified:**
- `src/noble_agent/data/providers/base.py` — reshaped DTOs + query objects, remove extras/pricing (Task 2).
- `src/noble_agent/data/providers/_serialize.py` — thinned, new keys (Task 4).
- `src/noble_agent/data/providers/__init__.py` — `pg_kb` branch, drop `active_extra_specs`/`active_tool_params`, drop legacy branches (Tasks 3, 7).
- `src/noble_agent/agent/tools/projects_info.py` — remap discover/overview/recommend to new fields (Task 5).
- `src/noble_agent/agent/tools/check_inventory.py` — unchanged call, serializer changes only (Task 4).
- `src/noble_agent/agent/tools/schemas.py` — remove `get_project_financial`, add `get_document`, remap `search_units`/`discover_projects`, standardize enums, drop `active_tool_params` import + simplify `build_schemas` (Task 7).
- `src/noble_agent/agent/tools/builtins.py` — drop `get_project_financial`, add `get_document`, move `search_units` executor (Task 7).
- `src/noble_agent/tenants/noble/manifest.toml` (+ `data/tenants/noble/manifest.toml`) — `data_source = "pg_kb"`, tool list swap (Task 7).
- `src/noble_agent/config.py` — `noble_data_source` default `pg_kb`, remove `nbx_sales_api_*` (Task 7).
- `src/noble_agent/agent/orchestrator.py` — drop the extras-appendix block (Task 2).
- `src/noble_agent/agent/prompts/builder.py` — drop `render_extras_appendix` (Task 2).
- `src/noble_agent/tenants/noble/persona/RULES.md` (+ materialized copy) — tool-catalog rewrite (Task 9).

**Deleted:**
- `src/noble_agent/data/providers/{mongo,nbx_mongo,sales_api,_name_code_map}.py` (Task 7).
- `src/noble_agent/data/providers/base.py` pricing DTOs + `ExtraFieldSpec`/`ToolParamSpec` (Task 2).
- `src/noble_agent/agent/tools/custom_params.py`, `agent/tools/project_financial.py` (Task 7).
- `tests/unit/unified/providers/test_{mongo_provider,nbx_mongo_provider,sales_api_provider,sales_api_dns,extras}.py`, `test_project_financial_mongo.py`, and extras/custom-param tests (Task 7).

---

## Task 1: KB Postgres schema DDL

**Files:**
- Create: `src/noble_agent/storage/sql/kb_real_estate.sql`
- Modify: `src/noble_agent/tenant/pg_provisioning.py` (add the KB file to `apply_schema`)
- Test: `tests/integration/tenant/test_kb_pg_live.py`

**Interfaces:**
- Produces: schema `tenant_data` gains tables `projects`, `zones`, `units`, `documents`, `media`, each RLS-forced with policies `tenant_isolation` + `agent_runtime`. `apply_schema` applies BOTH `odyssey_data_plane.sql` and `kb_real_estate.sql`.

- [ ] **Step 1: Read the existing apply path.** Read `src/noble_agent/tenant/pg_provisioning.py::apply_schema` to see how it loads `odyssey_data_plane.sql` (a path read + `conn.execute`). Note the exact loader so Step 3 mirrors it.

- [ ] **Step 2: Write the DDL file** `src/noble_agent/storage/sql/kb_real_estate.sql`:

```sql
-- SP1 KB data plane (real_estate). Applied by `noble-tenant pg-apply-schema` (admin DSN).
-- Shared schema + per-row tenant isolation via RLS. Idempotent. Mirrors odyssey_data_plane.sql
-- RLS shape: tenant_isolation (current_user, Portal) + agent_runtime (app.current_tenant, runtime).
CREATE SCHEMA IF NOT EXISTS tenant_data;

CREATE TABLE IF NOT EXISTS tenant_data.projects (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id            text        NOT NULL,
    project_code         text        NOT NULL,
    name                 text        NOT NULL DEFAULT '',
    category             text[]      NOT NULL DEFAULT '{}',
    region               text,
    address              text,
    investor             text,
    developer            text,
    total_land_area_m2   numeric,
    floor_area_m2        numeric,
    build_density_pct    numeric,
    product_scale        text,
    amenities            text,
    ownership_form       text,
    handover_standard    text,
    total_investment_vnd bigint,
    sale_phase           text,
    overview             text,
    cover_media_id       bigint,   -- soft ref to media.id (no hard FK: media<->project cycle)
    map_media_id         bigint,   -- soft ref to media.id
    link_360             text,
    status               text        NOT NULL DEFAULT 'draft',
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_code)
);
CREATE INDEX IF NOT EXISTS projects_tenant_status_idx ON tenant_data.projects (tenant_id, status);

CREATE TABLE IF NOT EXISTS tenant_data.zones (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     text        NOT NULL,
    project_code  text        NOT NULL,
    zone_code     text        NOT NULL,
    name          text        NOT NULL DEFAULT '',
    category      text,
    product_scale text,
    overview      text,
    cover_media_id bigint,
    map_media_id   bigint,
    status        text        NOT NULL DEFAULT 'draft',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_code, zone_code),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS zones_tenant_project_idx ON tenant_data.zones (tenant_id, project_code);

CREATE TABLE IF NOT EXISTS tenant_data.units (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         text        NOT NULL,
    project_code      text        NOT NULL,
    zone_code         text,
    unit_code         text        NOT NULL DEFAULT '',
    product_type      text,
    bedrooms          smallint,
    block             text,
    floor             smallint,
    num_floors        smallint,
    direction         text,
    area_built_m2     numeric,
    area_wall_m2      numeric,
    area_land_m2      numeric,
    price_vnd         numeric,
    price_per_m2_vnd  numeric,
    sale_status       text        NOT NULL DEFAULT 'available',
    image_url         text,
    status            text        NOT NULL DEFAULT 'draft',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS units_tenant_project_idx ON tenant_data.units (tenant_id, project_code);
CREATE INDEX IF NOT EXISTS units_tenant_project_code_idx ON tenant_data.units (tenant_id, project_code, unit_code);

CREATE TABLE IF NOT EXISTS tenant_data.documents (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    text        NOT NULL,
    project_code text        NOT NULL,
    title        text        NOT NULL DEFAULT '',
    body         text        NOT NULL DEFAULT '',
    file_url     text,
    status       text        NOT NULL DEFAULT 'draft',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS documents_tenant_project_idx ON tenant_data.documents (tenant_id, project_code);

CREATE TABLE IF NOT EXISTS tenant_data.media (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    text        NOT NULL,
    project_code text        NOT NULL,
    zone_code    text,
    unit_code    text,
    content_type text        NOT NULL DEFAULT 'image',
    category     text,
    caption      text,
    media_url    text        NOT NULL DEFAULT '',
    thumb_url    text,
    content_hash text,
    uploaded_by  text,
    status       text        NOT NULL DEFAULT 'draft',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS media_tenant_project_cat_idx ON tenant_data.media (tenant_id, project_code, category);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['projects','zones','units','documents','media'] LOOP
        EXECUTE format('ALTER TABLE tenant_data.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE tenant_data.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON tenant_data.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON tenant_data.%I '
            'USING (tenant_id = current_user) WITH CHECK (tenant_id = current_user)', t);
        EXECUTE format('DROP POLICY IF EXISTS agent_runtime ON tenant_data.%I', t);
        EXECUTE format(
            'CREATE POLICY agent_runtime ON tenant_data.%I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))', t);
    END LOOP;
END $$;
```

- [ ] **Step 3: Wire it into `apply_schema`.** In `tenant/pg_provisioning.py`, wherever `odyssey_data_plane.sql` is read and executed, apply `kb_real_estate.sql` right after using the identical loader (read the sibling file, `await conn.execute(sql)`). Keep both idempotent so re-runs are safe.

- [ ] **Step 4: Write a live schema/RLS test** `tests/integration/tenant/test_kb_pg_live.py` (guarded by the same env var as `test_pg_rls_live.py`; skip when unset):

```python
import os
import pytest
import asyncpg

ADMIN_DSN = os.environ.get("SPE_PG_ADMIN_DSN")
pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="live PG admin DSN not set")


@pytest.mark.asyncio
async def test_kb_schema_applies_and_rls_scopes():
    from noble_agent.tenant import pg_provisioning
    await pg_provisioning.apply_schema(ADMIN_DSN)  # idempotent, applies both SQL files
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        # app_role path: set tenant, insert, and confirm the other tenant sees 0.
        await conn.execute("SELECT set_config('app.current_tenant', 'ta', true)")
        # (full insert/read/isolation asserted in Task 12 via the shared app role;
        #  here just prove the tables + policies exist)
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='tenant_data' "
            "AND tablename = ANY($1)", ['projects', 'zones', 'units', 'documents', 'media'])
        assert {r['tablename'] for r in rows} == {'projects', 'zones', 'units', 'documents', 'media'}
    finally:
        await conn.close()
```

- [ ] **Step 5: Run it (if docker PG available).** `SPE_PG_ADMIN_DSN=... pytest tests/integration/tenant/test_kb_pg_live.py -v`. Expected: PASS (or SKIP if no DSN). Also confirm re-running `apply_schema` twice does not error (idempotency).

- [ ] **Step 6: Commit.**
```bash
git add src/noble_agent/storage/sql/kb_real_estate.sql src/noble_agent/tenant/pg_provisioning.py tests/integration/tenant/test_kb_pg_live.py
git commit -m "feat(kb): SP1 Postgres KB schema (projects/zones/units/documents/media) + RLS"
```

---

## Task 2: Reshape canonical DTOs (base.py) + drop extras/pricing plumbing  *(red window starts)*

**Files:**
- Modify: `src/noble_agent/data/providers/base.py`
- Modify: `src/noble_agent/agent/orchestrator.py:195-200` (remove extras-appendix block)
- Modify: `src/noble_agent/agent/prompts/builder.py` (remove `render_extras_appendix`)
- Test: `tests/unit/unified/providers/test_base_contract.py` (repoint to new DTOs)

**Interfaces:**
- Produces (new DTO field names later tasks consume):
  - `Unit(project_code, project_name, zone_code, unit_code, product_type, bedrooms, block, floor, num_floors, direction, area_built_m2, area_wall_m2, area_land_m2, price_vnd, price_per_m2_vnd, sale_status, image_url)`
  - `ProjectOverview(code, name, region, address, investor, developer, total_land_area_m2, floor_area_m2, build_density_pct, product_scale, amenities, ownership_form, handover_standard, total_investment_vnd, sale_phase, overview, link_360)`
  - `ProjectSummary(code, name, region, category: tuple[str,...], investor, price_from_vnd, sale_phase)`
  - `Document(project_code, title, body, file_url)`
  - `UnitQuery(project_code, product_type, max_price_vnd, direction, floor, block, unit_code, sale_status, min_area_built_m2)`
  - `DiscoverQuery(region, budget_max_vnd, product_type, purpose, investor, sale_phase, offset, limit)`
  - `RecommendQuery` unchanged.
  - `DataProvider` Protocol loses `get_pricing/get_payment_plans/get_loan_policies/get_promotions/get_project_fees/extra_specs/tool_params`; gains `get_document(project_code, query="") -> list[Document] | None`.
  - Module keeps: `ESCALATE_SIGNAL`, `Capability` (trim `PRICING/PAYMENT_PLANS/LOAN_POLICIES/PROMOTIONS/FEES`), `ProjectList`, `ProjectDiscovery`, `InventorySummary`+`InventoryByType`+`InventoryByDirection`, `UnitRecommendation`, `ProjectRegistryRow`.

- [ ] **Step 1: Write the new base.py.** Replace the DTOs/query objects/Protocol per the Interfaces block. Delete `ExtraFieldSpec`, `ToolParamSpec`, `EXTRA_UNIT_SUFFIX`, `UnitTypePricing`, `PricingTable`, and the removed `extras` fields. Add `InventoryByProductType`? No — keep `InventoryByType` (rename its semantic to product_type at serializer level). Add the `Document` dataclass. Trim `Capability`.

- [ ] **Step 2: Update the base-contract test.** In `test_base_contract.py`, replace assertions referencing removed fields (`area_m2`, `extras`, `UnitTypePricing`, pricing methods) with the new field names; assert a `Unit(**minimal)` constructs and `Document` exists. Add: `assert not hasattr(base, "ExtraFieldSpec")`.

- [ ] **Step 3: Remove the extras-appendix wiring.** In `agent/orchestrator.py` delete the block (≈ lines 195-200):
```python
from noble_agent.data.providers import active_extra_specs
appendix = render_extras_appendix(active_extra_specs().values())
```
and any use of `appendix`. In `agent/prompts/builder.py` delete `render_extras_appendix` and any `EXTRA_UNIT_SUFFIX` import.

- [ ] **Step 4: Run the base test.** `pytest tests/unit/unified/providers/test_base_contract.py -v`. Expected: PASS. (The wider suite is red now — that's the atomic window; do not run `make test-unit` yet.)

- [ ] **Step 5: Commit.**
```bash
git add src/noble_agent/data/providers/base.py src/noble_agent/agent/orchestrator.py src/noble_agent/agent/prompts/builder.py tests/unit/unified/providers/test_base_contract.py
git commit -m "refactor(kb): reshape canonical DTOs to standardized schema; drop extras/pricing DTOs (red window)"
```

---

## Task 3: PostgresKBProvider — roster + projects (list/overview/discover)  *(red window)*

**Files:**
- Create: `src/noble_agent/data/providers/postgres_kb.py`
- Test: `tests/unit/unified/providers/test_postgres_kb_provider.py`

**Interfaces:**
- Consumes: reshaped DTOs (Task 2); `storage.postgres_client.get_pool`, `tenant_conn`; `noble_agent.tenant.current.current_tenant`.
- Produces: `PostgresKBProvider` with `name="pg_kb"`, implementing the full `DataProvider` Protocol. Unit-tests inject a fake connection via a constructor hook `PostgresKBProvider(_conn_factory=...)`.

- [ ] **Step 1: Write the failing roster test.** Use a fake asyncpg-like connection returning canned rows.

```python
import pytest
from noble_agent.data.providers.postgres_kb import PostgresKBProvider


class _FakeConn:
    def __init__(self, rows): self._rows = rows
    async def fetch(self, sql, *args): return self._rows.get("fetch", [])
    async def fetchrow(self, sql, *args): return self._rows.get("fetchrow")


def _provider(rows):
    p = PostgresKBProvider()
    p._acquire = lambda: _FakeCtx(_FakeConn(rows))  # test hook (see Step 3)
    return p


class _FakeCtx:
    def __init__(self, conn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


@pytest.mark.asyncio
async def test_warm_and_cached_codes():
    p = _provider({"fetch": [
        {"project_code": "NPLB", "name": "Noble Palace Long Biên", "region": "Long Biên", "category": ["biet_thu"]},
    ]})
    await p.warm()
    assert p.cached_codes() == ["NPLB"]
    assert p.code_to_name()["NPLB"] == "Noble Palace Long Biên"
    assert p.registry_rows()[0].region == "Long Biên"
```

- [ ] **Step 2: Run it.** `pytest tests/unit/unified/providers/test_postgres_kb_provider.py::test_warm_and_cached_codes -v` → FAIL (module missing).

- [ ] **Step 3: Implement the provider core.**

```python
"""PostgresKBProvider — native reader of the SP1 KB schema (tenant_data.*).

Reads projects/zones/units/documents/media directly and maps rows 1:1 onto the
canonical DTOs — no translation shim. Every read is scoped to the current tenant
by `tenant_conn` + the RLS `agent_runtime` policy. Roster (warm/cached_codes/
registry_rows) comes from `projects` (published, minus the `__ALL__` sentinel).
"""
from __future__ import annotations

import time

from noble_agent.data.providers import base
from noble_agent.tenant.current import current_tenant

_SENTINEL = "__ALL__"


class PostgresKBProvider:
    name = "pg_kb"
    capabilities = frozenset({
        base.Capability.LISTING, base.Capability.OVERVIEW, base.Capability.UNIT_SEARCH,
        base.Capability.RECOMMEND, base.Capability.INVENTORY,
    })

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._last_warm = 0.0

    def _acquire(self):
        """Async CM yielding a tenant-scoped connection. Overridden in tests."""
        from noble_agent.storage import postgres_client

        async def _ctx():
            pool = await postgres_client.get_pool()
            return postgres_client.tenant_conn(pool, current_tenant())
        return _LazyCtx(_ctx())

    # ---- roster ----
    async def warm(self) -> None:
        try:
            async with self._acquire() as conn:
                rows = await conn.fetch(
                    "SELECT project_code, name, region, category FROM tenant_data.projects "
                    "WHERE status='published' AND project_code <> $1", _SENTINEL)
            self._rows = {
                r["project_code"]: {
                    "code": r["project_code"], "name": r["name"] or "",
                    "region": r["region"] or "",
                    "type": (r["category"][0] if r["category"] else ""),
                } for r in rows
            }
        except Exception:
            pass  # keep prior cache; log-and-continue (roster is best-effort)
        self._last_warm = time.monotonic()

    async def warm_if_stale(self, ttl_sec: float) -> None:
        if ttl_sec <= 0 or (time.monotonic() - self._last_warm) > ttl_sec:
            await self.warm()

    def cached_codes(self) -> list[str]:
        return list(self._rows)

    def code_to_name(self) -> dict[str, str]:
        return {c: v["name"] for c, v in self._rows.items()}

    def registry_rows(self) -> list[base.ProjectRegistryRow]:
        return [base.ProjectRegistryRow(code=v["code"], name=v["name"], region=v["region"], type=v["type"])
                for v in self._rows.values()]
```

Add a small `_LazyCtx` helper that awaits the coroutine returning the real async-CM and delegates `__aenter__/__aexit__` (so `_acquire()` can be sync-called and used in `async with`). In tests, `_acquire` is replaced with a lambda returning `_FakeCtx`.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Add list_projects / get_overview / discover_projects tests + impl.**

```python
@pytest.mark.asyncio
async def test_get_overview_maps_fields():
    p = _provider({"fetchrow": {
        "project_code": "NPLB", "name": "Noble Palace", "region": "Long Biên", "address": "Số 1",
        "investor": "Noble", "developer": "Noble Dev", "total_land_area_m2": 120000,
        "floor_area_m2": 450000, "build_density_pct": 21, "product_scale": "2400 sp",
        "amenities": "Bể bơi", "ownership_form": "Lâu dài", "handover_standard": "Thô",
        "total_investment_vnd": 35000000000000, "sale_phase": "dang_ban",
        "overview": "Đại đô thị", "link_360": "kuula.co/x",
    }})
    ov = await p.get_overview("NPLB")
    assert ov.total_land_area_m2 == 120000 and ov.sale_phase == "dang_ban" and ov.investor == "Noble"
```

Implement `get_overview` (`SELECT ... FROM tenant_data.projects WHERE project_code=$1 AND status='published'`, resolve alias via `base`-level normalization if desired; return `None` when no row). Implement `list_projects(region)` and `discover_projects(query)`:
- discover: `WHERE status='published' AND project_code <> '__ALL__'` + optional `region ILIKE`, `product_type` via `category && ARRAY[...]` or a units join, `investor ILIKE`, `sale_phase =`. For `price_from_vnd` and `budget_max_vnd`, LEFT JOIN a subquery `SELECT project_code, min(price_vnd) pf FROM tenant_data.units WHERE status='published' GROUP BY project_code`; filter `pf <= budget_max_vnd` when `budget_max_vnd>0`. Rank ORDER BY `array_position(ARRAY['dang_ban','sap_mo_ban','ban_giao','dong_gio_hang'], sale_phase)` NULLS LAST, then `name`. Return `ProjectDiscovery(total=<count before slice>, projects=<sliced ProjectSummary>)`.

- [ ] **Step 6: Run the project tests → PASS. Commit.**
```bash
git add src/noble_agent/data/providers/postgres_kb.py tests/unit/unified/providers/test_postgres_kb_provider.py
git commit -m "feat(kb): PostgresKBProvider roster + list/overview/discover (red window)"
```

---

## Task 4: PostgresKBProvider — units (search/recommend/inventory) + get_document  *(red window)*

**Files:**
- Modify: `src/noble_agent/data/providers/postgres_kb.py`
- Test: `tests/unit/unified/providers/test_postgres_kb_provider.py`

**Interfaces:**
- Produces: `search_units(UnitQuery)->list[Unit]|None`, `recommend_units(RecommendQuery)->UnitRecommendation|None`, `get_inventory_summary(project_code)->InventorySummary|None`, `get_document(project_code, query="")->list[Document]|None`.

- [ ] **Step 1: Failing search_units test** (fake rows → `Unit` with new fields; assert `product_type`, `area_built_m2`, `sale_status`, `block` mapped; filters passed to SQL are exercised by asserting the provider builds the WHERE from `UnitQuery`). Then implement:
  - `search_units`: `SELECT u.*, p.name project_name FROM tenant_data.units u JOIN tenant_data.projects p USING (tenant_id, project_code) WHERE p.status='published' AND u.status='published' AND u.project_code=$1` + optional `product_type=`, `price_vnd<=max`, `direction=`, `floor=`, `block=`, `unit_code=`, `sale_status=` (default 'available'), `area_built_m2>=min`. Map each row → `Unit(...)`. Empty → `None`.
  - `recommend_units`: cross-project (or `project_code`-scoped) `WHERE` on `region`(join project.region ILIKE), `price_vnd<=budget`, `bedrooms=`; return RAW unsorted `UnitRecommendation(units=[...])` (tool sorts feng-shui-first).
  - `get_inventory_summary`: aggregate `count(*) total`, `count(*) FILTER (WHERE sale_status='available') available`, group-by `product_type`, group-by `direction` (available only). Return `InventorySummary`. No units → `None`.
  - `get_document`: `SELECT title, body, file_url FROM tenant_data.documents WHERE status='published' AND project_code = ANY($1)` with `$1 = [project_code, '__ALL__']`; optional `query` → `AND (title ILIKE %q% OR body ILIKE %q%)`. Return `list[Document]` (may be empty list — NOT None; the tool decides escalate on empty).

- [ ] **Step 2: Run each new test → PASS.**

- [ ] **Step 3: Commit.**
```bash
git add src/noble_agent/data/providers/postgres_kb.py tests/unit/unified/providers/test_postgres_kb_provider.py
git commit -m "feat(kb): PostgresKBProvider units (search/recommend/inventory) + get_document (red window)"
```

---

## Task 5: Serializer + tool remaps to new fields  *(red window)*

**Files:**
- Modify: `src/noble_agent/data/providers/_serialize.py`
- Modify: `src/noble_agent/agent/tools/projects_info.py`
- Test: `tests/unit/unified/providers/test_serialize.py`

**Interfaces:**
- Produces: `unit_json`, `overview_json`, `discover_project_json`, `inventory_json` emitting the NEW standardized keys; `projects_info.recommend_units` reading new `Unit` fields.

- [ ] **Step 1: Rewrite the serialize tests** to expect the new keys, e.g.:
```python
def test_unit_json_new_keys():
    from noble_agent.data.providers import base, _serialize as ser
    u = base.Unit(project_code="NPLB", project_name="Noble Palace", zone_code="RIVER",
                  unit_code="S3.06.08", product_type="chung_cu", bedrooms=3, block="S3",
                  floor=6, num_floors=None, direction="dong_nam", area_built_m2=78.4,
                  area_wall_m2=85.2, area_land_m2=None, price_vnd=5_620_000_000,
                  price_per_m2_vnd=71_000_000, sale_status="available", image_url="")
    j = ser.unit_json(u)
    assert j["product_type"] == "chung_cu" and j["area_built_m2"] == 78.4
    assert j["sale_status"] == "available" and j["block"] == "S3"
    assert "clear_area_m2" not in j and "max_discount_pct" not in j
```

- [ ] **Step 2: Thin `_serialize.py`.** Drop `labeled_extras`/`active_extra_specs` import. New `unit_json`:
```python
def unit_json(u):
    return {
        "unit_code": u.unit_code, "product_type": u.product_type, "bedrooms": u.bedrooms,
        "direction": u.direction or "", "block": u.block or "", "floor": u.floor,
        "num_floors": u.num_floors, "area_built_m2": u.area_built_m2,
        "area_wall_m2": u.area_wall_m2, "area_land_m2": u.area_land_m2,
        "price_vnd": u.price_vnd, "price_per_m2_vnd": u.price_per_m2_vnd,
        "sale_status": u.sale_status, "image_url": u.image_url or "",
        "project_code": u.project_code, "project_name": u.project_name,
    }
```
Rewrite `overview_json` (region/address/investor/developer/total_land_area_m2/floor_area_m2/build_density_pct/product_scale/amenities/ownership_form/handover_standard/total_investment_vnd/sale_phase/overview/link_360), `discover_project_json` (code/name/region/category/investor/price_from_vnd/sale_phase — drop `hot`, `type`), `inventory_json` (`by_product_type` instead of `by_unit_type`). Delete `pricing_json`/`_unit_type_pricing_json`/`project_list_json` extras usage.

- [ ] **Step 3: Remap `projects_info.py`.** In `discover_projects`, drop `budget_max` from `_NARROW_AXES`? Keep it (still an axis). In `recommend_units`, change the per-unit dict build to new fields:
```python
units.append({
    "unit_code": u.unit_code, "product_type": u.product_type, "bedrooms": u.bedrooms,
    "area_built_m2": u.area_built_m2, "direction": u.direction or "",
    "price_vnd": u.price_vnd, "price_per_m2_vnd": u.price_per_m2_vnd,
    "project_code": u.project_code, "project_name": u.project_name,
    "feng_shui_match": fs_match, "direction_label": "hợp hướng" if fs_match else "",
})
```
Sort key uses `u.price_vnd` (unchanged). `get_project_overview` passes through the serializer (no field refs). `discover_projects` builds `DiscoverQuery(..., sale_phase=args.get("sale_phase","") or "")`.

- [ ] **Step 4: Run serialize + projects_info tests → PASS. Commit.**
```bash
git add src/noble_agent/data/providers/_serialize.py src/noble_agent/agent/tools/projects_info.py tests/unit/unified/providers/test_serialize.py
git commit -m "refactor(kb): thin serializer to standardized keys; remap projects_info (red window)"
```

---

## Task 6: New `get_document` tool  *(red window)*

**Files:**
- Create: `src/noble_agent/agent/tools/get_document.py`
- Test: `tests/unit/unified/test_get_document.py`

**Interfaces:**
- Consumes: `provider.get_document`.
- Produces: `get_document.run(args) -> str` (JSON). Registered in Task 7.

- [ ] **Step 1: Failing test.**
```python
import json, pytest
from noble_agent.agent.tools import get_document
from noble_agent.data.providers import base


class _P:
    async def get_document(self, code, query=""):
        return [base.Document(project_code="NPLB", title="CSBH Q3", body="Tiến độ...", file_url="acme/csbh.pdf")]


@pytest.mark.asyncio
async def test_get_document_returns_file(monkeypatch):
    monkeypatch.setattr("noble_agent.data.providers.get_provider", lambda s: _P())
    out = json.loads(await get_document.run({"project_code": "NPLB", "query": "CSBH"}))
    assert out["documents"][0]["file_url"] == "acme/csbh.pdf"
    assert out["count"] == 1
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement.**
```python
"""get_document — fetch a project's document (title/body/file_url) so Luna can
hand the customer a real file (CSBH/legal PDF). Reads tenant_data.documents via
the provider (scope = project_code + the '__ALL__' tenant-wide sentinel).
Empty result → ESCALATE_SIGNAL (hand off)."""
from __future__ import annotations
import json
from noble_agent.config import get_settings
from noble_agent.data import providers
from noble_agent.data.providers.base import ESCALATE_SIGNAL


async def run(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    docs = await provider.get_document(args.get("project_code", "") or "", args.get("query", "") or "")
    if not docs:
        return ESCALATE_SIGNAL
    return json.dumps({
        "count": len(docs),
        "documents": [{"title": d.title, "body": d.body[:800], "file_url": d.file_url} for d in docs],
    }, ensure_ascii=False)
```

- [ ] **Step 4: Run → PASS. Commit.**
```bash
git add src/noble_agent/agent/tools/get_document.py tests/unit/unified/test_get_document.py
git commit -m "feat(kb): get_document tool (red window)"
```

---

## Task 7: Wiring cutover — schemas, builtins, factory, config, manifest; delete legacy  *(red window ENDS — full gate)*

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py`, `builtins.py`
- Modify: `src/noble_agent/data/providers/__init__.py`, `config.py`
- Modify: `src/noble_agent/tenants/noble/manifest.toml` (+ `data/tenants/noble/manifest.toml`)
- Delete: `data/providers/{mongo,nbx_mongo,sales_api,_name_code_map}.py`, `agent/tools/{project_financial,custom_params}.py`, and their tests.

**Interfaces:**
- Consumes: everything from Tasks 2-6.
- Produces: a GREEN unit suite with `pg_kb` as the sole provider, `get_project_financial` gone, `get_document` offered.

- [ ] **Step 1: schemas.py.** Delete the `get_project_financial` schema entry. Add a `get_document` schema (params: `project_code` string, `query` string optional; required `["project_code"]`; description: "Lấy file tài liệu/CSBH/pháp lý của dự án (trả title/nội dung/link file). Dùng khi khách xin file hoặc hỏi chính sách bán hàng/pháp lý."). In `search_units` schema: rename `unit_type`→`product_type` (enum = the 12 `units.product_type` values), `min_area`→`min_area`(keep name, doc "diện tích thông thủy m²"), `tower`→`block`, `status`→`sale_status` (enum `available|booked|sold`), `direction` enum = the 8 `02a` values. In `discover_projects`: add `sale_phase` enum (`sap_mo_ban|dang_ban|ban_giao|dong_gio_hang`); `product_type` enum stays the project `category` set. Remove the `from noble_agent.data.providers import active_tool_params` import (line 13) and delete the "inject Tier-2 custom params" block in `build_schemas` (Steps 1 of that block) — keep the feng-shui-ranker gate + brand render.

- [ ] **Step 2: builtins.py.** Remove the `_get_project_financial` adapter + its `_BUILTINS` row. Move `search_units` executor: it now lives in `projects_info` or a small `unit_search.py` (since `project_financial.py` is deleted). Simplest: add `async def search_units(args)` to `projects_info.py` (calls `provider.search_units(UnitQuery(...))` with new fields, `ser.unit_json`), and point `_search_units` at it. Add `_get_document` adapter + `_BUILTINS` row `("get_document", _get_document, False, True)`; add its import.

```python
async def _get_document(args, *, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await get_document.run(args)
```

- [ ] **Step 3: factory + config.** In `data/providers/__init__.py`: add branch `elif source == "pg_kb": from ...postgres_kb import PostgresKBProvider; provider = PostgresKBProvider()`. Delete the `mongo`/`nbx`/`sales_api` branches. Delete `active_extra_specs` + `active_tool_params` functions and drop them from `__all__`. In `config.py`: `noble_data_source` default → `"pg_kb"`; delete `nbx_sales_api_url/timeout/token`.

- [ ] **Step 4: manifest.** In BOTH `src/noble_agent/tenants/noble/manifest.toml` and `data/tenants/noble/manifest.toml`: `data_source = "pg_kb"`; in `[tools].enabled` remove nothing for financial (it wasn't listed) but the noble list does not include `get_project_financial` (confirm) and ADD `"get_document"`. (Note: the noble manifest's enabled list currently has `service_customer`, not `crm_lookup`/etc. — only add `get_document`.)

- [ ] **Step 5: Delete legacy providers + tools + their tests.**
```bash
git rm src/noble_agent/data/providers/mongo.py src/noble_agent/data/providers/nbx_mongo.py \
       src/noble_agent/data/providers/sales_api.py src/noble_agent/data/providers/_name_code_map.py \
       src/noble_agent/agent/tools/project_financial.py src/noble_agent/agent/tools/custom_params.py \
       tests/unit/unified/providers/test_mongo_provider.py tests/unit/unified/providers/test_nbx_mongo_provider.py \
       tests/unit/unified/providers/test_sales_api_provider.py tests/unit/unified/providers/test_sales_api_dns.py \
       tests/unit/unified/providers/test_extras.py tests/unit/unified/test_project_financial_mongo.py
```
Also grep for and delete/repoint any remaining custom-param / build_schemas-injection tests (`grep -rln 'active_tool_params\|active_extra_specs\|custom_params\|get_project_financial\|UnitTypePricing' tests/`). Repoint `test_factory.py`/`test_source_switch.py` to `pg_kb`. Repoint `db_project_registry`/`find_project` tests to the pg roster (they use `set_cache_for_tests`, so likely unaffected — verify).

- [ ] **Step 6: Run the FULL gate.** `make test-unit`. Expected: green except the documented baseline; ZERO new failures beyond baseline (minus the deleted tests). Fix any fallout (imports of deleted symbols, `agent/base.py` `build_schemas` still valid, `test_agent_def` tool-count now includes `get_document` and excludes nothing financial). Then `make lint` on touched files (0 new).

- [ ] **Step 7: Commit.**
```bash
git add -A
git commit -m "refactor(kb): cut over to pg_kb provider; remove get_project_financial + legacy providers; add get_document (gate green)"
```

---

## Task 8: `catalog.py` reconciliation guard

**Files:**
- Modify: `src/noble_agent/agent/catalog.py` (only if needed)
- Test: `tests/unit/unified/test_catalog*.py`

**Interfaces:**
- Produces: `catalog.normalize` accepts any live `pg_kb` code (via the existing `db_project_registry.cached_codes()` fallback).

- [ ] **Step 1: Verify the fallback path.** Read `catalog.normalize` — confirm it consults `db_project_registry.cached_codes()` after its hardcoded alias map (the 2026-07-06 change). If so, no code change is needed for SP1: the migrated codes validate via the provider cache. Add/adjust a test asserting a non-hardcoded code present in `cached_codes()` normalizes to itself.
- [ ] **Step 2:** Leave the 15 hardcoded Noble aliases in place (SP2 confirms the migrated code set; stripping them is a separate decision, spec §10.3). If `normalize` does NOT consult the provider cache, add that fallback now (mirror the existing DB-codes fallback).
- [ ] **Step 3:** Run `pytest tests/unit/unified/test_catalog_db_codes.py -v` → PASS. Commit.
```bash
git add src/noble_agent/agent/catalog.py tests/unit/unified/test_catalog_db_codes.py
git commit -m "test(kb): catalog.normalize accepts live pg_kb codes via provider cache"
```

---

## Task 9: RULES.md tool-catalog rewrite (prompt)

**Files:**
- Modify: `src/noble_agent/tenants/noble/persona/RULES.md` (+ `data/tenants/noble/persona/RULES.md`)

- [ ] **Step 1:** In the RULES tool-catalog section, remove the `get_project_financial` row. Add a `get_document` row ("khách xin file / hỏi CSBH-pháp lý → get_document trả link file; nội dung chính sách/giá vẫn trả lời qua kb_search"). Update the escalate-signal paragraph to list `get_document` alongside the other data tools. Update any JSON-key references so Luna reads `product_type`/`area_built_m2`/`sale_status`/`price_vnd` (the new serializer keys) instead of the old `clear_area_m2`/`type`/`status`. Route financial/pricing questions to `kb_search` (from CSBH documents) — add one line: "Giá/CSBH/thanh toán/pháp lý: trả lời qua kb_search (nội dung tài liệu), KHÔNG còn tool get_project_financial."
- [ ] **Step 2:** Keep the two RULES.md copies byte-identical (source + materialized). Confirm `test_agent_def` expectations for offered tools match the new manifest (`get_document` present, no financial).
- [ ] **Step 3:** Commit.
```bash
git add src/noble_agent/tenants/noble/persona/RULES.md data/tenants/noble/persona/RULES.md
git commit -m "docs(prompt): RULES tool catalog — drop get_project_financial, add get_document, new JSON keys"
```

---

## Task 10: Cross-tenant isolation live test + final gate

**Files:**
- Modify: `tests/integration/tenant/test_kb_pg_live.py`

**Interfaces:**
- Consumes: the applied schema (Task 1) + shared app role (existing `ensure_app_role`).

- [ ] **Step 1: Write the isolation + roundtrip test** (guarded, size-1 pool to force connection reuse — mirror `test_pg_rls_live.py::test_app_role_set_local_isolation_and_leak`): under `tenant_conn(pool,'ta')` insert a published project + unit; assert `PostgresKBProvider().get_overview` returns it for `ta`; re-scope the SAME pooled conn to `tb` and assert `get_overview` returns `None` and `search_units` returns `None` (0 rows — RLS isolation); re-scope back to `ta` and assert it reappears; assert an unset GUC yields 0 rows (fail-closed).
- [ ] **Step 2: Run** `SPE_PG_ADMIN_DSN=... POSTGRES_DSN=... pytest tests/integration/tenant/test_kb_pg_live.py -v` → PASS (or SKIP without DSN).
- [ ] **Step 3: Final full gate.** `make test-unit` (zero new failures vs baseline) + `make lint` (0 new on every touched file). Manual `SMOKE.md` items that touch the turn loop/prompt if PG data is available; otherwise note the smoke is deferred until SP2 populates data.
- [ ] **Step 4: Commit.**
```bash
git add tests/integration/tenant/test_kb_pg_live.py
git commit -m "test(kb): cross-tenant RLS isolation + roundtrip live gate for pg_kb"
```

---

## Self-Review

**Spec coverage:** §2 schema → Task 1. §3 provider → Tasks 3-4. §4 DTO reshape → Task 2. §5 serializer → Task 5. §6 tool surface (remove financial / add get_document / remaps / enums) → Tasks 5-7,9. §7 delete legacy → Task 7. §8 catalog → Task 8. §9 testing (provider/tool/cross-tenant/repoint) → Tasks 3-7,10. §10 open items: #1 schema wording (Task 7), #2 `__ALL__` seed (Task 1 seeds current tenant via provisioning — NOTE: add a `__ALL__` seed step to provisioning or the SQL for dev; see gap below), #3 catalog aliases (Task 8), #4 media FK cycle (Task 1 uses soft `bigint` ref — done), #5 live gate (Tasks 1,10).

**Gap found → fix:** The `__ALL__` seed row was described in the spec (§2 seed) but no task seeds it. **Add to Task 1, Step 2:** append to `kb_real_estate.sql` a dev seed for the current tenant is NOT possible in a tenant-agnostic DDL — instead add a one-line note in Task 1 and a `Step` in Task 10's live test to `INSERT ... ON CONFLICT DO NOTHING` a `__ALL__` published project per test tenant; production seeding belongs to the provisioning path (out of SP1 scope, flag for SP2/provisioning). Documents/media queries already union `'__ALL__'` (Task 4 get_document), which simply returns nothing until the row+docs exist — safe.

**Placeholder scan:** No TBD/TODO; every code step has real code or an exact edit spec.

**Type consistency:** `Unit`/`ProjectOverview`/`ProjectSummary`/`Document` field names are identical across Task 2 (definition), Task 3-4 (provider), Task 5 (serializer), Task 6 (get_document). `get_document(project_code, query="")` signature matches between base Protocol (Task 2), provider (Task 4), tool (Task 6), and builtins adapter (Task 7). `DiscoverQuery` gains `sale_phase` in Task 2 and is used in Task 5.
