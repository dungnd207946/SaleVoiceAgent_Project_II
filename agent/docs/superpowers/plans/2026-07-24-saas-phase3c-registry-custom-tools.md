# SaaS Phase 3c — ToolSpec Registry + Custom Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dispatcher's hand-written `if/elif` chain with a `ToolSpec` registry so a tenant can add its own custom tool (with its own executor calling the tenant's provider) by dropping one file in `tenants/<id>/tools/` — without touching core dispatch. Behaviour is **identical** for the 12 standard Noble tools; custom-tool support is proven by a test-only fixture tenant.

**Architecture:** `agent/tools/registry.py` holds a `ToolSpec` (frozen: name, schema, executor, `dirties_customer`, `read_only`, `tenant`) keyed by `(tenant, name)`. Standard tools register as built-ins (`tenant="*"`) in `agent/tools/builtins.py` via thin adapter executors that call the existing tool-module functions unchanged (preserving every arg-massage: `_default_project_code`, booking routing). The dispatcher's outer `dispatch()` wrapper — which enforces the hot-path invariants (on_tool_start/done, crash handling, customer-dirty signal, auto-escalate, display-items strip) — is **untouched**; only `_exec()` becomes `registry.resolve(tenant, name).executor(...)`. `_DIRTIES_CUSTOMER` → `ToolSpec.dirties_customer`; semcache's `_READ_ONLY_TOOLS` → `ToolSpec.read_only`. The tenant loader imports `tenants/<id>/tools/` (if present) so `@tool`-decorated custom tools self-register.

