# discover_projects Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the enumerate-everything `list_projects` tool with a funnel-style `discover_projects` (top-K + total + narrowing hints + index pagination, hot-first ranking), and add a `project_code` scope to `recommend_units`.

**Architecture:** Agent-facing tool is provider-agnostic (canonical params/enums, shapes the wire envelope). A new `DataProvider.discover_projects` method + canonical DTOs (`DiscoverQuery`/`ProjectDiscovery`) push filter/rank/count/paginate into each adapter (`mongo`, `sales_api`). Ranking is a stable total order so index pagination never repeats/skips.

**Tech Stack:** Python 3.11+, pydantic-settings, pytest (`asyncio_mode=auto`), ruff (line-length 120). Providers TDD'd against in-memory fakes (see `tests/unit/unified/providers/`).

## Global Constraints

- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make lint` / `make format`.
- `product_type` canonical enum values: `chung_cu | biet_thu | lien_ke | shophouse | dat_nen | van_phong` (romanized VN, matches menh/zodiac precedent).
- `purpose` canonical enum values: `live | invest`. `purpose` is **advisory only** (does not filter projects), mirroring `recommend_units`.
- Hard project filters: `region`, `product_type`, `investor`. `budget_max` → server-side `price_max` on sales_api; **best-effort / no-op** on mongo (no project-level price field) — `price_from_vnd` is `None` when the source has no project price.
- Ranking total order: sales_api = `isHot` desc → `isFeatured` desc → `sortHot`/`sortOrder` asc → `code` asc; mongo = `code` asc (no hot field, `hot=False`). The final `code` tiebreak guarantees deterministic pagination.
- Adapter returns already-ranked, already-sliced `[offset:offset+limit]` projects + full `total`. The **tool** computes `has_more`, `next_index`, `suggested_narrow`, `instruction`, and caps nothing further (adapter already capped at `limit`).
- Money: `budget_max` param is tỷ VND → `int(x * 1e9)` VND (same convention as `recommend_units`).
- Never touch `develop`. Work on `feat/refactor2`. Commit per task.
- Run the smoke checklist (`src/noble_agent/SMOKE.md`) after Task 7 (prompt/turn-loop touch).

---

### Task 1: Config setting `NOBLE_DISCOVER_PAGE_SIZE`

**Files:**
- Modify: `src/noble_agent/config.py:446-450` (data-provider block)
- Modify: `.env.example` (data-provider section)
- Test: `tests/unit/unified/providers/test_factory.py` (append)

**Interfaces:**
- Produces: `UnifiedSettings.discover_page_size: int` (env `NOBLE_DISCOVER_PAGE_SIZE`, default `5`).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/unified/providers/test_factory.py`:

```python
def test_discover_page_size_default_is_5():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)  # bypass repo-local .env
    assert s.discover_page_size == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/providers/test_factory.py::test_discover_page_size_default_is_5 -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'discover_page_size'`

- [ ] **Step 3: Add the setting**

In `src/noble_agent/config.py`, inside the `# ── Data provider` block (right after `nbx_sales_api_token`):

```python
    # discover_projects funnel: how many projects returned per page (top-K)
    discover_page_size: int = 5
```

- [ ] **Step 4: Document in `.env.example`**

Under the data-provider section of `.env.example`, add:

```bash
# discover_projects: number of projects returned per page (funnel top-K)
NOBLE_DISCOVER_PAGE_SIZE=5
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/providers/test_factory.py::test_discover_page_size_default_is_5 -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py .env.example tests/unit/unified/providers/test_factory.py
git commit -m "feat(config): add NOBLE_DISCOVER_PAGE_SIZE (discover_projects page size)"
```

---

### Task 2: Canonical DTOs + Protocol (`base.py`)

**Files:**
- Modify: `src/noble_agent/data/providers/base.py:32-45` (extend `ProjectSummary`)
- Modify: `src/noble_agent/data/providers/base.py:162-168` (extend `RecommendQuery`)
- Modify: `src/noble_agent/data/providers/base.py` (add `DiscoverQuery`/`ProjectDiscovery` DTOs + Protocol method)
- Test: `tests/unit/unified/providers/test_base_contract.py` (append)

**Interfaces:**
- Produces:
  - `ProjectSummary(code, name, region, type, investor="", price_from_vnd=None, hot=False)` — new trailing optional fields.
  - `DiscoverQuery(region="", budget_max_vnd=0, product_type="", purpose="", investor="", offset=0, limit=5)`
  - `ProjectDiscovery(total: int, projects: list[ProjectSummary])`
  - `RecommendQuery(..., project_code="")` — new trailing field.
  - `DataProvider.discover_projects(self, query: DiscoverQuery) -> ProjectDiscovery | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/unified/providers/test_base_contract.py`:

```python
def test_project_summary_has_optional_discovery_fields():
    from noble_agent.data.providers import base

    s = base.ProjectSummary("NCLB", "Noble Crystal", "Long Biên", "chung_cu")
    assert s.investor == ""
    assert s.price_from_vnd is None
    assert s.hot is False
    s2 = base.ProjectSummary("X", "Y", "Z", "t", investor="CĐT", price_from_vnd=5_000_000_000, hot=True)
    assert (s2.investor, s2.price_from_vnd, s2.hot) == ("CĐT", 5_000_000_000, True)


def test_discover_dtos_and_recommend_project_code():
    from noble_agent.data.providers import base

    q = base.DiscoverQuery(region="Hà Nội", product_type="chung_cu", offset=5, limit=5)
    assert (q.region, q.product_type, q.offset, q.limit) == ("Hà Nội", "chung_cu", 5, 5)
    d = base.ProjectDiscovery(total=213, projects=[])
    assert d.total == 213 and d.projects == []
    assert base.RecommendQuery().project_code == ""
    assert base.RecommendQuery(project_code="NCLB").project_code == "NCLB"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/providers/test_base_contract.py -k "discovery_fields or discover_dtos" -v`
