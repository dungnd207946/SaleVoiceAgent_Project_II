# SaaS multi-tenant provider & tool layer — design

**Date:** 2026-07-23
**Branch:** `feat/refactor2` (proposed)
**Status:** Approved for planning

## Problem

The agent and its tools are coupled to a single provider (Noble). Even with the
existing per-provider adapter layer (`data/providers/`), there is a structural
mismatch: the canonical DTOs in `base.py` are a **fixed superset** of fields.
A new provider either lacks a field (→ `None`, wasted schema) or **has a field
the DTO cannot express** (e.g. a developer's tiered management fee, a smart-home
tier). On top of that, tools, prompt (persona "Luna"), brand strings ("Noble",
"app NobleX"), and VN-specific features (feng-shui) are hardcoded into the core.

**Goal (owner-of-agent viewpoint):** ship the agent + a standard tool set to many
providers. A provider brings their data/API. A developer's job shrinks to: write
**one adapter** + declare/write **custom fields, custom tool parameters, and
custom tools** for that provider — without touching core or other tenants.

## Decisions (locked during brainstorming)

1. **Tenancy:** one deploy, multi-tenant-ready code, **runtime one tenant per
   deploy** via `TENANT_ID` env. No DID→tenant table now; the whole config
   bundle resolves at boot.
2. **Field variance:** typed **extras bag + metadata declaration** (not DTO
   bloat, not free-text stuffing).
3. **Scope:** data tools + tenant config/persona. **Out of scope (unchanged):**
   `booking`, `escalate`, `crm_lookup`/`verify_identity`/`support_ticket`.
4. **Bundle organization:** **tenant package** — `tenants/<id>/` holds adapter +
   custom tools + manifest + persona, colocated and isolated.
5. **Extras output shape:** **Vietnamese label inline in JSON** (robust for
   weaker models, fewer tokens than a legend lookup).

## Architecture

Core (`src/noble_agent/`) knows only the canonical contract. Everything
provider-specific lives in `tenants/<id>/`, loaded by `TENANT_ID`.

```
src/noble_agent/
  data/providers/
    base.py              # canonical DTO (trimmed core) + ExtraFieldSpec + Protocol
    _serialize.py        # DTO -> JSON, renders core + extras from metadata
  agent/tools/
    registry.py          # NEW: ToolSpec registry (built-in + custom tools)
    schemas.py           # build_schemas(ctx) — dynamic per tenant (was a static dict)
  tenant/
    loader.py            # NEW: TENANT_ID -> import bundle -> TenantContext
    context.py           # NEW: TenantContext (frozen)

tenants/
  noble/
    manifest.toml        # adapter, enabled tools, extra_fields, tool_params,
                         # rankers, media_channel, [brand], persona_dir
    adapter.py           # (may reuse a built-in provider by name instead)
    tools/               # custom tool classes (self-register via decorator)
    persona/             # SOUL.md RULES.md PROMPT_TEMPLATE.md CUSTOMER_PROFILE.md
```

**Boot flow:** `loader.load(TENANT_ID)` → import `tenants/<id>/` (decorators
register the adapter + custom tools) → parse `manifest.toml` → build
`TenantContext { provider, tool_specs, extra_specs, tool_params, brand,
rankers, media_channel, persona_dir }`. `facade`/`orchestrator`/`builder`/
`dispatcher`/`schemas` all take `ctx` instead of hardcoded provider +
`agent/definitions/`.

## Part 1 — Core common-field schema + extras

A field is **core** only if virtually every real-estate source has it; otherwise
it is an **extra** declared per-tenant.

### Core `Project`
`code`, `name`, `region?`, `district?`, `category?`, `investor?`, `status?`,
`price_from_vnd?`, `description?`.

### Core `Unit`
`unit_code`, `unit_type` (label: "2PN"/"studio"/"shophouse"), `bedrooms?`,
`area_m2?`, `price_vnd?`, `price_per_m2_vnd?`, `direction?`, `floor?`, `block?`,
`status` (`available|sold|booked|unknown`).

