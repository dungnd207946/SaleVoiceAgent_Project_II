# Tool + Provider BĐS Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện provider `sales_api` + thêm tool `check_inventory` (thứ 11) + 4 mốc giá thanh toán, rồi flip `NOBLE_DATA_SOURCE` mặc định sang `sales_api`.

**Architecture:** Không đổi ranh giới tool↔provider. Mở rộng contract canonical (DTO + 1 Capability) ở `base.py`, map field ở 2 provider (`sales_api`, `mongo`), giữ wire-shape LLM ở `_serialize.py`. Tool chỉ gọi `get_provider(get_settings()).<method>()`.

**Tech Stack:** Python 3.11+, pydantic-settings, httpx (sales_api), motor (mongo), pytest (`asyncio_mode=auto`), ruff (line-length 120).

Design: [`docs/superpowers/specs/2026-07-21-tool-provider-bds-refactor-design.md`](../specs/2026-07-21-tool-provider-bds-refactor-design.md).
Contract: [`docs/BA/spec_provider.md`](../../BA/spec_provider.md) · Câu hỏi↔tool: [`docs/BA/spec_tool.md`](../../BA/spec_tool.md).

## Global Constraints

- **Branch `feat/refactor2`** — commit local, KHÔNG đụng `develop`, không push/PR/merge.
- **Never raise qua ranh giới tool** — provider trả `None`/rỗng theo spec_provider §5; `None` → `ESCALATE_SIGNAL`.
- **Đơn vị canonical:** giá = VND int (API tỷ → ×1e9); area = m² float; missing → `None`, không bịa.
- **`project_code` là định danh duy nhất lộ ra** — không để `id`/`slug`/`uuid` vào DTO/tool args.
- DTO là `@dataclass(frozen=True)`; field mới phải có default (`= None`) và append CUỐI dataclass (field không default không được đứng sau field có default).
- Ruff `E,F,W,I,UP,B,SIM`, line-length 120. `make test-unit` phải xanh (delta 0 vs baseline; các fail catalog/mongo-drift pre-existing được phép giữ nguyên).
- Chạy test bằng `python -m pytest ... -v` trong `.venv`.

---

### Task 1: Mở rộng contract — DTO + Capability + Protocol (base.py) + FakeProvider

**Files:**
- Modify: `src/noble_agent/data/providers/base.py`
- Modify: `tests/unit/unified/providers/test_base_contract.py` (FakeProvider phải có method mới, nếu không `isinstance(FakeProvider(), base.DataProvider)` fail)
- Modify: `docs/BA/spec_provider.md` (§3 method, §6 DTO)

**Interfaces:**
- Produces: `base.Capability.INVENTORY`; `base.ProjectOverview.product: str | None`; `base.Unit.price_early_vnd/price_progress_vnd/price_loan_vnd: int | None`; `base.UnitTypePricing.price_early_from_vnd/price_early_to_vnd: int | None`; DTOs `base.InventoryByType(unit_type:str,total:int,available:int,price_from_vnd:int|None,price_to_vnd:int|None)`, `base.InventoryByDirection(direction:str,available:int)`, `base.InventorySummary(project_code:str,total:int,available:int,by_unit_type:list[InventoryByType],by_direction:list[InventoryByDirection])`; Protocol method `async def get_inventory_summary(self, project_code: str) -> InventorySummary | None`.

- [ ] **Step 1: Write failing tests** (append to `tests/unit/unified/providers/test_base_contract.py`)

```python
def test_inventory_dtos_and_capability():
    assert base.Capability.INVENTORY.value == "inventory"
    s = base.InventorySummary(
        project_code="MCP", total=10, available=4,
        by_unit_type=[base.InventoryByType("2PN", 6, 3, 5_000_000_000, 7_000_000_000)],
        by_direction=[base.InventoryByDirection("Đông", 2)],
    )
    assert s.available == 4 and s.by_unit_type[0].available == 3


def test_new_optional_fields_default_none():
    ov = base.ProjectOverview(code="MCP", name="X")
    assert ov.product is None
    u = base.Unit(
        project_code="MCP", project_name="X", unit_code="A-1", unit_type="2PN",
        unit_type_group="can_ho", bedrooms=2, area_m2=75.0, wall_area_m2=None,
        price_vnd=5_000_000_000, price_per_m2_vnd=None, direction="Đông", floor=None,
        view=None, status="available", max_discount_pct=None, image_url=None,
    )
    assert u.price_early_vnd is None and u.price_progress_vnd is None and u.price_loan_vnd is None
    p = base.UnitTypePricing(
        unit_type="2PN", group="can_ho", area_min_m2=None, area_max_m2=None,
        price_from_vnd=None, price_to_vnd=None, price_per_m2_from_vnd=None,
        price_per_m2_to_vnd=None, total_units=1, available_units=1,
    )
    assert p.price_early_from_vnd is None and p.price_early_to_vnd is None
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_base_contract.py -v` → FAIL (`AttributeError`/`TypeError` on missing members).

- [ ] **Step 3: Implement in `base.py`**

