# Plan 1 — Tenant Contextvar Spine + De-globalize (§5b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one process serve any tenant correctly — resolve tenant **per-request** via a `ContextVar` (never process-global) and convert every "process = one tenant" singleton to per-tenant-keyed, so two tenants interleaved in one process never bleed prompt / tool-list / project-index / registry / provider data into each other.

**Architecture:** Introduce a tenant `ContextVar` (`tenant/current.py`) with `current_tenant()` that falls back to `settings.tenant_id` when unset — so single-tenant dev is byte-identical. Every transport entry boundary sets the contextvar from the best per-request source (voice: LiveKit participant metadata; chat: optional provision/handshake field), and `NobleAgent` **captures** the tenant at `create()` and **re-establishes** it (`use_tenant(...)`) around every turn, so correctness survives asyncio task boundaries. All per-tenant caches (`get_tenant_context`, `find_project` index, data-provider instances, facade `_runners`) become keyed by tenant.

**Tech Stack:** Python 3.11+, asyncio, `contextvars`, pydantic-settings, pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Branch `feat/agent`. **NO commit/push/PR** without explicit instruction in the same session. **Never touch `develop`.** (memo §10)
- **Tenant is ALWAYS per-request via `ContextVar`, NEVER process-global.** Runs identically in 1 process or N pods. (memo §0.1, §0.2)
- **`settings.tenant_id` fallback must keep single-tenant dev byte-identical** — when the contextvar is unset, every path behaves exactly as today (Noble/Santa unaffected).
- **Surgical.** Touch only what the de-globalize audit requires. Keep every existing cache (version TTL, materialize-once, `_runners` LRU) — only change its **key** to include tenant. (memo §10)
- **`_runners` cap ≥ 256** (O4 = 200 concurrent tenants); runner init is cheap (prompt text + schemas dict), provider client is process-global one-time. (memo §5, O4)
- `make test-unit` keeps the documented CLAUDE.md baseline (the ~8 known failures), **0 new**; `make lint` clean on every touched file. (memo §9)
- Non-trivial → follow `noble-feature-flow` (plan → TDD → review+verify). CLAUDE.md self-maintenance: architecture change → update the Architecture section + append a Change Log row **in the same commit**.

---

## File Structure

**New files:**
- `src/noble_agent/tenant/current.py` — the tenant `ContextVar` + `current_tenant()` / `set_current_tenant()` / `reset_current_tenant()` / `use_tenant()`.
- `tests/unit/tenant/test_current.py` — contextvar semantics + settings fallback.
- `tests/unit/tenant/test_deglobalize_isolation.py` — the §9 de-globalize test (two tenants interleaved in one process).

**Modified files:**
- `src/noble_agent/tenant/loader.py` — `get_tenant_context()` → per-tenant-keyed dict resolved via `current_tenant()`.
- `src/noble_agent/agent/tools/find_project.py` — module `_INDEX` single slot → `_INDEX_BY_TENANT` dict; `set_index`/`get_index`/`run` tenant-aware.
- `src/noble_agent/agent/orchestrator.py` — `_build_project_index()` installs keyed by `current_tenant()`; `_run_live` dispatcher `tenant=current_tenant()`.
- `src/noble_agent/data/providers/__init__.py` — `_INSTANCES` keyed by `(tenant_id, source)`; source resolved from the tenant's `TenantContext.data_source`.
- `src/noble_agent/agent/facade.py` — `_runners` keyed `(tenant, version)`, cap 256; legacy runner per-tenant; `_resolve_current_version`/`_build_runner_for_version`/`_get_runner_for_version`/`_get_runner`/`ensure_version_built` take tenant; `NobleAgent` captures + wraps tenant on every method.
- `src/noble_agent/transport/livekit/worker.py` — `entrypoint` resolves per-job tenant from participant metadata (fallback settings) and sets the contextvar before the session starts.
- `src/noble_agent/server/text_chat.py` — `handle_text_session` accepts an optional per-session tenant and sets the contextvar (fallback settings).
- `src/noble_agent/server/ws_handler.py` — thread the optional tenant into `handle_text_session` (default `None`).