**Tech Stack:** Python 3.11–3.13, frozen dataclasses, pytest (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- **Branch:** `feat/refactor2` only. Never touch `develop`; no push/PR/merge/worktree/rebase without explicit user instruction. Local commits on `feat/refactor2` are fine.
- **Behaviour-identical for the 12 standard tools.** Same dispatch result, same customer-dirty rebuild timing, same auto-escalate, same display-items strip, same semcache read/write classification. Every existing dispatcher/booking/auto-escalate/sandbox test must stay green with no assertion changes (except where a test reads the now-removed `_DIRTIES_CUSTOMER`/`_READ_ONLY_TOOLS` symbol directly — those update to the registry).
- **Hot-path invariants preserved (do NOT regress):** in `runner.py`, tool_calls with empty `id`/`name` are dropped (unchanged, not in scope); on interrupt mid-loop, `{"interrupted": true}` placeholders are injected (unchanged); the dispatcher rebuilds the system prompt when a tool sets customer-dirty. The dispatcher's `dispatch()` body stays behaviourally identical.
- **`read_only` flags must reproduce the CURRENT `_READ_ONLY_TOOLS` set EXACTLY** (behaviour-identity for semcache): `read_only=True` for `noble_search`, `discover_projects`, `get_project_overview`, `recommend_units`, `get_project_financial`, `search_units`, `crm_lookup`; `read_only=False` for everything else (incl. `check_inventory`, `find_project`, `update_customer`, `escalate`, `send_media`, `verify_identity`, `support_ticket`, `booking`). `booking` stays **action-special-cased** in the sandbox (`check_availability`/`list` read-only) — the flag alone does not decide booking.
- **`dirties_customer` reproduces the CURRENT set EXACTLY:** `True` only for `update_customer`. `booking` stays **action-special-cased** in `dispatch()` (`schedule` dirties) — its flag is `False`.
- Commit message final line, verbatim: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Reply to the user in Vietnamese.

---

## File Structure

- `src/noble_agent/agent/tools/registry.py` — **create**: `ToolSpec`, `_REGISTRY`, `register`, `tool` decorator, `resolve`, `registered_names`, `clear_tenant_for_tests`.
- `src/noble_agent/agent/tools/builtins.py` — **create**: adapter executors + `ToolSpec` registration for the 12 standard tools (`tenant="*"`).
- `src/noble_agent/agent/tools/dispatcher.py` — **modify**: `_exec` → registry lookup; `dispatch()` resolves the spec once and reads `spec.dirties_customer`; add `tenant` + `provider` access; expose `default_project_code`. Import `builtins` for registration side-effect. Drop `_DIRTIES_CUSTOMER`.
- `src/noble_agent/agent/orchestrator.py` — **modify**: pass `tenant=` when constructing `ToolDispatcher`.
- `src/noble_agent/semcache/sandbox.py` — **modify**: `_is_write_tool` reads `registry.resolve(tenant,name).read_only` (booking special-case kept); pass `tenant=` to its `ToolDispatcher`.
- `src/noble_agent/tenant/loader.py` — **modify**: after building the context, import `tenants/<id>/tools/` (if present) so custom tools self-register.
- `tests/fixtures/tenant_acme/` — **create**: a fixture tenant with `manifest.toml` + `persona/` + `tools/loan.py` (a custom tool) to prove registration + isolation.
- `tests/unit/tools/{test_registry.py,test_builtins.py}` — **create**.
- `tests/unit/tenant/test_custom_tool_loading.py` — **create**.

---

## Task 1: `registry.py` — ToolSpec + registry primitives

**Files:**
- Create: `src/noble_agent/agent/tools/registry.py`
- Test: `tests/unit/tools/test_registry.py`

**Interfaces:**
- Produces:
  - `ToolSpec(name: str, schema: dict, executor: Callable[..., Awaitable[str]], dirties_customer: bool = False, read_only: bool = True, tenant: str = "*")` — frozen.
  - `register(spec: ToolSpec) -> None`.
  - `tool(*, name, schema, tenant="*", dirties_customer=False, read_only=True)` — decorator registering the wrapped async fn as a `ToolSpec` and returning it unchanged.
  - `resolve(tenant: str, name: str) -> ToolSpec | None` — tenant-specific `(tenant,name)` first, else built-in `("*",name)`, else `None`.
  - `registered_names(tenant: str) -> set[str]` — names visible to a tenant (its own + built-ins).
  - `clear_tenant_for_tests(tenant: str) -> None` — remove that tenant's entries (never touches `"*"`).

- [ ] **Step 1: Write the failing test** — create `tests/unit/tools/__init__.py` (empty) and `tests/unit/tools/test_registry.py`:

```python
import pytest

from noble_agent.agent.tools import registry as reg


@pytest.fixture(autouse=True)
def _clean():
    reg.clear_tenant_for_tests("acme")
    yield
    reg.clear_tenant_for_tests("acme")


async def _dummy(args, **_):
    return "ok"


def test_register_and_resolve_builtin():
    reg.register(reg.ToolSpec(name="zzz_test_builtin", schema={}, executor=_dummy))
    spec = reg.resolve("noble", "zzz_test_builtin")
    assert spec is not None and spec.tenant == "*" and spec.read_only is True


def test_tenant_specific_shadows_builtin():
    reg.register(reg.ToolSpec(name="find_project", schema={}, executor=_dummy, tenant="acme"))
    assert reg.resolve("acme", "find_project").tenant == "acme"
    assert reg.resolve("noble", "find_project").tenant == "*"  # noble unaffected


def test_resolve_unknown_returns_none():
    assert reg.resolve("noble", "does_not_exist") is None


def test_decorator_registers():
    @reg.tool(name="acme_custom", schema={"x": 1}, tenant="acme", read_only=False, dirties_customer=True)
    async def _fn(args, **_):
        return "hi"

    spec = reg.resolve("acme", "acme_custom")
    assert spec.executor is _fn and spec.read_only is False and spec.dirties_customer is True
    assert spec.schema == {"x": 1}


def test_registered_names_includes_builtins_and_own():
    reg.register(reg.ToolSpec(name="acme_only", schema={}, executor=_dummy, tenant="acme"))
    names = reg.registered_names("acme")
    assert "acme_only" in names
    assert "acme_only" not in reg.registered_names("noble")


def test_tool_spec_frozen():
    from dataclasses import FrozenInstanceError

    s = reg.ToolSpec(name="x", schema={}, executor=_dummy)
    with pytest.raises(FrozenInstanceError):
        s.name = "y"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tools/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.agent.tools.registry'`.

- [ ] **Step 3: Write the implementation** — `src/noble_agent/agent/tools/registry.py`:

```python
"""ToolSpec registry — the single dispatch table for built-in + custom tools.

Built-in (standard) tools register under ``tenant="*"``. A tenant's custom
tools register under their own id and shadow a built-in of the same name for
that tenant only. The dispatcher resolves ``(tenant, name)`` → ``ToolSpec`` and
calls its executor; semcache reads ``read_only``; the dispatcher reads
``dirties_customer``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict
    executor: Callable[..., Awaitable[str]]
    dirties_customer: bool = False
    read_only: bool = True
    tenant: str = "*"


_REGISTRY: dict[tuple[str, str], ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    _REGISTRY[(spec.tenant, spec.name)] = spec


def tool(*, name, schema, tenant="*", dirties_customer=False, read_only=True):
    """Decorator: register the wrapped async executor as a ToolSpec."""

    def deco(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        register(
            ToolSpec(
                name=name,
                schema=schema,
                executor=fn,
                dirties_customer=dirties_customer,
                read_only=read_only,
                tenant=tenant,
            )
        )
        return fn

    return deco


def resolve(tenant: str, name: str) -> ToolSpec | None:
    return _REGISTRY.get((tenant, name)) or _REGISTRY.get(("*", name))


def registered_names(tenant: str) -> set[str]:
    return {n for (t, n) in _REGISTRY if t in ("*", tenant)}


def clear_tenant_for_tests(tenant: str) -> None:
    if tenant == "*":
        return
    for key in [k for k in _REGISTRY if k[0] == tenant]:
        del _REGISTRY[key]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tools/test_registry.py -v`
Expected: PASS (6).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/registry.py tests/unit/tools/__init__.py tests/unit/tools/test_registry.py
git commit -m "feat(tools): ToolSpec registry (register/tool decorator/resolve)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `builtins.py` — register the 12 standard tools

**Files:**
- Create: `src/noble_agent/agent/tools/builtins.py`
- Test: `tests/unit/tools/test_builtins.py`

**Interfaces:**
- Consumes: `registry.register` + `ToolSpec` (Task 1); `schemas.SCHEMAS`; the existing tool modules; a `dispatcher.default_project_code(args)` helper (Task 3 exposes it — for Task 2 the adapters take `dispatcher` and call `dispatcher.default_project_code`, which Task 3 adds; import ordering is fine because the call happens at dispatch time, not import time).
- Produces: on import, registers 12 built-in `ToolSpec`s (`tenant="*"`). Executors take `(args, *, ...bag...)` and return `str`.

Adapter executor bag: every executor is `async def _x(args, *, state, customer, callbacks, session_id, provider, tenant, rag, dispatcher) -> str` — declare only what's used plus `**_`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/tools/test_builtins.py`:

```python
from noble_agent.agent.tools import builtins as _b  # noqa: F401 — import registers
from noble_agent.agent.tools import registry as reg

# The exact behaviour-identity contract copied from the pre-refactor code.
READ_ONLY = {
    "noble_search", "discover_projects", "get_project_overview", "recommend_units",
    "get_project_financial", "search_units", "crm_lookup",
}
DIRTIES = {"update_customer"}
ALL_12 = {
    "find_project", "update_customer", "noble_search", "discover_projects",
    "get_project_overview", "get_project_financial", "search_units",
    "recommend_units", "booking", "escalate", "send_media", "check_inventory",
}


def test_all_standard_tools_registered_as_builtins():
    for name in ALL_12 | {"crm_lookup", "verify_identity", "support_ticket"}:
        spec = reg.resolve("noble", name)
        assert spec is not None and spec.tenant == "*", name


def test_read_only_flags_match_legacy_set():
    for name in READ_ONLY:
        assert reg.resolve("noble", name).read_only is True, name
    # Spot-check writes (behaviour-identity with the old _READ_ONLY_TOOLS set):
    for name in ("update_customer", "find_project", "check_inventory", "booking", "send_media", "escalate"):
        assert reg.resolve("noble", name).read_only is False, name


def test_dirties_customer_flags_match_legacy_set():
    assert reg.resolve("noble", "update_customer").dirties_customer is True
    for name in ALL_12 - {"update_customer"}:
        assert reg.resolve("noble", name).dirties_customer is False, name


def test_builtin_schema_is_the_canonical_schema():
    from noble_agent.agent.tools.schemas import SCHEMAS
    assert reg.resolve("noble", "booking").schema is SCHEMAS["booking"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tools/test_builtins.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.agent.tools.builtins'`.

- [ ] **Step 3: Write the implementation** — `src/noble_agent/agent/tools/builtins.py`:

```python
"""Built-in (standard) tool registrations — thin adapters over the existing
tool modules, preserving every arg-massage. Imported for its registration
side effect. Behaviour-identical to the pre-registry dispatcher `_exec`."""

from __future__ import annotations

from noble_agent.agent.tools import (
    booking,
    check_inventory,
    find_project,
    noble_search,
    project_financial,
    projects_info,
    support_ops,
    update_customer,
)
from noble_agent.agent.tools.registry import ToolSpec, register
from noble_agent.agent.tools.schemas import SCHEMAS

_BOOKING_NEEDS_PROJECT_ACTIONS = {"check_availability", "schedule"}


async def _update_customer(args, *, customer, **_):
    return await update_customer.run(customer, args)


async def _noble_search(args, *, dispatcher, rag, **_):
    return await noble_search.run(rag, dispatcher, args)


async def _find_project(args, *, dispatcher, **_):
    return await find_project.run(dispatcher, args)


async def _discover_projects(args, **_):
    return await projects_info.discover_projects(args)


async def _get_project_overview(args, *, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await projects_info.get_project_overview(args)


async def _recommend_units(args, *, state, customer, **_):
    return await projects_info.recommend_units(args, state=state, customer=customer)


async def _get_project_financial(args, *, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await project_financial.get_project_financial(args)


async def _search_units(args, *, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await project_financial.search_units(args)


async def _check_inventory(args, *, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await check_inventory.run(args)


async def _booking(args, *, state, customer, session_id, dispatcher, **_):
    if args.get("action") in _BOOKING_NEEDS_PROJECT_ACTIONS:
        dispatcher.default_project_code(args)
    return await booking.run(state, customer, args, session_id=session_id)


async def _crm_lookup(args, **_):
    return await support_ops.crm_lookup(args)


async def _verify_identity(args, *, state, **_):
    return await support_ops.verify_identity(state, args)


async def _support_ticket(args, **_):
    return await support_ops.support_ticket(args)


async def _escalate(args, *, state, customer, **_):
    return await support_ops.escalate(state, customer, args)


async def _send_media(args, *, customer, session_id, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await support_ops.send_media(customer, args, session_id=session_id)


# (name, executor, dirties_customer, read_only)
_BUILTINS = [
    ("update_customer", _update_customer, True, False),
    ("noble_search", _noble_search, False, True),
    ("find_project", _find_project, False, False),
    ("discover_projects", _discover_projects, False, True),
    ("get_project_overview", _get_project_overview, False, True),
    ("recommend_units", _recommend_units, False, True),
    ("get_project_financial", _get_project_financial, False, True),
    ("search_units", _search_units, False, True),
    ("check_inventory", _check_inventory, False, False),
    ("booking", _booking, False, False),
    ("crm_lookup", _crm_lookup, False, True),
    ("verify_identity", _verify_identity, False, False),
    ("support_ticket", _support_ticket, False, False),
    ("escalate", _escalate, False, False),
    ("send_media", _send_media, False, False),
]

for _name, _fn, _dirty, _ro in _BUILTINS:
    register(ToolSpec(name=_name, schema=SCHEMAS.get(_name, {}), executor=_fn, dirties_customer=_dirty, read_only=_ro))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tools/test_builtins.py -v`
Expected: PASS (4). (`default_project_code` is only called at dispatch time, so importing `builtins` before Task 3 adds that method is fine — registration doesn't invoke executors.)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/builtins.py tests/unit/tools/test_builtins.py
git commit -m "feat(tools): register 12 standard tools as ToolSpec built-ins (adapters)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Rewire the dispatcher to the registry

**Files:**
- Modify: `src/noble_agent/agent/tools/dispatcher.py`
- Modify: `src/noble_agent/agent/orchestrator.py`
- Test: existing `tests/unit/unified/test_*dispatch*`, `test_auto_escalate.py`, `test_booking*.py` (must stay green); add `tests/unit/tools/test_dispatch_registry.py`.

**Interfaces:**
- Consumes: `registry.resolve` (Task 1), `builtins` registrations (Task 2), `get_provider` (existing).
- Produces:
  - `ToolDispatcher(state, customer, rag, callbacks, session_id, tenant="noble")` — new `tenant` kwarg (default `"noble"` for back-compat with direct unit tests).
  - `ToolDispatcher.default_project_code(args)` — public (was `_default_project_code`).
  - `ToolDispatcher.provider` property — `get_provider(get_settings())` (lazy).
  - `_exec(name, args)` → resolve spec, call `spec.executor(args, **bag)`; unknown → `{"error": f"unknown tool {name}"}`.
  - `dispatch()` reads `spec.dirties_customer` (booking `schedule` still special-cased). `_DIRTIES_CUSTOMER` removed.

- [ ] **Step 1: Write the failing test** — create `tests/unit/tools/test_dispatch_registry.py`:

```python
import json

import pytest

from noble_agent.agent.tools.dispatcher import ToolDispatcher


class _CB:
    interrupt_check = None
    def __init__(self): self.starts = []; self.dones = []
    async def on_tool_start(self, n, a): self.starts.append((n, a))
    async def on_tool_done(self, n, r): self.dones.append((n, r))


class _State:
    def __init__(self): self.scratchpad = {}; self.history = []


class _Cust:
    project_interest = "NCLB"


async def test_unknown_tool_returns_error():
    d = ToolDispatcher(state=_State(), customer=_Cust(), rag=None, callbacks=_CB(), session_id="s")
    out = await d.dispatch({"function": {"name": "nope", "arguments": "{}"}})
    assert json.loads(out)["error"] == "unknown tool nope"


async def test_default_project_code_fills_from_customer():
    d = ToolDispatcher(state=_State(), customer=_Cust(), rag=None, callbacks=_CB(), session_id="s")
    args = {}
    d.default_project_code(args)
    assert args["project_code"] == "NCLB"


async def test_update_customer_sets_dirty_via_spec(monkeypatch):
    import noble_agent.agent.tools.builtins  # noqa: F401
    d = ToolDispatcher(state=_State(), customer=_Cust(), rag=None, callbacks=_CB(), session_id="s")

    async def _fake_run(customer, args):  # patch the underlying executor target
        return json.dumps({"ok": True})

    monkeypatch.setattr("noble_agent.agent.tools.update_customer.run", _fake_run)
    await d.dispatch({"function": {"name": "update_customer", "arguments": "{}"}})
    assert d.consume_customer_dirty() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tools/test_dispatch_registry.py -v`
Expected: FAIL — `default_project_code` doesn't exist / unknown-tool path differs / dirty not set through the registry path.

- [ ] **Step 3: Rewrite the dispatcher** — in `src/noble_agent/agent/tools/dispatcher.py`:

At the top, replace the tool-module imports block and `ESCALATE_SIGNAL` import with:

```python
from noble_agent.agent.tools import builtins as _builtins  # noqa: F401 — registers built-ins
from noble_agent.agent.tools import registry, support_ops
from noble_agent.config import get_settings
from noble_agent.data.providers import ESCALATE_SIGNAL, get_provider
```

Delete the `_DIRTIES_CUSTOMER` constant (keep `_BOOKING_DIRTYING_ACTIONS` and `_BOOKING_NEEDS_PROJECT_ACTIONS` — the latter is now only used by the booking adapter in `builtins.py`, so **remove `_BOOKING_NEEDS_PROJECT_ACTIONS` from dispatcher.py**; keep `_BOOKING_DIRTYING_ACTIONS`). Keep `_DISPLAY_ITEMS_TOOLS` + `_strip_display_items` unchanged.

Change `__init__` and add helpers:

```python
    def __init__(self, state, customer, rag, callbacks, session_id: str, tenant: str = "noble"):
        self.state = state
        self.customer = customer
        self.rag = rag
        self.callbacks = callbacks
        self.session_id = session_id
        self.tenant = tenant
        self._customer_dirty = False
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_provider(get_settings())
        return self._provider

    def default_project_code(self, args: dict) -> None:
        """Default an empty `project_code` arg to the customer's sticky project."""
        if not args.get("project_code"):
            args["project_code"] = getattr(self.customer, "project_interest", "") or ""
```

(Delete the old private `_default_project_code`.)

In `dispatch()`, resolve the spec once and use its flag. Replace the customer-dirty block:

```python
        if not crashed and (
            name in _DIRTIES_CUSTOMER or (name == "booking" and args.get("action") in _BOOKING_DIRTYING_ACTIONS)
        ):
            self._customer_dirty = True
```

with:

```python
        spec = registry.resolve(self.tenant, name)
        if not crashed and (
            (spec is not None and spec.dirties_customer)
            or (name == "booking" and args.get("action") in _BOOKING_DIRTYING_ACTIONS)
        ):
            self._customer_dirty = True
```

Replace the whole `_exec` method with:

```python
    async def _exec(self, name: str, args: dict) -> str:
        spec = registry.resolve(self.tenant, name)
        if spec is None:
            return json.dumps({"error": f"unknown tool {name}"})
        return await spec.executor(
            args,
            state=self.state,
            customer=self.customer,
            callbacks=self.callbacks,
            session_id=self.session_id,
            provider=self.provider,
            tenant=self.tenant,
            rag=self.rag,
            dispatcher=self,
        )
```

`_auto_escalate` stays as-is (still calls `support_ops.escalate`).

- [ ] **Step 4: Pass `tenant` at the orchestrator construction site** — in `src/noble_agent/agent/orchestrator.py` where `ToolDispatcher(...)` is built (around line 371), add `tenant=get_tenant_context().tenant_id` (import `from noble_agent.tenant.loader import get_tenant_context` lazily/at top). If the orchestrator already holds a tenant id, use that; otherwise the default `"noble"` is correct — but wire it explicitly:

```python
        from noble_agent.tenant.loader import get_tenant_context

        dispatcher = ToolDispatcher(
            state=state,
            customer=customer,
            rag=self._rag,
            callbacks=callbacks,
            session_id=sid,
            tenant=get_tenant_context().tenant_id,
        )
```

- [ ] **Step 5: Run the dispatch + behaviour-identity suites**

Run: `pytest tests/unit/tools/test_dispatch_registry.py tests/unit/unified/test_auto_escalate.py tests/unit/unified/test_booking_guard.py tests/unit/unified/test_booking_phone.py tests/unit/unified/test_send_media.py tests/unit/unified/test_search_units_custom_filter.py -v`
Expected: PASS (the dispatch behaviour is unchanged; `default_project_code` still fills project_code; auto-escalate still fires; booking still routes).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/tools/dispatcher.py src/noble_agent/agent/orchestrator.py tests/unit/tools/test_dispatch_registry.py
git commit -m "refactor(tools): dispatcher _exec via ToolSpec registry (behaviour-identical)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Semcache sandbox reads `read_only` from the registry

**Files:**
- Modify: `src/noble_agent/semcache/sandbox.py`
- Test: `tests/unit/tools/test_sandbox_readonly.py` (new) + existing semcache tests stay green.

**Interfaces:**
- Consumes: `registry.resolve` (Task 1), `builtins` (Task 2).
- Produces: `_is_write_tool(tool_call, tenant="noble")` classifies via `registry.resolve(tenant, name).read_only`; `booking` action special-case unchanged; an unknown/unresolved tool is treated as a write (conservative, unchanged). The sandbox `ToolDispatcher(...)` passes `tenant=`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/tools/test_sandbox_readonly.py`:

```python
import noble_agent.agent.tools.builtins  # noqa: F401 — registers built-ins
from noble_agent.semcache.sandbox import _is_write_tool


def _tc(name, args="{}"):
    return {"function": {"name": name, "arguments": args}}


def test_read_only_tools_are_not_writes():
    for name in ("noble_search", "discover_projects", "get_project_overview",
                 "recommend_units", "get_project_financial", "search_units", "crm_lookup"):
        assert _is_write_tool(_tc(name)) is False, name


def test_write_tools_are_writes():
    for name in ("update_customer", "send_media", "escalate", "find_project", "check_inventory"):
        assert _is_write_tool(_tc(name)) is True, name


def test_booking_action_special_case():
    assert _is_write_tool(_tc("booking", '{"action":"check_availability"}')) is False
    assert _is_write_tool(_tc("booking", '{"action":"list"}')) is False
    assert _is_write_tool(_tc("booking", '{"action":"schedule"}')) is True


def test_unknown_tool_is_write():
    assert _is_write_tool(_tc("mystery")) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tools/test_sandbox_readonly.py -v`
Expected: FAIL — `_is_write_tool` currently uses the module-level `_READ_ONLY_TOOLS` set; the new-signature/registry behaviour isn't there yet (test for `find_project`/`check_inventory` as writes already passes by luck, but the intent is registry-sourced — the failing assertions guide the refactor). If all pass by coincidence, still do Step 3 to source from the registry (delete the duplicated set).

- [ ] **Step 3: Rewrite `_is_write_tool`** — in `src/noble_agent/semcache/sandbox.py`, delete the `_READ_ONLY_TOOLS` set and replace `_is_write_tool`:

```python
import noble_agent.agent.tools.builtins  # noqa: F401 — ensures built-ins are registered
from noble_agent.agent.tools import registry

_READ_ONLY_BOOKING_ACTIONS: set[str] = {"check_availability", "list"}


def _is_write_tool(tool_call: dict, tenant: str = "noble") -> bool:
    name = tool_call["function"]["name"]
    if name == "booking":
        try:
            args = json.loads(tool_call["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            return True
        return args.get("action") not in _READ_ONLY_BOOKING_ACTIONS
    spec = registry.resolve(tenant, name)
    if spec is None:
        return True  # unknown → conservative write (unchanged)
    return not spec.read_only
```

Also pass `tenant=` to the sandbox's `ToolDispatcher(...)` construction (around line 124): add `tenant=get_tenant_context().tenant_id` with a lazy `from noble_agent.tenant.loader import get_tenant_context`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/tools/test_sandbox_readonly.py tests/unit/unified/ -k "semcache or sandbox" -v`
Expected: PASS. (semcache is off by default; these tests exercise the classifier directly.)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/semcache/sandbox.py tests/unit/tools/test_sandbox_readonly.py
git commit -m "refactor(semcache): read tool read_only from the registry (drop duplicated set)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Custom-tool loading + fixture-tenant isolation proof

**Files:**
- Modify: `src/noble_agent/tenant/loader.py` (import the tenant's `tools/` package)
- Create: `tests/fixtures/tenant_acme/{manifest.toml,persona/{SOUL.md,RULES.md,PROMPT_TEMPLATE.md,CUSTOMER_PROFILE.md,config.json},tools/__init__.py,tools/loan.py}`
- Test: `tests/unit/tenant/test_custom_tool_loading.py`

**Interfaces:**
- Consumes: `registry.tool` decorator (Task 1), `load_tenant` (Phase 3ab).
- Produces: `loader.load_tenant(...)` imports `noble_agent.tenants.<id>.tools` (if the package exists) so `@tool`-decorated executors self-register. A helper `loader._import_tenant_tools(tenant_id)` (importlib, swallow `ModuleNotFoundError` for a tenant with no `tools/`, re-raise other import errors).

Note: the fixture tenant lives under `tests/fixtures/`, not the package, so the test imports it by manipulating the module path directly (it does not need `load_tenant`'s package-based import — it validates the registration mechanism + isolation via `registry`).

- [ ] **Step 1: Write the failing test** — create the fixture custom tool `tests/fixtures/tenant_acme/tools/__init__.py` (empty) and `tests/fixtures/tenant_acme/tools/loan.py`:

```python
from noble_agent.agent.tools.registry import tool

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_loan",
        "description": "Kiểm tra điều kiện vay (custom tool của Acme).",
        "parameters": {"type": "object", "properties": {"amount": {"type": "number"}}, "required": []},
    },
}


@tool(name="check_loan", schema=_SCHEMA, tenant="acme", read_only=True)
async def check_loan(args, *, provider, tenant, **_):
    return f"acme-loan:{tenant}:{args.get('amount', 0)}"
```

Then `tests/unit/tenant/test_custom_tool_loading.py`:

```python
import importlib

import pytest

from noble_agent.agent.tools import registry as reg


@pytest.fixture(autouse=True)
def _clean():
    reg.clear_tenant_for_tests("acme")
    yield
    reg.clear_tenant_for_tests("acme")


def test_custom_tool_registers_and_is_isolated():
    # Importing the fixture tenant's tools module runs the @tool decorator.
    importlib.import_module("tests.fixtures.tenant_acme.tools.loan")
    acme = reg.resolve("acme", "check_loan")
    assert acme is not None and acme.tenant == "acme" and acme.read_only is True
    # Isolation: noble cannot see acme's custom tool.
    assert reg.resolve("noble", "check_loan") is None
    assert "check_loan" not in reg.registered_names("noble")
    assert "check_loan" in reg.registered_names("acme")


async def test_custom_tool_executor_receives_tenant_and_provider():
    importlib.import_module("tests.fixtures.tenant_acme.tools.loan")
    spec = reg.resolve("acme", "check_loan")
    out = await spec.executor({"amount": 5}, provider=object(), tenant="acme")
    assert out == "acme-loan:acme:5"


def test_loader_import_tenant_tools_no_tools_dir_is_noop():
    from noble_agent.tenant import loader
    # noble has no tools/ package yet → must not raise.
    loader._import_tenant_tools("noble")
```

Also create the fixture persona so a future `load_tenant("acme")` would be valid (minimal): `tests/fixtures/tenant_acme/manifest.toml`:

```toml
tenant_id = "acme"
data_source = "nbx"
persona_dir = "persona"

[tools]
enabled = ["check_loan"]
```

and `tests/fixtures/tenant_acme/persona/{SOUL.md,RULES.md,PROMPT_TEMPLATE.md,CUSTOMER_PROFILE.md}` (each a one-line stub) + `persona/config.json` `{"name":"Acme","model":"gemini-2.5-flash","temperature":0.7,"max_tokens":800}`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_custom_tool_loading.py -v`
Expected: FAIL — `loader._import_tenant_tools` doesn't exist.

- [ ] **Step 3: Add `_import_tenant_tools` to the loader** — in `src/noble_agent/tenant/loader.py`, add and call it at the end of `load_tenant` (before returning the context is fine, or right after — it must run once per tenant load):

```python
def _import_tenant_tools(tenant_id: str) -> None:
    """Import ``noble_agent.tenants.<id>.tools`` so @tool-decorated custom tools
    self-register. A tenant with no ``tools/`` package is a no-op; any other
    import error propagates (fail loud on a broken custom tool)."""
    import importlib

    try:
        importlib.import_module(f"noble_agent.tenants.{tenant_id}.tools")
    except ModuleNotFoundError as e:
        # Only swallow "the tools package itself is absent"; a missing import
        # INSIDE a present tools package must surface.
        if e.name in (f"noble_agent.tenants.{tenant_id}.tools", f"noble_agent.tenants.{tenant_id}"):
            return
        raise
```

Call it inside `load_tenant`, just before `return TenantContext(...)`:

```python
    _import_tenant_tools(tenant_id)
    return TenantContext(
        ...
    )
```

(For the `noble` tenant there is no `tools/` package yet → no-op. When a real custom tool is added later, drop it in `src/noble_agent/tenants/<id>/tools/`.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/tenant/test_custom_tool_loading.py tests/unit/tenant/test_loader.py -v`
Expected: PASS (custom tool registers, isolated from noble; loader no-op for noble).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/loader.py tests/fixtures/tenant_acme tests/unit/tenant/test_custom_tool_loading.py
git commit -m "feat(tenant): load tenants/<id>/tools for custom-tool self-registration + isolation proof

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Verification gate + changelog + ledger

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.superpowers/sdd/progress.md`

- [ ] **Step 1: Full unit suite** — `make test-unit 2>&1 | tail -5`; extract the summary + unique FAILED ids. Expected: the same known baseline (8 failures: 2 USD-normalize, 2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:', 1 local-.env media), **ZERO new**. Passed count rises by the new registry/builtins/sandbox/custom-tool tests. Confirm each failing id matches the baseline.

- [ ] **Step 2: Ruff** — `ruff check src/noble_agent/agent/tools/ src/noble_agent/semcache/sandbox.py src/noble_agent/tenant/loader.py`. Expected: clean.

- [ ] **Step 3: Behaviour-identity smoke** — confirm the dispatcher resolves + runs a standard tool end-to-end unchanged:
```bash
python -c "
import asyncio, json
import noble_agent.agent.tools.builtins  # register
from noble_agent.agent.tools import registry
assert registry.resolve('noble','booking').schema['function']['name']=='booking'
assert registry.resolve('noble','noble_search').read_only is True
assert registry.resolve('noble','update_customer').dirties_customer is True
print('OK: 15 builtins registered, flags match legacy contract')
"
```

- [ ] **Step 4: Update `CLAUDE.md`** — (a) the `agent/tools/` architecture row: note dispatch now goes through `agent/tools/registry.py` (`ToolSpec` registry) + `builtins.py`; `dirties_customer`/`read_only` are ToolSpec flags; custom tools live in `tenants/<id>/tools/`. (b) Update the "Adding a new tool" section: standard tool = add a built-in ToolSpec in `builtins.py` + schema + `manifest.enabled`; custom tenant tool = a `@tool`-decorated file in `tenants/<id>/tools/`. (c) Add a Change Log row (2026-07-24, `feat/refactor2`) summarizing the registry, behaviour-identity for the 12 standard tools, flags moved off the two module-level sets, custom-tool loading + fixture isolation proof, gate result + ZERO new failures.

- [ ] **Step 5: Append a Phase-3c section to `.superpowers/sdd/progress.md`** with each task's commit + gate result + any Minor findings.

- [ ] **Step 6: Commit** the docs.

```bash
git add CLAUDE.md
git commit -m "docs: SaaS Phase 3c (ToolSpec registry + custom tools) — changelog + gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Manual smoke note (report; do NOT merge/push)** — per `SMOKE.md`, a live `/chat` run should confirm the 12 tools still dispatch correctly (booking flow, escalate, send_media, a data tool) before prod reliance.

---

## Self-Review

**1. Spec coverage (Part 4 — custom tools via registry):**
- `ToolSpec` (name/schema/executor/dirties_customer/read_only) → Task 1. ✅ (added `tenant` for keying, per the spec's `tenant="*"` built-in model.)
- Standard tools are ToolSpecs (`tenant="*"`) → Task 2. ✅
- Dispatcher if/elif → registry lookup; `_DIRTIES_CUSTOMER` → `dirties_customer`; `_READ_ONLY_TOOLS` → `read_only` → Tasks 3, 4. ✅
- Custom tools register per tenant + assembled/loaded from `tenants/<id>/tools/` → Task 5. ✅
- Hot-path invariants preserved (outer `dispatch()` untouched: empty id/name drop is in runner; interrupt placeholder in runner; customer-dirty rebuild via flag) → Task 3 constraints. ✅
- Isolation (a fixture tenant's custom tool invisible to Noble) → Task 5. ✅

**2. Placeholder scan:** No TBD/TODO/vague error handling; full code for every new file; the 12 adapters are written out, not summarized. ✅

**3. Type consistency:** `ToolSpec(name, schema, executor, dirties_customer, read_only, tenant)` identical across Tasks 1–5. `resolve(tenant, name)` / `registered_names(tenant)` / `clear_tenant_for_tests(tenant)` names match between registry (Task 1) and every consumer (Tasks 2–5, tests). `ToolDispatcher(..., tenant="noble")` + `.default_project_code` + `.provider` match between Task 3 (def) and Task 2 (adapters call `dispatcher.default_project_code`) and the orchestrator/sandbox construction sites. Executor bag kwargs (`state, customer, callbacks, session_id, provider, tenant, rag, dispatcher`) match between the dispatcher's `_exec` call (Task 3) and every adapter signature (Task 2) + the custom-tool fixture (Task 5). `_is_write_tool(tool_call, tenant="noble")` matches between sandbox (Task 4) and its tests. ✅
