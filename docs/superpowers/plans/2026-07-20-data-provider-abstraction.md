# Data Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a swappable in-process data-provider layer so the project/unit data source (MongoDB, NBX Sales API, future sources) can change via one env var without touching tool code, tool schemas, or model-facing arguments.

**Architecture:** A `DataProvider` Protocol + canonical DTOs live in `data/providers/base.py`. Two implementations — `mongo.py` (behaviour-preserving port of today's `data/structured_data.py` + `data/db_project_registry.py` Mongo warm) and `sales_api.py` (httpx client for the public NBX Sales API) — are selected by `get_provider(settings)` keyed on `NOBLE_DATA_SOURCE`. Tools call the provider and serialise its DTOs to the **exact same JSON** the LLM sees today, so behaviour is unchanged when the source is `mongo` (the default).

**Tech Stack:** Python 3.11+, pydantic-settings (`config.py`), motor (Mongo), httpx (Sales API), pytest (`asyncio_mode=auto`).

## Global Constraints

- **Contract of record:** `docs/BA/spec_provider.md`. Every DTO/method/unit convention MUST match it. If the plan and spec disagree, fix the spec first.
- **Default source is `mongo`.** `NOBLE_DATA_SOURCE=mongo` must reproduce today's behaviour byte-for-byte in the JSON returned to the LLM. This plan does NOT flip the live roster to the Sales-API projects (that is a separate migration — see spec §7).
- **Model-facing args never change.** Tools keep `project_code` / `region` / `budget_max` etc. No `project_id`/`slug`/`uuid` ever reaches a tool arg or the LLM.
- **Never raise across the tool boundary.** Providers return `None` ("cannot answer" → `ESCALATE_SIGNAL`) or an empty wrapper ("healthy, no match") per spec §5.
- **Canonical units (spec §4):** price = VND int; area = m² float; `region`/`type`/`status` = canonical enums; missing field → `None`, never fabricated.
- **Python 3.11 target, ruff line-length 120, rules E,F,W,I,UP,B,SIM.** Heavy/optional imports stay function-local so `make test-unit` collects without live services.
- **Branch:** work on the current branch (`feat/refactor2`). Local commits only; no push/merge/PR without explicit instruction.
- `ESCALATE_SIGNAL` string is unchanged: `"Thông tin đã được chuyển đến chuyên viên tư vấn"`.

---

## File Structure

**Create:**
- `src/noble_agent/data/providers/__init__.py` — `get_provider(settings)` factory (lazy import, per-source singleton) + re-export `ESCALATE_SIGNAL`.
- `src/noble_agent/data/providers/base.py` — `DataProvider` Protocol, `Capability`, all DTOs, query objects, `ESCALATE_SIGNAL`.
- `src/noble_agent/data/providers/mongo.py` — MongoDB provider (port of `structured_data.py` + `db_project_registry` warm; adds region→macro-region mapping).
- `src/noble_agent/data/providers/sales_api.py` — NBX Sales API provider (httpx).
- `src/noble_agent/data/providers/_serialize.py` — DTO → legacy-JSON serialisers (keeps the LLM-facing JSON identical).
- `tests/unit/unified/providers/test_base_contract.py` — shared contract test + `FakeProvider`.
- `tests/unit/unified/providers/test_factory.py`
- `tests/unit/unified/providers/test_mongo_provider.py`
- `tests/unit/unified/providers/test_sales_api_provider.py`
- `tests/unit/unified/providers/test_serialize.py`

**Modify:**
- `src/noble_agent/config.py` — add `noble_data_source`, `nbx_sales_api_url`, `nbx_sales_api_timeout`, `nbx_sales_api_token`.
- `src/noble_agent/agent/tools/projects_info.py` — call provider + serialiser instead of `structured_data`.
- `src/noble_agent/agent/tools/project_financial.py` — same.
- `src/noble_agent/data/db_project_registry.py` — delegate warm/registry accessors to the active provider (keep the public surface stable for `orchestrator`/`runner`/`catalog`).
- `.env.example` — document the new vars.

**Left in place (untouched behaviour):** `data/structured_data.py` stays as-is until Task 3 moves its logic; after the port it becomes a thin re-export shim so any stray importer keeps working. `agent/catalog.py`, `orchestrator.py`, `runner.py`, `booking`/`schedule_viewing` are NOT modified (they consume `db_project_registry`, whose public API is preserved).

---

### Task 1: Contract — `base.py` DTOs, Capability, Protocol, queries

**Files:**
- Create: `src/noble_agent/data/providers/base.py`
- Test: `tests/unit/unified/providers/test_base_contract.py`

**Interfaces:**
- Produces: `ESCALATE_SIGNAL: str`; `Capability(StrEnum)`; DTOs `ProjectSummary, ProjectList, ProjectOverview, Unit, UnitTypePricing, PricingTable, UnitRecommendation, ProjectRegistryRow`; query dataclasses `UnitQuery, RecommendQuery`; `DataProvider(Protocol)` with the async methods + sync registry accessors from spec §3.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/providers/test_base_contract.py
from dataclasses import FrozenInstanceError

import pytest

from noble_agent.data.providers import base


def test_escalate_signal_value():
    assert base.ESCALATE_SIGNAL == "Thông tin đã được chuyển đến chuyên viên tư vấn"


def test_capability_members():
    assert {c.value for c in base.Capability} >= {
        "listing", "overview", "pricing", "unit_search",
        "recommend", "payment_plans", "loan_policies", "promotions", "fees",
    }


def test_unit_dto_is_frozen_and_typed():
    u = base.Unit(
        project_code="MCP", project_name="Masteri Centre Point", unit_code="A-1",
        unit_type="2PN", unit_type_group="can_ho", bedrooms=2, area_m2=75.0,
        wall_area_m2=80.0, price_vnd=5_000_000_000, price_per_m2_vnd=None, direction="Đông",
        floor=None, view=None, status="available", max_discount_pct=None, image_url=None,
    )
    assert u.price_vnd == 5_000_000_000
    with pytest.raises(FrozenInstanceError):
        u.price_vnd = 1  # type: ignore[misc]


def test_query_defaults():
    q = base.UnitQuery(project_code="MCP")
    assert q.status == "available" and q.max_price_vnd == 0
    r = base.RecommendQuery()
    assert r.limit == 6 and r.good_directions == frozenset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/providers/test_base_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.data.providers.base`

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/data/providers/base.py
"""Data-provider contract — canonical DTOs, capabilities, Protocol.

The stable boundary between agent tools and any data source (Mongo, HTTP API,
…). See docs/BA/spec_provider.md. Providers map their native fields onto these
DTOs and speak only in canonical units (price=VND int, area=m² float, region /
type / status = canonical enums). Missing field → None (never fabricated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

ESCALATE_SIGNAL = "Thông tin đã được chuyển đến chuyên viên tư vấn"


class Capability(StrEnum):
    LISTING = "listing"
    OVERVIEW = "overview"
    PRICING = "pricing"
    UNIT_SEARCH = "unit_search"
    RECOMMEND = "recommend"
    PAYMENT_PLANS = "payment_plans"
    LOAN_POLICIES = "loan_policies"
    PROMOTIONS = "promotions"
    FEES = "fees"


# ── DTOs (frozen; Optional where the field is not guaranteed) ────────────────
@dataclass(frozen=True)
class ProjectSummary:
    code: str
    name: str
    region: str
    type: str


@dataclass(frozen=True)
class ProjectList:
    count: int
    projects: list[ProjectSummary]
    region: str = ""
    note: str = ""


@dataclass(frozen=True)
class ProjectOverview:
    code: str
    name: str
    region: str | None = None
    district: str | None = None
    type: str | None = None
    investor: str | None = None
    total_units: str | None = None
    management: str | None = None
    ownership: str | None = None
    handover: str | None = None
    land_area: str | None = None
    total_investment_vnd: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class Unit:
    project_code: str
    project_name: str
    unit_code: str
    unit_type: str
    unit_type_group: str
    bedrooms: int | None
    area_m2: float | None          # diện tích sử dụng chính (thông thủy)
    wall_area_m2: float | None     # diện tích tim tường (None nếu nguồn không tách)
    price_vnd: int | None
    price_per_m2_vnd: int | None
    direction: str | None
    floor: str | None
    view: str | None
    status: str  # available | sold | booked | unknown
    max_discount_pct: float | None
    image_url: str | None


@dataclass(frozen=True)
class UnitTypePricing:
    unit_type: str
    group: str
    area_min_m2: float | None
    area_max_m2: float | None
    price_from_vnd: int | None
    price_to_vnd: int | None
    price_per_m2_from_vnd: int | None
    price_per_m2_to_vnd: int | None
    total_units: int
    available_units: int | None


@dataclass(frozen=True)
class PricingTable:
    project_code: str
    results: list[UnitTypePricing]


@dataclass(frozen=True)
class UnitRecommendation:
    units: list[Unit]


@dataclass(frozen=True)
class ProjectRegistryRow:
    code: str
    name: str
    region: str
    type: str


# ── Query objects (all values already canonical) ─────────────────────────────
@dataclass(frozen=True)
class UnitQuery:
    project_code: str
    unit_type: str = ""
    max_price_vnd: int = 0
    direction: str = ""
    floor: int = 0
    tower: str = ""
    unit_code: str = ""
    status: str = "available"
    min_area_m2: float = 0.0


@dataclass(frozen=True)
class RecommendQuery:
    region: str = ""
    budget_max_vnd: int = 0
    bedrooms: int = 0
    good_directions: frozenset[str] = field(default_factory=frozenset)
    limit: int = 6


@runtime_checkable
class DataProvider(Protocol):
    name: str
    capabilities: frozenset[Capability]

    async def list_projects(self, *, region: str = "") -> ProjectList | None: ...
    async def get_overview(self, project_code: str) -> ProjectOverview | None: ...
    async def get_pricing(
        self, project_code: str, *, unit_type: str = "", max_price_vnd: int = 0
    ) -> PricingTable | None: ...
    async def search_units(self, query: UnitQuery) -> list[Unit] | None: ...
    async def recommend_units(self, query: RecommendQuery) -> UnitRecommendation: ...

    async def get_payment_plans(self, project_code: str) -> None: ...
    async def get_loan_policies(self, project_code: str) -> None: ...
    async def get_promotions(self, project_code: str) -> None: ...
    async def get_project_fees(self, project_code: str) -> None: ...

    async def warm(self) -> None: ...
    async def warm_if_stale(self, ttl_sec: float) -> None: ...
    def registry_rows(self) -> list[ProjectRegistryRow]: ...
    def cached_codes(self) -> list[str]: ...
    def code_to_name(self) -> dict[str, str]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/providers/test_base_contract.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the shared `FakeProvider` + contract test (used by later tasks)**

```python
# append to tests/unit/unified/providers/test_base_contract.py
from noble_agent.data.providers import base


class FakeProvider:
    """Minimal in-memory provider for tool tests. Declares all capabilities."""

    name = "fake"
    capabilities = frozenset(base.Capability)

    def __init__(self, *, projects=None, units=None):
        self._projects = projects or []   # list[ProjectRegistryRow]
        self._units = units or []         # list[base.Unit]

    async def list_projects(self, *, region: str = ""):
        subs = [base.ProjectSummary(p.code, p.name, p.region, p.type) for p in self._projects]
        if region:
            subs = [s for s in subs if region == s.region]
            if not subs:
                return base.ProjectList(0, [], region=region, note="none")
            return base.ProjectList(len(subs), subs, region=region)
        return base.ProjectList(len(subs), subs)

    async def get_overview(self, project_code):
        for p in self._projects:
            if p.code == project_code:
                return base.ProjectOverview(code=p.code, name=p.name, region=p.region, type=p.type)
        return None

    async def get_pricing(self, project_code, *, unit_type="", max_price_vnd=0):
        return None

    async def search_units(self, query):
        hits = [u for u in self._units if u.project_code == query.project_code]
        return hits or None

    async def recommend_units(self, query):
        return base.UnitRecommendation(list(self._units[: query.limit]))

    async def get_payment_plans(self, c): return None
    async def get_loan_policies(self, c): return None
    async def get_promotions(self, c): return None
    async def get_project_fees(self, c): return None
    async def warm(self): ...
    async def warm_if_stale(self, ttl_sec): ...
    def registry_rows(self): return list(self._projects)
    def cached_codes(self): return [p.code for p in self._projects]
    def code_to_name(self): return {p.code: p.name for p in self._projects}


def test_fake_provider_satisfies_protocol():
    assert isinstance(FakeProvider(), base.DataProvider)
```

- [ ] **Step 6: Run + commit**

Run: `pytest tests/unit/unified/providers/test_base_contract.py -v`
Expected: PASS (5 tests)

```bash
git add src/noble_agent/data/providers/base.py tests/unit/unified/providers/test_base_contract.py
git commit -m "feat(providers): add data-provider contract (DTOs, Capability, Protocol)"
```

---

### Task 2: Config + factory

**Files:**
- Modify: `src/noble_agent/config.py` (add settings near the other `NOBLE_*` fields)
- Create: `src/noble_agent/data/providers/__init__.py`
- Modify: `.env.example`
- Test: `tests/unit/unified/providers/test_factory.py`

**Interfaces:**
- Consumes: `base.DataProvider` (Task 1).
- Produces: `get_provider(settings) -> base.DataProvider` (per-source singleton, lazy import); settings `noble_data_source`, `nbx_sales_api_url`, `nbx_sales_api_timeout`, `nbx_sales_api_token`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/providers/test_factory.py
import pytest

from noble_agent.data import providers


class _S:  # minimal settings stand-in
    def __init__(self, source): self.noble_data_source = source
    nbx_sales_api_url = "http://x"; nbx_sales_api_timeout = 1.0; nbx_sales_api_token = ""


def test_factory_returns_mongo_by_default():
    p = providers.get_provider(_S("mongo"))
    assert p.name == "mongo"


def test_factory_returns_sales_api():
    p = providers.get_provider(_S("sales_api"))
    assert p.name == "sales_api"


def test_factory_unknown_source_raises():
    with pytest.raises(ValueError):
        providers.get_provider(_S("nope"))


def test_factory_singleton_per_source():
    assert providers.get_provider(_S("mongo")) is providers.get_provider(_S("mongo"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/unified/providers/test_factory.py -v`
Expected: FAIL — `get_provider` undefined (and mongo/sales_api modules not yet present; import happens lazily so the failure is on the missing attribute).

- [ ] **Step 3: Add settings to `config.py`**

Add these fields to the `UnifiedSettings` class (place beside the other `noble_*` data fields):

```python
    # ── Data provider (see docs/BA/spec_provider.md) ─────────────────────────
    noble_data_source: str = "mongo"          # "mongo" | "sales_api"
    nbx_sales_api_url: str = "https://nbx-sales-api-dev.noble.vn"
    nbx_sales_api_timeout: float = 10.0
    nbx_sales_api_token: str = ""             # public endpoints need none; set if required
```

- [ ] **Step 4: Implement the factory**

```python
# src/noble_agent/data/providers/__init__.py
"""Data-provider factory. Selects the source by ``settings.noble_data_source``.

Lazy-imports the concrete provider so importing this package never pulls motor
or httpx unless the chosen provider needs it. One instance per source is cached
(providers hold a warmed registry cache, so a singleton is correct)."""

from __future__ import annotations

from noble_agent.data.providers.base import ESCALATE_SIGNAL, DataProvider

__all__ = ["get_provider", "ESCALATE_SIGNAL", "DataProvider"]

_INSTANCES: dict[str, DataProvider] = {}


def get_provider(settings) -> DataProvider:
    source = (getattr(settings, "noble_data_source", "") or "mongo").strip()
    cached = _INSTANCES.get(source)
    if cached is not None:
        return cached
    if source == "mongo":
        from noble_agent.data.providers.mongo import MongoProvider

        provider: DataProvider = MongoProvider()
    elif source == "sales_api":
        from noble_agent.data.providers.sales_api import SalesApiProvider

        provider = SalesApiProvider(
            base_url=settings.nbx_sales_api_url,
            timeout=settings.nbx_sales_api_timeout,
            token=settings.nbx_sales_api_token,
        )
    else:
        raise ValueError(f"Unknown NOBLE_DATA_SOURCE: {source!r} (mongo | sales_api)")
    _INSTANCES[source] = provider
    return provider


def reset_for_tests() -> None:
    _INSTANCES.clear()
```

- [ ] **Step 5: Create stub provider modules so the factory imports resolve**

Create `src/noble_agent/data/providers/mongo.py` and `sales_api.py` with a class exposing only `name` for now (fleshed out in Tasks 3 & 6):

```python
# src/noble_agent/data/providers/mongo.py
class MongoProvider:
    name = "mongo"
```

```python
# src/noble_agent/data/providers/sales_api.py
class SalesApiProvider:
    name = "sales_api"

    def __init__(self, *, base_url: str, timeout: float, token: str = ""):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._token = token
```

- [ ] **Step 6: Document env vars in `.env.example`**

Add:

```bash
# ── Data provider ─────────────────────────────────────────────────────────
NOBLE_DATA_SOURCE=mongo          # mongo | sales_api
NBX_SALES_API_URL=https://nbx-sales-api-dev.noble.vn
NBX_SALES_API_TIMEOUT=10.0
NBX_SALES_API_TOKEN=
```

- [ ] **Step 7: Run + commit**

Run: `pytest tests/unit/unified/providers/test_factory.py -v`
Expected: PASS (4 tests)

```bash
git add src/noble_agent/config.py src/noble_agent/data/providers/__init__.py \
        src/noble_agent/data/providers/mongo.py src/noble_agent/data/providers/sales_api.py \
        .env.example tests/unit/unified/providers/test_factory.py
git commit -m "feat(providers): add get_provider factory + NOBLE_DATA_SOURCE config"
```

---

### Task 3: Mongo provider (behaviour-preserving port)

**Files:**
- Modify: `src/noble_agent/data/providers/mongo.py` (full implementation)
- Modify: `src/noble_agent/data/structured_data.py` (becomes a shim after the logic moves — see Step 6)
- Test: `tests/unit/unified/providers/test_mongo_provider.py`

**Interfaces:**
- Consumes: `base.*` DTOs/queries (Task 1); `noble_agent.storage.mongo_client.get_db`; `noble_agent.agent.catalog.normalize`; `noble_agent.agent.feng_shui.direction_matches`.
- Produces: `MongoProvider` implementing every `DataProvider` method. Field-mapping logic is the existing `structured_data.py` code, returning DTOs instead of dicts. Region filtering keeps the current `_region_matches` substring behaviour (canonical macro-region mapping for Mongo is deferred — see note).

**Note on region:** the spec's macro-region enum applies to Sales API. Mongo `khu_vuc` is free text; to preserve today's behaviour byte-for-byte, `MongoProvider` keeps the existing `_region_matches` substring logic. A macro-region mapping table for Mongo is out of scope for this plan (would change current behaviour) and is tracked as a follow-up in spec §4.

- [ ] **Step 1: Write the failing test (in-memory fake db, mirrors existing `test_project_financial_mongo.py` style)**

```python
# tests/unit/unified/providers/test_mongo_provider.py
import pytest

from noble_agent.data.providers import base
from noble_agent.data.providers.mongo import MongoProvider


class _Cursor:
    def __init__(self, docs): self._docs = docs
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _Coll:
    def __init__(self, docs): self._docs = docs
    def find(self, *a, **k): return _Cursor(self._docs)
    async def find_one(self, query, projection=None):
        return self._docs[0] if self._docs else None


class _DB:
    def __init__(self, du_an, can_ho):
        self.project_du_an = _Coll(du_an)
        self.project_can_ho = _Coll(can_ho)


@pytest.fixture
def patched_db(monkeypatch):
    du_an = [{"_id": "OID1", "ma_du_an": "NCLB", "ten_thuong_mai": "Noble Crystal Long Biên",
              "khu_vuc": "Long Biên", "loai_hinh_sp": "cao_tang"}]
    can_ho = [{"du_an_id": "OID1", "ma_can": "A-1", "so_phong_ngu": 2, "loai_san_pham": "Căn hộ",
               "dien_tich_thong_thuy_m2": "75", "gia_vnd": "5000000000", "gia_m2_vnd": "66000000",
               "huong": "Đông", "trang_thai": "mở bán"}]

    async def fake_get_db():
        return _DB(du_an, can_ho)

    monkeypatch.setattr("noble_agent.data.providers.mongo.get_db", fake_get_db)
    return du_an, can_ho


async def test_list_projects_returns_dto(patched_db):
    result = await MongoProvider().list_projects()
    assert isinstance(result, base.ProjectList)
    assert result.count == 1 and result.projects[0].code == "NCLB"


async def test_search_units_maps_price_and_area(patched_db):
    units = await MongoProvider().search_units(base.UnitQuery(project_code="NCLB"))
    assert units and isinstance(units[0], base.Unit)
    assert units[0].price_vnd == 5_000_000_000 and units[0].area_m2 == 75.0


async def test_get_pricing_none_for_unknown_project(monkeypatch):
    async def fake_get_db():
        return _DB([], [])
    monkeypatch.setattr("noble_agent.data.providers.mongo.get_db", fake_get_db)
    assert await MongoProvider().get_pricing("ZZZ") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/unified/providers/test_mongo_provider.py -v`
Expected: FAIL — `MongoProvider` has no `list_projects`.

- [ ] **Step 3: Implement `MongoProvider` by porting `structured_data.py`**

Move the bodies of `structured_data.py` into `mongo.py` as methods, changing only the **return type** from dict/list-of-dict to the DTOs, and keeping every field-mapping and the `None`-vs-empty semantics identical. Concretely:

- Copy the module-level helpers verbatim into `mongo.py`: `_to_float`, `_to_int`, `_is_available`, `_unit_type_label`, `_matches_unit_type`, `_matches_status`, `_region_matches`, `_build_overview`, `_all_overview_fields_empty`, `_OVERVIEW_STRING_FIELDS`, `_AVAILABLE_HINTS`, and the resolve helpers `_resolve_du_an_id`, `_fetch_units`, `_fetch_project_doc`.
- Wrap them in the class. Each public method mirrors the matching `structured_data` function but constructs DTOs:

```python
# src/noble_agent/data/providers/mongo.py  (implementation shape — helpers omitted for brevity;
# copy them verbatim from data/structured_data.py)
from __future__ import annotations

import logging
import time

from noble_agent.agent import catalog, feng_shui
from noble_agent.data.providers import base
from noble_agent.storage.mongo_client import get_db

logger = logging.getLogger("noble_agent.data.providers.mongo")

_FALLBACK_CODES = (...)   # copy from db_project_registry._FALLBACK_CODES
_FALLBACK_NAMES = {...}   # copy from db_project_registry._FALLBACK_NAMES


class MongoProvider:
    name = "mongo"
    capabilities = frozenset({
        base.Capability.LISTING, base.Capability.OVERVIEW,
        base.Capability.PRICING, base.Capability.UNIT_SEARCH, base.Capability.RECOMMEND,
    })

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._last_warm_ts = 0.0

    async def list_projects(self, *, region: str = "") -> base.ProjectList | None:
        db = await get_db()
        if db is None:
            return None
        docs = [d async for d in db.project_du_an.find({})]
        if not docs:
            return None
        def _summ(d):
            return base.ProjectSummary(
                (d.get("ma_du_an") or "").strip(), (d.get("ten_thuong_mai") or "").strip(),
                (d.get("khu_vuc") or "").strip(), (d.get("loai_hinh_sp") or "").strip(),
            )
        if region:
            matched = [_summ(d) for d in docs if self._region_matches(d.get("khu_vuc", ""), region)]
            if not matched:
                return base.ProjectList(0, [], region=region, note="Không tìm thấy khu vực này.")
            return base.ProjectList(len(matched), matched, region=region)
        subs = [_summ(d) for d in docs]
        return base.ProjectList(len(subs), subs)

    async def search_units(self, query: base.UnitQuery) -> list[base.Unit] | None:
        units = await self._fetch_units(query.project_code)
        if not units:
            return None
        out: list[base.Unit] = []
        for u in units:
            # ... apply the SAME filters as structured_data.search_units, using
            #     query.max_price_vnd / query.min_area_m2 / query.direction / etc.
            out.append(base.Unit(
                project_code=query.project_code,
                project_name="",  # structured_data did not carry it; keep ""
                unit_code=u.get("ma_can") or "",
                unit_type=self._unit_type_label(u),
                unit_type_group=(u.get("loai_san_pham") or "").strip(),
                bedrooms=u.get("so_phong_ngu"),
                area_m2=self._to_float(u.get("dien_tich_thong_thuy_m2")) or self._to_float(u.get("dien_tich_tim_tuong_m2")),
                wall_area_m2=self._to_float(u.get("dien_tich_tim_tuong_m2")),
                price_vnd=self._to_int(u.get("gia_vnd")),
                price_per_m2_vnd=self._to_int(u.get("gia_m2_vnd")),
                direction=(u.get("huong") or "").strip(),
                floor=(u.get("dai_tang") or "").strip() or None,
                view=(u.get("tam_nhin") or "").strip() or None,
                status="available" if self._is_available(u.get("trang_thai", "")) else "unknown",
                max_discount_pct=self._to_float(u.get("chiet_khau_toi_da_pct")),
                image_url=(u.get("anh_url") or "").strip() or None,
            ))
        return out or None

    # get_pricing / get_overview / recommend_units: same 1:1 port, building
    # PricingTable / ProjectOverview / UnitRecommendation. recommend_units keeps
    # feng_shui.direction_matches and returns UnitRecommendation(units=...) RAW
    # (sorting is done by the tool — see Task 5).

    async def get_payment_plans(self, project_code): return None
    async def get_loan_policies(self, project_code): return None
    async def get_promotions(self, project_code): return None
    async def get_project_fees(self, project_code): return None

    # registry: port db_project_registry.warm / warm_if_stale / accessors here.
    async def warm(self) -> None:
        self._last_warm_ts = time.monotonic()
        db = await get_db()
        if db is None:
            return
        new: dict[str, dict] = {}
        projection = {"ma_du_an": 1, "ten_thuong_mai": 1, "khu_vuc": 1, "loai_hinh_sp": 1}
        async for d in db.project_du_an.find({}, projection):
            code = (d.get("ma_du_an") or "").strip()
            if code:
                new[code] = {"code": code, "name": (d.get("ten_thuong_mai") or "").strip(),
                             "region": (d.get("khu_vuc") or "").strip(), "type": (d.get("loai_hinh_sp") or "").strip()}
        if new:
            self._cache = new

    async def warm_if_stale(self, ttl_sec: float) -> None:
        if ttl_sec <= 0 or (time.monotonic() - self._last_warm_ts) < ttl_sec:
            return
        await self.warm()

    def registry_rows(self):
        src = self._cache or {c: {"code": c, "name": _FALLBACK_NAMES.get(c, ""), "region": "", "type": ""} for c in _FALLBACK_CODES}
        return [base.ProjectRegistryRow(v.get("code", c), v.get("name", ""), v.get("region", ""), v.get("type", "")) for c, v in src.items()]

    def cached_codes(self):
        return list(self._cache) if self._cache else list(_FALLBACK_CODES)

    def code_to_name(self):
        return {c: v.get("name", "") for c, v in self._cache.items()} if self._cache else dict(_FALLBACK_NAMES)
```

> Copy the omitted helpers and the full bodies of `get_pricing`/`get_overview`/`recommend_units` verbatim from `structured_data.py`, changing only the return construction to DTOs. Do NOT alter any filter/threshold logic.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/unit/unified/providers/test_mongo_provider.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Eliminate duplication — `structured_data.py` becomes a thin delegating shim**

`mongo.py` is now the ONLY home of the logic. Do NOT leave the ported bodies in `structured_data.py` (that would duplicate logic — a review defect). Rewrite `structured_data.py` so its public functions delegate to a shared `MongoProvider` and convert the DTO back to the legacy dict via the Task-5 serialisers. This keeps existing callers (`dispatcher`, the four test files) working until they migrate. Concretely:

```python
# src/noble_agent/data/structured_data.py  (full replacement — shim only)
"""Backward-compat shim. Logic now lives in data/providers/mongo.py. Retained
so existing importers keep working; new code should use the provider directly."""

from __future__ import annotations

from noble_agent.data.providers.base import ESCALATE_SIGNAL  # re-export
from noble_agent.data.providers.mongo import MongoProvider

_provider = MongoProvider()

# NOTE: these return the legacy dict/list shapes by asking the provider then
# converting via providers._serialize. Only the functions still imported
# elsewhere are kept (get_project_pricing, search_units, get_project_overview_data,
# list_projects_data, recommend_units_data, resolve_project_ref). Copy each
# body as: call the matching MongoProvider method → if None return None → else
# serialise to the legacy dict (see _serialize.py for the exact key mapping).
```

> Keep ONLY the function names that are still imported outside the tools (confirm with `grep -rn "structured_data\." src/ tests/`). Delete any that nothing imports. The dispatcher's `from ...structured_data import ESCALATE_SIGNAL` keeps working via the re-export.

- [ ] **Step 6: Update the four existing tests to target the shim or provider**

`test_project_financial_mongo.py`, `test_projects_info_mongo.py`, `test_recommend_units.py` patch `structured_data.get_db`. Since `get_db` now lives in `mongo.py`, repoint the monkeypatch to `noble_agent.data.providers.mongo.get_db`. `test_auto_escalate.py` uses `ESCALATE_SIGNAL` + patches `sd` — keep it working via the shim. Do NOT weaken assertions; only repoint patch targets.

- [ ] **Step 7: Commit**

Run: `pytest tests/unit/unified/providers/ tests/unit/unified/test_project_financial_mongo.py tests/unit/unified/test_projects_info_mongo.py tests/unit/unified/test_recommend_units.py tests/unit/unified/test_auto_escalate.py -v`
Expected: PASS

```bash
git add src/noble_agent/data/providers/mongo.py src/noble_agent/data/structured_data.py \
        tests/unit/unified/providers/test_mongo_provider.py tests/unit/unified/
git commit -m "feat(providers): MongoProvider — behaviour-preserving port of structured_data"
```

---

### Task 4: Registry delegation (`db_project_registry` → active provider)

**Files:**
- Modify: `src/noble_agent/data/db_project_registry.py`
- Test: `tests/unit/unified/providers/test_registry_delegation.py` (new) + existing `tests/unit/unified/test_db_project_registry.py`

**Interfaces:**
- Consumes: `providers.get_provider(get_settings())` (Task 2); provider registry accessors (Task 3).
- Produces: unchanged public surface — `warm()`, `warm_if_stale(ttl)`, `cached_codes()`, `code_to_name()`, `registry_rows()`, `set_cache_for_tests(rows)`. Callers (`orchestrator`, `runner`, `catalog`) keep working with no edits.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/providers/test_registry_delegation.py
from noble_agent.data import db_project_registry as reg
from noble_agent.data import providers
from noble_agent.data.providers.base import ProjectRegistryRow


class _StubProvider:
    name = "stub"
    def registry_rows(self): return [ProjectRegistryRow("MCP", "Masteri Centre Point", "mien_bac", "can_ho")]
    def cached_codes(self): return ["MCP"]
    def code_to_name(self): return {"MCP": "Masteri Centre Point"}
    async def warm(self): ...
    async def warm_if_stale(self, ttl): ...


def test_registry_delegates_to_active_provider(monkeypatch):
    monkeypatch.setattr(providers, "get_provider", lambda settings: _StubProvider())
    assert reg.cached_codes() == ["MCP"]
    assert reg.code_to_name()["MCP"] == "Masteri Centre Point"
    assert reg.registry_rows()[0]["code"] == "MCP"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/unified/providers/test_registry_delegation.py -v`
Expected: FAIL — `cached_codes()` returns the old bundled fallback, not the stub's `["MCP"]`.

- [ ] **Step 3: Rewrite `db_project_registry.py` to delegate**

```python
# src/noble_agent/data/db_project_registry.py
"""Public registry facade — delegates to the active DataProvider.

Kept as a stable module so orchestrator / runner / catalog need no edits when
the data source changes. All roster data now comes from the provider chosen by
NOBLE_DATA_SOURCE (see docs/BA/spec_provider.md)."""

from __future__ import annotations

import logging

from noble_agent.config import get_settings
from noble_agent.data import providers

logger = logging.getLogger("noble_agent.data.db_project_registry")

_test_rows: dict[str, dict] | None = None


def _provider():
    return providers.get_provider(get_settings())


async def warm() -> None:
    await _provider().warm()


async def warm_if_stale(ttl_sec: float) -> None:
    await _provider().warm_if_stale(ttl_sec)


def cached_codes() -> list[str]:
    if _test_rows is not None:
        return list(_test_rows)
    return _provider().cached_codes()


def code_to_name() -> dict[str, str]:
    if _test_rows is not None:
        return {c: v.get("name", "") for c, v in _test_rows.items()}
    return _provider().code_to_name()


def registry_rows() -> list[dict]:
    if _test_rows is not None:
        return [{"code": v.get("code", c), "name": v.get("name", ""),
                 "region": v.get("region", ""), "type": v.get("type", "")} for c, v in _test_rows.items()]
    return [{"code": r.code, "name": r.name, "region": r.region, "type": r.type}
            for r in _provider().registry_rows()]


def set_cache_for_tests(rows: dict[str, dict] | None) -> None:
    global _test_rows
    _test_rows = dict(rows) if rows else None
```

> `registry_rows()` still returns `list[dict]` (its historical shape) so `builder._project_table()` needs no change. `cached_codes`/`code_to_name` keep their signatures.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/unit/unified/providers/test_registry_delegation.py tests/unit/unified/test_db_project_registry.py -v`
Expected: PASS. If `test_db_project_registry.py` asserted the old private `_cache`/`_FALLBACK_*` internals, update those assertions to go through `set_cache_for_tests` + the public accessors (the fallback now lives in `MongoProvider`).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/db_project_registry.py \
        tests/unit/unified/providers/test_registry_delegation.py \
        tests/unit/unified/test_db_project_registry.py
git commit -m "refactor(registry): delegate db_project_registry to the active provider"
```

---

### Task 5: Wire tools to the provider (+ serialisers)

**Files:**
- Create: `src/noble_agent/data/providers/_serialize.py`
- Modify: `src/noble_agent/agent/tools/projects_info.py`
- Modify: `src/noble_agent/agent/tools/project_financial.py`
- Test: `tests/unit/unified/providers/test_serialize.py` + adapt existing tool tests.

**Interfaces:**
- Consumes: `get_provider` (Task 2), DTOs (Task 1), `FakeProvider` (Task 1 test helper).
- Produces: serialisers `project_list_json(ProjectList) -> dict`, `overview_json(ProjectOverview) -> dict`, `pricing_json(PricingTable) -> dict`, `unit_json(Unit) -> dict` that reproduce **exactly** today's LLM-facing JSON keys.

**Legacy JSON key contract (must match today):**
- list_projects: `{"count", "projects":[{"code","name","type","region"}], "region"?, "note"?}`
- overview: `{"code","name","region","district","type","units","management","investor","ownership","handover","land_area_m2","total_investment_vnd"}`
- pricing: `{"project","results_count","results":[{"type","category","area_min_m2","area_max_m2","price_from_vnd","price_to_vnd","price_per_m2_from_vnd","price_per_m2_to_vnd","total_units","available_units"}]}`
- search_units: `{"units":[{"unit_code","type","product_kind","wall_area_m2","clear_area_m2","bedroom_count","direction","floor","tower","view","price_vnd","price_per_m2_vnd","max_discount_pct","image_url","status"}], "count"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/providers/test_serialize.py
from noble_agent.data.providers import base
from noble_agent.data.providers import _serialize as ser


def test_project_list_json_keys():
    pl = base.ProjectList(1, [base.ProjectSummary("MCP", "Masteri", "mien_bac", "can_ho")])
    out = ser.project_list_json(pl)
    assert out["count"] == 1
    assert set(out["projects"][0]) == {"code", "name", "type", "region"}


def test_overview_json_uses_legacy_keys():
    ov = base.ProjectOverview(code="MCP", name="Masteri", total_units="480 căn", land_area="4 ha")
    out = ser.overview_json(ov)
    assert out["units"] == "480 căn"          # DTO.total_units → legacy "units"
    assert out["land_area_m2"] == "4 ha"       # DTO.land_area → legacy "land_area_m2"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/unified/providers/test_serialize.py -v`
Expected: FAIL — `_serialize` missing.

- [ ] **Step 3: Implement the serialisers**

```python
# src/noble_agent/data/providers/_serialize.py
"""DTO → legacy LLM-facing JSON. Isolated so the wire shape the model sees is
frozen independent of canonical DTO field names."""

from __future__ import annotations

from noble_agent.data.providers import base


def project_list_json(pl: base.ProjectList) -> dict:
    out: dict = {"count": pl.count,
                 "projects": [{"code": s.code, "name": s.name, "type": s.type, "region": s.region}
                              for s in pl.projects]}
    if pl.region:
        out["region"] = pl.region
    if pl.note:
        out["note"] = pl.note
    return out


def overview_json(ov: base.ProjectOverview) -> dict:
    return {
        "code": ov.code, "name": ov.name or "", "region": ov.region or "",
        "district": ov.district or "", "type": ov.type or "", "units": ov.total_units or "",
        "management": ov.management or "", "investor": ov.investor or "",
        "ownership": ov.ownership or "", "handover": ov.handover or "",
        "land_area_m2": ov.land_area or "", "total_investment_vnd": ov.total_investment_vnd,
    }


def _unit_type_pricing_json(r: base.UnitTypePricing) -> dict:
    return {"type": r.unit_type, "category": r.group,
            "area_min_m2": r.area_min_m2, "area_max_m2": r.area_max_m2,
            "price_from_vnd": r.price_from_vnd, "price_to_vnd": r.price_to_vnd,
            "price_per_m2_from_vnd": r.price_per_m2_from_vnd, "price_per_m2_to_vnd": r.price_per_m2_to_vnd,
            "total_units": r.total_units, "available_units": r.available_units}


def pricing_json(pt: base.PricingTable) -> dict:
    return {"project": pt.project_code, "results_count": len(pt.results),
            "results": [_unit_type_pricing_json(r) for r in pt.results]}


def unit_json(u: base.Unit) -> dict:
    return {"unit_code": u.unit_code, "type": u.unit_type, "product_kind": u.unit_type_group,
            "wall_area_m2": u.wall_area_m2, "clear_area_m2": u.area_m2, "bedroom_count": u.bedrooms,
            "direction": u.direction or "", "floor": u.floor or "", "tower": "",
            "view": u.view or "", "price_vnd": u.price_vnd, "price_per_m2_vnd": u.price_per_m2_vnd,
            "max_discount_pct": u.max_discount_pct, "image_url": u.image_url or "", "status": u.status}
```

> The canonical `Unit` carries both `area_m2` (thông thủy → `clear_area_m2`) and `wall_area_m2` (tim tường), plus `max_discount_pct`, so the mongo path's search_units JSON is byte-for-byte unchanged. `tower` is always `""` (already ignored upstream). Sales-API sets `wall_area_m2`/`max_discount_pct` to `None`.

- [ ] **Step 4: Rewire `projects_info.py`**

```python
# src/noble_agent/agent/tools/projects_info.py  (replace the sd calls)
import json

from noble_agent.agent import feng_shui
from noble_agent.config import get_settings
from noble_agent.data import providers
from noble_agent.data.providers import _serialize as ser
from noble_agent.data.providers.base import ESCALATE_SIGNAL, RecommendQuery


async def list_projects(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    result = await provider.list_projects(region=args.get("region", "") or "")
    if result is None:
        return ESCALATE_SIGNAL
    return json.dumps(ser.project_list_json(result), ensure_ascii=False)


async def get_project_overview(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    code = (args.get("project_code", "") or "") or (args.get("project_name", "") or "")
    result = await provider.get_overview(code)
    if result is None:
        return ESCALATE_SIGNAL
    return json.dumps(ser.overview_json(result), ensure_ascii=False)
```

For `recommend_units`, keep the feng-shui guard logic as-is but call the provider and **sort feng-shui-first in the tool** (the provider returns raw units per spec §6):

```python
async def recommend_units(args: dict, *, state, customer) -> str:
    # ... unchanged feng-shui guard + fs = feng_shui.compute(...) ...
    good = fs.good_directions if (fs and fs.applied) else frozenset()
    provider = providers.get_provider(get_settings())
    budget_max = args.get("budget_max") or 0
    rec = await provider.recommend_units(RecommendQuery(
        region=args.get("region", "") or "",
        budget_max_vnd=int(float(budget_max) * 1e9) if budget_max else 0,
        bedrooms=args.get("bedrooms") or 0,
        good_directions=good,
        limit=6,
    ))
    if rec is None:                     # provider signals a system gap → hand off
        return ESCALATE_SIGNAL
    # Provider returns RAW (unsorted, unlimited) units. Sort feng-shui-first then
    # price, and ONLY THEN take the top 6 — slicing before the sort would drop the
    # feng-shui-best units. This mirrors the old recommend_units_data (sort → [:limit]).
    units_dto = sorted(
        rec.units,
        key=lambda u: (not feng_shui.direction_matches(u.direction or "", good) if good else True,
                       u.price_vnd if u.price_vnd is not None else 10**18),
    )[:6]
    units = []
    for u in units_dto:
        fs_match = bool(good) and feng_shui.direction_matches(u.direction or "", good)
        units.append({"unit_code": u.unit_code, "type": u.unit_type, "bedroom_count": u.bedrooms,
                      "clear_area_m2": u.area_m2, "direction": u.direction or "", "view": u.view or "",
                      "price_vnd": u.price_vnd, "price_per_m2_vnd": u.price_per_m2_vnd,
                      "project_code": u.project_code, "project_name": u.project_name,
                      "feng_shui_match": fs_match, "direction_label": "hợp hướng" if fs_match else ""})
    # ... unchanged payload assembly (counts / criteria / instruction / feng_shui block) ...
```

> **Behaviour check:** `MongoProvider.recommend_units` must return units RAW (unsorted) for this to match — verify the port in Task 3 removed the in-provider sort. The old `recommend_units_data` multiplied budget by `1e9` internally; now the tool does the `*1e9` conversion (spec §4) and the provider receives VND. Update `MongoProvider.recommend_units` to compare against `query.budget_max_vnd` directly (no `*1e9`).

- [ ] **Step 5: Rewire `project_financial.py`**

```python
# src/noble_agent/agent/tools/project_financial.py
import json

from noble_agent.config import get_settings
from noble_agent.data import providers
from noble_agent.data.providers import _serialize as ser
from noble_agent.data.providers.base import ESCALATE_SIGNAL, UnitQuery


async def get_project_financial(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    project = args.get("project_code", "") or ""
    info_type = args.get("info_type", "pricing") or "pricing"
    if info_type == "pricing":
        result = await provider.get_pricing(project, unit_type=args.get("unit_type", "") or "")
        if result is None:
            return ESCALATE_SIGNAL
        return json.dumps(ser.pricing_json(result), ensure_ascii=False)
    if info_type in {"payment_plans", "loan_policies", "promotions", "fees"}:
        fn = {"payment_plans": provider.get_payment_plans, "loan_policies": provider.get_loan_policies,
              "promotions": provider.get_promotions, "fees": provider.get_project_fees}[info_type]
        return ESCALATE_SIGNAL if await fn(project) is None else json.dumps({}, ensure_ascii=False)
    return json.dumps({"error": f"Unknown info_type: {info_type}"}, ensure_ascii=False)


async def search_units(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    result = await provider.search_units(UnitQuery(
        project_code=args.get("project_code", "") or "",
        unit_type=args.get("unit_type", "") or "",
        max_price_vnd=int(args.get("max_price") or 0),
        direction=args.get("direction", "") or "",
        floor=args.get("floor") or 0,
        tower=args.get("tower", "") or "",
        unit_code=args.get("unit_code", "") or "",
        status=args.get("status", "available") or "available",
        min_area_m2=float(args.get("min_area") or 0),
    ))
    if not result:
        return ESCALATE_SIGNAL
    return json.dumps({"units": [ser.unit_json(u) for u in result], "count": len(result)}, ensure_ascii=False)
```

> `max_price` today is raw VND (Mongo), so `UnitQuery.max_price_vnd` receives it directly — no conversion for the mongo path. (The Sales-API provider converts its own tỷ→VND internally.)

- [ ] **Step 6: Adapt existing tool tests to inject `FakeProvider`**

Any test that patched `structured_data` now patches `providers.get_provider` to return a `FakeProvider` (Task 1) seeded with the needed rows/units. Run the touched suites:

Run: `pytest tests/unit/unified/ -k "project or units or recommend or list_projects" -v`
Expected: PASS (update assertions only where they asserted removed internals, not behaviour).

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/data/providers/_serialize.py \
        src/noble_agent/agent/tools/projects_info.py \
        src/noble_agent/agent/tools/project_financial.py \
        tests/unit/unified/providers/test_serialize.py tests/unit/unified/
git commit -m "refactor(tools): route project/unit tools through DataProvider + serialisers"
```

---

### Task 6: Sales API provider — mappings

**Files:**
- Modify: `src/noble_agent/data/providers/sales_api.py` (full implementation)
- Create: `src/noble_agent/data/providers/_name_code_map.py` (loads `docs/api/project_code_map.json`)
- Test: `tests/unit/unified/providers/test_sales_api_provider.py`

**Interfaces:**
- Consumes: `base.*`, httpx, `docs/api/project_code_map.json`.
- Produces: `SalesApiProvider` implementing `list_projects`, `get_overview`, `get_pricing`, `search_units`, `recommend_units`, registry accessors; capabilities = `{LISTING, OVERVIEW, PRICING, UNIT_SEARCH, RECOMMEND}`. Identity: `project_code` ↔ API `name` via the map; per-project inventory from `/projects/{slug}.units[]`, cross-project from `/hot-units`. Price `× 1e9`. `region`/`type` from API enums; unmapped filters (floor/tower/view) ignored; `status` from `units[].status` (else `"unknown"`).

- [ ] **Step 1: Write the failing test (mock httpx via a transport/monkeypatched client)**

```python
# tests/unit/unified/providers/test_sales_api_provider.py
import json

import pytest

from noble_agent.data.providers import base
from noble_agent.data.providers.sales_api import SalesApiProvider


class _Resp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): ...
    def json(self): return self._p


class _Client:
    def __init__(self, routes): self._routes = routes  # {path: payload}
    async def __aenter__(self): return self
    async def __aexit__(self, *a): ...
    async def get(self, url, params=None):
        for path, payload in self._routes.items():
            if path in url:
                return _Resp(payload)
        return _Resp({})


@pytest.fixture
def provider(monkeypatch):
    routes = {
        "/api/v1/projects/qc-masteri": {
            "id": "uuid-1", "slug": "qc-masteri", "name": "MASTERI CENTRE POINT",
            "type": "can_ho", "areaRegion": "mien_nam", "location": "TP.HCM",
            "investor": "Masterise", "overview": {"scale": "5 ha", "units_text": "1200 căn", "ownership": "Lâu dài"},
            "units": [{"code": "A-1", "price": 5.0, "area": 75.0, "areaBuild": 75.0,
                       "direction": "Đông", "status": "available",
                       "unitType": {"name": "2PN", "group": "can_ho"}, "floor": None}],
        },
        "/api/v1/projects": {"items": [{"slug": "qc-masteri", "name": "MASTERI CENTRE POINT",
                                        "type": "can_ho", "areaRegion": "mien_nam"}],
                             "total": 1, "page": 1, "pageSize": 20},
    }
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr(p, "_client", lambda: _Client(routes))
    # stub the name→code map so MASTERI CENTRE POINT → MCP
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code",
                        lambda name: {"MASTERI CENTRE POINT": "MCP"}.get(name.upper().strip(), ""))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.code_to_name_map",
                        lambda: {"MCP": "MASTERI CENTRE POINT"})
    return p