### Moved to extras (Noble examples)
`wall_area_m2`, `price_early_vnd`, `price_progress_vnd`, `price_loan_vnd`,
`max_discount_pct`, `view`, `image_url`. **No data is dropped — only relocated.**

### Extras mechanism
```python
@dataclass(frozen=True)
class ExtraFieldSpec:
    key: str            # extras dict key, e.g. "price_early_vnd"
    label: str          # LLM/human label, e.g. "Giá thanh toán sớm"
    entity: str         # "unit" | "project" | "pricing"
    type: str           # "int"|"number"|"string"|"bool"|"enum"
    unit: str = ""      # "vnd"|"m2"|"pct"|"" — rendering + LLM understanding
    description: str = ""
    enum: tuple[str, ...] = ()

# Core DTOs gain ONE field each:
#   Unit.extras: dict[str, Any]   ProjectOverview.extras: dict[str, Any]
```

Extras flow to the LLM through three automatic channels:
1. **Adapter** fills `extras={"price_early_vnd": ...}` — core DTO untouched.
2. **Serializer** renders core + extras with the label inline (shape A):
   `{"unit_code": "A-1", "price_vnd": 5000000000, "Giá thanh toán sớm (đồng)": 4800000000}`.
3. **System prompt** auto-generates a "Trường dữ liệu bổ sung" appendix from
   `extra_specs` so the model understands each field's meaning.

Adding a provider field = one `[[extra_fields]]` block + a line in the adapter.
`base.py` core, `schemas.py`, and other tenants are untouched.

## Part 2 — Custom tool parameters (two tiers)

### Tier 1 — display extra (default, ~90%)
Customer does not filter on it. Touches only manifest + adapter + (auto)
serializer + (auto) prompt appendix. **No `schemas.py`/dispatcher/tool-input
change.**

### Tier 2 — filterable / custom parameter (opt-in)
Lets a provider add a **new input parameter** absent from the generic set, with
full description + type, auto-linked to the adapter.

```toml
# data field (Tier 1)
[[extra_fields]]
key = "payment_scheme"
label = "Phương án thanh toán"
entity = "unit"
type = "enum"
enum = ["som", "tien_do", "vay"]
description = "Phương án thanh toán áp dụng cho căn."

# new tool parameter (Tier 2) — auto-links to the field above
[[tool_params]]
tool = "search_units"
name = "payment_scheme"
type = "enum"
enum = ["som", "tien_do", "vay"]
description = "Phương án thanh toán khách muốn (sớm/tiến độ/vay). Chỉ truyền khi khách nêu rõ."
maps_to = "payment_scheme"      # key in unit.extras
match = "eq"                    # eq | substring | gte | lte | exists | contains
```

Framework does three things, no glue code:
1. **Schema build** — `build_schemas(ctx)` injects the param (description/type/
   enum) into the target tool's JSON schema; the LLM sees it like a native param.
2. **Dispatch** — the dispatcher collects any arg that is a declared custom param
   into `UnitQuery.custom_params: dict` (generic, no hardcoded name).
3. **Filter** — framework compares `unit.extras[maps_to]` to the value via
   `match`. **Adapter needs zero filter code** for declarative cases.

**Auto-link tiers:**
- Declarative (`maps_to` + `match` operator) → framework filters generically.
- Complex → adapter implements optional hook `apply_custom_filter(name, value,
  item) -> bool`. `query.custom_params` is always passed to the adapter too, so
  it may push filters server-side (optimization); the framework re-applies the
  declarative filter as a safety net, so a superset from the adapter is never
  wrong.

## Part 3 — Standard tool set, per-tenant gating, brand templating

**Group A — standard data tools (toggleable):** `find_project`,
`discover_projects`, `get_project_overview`, `get_project_financial`,
`search_units`, `check_inventory`, `recommend_units`, `kb_search` (renamed from
`noble_search` → brand-neutral).