**Files intentionally NOT changed** (per §5b, but noted): `data/db_project_registry.py` needs **no** edit — `_provider()` already delegates to `providers.get_provider(get_settings())`, which becomes tenant-aware in Task 5. Heartbeat/worker `agent_dispatch_name(settings.tenant_id)` registration (`worker.py:299`, `server/http.py:1027`, `server/app_session.py:241`) is **process-level infra** (the deploy's home tenant / LiveKit registration), NOT the per-request data path — left for the infra phase (memo §0, §3). Record this exclusion in the Change Log.

---

## Design contract (interfaces every task shares)

```python
# tenant/current.py — the spine every downstream task consumes
def set_current_tenant(tenant_id: str | None) -> "contextvars.Token": ...
def reset_current_tenant(token) -> None: ...
def current_tenant() -> str:        # contextvar value, else get_settings().tenant_id
    ...
@contextmanager
def use_tenant(tenant_id: str | None): ...   # set on enter, reset on exit
```

- `get_tenant_context()` keeps its **no-arg** signature (many callers) but now resolves `current_tenant()` internally and caches per tenant.
- `find_project.set_index(idx, *, tenant: str | None = None)` / `get_index(*, tenant: str | None = None)` — `None` → `current_tenant()`.
- `providers.get_provider(settings)` keeps its signature; internally keys `_INSTANCES` by `(current_tenant(), source)` where `source = get_tenant_context().data_source`.
- `NobleAgent.create(session_id, customer=None, *, tenant_id: str | None = None)` — `None` → `current_tenant()`; stores `self.tenant_id`; every public method runs under `use_tenant(self.tenant_id)`.

---

### Task 1: Tenant contextvar module (`tenant/current.py`)

**Files:**
- Create: `src/noble_agent/tenant/current.py`
- Test: `tests/unit/tenant/test_current.py`

**Interfaces:**
- Produces: `set_current_tenant`, `reset_current_tenant`, `current_tenant`, `use_tenant` (see Design contract).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/tenant/test_current.py
from noble_agent.config import reset_settings_for_tests
from noble_agent.tenant.current import (
    current_tenant, set_current_tenant, reset_current_tenant, use_tenant,
)


def test_unset_falls_back_to_settings_tenant_id(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    assert current_tenant() == "noble"


def test_set_overrides_settings(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    tok = set_current_tenant("acme")
    try:
        assert current_tenant() == "acme"
    finally:
        reset_current_tenant(tok)
    assert current_tenant() == "noble"


def test_use_tenant_scopes_and_restores(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    with use_tenant("acme"):
        assert current_tenant() == "acme"
    assert current_tenant() == "noble"


def test_empty_string_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    with use_tenant(""):
        assert current_tenant() == "noble"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_current.py -v`
Expected: FAIL with `ModuleNotFoundError: noble_agent.tenant.current`

- [ ] **Step 3: Write the implementation**

```python
# src/noble_agent/tenant/current.py
"""Per-request tenant identity via a ContextVar.

The single source of truth for "which tenant is this request for" inside a
shared multi-tenant process. NEVER read settings.tenant_id on the request/data
path — call current_tenant() instead. Unset → falls back to settings.tenant_id
so single-tenant deployments are byte-identical.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token

_current: ContextVar[str | None] = ContextVar("noble_current_tenant", default=None)


def set_current_tenant(tenant_id: str | None) -> Token:
    """Set the current tenant; returns a token for reset_current_tenant()."""
    return _current.set(tenant_id or None)


def reset_current_tenant(token: Token) -> None:
    _current.reset(token)


def current_tenant() -> str:
    """The request's tenant id, else the process default (settings.tenant_id)."""
    tid = _current.get()
    if tid:
        return tid
    from noble_agent.config import get_settings

    return get_settings().tenant_id


@contextmanager
def use_tenant(tenant_id: str | None):
    """Scope a block to a tenant. Empty/None → inherit the outer value."""
    token = _current.set(tenant_id or None) if tenant_id else _current.set(_current.get())
    try:
        yield
    finally:
        _current.reset(token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/tenant/test_current.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/current.py tests/unit/tenant/test_current.py
git commit -m "feat(tenant): per-request tenant ContextVar spine (current_tenant/use_tenant)"
```

---

### Task 2: Tenant-key `get_tenant_context()` (`tenant/loader.py`)

**Files:**
- Modify: `src/noble_agent/tenant/loader.py:16` (`_ctx_singleton`), `:127-139` (`get_tenant_context`, `reset_tenant_context_for_tests`)
- Test: `tests/unit/tenant/test_loader.py` (extend)

**Interfaces:**
- Consumes: `current_tenant` (Task 1).
- Produces: `get_tenant_context()` unchanged signature, now per-tenant-keyed.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/tenant/test_loader.py  (add)
def test_get_tenant_context_keyed_by_current_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant
    from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    reset_tenant_context_for_tests()

    with use_tenant("noble"):
        a = get_tenant_context()
    with use_tenant("demo_acme"):
        b = get_tenant_context()

    assert a.tenant_id == "noble"
    assert b.tenant_id == "demo_acme"
    # cached per tenant — same object on second read
    with use_tenant("noble"):
        assert get_tenant_context() is a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_loader.py::test_get_tenant_context_keyed_by_current_tenant -v`
Expected: FAIL — returns the `demo_acme` context for the `noble` re-read (single-slot singleton).

- [ ] **Step 3: Implement — replace the single slot with a per-tenant dict**

In `tenant/loader.py`, replace line 16:

```python
_ctx_by_tenant: dict[str, TenantContext] = {}
```

Replace `get_tenant_context` (127-134) and `reset_tenant_context_for_tests` (137-139):

```python
def get_tenant_context() -> TenantContext:
    """The TenantContext for the CURRENT tenant (per-request), cached per tenant.

    Resolves the tenant via current_tenant() (contextvar → settings fallback),
    so a shared process serves each tenant its own frozen bundle. Cached per
    tenant id: bundles are immutable per boot, so one load each.
    """
    from noble_agent.config import get_settings
    from noble_agent.tenant.current import current_tenant

    tid = current_tenant()
    ctx = _ctx_by_tenant.get(tid)
    if ctx is None:
        ctx = load_tenant(tid, get_settings())
        _ctx_by_tenant[tid] = ctx
    return ctx


def reset_tenant_context_for_tests() -> None:
    _ctx_by_tenant.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_loader.py -v`
Expected: PASS (existing loader tests + the new one)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/loader.py tests/unit/tenant/test_loader.py
git commit -m "feat(tenant): key get_tenant_context() per current tenant"
```

---

### Task 3: Tenant-key the `find_project` project-name index

**Files:**
- Modify: `src/noble_agent/agent/tools/find_project.py:14-23` (`_INDEX`/`set_index`/`get_index`), `:39-42` (`run`)
- Test: `tests/unit/unified/tools/test_find_project.py` (extend or create)

**Interfaces:**
- Consumes: `current_tenant` (Task 1).
- Produces: `set_index(idx, *, tenant=None)`, `get_index(*, tenant=None)` — `None` → `current_tenant()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/tools/test_find_project.py  (add)
def test_index_is_per_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant
    from noble_agent.agent.tools import find_project
    from noble_agent.data.project_matching.index import ProjectNameIndex

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()

    idx_a = ProjectNameIndex([{"code": "AAA", "name": "Alpha", "region": "", "type": ""}])
    idx_b = ProjectNameIndex([{"code": "BBB", "name": "Beta", "region": "", "type": ""}])
    find_project.set_index(idx_a, tenant="t_a")
    find_project.set_index(idx_b, tenant="t_b")

    with use_tenant("t_a"):
        assert find_project.get_index() is idx_a
    with use_tenant("t_b"):
        assert find_project.get_index() is idx_b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/tools/test_find_project.py::test_index_is_per_tenant -v`
Expected: FAIL — the single `_INDEX` slot returns `idx_b` for both.

- [ ] **Step 3: Implement**

Replace lines 14-23 of `find_project.py`:

```python
_INDEX_BY_TENANT: dict[str, ProjectNameIndex] = {}


def _resolve_tenant(tenant: str | None) -> str:
    if tenant:
        return tenant
    from noble_agent.tenant.current import current_tenant

    return current_tenant()


def set_index(idx: ProjectNameIndex | None, *, tenant: str | None = None) -> None:
    tid = _resolve_tenant(tenant)
    if idx is None:
        _INDEX_BY_TENANT.pop(tid, None)
    else:
        _INDEX_BY_TENANT[tid] = idx


def get_index(*, tenant: str | None = None) -> ProjectNameIndex | None:
    return _INDEX_BY_TENANT.get(_resolve_tenant(tenant))
```

In `run` (line 40) replace `idx = _INDEX` with:

```python
    idx = get_index()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/tools/test_find_project.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/find_project.py tests/unit/unified/tools/test_find_project.py
git commit -m "feat(tools): key find_project ProjectNameIndex per tenant"
```

---

### Task 4: Build the project index per-tenant in the orchestrator

**Files:**
- Modify: `src/noble_agent/agent/orchestrator.py:34-47` (`_build_project_index`), `:372-379` (`_run_live` dispatcher tenant)
- Test: `tests/unit/unified/test_orchestrator_index.py` (create)

**Interfaces:**
- Consumes: `find_project.set_index(idx, *, tenant)` (Task 3), `current_tenant` (Task 1).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_orchestrator_index.py
def test_build_index_installs_for_current_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant
    from noble_agent.agent import orchestrator
    from noble_agent.agent.tools import find_project
    from noble_agent.data import db_project_registry

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    db_project_registry.set_cache_for_tests(
        {"XYZ": {"code": "XYZ", "name": "Xyz", "region": "R", "type": "T"}}
    )
    try:
        with use_tenant("t_build"):
            orchestrator._build_project_index()
            assert find_project.get_index() is not None
        # a different tenant with no build has no index
        with use_tenant("t_other"):
            assert find_project.get_index() is None
    finally:
        db_project_registry.set_cache_for_tests(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_orchestrator_index.py -v`
Expected: FAIL — `_build_project_index` installs into the tenant-unaware slot so `t_other` also sees the index.

- [ ] **Step 3: Implement**

In `_build_project_index` (line 45) replace `find_project.set_index(ProjectNameIndex(rows))` with:

```python
        from noble_agent.tenant.current import current_tenant

        find_project.set_index(ProjectNameIndex(rows), tenant=current_tenant())
```

In `_run_live` (line 378) replace `tenant=get_tenant_context().tenant_id,` with:

```python
            tenant=current_tenant(),
```

Add the import at the top of `orchestrator.py` (next to the `get_tenant_context` import, line 21):

```python
from noble_agent.tenant.current import current_tenant
```

(Leave the `get_tenant_context` import; it is still used elsewhere in the module if present. If `get_tenant_context` becomes unused after this edit, remove it — run `ruff check` to confirm.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_orchestrator_index.py tests/unit/unified/test_orchestrator*.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/orchestrator.py tests/unit/unified/test_orchestrator_index.py
git commit -m "feat(orchestrator): build project index + dispatch tenant per current tenant"
```

---

### Task 5: Tenant-key data-provider instances (`data/providers/__init__.py`)

**Files:**
- Modify: `src/noble_agent/data/providers/__init__.py:13` (`_INSTANCES`), `:16-40` (`get_provider`), `:43-62` (`active_extra_specs`/`active_tool_params`), `:65-66` (`reset_for_tests`)
- Test: `tests/unit/unified/providers/test_factory.py` (extend)

**Interfaces:**
- Consumes: `current_tenant` (Task 1), `get_tenant_context().data_source` (Task 2).
- Produces: `get_provider(settings)` unchanged signature, `_INSTANCES` keyed by `(tenant_id, source)`; a provider instance's warmed `self._cache` roster is now per-tenant.

**Why:** `NbxMongoProvider` holds the tenant roster in `self._cache` (audit: `nbx_mongo.py:213`). Keyed by the bare `source` string, two tenants both on `nbx` would **share one roster** — a cross-tenant data leak. Key by `(tenant, source)`; resolve `source` from the tenant's manifest `data_source` (memo §5b), falling back to `settings.noble_data_source`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/providers/test_factory.py  (add)
def test_provider_instances_are_per_tenant(monkeypatch):
    from noble_agent.config import get_settings, reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant
    from noble_agent.data import providers

    monkeypatch.setenv("TENANT_ID", "noble")
    monkeypatch.setenv("NOBLE_DATA_SOURCE", "nbx")
    reset_settings_for_tests()
    providers.reset_for_tests()
    s = get_settings()

    with use_tenant("t_a"):
        pa = providers.get_provider(s)
        pa2 = providers.get_provider(s)
    with use_tenant("t_b"):
        pb = providers.get_provider(s)

    assert pa is pa2            # same tenant → cached
    assert pa is not pb         # different tenant → distinct instance (distinct roster cache)
```

(If `use_tenant("t_a")` triggers a manifest load for a tenant with no bundle, guard the test by stubbing `get_tenant_context` to return a context whose `data_source == "nbx"`; or drive the two tenants as `"noble"` and `"demo_acme"` which both have bundles. Prefer the bundle-backed tenants to keep the test hermetic.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/providers/test_factory.py -v`
Expected: FAIL — `pa is pb` (single instance per source string).

- [ ] **Step 3: Implement**

Replace line 13 and `get_provider` (16-40):

```python
_INSTANCES: dict[tuple[str, str], DataProvider] = {}


def _active_source(settings) -> str:
    """Data source for the CURRENT tenant: the tenant manifest's data_source
    (per-tenant, memo §5b), falling back to settings.noble_data_source."""
    try:
        from noble_agent.tenant.loader import get_tenant_context

        src = get_tenant_context().data_source
    except Exception:
        src = ""
    return (src or getattr(settings, "noble_data_source", "") or "mongo").strip()


def get_provider(settings) -> DataProvider:
    from noble_agent.tenant.current import current_tenant

    tenant_id = current_tenant()
    source = _active_source(settings)
    key = (tenant_id, source)
    cached = _INSTANCES.get(key)
    if cached is not None:
        return cached
    if source == "mongo":
        from noble_agent.data.providers.mongo import MongoProvider

        provider: DataProvider = MongoProvider()
    elif source == "nbx":
        from noble_agent.data.providers.nbx_mongo import NbxMongoProvider

        provider = NbxMongoProvider()
    elif source == "sales_api":
        from noble_agent.data.providers.sales_api import SalesApiProvider

        provider = SalesApiProvider(
            base_url=settings.nbx_sales_api_url,
            timeout=settings.nbx_sales_api_timeout,
            token=settings.nbx_sales_api_token,
        )
    else:
        raise ValueError(f"Unknown data source: {source!r} (mongo | nbx | sales_api)")
    _INSTANCES[key] = provider
    return provider
```

`active_extra_specs` / `active_tool_params` (43-62) already call `get_provider(get_settings())`, which is now tenant-aware — leave their bodies unchanged, but update the stale docstrings (drop "Phase 3 threads these through TenantContext" → "resolves the current tenant's provider"). `reset_for_tests` (66) — `_INSTANCES.clear()` still correct.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/providers/ -v`
Expected: PASS (all provider tests + the new one)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/__init__.py tests/unit/unified/providers/test_factory.py
git commit -m "feat(providers): key provider instances per (tenant, source); source from tenant manifest"
```

---

### Task 6: Tenant-key the facade runner registry + capture/wrap tenant on `NobleAgent`

**Files:**
- Modify: `src/noble_agent/agent/facade.py` — `:34-44` (globals), `:201-208` (`_build_runner`), `:274-281` (`_get_runner`), `:284-316` (`_resolve_current_version`), `:319-327` (`_build_runner_for_version`), `:330-346` (`_get_runner_for_version`), `:349-359` (`ensure_version_built`), `:445-462` (`NobleAgent.__init__`/`create`), `:464-618` (public methods wrap `use_tenant`), `:621-624` (`reset_runner_for_tests`)
- Test: `tests/unit/unified/test_facade_tenant.py` (create)

**Interfaces:**
- Consumes: `current_tenant`, `use_tenant` (Task 1).
- Produces: `NobleAgent.create(session_id, customer=None, *, tenant_id=None)` → instance with `self.tenant_id`; `_runners` keyed `(tenant, version)`, cap 256; `_legacy_runners: dict[str, TurnRunner]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_facade_tenant.py
import pytest
from noble_agent.agent import facade


@pytest.mark.asyncio
async def test_create_captures_current_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()

    built = []

    async def fake_get_runner(tenant_id):
        built.append(tenant_id)
        return object()

    monkeypatch.setattr(facade, "_resolve_current_version", lambda tenant_id: 0)
    monkeypatch.setattr(facade, "_get_runner", fake_get_runner)

    with use_tenant("acme"):
        agent = await facade.NobleAgent.create("sess-1")
    assert agent.tenant_id == "acme"
    assert built == ["acme"]


def test_runners_keyed_by_tenant_and_version():
    facade.reset_runner_for_tests()
    facade._runners[("t_a", 5)] = object()
    facade._runners[("t_b", 5)] = object()
    assert facade._runners[("t_a", 5)] is not facade._runners[("t_b", 5)]
    assert facade._RUNNERS_MAX >= 256
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_facade_tenant.py -v`
Expected: FAIL — `create` takes no tenant, `_resolve_current_version`/`_get_runner` take no tenant arg, `_RUNNERS_MAX == 4`.

- [ ] **Step 3: Implement**

Replace the globals (34-44):

```python
_legacy_runners: dict[str, TurnRunner] = {}  # version 0 (package/store-disabled), per tenant
_runner_lock = asyncio.Lock()

# Version-keyed runner registry (SP-C2), now ALSO keyed by tenant so a shared
# multi-tenant process never serves tenant A the runner built for tenant B.
# Cap 256 to cover O4 = 200 concurrent tenants (runner init is cheap: prompt
# text + schemas dict; provider clients are process-global one-time).
_runners: OrderedDict[tuple[str, int], TurnRunner] = OrderedDict()
_runners_lock = asyncio.Lock()
_RUNNERS_MAX = 256
```

`_build_runner` (201-208) → take tenant, run the build under it:

```python
async def _build_runner(tenant_id: str) -> TurnRunner:
    """Legacy single-runner build for version 0 (store-disabled/package mode)."""
    from noble_agent.tenant.current import use_tenant
    from noble_agent.tenant.loader import get_tenant_context

    with use_tenant(tenant_id):
        return await _build_runner_from_ctx(get_tenant_context())
```

`_get_runner` (274-281) → per-tenant:

```python
async def _get_runner(tenant_id: str) -> TurnRunner:
    existing = _legacy_runners.get(tenant_id)
    if existing is not None:
        return existing
    async with _runner_lock:
        existing = _legacy_runners.get(tenant_id)
        if existing is None:
            existing = await _build_runner(tenant_id)
            _legacy_runners[tenant_id] = existing
    return existing
```

`_resolve_current_version` (284) → `def _resolve_current_version(tenant_id: str) -> int:` and replace the two `settings.tenant_id` reads (298) with the `tenant_id` param. (The body's `store = _build_store(settings)` stays.)

`_build_runner_for_version` (319) → `async def _build_runner_for_version(tenant_id: str, version: int) -> TurnRunner:`; replace `settings.tenant_id` (326) with `tenant_id`; wrap the build under `use_tenant(tenant_id)`:

```python
async def _build_runner_for_version(tenant_id: str, version: int) -> TurnRunner:
    settings = get_settings()
    from noble_agent.tenant.current import use_tenant
    from noble_agent.tenant.loader import _build_store
    from noble_agent.tenant.version_resolver import context_for_version

    store = _build_store(settings)
    ctx = context_for_version(store, settings, tenant_id, version)
    with use_tenant(tenant_id):
        return await _build_runner_from_ctx(ctx)
```

`_get_runner_for_version` (330) → key `(tenant_id, version)`:

```python
async def _get_runner_for_version(tenant_id: str, version: int) -> TurnRunner:
    key = (tenant_id, version)
    existing = _runners.get(key)
    if existing is not None:
        _runners.move_to_end(key)
        return existing
    async with _runners_lock:
        existing = _runners.get(key)
        if existing is not None:
            _runners.move_to_end(key)
            return existing
        runner = await _build_runner_for_version(tenant_id, version)
        _runners[key] = runner
        _runners.move_to_end(key)
        while len(_runners) > _RUNNERS_MAX:
            _runners.popitem(last=False)
        return runner
```

`ensure_version_built` (349) → add tenant (default settings for the process-level heartbeat caller):

```python
async def ensure_version_built(version: int, *, tenant_id: str | None = None) -> None:
    tid = tenant_id or get_settings().tenant_id
    await _get_runner_for_version(tid, version)
```

`NobleAgent.__init__` (446) → add `tenant_id`:

```python
    def __init__(self, session_id: str, runner: TurnRunner, version: int = 0, tenant_id: str | None = None):
        self.session_id = session_id
        self._runner = runner
        self._current_agent = "unified"
        self.pinned_version = version
        from noble_agent.tenant.current import current_tenant

        self.tenant_id = tenant_id or current_tenant()
```

`NobleAgent.create` (455-462):

```python
    @classmethod
    async def create(cls, session_id: str, customer: dict | None = None, *, tenant_id: str | None = None) -> "NobleAgent":
        from noble_agent.tenant.current import current_tenant, use_tenant

        tid = tenant_id or current_tenant()
        with use_tenant(tid):
            version = _resolve_current_version(tid)
            if version:
                runner = await _get_runner_for_version(tid, version)
            else:
                runner = await _get_runner(tid)
        return cls(session_id=session_id, runner=runner, version=version, tenant_id=tid)
```

Wrap the **body** of each public method that runs turn work in `with use_tenant(self.tenant_id):` — `ensure_session_started` (464), `stream_response` (499), `suggest_followups` (528), `set_customer_fields` (563). Example for `stream_response`:

```python
    async def stream_response(self, user_text, on_token=None, on_tool_start=None,
                              on_tool_done=None, interrupt_check=None, on_agent_switch=None,
                              show_thinking=False, **_legacy_ignored) -> str:
        from noble_agent.tenant.current import use_tenant

        with use_tenant(self.tenant_id):
            sink: list[str] = []
            stripper = None if show_thinking else ThinkStripper()
            cb = _Callbacks(on_token=on_token, on_tool_start=on_tool_start,
                            on_tool_done=on_tool_done, interrupt_check=interrupt_check,
                            sink=sink, stripper=stripper)
            try:
                await self._runner.handle_turn(self.session_id, user_text, cb)
            finally:
                await cb.flush()
            return "".join(sink)
```

`reset_runner_for_tests` (621-624):

```python
def reset_runner_for_tests() -> None:
    _legacy_runners.clear()
    _runners.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_facade_tenant.py tests/unit/unified/test_facade*.py tests/unit/unified/test_runner*.py -v`
Expected: PASS. Then the SP-C2 / version tests: `pytest tests/unit/unified -k "version or runner or facade" -v` — all green (0 new failures vs baseline).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/facade.py tests/unit/unified/test_facade_tenant.py
git commit -m "feat(facade): key runners per (tenant, version) cap 256; NobleAgent captures+wraps tenant"
```

---

### Task 7: Set the tenant contextvar at the voice (LiveKit) entry boundary

**Files:**
- Modify: `src/noble_agent/transport/livekit/worker.py:169-217` (`entrypoint` — resolve per-job tenant from participant metadata, set contextvar)
- Test: `tests/unit/unified/test_worker_tenant.py` (create) — unit-test the tenant-extraction helper.

**Interfaces:**
- Consumes: `set_current_tenant` (Task 1), `identity_to_fields` (unchanged).
- Produces: a pure helper `_job_tenant(metadata_json: str, default: str) -> str` extracting `tenant_id` from the caller's participant metadata (gateway may place it there), else `default = settings.tenant_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_worker_tenant.py
def test_job_tenant_from_metadata():
    from noble_agent.transport.livekit.worker import _job_tenant
    assert _job_tenant('{"tenant_id": "acme", "phone": "0900"}', "noble") == "acme"
    assert _job_tenant('{"phone": "0900"}', "noble") == "noble"      # no tenant → default
    assert _job_tenant("not json", "noble") == "noble"
    assert _job_tenant("", "noble") == "noble"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_worker_tenant.py -v`
Expected: FAIL — `_job_tenant` does not exist.

- [ ] **Step 3: Implement**

Add near the top of `worker.py` (module level):

```python
def _job_tenant(metadata_json: str, default: str) -> str:
    """Per-job tenant from the caller's participant metadata (gateway-set),
    else the process default. De-globalize: a voice job resolves its own
    tenant, it does NOT assume the worker's home tenant."""
    import json as _json

    try:
        data = _json.loads(metadata_json) if metadata_json else {}
    except (ValueError, TypeError):
        return default
    tid = data.get("tenant_id") if isinstance(data, dict) else None
    return tid or default
```

In `entrypoint`, after the `identity` parse (line 206) and before the customer seed, set the contextvar for the whole job:

```python
    from noble_agent.tenant.current import set_current_tenant

    set_current_tenant(_job_tenant(getattr(caller, "metadata", "") or "", settings.tenant_id))
```

(No reset — the job runs in its own subprocess/task; the contextvar dies with it. `NobleAgent.create` inside `RoomSession`/`voice_agent` then captures this per-job tenant. Fallback = `settings.tenant_id`, so today's single-tenant deploy is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_worker_tenant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/transport/livekit/worker.py tests/unit/unified/test_worker_tenant.py
git commit -m "feat(voice): resolve per-job tenant from participant metadata + set contextvar"
```

---

### Task 8: Set the tenant contextvar at the chat (WS) entry boundary

**Files:**
- Modify: `src/noble_agent/server/text_chat.py:224` (`handle_text_session` gains optional `tenant_id`), `src/noble_agent/server/ws_handler.py:98` (pass the optional tenant, default `None`)
- Test: `tests/unit/unified/test_text_chat_tenant.py` (create)

**Interfaces:**
- Consumes: `set_current_tenant` (Task 1).
- Produces: `handle_text_session(ws, session_id, *, tenant_id: str | None = None)` — sets the contextvar for the session (fallback settings).

**Note:** chat carries no tenant today (audit A3). Phase-1 default is `None` → contextvar unset → `current_tenant()` falls back to `settings.tenant_id` (byte-identical single-tenant dev). The optional param is the forward-compatible seam the gateway/provision fills later; the de-globalize test (Task 10) drives it via `use_tenant`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_text_chat_tenant.py
import inspect
from noble_agent.server import text_chat


def test_handle_text_session_accepts_tenant_id():
    sig = inspect.signature(text_chat.handle_text_session)
    assert "tenant_id" in sig.parameters
    assert sig.parameters["tenant_id"].default is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_text_chat_tenant.py -v`
Expected: FAIL — no `tenant_id` parameter.

- [ ] **Step 3: Implement**

`handle_text_session` (224): change the signature and set the contextvar first:

```python
async def handle_text_session(ws: Any, session_id: str, *, tenant_id: str | None = None) -> None:
    from noble_agent.tenant.current import set_current_tenant

    if tenant_id:
        set_current_tenant(tenant_id)
    ...  # rest unchanged
```

`ws_handler.py` (98): pass through (chat has no tenant today → `None`, keeping fallback):

```python
            await text_chat.handle_text_session(ws, session_id, tenant_id=None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_text_chat_tenant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/text_chat.py src/noble_agent/server/ws_handler.py tests/unit/unified/test_text_chat_tenant.py
git commit -m "feat(chat): optional per-session tenant sets contextvar (fallback settings)"
```

---

### Task 9: Grep-audit sweep — no `settings.tenant_id` / `get_tenant_context().tenant_id` left on the request/data path

**Files:**
- Audit (read-only grep) across `src/noble_agent/`; fix any newly-found request-path read the same way (route through `current_tenant()`).
- Test: none new — this task's deliverable is a clean grep + the existing suite staying green.

**Interfaces:** none produced; this closes the memo §120 "session nhận phải làm một pass audit riêng."

- [ ] **Step 1: Run the audit greps**

```bash
grep -rn "settings.tenant_id\|get_settings().tenant_id" src/noble_agent/ | grep -v "def _tenant_id\|pg_data_plane\|pg_provisioning"
grep -rn "get_tenant_context()" src/noble_agent/
grep -rn "\.tenant_id" src/noble_agent/agent src/noble_agent/semcache
```

- [ ] **Step 2: Classify each hit**

For each remaining hit decide: **request/data path** (must use `current_tenant()`), or **process-level infra** (heartbeat emitter `server/http.py:1027`, worker registration `worker.py:271,299`, `app_session.py:241` dispatch-name) which is out of scope this phase (record in the Change Log exclusion). Known already-handled request-path reads: `orchestrator.py:378` (Task 4), `agent/tools/schemas.py:633,668,683`, `agent/tools/projects_info.py:108`, `semcache/sandbox.py:116` — these call `get_tenant_context()` (no `.tenant_id` needed for the ctx object) and are now tenant-correct **because the turn runs under `use_tenant(self.tenant_id)`** (Task 6). Verify each is reached only inside a turn (under the wrap); if any runs at build time, confirm build is also wrapped (it is — `_build_runner_for_version`/`_build_runner` wrap).

- [ ] **Step 3: Fix any genuine request-path leak found**

For any hit that is on the request/data path and NOT covered by the turn-wrap (e.g. a helper called from a fire-and-forget task created without copying context), replace the `settings.tenant_id` read with `current_tenant()` (import from `noble_agent.tenant.current`). Add a focused unit test reproducing the leak first (TDD).

- [ ] **Step 4: Run the full unit suite**

Run: `make test-unit`
Expected: baseline pass count from CLAUDE.md, **0 new failures**.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(tenant): route remaining request-path tenant reads through current_tenant()"
```

---

### Task 10: De-globalize isolation test (the §9 "XONG" gate)

**Files:**
- Test: `tests/unit/tenant/test_deglobalize_isolation.py` (create)

**Interfaces:**
- Consumes everything above. Two bundle-backed tenants exist in the package: `noble` and `demo_acme` (audit). Use them so the test is hermetic.

- [ ] **Step 1: Write the test**

```python
# tests/unit/tenant/test_deglobalize_isolation.py
"""§9 de-globalize gate: two tenants interleaved in ONE process each get their
own TenantContext / provider instance / find_project index — no bleed."""
from noble_agent.config import reset_settings_for_tests
from noble_agent.tenant.current import use_tenant
from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests
from noble_agent.data import providers
from noble_agent.agent.tools import find_project
from noble_agent.data.project_matching.index import ProjectNameIndex


def test_two_tenants_do_not_bleed(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    reset_tenant_context_for_tests()
    providers.reset_for_tests()

    idx_noble = ProjectNameIndex([{"code": "NBL", "name": "N", "region": "", "type": ""}])
    idx_acme = ProjectNameIndex([{"code": "ACM", "name": "A", "region": "", "type": ""}])
    find_project.set_index(idx_noble, tenant="noble")
    find_project.set_index(idx_acme, tenant="demo_acme")

    # Interleave: noble → acme → noble → acme
    for _ in range(2):
        with use_tenant("noble"):
            assert get_tenant_context().tenant_id == "noble"
            assert find_project.get_index() is idx_noble
        with use_tenant("demo_acme"):
            assert get_tenant_context().tenant_id == "demo_acme"
            assert find_project.get_index() is idx_acme
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/unit/tenant/test_deglobalize_isolation.py -v`
Expected: PASS (both tenants stay isolated across interleaving)

- [ ] **Step 3: Full gate + lint**

Run: `make test-unit && make lint`
Expected: baseline pass, 0 new failures; ruff clean on every touched file.

- [ ] **Step 4: Update CLAUDE.md (self-maintenance)**

Edit the **Architecture** section: note tenant is now per-request via `tenant/current.py` (`current_tenant()`), `get_tenant_context()`/`find_project` index/provider `_INSTANCES`/facade `_runners` are tenant-keyed, and the process-level infra dispatch (`agent_dispatch_name(settings.tenant_id)` in worker/heartbeat/app_session) is deliberately still process-scoped (infra phase). Append a Change Log row (date 2026-07-31, what changed, why) — same commit.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/tenant/test_deglobalize_isolation.py CLAUDE.md
git commit -m "test(tenant): de-globalize isolation gate + CLAUDE.md sync"
```

---

## Self-Review

**Spec coverage (memo §5b table):**
- `settings.tenant_id` on data-path → contextvar: Tasks 1, 6, 9. ✅
- ProjectNameIndex module-singleton → per-tenant: Tasks 3, 4. ✅
- `db_project_registry._cache` per-tenant: covered transitively — the registry delegates to the now per-tenant provider (Task 5), no direct edit needed. ✅
- Provider/data-source per tenant context: Task 5. ✅
- `_runners` keyed `(tenant, version)`: Task 6. ✅
- `get_tenant_context()` singleton → per-request: Task 2. ✅
- Grep audit pass (memo §120): Task 9. ✅
- Transports keep voice/chat separate + set contextvar (memo §0.5, §3): Tasks 7, 8. ✅
- §9 de-globalize test: Task 10. ✅
- PG `_tenant_id()` (`pg_data_plane.py:221`) → deferred to **Plan 2** (Option C RLS) which owns the whole PG-tenant thread. Noted, not a gap.

**Placeholder scan:** no TBD/"handle errors"/"similar to Task N" — every code step has real code. ✅

**Type consistency:** `set_index(idx, *, tenant=None)`, `get_index(*, tenant=None)`, `current_tenant() -> str`, `NobleAgent.create(..., *, tenant_id=None)`, `_runners: OrderedDict[tuple[str,int], TurnRunner]` used consistently across Tasks 3/4/6/10. ✅

**Out-of-scope carried forward:** PG tenant thread → Plan 2; noisy-neighbor (hipporag PPR offload, chat admission cap) → Plan 3; process-level dispatch registration → infra phase.