async def test_search_units_converts_price_to_vnd(provider):
    units = await provider.search_units(base.UnitQuery(project_code="MCP"))
    assert units and units[0].price_vnd == 5_000_000_000   # 5.0 tỷ → VND
    assert units[0].status == "available" and units[0].bedrooms == 2


async def test_list_projects_maps_name_to_code(provider):
    pl = await provider.list_projects()
    assert pl.projects[0].code == "MCP" and pl.projects[0].region == "mien_nam"


async def test_unknown_project_returns_none(provider, monkeypatch):
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code", lambda n: "")
    assert await provider.get_pricing("ZZZ") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/unified/providers/test_sales_api_provider.py -v`
Expected: FAIL — `SalesApiProvider.search_units` undefined.

- [ ] **Step 3: Implement the name↔code map loader**

```python
# src/noble_agent/data/providers/_name_code_map.py
"""Loads docs/api/project_code_map.json: API project name → canonical code."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("noble_agent.data.providers.name_code_map")

_MAP_PATH = Path(__file__).resolve().parents[3] / "docs" / "api" / "project_code_map.json"


@lru_cache(maxsize=1)
def _raw() -> dict[str, str]:
    try:
        data = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("name_code_map: cannot load %s: %s", _MAP_PATH, exc)
        return {}
    return {k.upper().strip(): v for k, v in data.items() if not k.startswith("_")}


def name_to_code(name: str) -> str:
    return _raw().get((name or "").upper().strip(), "")


@lru_cache(maxsize=1)
def code_to_name_map() -> dict[str, str]:
    return {v: k for k, v in _raw().items()}


def all_codes() -> list[str]:
    return list(_raw().values())
```

- [ ] **Step 4: Implement `SalesApiProvider`**

```python
# src/noble_agent/data/providers/sales_api.py
from __future__ import annotations

import logging

import httpx

from noble_agent.data.providers import base
from noble_agent.data.providers._name_code_map import (
    all_codes, code_to_name_map, name_to_code,
)

logger = logging.getLogger("noble_agent.data.providers.sales_api")


def _to_vnd(price_ty) -> int | None:
    try:
        return int(round(float(price_ty) * 1e9))
    except (TypeError, ValueError):
        return None


def _bedrooms(unit_type_name: str) -> int | None:
    s = (unit_type_name or "").strip().upper()
    if s.endswith("PN") and s[:-2].isdigit():
        return int(s[:-2])
    if s == "STUDIO":
        return 0
    return None


class SalesApiProvider:
    name = "sales_api"
    capabilities = frozenset({
        base.Capability.LISTING, base.Capability.OVERVIEW,
        base.Capability.PRICING, base.Capability.UNIT_SEARCH, base.Capability.RECOMMEND,
    })

    def __init__(self, *, base_url: str, timeout: float, token: str = ""):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._token = token
        self._cache: dict[str, dict] = {}
        self._last_warm_ts = 0.0

    def _client(self) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        return httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, headers=headers)

    async def _get(self, path: str, params: dict | None = None) -> dict | list | None:
        try:
            async with self._client() as c:
                resp = await c.get(path, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001 — never raise across the boundary
            logger.warning("sales_api GET %s failed: %s", path, exc)
            return None

    async def _slug_for(self, project_code: str) -> str | None:
        name = code_to_name_map().get(project_code.strip().upper())
        if not name:
            return None
        data = await self._get("/api/v1/projects", {"keyword": name})
        for item in (data or {}).get("items", []):
            if (item.get("name") or "").upper().strip() == name.upper().strip():
                return item.get("slug")
        return None

    def _unit_from(self, u: dict, code: str, project_name: str) -> base.Unit:
        ut = u.get("unitType") or {}
        return base.Unit(
            project_code=code, project_name=project_name, unit_code=u.get("code") or "",
            unit_type=(ut.get("name") or "").strip(), unit_type_group=(ut.get("group") or "").strip(),
            bedrooms=_bedrooms(ut.get("name", "")),
            area_m2=u.get("area") if u.get("area") is not None else u.get("areaBuild"),
            wall_area_m2=None,
            price_vnd=_to_vnd(u.get("price")), price_per_m2_vnd=None,
            direction=(u.get("direction") or None), floor=(u.get("floor") or None), view=None,
            status=(u.get("status") or "unknown"), max_discount_pct=None,
            image_url=(u.get("image") or None),
        )

    async def _project_detail(self, project_code: str) -> dict | None:
        slug = await self._slug_for(project_code)
        if not slug:
            return None
        return await self._get(f"/api/v1/projects/{slug}")

    async def list_projects(self, *, region: str = "") -> base.ProjectList | None:
        params = {"area_region": region} if region else None
        data = await self._get("/api/v1/projects", params)
        if data is None:
            return None
        subs = []
        for item in data.get("items", []):
            code = name_to_code(item.get("name", ""))
            if not code:
                continue
            subs.append(base.ProjectSummary(code, item.get("name", ""),
                                            item.get("areaRegion", ""), item.get("type", "")))
        if region and not subs:
            return base.ProjectList(0, [], region=region, note="Không tìm thấy khu vực này.")
        return base.ProjectList(len(subs), subs, region=region)

    async def get_overview(self, project_code: str) -> base.ProjectOverview | None:
        doc = await self._project_detail(project_code)
        if not doc:
            return None
        ov = doc.get("overview") or {}
        return base.ProjectOverview(
            code=project_code, name=doc.get("name") or "", region=doc.get("areaRegion"),
            district=doc.get("location"), type=doc.get("type"), investor=doc.get("investor"),
            total_units=ov.get("units_text"), ownership=ov.get("ownership"),
            land_area=ov.get("scale"), description=doc.get("description"),
        )

    async def _project_units(self, project_code: str) -> tuple[list[dict], str] | None:
        doc = await self._project_detail(project_code)
        if not doc:
            return None
        return (doc.get("units") or []), (doc.get("name") or project_code)

    async def get_pricing(self, project_code, *, unit_type="", max_price_vnd=0) -> base.PricingTable | None:
        got = await self._project_units(project_code)
        if not got or not got[0]:
            return None
        raw, pname = got
        groups: dict[str, dict] = {}
        for u in raw:
            unit = self._unit_from(u, project_code, pname)
            g = groups.setdefault(unit.unit_type or "Khác", {"group": unit.unit_type_group,
                "areas": [], "prices": [], "total": 0, "avail": 0})
            g["total"] += 1
            if unit.status == "available":
                g["avail"] += 1
            if unit.area_m2 is not None:
                g["areas"].append(unit.area_m2)
            if unit.price_vnd is not None:
                g["prices"].append(unit.price_vnd)
        results = []
        for label, g in groups.items():
            results.append(base.UnitTypePricing(
                unit_type=label, group=g["group"],
                area_min_m2=min(g["areas"]) if g["areas"] else None,
                area_max_m2=max(g["areas"]) if g["areas"] else None,
                price_from_vnd=min(g["prices"]) if g["prices"] else None,
                price_to_vnd=max(g["prices"]) if g["prices"] else None,
                price_per_m2_from_vnd=None, price_per_m2_to_vnd=None,
                total_units=g["total"], available_units=g["avail"]))
        if unit_type:
            ut = unit_type.strip().upper()
            results = [r for r in results if ut in r.unit_type.upper() or ut in r.group.upper()]
        if max_price_vnd:
            results = [r for r in results if r.price_from_vnd is not None and r.price_from_vnd <= max_price_vnd]
        if not results:
            return None
        results.sort(key=lambda r: (r.price_from_vnd is None, r.price_from_vnd or 0))
        return base.PricingTable(project_code, results)

    async def search_units(self, query: base.UnitQuery) -> list[base.Unit] | None:
        got = await self._project_units(query.project_code)
        if not got or not got[0]:
            return None
        raw, pname = got
        out: list[base.Unit] = []
        for u in raw:
            unit = self._unit_from(u, query.project_code, pname)
            if query.unit_type and query.unit_type.strip().upper() not in (unit.unit_type.upper() + unit.unit_type_group.upper()):
                continue
            if query.max_price_vnd and (unit.price_vnd is None or unit.price_vnd > query.max_price_vnd):
                continue
            if query.min_area_m2 and (unit.area_m2 is None or unit.area_m2 < query.min_area_m2):
                continue
            if query.direction and query.direction.strip().lower() not in (unit.direction or "").lower():
                continue
            if query.unit_code and query.unit_code.strip().upper() not in unit.unit_code.upper():
                continue
            if query.status and query.status != "available":
                if unit.status != query.status:
                    continue
            elif query.status == "available" and unit.status not in ("available", "unknown"):
                continue
            out.append(unit)
        return out or None

    async def recommend_units(self, query: base.RecommendQuery) -> base.UnitRecommendation:
        data = await self._get("/api/v1/hot-units")
        if data is None:
            return base.UnitRecommendation([])
        items = data.get("items", []) if isinstance(data, dict) else []
        # optional region pre-filter via project.slug set from list_projects
        allowed_codes = None
        if query.region:
            pl = await self.list_projects(region=query.region)
            allowed_codes = {s.code for s in (pl.projects if pl else [])}
        out: list[base.Unit] = []
        for u in items:
            proj = u.get("project") or {}
            code = name_to_code(proj.get("name", ""))
            if not code:
                continue
            if allowed_codes is not None and code not in allowed_codes:
                continue
            unit = self._unit_from(u, code, proj.get("name") or code)
            if query.bedrooms and unit.bedrooms != query.bedrooms:
                continue
            if query.budget_max_vnd and (unit.price_vnd is None or unit.price_vnd > query.budget_max_vnd):
                continue
            out.append(unit)
        # RAW + unlimited (like MongoProvider): the recommend_units TOOL sorts
        # feng-shui-first then slices to 6. Slicing here would drop the best units.
        return base.UnitRecommendation(out)

    async def get_payment_plans(self, project_code): return None
    async def get_loan_policies(self, project_code): return None
    async def get_promotions(self, project_code): return None
    async def get_project_fees(self, project_code): return None

    # registry from the static map (roster is the map's codes)
    async def warm(self) -> None:
        import time
        self._last_warm_ts = time.monotonic()

    async def warm_if_stale(self, ttl_sec: float) -> None:
        import time
        if ttl_sec <= 0 or (time.monotonic() - self._last_warm_ts) < ttl_sec:
            return
        await self.warm()

    def registry_rows(self):
        c2n = code_to_name_map()
        return [base.ProjectRegistryRow(code, c2n.get(code, ""), "", "") for code in all_codes()]

    def cached_codes(self):
        return all_codes()

    def code_to_name(self):
        # code_to_name_map() is {code: NAME}; expose {code: name} for the roster.
        c2n = code_to_name_map()
        return {code: c2n.get(code, "") for code in all_codes()}
```

> `recommend_units` returns ALL matching units; the tool sorts then slices to 6 (matches Mongo). Sorting is done by the tool (Task 5). `cached_codes`/`code_to_name` come from the static map — the roster is fixed by `project_code_map.json`; region/type are `""` in registry rows (list order comes from the map). A future enhancement can warm region/type from `/api/v1/projects`.

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/unit/unified/providers/test_sales_api_provider.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/data/providers/sales_api.py \
        src/noble_agent/data/providers/_name_code_map.py \
        tests/unit/unified/providers/test_sales_api_provider.py
git commit -m "feat(providers): SalesApiProvider (NBX Sales API, name↔code map, tỷ→VND)"
```

---

### Task 7: End-to-end source switch + full suite

**Files:**
- Test: `tests/unit/unified/providers/test_source_switch.py` (new)

**Interfaces:**
- Consumes: everything above.
- Produces: proof that flipping `NOBLE_DATA_SOURCE` swaps the provider a tool uses, with model-facing JSON keys unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/providers/test_source_switch.py
import json

import pytest

from noble_agent.agent.tools import projects_info
from noble_agent.data import providers
from noble_agent.data.providers.base import ProjectRegistryRow
from tests.unit.unified.providers.test_base_contract import FakeProvider


@pytest.fixture(autouse=True)
def _reset():
    providers.reset_for_tests()
    yield
    providers.reset_for_tests()


async def test_tool_uses_active_provider_and_keeps_json_shape(monkeypatch):
    fake = FakeProvider(projects=[ProjectRegistryRow("MCP", "Masteri", "mien_nam", "can_ho")])
    monkeypatch.setattr(providers, "get_provider", lambda settings: fake)
    out = json.loads(await projects_info.list_projects({}))
    assert out["count"] == 1
    assert set(out["projects"][0]) == {"code", "name", "type", "region"}
```

- [ ] **Step 2: Run to verify it fails, then passes once imports line up**

Run: `pytest tests/unit/unified/providers/test_source_switch.py -v`
Expected: PASS (the wiring from Task 5 already supports it; if the import path for `FakeProvider` differs, adjust it).

- [ ] **Step 3: Run the full unit suite + lint**

Run: `make test-unit`
Expected: PASS except the ~pre-existing unrelated failures noted in CLAUDE.md (catalog/mongo/qdrant drift). No NEW failures attributable to this change.

Run: `make lint`
Expected: clean (fix any ruff findings in the new files).

- [ ] **Step 4: Manual smoke — both sources**

```bash
# mongo (default) — behaviour unchanged
NOBLE_DATA_SOURCE=mongo python -c "import asyncio; from noble_agent.agent.tools.projects_info import list_projects; print(asyncio.run(list_projects({})))"
# sales_api — live public API
NOBLE_DATA_SOURCE=sales_api python -c "import asyncio; from noble_agent.agent.tools.projects_info import list_projects; print(asyncio.run(list_projects({})))"
```
Expected: mongo prints the current Noble/Sunshine roster; sales_api prints Masteri/Vinhomes codes from the map. Both are valid JSON with identical keys.

- [ ] **Step 5: Run `src/noble_agent/SMOKE.md`** (turn loop / prompt / transport unaffected, but the tool path changed).

- [ ] **Step 6: Commit**

```bash
git add tests/unit/unified/providers/test_source_switch.py
git commit -m "test(providers): end-to-end NOBLE_DATA_SOURCE switch keeps LLM JSON shape"
```

---

## Out of Scope (follow-up plans)

1. **Roster/RAG migration to the Sales-API projects** — flipping the default source, rewriting `catalog._REGISTRY` aliases for the ~41 new projects, re-ingesting the `noble_search` Qdrant corpus for the new roster (spec §7). Must not ship until the KB is re-ingested, or `noble_search` returns wrong-project content.
2. **Mongo macro-region mapping** — a tỉnh/quận → `mien_bac/trung/nam` table so the Mongo provider also speaks the canonical region enum (spec §4). Deferred to preserve current behaviour.
3. **Sales-API overview enrichment** — warming region/type into `registry_rows()` from `/api/v1/projects`, and parsing `management`/`handover`/`total_investment` if the CMS later exposes them.

## Self-Review

- **Spec coverage:** §1 principles → Global Constraints + Task 5 (arg stability) + serialisers. §2 architecture → file structure. §3 interface → Task 1. §4 units → Task 6 (`_to_vnd`, `_bedrooms`), Task 5 (`*1e9` in recommend). §5 None-vs-empty → Tasks 3 & 6 return `None`/empty wrapper; tool escalates on `None`. §6 DTOs → Task 1. §7 registry/identity → Tasks 4 & 6 (`_slug_for`, name↔code map). §8 checklist → followed by Task 6. §9 mapping → Task 6 field-by-field.
- **Placeholder scan:** the only "copy verbatim" directions are in Task 3 (porting existing, in-repo `structured_data.py` code) — the source is named and present; this is a move, not a placeholder.
- **Type consistency:** `UnitQuery`/`RecommendQuery` field names (`max_price_vnd`, `min_area_m2`, `budget_max_vnd`) are used identically in Tasks 5 & 6. DTO field names in `_serialize.py` match `base.py`. `get_provider`/`reset_for_tests` names consistent across Tasks 2, 5, 7.
- **Resolved:** `Unit` DTO carries `wall_area_m2` + `max_discount_pct` so the mongo search_units JSON is byte-for-byte unchanged; Sales-API sets both to `None` (source lacks them).
