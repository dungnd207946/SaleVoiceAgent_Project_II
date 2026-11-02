# SaaS Phase 2 — Custom Tool Parameters (Tier-2 filterable) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a provider declare a **new, filterable tool parameter** (absent from the generic tool set) that auto-injects into a tool's JSON schema, is collected at dispatch, and filters results against `item.extras[maps_to]` via a declarative `match` operator — **with zero glue code in the adapter for declarative cases**.

**Architecture:** Mirror Phase 1's interim single-tenant pattern. A `ToolParamSpec` (metadata) is declared as an attribute on the active provider (like `extra_specs`), read through an `active_tool_params()` factory. A new `build_schemas(names)` deep-copies the static `SCHEMAS` and injects declared params before `load_agent_def` freezes them. A pure `custom_params` engine collects declared args and filters `list[Unit]` by `extras[maps_to]`. `search_units` is the first (and only, this phase) consumer: it builds `UnitQuery(custom_params=...)` and re-applies the declarative filter as a safety net. The dispatcher → registry refactor and custom *tools* are explicitly **deferred to Phase 3** (they need `TenantContext`).

**Tech Stack:** Python 3.11–3.13, frozen dataclasses, pytest (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- **Branch:** `feat/refactor2` only. **Never** checkout/merge/push/fetch `develop`; no `git push`/`gh pr create`/`worktree add`/`rebase --onto` without explicit user instruction. Local commits on `feat/refactor2` are fine.
- **Additive only.** No core DTO field, no tool-schema param, no provider behaviour removed. The empty-`tool_params` path (mongo / sales_api) must stay **byte-identical** to today.
- **Interim, not TenantContext.** `tool_params` live on the provider and are read via `active_tool_params()`. Phase 3 relocates them into the manifest/`TenantContext`. Do NOT introduce `tenant/`, `tenants/`, `ToolSpec`, or a registry in this phase.
- **Keep `schemas_for` unchanged** (existing tests call it directly and expect no injection). Injection lives in the new `build_schemas`.
- **`match` operators (exact set):** `eq`, `substring`, `gte`, `lte`, `exists`, `contains`. A missing `extras[maps_to]` key → item is **excluded** (for `exists` with value `False`, a missing/None key → **included**). Comparison errors (e.g. `gte` on non-numeric) → item **excluded** (safe).
- Commit message footer, verbatim last line:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Reply to the user in Vietnamese (plan file itself may stay as written).

---

## File Structure

- `src/noble_agent/data/providers/base.py` — **modify**: add `ToolParamSpec` frozen dataclass; add `custom_params` field to `UnitQuery`; add `tool_params` to the `DataProvider` Protocol.
- `src/noble_agent/data/providers/__init__.py` — **modify**: add `active_tool_params()` factory (mirror `active_extra_specs`).
- `src/noble_agent/agent/tools/custom_params.py` — **create**: pure engine (`collect_custom_params`, `filter_by_custom_params`, `TYPE_JSON` map).
- `src/noble_agent/agent/tools/schemas.py` — **modify**: add `build_schemas(names)` (deep-copy + inject `active_tool_params`). `schemas_for` untouched.
- `src/noble_agent/agent/base.py` — **modify**: `load_agent_def` calls `build_schemas(tool_names)` instead of `schemas_for(tool_names)`.
- `src/noble_agent/agent/tools/project_financial.py` — **modify**: `search_units` collects custom params → `UnitQuery(custom_params=...)` → re-applies `filter_by_custom_params` on results.
- `src/noble_agent/data/providers/nbx_mongo.py` — **modify**: declare a `tool_params` demo (`fund_type` on `search_units`).
- `tests/unit/unified/providers/test_base_contract.py` — **modify**: `FakeProvider` gains `tool_params = ()`.
- `tests/unit/unified/test_custom_params.py` — **create**: engine + operator tests.
- `tests/unit/unified/test_build_schemas.py` — **create**: injection tests.
- `tests/unit/unified/test_search_units_custom_filter.py` — **create**: end-to-end filter via a fake provider.
- `tests/unit/unified/providers/test_nbx_mongo_provider.py` — **modify**: assert nbx `tool_params` + fund_type filter behaviour.

---

## Task 1: `ToolParamSpec` DTO + `UnitQuery.custom_params` + Protocol attr

**Files:**
- Modify: `src/noble_agent/data/providers/base.py`
- Modify: `tests/unit/unified/providers/test_base_contract.py`
- Test: `tests/unit/unified/providers/test_base_contract.py`

**Interfaces:**
- Produces:
  - `base.ToolParamSpec(tool: str, name: str, type: str, description: str, maps_to: str, match: str = "eq", enum: tuple[str, ...] = ())` — frozen.
  - `base.UnitQuery.custom_params: dict[str, Any]` (default `{}`).
  - `base.DataProvider.tool_params: tuple[ToolParamSpec, ...]` (Protocol attribute).

- [ ] **Step 1: Write the failing test** — append to `tests/unit/unified/providers/test_base_contract.py`:

```python
def test_tool_param_spec_fields_and_frozen():
    from dataclasses import FrozenInstanceError

    p = base.ToolParamSpec(
        tool="search_units",
        name="fund_type",
        type="string",
        description="Loại quỹ căn khách muốn.",
        maps_to="fund_type",
    )
    assert p.match == "eq" and p.enum == ()
    with pytest.raises(FrozenInstanceError):
        p.match = "substring"  # type: ignore[misc]


def test_unit_query_custom_params_default_empty():
    q = base.UnitQuery(project_code="MCP")
    assert q.custom_params == {}
    q2 = base.UnitQuery(project_code="MCP", custom_params={"fund_type": "hot"})
    assert q2.custom_params == {"fund_type": "hot"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/providers/test_base_contract.py::test_tool_param_spec_fields_and_frozen tests/unit/unified/providers/test_base_contract.py::test_unit_query_custom_params_default_empty -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'ToolParamSpec'` and `TypeError: ... unexpected keyword argument 'custom_params'`.

- [ ] **Step 3: Write minimal implementation** — in `src/noble_agent/data/providers/base.py`:

Add the dataclass right after `ExtraFieldSpec` (before `class Capability`):

```python
@dataclass(frozen=True)
class ToolParamSpec:
    """Per-provider declaration of a NEW input parameter on a standard tool
    (Tier-2). Auto-injected into the tool's JSON schema, collected at dispatch,
    and (for declarative cases) filtered by the framework against
    ``item.extras[maps_to]`` using ``match``. The adapter needs no filter code."""

    tool: str           # target tool name, e.g. "search_units"
    name: str           # parameter name the LLM fills, e.g. "fund_type"
    type: str           # "int" | "number" | "string" | "bool" | "enum"
    description: str     # LLM-facing description
    maps_to: str        # key inside the DTO's ``extras`` dict
    match: str = "eq"   # eq | substring | gte | lte | exists | contains
    enum: tuple[str, ...] = ()
```

Add `custom_params` as the **last** field of `UnitQuery` (after `min_area_m2`), so positional construction is unchanged:

```python
    min_area_m2: float = 0.0
    custom_params: dict[str, Any] = field(default_factory=dict)
```

Add to the `DataProvider` Protocol, right after `extra_specs`:

```python
    tool_params: tuple[ToolParamSpec, ...]
```

- [ ] **Step 4: Add `tool_params = ()` to `FakeProvider`** — in `tests/unit/unified/providers/test_base_contract.py`, right after `extra_specs: tuple[base.ExtraFieldSpec, ...] = ()`:

```python
    tool_params: tuple[base.ToolParamSpec, ...] = ()
```

(Necessary: `@runtime_checkable` `isinstance` in `test_fake_provider_satisfies_protocol` checks the attribute exists.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/unified/providers/test_base_contract.py -v`
Expected: PASS (all, incl. `test_fake_provider_satisfies_protocol`).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/data/providers/base.py tests/unit/unified/providers/test_base_contract.py
git commit -m "feat(providers): ToolParamSpec + UnitQuery.custom_params + Protocol tool_params

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Pure custom-params engine (`agent/tools/custom_params.py`)

**Files:**
- Create: `src/noble_agent/agent/tools/custom_params.py`
- Test: `tests/unit/unified/test_custom_params.py`

**Interfaces:**
- Consumes: `base.ToolParamSpec` (Task 1).
- Produces:
  - `TYPE_JSON: dict[str, str]` — spec `type` → JSON-schema type (`{"int":"integer","number":"number","string":"string","bool":"boolean","enum":"string"}`).
  - `collect_custom_params(tool_name: str, args: dict, specs: tuple[ToolParamSpec, ...]) -> dict[str, Any]` — returns `{name: value}` for each spec whose `tool == tool_name` and whose `name` is present in `args` with a non-empty value (`value not in ("", None)`; `0`/`False` are kept).
  - `filter_by_custom_params(items: list, params: dict, specs: tuple[ToolParamSpec, ...]) -> list` — keeps items passing ALL params. Each item must expose `.extras: dict`. Lookup spec by `name`. Missing `extras[maps_to]` → excluded (except `exists` with `value=False` → included). Comparison error → excluded.

- [ ] **Step 1: Write the failing test** — create `tests/unit/unified/test_custom_params.py`:

```python
from dataclasses import dataclass, field
from typing import Any

from noble_agent.agent.tools import custom_params as cp
from noble_agent.data.providers.base import ToolParamSpec


@dataclass
class _Item:
    extras: dict[str, Any] = field(default_factory=dict)


SPECS = (
    ToolParamSpec(tool="search_units", name="fund_type", type="string",
                  description="", maps_to="fund_type", match="eq"),
    ToolParamSpec(tool="search_units", name="tag", type="string",
                  description="", maps_to="tag", match="substring"),
    ToolParamSpec(tool="search_units", name="min_score", type="number",
                  description="", maps_to="score", match="gte"),
    ToolParamSpec(tool="search_units", name="max_score", type="number",
                  description="", maps_to="score", match="lte"),
    ToolParamSpec(tool="search_units", name="has_promo", type="bool",
                  description="", maps_to="promo", match="exists"),
    ToolParamSpec(tool="search_units", name="amenity", type="string",
                  description="", maps_to="amenities", match="contains"),
    ToolParamSpec(tool="other_tool", name="ignored", type="string",
                  description="", maps_to="x", match="eq"),
)


def test_type_json_map():
    assert cp.TYPE_JSON == {
        "int": "integer", "number": "number", "string": "string",
        "bool": "boolean", "enum": "string",
    }


def test_collect_only_declared_for_this_tool_nonempty():
    args = {"fund_type": "hot", "ignored": "y", "tag": "", "project_code": "MCP"}
    out = cp.collect_custom_params("search_units", args, SPECS)
    # "ignored" belongs to other_tool; "tag" is empty; project_code isn't declared
    assert out == {"fund_type": "hot"}


def test_collect_keeps_zero_and_false():
    args = {"min_score": 0, "has_promo": False}
    out = cp.collect_custom_params("search_units", args, SPECS)
    assert out == {"min_score": 0, "has_promo": False}


def test_filter_eq():
    items = [_Item({"fund_type": "hot"}), _Item({"fund_type": "cold"}), _Item({})]
    out = cp.filter_by_custom_params(items, {"fund_type": "hot"}, SPECS)
    assert out == [items[0]]


def test_filter_substring_case_insensitive():
    items = [_Item({"tag": "VIP-Hot"}), _Item({"tag": "normal"})]
    out = cp.filter_by_custom_params(items, {"tag": "hot"}, SPECS)
    assert out == [items[0]]


def test_filter_gte_lte_numeric_and_bad_value_excluded():
    items = [_Item({"score": 5}), _Item({"score": 9}), _Item({"score": "NaNish"})]
    assert cp.filter_by_custom_params(items, {"min_score": 6}, SPECS) == [items[1]]
    assert cp.filter_by_custom_params(items, {"max_score": 6}, SPECS) == [items[0]]


def test_filter_exists_true_and_false():
    items = [_Item({"promo": "x"}), _Item({"promo": None}), _Item({})]
    assert cp.filter_by_custom_params(items, {"has_promo": True}, SPECS) == [items[0]]
    # value False -> keep items WITHOUT the key (missing/None)
    assert cp.filter_by_custom_params(items, {"has_promo": False}, SPECS) == [items[1], items[2]]


def test_filter_contains_list():
    items = [_Item({"amenities": ["pool", "gym"]}), _Item({"amenities": ["gym"]})]
    out = cp.filter_by_custom_params(items, {"amenity": "pool"}, SPECS)
    assert out == [items[0]]


def test_filter_all_params_must_pass():
    items = [_Item({"fund_type": "hot", "score": 9}), _Item({"fund_type": "hot", "score": 1})]
    out = cp.filter_by_custom_params(items, {"fund_type": "hot", "min_score": 5}, SPECS)
    assert out == [items[0]]


def test_filter_empty_params_returns_all():
    items = [_Item({"fund_type": "hot"}), _Item({})]
    assert cp.filter_by_custom_params(items, {}, SPECS) == items
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_custom_params.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.agent.tools.custom_params'`.

- [ ] **Step 3: Write minimal implementation** — create `src/noble_agent/agent/tools/custom_params.py`:

```python
"""Tier-2 custom-parameter engine (interim single-tenant).

Pure functions with no I/O. A provider declares a ``ToolParamSpec`` per new
parameter; this module (1) knows its JSON-schema type for injection and
(2) filters DTO items (which expose ``.extras``) against the declared value
using the spec's ``match`` operator. Declarative filtering means the adapter
writes zero filter code.
"""

from __future__ import annotations

from typing import Any

from noble_agent.data.providers.base import ToolParamSpec

TYPE_JSON: dict[str, str] = {
    "int": "integer",
    "number": "number",
    "string": "string",
    "bool": "boolean",
    "enum": "string",
}


def collect_custom_params(
    tool_name: str, args: dict, specs: tuple[ToolParamSpec, ...]
) -> dict[str, Any]:
    """Extract declared custom-param args for ``tool_name`` from ``args``.

    Keeps a value unless it is an empty string or None; ``0`` / ``False`` are
    meaningful and preserved."""
    out: dict[str, Any] = {}
    for spec in specs:
        if spec.tool != tool_name:
            continue
        if spec.name not in args:
            continue
        value = args[spec.name]
        if value in ("", None):
            continue
        out[spec.name] = value
    return out


def _matches(spec: ToolParamSpec, item_extras: dict, value: Any) -> bool:
    present = spec.maps_to in item_extras and item_extras.get(spec.maps_to) is not None
    if spec.match == "exists":
        # value truthy -> must be present; value falsy -> must be absent/None
        return present if value else not present
    if not present:
        return False
    actual = item_extras[spec.maps_to]
    try:
        if spec.match == "eq":
            return actual == value
        if spec.match == "substring":
            return str(value).lower() in str(actual).lower()
        if spec.match == "gte":
            return float(actual) >= float(value)
        if spec.match == "lte":
            return float(actual) <= float(value)
        if spec.match == "contains":
            return value in actual
    except (TypeError, ValueError):
        return False
    return False  # unknown operator -> conservative exclude


def filter_by_custom_params(
    items: list, params: dict, specs: tuple[ToolParamSpec, ...]
) -> list:
    """Return items passing ALL ``params``. Items must expose ``.extras``."""
    if not params:
        return items
    by_name = {s.name: s for s in specs}
    out = []
    for item in items:
        extras = getattr(item, "extras", {}) or {}
        if all(
            (name in by_name) and _matches(by_name[name], extras, value)
            for name, value in params.items()
        ):
            out.append(item)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_custom_params.py -v`
Expected: PASS (all 10).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/custom_params.py tests/unit/unified/test_custom_params.py
git commit -m "feat(tools): pure Tier-2 custom-param engine (collect + declarative filter)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `active_tool_params()` factory + `build_schemas` injection + `load_agent_def`

**Files:**
- Modify: `src/noble_agent/data/providers/__init__.py`
- Modify: `src/noble_agent/agent/tools/schemas.py`
- Modify: `src/noble_agent/agent/base.py`
- Test: `tests/unit/unified/test_build_schemas.py`

**Interfaces:**
- Consumes: `base.ToolParamSpec` (Task 1), `custom_params.TYPE_JSON` (Task 2), `active_extra_specs` pattern.
- Produces:
  - `providers.active_tool_params() -> tuple[base.ToolParamSpec, ...]` — for the active provider (empty if unset).
  - `schemas.build_schemas(names: list[str]) -> list[dict]` — `schemas_for(names)` deep-copied, with any declared `tool_params` whose `tool ∈ names` injected into that tool's `parameters.properties`. Never mutates the module-level `SCHEMAS`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/unified/test_build_schemas.py`:

```python
import copy

import pytest

from noble_agent.agent.tools import schemas
from noble_agent.data.providers.base import ToolParamSpec


@pytest.fixture
def patch_tool_params(monkeypatch):
    def _set(specs):
        # build_schemas reads providers.active_tool_params — patch that binding.
        import noble_agent.agent.tools.schemas as sch
        monkeypatch.setattr(sch, "active_tool_params", lambda: specs, raising=True)
    return _set


def test_build_schemas_matches_schemas_for_when_no_params(patch_tool_params):
    patch_tool_params(())
    names = ["search_units", "booking"]
    assert schemas.build_schemas(names) == schemas.schemas_for(names)


def test_build_schemas_injects_declared_param(patch_tool_params):
    patch_tool_params((
        ToolParamSpec(tool="search_units", name="fund_type", type="enum",
                      description="Loại quỹ căn.", maps_to="fund_type",
                      match="eq", enum=("hot", "normal")),
    ))
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["search_units"])}
    props = out["search_units"]["function"]["parameters"]["properties"]
    assert props["fund_type"]["type"] == "string"       # enum -> string
    assert props["fund_type"]["enum"] == ["hot", "normal"]
    assert props["fund_type"]["description"] == "Loại quỹ căn."


def test_build_schemas_skips_param_for_disabled_tool(patch_tool_params):
    patch_tool_params((
        ToolParamSpec(tool="search_units", name="fund_type", type="string",
                      description="x", maps_to="fund_type"),
    ))
    # search_units not in the enabled set -> nothing injected anywhere
    out = schemas.build_schemas(["booking"])
    booking = out[0]["function"]["parameters"]["properties"]
    assert "fund_type" not in booking


def test_build_schemas_does_not_mutate_static_SCHEMAS(patch_tool_params):
    before = copy.deepcopy(schemas.SCHEMAS["search_units"])
    patch_tool_params((
        ToolParamSpec(tool="search_units", name="fund_type", type="string",
                      description="x", maps_to="fund_type"),
    ))
    schemas.build_schemas(["search_units"])
    assert schemas.SCHEMAS["search_units"] == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_build_schemas.py -v`
Expected: FAIL — `AttributeError: module 'noble_agent.agent.tools.schemas' has no attribute 'build_schemas'` (and no `active_tool_params`).

- [ ] **Step 3a: Add `active_tool_params()`** — in `src/noble_agent/data/providers/__init__.py`, add to `__all__` and after `active_extra_specs`:

```python
def active_tool_params() -> tuple:
    """`(ToolParamSpec, ...)` declared by the active provider (empty if unset).

    Interim single-tenant lookup, mirroring active_extra_specs(). Phase 3
    threads these through TenantContext instead."""
    from noble_agent.config import get_settings

    provider = get_provider(get_settings())
    return tuple(getattr(provider, "tool_params", ()))
```

Update `__all__`:

```python
__all__ = ["get_provider", "active_extra_specs", "active_tool_params", "ESCALATE_SIGNAL", "DataProvider"]
```

- [ ] **Step 3b: Add `build_schemas`** — in `src/noble_agent/agent/tools/schemas.py`, add at the top of the file (after `from __future__`):

```python
import copy as _copy
```

Import the factory name at module scope so tests can monkeypatch the binding:

```python
from noble_agent.data.providers import active_tool_params
```

(Placed after the existing imports / near the top. This does not create a cycle: `providers/__init__` imports only `providers.base`.)

Add at the end of the file, after `schemas_for`:

```python
def build_schemas(names: list[str]) -> list[dict]:
    """Tool schemas for ``names`` with the active provider's declared Tier-2
    ``tool_params`` injected (interim single-tenant). Deep-copies so the shared
    module-level ``SCHEMAS`` is never mutated. ``schemas_for`` stays injection-free
    for callers that want the raw static schema."""
    from noble_agent.agent.tools.custom_params import TYPE_JSON

    out = [_copy.deepcopy(SCHEMAS[name]) for name in names if name in SCHEMAS]
    by_name = {s["function"]["name"]: s for s in out}
    for spec in active_tool_params():
        target = by_name.get(spec.tool)
        if target is None:
            continue  # tool not enabled this build -> param dropped
        prop: dict = {
            "type": TYPE_JSON.get(spec.type, "string"),
            "description": spec.description,
        }
        if spec.enum:
            prop["enum"] = list(spec.enum)
        target["function"]["parameters"]["properties"][spec.name] = prop
    return out
```

- [ ] **Step 3c: Use it in `load_agent_def`** — in `src/noble_agent/agent/base.py`, change the import and call:

Replace `from noble_agent.agent.tools.schemas import schemas_for` with:

```python
    from noble_agent.agent.tools.schemas import build_schemas
```

Replace `tool_schemas = schemas_for(tool_names)` with:

```python
    tool_schemas = build_schemas(tool_names)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_build_schemas.py tests/unit/unified/test_agent_def.py tests/unit/unified/test_tool_schemas.py tests/unit/unified/test_schemas_dynamic_enum.py -v`
Expected: PASS. (`test_agent_def` still sees 12 tools/names — injection adds a param, not a tool. `test_tool_schemas`/`test_schemas_dynamic_enum` call `schemas_for`, unaffected.)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/__init__.py src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/base.py tests/unit/unified/test_build_schemas.py
git commit -m "feat(tools): build_schemas injects provider tool_params into tool JSON schema

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire the filter into `search_units` (end-to-end)

**Files:**
- Modify: `src/noble_agent/agent/tools/project_financial.py`
- Test: `tests/unit/unified/test_search_units_custom_filter.py`

**Interfaces:**
- Consumes: `providers.active_tool_params` (Task 3), `custom_params.collect_custom_params` / `filter_by_custom_params` (Task 2), `base.UnitQuery.custom_params` (Task 1).
- Produces: `search_units(args)` now (a) forwards `custom_params` into `UnitQuery` (adapters MAY use it server-side later; unused today), and (b) re-applies `filter_by_custom_params` on the returned units before serialization — the framework safety net. If filtering empties the result → returns `ESCALATE_SIGNAL`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/unified/test_search_units_custom_filter.py`:

```python
import json

import pytest

from noble_agent.agent.tools import project_financial as pf
from noble_agent.data.providers import base


def _unit(code, fund):
    return base.Unit(
        project_code="MCP", project_name="X", unit_code=code, unit_type="2PN",
        unit_type_group="can_ho", bedrooms=2, area_m2=75.0, wall_area_m2=None,
        price_vnd=5_000_000_000, price_per_m2_vnd=None, direction="Đông", floor=None,
        view=None, status="available", max_discount_pct=None, image_url=None,
        extras={"fund_type": fund} if fund else {},
    )


class _Prov:
    name = "fake"
    extra_specs = ()
    tool_params = (
        base.ToolParamSpec(tool="search_units", name="fund_type", type="string",
                           description="", maps_to="fund_type", match="eq"),
    )

    def __init__(self, units):
        self._units = units
        self.last_query = None

    async def search_units(self, query):
        self.last_query = query
        return list(self._units)  # returns ALL; framework must filter


@pytest.fixture
def patched(monkeypatch):
    def _install(units):
        prov = _Prov(units)
        monkeypatch.setattr(pf.providers, "get_provider", lambda _s: prov)
        monkeypatch.setattr(pf.providers, "active_tool_params", lambda: prov.tool_params)
        monkeypatch.setattr(pf, "get_settings", lambda: object())
        return prov
    return _install


async def test_custom_param_forwarded_and_filtered(patched):
    prov = patched([_unit("A-1", "hot"), _unit("A-2", "cold"), _unit("A-3", None)])
    out = json.loads(await pf.search_units({"project_code": "MCP", "fund_type": "hot"}))
    codes = [u["unit_code"] for u in out["units"]]
    assert codes == ["A-1"]
    assert out["count"] == 1
    # forwarded to the adapter too (server-side optimization hook)
    assert prov.last_query.custom_params == {"fund_type": "hot"}


async def test_no_custom_param_returns_all(patched):
    patched([_unit("A-1", "hot"), _unit("A-2", "cold")])
    out = json.loads(await pf.search_units({"project_code": "MCP"}))
    assert out["count"] == 2


async def test_custom_filter_empty_escalates(patched):
    patched([_unit("A-1", "cold")])
    out = await pf.search_units({"project_code": "MCP", "fund_type": "hot"})
    assert out == base.ESCALATE_SIGNAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_search_units_custom_filter.py -v`
Expected: FAIL — `AttributeError` on `custom_params` in the built `UnitQuery` assertion / filter not applied (`codes == ["A-1", "A-2", "A-3"]`).

- [ ] **Step 3: Write minimal implementation** — rewrite `search_units` in `src/noble_agent/agent/tools/project_financial.py`. Add imports at top:

```python
from noble_agent.agent.tools.custom_params import collect_custom_params, filter_by_custom_params
```

Replace the `search_units` function body:

```python
async def search_units(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    specs = providers.active_tool_params()
    custom = collect_custom_params("search_units", args, specs)
    result = await provider.search_units(
        UnitQuery(
            project_code=args.get("project_code", "") or "",
            unit_type=args.get("unit_type", "") or "",
            max_price_vnd=int(args.get("max_price") or 0),
            direction=args.get("direction", "") or "",
            floor=args.get("floor") or 0,
            tower=args.get("tower", "") or "",
            unit_code=args.get("unit_code", "") or "",
            status=args.get("status", "available") or "available",
            min_area_m2=float(args.get("min_area") or 0),
            custom_params=custom,
        )
    )
    if not result:
        return ESCALATE_SIGNAL
    # Framework safety net: re-apply the declarative filter even if the adapter
    # already narrowed server-side (a superset from the adapter is never wrong).
    result = filter_by_custom_params(result, custom, specs)
    if not result:
        return ESCALATE_SIGNAL
    return json.dumps({"units": [ser.unit_json(u) for u in result], "count": len(result)}, ensure_ascii=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_search_units_custom_filter.py tests/unit/unified/test_project_financial_mongo.py -v`
Expected: PASS. (`test_project_financial_mongo` unaffected — no `tool_params` in its fake provider → `custom` is `{}` → `filter_by_custom_params` returns all.)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/project_financial.py tests/unit/unified/test_search_units_custom_filter.py
git commit -m "feat(tools): search_units collects + filters Tier-2 custom params (framework safety net)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: nbx demo `tool_params` (`fund_type` on `search_units`)

**Files:**
- Modify: `src/noble_agent/data/providers/nbx_mongo.py`
- Test: `tests/unit/unified/providers/test_nbx_mongo_provider.py`

**Interfaces:**
- Consumes: `base.ToolParamSpec` (Task 1); the already-present `extra_specs=(fund_type,)` + `_unit_from` extras fill.
- Produces: `NbxMongoProvider.tool_params = (ToolParamSpec(tool="search_units", name="fund_type", ...),)`. `mongo.py` / `sales_api.py` are **NOT** touched — `active_tool_params` uses `getattr(..., ())`, so their empty path stays byte-identical.

- [ ] **Step 1: Write the failing test** — append to `tests/unit/unified/providers/test_nbx_mongo_provider.py` (match the file's existing import style; if it imports `base` and `NbxMongoProvider`, reuse those):

```python
def test_nbx_declares_fund_type_tool_param():
    from noble_agent.data.providers.nbx_mongo import NbxMongoProvider

    specs = NbxMongoProvider().tool_params
    fund = {s.name: s for s in specs}["fund_type"]
    assert fund.tool == "search_units"
    assert fund.maps_to == "fund_type"
    assert fund.match == "eq"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/providers/test_nbx_mongo_provider.py::test_nbx_declares_fund_type_tool_param -v`
Expected: FAIL — `AttributeError: 'NbxMongoProvider' object has no attribute 'tool_params'` (or `KeyError: 'fund_type'`).

- [ ] **Step 3: Write minimal implementation** — in `src/noble_agent/data/providers/nbx_mongo.py`, add right after the `extra_specs = (...)` block (before `def __init__`):

```python
    tool_params = (
        base.ToolParamSpec(
            tool="search_units",
            name="fund_type",
            type="string",
            description=(
                "Lọc căn theo nhóm quỹ căn của nguồn (vd 'hot' = quỹ ưu tiên/nổi bật). "
                "Chỉ truyền khi khách nêu rõ muốn xem quỹ căn đó."
            ),
            maps_to="fund_type",
            match="eq",
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/providers/test_nbx_mongo_provider.py -v`
Expected: PASS (all, incl. the new one).

- [ ] **Step 5: Verify the end-to-end demo through `build_schemas` with nbx active**

Run:
```bash
python -c "
from noble_agent.config import get_settings
from noble_agent.data.providers import reset_for_tests
import os
os.environ['NOBLE_DATA_SOURCE'] = 'nbx'
reset_for_tests()
from noble_agent.agent.tools.schemas import build_schemas
s = {x['function']['name']: x for x in build_schemas(['search_units'])}
props = s['search_units']['function']['parameters']['properties']
assert 'fund_type' in props, props.keys()
print('OK: fund_type injected ->', props['fund_type'])
"
```
Expected: `OK: fund_type injected -> {'type': 'string', 'description': '...'}`.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/data/providers/nbx_mongo.py tests/unit/unified/providers/test_nbx_mongo_provider.py
git commit -m "feat(providers): nbx declares fund_type as a Tier-2 filterable tool param

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Verification gate + changelog + ledger

**Files:**
- Modify: `CLAUDE.md` (Change Log row)
- Modify: `.superpowers/sdd/progress.md` (Phase-2 section)

- [ ] **Step 1: Full unit suite + ruff**

Run: `make test-unit 2>&1 | tail -30`
Expected: only the **pre-existing baseline failures** from the Phase-1 ledger (7 known + 1 local `.env` `test_config_media_search_defaults`). **ZERO new failures.** Record the exact pass/fail counts.

Run: `ruff check src/noble_agent/data/providers/base.py src/noble_agent/data/providers/__init__.py src/noble_agent/data/providers/nbx_mongo.py src/noble_agent/agent/tools/custom_params.py src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/project_financial.py src/noble_agent/agent/base.py`
Expected: clean (no findings).

- [ ] **Step 2: Confirm empty-`tool_params` byte-identity for mongo/sales_api**

Run:
```bash
python -c "
import os
os.environ['NOBLE_DATA_SOURCE']='mongo'
from noble_agent.data.providers import reset_for_tests, active_tool_params
reset_for_tests()
assert active_tool_params()==(), active_tool_params()
from noble_agent.agent.tools.schemas import build_schemas, schemas_for
assert build_schemas(['search_units'])==schemas_for(['search_units'])
print('OK mongo: build_schemas == schemas_for (no injection)')
"
```
Expected: `OK mongo: ...`.

- [ ] **Step 3: Add a Change Log row to `CLAUDE.md`** (top of the `## Change Log` table), dated `2026-07-24`, branch `feat/refactor2`, summarizing: Tier-2 custom filterable tool params — `ToolParamSpec` + `UnitQuery.custom_params`, `active_tool_params()` interim factory, `build_schemas` injection (schemas_for untouched), pure `custom_params` engine (6 match operators), `search_units` collect+filter safety net, nbx `fund_type` demo; registry/custom-tools deferred to Phase 3; empty path byte-identical; ZERO new test failures.

- [ ] **Step 4: Append a Phase-2 section to `.superpowers/sdd/progress.md`** recording each task's commit + the gate result.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .superpowers/sdd/progress.md
git commit -m "docs: SaaS Phase 2 (custom params) — changelog + ledger + verification gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Manual smoke (report to user; do NOT merge/push)**

Note in the final report that — per `SMOKE.md`, because this touches the tool-schema build and the `search_units` path — a live `/chat` run should confirm the LLM sees `fund_type` on `search_units` and that a `fund_type` filter narrows results, before prod reliance. Do not merge/push/PR (branch rule).

---

## Self-Review

**1. Spec coverage (Part 2 — custom tool parameters):**
- Tier-2 declaration with description/type/enum/maps_to/match → `ToolParamSpec` (Task 1). ✅
- Schema build injects param into target tool → `build_schemas` (Task 3). ✅
- Dispatch collects declared args into a generic dict → `collect_custom_params` fed into `UnitQuery.custom_params` (Tasks 2, 4). ✅ (Interim: collection happens in the `search_units` tool fn, not a registry-based dispatcher — the dispatcher→registry refactor is Phase 3 per the chosen scope. Equivalent, localized.)
- Framework compares `unit.extras[maps_to]` via `match`; adapter needs zero filter code → `filter_by_custom_params` (Tasks 2, 4). ✅
- `query.custom_params` always passed to the adapter; framework re-applies as safety net → Task 4. ✅
- Declarative operators `eq|substring|gte|lte|exists|contains` → Task 2. ✅
- Complex/`apply_custom_filter` adapter hook → **explicitly out of scope this phase** (no adapter needs it; the safety-net filter covers declarative cases). Documented, not silently dropped.
- **Deferred to Phase 3 (not in this plan, by the chosen scope):** `ToolSpec` registry, dispatcher if/elif → registry lookup, custom *tools*, `TenantContext`. ✅ consistent with the user's decision.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code; every test shows assertions. ✅

**3. Type consistency:** `ToolParamSpec(tool,name,type,description,maps_to,match,enum)` identical across Tasks 1–5. `UnitQuery(..., custom_params=...)` matches the Task-1 field. `active_tool_params()` returns a tuple everywhere it's consumed (Tasks 3, 4). `collect_custom_params`/`filter_by_custom_params` signatures match between Task 2 (def) and Task 4 (call). `TYPE_JSON` keys match spec `type` values. ✅
