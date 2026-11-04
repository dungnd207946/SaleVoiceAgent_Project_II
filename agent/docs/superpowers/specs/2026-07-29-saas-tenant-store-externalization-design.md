# SaaS Slice #1 — Externalize Tenant Store + Provisioning Contract

- **Date:** 2026-07-29
- **Branch:** `feat/refactor2`
- **Status:** Design approved, pending spec review → implementation plan.
- **Scope:** Sub-project #1 of the multi-tenant SaaS platform (see Roadmap).

## 1. Background & Problem

Today a tenant is a config bundle resolved **once at boot** from `TENANT_ID` →
`tenants/<id>/manifest.toml` by `tenant/loader.py::get_tenant_context()` (a
process-wide singleton). The bundle — `manifest.toml` + `persona/` (SOUL, RULES,
PROMPT_TEMPLATE, CUSTOMER_PROFILE, config.json) + optional `tools/*.py` custom
tools — lives **inside the Python package** (`src/noble_agent/tenants/<id>/`) and
ships read-only in the wheel. Custom tools are loaded as **package submodules**
(`importlib.import_module("noble_agent.tenants.<id>.tools")`, pkgutil walk).

Consequences that block a real SaaS:

1. **No runtime tenant creation.** A new tenant means editing the source tree +
   rebuilding + redeploying the wheel. An admin cannot create a tenant from a
   dashboard.
2. **Read-only in prod.** The package dir is not writable in a prod container, so
   there is nowhere to "write a new `tenants/<name>/` folder" at runtime.
3. **1 process = 1 tenant, fixed at boot.** The singleton context is read once
   from an env var.

This slice removes blockers (1) and (2): it makes the **bundle a mutable,
externally-stored artifact** that a running (or newly-started) process reads,
and defines the **provisioning contract** (the behavior of "create a tenant").
It does **not** change the "1 process = 1 tenant" runtime model — that is
addressed by slice #2.

## 2. Platform Roadmap (context)

The overall SaaS goal was decomposed into 5 sub-projects; the chosen platform
runtime model is **process-per-tenant + scale-to-zero** (each tenant runs in its
own process/container, provisioned by a control plane; idle tenants scale to
zero). Rationale recorded below in §9.

| # | Sub-project | Depends on | This spec |
|---|---|---|---|
| **1** | **Externalize tenant store + provisioning contract** | — | ✅ **THIS** |
| 2 | Runtime routing + process lifecycle (scale-to-zero) | #1 | later |
| 3 | Custom tool authoring & **safe execution / sandbox** | #1 | later |
| 4 | Provisioning backend / control-plane HTTP API | #1, #2 | later |
| 5 | Admin dashboard UI | #4 | later |

Each sub-project gets its own spec → plan → implementation cycle.

## 3. Goals & Non-Goals

### Goals (slice #1)
- A running process can load a tenant bundle from **MinIO** (S3-compatible)
  object storage, materializing it to a local directory at boot.
- A documented, **validated** bundle format.
- A **library API + CLI** (`noble-tenant`) that creates / updates / disables /
  lists / shows / validates a tenant bundle in the store, and can seed an
  existing in-wheel tenant into the store.
- Fully **backward compatible**: with the store disabled (default), behavior is
  byte-identical to today; `noble` / `demo_acme` keep loading from the package;
  the existing ~1450 unit tests stay green with no MinIO dependency.

### Non-Goals (explicitly deferred)
- **HTTP provisioning API + admin dashboard** → slices #4 / #5.
- **Process orchestration, routing, scale-to-zero** → slice #2.
- **Custom-tool sandboxing / trust boundary** → slice #3. This slice *loads*
  tenant-authored tool code but treats it as **admin-trusted**; it only performs
  a syntax (`compile()`) check, not sandboxed execution. It MAY emit warnings
  (e.g. imports outside an allowlist) as hints for #3, but does not enforce.
- **Per-tenant data isolation** for Redis / Mongo session keys (a separate
  concern; noted as a known gap, not solved here).