Add to `Capability`:
```python
    INVENTORY = "inventory"
```
Add to `ProjectOverview` (cuối dataclass, đã có default nên hợp lệ):
```python
    product: str | None = None
```
Add to `Unit` (cuối dataclass — 3 field mới có default để không phá site dựng Unit hiện có):
```python
    price_early_vnd: int | None = None       # priceTts — thanh toán sớm
    price_progress_vnd: int | None = None    # priceTttd — theo tiến độ
    price_loan_vnd: int | None = None        # priceLoan — vay
```
Add to `UnitTypePricing` (cuối):
```python
    price_early_from_vnd: int | None = None
    price_early_to_vnd: int | None = None
```
Add new DTOs (sau `PricingTable`):
```python
@dataclass(frozen=True)
class InventoryByType:
    unit_type: str
    total: int
    available: int
    price_from_vnd: int | None
    price_to_vnd: int | None


@dataclass(frozen=True)
class InventoryByDirection:
    direction: str
    available: int


@dataclass(frozen=True)
class InventorySummary:
    project_code: str
    total: int
    available: int
    by_unit_type: list[InventoryByType]
    by_direction: list[InventoryByDirection]
```
Add to `DataProvider` Protocol (sau `recommend_units`):
```python
    async def get_inventory_summary(self, project_code: str) -> InventorySummary | None: ...
```

- [ ] **Step 4: Add `get_inventory_summary` to FakeProvider** (`test_base_contract.py`, trong class `FakeProvider`, sau `recommend_units`):

```python
    async def get_inventory_summary(self, project_code):
        hits = [u for u in self._units if u.project_code == project_code]
        if not hits:
            return None
        avail = sum(1 for u in hits if u.status == "available")
        return base.InventorySummary(
            project_code=project_code, total=len(hits), available=avail,
            by_unit_type=[], by_direction=[],
        )
```

- [ ] **Step 5: Run tests** — `python -m pytest tests/unit/unified/providers/test_base_contract.py -v` → PASS (kể cả `test_fake_provider_satisfies_protocol`).