Expected: FAIL — `AttributeError`/`TypeError` on missing fields/DTOs.

- [ ] **Step 3: Extend `ProjectSummary`**

Replace the `ProjectSummary` dataclass (`base.py:32-38`) with:

```python
@dataclass(frozen=True)
class ProjectSummary:
    code: str
    name: str
    region: str
    type: str
    investor: str = ""
    price_from_vnd: int | None = None   # project entry price if source exposes one; else None
    hot: bool = False
```

- [ ] **Step 4: Add discovery DTOs**

Add after `ProjectList` (before `ProjectOverview`), keeping the DTO grouping:

```python
@dataclass(frozen=True)
class ProjectDiscovery:
    total: int                          # total matches BEFORE the page slice
    projects: list[ProjectSummary]      # already ranked (stable total order) + sliced [offset, offset+limit)
```

- [ ] **Step 5: Add `DiscoverQuery` + extend `RecommendQuery`**

In the query-objects block, add `DiscoverQuery` and add `project_code` to `RecommendQuery`:

```python
@dataclass(frozen=True)
class DiscoverQuery:
    region: str = ""
    budget_max_vnd: int = 0
    product_type: str = ""      # canonical enum value
    purpose: str = ""           # canonical enum value (advisory, not a filter)
    investor: str = ""
    offset: int = 0
    limit: int = 5
```

Edit `RecommendQuery` (`base.py:162-168`) to add a trailing field:

```python
@dataclass(frozen=True)
class RecommendQuery:
    region: str = ""
    budget_max_vnd: int = 0
    bedrooms: int = 0
    good_directions: frozenset[str] = field(default_factory=frozenset)
    limit: int = 6
    project_code: str = ""      # empty = cross-project (unchanged); set = scope to one project
```

- [ ] **Step 6: Add Protocol method**

In the `DataProvider` Protocol, add after `recommend_units` (`base.py:182`):

```python
    async def discover_projects(self, query: DiscoverQuery) -> ProjectDiscovery | None: ...
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/unified/providers/test_base_contract.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 8: Commit**

```bash
git add src/noble_agent/data/providers/base.py tests/unit/unified/providers/test_base_contract.py
git commit -m "feat(providers): discovery DTOs + ProjectSummary/RecommendQuery extensions"
```

---

### Task 3: `MongoProvider.discover_projects` + `recommend_units(project_code)`

**Files:**
- Modify: `src/noble_agent/data/providers/mongo.py` (add `discover_projects`; scope `recommend_units`)
- Test: `tests/unit/unified/providers/test_mongo_provider.py` (append + extend `patched_db`)

**Interfaces:**
- Consumes: `base.DiscoverQuery`, `base.ProjectDiscovery`, `base.ProjectSummary`, `base.RecommendQuery.project_code`, `_region_matches` (module helper).
- Produces: `MongoProvider.discover_projects(query) -> ProjectDiscovery | None`; `recommend_units` honoring `query.project_code`.

Notes for the implementer:
- mongo has **no** project-level hot field → `hot=False`, ranking is `code` asc only (still a total order). `price_from_vnd=None` (no project price field) so `budget_max_vnd` is a no-op on this legacy provider (documented).
- `product_type` (canonical) maps to a VN substring tested against `loai_hinh_sp` via a module dict.
- `investor` matches `chu_dau_tu` (case-insensitive substring, either direction — reuse the `_region_matches` idea via a small local helper).

- [ ] **Step 1: Write the failing tests**

First extend the `patched_db` fixture `du_an` list in `test_mongo_provider.py` to have 3 projects for pagination/filtering (add two more docs after the existing `NCLB` doc, inside the `du_an = [...]` list):

```python
        {
            "_id": "OID2",
            "ma_du_an": "NCTH",
            "ten_thuong_mai": "Noble Palace Tây Hồ",
            "khu_vuc": "Tây Hồ",
            "loai_hinh_sp": "Biệt thự",
            "chu_dau_tu": "Noble Group",
        },
        {
            "_id": "OID3",
            "ma_du_an": "SGR",
            "ten_thuong_mai": "Sunshine Green",
            "khu_vuc": "Long Biên",
            "loai_hinh_sp": "Căn hộ chung cư",
            "chu_dau_tu": "Sunshine Group",
        },
```

Append tests:

```python
async def test_discover_projects_ranks_and_paginates(patched_db):
    from noble_agent.data.providers import base

    p = MongoProvider()
    page1 = await p.discover_projects(base.DiscoverQuery(offset=0, limit=2))
    assert page1.total == 3
    assert [s.code for s in page1.projects] == ["NCLB", "NCTH"]  # code asc, stable total order
    page2 = await p.discover_projects(base.DiscoverQuery(offset=2, limit=2))
    assert [s.code for s in page2.projects] == ["SGR"]  # no overlap/skip with page1