- **Hot-reload within a running process.** A bundle edit takes effect on the
  **next process start** (slice #2's control plane restarts the tenant process).

## 4. Bundle Representation in MinIO

Bundle stored as a **file tree** under bucket `hotline-tenants`, prefixed by
tenant id:

```
s3://hotline-tenants/<tenant_id>/
├── _meta.json               # {status, version, bundle_hash, updated_at, created_at}
├── manifest.toml
├── persona/
│   ├── SOUL.md
│   ├── RULES.md
│   ├── PROMPT_TEMPLATE.md
│   ├── CUSTOMER_PROFILE.md
│   └── config.json
└── tools/                   # optional
    └── *.py
```

- **`_meta.json`** holds orchestration metadata, kept separate from bundle
  content so the loader can cheaply read status/hash without downloading the
  whole tree:
  ```jsonc
  {
    "tenant_id": "acme",
    "status": "active|draft|disabled",
    "version": 3,                 // monotonically bumped each update
    "bundle_hash": "sha256:…",    // hash over canonical content (files+manifest)
    "created_at": "2026-07-29T…Z",
    "updated_at": "2026-07-29T…Z"
  }
  ```
- Content files keep their native form (TOML / MD / JSON / PY), so
  materialization is a plain recursive download — no transform.
- `tenant_id` is a slug matching `^[a-z0-9][a-z0-9_-]{1,62}$` (also the S3 prefix
  and the local materialize dir name).
- `bundle_hash` is computed over the sorted `(relative_path, content_bytes)`
  pairs of all files **including** `manifest.toml`, excluding `_meta.json`. It
  drives idempotent materialization and provisioning idempotency.

## 5. Loader Changes (`tenant/loader.py`)

New resolution order in `load_tenant(tenant_id, settings)`:

1. **Store-first**: if `settings.tenant_store_enabled` and the store has
   `<tenant_id>/_meta.json` with `status == "active"`:
   a. **Sync** prefix `<tenant_id>/` from MinIO → `TENANT_MATERIALIZE_DIR/<id>/`.
   b. Parse the tenant from that local dir, reusing the **existing file-based
      parse** (manifest keys, persona dir, tools).
2. **Fallback**: otherwise, read from the in-wheel package dir
   `noble_agent/tenants/<id>/` exactly as today. (Covers `noble` / `demo_acme`
   and keeps dev/test offline with no MinIO.)

Materialization (`tenant/store.py`):
- **Idempotent**: compare `_meta.json.bundle_hash` against an on-disk marker
  `TENANT_MATERIALIZE_DIR/<id>/.bundle_hash`. If equal, skip the download (avoids
  a MinIO round-trip on every boot).
- **Atomic-ish**: download into a temp dir sibling, then swap into place, so a
  crashed/partial sync never leaves a half-written bundle that the loader reads.
- Writes the `.bundle_hash` marker last, after all files land.

Custom-tool import (`tenant/loader.py::_import_tenant_tools`):
- **In-wheel tenant** (fallback path): unchanged
  `importlib.import_module("noble_agent.tenants.<id>.tools")` + pkgutil walk.
- **Materialized tenant** (store path): import each `tools/*.py` from the
  materialized dir via `importlib.util.spec_from_file_location`, under a
  synthetic module name `noble_agent._tenant_tools.<id>.<modname>`. The `@tool`
  decorator self-registers as it does today; the tool file's
  `from noble_agent.agent.tools.registry import tool` is an absolute import and
  works regardless of the file's location.
- Import failure inside a **present** tools dir propagates (fail loud), matching
  the current contract; absent tools dir is a no-op.

`TenantContext` is **unchanged** (frozen dataclass). For a store tenant,
`persona_dir` simply points at the materialized dir instead of the package dir.

## 6. Provisioning Contract

### 6.1 Library API — `tenant/provisioning.py`
Pure functions over a store client (see §7), each validating before writing:

- `create_tenant(tenant_id, manifest_text, files: dict[str, str], *, status="draft") -> Meta`
  — fail if the tenant already exists; validate; write files + `_meta.json`
  (version 1).
- `update_tenant(tenant_id, *, manifest_text=None, files=None, status=None) -> Meta`
  — validate the resulting bundle; bump `version`; recompute `bundle_hash`.
- `set_status(tenant_id, status)` / `disable_tenant(tenant_id)` — flip
  `_meta.json.status`.
- `list_tenants() -> list[Meta]` / `get_tenant(tenant_id) -> Bundle` — read.
- `import_from_package(tenant_id) -> Meta` — read the in-wheel
  `tenants/<id>/` bundle and write it into the store (seed / demo helper).

`files` maps a bundle-relative path (e.g. `persona/SOUL.md`, `tools/loan.py`) to
UTF-8 text content.

### 6.2 CLI — `noble-tenant` (new console script)
Thin wrapper over the library:
- `noble-tenant create <id> --dir <path> [--status draft|active]`
- `noble-tenant update <id> --dir <path>`
- `noble-tenant show <id>` / `list`
- `noble-tenant disable <id>` / `activate <id>`
- `noble-tenant validate --dir <path>` (validate a local bundle dir, no write)
- `noble-tenant materialize <id> [--dest <path>]` (dry-run: download from store)
- `noble-tenant import-from-package <id>` (seed an in-wheel tenant)

### 6.3 Validation (`tenant/validation.py`), shared by create/update/validate
1. `tenant_id` matches the slug regex and (for create) does not already exist.
2. `manifest.toml` parses as TOML **and** has the required keys
   (`data_source`, `persona_dir`, `[tools].enabled`) — reuse the loader's
   existing checks by extracting a shared `parse_manifest(text) -> dict`.
3. Every name in `[tools].enabled` **resolves**: it is a built-in `ToolSpec`
   (registered `tenant="*"`) **or** is declared by a custom `tools/*.py` file in
   the bundle. Resolution is checked **statically** (AST scan of each tool file
   for `@tool(name=...)` decorator calls) — validation MUST NOT import/execute
   tenant code. (The actual import/execution happens only at boot on the
   admin-trusted loader path, §5, which is separate from validation.)
4. The persona files the manifest's `persona_dir` implies exist in the bundle
   (`config.json`, `SOUL.md`, `RULES.md`, `PROMPT_TEMPLATE.md`,
   `CUSTOMER_PROFILE.md`) and `config.json` parses as JSON.
5. Each custom tool file **compiles** (`compile(src, name, "exec")`) — a syntax
   gate only. NOT execution, NOT a sandbox (that is slice #3). Imports outside a
   documented allowlist produce a **warning** (advisory for #3), not a failure.

Validation is total: it returns a structured report (errors + warnings); the
provisioning functions refuse to write when there are errors.

### 6.4 Lifecycle / activation semantics
- `draft` — exists in the store, **not served** (the loader treats non-`active`
  as "not in store" → falls back to package or fails if none).
- `active` — served by a process booting with that `TENANT_ID`.
- `disabled` — refused (not served, distinct from `draft` for audit).
- Editing a bundle writes a new `version` + `bundle_hash`. A **running process
  does not hot-reload**; the change is picked up at the next boot (slice #2's
  control plane restarts the tenant's process, which re-materializes).

## 7. Store Client & Config

### 7.1 Client (`tenant/store.py`)
- **`boto3`** S3 client with `endpoint_url = MINIO_ENDPOINT` (S3-compatible;
  MinIO works transparently). Lazy-imported so `make test-unit` collects without
  the dep; used only at boot-time materialization + provisioning (not the hot
  path), so a synchronous client is fine.
- A thin `TenantStore` wrapper exposes: `read_meta(id)`, `list_ids()`,
  `download_tree(id, dest)`, `put_bundle(id, files, meta)`, `put_meta(id, meta)`.
- Injectable for tests (a fake in-memory store implementing the same interface;
  or `moto`/`botocore` stubber) so no real MinIO is touched in unit tests.

### 7.2 New settings (`config.py`, pydantic-settings)
| Setting (env) | Default | Purpose |
|---|---|---|
| `TENANT_STORE_ENABLED` | `false` | Master flag. `false` → pure in-wheel (today's behavior, offline). |
| `MINIO_ENDPOINT` | empty | S3 endpoint, e.g. `http://10.50.13.220:9000`. |
| `MINIO_ROOT_USER` | empty | Access key. |
| `MINIO_ROOT_PASSWORD` | empty | Secret key. **`.env` only, never hardcoded/committed.** |
| `TENANT_BUCKET` | `hotline-tenants` | Bucket holding bundles. |
| `TENANT_MATERIALIZE_DIR` | `/var/lib/noble/tenants` | Local dir bundles are synced into. |

`.env.example` documents all six (with placeholder secrets). The real
`MINIO_ROOT_PASSWORD` lives only in the gitignored `.env`.

## 8. Backward Compatibility & Testing

- `TENANT_STORE_ENABLED=false` (default) → loader never touches MinIO; identical
  to current behavior; the ~1450 existing unit tests are unaffected and need no
  MinIO.
- `noble` / `demo_acme` continue to load from the package regardless of the flag
  (they are not `active` in the store unless explicitly seeded).

New tests (fake store, no live MinIO):
- **Store round-trip**: `create_tenant` → `get_tenant` → content matches;
  `update_tenant` bumps version + hash.
- **Materialization**: writes the tree; second boot with matching hash **skips**
  download; atomic swap leaves no partial dir on simulated mid-sync failure.
- **Loader precedence**: store `active` wins over package; store `draft`/absent
  falls back to package; store enabled but tenant missing + no package → the
  existing fail-loud error.
- **Custom tool file-path import**: a materialized `tools/*.py` self-registers
  its `@tool` under the tenant and is invisible to other tenants (mirrors the
  `demo_acme` isolation test through the new import path).
- **Validation**: rejects bad TOML / missing manifest key / an `enabled` tool
  that resolves to neither a built-in nor a bundle tool / a missing persona file
  / a tool with a syntax error; passes a well-formed bundle; emits the
  import-allowlist warning without failing.
- **CLI**: `validate --dir` on the in-wheel `noble` bundle passes;
  `import-from-package noble` seeds the store (against the fake store).

## 9. Key Decisions & Rationale

- **Runtime model = process-per-tenant + scale-to-zero.** Chosen over a hybrid
  worker pool because: (a) it barely changes the current boot-singleton runtime
  (no hot-path refactor); (b) untrusted custom tools strongly favor OS-level
  isolation — Python cannot unload modules and the tool registry is a
  process-global dict, so a reused shared worker would accumulate every tenant's
  tools in one interpreter (memory + cross-tenant security), forcing
  respawn-on-switch and erasing the pool's density benefit; (c) voice TTFA
  punishes cold session-assignment; (d) STT/TTS are already remote services, so
  a per-tenant process does **not** imply a per-tenant GPU, making "keep the
  process warm / scale to zero" cheap. Hybrid remains a viable later optimization
  for a low-traffic long-tail tier without discarding this foundation.
- **MinIO source of truth, materialize-at-boot.** Keeps the loader file-based
  (minimal change), makes the bundle a mutable artifact a dashboard can write,
  and fits process-per-tenant (each process starts fresh and syncs its bundle).
- **Store-first with in-wheel fallback.** Additive, low-risk: keeps dev/test
  offline and the existing tenants/tests working with zero migration.
- **Provisioning = library + CLI (no HTTP yet).** Tight, testable boundary; the
  dashboard/HTTP layer builds on this in slices #4/#5.

## 10. Known Gaps (tracked for later slices)
- MinIO is on the critical path of process start (mitigated by the hash-cache
  skip). The in-wheel package fallback only covers an **absent, draft, or
  disabled** tenant (`read_meta` returning `None` or a non-`active` status) —
  a genuine store **backend error** (MinIO down, network, auth) during
  `read_meta`/`read_bundle` RAISES and does NOT fall back to the package; this
  is a deliberate fail-loud choice, with graceful degradation on a backend
  error deferred to slice #2. Slice #2 may also add a warm/pre-sync step.
- No per-tenant Redis/Mongo session-data isolation yet.
- Custom tool code is admin-trusted (syntax-checked only) until slice #3 adds a
  sandbox.
- No in-process hot-reload; relies on slice #2 restart-on-change.