- [ ] **Step 6: Update `docs/BA/spec_provider.md`** — §3 thêm dòng `get_inventory_summary`; §6 thêm `product` vào `ProjectOverview`, 3 field giá vào `Unit`, 2 field vào `UnitTypePricing`, và 3 DTO Inventory\*; §4 (tuỳ chọn) 1 dòng ánh xạ giá thanh toán. Giữ văn phong ngắn.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/data/providers/base.py tests/unit/unified/providers/test_base_contract.py docs/BA/spec_provider.md
git commit -m "feat(providers): contract adds INVENTORY capability + product/payment-price/inventory DTOs"
```

---

### Task 2: sales_api — fix `overview` double-encoded JSON + map `product`

**Files:**
- Modify: `src/noble_agent/data/providers/sales_api.py`
- Modify: `tests/unit/unified/providers/test_sales_api_provider.py`

**Interfaces:**
- Consumes: `base.ProjectOverview.product` (Task 1).
- Produces: `get_overview` đọc đúng khi `overview` là `str` JSON; set `product`.

- [ ] **Step 1: Write failing test** (append to `test_sales_api_provider.py`)

```python
async def test_overview_decodes_json_string_and_maps_product(monkeypatch):
    import json as _json
    routes = {
        "/api/v1/projects/qc-masteri": {
            "name": "MASTERI CENTRE POINT", "type": "can_ho", "areaRegion": "mien_nam",
            "location": "TP.HCM", "investor": "Masterise",
            # overview arrives as a DOUBLE-ENCODED JSON STRING, not an object
            "overview": _json.dumps({
                "scale": "5 ha", "units_text": "1200 căn",
                "ownership": "Lâu dài", "product": "Căn hộ, shophouse",
            }, ensure_ascii=False),
        },
        "/api/v1/projects": {"items": [{"slug": "qc-masteri", "name": "MASTERI CENTRE POINT"}],
                             "total": 1, "page": 1, "pageSize": 20},
    }
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr(p, "_client", lambda: _Client(routes))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code",
                        lambda n: {"MASTERI CENTRE POINT": "MCP"}.get(n.upper().strip(), ""))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.code_to_name_map",
                        lambda: {"MCP": "MASTERI CENTRE POINT"})
    ov = await p.get_overview("MCP")
    assert ov.total_units == "1200 căn" and ov.ownership == "Lâu dài"
    assert ov.land_area == "5 ha" and ov.product == "Căn hộ, shophouse"
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_sales_api_provider.py::test_overview_decodes_json_string_and_maps_product -v` → FAIL (`ov.total_units is None`, `ov.product` missing).

- [ ] **Step 3: Implement** in `sales_api.py`.

Add near top (after `_to_vnd`):
```python
def _safe_json_obj(raw) -> dict:
    """API sometimes double-encodes objects as a JSON string. Decode defensively."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}
```
Add `import json` at top of module. In `get_overview`, replace `ov = doc.get("overview") or {}` with:
```python
        ov = _safe_json_obj(doc.get("overview"))
```
and add `product=ov.get("product")` to the `base.ProjectOverview(...)` kwargs.

- [ ] **Step 4: Run test** — same command → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/sales_api.py tests/unit/unified/providers/test_sales_api_provider.py
git commit -m "fix(sales-api): decode double-encoded overview JSON string + map product"
```

---

### Task 3: sales_api — 4 mốc giá thanh toán (Unit + pricing early range)

**Files:**
- Modify: `src/noble_agent/data/providers/sales_api.py`
- Modify: `tests/unit/unified/providers/test_sales_api_provider.py`

**Interfaces:**
- Consumes: `base.Unit.price_early_vnd/…`, `base.UnitTypePricing.price_early_from_vnd/…` (Task 1).
- Produces: `_unit_from` set 3 giá; `get_pricing` aggregate early-range per type.

- [ ] **Step 1: Write failing tests**

```python
async def test_unit_carries_payment_prices(monkeypatch):
    routes = {
        "/api/v1/projects/qc-masteri": {
            "name": "MASTERI CENTRE POINT", "overview": "{}",
            "units": [
                {"code": "A-1", "price": 5.0, "priceTts": 4.5, "priceTttd": 4.8,
                 "priceLoan": 5.2, "area": 75.0, "status": "available",
                 "unitType": {"name": "2PN", "group": "can_ho"}},
            ],
        },
        "/api/v1/projects": {"items": [{"slug": "qc-masteri", "name": "MASTERI CENTRE POINT"}],
                             "total": 1, "page": 1, "pageSize": 20},
    }
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr(p, "_client", lambda: _Client(routes))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code",
                        lambda n: {"MASTERI CENTRE POINT": "MCP"}.get(n.upper().strip(), ""))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.code_to_name_map",
                        lambda: {"MCP": "MASTERI CENTRE POINT"})
    units = await p.search_units(base.UnitQuery(project_code="MCP"))
    u = units[0]
    assert u.price_early_vnd == 4_500_000_000      # priceTts ×1e9
    assert u.price_progress_vnd == 4_800_000_000   # priceTttd ×1e9
    assert u.price_loan_vnd == 5_200_000_000       # priceLoan ×1e9


async def test_pricing_aggregates_early_price_range(monkeypatch):
    routes = {
        "/api/v1/projects/qc-masteri": {
            "name": "MASTERI CENTRE POINT", "overview": "{}",
            "units": [
                {"code": "A-1", "price": 5.0, "priceTts": 4.5, "area": 75.0,
                 "status": "available", "unitType": {"name": "2PN", "group": "can_ho"}},
                {"code": "A-2", "price": 6.0, "priceTts": 5.4, "area": 80.0,
                 "status": "available", "unitType": {"name": "2PN", "group": "can_ho"}},
            ],
        },
        "/api/v1/projects": {"items": [{"slug": "qc-masteri", "name": "MASTERI CENTRE POINT"}],
                             "total": 1, "page": 1, "pageSize": 20},
    }
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr(p, "_client", lambda: _Client(routes))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code",
                        lambda n: {"MASTERI CENTRE POINT": "MCP"}.get(n.upper().strip(), ""))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.code_to_name_map",
                        lambda: {"MCP": "MASTERI CENTRE POINT"})
    pt = await p.get_pricing("MCP")
    row = pt.results[0]
    assert row.price_early_from_vnd == 4_500_000_000 and row.price_early_to_vnd == 5_400_000_000
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_sales_api_provider.py -k "payment_prices or early_price_range" -v` → FAIL.

- [ ] **Step 3: Implement**.

In `_unit_from`, add the 3 kwargs to `base.Unit(...)`:
```python
            price_early_vnd=_to_vnd(u.get("priceTts")),
            price_progress_vnd=_to_vnd(u.get("priceTttd")),
            price_loan_vnd=_to_vnd(u.get("priceLoan")),
```
In `get_pricing`, extend the per-group accumulator: in the `groups.setdefault(...)` dict add `"early": []`, then after computing `unit`:
```python
            if unit.price_early_vnd is not None:
                g["early"].append(unit.price_early_vnd)
```
and in the `base.UnitTypePricing(...)` build add:
```python
                    price_early_from_vnd=min(g["early"]) if g["early"] else None,
                    price_early_to_vnd=max(g["early"]) if g["early"] else None,
```

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/sales_api.py tests/unit/unified/providers/test_sales_api_provider.py
git commit -m "feat(sales-api): map 4 payment prices (unit) + early-price range (pricing)"
```

---

### Task 4: sales_api — push server-side filters in `recommend_units`

**Files:**
- Modify: `src/noble_agent/data/providers/sales_api.py`
- Modify: `tests/unit/unified/providers/test_sales_api_provider.py`

**Interfaces:**
- Produces: `recommend_units` gọi `GET /hot-units` với params `region`/`price_max` (tỷ), bỏ N+1 `list_projects`.

- [ ] **Step 1: Write failing test** (capturing client records params)

```python
async def test_recommend_pushes_region_and_price_server_side(monkeypatch):
    captured = {}

    class _CapClient(_Client):
        async def get(self, url, params=None):
            if "hot-units" in url:
                captured["params"] = dict(params or {})
            return await super().get(url, params=params)

    routes = {"/api/v1/hot-units": {"items": []}}
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr(p, "_client", lambda: _CapClient(routes))
    # If list_projects were still called, it would hit /api/v1/projects — assert it is NOT.
    monkeypatch.setattr(p, "list_projects",
                        lambda **k: (_ for _ in ()).throw(AssertionError("N+1 list_projects called")))
    await p.recommend_units(base.RecommendQuery(region="mien_nam", budget_max_vnd=5_000_000_000))
    assert captured["params"].get("region") == "mien_nam"
    assert float(captured["params"].get("price_max")) == 5.0  # VND → tỷ
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_sales_api_provider.py::test_recommend_pushes_region_and_price_server_side -v` → FAIL (params empty / N+1 called).

- [ ] **Step 3: Implement** — rewrite `recommend_units` head to build params and drop the `list_projects` pre-filter:

```python
    async def recommend_units(self, query: base.RecommendQuery) -> base.UnitRecommendation | None:
        params: dict = {}
        if query.region:
            params["region"] = query.region
        if query.budget_max_vnd:
            params["price_max"] = round(query.budget_max_vnd / 1e9, 4)
        data = await self._get("/api/v1/hot-units", params or None)
        if data is None:
            return None
        items = data.get("items", []) if isinstance(data, dict) else []
        out: list[base.Unit] = []
        for u in items:
            proj = u.get("project") or {}
            code = name_to_code(proj.get("name", ""))
            if not code:
                continue
            unit = self._unit_from(u, code, proj.get("name") or code)
            if query.bedrooms and unit.bedrooms != query.bedrooms:
                continue
            out.append(unit)
        return base.UnitRecommendation(out)
```

- [ ] **Step 4: Run tests** — task command + `python -m pytest tests/unit/unified/providers/test_sales_api_provider.py -v` (existing recommend tests still pass; the empty/down tests hit `/hot-units` regardless of params).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/sales_api.py tests/unit/unified/providers/test_sales_api_provider.py
git commit -m "perf(sales-api): push region/price_max to /hot-units, drop N+1 list_projects"
```

---

### Task 5: sales_api — `warm()` nạp region/type cho registry

**Files:**
- Modify: `src/noble_agent/data/providers/sales_api.py`
- Modify: `tests/unit/unified/providers/test_sales_api_provider.py`

**Interfaces:**
- Produces: sau `warm()`, `registry_rows()` có `region`/`type` từ `/api/v1/projects`; `cached_codes()` vẫn từ roster map (ổn định); fallback map khi nguồn down.

- [ ] **Step 1: Write failing test**

```python
async def test_warm_enriches_region_type(monkeypatch):
    routes = {"/api/v1/projects": {
        "items": [{"slug": "qc-masteri", "name": "MASTERI CENTRE POINT",
                   "areaRegion": "mien_nam", "type": "can_ho"}],
        "total": 1, "page": 1, "pageSize": 20}}
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr(p, "_client", lambda: _Client(routes))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code",
                        lambda n: {"MASTERI CENTRE POINT": "MCP"}.get(n.upper().strip(), ""))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.all_codes", lambda: ["MCP"])
    monkeypatch.setattr("noble_agent.data.providers.sales_api.code_to_name_map",
                        lambda: {"MCP": "MASTERI CENTRE POINT"})
    await p.warm()
    row = next(r for r in p.registry_rows() if r.code == "MCP")
    assert row.region == "mien_nam" and row.type == "can_ho"
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_sales_api_provider.py::test_warm_enriches_region_type -v` → FAIL (region/type == "").

- [ ] **Step 3: Implement** — add `self._region_type: dict[str, tuple[str, str]] = {}` in `__init__`; rewrite `warm` + `registry_rows`:

```python
    async def warm(self) -> None:
        self._last_warm_ts = time.monotonic()
        items = await self._fetch_all_projects({})
        if not items:
            return  # keep last-good cache; registry_rows falls back to the static map
        rt: dict[str, tuple[str, str]] = {}
        for it in items:
            code = name_to_code(it.get("name", ""))
            if code:
                rt[code] = (it.get("areaRegion", "") or "", it.get("type", "") or "")
        self._region_type = rt

    def registry_rows(self) -> list[base.ProjectRegistryRow]:
        c2n = code_to_name_map()
        rows = []
        for code in all_codes():
            region, ptype = self._region_type.get(code, ("", ""))
            rows.append(base.ProjectRegistryRow(code, c2n.get(code, ""), region, ptype))
        return rows
```

- [ ] **Step 4: Run tests** — task command + full file → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/sales_api.py tests/unit/unified/providers/test_sales_api_provider.py
git commit -m "feat(sales-api): warm region/type into registry rows for the prompt project table"
```

---

### Task 6: sales_api — `get_inventory_summary`

**Files:**
- Modify: `src/noble_agent/data/providers/sales_api.py`
- Modify: `tests/unit/unified/providers/test_sales_api_provider.py`

**Interfaces:**
- Consumes: `base.InventorySummary/InventoryByType/InventoryByDirection` (Task 1), `_project_units` (existing).
- Produces: `async def get_inventory_summary(self, project_code) -> base.InventorySummary | None`; declare `base.Capability.INVENTORY`.

- [ ] **Step 1: Write failing test**

```python
async def test_inventory_summary_aggregates(monkeypatch):
    routes = {
        "/api/v1/projects/qc-masteri": {
            "name": "MASTERI CENTRE POINT", "overview": "{}",
            "units": [
                {"code": "A-1", "price": 5.0, "direction": "Đông", "status": "available",
                 "unitType": {"name": "2PN", "group": "can_ho"}},
                {"code": "A-2", "price": 6.0, "direction": "Đông", "status": "sold",
                 "unitType": {"name": "2PN", "group": "can_ho"}},
                {"code": "B-1", "price": 9.0, "direction": "Tây", "status": "available",
                 "unitType": {"name": "3PN", "group": "can_ho"}},
            ],
        },
        "/api/v1/projects": {"items": [{"slug": "qc-masteri", "name": "MASTERI CENTRE POINT"}],
                             "total": 1, "page": 1, "pageSize": 20},
    }
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr(p, "_client", lambda: _Client(routes))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code",
                        lambda n: {"MASTERI CENTRE POINT": "MCP"}.get(n.upper().strip(), ""))
    monkeypatch.setattr("noble_agent.data.providers.sales_api.code_to_name_map",
                        lambda: {"MCP": "MASTERI CENTRE POINT"})
    s = await p.get_inventory_summary("MCP")
    assert s.total == 3 and s.available == 2
    twoPN = next(t for t in s.by_unit_type if t.unit_type == "2PN")
    assert twoPN.total == 2 and twoPN.available == 1
    dong = next(d for d in s.by_direction if d.direction == "Đông")
    assert dong.available == 1


async def test_inventory_summary_none_for_unknown(monkeypatch):
    p = SalesApiProvider(base_url="http://x", timeout=1.0)
    monkeypatch.setattr("noble_agent.data.providers.sales_api.name_to_code", lambda n: "")
    assert await p.get_inventory_summary("ZZZ") is None
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_sales_api_provider.py -k inventory_summary -v` → FAIL (`AttributeError`).

- [ ] **Step 3: Implement** — add `base.Capability.INVENTORY` to the `capabilities` frozenset; add method:

```python
    async def get_inventory_summary(self, project_code: str) -> base.InventorySummary | None:
        got = await self._project_units(project_code)
        if not got or not got[0]:
            return None
        raw, pname = got
        by_type: dict[str, dict] = {}
        by_dir: dict[str, int] = {}
        total = avail = 0
        for u in raw:
            unit = self._unit_from(u, project_code, pname)
            total += 1
            is_av = unit.status == "available"
            avail += 1 if is_av else 0
            t = by_type.setdefault(
                unit.unit_type or "Khác",
                {"total": 0, "available": 0, "prices": []},
            )
            t["total"] += 1
            t["available"] += 1 if is_av else 0
            if unit.price_vnd is not None:
                t["prices"].append(unit.price_vnd)
            if unit.direction and is_av:
                by_dir[unit.direction] = by_dir.get(unit.direction, 0) + 1
        return base.InventorySummary(
            project_code=project_code, total=total, available=avail,
            by_unit_type=[
                base.InventoryByType(
                    unit_type=k, total=v["total"], available=v["available"],
                    price_from_vnd=min(v["prices"]) if v["prices"] else None,
                    price_to_vnd=max(v["prices"]) if v["prices"] else None,
                )
                for k, v in by_type.items()
            ],
            by_direction=[base.InventoryByDirection(d, n) for d, n in by_dir.items()],
        )
```

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/sales_api.py tests/unit/unified/providers/test_sales_api_provider.py
git commit -m "feat(sales-api): get_inventory_summary (count by unit_type + direction)"
```

---

### Task 7: mongo — `get_inventory_summary`

**Files:**
- Modify: `src/noble_agent/data/providers/mongo.py`
- Modify: `tests/unit/unified/providers/test_mongo_provider.py`

**Interfaces:**
- Consumes: `_fetch_units` (existing), `_unit_type_label`/`_is_available` (existing helpers), `base.InventorySummary` (Task 1).
- Produces: `async def get_inventory_summary(self, project_code) -> base.InventorySummary | None`; declare `Capability.INVENTORY`.

- [ ] **Step 1: Read the existing mongo test** to mirror its DB-fake pattern: `python -m pytest tests/unit/unified/providers/test_mongo_provider.py -v --collect-only`, then open the file to copy how `_fetch_units`/`get_db` is faked.

- [ ] **Step 2: Write failing test** (match the file's existing fake-DB fixture; shape below)

```python
async def test_mongo_inventory_summary(monkeypatch):
    from noble_agent.data.providers.mongo import MongoProvider
    units = [
        {"ma_can": "A-1", "loai_san_pham": "can_ho", "so_phong_ngu": 2, "gia_vnd": 5_000_000_000,
         "huong": "Đông", "trang_thai": "Còn hàng"},
        {"ma_can": "A-2", "loai_san_pham": "can_ho", "so_phong_ngu": 2, "gia_vnd": 6_000_000_000,
         "huong": "Đông", "trang_thai": "Đã bán"},
    ]
    p = MongoProvider()
    async def _fake_fetch(code):
        return units
    monkeypatch.setattr("noble_agent.data.providers.mongo._fetch_units", _fake_fetch)
    s = await p.get_inventory_summary("MCP")
    assert s.total == 2 and s.available == 1
    assert s.by_unit_type[0].available == 1
    assert next(d for d in s.by_direction if d.direction == "Đông").available == 1
```

> If the existing test file fakes units differently (e.g. patches a bound method or a fake db), follow that pattern instead of `_fetch_units` — keep this file's convention.

- [ ] **Step 3: Run to verify fail** → FAIL (`AttributeError`).

- [ ] **Step 4: Implement** in `mongo.py` — add `Capability.INVENTORY` to the provider's `capabilities`; add method (uses `_unit_type_label`, `_is_available`, `_to_int` already in module):

```python
    async def get_inventory_summary(self, project_code: str) -> base.InventorySummary | None:
        units = await _fetch_units(project_code)
        if not units:
            return None
        by_type: dict[str, dict] = {}
        by_dir: dict[str, int] = {}
        total = avail = 0
        for u in units:
            total += 1
            is_av = _is_available(u.get("trang_thai", ""))
            avail += 1 if is_av else 0
            label = _unit_type_label(u)
            t = by_type.setdefault(label, {"total": 0, "available": 0, "prices": []})
            t["total"] += 1
            t["available"] += 1 if is_av else 0
            price = _to_int(u.get("gia_vnd"))
            if price is not None:
                t["prices"].append(price)
            huong = (u.get("huong") or "").strip()
            if huong and is_av:
                by_dir[huong] = by_dir.get(huong, 0) + 1
        return base.InventorySummary(
            project_code=project_code, total=total, available=avail,
            by_unit_type=[
                base.InventoryByType(
                    unit_type=k, total=v["total"], available=v["available"],
                    price_from_vnd=min(v["prices"]) if v["prices"] else None,
                    price_to_vnd=max(v["prices"]) if v["prices"] else None,
                )
                for k, v in by_type.items()
            ],
            by_direction=[base.InventoryByDirection(d, n) for d, n in by_dir.items()],
        )
```

- [ ] **Step 5: Run tests** → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/data/providers/mongo.py tests/unit/unified/providers/test_mongo_provider.py
git commit -m "feat(mongo): get_inventory_summary (aggregate project_can_ho by type + direction)"
```

---

### Task 8: Serialize — overview `product`, unit payment prices, pricing early range, `inventory_json`

**Files:**
- Modify: `src/noble_agent/data/providers/_serialize.py`
- Modify: `tests/unit/unified/providers/test_serialize.py`

**Interfaces:**
- Produces: `ser.overview_json` + `"product"`; `ser.unit_json` + `"price_early_vnd"/"price_progress_vnd"/"price_loan_vnd"`; `ser._unit_type_pricing_json` + `"price_early_from_vnd"/"price_early_to_vnd"`; new `ser.inventory_json(base.InventorySummary) -> dict`.

- [ ] **Step 1: Write failing tests** (append to `test_serialize.py`)

```python
def test_overview_json_has_product():
    ov = base.ProjectOverview(code="MCP", name="X", product="Căn hộ, shophouse")
    assert ser.overview_json(ov)["product"] == "Căn hộ, shophouse"


def test_unit_json_has_payment_prices():
    u = base.Unit(
        project_code="MCP", project_name="X", unit_code="A-1", unit_type="2PN",
        unit_type_group="can_ho", bedrooms=2, area_m2=75.0, wall_area_m2=None,
        price_vnd=5_000_000_000, price_per_m2_vnd=None, direction="Đông", floor=None,
        view=None, status="available", max_discount_pct=None, image_url=None,
        price_early_vnd=4_500_000_000,
    )
    j = ser.unit_json(u)
    assert j["price_early_vnd"] == 4_500_000_000 and "price_progress_vnd" in j and "price_loan_vnd" in j


def test_inventory_json_shape():
    s = base.InventorySummary(
        project_code="MCP", total=3, available=2,
        by_unit_type=[base.InventoryByType("2PN", 2, 1, 5_000_000_000, 6_000_000_000)],
        by_direction=[base.InventoryByDirection("Đông", 1)],
    )
    j = ser.inventory_json(s)
    assert j["project_code"] == "MCP" and j["available"] == 2
    assert j["by_unit_type"][0]["type"] == "2PN" and j["by_unit_type"][0]["available"] == 1
    assert j["by_direction"][0] == {"direction": "Đông", "available": 1}
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_serialize.py -k "product or payment_prices or inventory_json" -v` → FAIL.

- [ ] **Step 3: Implement** in `_serialize.py`:

In `overview_json` return dict add: `"product": ov.product or "",`.
In `unit_json` return dict add:
```python
        "price_early_vnd": u.price_early_vnd,
        "price_progress_vnd": u.price_progress_vnd,
        "price_loan_vnd": u.price_loan_vnd,
```
In `_unit_type_pricing_json` return dict add:
```python
        "price_early_from_vnd": r.price_early_from_vnd,
        "price_early_to_vnd": r.price_early_to_vnd,
```
Add new function:
```python
def inventory_json(s: base.InventorySummary) -> dict:
    return {
        "project_code": s.project_code,
        "total": s.total,
        "available": s.available,
        "by_unit_type": [
            {
                "type": t.unit_type,
                "total": t.total,
                "available": t.available,
                "price_from": t.price_from_vnd,
                "price_to": t.price_to_vnd,
            }
            for t in s.by_unit_type
        ],
        "by_direction": [{"direction": d.direction, "available": d.available} for d in s.by_direction],
    }
```

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/providers/_serialize.py tests/unit/unified/providers/test_serialize.py
git commit -m "feat(serialize): overview product, unit payment prices, pricing early range, inventory_json"
```

---

### Task 9: `check_inventory` tool + schema + dispatcher + config.json + RULES

**Files:**
- Create: `src/noble_agent/agent/tools/check_inventory.py`
- Modify: `src/noble_agent/agent/tools/schemas.py` (add schema + `_PROJECT_CODE_TOOLS`)
- Modify: `src/noble_agent/agent/tools/dispatcher.py`
- Modify: `src/noble_agent/agent/definitions/config.json`
- Modify: `src/noble_agent/agent/definitions/RULES.md`
- Create: `tests/unit/unified/test_check_inventory.py`
- Modify: `tests/unit/unified/test_agent_def.py` (10 → 11)

**Interfaces:**
- Consumes: `providers.get_provider`, `ser.inventory_json`, `base.ESCALATE_SIGNAL`.
- Produces: `check_inventory.run(args: dict) -> str`; dispatcher branch `name == "check_inventory"`; schema key `"check_inventory"`.

- [ ] **Step 1: Write failing tests** (`tests/unit/unified/test_check_inventory.py`)

```python
import json

from noble_agent.agent.tools import check_inventory
from noble_agent.data.providers import base


class _Prov:
    def __init__(self, summary):
        self._s = summary

    async def get_inventory_summary(self, code):
        return self._s


def _patch(monkeypatch, prov):
    monkeypatch.setattr("noble_agent.agent.tools.check_inventory.providers.get_provider", lambda s: prov)
    monkeypatch.setattr("noble_agent.agent.tools.check_inventory.get_settings", lambda: object())


async def test_check_inventory_serializes_summary(monkeypatch):
    s = base.InventorySummary(
        project_code="MCP", total=3, available=2,
        by_unit_type=[base.InventoryByType("2PN", 2, 1, 5_000_000_000, 6_000_000_000)],
        by_direction=[base.InventoryByDirection("Đông", 1)],
    )
    _patch(monkeypatch, _Prov(s))
    out = json.loads(await check_inventory.run({"project_code": "MCP"}))
    assert out["available"] == 2 and out["by_unit_type"][0]["type"] == "2PN"


async def test_check_inventory_none_escalates(monkeypatch):
    _patch(monkeypatch, _Prov(None))
    assert await check_inventory.run({"project_code": "ZZZ"}) == base.ESCALATE_SIGNAL
```

Add to `tests/unit/unified/test_check_inventory.py` a schema/agent test:
```python
def test_check_inventory_in_catalog():
    from noble_agent.agent.tools.schemas import schemas_for
    schemas = schemas_for(["check_inventory"], codes=["MCP", "VGP"])
    props = schemas[0]["function"]["parameters"]["properties"]
    assert schemas[0]["function"]["name"] == "check_inventory"
    assert props["project_code"]["enum"] == ["", "MCP", "VGP"]
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/test_check_inventory.py -v` → FAIL (module missing).

- [ ] **Step 3: Create `check_inventory.py`**

```python
"""check_inventory tool — inventory count SUMMARY for one project (not a unit
list). Answers "còn bao nhiêu căn / còn loại nào / hướng nào". Voice-friendly:
returns aggregate counts, unlike search_units which returns individual units.
None (unknown project / no inventory / source down) → ESCALATE_SIGNAL.
"""

from __future__ import annotations

import json

from noble_agent.config import get_settings
from noble_agent.data import providers
from noble_agent.data.providers import _serialize as ser
from noble_agent.data.providers.base import ESCALATE_SIGNAL


async def run(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    result = await provider.get_inventory_summary(args.get("project_code", "") or "")
    if result is None:
        return ESCALATE_SIGNAL
    return json.dumps(ser.inventory_json(result), ensure_ascii=False)
```

- [ ] **Step 4: Add schema** in `schemas.py` `SCHEMAS` dict (near `search_units`):

```python
    "check_inventory": {
        "type": "function",
        "function": {
            "name": "check_inventory",
            "description": (
                "Tóm tắt tồn kho của MỘT dự án: còn bao nhiêu căn, theo từng loại căn và "
                "từng hướng. Dùng khi khách hỏi 'dự án còn nhiều căn không', 'còn loại nào', "
                "'hướng nào còn'. KHÁC search_units (liệt kê từng căn) và KHÁC "
                "booking(check_availability) (lịch đi xem, không phải tồn kho)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"project_code": {"type": "string"}},
                "required": ["project_code"],
            },
        },
    },
```
Add `"check_inventory"` to the `_PROJECT_CODE_TOOLS` tuple.

- [ ] **Step 5: Wire dispatcher** — in `dispatcher.py` import `check_inventory` in the `from noble_agent.agent.tools import (...)` block, and add a branch (near `search_units`):

```python
        if name == "check_inventory":
            return await check_inventory.run(args)
```

- [ ] **Step 6: Add to `config.json`** — append `"check_inventory"` to the `"tools"` list.

- [ ] **Step 7: Add RULES.md catalog row** — under `## Tool catalog`, after the `search_units` row:

```
| "Dự án còn nhiều căn không / còn loại nào / hướng nào còn" | check_inventory(project_code=<MÃ>) — tóm tắt đếm, KHÁC booking(check_availability) là lịch xem |
```
Also add `check_inventory` to the "Tín hiệu chuyển chuyên viên" sentence list (line ~144).

- [ ] **Step 8: Update `test_agent_def.py`** — change `assert len(agent.tool_names) == 10` → `== 11`, `assert len(agent.tool_schemas) == 10` → `== 11`, and add `assert "check_inventory" in agent.tool_names`.

- [ ] **Step 9: Run tests** — `python -m pytest tests/unit/unified/test_check_inventory.py tests/unit/unified/test_agent_def.py -v` → PASS.

- [ ] **Step 10: Commit**

```bash
git add src/noble_agent/agent/tools/check_inventory.py src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/dispatcher.py src/noble_agent/agent/definitions/config.json src/noble_agent/agent/definitions/RULES.md tests/unit/unified/test_check_inventory.py tests/unit/unified/test_agent_def.py
git commit -m "feat(tools): add check_inventory (11th tool) — inventory count summary"
```

---

### Task 10: Flip `NOBLE_DATA_SOURCE` default → `sales_api` + docs

**Files:**
- Modify: `src/noble_agent/config.py:447`
- Modify: `.env.example`
- Modify: `src/noble_agent/CLAUDE.md` (config table + tool count + layout row + Change Log)
- Modify: `docs/BA/spec_tool.md` (check_inventory: đề xuất → đã thêm)
- Modify: `tests/unit/unified/providers/test_factory.py` and/or `test_source_switch.py`

**Interfaces:**
- Produces: `get_settings().noble_data_source == "sales_api"` mặc định; `get_provider(default settings)` → `SalesApiProvider`.

- [ ] **Step 1: Write/adjust failing test** — read `tests/unit/unified/providers/test_factory.py` + `test_source_switch.py`; add/adjust:

```python
def test_default_source_is_sales_api(monkeypatch):
    monkeypatch.delenv("NOBLE_DATA_SOURCE", raising=False)
    from noble_agent.config import UnifiedSettings
    assert UnifiedSettings().noble_data_source == "sales_api"
```
> If an existing test asserts the default is `mongo`, update it to `sales_api`. Keep the explicit-`mongo` and explicit-`sales_api` switch tests intact.

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/unit/unified/providers/test_factory.py tests/unit/unified/providers/test_source_switch.py -v` → FAIL on the default.

- [ ] **Step 3: Flip default** — `config.py`:
```python
    noble_data_source: str = "sales_api"       # "mongo" | "sales_api"
```
`.env.example`: set `NOBLE_DATA_SOURCE=sales_api` (or comment noting the new default) + a line that `mongo` is the legacy source.

- [ ] **Step 4: Update docs** —
  - `CLAUDE.md`: config table `NOBLE_DATA_SOURCE` default → `sales_api`; layout row `agent/tools/` note **11 tools** (+`check_inventory`); tool-count mentions 10→11 where they appear; append a Change Log row (date 2026-07-21, what/why per the design doc).
  - `docs/BA/spec_tool.md`: §4/§4.1 đổi trạng thái `check_inventory` từ "đề xuất" → "đã thêm (11 tool)"; Change Log +1 dòng.

- [ ] **Step 5: Run tests** → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py .env.example src/noble_agent/CLAUDE.md docs/BA/spec_tool.md tests/unit/unified/providers/test_factory.py tests/unit/unified/providers/test_source_switch.py
git commit -m "feat(config): default NOBLE_DATA_SOURCE=sales_api + docs (11 tools, check_inventory)"
```

---

### Task 11: Full unit-suite gate + live smoke

**Files:** none (verification only).

- [ ] **Step 1: Run the unit suite** — `make test-unit` (or `python -m pytest tests/unit -q`). Expected: all new tests green; the only failures are the **pre-existing** catalog/mongo-drift / `.env`-parsing ones (compare against a clean checkout of `feat/refactor2` before this work — the failing set must be identical, i.e. **delta 0**). If any NEW failure appears, fix it before proceeding.

- [ ] **Step 2: Lint** — `make lint` (ruff). Fix any new findings in touched files.

- [ ] **Step 3: Live smoke against sales_api dev** — start the server (`scripts/run.sh --no-reload`, `.env` with `NOBLE_DATA_SOURCE=sales_api`, `USE_UNIFIED_AGENT=true`), open `http://localhost:8766/chat`, and exercise the funnel end-to-end:
  1. "Bên em có dự án nào ở miền Nam?" → `list_projects` trả roster mới (Masteri/Vinhomes…).
  2. "Dự án <X> thế nào?" → `get_project_overview` trả `product`/`ownership`/`units_text` (KHÔNG rỗng — verify bug §1.1 đã fix).
  3. "Tầm 5 tỷ ở miền Nam nên xem căn nào?" → `recommend_units` (verify chỉ 1 call `/hot-units` có `region`+`price_max`).
  4. "Căn 2PN dự án <X> còn không?" → `search_units`.
  5. "Dự án <X> còn nhiều căn không?" → `check_inventory` (tóm tắt đếm).
  6. Một câu định tính (tiện ích/vị trí) → `noble_search` trả đúng dự án (verify RAG roster khớp).
  7. Đặt lịch → `booking`.
  Ghi lại kết quả; nếu field nào rỗng ngoài dự kiến (vd 4 mốc giá trên đường per-project), đối chiếu spec_provider §9 và ghi chú (None-safe nên không vỡ, nhưng cần biết).

- [ ] **Step 4: Run `src/noble_agent/SMOKE.md`** — vì flip đổi hành vi runtime cho mọi transport.

- [ ] **Step 5: Commit** (nếu có fix phát sinh từ smoke) trên `feat/refactor2`.

---

## Self-Review (đã chạy)

- **Spec coverage:** Part 1.1 fix overview → T2; 1.2 product → T1/T2/T8; 1.3 server-side → T4; 1.4 warm region/type → T5. Part 2 check_inventory → T1(contract)+T6(sales)+T7(mongo)+T8(serialize)+T9(tool). Part 3 payment prices → T1(DTO)+T3(sales)+T8(serialize). Part 4 flip+docs → T10; gate → T11. ✅ Mọi mục design có task.
- **Placeholder scan:** không có TBD; mọi step code có nội dung thật. Task 7 Step 1 & Task 10 Step 1 chủ động yêu cầu ĐỌC test hiện có để khớp fake-pattern (không phải placeholder — là chỉ dẫn cần thiết vì fake-DB convention nằm ngoài file này).
- **Type consistency:** `get_inventory_summary`/`InventorySummary`/`inventory_json` đồng nhất mọi task; field giá `price_early_vnd`/`price_progress_vnd`/`price_loan_vnd` + `price_early_from_vnd`/`price_early_to_vnd` dùng đúng tên xuyên T1/T3/T8. ✅