async def test_discover_projects_region_filter(patched_db):
    from noble_agent.data.providers import base

    p = MongoProvider()
    got = await p.discover_projects(base.DiscoverQuery(region="Long Biên", limit=10))
    assert {s.code for s in got.projects} == {"NCLB", "SGR"}
    assert got.total == 2


async def test_discover_projects_product_type_and_investor(patched_db):
    from noble_agent.data.providers import base

    p = MongoProvider()
    villas = await p.discover_projects(base.DiscoverQuery(product_type="biet_thu", limit=10))
    assert [s.code for s in villas.projects] == ["NCTH"]
    sun = await p.discover_projects(base.DiscoverQuery(investor="Sunshine", limit=10))
    assert [s.code for s in sun.projects] == ["SGR"]


async def test_discover_projects_none_when_db_down(monkeypatch):
    from noble_agent.data.providers import base

    async def down():
        return None

    monkeypatch.setattr("noble_agent.data.providers.mongo.get_db", down)
    assert await MongoProvider().discover_projects(base.DiscoverQuery()) is None


async def test_recommend_units_scoped_to_project_code(patched_db):
    from noble_agent.data.providers import base

    p = MongoProvider()
    # NCLB is the only du_an with units in the fixture; scoping to NCTH → no units
    scoped = await p.recommend_units(base.RecommendQuery(project_code="NCTH"))
    assert scoped.units == []
    scoped_hit = await p.recommend_units(base.RecommendQuery(project_code="NCLB"))
    assert all(u.project_code == "NCLB" for u in scoped_hit.units)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/providers/test_mongo_provider.py -k "discover or scoped_to_project" -v`
Expected: FAIL — `AttributeError: 'MongoProvider' object has no attribute 'discover_projects'` (and the scope test fails since `project_code` is ignored today).

- [ ] **Step 3: Add product-type keyword map + investor helper**

Near the top of `mongo.py` (after `_region_matches`, ~line 152) add:

```python
# canonical product_type -> VN substring tested against `loai_hinh_sp`
_PRODUCT_TYPE_KW = {
    "chung_cu": ("chung cư", "căn hộ", "cao_tang", "cao tầng"),
    "biet_thu": ("biệt thự",),
    "lien_ke": ("liền kề", "shophouse", "nhà phố", "thấp tầng"),
    "shophouse": ("shophouse", "nhà phố thương mại"),
    "dat_nen": ("đất nền", "phân lô"),
    "van_phong": ("văn phòng", "office"),
}


def _product_type_matches(loai_hinh_sp: str, product_type: str) -> bool:
    if not product_type:
        return True
    hay = (loai_hinh_sp or "").strip().lower()
    return any(kw in hay for kw in _PRODUCT_TYPE_KW.get(product_type, ()))


def _investor_matches(chu_dau_tu: str, investor: str) -> bool:
    if not investor:
        return True
    a = (chu_dau_tu or "").strip().lower()
    b = investor.strip().lower()
    return bool(a) and (b in a or a in b)
```

- [ ] **Step 4: Implement `discover_projects`**

Add to `MongoProvider` right after `list_projects` (which stays for now; removed in Task 6 only if unreferenced — keep it, `db_project_registry`/registry may call it — verify: it is only called by the old tool, but leaving it is harmless). Insert:

```python
    async def discover_projects(self, query: base.DiscoverQuery) -> base.ProjectDiscovery | None:
        db = await get_db()
        if db is None:
            logger.warning("mongo provider: MongoDB unavailable")
            return None
        docs = [d async for d in db.project_du_an.find({})]
        if not docs:
            return None

        def _ok(d: dict) -> bool:
            if query.region and not _region_matches(d.get("khu_vuc", ""), query.region):
                return False
            if not _product_type_matches(d.get("loai_hinh_sp", ""), query.product_type):
                return False
            if not _investor_matches(d.get("chu_dau_tu", ""), query.investor):
                return False
            return True

        matched = [d for d in docs if _ok(d)]
        # stable total order: code asc (mongo has no hot field)
        matched.sort(key=lambda d: (d.get("ma_du_an") or "").strip())
        total = len(matched)
        page = matched[query.offset : query.offset + query.limit]
        projects = [
            base.ProjectSummary(
                code=(d.get("ma_du_an") or "").strip(),
                name=(d.get("ten_thuong_mai") or "").strip(),
                region=(d.get("khu_vuc") or "").strip(),
                type=(d.get("loai_hinh_sp") or "").strip(),
                investor=(d.get("chu_dau_tu") or "").strip(),
                price_from_vnd=None,   # legacy source has no project-level price
                hot=False,
            )
            for d in page
        ]
        return base.ProjectDiscovery(total=total, projects=projects)
```

- [ ] **Step 5: Scope `recommend_units` by `project_code`**

In `MongoProvider.recommend_units` (`mongo.py:493`), after the `if not proj: return None` guard and BEFORE the `if query.region:` filter, add a project-code scope:

```python
        if query.project_code:
            proj = [d for d in proj if (d.get("ma_du_an") or "").strip() == query.project_code]
            if not proj:
                return base.UnitRecommendation(units=[])
