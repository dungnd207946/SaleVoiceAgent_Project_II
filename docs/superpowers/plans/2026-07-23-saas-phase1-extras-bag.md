# SaaS Phase 1 — Extras Bag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the canonical DTOs a typed `extras` bag with per-provider metadata, so a provider can surface a field the core schema does not model — rendered to the LLM with a Vietnamese label inline and described in a system-prompt appendix — without touching core DTO fields, tool schemas, or other providers.

**Architecture:** Add `ExtraFieldSpec` + an `extras: dict` field to `Unit`/`ProjectOverview` in `base.py`; providers expose an `extra_specs` tuple (metadata). The serializer renders `extras` with labels looked up from the active provider's specs (shape A — label inline). The orchestrator folds a "Trường dữ liệu bổ sung" appendix (generated from those specs) into the frozen `customer_block` at first-turn bootstrap, mirroring the existing short-term-memory fold. Demonstrated end-to-end by mapping `nbx_units.fundType` (currently dropped) to a `fund_type` extra.

**Tech Stack:** Python 3.11–3.13, frozen dataclasses, pytest (`asyncio_mode=auto`), ruff (line-length 120), motor (Mongo, mocked in tests).

## Global Constraints

- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `ruff check` + `ruff format` on every changed file.
- Canonical units unchanged: price = VND int, area = m² float, `status` ∈ `available|sold|booked|unknown`.
- **Additive only** — do NOT remove or rename any existing core DTO field, tool schema, or serializer key in this phase. Relocating existing Noble-specific fields (`wall_area_m2`, `price_early_vnd`, …) into extras is deferred to Phase 3.
- Missing field → `None`/absent, never fabricated.
- Extras output shape = **A**: label inline in JSON (e.g. `"Loại quỹ căn": "hot"`), value verbatim.
- Branch `feat/refactor2`. Never touch `develop`. Commit locally on the feature branch only.
- Tests are `async def` (pytest-asyncio auto mode); no `@pytest.mark.asyncio` needed.

---

## Files

- Modify: `src/noble_agent/data/providers/base.py` — add `ExtraFieldSpec`, `extras` field on `Unit`/`ProjectOverview`, `extra_specs` on the `DataProvider` Protocol.
- Modify: `src/noble_agent/data/providers/__init__.py` — add `active_extra_specs()` helper.
- Modify: `src/noble_agent/data/providers/_serialize.py` — render labeled extras in `unit_json`/`overview_json`.
- Modify: `src/noble_agent/data/providers/nbx_mongo.py` — declare `extra_specs`, populate `fund_type` extra.
- Modify: `src/noble_agent/agent/prompts/builder.py` — add `render_extras_appendix()`.
- Modify: `src/noble_agent/agent/orchestrator.py:180-193` — fold the appendix into `customer_block` at bootstrap.
- Test: `tests/unit/unified/providers/test_extras.py` (new) — DTO + serializer + helper.
- Test: `tests/unit/unified/providers/test_nbx_mongo_provider.py` (extend) — `fund_type` extra.
- Test: `tests/unit/unified/test_extras_appendix.py` (new) — appendix rendering.

---

### Task 1: `ExtraFieldSpec` + `extras` bag on DTOs + Protocol

**Files:**
- Modify: `src/noble_agent/data/providers/base.py`
- Test: `tests/unit/unified/providers/test_extras.py`