**Group B — standard but region-specific → plugin:**
- `recommend_units`: the filter frame is standard; the **feng-shui overlay**
  (bát trạch/ngũ hành) becomes an **optional ranker plugin** (`rankers =
  ["feng_shui"]`). When off, its `birth_year/menh/zodiac` params drop from the
  schema.
- `send_media`: media content is provider data; the **delivery channel** (NobleX
  app) is infra → **channel abstraction** (`media_channel = "noblex_app" |
  "none" | custom`).

**Group C — out of scope (unchanged):** `booking`, `escalate`, and the
not-offered `crm_lookup`/`verify_identity`/`support_ticket`.

**Gating (`manifest.toml`):**
```toml
[tools]
enabled = ["find_project","discover_projects","get_project_overview",
           "get_project_financial","search_units","check_inventory",
           "recommend_units","kb_search","send_media","booking","escalate"]
rankers = ["feng_shui"]
media_channel = "noblex_app"
```
`build_schemas(ctx)` emits schemas only for `enabled`, injects `tool_params`, and
strips params of rankers/channels not enabled.

**Brand templating:** tool descriptions (and SOUL/RULES) use `{{ brand.company }}`
/ `{{ brand.app_name }}`, rendered at build time from `[brand]`. New providers
change two lines, not tool copy.

## Part 4 — Custom tools (entirely new capability) via registry