```

(Region filter still applies afterward; both narrow the same `proj` list.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/unified/providers/test_mongo_provider.py -v`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/data/providers/mongo.py tests/unit/unified/providers/test_mongo_provider.py
git commit -m "feat(mongo): discover_projects + recommend_units project_code scope"
```

---

### Task 4: `SalesApiProvider.discover_projects` + `recommend_units(project_code)`

**Files:**
- Modify: `src/noble_agent/data/providers/sales_api.py` (add `discover_projects`; scope `recommend_units`)
- Test: `tests/unit/unified/providers/test_sales_api_provider.py` (append + extend routes)

**Interfaces:**
- Consumes: `base.DiscoverQuery`, `base.ProjectDiscovery`, `base.ProjectSummary`, `base.RecommendQuery.project_code`, `name_to_code`, `_fetch_all_projects`.
- Produces: `SalesApiProvider.discover_projects(query) -> ProjectDiscovery | None`; `recommend_units` honoring `query.project_code`.

Notes:
- `region` → `area_region` server param (existing). `budget_max_vnd` → `price_max` (tỷ) server param when set (API decides qualifying projects).
- `product_type`/`investor` filtered **in-process** against `item["type"]`/`item["investor"]` (API param support unverified — do it client-side, bounded like `_fetch_all_projects`).
- Ranking reads defensively-present list-item fields: `isHot`, `isFeatured`, `sortHot`, `sortOrder` (absent → treated as not-hot / large sort). Final tiebreak `code` asc.
- `price_from_vnd` from `item.get("priceFrom")`/`item.get("price_from")` × 1e9 if present (reuse `_to_vnd`), else `None`.

- [ ] **Step 1: Write the failing tests**

Extend the `provider` fixture `routes` in `test_sales_api_provider.py` so `/api/v1/projects` returns a multi-item page (add or adjust the `"/api/v1/projects"` route payload — NOT the `/projects/{slug}` detail route):

```python
        "/api/v1/projects": {
            "total": 3,
            "items": [
                {"name": "MASTERI CENTRE POINT", "type": "can_ho", "areaRegion": "mien_nam",
                 "investor": "Masterise", "isHot": False, "sortOrder": 2},
                {"name": "VINHOMES OCEAN PARK", "type": "biet_thu", "areaRegion": "mien_bac",
                 "investor": "Vinhomes", "isHot": True, "sortHot": 1},
                {"name": "MASTERI WEST HEIGHTS", "type": "can_ho", "areaRegion": "mien_bac",
                 "investor": "Masterise", "isHot": False, "sortOrder": 1},
            ],
        },
```

Ensure `docs/api/project_code_map.json` maps those three names to codes; if not present in the real map, monkeypatch `name_to_code` in the test to a deterministic stub. Add a test-local monkeypatch to avoid coupling to the live map:

```python
@pytest.fixture
def discover_provider(provider, monkeypatch):
    codes = {
        "MASTERI CENTRE POINT": "MCP",
        "VINHOMES OCEAN PARK": "VOP",
        "MASTERI WEST HEIGHTS": "MWH",
    }
    monkeypatch.setattr(
        "noble_agent.data.providers.sales_api.name_to_code",
        lambda name: codes.get((name or "").upper().strip(), ""),
    )
    return provider
```

Append tests:

```python
async def test_discover_hot_first_ranking(discover_provider):
    from noble_agent.data.providers import base

    got = await discover_provider.discover_projects(base.DiscoverQuery(limit=10))
    assert got.total == 3
    assert got.projects[0].code == "VOP"      # isHot=True → first
    assert got.projects[0].hot is True
    # remaining ordered by sortOrder asc then code: MWH(1) before MCP(2)
    assert [s.code for s in got.projects[1:]] == ["MWH", "MCP"]


async def test_discover_pagination_stable(discover_provider):
    from noble_agent.data.providers import base

    p1 = await discover_provider.discover_projects(base.DiscoverQuery(offset=0, limit=2))
    p2 = await discover_provider.discover_projects(base.DiscoverQuery(offset=2, limit=2))
    assert [s.code for s in p1.projects] == ["VOP", "MWH"]
    assert [s.code for s in p2.projects] == ["MCP"]  # no overlap