**Interfaces:**
- Produces:
  - `base.ExtraFieldSpec(key: str, label: str, entity: str, type: str, unit: str = "", description: str = "", enum: tuple[str, ...] = ())` — frozen dataclass.
  - `base.Unit.extras: dict[str, Any]` (default `{}`).
  - `base.ProjectOverview.extras: dict[str, Any]` (default `{}`).
  - `DataProvider.extra_specs: tuple[ExtraFieldSpec, ...]` (Protocol attribute; concrete providers default to `()`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/providers/test_extras.py`:

```python
"""ExtraFieldSpec + extras bag on the canonical DTOs."""

from __future__ import annotations

from noble_agent.data.providers import base


def _unit(**kw):
    defaults = dict(
        project_code="NCLB", project_name="P", unit_code="A-1", unit_type="2PN",
        unit_type_group="can_ho", bedrooms=2, area_m2=75.0, wall_area_m2=None,
        price_vnd=5_000_000_000, price_per_m2_vnd=None, direction="Đông",
        floor=None, view=None, status="available", max_discount_pct=None,
        image_url=None,
    )
    defaults.update(kw)
    return base.Unit(**defaults)


def test_extra_field_spec_is_frozen():
    spec = base.ExtraFieldSpec(key="fund_type", label="Loại quỹ căn", entity="unit", type="string")
    assert spec.key == "fund_type" and spec.entity == "unit"
    assert spec.unit == "" and spec.enum == ()


def test_unit_extras_defaults_empty_and_is_settable():
    assert _unit().extras == {}
    u = _unit(extras={"fund_type": "hot"})
    assert u.extras == {"fund_type": "hot"}


def test_overview_extras_defaults_empty():
    ov = base.ProjectOverview(code="NCLB", name="P")
    assert ov.extras == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/unified/providers/test_extras.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'ExtraFieldSpec'` (and `unexpected keyword argument 'extras'`).

- [ ] **Step 3: Implement in `base.py`**

Add the `Any` import at the top (change `from typing import Protocol, runtime_checkable`):

```python
from typing import Any, Protocol, runtime_checkable
```

Add the spec dataclass just before the `# ── DTOs` section:

```python
@dataclass(frozen=True)
class ExtraFieldSpec:
    """Per-provider metadata for a field outside the canonical core. Drives the
    serializer's labeled output and the system-prompt appendix so the LLM can
    understand a field the core DTOs do not model."""

    key: str            # key inside the DTO's ``extras`` dict
    label: str          # LLM/human-facing label, e.g. "Loại quỹ căn"
    entity: str         # "unit" | "project" | "pricing"
    type: str           # "int" | "number" | "string" | "bool" | "enum"
    unit: str = ""      # "vnd" | "m2" | "pct" | "" — rendering + LLM understanding
    description: str = ""
    enum: tuple[str, ...] = ()
```

Add `extras` as the LAST field of `Unit` (after `price_loan_vnd`):

```python
    price_loan_vnd: int | None = None        # priceLoan — vay
    extras: dict[str, Any] = field(default_factory=dict)
```

Add `extras` as the LAST field of `ProjectOverview` (after `product`):

```python
    product: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
```

Add `extra_specs` to the `DataProvider` Protocol (after `capabilities`):

```python
    name: str
    capabilities: frozenset[Capability]
    extra_specs: tuple[ExtraFieldSpec, ...]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/unified/providers/test_extras.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Confirm no regression on the existing provider suite**

Run: `python -m pytest tests/unit/unified/providers/ -q`
Expected: all pass (the three providers construct `Unit`/`ProjectOverview` without `extras`, defaulting to `{}`; `extra_specs` is not yet set on the concrete classes but the Protocol attribute is only structural — no runtime check fails).

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/noble_agent/data/providers/base.py tests/unit/unified/providers/test_extras.py
git add src/noble_agent/data/providers/base.py tests/unit/unified/providers/test_extras.py
git commit -m "feat(providers): add ExtraFieldSpec + extras bag to canonical DTOs"
```

---

### Task 2: `active_extra_specs()` + labeled-extras serialization

**Files:**
- Modify: `src/noble_agent/data/providers/__init__.py`
- Modify: `src/noble_agent/data/providers/_serialize.py`
- Test: `tests/unit/unified/providers/test_extras.py` (extend)

**Interfaces:**
- Consumes: `base.ExtraFieldSpec`, `base.Unit.extras` (Task 1).
- Produces:
  - `providers.active_extra_specs() -> dict[str, base.ExtraFieldSpec]` — `{spec.key: spec}` of the active provider, `{}` if none/unset.
  - `_serialize.labeled_extras(extras: dict, specs: dict[str, base.ExtraFieldSpec]) -> dict[str, Any]` — `{spec.label (+unit suffix): value}` for keys present in both.
  - `unit_json`/`overview_json` merge `labeled_extras(...)` (using `active_extra_specs()`) into their output.

- [ ] **Step 1: Write the failing test** (append to `test_extras.py`)

```python
from noble_agent.data.providers import _serialize


def test_labeled_extras_applies_unit_suffix():
    specs = {
        "fund_type": base.ExtraFieldSpec("fund_type", "Loại quỹ căn", "unit", "string"),
        "mgmt_fee_vnd": base.ExtraFieldSpec("mgmt_fee_vnd", "Phí quản lý", "unit", "int", unit="vnd"),
        "eff_pct": base.ExtraFieldSpec("eff_pct", "Hiệu suất", "unit", "number", unit="pct"),
    }
    out = _serialize.labeled_extras(
        {"fund_type": "hot", "mgmt_fee_vnd": 15000, "eff_pct": 7.5, "unknown": 1}, specs
    )
    assert out == {"Loại quỹ căn": "hot", "Phí quản lý (đồng)": 15000, "Hiệu suất (%)": 7.5}


def test_unit_json_merges_labeled_extras(monkeypatch):
    specs = {"fund_type": base.ExtraFieldSpec("fund_type", "Loại quỹ căn", "unit", "string")}
    monkeypatch.setattr("noble_agent.data.providers._serialize.active_extra_specs", lambda: specs)
    u = _unit(extras={"fund_type": "hot"})
    js = _serialize.unit_json(u)
    assert js["Loại quỹ căn"] == "hot"
    assert js["unit_code"] == "A-1"  # core keys still present


def test_unit_json_no_extras_when_specs_empty(monkeypatch):
    monkeypatch.setattr("noble_agent.data.providers._serialize.active_extra_specs", lambda: {})
    js = _serialize.unit_json(_unit(extras={"fund_type": "hot"}))
    assert "Loại quỹ căn" not in js and "fund_type" not in js
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/unified/providers/test_extras.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'labeled_extras'`.

- [ ] **Step 3: Implement the helper in `__init__.py`**

Add to `src/noble_agent/data/providers/__init__.py` (after `get_provider`):

```python
def active_extra_specs() -> dict:
    """`{spec.key: ExtraFieldSpec}` for the active provider (empty if unset).

    Interim single-tenant lookup: reads the provider chosen by the current
    settings. Phase 3 threads these through TenantContext instead."""
    from noble_agent.config import get_settings

    provider = get_provider(get_settings())
    return {s.key: s for s in getattr(provider, "extra_specs", ())}
```

Add `active_extra_specs` to `__all__`:

```python
__all__ = ["get_provider", "active_extra_specs", "ESCALATE_SIGNAL", "DataProvider"]
```

- [ ] **Step 4: Implement `labeled_extras` + wire into `_serialize.py`**

At the top of `src/noble_agent/data/providers/_serialize.py`, extend the import:

```python
from noble_agent.data.providers import active_extra_specs, base
```

Add the helper after the imports:

```python
_UNIT_SUFFIX = {"vnd": " (đồng)", "m2": " (m²)", "pct": " (%)"}


def labeled_extras(extras: dict, specs: dict) -> dict:
    """Render an ``extras`` dict to ``{label(+unit suffix): value}`` (shape A),
    keeping only keys that have a matching ``ExtraFieldSpec``."""
    out: dict = {}
    for key, value in (extras or {}).items():
        spec = specs.get(key)
        if spec is None:
            continue
        out[spec.label + _UNIT_SUFFIX.get(spec.unit, "")] = value
    return out
```

In `unit_json`, change the final `return {...}` to build the dict then merge:

```python
def unit_json(u: base.Unit) -> dict:
    out = {
        "unit_code": u.unit_code,
        "type": u.unit_type,
        "product_kind": u.unit_type_group,
        "wall_area_m2": u.wall_area_m2,
        "clear_area_m2": u.area_m2,
        "bedroom_count": u.bedrooms,
        "direction": u.direction or "",
        "floor": u.floor or "",
        "tower": "",
        "view": u.view or "",
        "price_vnd": u.price_vnd,
        "price_per_m2_vnd": u.price_per_m2_vnd,
        "max_discount_pct": u.max_discount_pct,
        "image_url": u.image_url or "",
        "status": u.status,
        "price_early_vnd": u.price_early_vnd,
        "price_progress_vnd": u.price_progress_vnd,
        "price_loan_vnd": u.price_loan_vnd,
    }
    out.update(labeled_extras(u.extras, active_extra_specs()))
    return out
```

In `overview_json`, likewise build `out` then `out.update(labeled_extras(ov.extras, active_extra_specs()))` before returning.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/unit/unified/providers/test_extras.py -q`
Expected: PASS.

- [ ] **Step 6: Regression + lint + commit**

```bash
python -m pytest tests/unit/unified/providers/ -q
ruff check src/noble_agent/data/providers/__init__.py src/noble_agent/data/providers/_serialize.py tests/unit/unified/providers/test_extras.py
git add src/noble_agent/data/providers/__init__.py src/noble_agent/data/providers/_serialize.py tests/unit/unified/providers/test_extras.py
git commit -m "feat(providers): serialize extras with inline VN labels (shape A)"
```

Expected: existing `test_serialize.py` still passes (providers with empty `extra_specs` add no keys).

---

### Task 3: nbx provider declares `extra_specs` + populates `fund_type`

**Files:**
- Modify: `src/noble_agent/data/providers/nbx_mongo.py`
- Test: `tests/unit/unified/providers/test_nbx_mongo_provider.py` (extend)

**Interfaces:**
- Consumes: `base.ExtraFieldSpec`, `base.Unit.extras`, `providers.active_extra_specs` (Tasks 1–2).
- Produces: `NbxMongoProvider.extra_specs: tuple[base.ExtraFieldSpec, ...]` with a `fund_type` (entity `unit`) spec; `_unit_from` fills `extras={"fund_type": ...}` when the source doc has a non-empty `fundType`.

- [ ] **Step 1: Write the failing test** (append to `test_nbx_mongo_provider.py`)

```python
async def test_unit_carries_fund_type_extra(patched_db):
    units = await NbxMongoProvider().search_units(base.UnitQuery(project_code="NCLB"))
    a1 = next(u for u in units if u.unit_code == "A-1")
    assert a1.extras == {"fund_type": "hot"}   # A-1 fixture has fundType="hot"
    a2 = next(u for u in units if u.unit_code == "A-2")
    assert a2.extras == {}                       # A-2 fixture has no fundType


def test_nbx_declares_fund_type_spec():
    specs = {s.key: s for s in NbxMongoProvider().extra_specs}
    assert "fund_type" in specs and specs["fund_type"].entity == "unit"
```

Add `"fundType": "hot"` to the A-1 unit dict in the `_units()` fixture (A-2 keeps none).

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/unified/providers/test_nbx_mongo_provider.py -q`
Expected: FAIL — `AttributeError: 'NbxMongoProvider' object has no attribute 'extra_specs'` and the extras assertion fails.

- [ ] **Step 3: Implement in `nbx_mongo.py`**

Add the spec tuple as a class attribute on `NbxMongoProvider` (after `capabilities`):

```python
    extra_specs = (
        base.ExtraFieldSpec(
            key="fund_type",
            label="Loại quỹ căn",
            entity="unit",
            type="string",
            description="Nhóm quỹ căn của nguồn (vd 'hot' = quỹ ưu tiên/nổi bật).",
        ),
    )
```

In `_unit_from`, build the extras dict and pass it:

```python
    def _unit_from(self, u: dict, code: str, project_name: str) -> base.Unit:
        ut = u.get("unitType") or {}
        extras: dict = {}
        if (fund := (u.get("fundType") or "").strip()):
            extras["fund_type"] = fund
        return base.Unit(
            project_code=code,
            project_name=project_name,
            unit_code=u.get("code") or "",
            unit_type=(ut.get("name") or "").strip(),
            unit_type_group=(ut.get("group") or "").strip(),
            bedrooms=_bedrooms(ut.get("name", "")),
            area_m2=_to_float(u.get("area")),
            wall_area_m2=_to_float(u.get("areaBuild")),
            price_vnd=_to_vnd(u.get("price")),
            price_per_m2_vnd=None,
            price_early_vnd=_to_vnd(u.get("priceTts")),
            price_progress_vnd=None,
            price_loan_vnd=None,
            direction=(u.get("direction") or None),
            floor=None,
            view=None,
            status=_canon_status(u.get("status")),
            max_discount_pct=None,
            image_url=(u.get("image") or None),
            extras=extras,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/unified/providers/test_nbx_mongo_provider.py -q`
Expected: PASS (19 tests).

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/data/providers/nbx_mongo.py tests/unit/unified/providers/test_nbx_mongo_provider.py
git add src/noble_agent/data/providers/nbx_mongo.py tests/unit/unified/providers/test_nbx_mongo_provider.py
git commit -m "feat(nbx): surface nbx_units.fundType as the fund_type extra"
```

---

### Task 4: extras appendix in the system prompt

**Files:**
- Modify: `src/noble_agent/agent/prompts/builder.py`
- Modify: `src/noble_agent/agent/orchestrator.py:180-193`
- Test: `tests/unit/unified/test_extras_appendix.py` (new)

**Interfaces:**
- Consumes: `base.ExtraFieldSpec` (Task 1), `providers.active_extra_specs` (Task 2).
- Produces: `builder.render_extras_appendix(specs) -> str` — a Markdown block, `""` when no specs. Folded into `state.scratchpad["customer_block"]` at bootstrap.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_extras_appendix.py`:

```python
"""Extras appendix rendered into the system-prompt customer block."""

from __future__ import annotations

from noble_agent.agent.prompts.builder import render_extras_appendix
from noble_agent.data.providers import base


def test_appendix_empty_when_no_specs():
    assert render_extras_appendix(()) == ""


def test_appendix_lists_unit_and_project_fields():
    specs = (
        base.ExtraFieldSpec("fund_type", "Loại quỹ căn", "unit", "string",
                            description="Nhóm quỹ căn."),
        base.ExtraFieldSpec("mgmt_fee_vnd", "Phí quản lý", "project", "int", unit="vnd",
                            description="Phí quản lý dự án."),
    )
    out = render_extras_appendix(specs)
    assert "Trường dữ liệu bổ sung" in out
    assert "Loại quỹ căn" in out and "Nhóm quỹ căn." in out
    assert "Phí quản lý" in out and "(đồng)" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/unified/test_extras_appendix.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_extras_appendix'`.

- [ ] **Step 3: Implement `render_extras_appendix` in `builder.py`**

Add to `src/noble_agent/agent/prompts/builder.py` (after the imports):

```python
from collections.abc import Iterable

from noble_agent.data.providers.base import ExtraFieldSpec

_EXTRA_UNIT_SUFFIX = {"vnd": " (đồng)", "m2": " (m²)", "pct": " (%)"}
_ENTITY_LABEL = {"unit": "Căn hộ", "project": "Dự án", "pricing": "Bảng giá"}


def render_extras_appendix(specs: Iterable[ExtraFieldSpec]) -> str:
    """Markdown appendix telling the model which extra fields tool results may
    carry (grouped by entity). Empty string when there are no specs."""
    specs = list(specs)
    if not specs:
        return ""
    lines = ["## Trường dữ liệu bổ sung",
             "Kết quả từ tool có thể kèm các trường sau (ngoài trường chuẩn):"]
    for entity in ("project", "unit", "pricing"):
        group = [s for s in specs if s.entity == entity]
        if not group:
            continue
        lines.append(f"- {_ENTITY_LABEL.get(entity, entity)}:")
        for s in group:
            label = s.label + _EXTRA_UNIT_SUFFIX.get(s.unit, "")
            desc = f" — {s.description}" if s.description else ""
            lines.append(f'  - "{label}"{desc}')
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/unified/test_extras_appendix.py -q`
Expected: PASS.

- [ ] **Step 5: Fold the appendix into the bootstrap `customer_block`**

In `src/noble_agent/agent/orchestrator.py`, add the import near the other builder import (top of file):

```python
from noble_agent.agent.prompts.builder import build_system_prompt, render_customer_block, render_extras_appendix
```

Then, inside the `_profile_loaded` bootstrap block, after the short-term-memory fold (currently line 191, right before `state.scratchpad["_profile_loaded"] = True`), append:

```python
                # Fold the active provider's extra-field appendix into the frozen
                # customer_block so the model understands non-core fields that
                # tool results may carry (Phase 1 extras bag). One-time per call.
                from noble_agent.data.providers import active_extra_specs

                appendix = render_extras_appendix(active_extra_specs().values())
                if appendix:
                    state.scratchpad["customer_block"] += "\n\n" + appendix
```

- [ ] **Step 6: Run the orchestrator + builder tests to confirm no regression**

Run: `python -m pytest tests/unit/unified/ -q -k "orchestrator or builder or extras or prompt"`
Expected: all pass (appendix is `""` under providers without specs, so existing prompt snapshots are unaffected; under `nbx` it appends the fund_type block).

- [ ] **Step 7: Lint + commit**

```bash
ruff check src/noble_agent/agent/prompts/builder.py src/noble_agent/agent/orchestrator.py tests/unit/unified/test_extras_appendix.py
git add src/noble_agent/agent/prompts/builder.py src/noble_agent/agent/orchestrator.py tests/unit/unified/test_extras_appendix.py
git commit -m "feat(prompt): fold provider extra-field appendix into bootstrap customer_block"
```

---

### Task 5: Full-suite verification + CLAUDE.md change-log

**Files:**
- Modify: `CLAUDE.md` (Change Log)

- [ ] **Step 1: Run the full unit suite**

Run: `python -m pytest tests/unit -q 2>&1 | tail -20`
Expected: no NEW failures vs the pre-existing baseline (~7 known-red per the 2026-07-22 change-log row). Record the pass/fail counts.

- [ ] **Step 2: Lint the whole changed set**

Run: `ruff check src/noble_agent/data/providers/ src/noble_agent/agent/prompts/builder.py src/noble_agent/agent/orchestrator.py tests/unit/unified/`
Expected: `All checks passed!`

- [ ] **Step 3: Code-level smoke — extras render under nbx**

Run:
```bash
python -c "
import asyncio, json
from noble_agent.data.providers import _serialize, active_extra_specs
from noble_agent.data.providers import base
u = base.Unit(project_code='NCLB', project_name='P', unit_code='A-1', unit_type='2PN',
              unit_type_group='can_ho', bedrooms=2, area_m2=75.0, wall_area_m2=None,
              price_vnd=5_000_000_000, price_per_m2_vnd=None, direction='Đông', floor=None,
              view=None, status='available', max_discount_pct=None, image_url=None,
              extras={'fund_type':'hot'})
from noble_agent.data.providers.nbx_mongo import NbxMongoProvider
import noble_agent.data.providers as P
P._INSTANCES['nbx'] = NbxMongoProvider()
import noble_agent.config as C
class S: noble_data_source='nbx'
C.get_settings = lambda: S()
print(json.dumps(_serialize.unit_json(u), ensure_ascii=False))
"
```
Expected: JSON includes `"Loại quỹ căn": "hot"` alongside the core keys.

- [ ] **Step 4: Append the CLAUDE.md change-log row**

Add under `## Change Log`, above the 2026-07-23 nbx row:

```
| 2026-07-23 | **Phase 1 of the SaaS refactor — extras bag on the canonical DTOs (additive).** `base.ExtraFieldSpec` + an `extras: dict` field on `Unit`/`ProjectOverview`; providers expose `extra_specs`. Serializer renders extras with an inline VN label (shape A) via `providers.active_extra_specs()`; `builder.render_extras_appendix()` folds a "Trường dữ liệu bổ sung" block into the bootstrap `customer_block`. Demonstrated by mapping the previously-dropped `nbx_units.fundType` → `fund_type` extra. No core DTO field/tool schema removed — relocating Noble-specific fields into extras is Phase 3. Spec `docs/superpowers/specs/2026-07-23-saas-multi-tenant-provider-tools-design.md`; plan `docs/superpowers/plans/2026-07-23-saas-phase1-extras-bag.md`. Branch `feat/refactor2`. | First step toward the SaaS provider/tool layer: lets a provider surface a field the core schema doesn't model, reaching the LLM (output + prompt) without touching core, tool schemas, or other providers — the "field mismatch" the refactor set out to fix. |
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(changelog): SaaS Phase 1 extras bag"
```

---

## Self-review notes

- **Spec coverage (Phase 1 slice):** covers the Part-1 extras mechanism (bag + `ExtraFieldSpec` + serializer shape A + prompt appendix) end-to-end. It deliberately does NOT relocate existing core fields (Phase 3), add `tool_params`/filtering (Part 2 → Phase 2), the `ToolSpec` registry (Part 4 → Phase 2), or tenant packages/persona/brand (Parts 3/5/6 → Phase 3). Those are separate plans below.
- **Type consistency:** `ExtraFieldSpec` signature and the `active_extra_specs() -> {key: spec}` / `labeled_extras(extras, specs)` / `render_extras_appendix(specs)` shapes are used identically across Tasks 1–4.
- **No placeholders:** every code step shows complete code; every run step states the exact command + expected result.

## Subsequent plans (roadmap — detailed after Phase 1 lands)

- **Phase 2 — `ToolSpec` registry + custom tool parameters.** `agent/tools/registry.py`; refactor `dispatcher.py` if/elif → registry lookup (preserve invariants: empty id/name drop, interrupt placeholder, customer-dirty rebuild); `build_schemas(ctx)` injects declared `tool_params` with `maps_to`/`match` auto-filtering; `UnitQuery.custom_params`.
- **Phase 3 — Tenant packages + neutralization.** `tenant/loader.py` + `tenant/context.py`; migrate `agent/definitions/` → `tenants/noble/persona/`; `manifest.toml` (adapter, enabled, extra_fields, tool_params, rankers, media_channel, brand); rename `noble_search` → `kb_search`; brand templating; relocate Noble-specific core fields into extras.
- **Phase 4 — Second provider.** A fixture/real second tenant proving isolation (custom field + custom tool invisible to Noble); multi-tenant SMOKE case (swap `TENANT_ID`).