A provider-specific tool with its own executor (may call the provider's own API).

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict                       # JSON parameters (one SCHEMAS entry)
    executor: Callable[..., Awaitable[str]]
    dirties_customer: bool = False     # rebuild system prompt after run?
    read_only: bool = True             # semcache/sandbox classification

# executor signature (adds tenant context to the current tool signature):
async def execute(args, *, state, customer, callbacks, session_id, provider, tenant) -> str: ...
```

Registration (`tenants/noble/tools/check_loan.py`):
```python
from noble_agent.agent.tools.registry import tool

@tool(tenant="noble", name="check_loan_eligibility", schema={...}, read_only=True)
async def check_loan_eligibility(args, *, provider, tenant, **_):
    ...
    return "..."
```

**Registry unifies dispatch:**
- Standard tools are also `ToolSpec`s (built-in, `tenant="*"`); custom tools
  register under their tenant.
- `TenantContext` assembles `[standard ToolSpecs ∈ manifest.enabled] + [tenant's
  custom ToolSpecs]`.
- `dispatcher.py` changes from the if/elif chain to a registry lookup:
  `registry.resolve(tenant, name).executor(...)`. `_DIRTIES_CUSTOMER` → the
  `dirties_customer` flag; `_READ_ONLY_TOOLS` (semcache) → the `read_only` flag.

Adding a tool = one file in `tenants/<id>/tools/` + one line in `enabled`.

**Risk:** the dispatcher refactor touches the hot dispatch path — the current
invariants MUST be preserved: drop tool calls with empty `id`/`name`, inject
`{"interrupted": true}` placeholders on mid-loop interrupt, rebuild the system
prompt on customer-dirty. Covered by tests.

## Part 5 — Persona / prompt / brand per tenant

`agent/definitions/*` moves to `tenants/noble/persona/` (`SOUL.md`, `RULES.md`,
`PROMPT_TEMPLATE.md`, `CUSTOMER_PROFILE.md`). `config.json` (offered-tool list)
is **merged into `manifest.toml` `[tools].enabled`** — one source of truth.

`build_system_prompt(ctx, ...)` composes: `[SOUL + RULES with brand vars]` +
`[auto extras appendix]` + `[customer block]`. `load_agent_def(persona_dir)`
takes the directory from `TenantContext`; tool names come from
`manifest.enabled`.

## Part 6 — Loader / bootstrap / migration

**Load:** `TENANT_ID` → `tenant.loader.load(id)`: import `tenants/<id>/`
(decorators register adapter + custom tools) → read `manifest.toml` (adapter is a
built-in name `nbx`/`sales_api`/`mongo` **or** a class path; plus `enabled`,
`extra_fields`, `tool_params`, `rankers`, `media_channel`, `[brand]`,
persona_dir) → build frozen `TenantContext`.

**Core consumes it:** `get_tenant_context()` singleton (mirrors
`get_settings()`); `get_provider()` returns `ctx.provider` (adapter now declared
in the manifest — `NOBLE_DATA_SOURCE` folds into the manifest as a `data source`
field); `facade`/`orchestrator`/`builder`/`dispatcher`/`schemas` receive `ctx`;
existing bootstrap (warm registry, build `find_project` index) runs from `ctx`.

**Migration (Noble first; behaviour unchanged):** git-mv `agent/definitions/*` →
`tenants/noble/persona/`; keep `data/providers/nbx_mongo.py`, referenced via
`manifest adapter = "nbx"`; `manifest.enabled` = the current 12 tools; `rankers =
["feng_shui"]`; `media_channel = "noblex_app"`; `extra_fields` = the relocated
Noble fields; `[brand] company="Noble" app_name="NobleX"`. Deploy with
`TENANT_ID=noble` → runs exactly as today.

**Errors & rollout:** missing manifest / unknown tenant / adapter import failure
→ **fail loud at boot** (never silently serve empty). Phased rollout:
1. Infra: `registry` + `TenantContext` + extras bag (no behaviour change).
2. Migrate Noble into `tenants/noble/`.
3. Neutralize tool copy + brand vars.
4. Add a second provider to prove isolation.

## What changes in core

| Component | Change |
|---|---|
| `data/providers/base.py` | `+extras` on `Unit`/`ProjectOverview`; `+ExtraFieldSpec`; trim documented core |
| `data/providers/_serialize.py` | render core + labeled extras (generic) |
| `agent/tools/registry.py` | NEW — `ToolSpec` registry, decorator |
| `agent/tools/schemas.py` | static dict → `build_schemas(ctx)` (enabled + tool_params + brand + strip disabled) |
| `agent/tools/dispatcher.py` | if/elif → registry lookup; flags from `ToolSpec` |
| `agent/base.py` | `load_agent_def(persona_dir)` |
| `agent/prompts/builder.py` | render brand vars + auto extras appendix |
| `tenant/loader.py`, `tenant/context.py` | NEW |
| `facade.py`/`orchestrator.py`/`runner.py` | receive `TenantContext` |
| `agent/definitions/` → `tenants/noble/persona/` | git-mv; `config.json` folded into manifest |
| `SMOKE.md` | +multi-tenant case (swap `TENANT_ID`) |

## Testing

- **Unit:** `ExtraFieldSpec` round-trip; serializer renders labeled extras;
  `build_schemas` injects `tool_params` + strips disabled ranker/channel params;
  registry resolve (built-in + custom, tenant isolation); declarative `match`
  operators; brand templating; loader builds `TenantContext` from a fixture
  manifest; fail-loud on bad manifest.
- **Invariant regression (dispatcher refactor):** empty id/name drop, interrupt
  placeholder injection, customer-dirty rebuild — all preserved.
- **Migration parity:** with `TENANT_ID=noble`, offered tools + system prompt +
  tool outputs match the pre-migration snapshot (a golden test).
- **Isolation:** a second fixture tenant's custom tool/field is invisible to
  Noble and vice-versa.

## Out of scope / follow-ups

- `booking`/`escalate`/CRM tools staying Noble-shaped (separate spec).
- Runtime multi-tenant resolution (DID/API-key → tenant) — code is ready; only
  the resolver is deferred.
- Migrating the RAG/`kb_search` corpus per tenant (this spec keeps the current
  single corpus; per-tenant KB is a follow-up).
```