async def test_discover_product_type_and_investor_filter(discover_provider):
    from noble_agent.data.providers import base

    villas = await discover_provider.discover_projects(base.DiscoverQuery(product_type="biet_thu", limit=10))
    assert [s.code for s in villas.projects] == ["VOP"]
    mast = await discover_provider.discover_projects(base.DiscoverQuery(investor="Masterise", limit=10))
    assert {s.code for s in mast.projects} == {"MCP", "MWH"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/providers/test_sales_api_provider.py -k discover -v`
Expected: FAIL — no `discover_projects` attribute.

- [ ] **Step 3: Add product-type keyword map (sales_api)**

Near the top of `sales_api.py` (after imports / module constants) add:

```python
# canonical product_type -> substrings tested against the API `type` string
_PRODUCT_TYPE_KW = {
    "chung_cu": ("can_ho", "chung", "căn hộ", "cao_tang"),
    "biet_thu": ("biet_thu", "biệt thự", "villa"),
    "lien_ke": ("lien_ke", "liền kề", "nha_pho", "shophouse", "thap_tang"),
    "shophouse": ("shophouse", "nha_pho"),
    "dat_nen": ("dat_nen", "đất nền"),
    "van_phong": ("van_phong", "office", "văn phòng"),
}


def _api_product_type_matches(api_type: str, product_type: str) -> bool:
    if not product_type:
        return True
    hay = (api_type or "").strip().lower()
    return any(kw in hay for kw in _PRODUCT_TYPE_KW.get(product_type, ()))


def _api_investor_matches(api_investor: str, investor: str) -> bool:
    if not investor:
        return True
    a = (api_investor or "").strip().lower()
    b = investor.strip().lower()
    return bool(a) and (b in a or a in b)


def _hot_sort_key(item: dict) -> tuple:
    """Stable total order: isHot desc, isFeatured desc, sortHot/sortOrder asc, then code asc.
    Absent flags sort as not-hot / large order. Caller appends code for the final tiebreak."""
    is_hot = 1 if item.get("isHot") else 0
    is_feat = 1 if item.get("isFeatured") else 0
    sort_hot = item.get("sortHot")
    sort_order = item.get("sortOrder")
    rank = sort_hot if sort_hot is not None else (sort_order if sort_order is not None else 10**9)
    return (-is_hot, -is_feat, rank)
```

- [ ] **Step 4: Implement `discover_projects`**

Add to `SalesApiProvider` right after `list_projects` (`sales_api.py:388`):

```python
    async def discover_projects(self, query: base.DiscoverQuery) -> base.ProjectDiscovery | None:
        params: dict = {}
        if query.region:
            params["area_region"] = query.region
        if query.budget_max_vnd:
            params["price_max"] = round(query.budget_max_vnd / 1e9, 4)  # API unit is tỷ
        items = await self._fetch_all_projects(params)
        if items is None:
            return None

        rows: list[tuple[tuple, base.ProjectSummary]] = []
        for item in items:
            code = name_to_code(item.get("name", ""))
            if not code:
                continue
            if not _api_product_type_matches(item.get("type", ""), query.product_type):
                continue
            if not _api_investor_matches(item.get("investor", ""), query.investor):
                continue
            summary = base.ProjectSummary(
                code=code,
                name=item.get("name", ""),
                region=item.get("areaRegion", ""),
                type=item.get("type", ""),
                investor=item.get("investor", "") or "",
                price_from_vnd=_to_vnd(item.get("priceFrom") or item.get("price_from")),
                hot=bool(item.get("isHot")),
            )
            rows.append((_hot_sort_key(item) + (code,), summary))

        rows.sort(key=lambda r: r[0])  # total order incl. code tiebreak
        total = len(rows)
        page = [s for _, s in rows[query.offset : query.offset + query.limit]]
        return base.ProjectDiscovery(total=total, projects=page)
```

- [ ] **Step 5: Scope `recommend_units` by `project_code`**

In `SalesApiProvider.recommend_units` (`sales_api.py:495`), inside the `for u in items:` loop, right after `code = name_to_code(proj.get("name", ""))` and the `if not code: continue` guard, add:

```python
            if query.project_code and code != query.project_code:
                continue
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/unified/providers/test_sales_api_provider.py -v`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/data/providers/sales_api.py tests/unit/unified/providers/test_sales_api_provider.py
git commit -m "feat(sales_api): discover_projects (hot-first, paginated) + recommend_units project_code scope"
```

---

### Task 5: Tool layer — `discover_projects` shaping + serializer + `recommend_units` forwarding

**Files:**
- Modify: `src/noble_agent/data/providers/_serialize.py` (add per-project discovery mapper)
- Modify: `src/noble_agent/agent/tools/projects_info.py` (add `discover_projects`; forward `project_code`)
- Test: `tests/unit/unified/test_discover_projects.py` (new)

**Interfaces:**
- Consumes: `providers.get_provider`, `base.DiscoverQuery`, `base.ProjectDiscovery`, `base.RecommendQuery.project_code`, `get_settings().discover_page_size`, `ESCALATE_SIGNAL`.
- Produces: `projects_info.discover_projects(args: dict) -> str` (JSON envelope); `_serialize.discover_project_json(s) -> dict`.

Envelope contract (what Luna sees): `{total, index, count, projects[], has_more, next_index, suggested_narrow[], instruction}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/unified/test_discover_projects.py`:

```python
"""discover_projects tool: envelope shaping over a fake provider."""

from __future__ import annotations

import json

import pytest

from noble_agent.agent.tools import projects_info
from noble_agent.data.providers import base


class _FakeProvider:
    def __init__(self, total, page):
        self._total, self._page = total, page
        self.last_query = None

    async def discover_projects(self, query):
        self.last_query = query
        return base.ProjectDiscovery(total=self._total, projects=self._page)


def _install(monkeypatch, provider):
    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: provider)


def _summ(code):
    return base.ProjectSummary(code, f"Dự án {code}", "Hà Nội", "chung_cu", investor="CĐT", hot=True)


async def test_envelope_has_more_and_suggested_narrow(monkeypatch):
    prov = _FakeProvider(total=213, page=[_summ("A"), _summ("B")])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 2})())

    out = json.loads(await projects_info.discover_projects({"region": "Hà Nội", "index": 0}))
    assert out["total"] == 213
    assert out["index"] == 0
    assert out["count"] == 2
    assert out["has_more"] is True
    assert out["next_index"] == 2
    assert [p["code"] for p in out["projects"]] == ["A", "B"]
    # region given → not suggested; budget/product_type/purpose/investor not given → suggested
    assert "region" not in out["suggested_narrow"]
    assert "budget_max" in out["suggested_narrow"]
    # provider received canonical query with limit = page size and offset = index
    assert prov.last_query.limit == 2 and prov.last_query.offset == 0
    assert prov.last_query.region == "Hà Nội"


async def test_envelope_last_page_no_more(monkeypatch):
    prov = _FakeProvider(total=2, page=[_summ("A"), _summ("B")])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())

    out = json.loads(await projects_info.discover_projects({"index": 0}))
    assert out["has_more"] is False
    assert "next_index" not in out


async def test_budget_converted_to_vnd(monkeypatch):
    prov = _FakeProvider(total=0, page=[])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())

    await projects_info.discover_projects({"budget_max": 5})
    assert prov.last_query.budget_max_vnd == 5_000_000_000


async def test_escalate_on_none(monkeypatch):
    class _Down:
        async def discover_projects(self, q):
            return None

    _install(monkeypatch, _Down())
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())
    out = await projects_info.discover_projects({})
    assert out == base.ESCALATE_SIGNAL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_discover_projects.py -v`
Expected: FAIL — `AttributeError: module 'noble_agent.agent.tools.projects_info' has no attribute 'discover_projects'`.

- [ ] **Step 3: Add the per-project serializer**

In `src/noble_agent/data/providers/_serialize.py`, add after `project_list_json`:

```python
def discover_project_json(s: base.ProjectSummary) -> dict:
    return {
        "code": s.code,
        "name": s.name,
        "region": s.region,
        "type": s.type,
        "investor": s.investor,
        "price_from_vnd": s.price_from_vnd,
        "hot": s.hot,
    }
```

- [ ] **Step 4: Implement the tool**

In `src/noble_agent/agent/tools/projects_info.py`, replace the `list_projects` function (`projects_info.py:23-28`) with `discover_projects`, and add the needed imports (`base.DiscoverQuery`). Add near the top import block:

```python
from noble_agent.data.providers.base import ESCALATE_SIGNAL, DiscoverQuery, RecommendQuery
```
(remove the now-partial `from ... import ESCALATE_SIGNAL, RecommendQuery` and use the combined line.)

Replace the function:

```python
# Priority order for narrowing hints (most useful first); capped to 2.
_NARROW_AXES = ("budget_max", "product_type", "region", "purpose", "investor")


async def discover_projects(args: dict) -> str:
    settings = get_settings()
    limit = settings.discover_page_size
    index = int(args.get("index") or 0)
    budget = args.get("budget_max") or 0
    provider = providers.get_provider(settings)
    result = await provider.discover_projects(
        DiscoverQuery(
            region=args.get("region", "") or "",
            budget_max_vnd=int(float(budget) * 1e9) if budget else 0,
            product_type=args.get("product_type", "") or "",
            purpose=args.get("purpose", "") or "",
            investor=args.get("investor", "") or "",
            offset=index,
            limit=limit,
        )
    )
    if result is None:
        return ESCALATE_SIGNAL

    count = len(result.projects)
    has_more = index + count < result.total
    given = {a for a in _NARROW_AXES if (args.get(a) or 0) not in ("", 0, None)}
    suggested = [a for a in _NARROW_AXES if a not in given][:2]

    remaining = result.total - (index + count)
    if result.total == 0:
        instruction = "Không có dự án khớp tiêu chí. Hãy gợi ý khách đổi khu vực hoặc nới tiêu chí, đừng bịa."
    elif has_more:
        hint = " hoặc ".join(suggested) if suggested else "tiêu chí khác"
        instruction = (
            f"Giới thiệu tối đa 3 dự án nổi bật trong số này, rồi hỏi khách muốn thêm tiêu chí "
            f"({hint}) hay nghe thêm {remaining} dự án còn lại."
        )
    else:
        instruction = "Giới thiệu các dự án này cho khách, dẫn dắt chọn 1 dự án để tìm hiểu sâu."

    payload: dict = {
        "total": result.total,
        "index": index,
        "count": count,
        "projects": [ser.discover_project_json(s) for s in result.projects],
        "has_more": has_more,
        "suggested_narrow": suggested,
        "instruction": instruction,
    }
    if has_more:
        payload["next_index"] = index + count
    return json.dumps(payload, ensure_ascii=False)
```

- [ ] **Step 5: Forward `project_code` in `recommend_units`**

In `projects_info.recommend_units` (the `RecommendQuery(...)` construction, `projects_info.py:94-100`), add `project_code`:

```python
    rec = await provider.recommend_units(
        RecommendQuery(
            region=args.get("region", "") or "",
            budget_max_vnd=int(float(budget_max) * 1e9) if budget_max else 0,
            bedrooms=args.get("bedrooms") or 0,
            good_directions=good,
            limit=6,
            project_code=args.get("project_code", "") or "",
        )
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_discover_projects.py -v`
Expected: PASS (all 4).

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/data/providers/_serialize.py src/noble_agent/agent/tools/projects_info.py tests/unit/unified/test_discover_projects.py
git commit -m "feat(tools): discover_projects envelope shaping + recommend_units project_code forward"
```

---

### Task 6: Wire the tool — schemas, dispatcher, config.json, stale tests

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py:110-130` (rename `list_projects`→`discover_projects` + new schema); `recommend_units` schema (add `project_code`)
- Modify: `src/noble_agent/agent/tools/dispatcher.py:131-137`
- Modify: `src/noble_agent/agent/definitions/config.json:10`
- Test/fix: `tests/unit/unified/test_tool_schemas.py:36`, and any other test referencing `list_projects`

**Interfaces:**
- Consumes: `projects_info.discover_projects`.
- Produces: tool name `discover_projects` in SCHEMAS + offered set; dispatch branch.

- [ ] **Step 1: Write/adjust the failing test**

In `tests/unit/unified/test_tool_schemas.py`, add a test asserting the new schema and enums, and update the stale name at line 36 (`"list_projects"` → `"discover_projects"`):

```python
def test_discover_projects_schema_enums():
    from noble_agent.agent.tools.schemas import SCHEMAS

    fn = SCHEMAS["discover_projects"]["function"]
    props = fn["parameters"]["properties"]
    assert props["product_type"]["enum"] == [
        "chung_cu", "biet_thu", "lien_ke", "shophouse", "dat_nen", "van_phong",
    ]
    assert props["purpose"]["enum"] == ["live", "invest"]
    assert "index" in props
    assert "list_projects" not in SCHEMAS


def test_recommend_units_has_project_code():
    from noble_agent.agent.tools.schemas import SCHEMAS

    assert "project_code" in SCHEMAS["recommend_units"]["function"]["parameters"]["properties"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_tool_schemas.py -k "discover_projects_schema or recommend_units_has_project" -v`
Expected: FAIL — `KeyError: 'discover_projects'`.

- [ ] **Step 3: Rewrite the schema entry**

In `schemas.py`, replace the whole `"list_projects": {...}` entry (`schemas.py:110-130`) with:

```python
    "discover_projects": {
        "type": "function",
        "function": {
            "name": "discover_projects",
            "description": (
                "Gợi ý top dự án phù hợp khi khách KHÁM PHÁ (chưa biết chọn dự án nào) — trả về "
                "một TRANG dự án nổi bật + tổng số khớp + gợi ý tiêu chí thu hẹp. Dùng cho 'bên "
                "em có dự án gì', 'dự án ở khu X', 'dự án của chủ đầu tư Y'. KHÔNG liệt kê hết: "
                "giới thiệu tối đa 3 dự án/lượt rồi thu hẹp. Xem thêm: gọi lại CÙNG tham số với "
                "index=next_index. Khách cho thêm tiêu chí: gọi lại tiêu chí mới với index=0. "
                "Khác recommend_units (gợi ý CĂN cụ thể). Ví dụ 'ở Long Biên có dự án gì'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "description": "Khu vực lấy đúng lời khách; '' = không lọc khu vực.",
                    },
                    "budget_max": {"type": "number", "description": "Ngân sách tối đa (tỷ VNĐ). Tùy chọn."},
                    "product_type": {
                        "type": "string",
                        "enum": ["chung_cu", "biet_thu", "lien_ke", "shophouse", "dat_nen", "van_phong"],
                        "description": "Loại hình sản phẩm khách muốn. Tùy chọn.",
                    },
                    "purpose": {
                        "type": "string",
                        "enum": ["live", "invest"],
                        "description": "Mục đích ở/đầu tư (chỉ để tư vấn, KHÔNG lọc). Tùy chọn.",
                    },
                    "investor": {"type": "string", "description": "Tên chủ đầu tư khách hỏi. Tùy chọn."},
                    "index": {
                        "type": "integer",
                        "description": "Offset phân trang, mặc định 0. Xem thêm → truyền next_index của lần trước.",
                    },
                },
                "required": [],
            },
        },
    },
```

- [ ] **Step 4: Add `project_code` to `recommend_units` schema**

In the `recommend_units` `properties` block (`schemas.py:273`), add as the first property:

```python
                    "project_code": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical (find_project) để chỉ gợi ý căn TRONG dự án đó. "
                            "Bỏ trống = gợi ý xuyên tất cả dự án."
                        ),
                    },
```

- [ ] **Step 5: Update dispatcher**

In `dispatcher.py:131-132`, change:

```python
        if name == "discover_projects":
            return await projects_info.discover_projects(args)
```

- [ ] **Step 6: Update offered tools**

In `src/noble_agent/agent/definitions/config.json`, change `"list_projects"` (line 10) to `"discover_projects"`.

- [ ] **Step 7: Fix remaining stale `list_projects` test references**

Run to find them: `grep -rn "list_projects" tests/ src/noble_agent/agent/tools/`
Update `tests/unit/unified/test_tool_schemas.py:36` (`"list_projects"` in the tools set → `"discover_projects"`) and any hit in `tests/unit/unified/test_projects_info_mongo.py` (rename calls to `projects_info.discover_projects`; adjust expected shape to the new envelope, or delete now-superseded list_projects-shape assertions if fully covered by `test_discover_projects.py` — prefer updating call name + asserting `total`/`projects`).

- [ ] **Step 8: Run the tool/schema + provider suites**

Run: `pytest tests/unit/unified/test_tool_schemas.py tests/unit/unified/test_discover_projects.py tests/unit/unified/providers/ -v`
Expected: PASS. Then `grep -rn "list_projects" src/ tests/` returns only intentional leftovers (ideally none in `src/`).

- [ ] **Step 9: Commit**

```bash
git add src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/dispatcher.py src/noble_agent/agent/definitions/config.json tests/
git commit -m "feat(tools): wire discover_projects (schema/dispatch/config) + recommend_units project_code param"
```

---

### Task 7: Prompt (RULES.md) — funnel behavior + tool catalog

**Files:**
- Modify: `src/noble_agent/agent/definitions/RULES.md` (tool catalog rows + discovery rule + escalate-signal list)

**Interfaces:** none (prompt-only). No new test; verify by live smoke.

- [ ] **Step 1: Update the discovery tool-catalog row**

In `RULES.md`, replace the `list_projects` catalog row (`RULES.md:134`):

```
| "Có dự án nào / bên em có gì / dự án ở khu X / của chủ đầu tư Y" | discover_projects(region/product_type/investor/budget_max nếu khách nêu). Trả về 1 TRANG: giới thiệu tối đa 3 dự án nổi bật, rồi hỏi thêm tiêu chí (theo suggested_narrow) HOẶC nghe thêm. Khách muốn xem thêm → gọi lại CÙNG tham số + index=next_index. Khách cho thêm tiêu chí → gọi lại tiêu chí mới + index=0. KHÔNG đọc quá 3 tên/lượt |
```

- [ ] **Step 2: Update the `recommend_units` catalog row**

Replace the `recommend_units` row (`RULES.md:139`) to mention `project_code`:

```
| "Gợi ý căn phù hợp / nên xem căn nào / hợp tuổi-mệnh-năm sinh của tôi" | recommend_units(budget_max, region, bedrooms, project_code nếu đã chốt 1 dự án, và birth_year/gender/menh/zodiac nếu khách hỏi phong thủy) |
```

- [ ] **Step 3: Update the escalate-signal list**

In the "Tín hiệu chuyển chuyên viên" paragraph (`RULES.md:146-147`), replace `list_projects` with `discover_projects` in the tool list.

- [ ] **Step 4: Update other `list_projects` mentions**

Fix the mentions at `RULES.md:18` and `RULES.md:34` (`list_projects` → `discover_projects`), keeping surrounding wording. Verify none remain: `grep -n "list_projects" src/noble_agent/agent/definitions/RULES.md` → no output.

- [ ] **Step 5: Sanity-load the agent definition**

Run: `python -c "from noble_agent.agent.base import load_agent_def; d=load_agent_def(); print(sorted(d.tool_names))"`
Expected: list includes `discover_projects`, excludes `list_projects`, still 12 tools.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/definitions/RULES.md
git commit -m "docs(prompt): funnel discovery rules for discover_projects + recommend_units project_code"
```

---

### Task 8: Full verification + CLAUDE.md change log

**Files:**
- Modify: `CLAUDE.md` (tool-catalog summary in the `agent/tools/` layout row + Change Log)
- No new code.

- [ ] **Step 1: Run the unit suite**

Run: `make test-unit`
Expected: no NEW failures vs baseline. (Pre-existing catalog/registry/.env failures noted in CLAUDE.md may remain — compare against a clean `git stash` baseline count if unsure.)

- [ ] **Step 2: Lint**

Run: `make lint`
Expected: clean (fix any ruff findings in touched files; `make format` if needed).

- [ ] **Step 3: Live smoke (text chat)**

Start the dev server (`scripts/run.sh --no-reload`), open `http://localhost:8766/chat`, and verify:
- "bên em có dự án gì ở Hà Nội?" → Luna calls `discover_projects`, names ≤3 projects, asks a narrowing question, does NOT dump a list.
- "cho anh xem thêm dự án nữa" → second `discover_projects` call with `index` advanced; different projects, no repeats.
- "gợi ý căn hợp tuổi anh trong [dự án vừa chọn]" → `recommend_units` with `project_code` set.
Capture the tool-call args from logs as evidence.

- [ ] **Step 4: Update CLAUDE.md**

- In the `agent/tools/` layout row, change the tool count and description: `list_projects` → `discover_projects` (funnel: top-K + total + suggested_narrow + index pagination), note `recommend_units` gained `project_code`.
- Append a Change Log row (date 2026-07-22) summarizing the reshape + spec/plan paths + branch `feat/refactor2`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document discover_projects funnel + recommend_units project_code"
```

---

## Self-Review

**Spec coverage:**
- §3 behavior (funnel, axes, narrowing signal, hot-first) → Tasks 3/4 (ranking+filter), Task 5 (suggested_narrow/instruction). ✓
- §4 contract (params, envelope, pagination, invariant) → Task 5 (envelope) + Tasks 3/4 (stable order slice). ✓
- §5 provider DTOs → Task 2; adapters → Tasks 3/4. ✓
- §6 recommend_units project_code → Tasks 2/3/4/5/6. ✓
- §7 prompt → Task 7. ✓
- §8 surface — every listed file has a task. ✓
- §9 risks (roster static; API capability; pagination stability) → documented in Global Constraints + Tasks 3/4 notes (out-of-scope roster untouched). ✓
- §10 completion criteria → Task 8 verification. ✓

**Placeholder scan:** no TBD/TODO; every code step shows full code. The binding `purpose` enum value is `live | invest`, consistent across schema/test/adapter steps. ✓

**Type consistency:** `discover_projects(args)->str` (tool) vs `discover_projects(query)->ProjectDiscovery|None` (provider) — distinct layers, names intentionally shared, signatures differ by design. `DiscoverQuery`/`ProjectDiscovery`/`ProjectSummary(...investor,price_from_vnd,hot)` field names identical across Tasks 2→3→4→5. `discover_project_json` (serializer) used only in Task 5. `_NARROW_AXES` values (`budget_max`,`product_type`,`region`,`purpose`,`investor`) match the schema property names in Task 6 (note: the tool param is `budget_max`, mapped to `DiscoverQuery.budget_max_vnd`). ✓
