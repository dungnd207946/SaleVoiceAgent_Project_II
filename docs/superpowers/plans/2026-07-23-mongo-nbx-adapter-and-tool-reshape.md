# MongoProvider `nbx_*` + Tool Reshape — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Viết lại `MongoProvider` để đọc bộ collection `nbx_*` (mirror offline của roster sales_api) và nắn lại 2 tool: gộp khoảng giá vào `get_project_overview`, đổi `get_project_financial` → `get_financial_policy` (chỉ còn chính sách tài chính).

**Architecture:** Hai provider (`sales_api`, `mongo`) trở thành hai mirror của cùng nguồn NBX, nói cùng canonical code + cùng `DataProvider` DTO. Helper thuần dùng chung tách ra `data/providers/_mapping.py`. `MongoProvider` join trực tiếp `nbx_projects.projectCode`, không cần `catalog.normalize`. Tool layer/dispatcher/serialize không đổi ở Phần A.

**Tech Stack:** Python 3.11+, motor (async Mongo), pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Ruff: line-length **120**, target **py311**, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` sạch trên file đã chạm.
- Canonical units bất biến: `price_*_vnd` = **VND int**, `area_*_m2` = **float m²**, `region`/`type`/`status` = enum canonical. Thiếu field → `None` (không bịa).
- DTO trong `base.py` **frozen** — không sửa DTO/contract trong plan này.
- `DataProvider` Protocol không đổi → tool layer, `dispatcher`, `_serialize` không sửa ở Phần A.
- Branch: `feat/refactor2`. **Không** đụng `develop`. Commit local trên branch hiện tại.
- Mặc định `NOBLE_DATA_SOURCE` giữ `sales_api` (không đổi default).
- `nbx_units.price`/`priceTts` theo **tỷ** → nhân `1e9` ra VND int (`_mapping.to_vnd`).
- Join: `nbx_units.projectId == nbx_projects._id` (UUID string); resolve code qua `nbx_projects.projectCode` (case-insensitive).
- Spec nguồn: `docs/superpowers/specs/2026-07-23-mongo-nbx-adapter-and-tool-reshape-design.md`.

---

## File Structure

- **Create** `src/noble_agent/data/providers/_mapping.py` — helper thuần dùng chung 2 provider.
- **Modify** `src/noble_agent/data/providers/sales_api.py` — import từ `_mapping`, giữ alias private cho test.
- **Rewrite** `src/noble_agent/data/providers/mongo.py` — đọc `nbx_projects`/`nbx_units`.
- **Modify** `src/noble_agent/data/structured_data.py` — gỡ re-export helper private đã biến mất.
- **Modify** `src/noble_agent/agent/tools/projects_info.py` — `get_project_overview` gộp khoảng giá.
- **Modify** `src/noble_agent/agent/tools/project_financial.py` — rename hàm, bỏ nhánh pricing.
- **Modify** `src/noble_agent/agent/tools/schemas.py` — schema 2 tool.
- **Modify** `src/noble_agent/agent/tools/dispatcher.py` — nhánh dispatch tên tool.
- **Modify** `src/noble_agent/agent/definitions/config.json` — danh sách tool offered.
- **Modify** `src/noble_agent/agent/definitions/RULES.md` — tool catalog.
- **Create** `tests/unit/unified/providers/test_mapping.py`.
- **Create** `tests/unit/unified/providers/test_mongo_nbx.py` (thay `test_mongo_provider.py`).
- **Delete** `tests/unit/unified/providers/test_mongo_provider.py`.
- **Modify** `tests/unit/unified/test_project_financial_mongo.py`, `test_projects_info_mongo.py`, `test_recommend_units.py`, `test_auto_escalate.py` — di trú fixture sang `nbx_*` + rename tool.

---

# PHASE A — MongoProvider đọc `nbx_*`

### Task 1: Tách `_mapping.py` (helper dùng chung)

**Files:**
- Create: `src/noble_agent/data/providers/_mapping.py`
- Modify: `src/noble_agent/data/providers/sales_api.py`
- Test: `tests/unit/unified/providers/test_mapping.py`

**Interfaces:**
- Produces: module `_mapping` với `to_vnd(price_ty)->int|None`, `canon_status(raw)->str`, `fold(s)->str`, `region_to_slug(region)->str`, `product_type_matches(api_type,product_type)->bool`, `hot_sort_key(item:dict)->tuple`, `bedrooms(unit_type_name)->int|None`, và các const `_STATUS_MAP`, `_REGION_SLUG_ALIASES`, `_PRODUCT_TYPE_KW`.
- `sales_api` giữ alias private (`_to_vnd`, `_canon_status`, `_fold`, `_region_to_slug`, `_api_product_type_matches`, `_hot_sort_key`, `_bedrooms`) trỏ vào `_mapping` để không đổi call-site + test import.

- [ ] **Step 1: Viết `_mapping.py`** (copy verbatim logic hiện có trong `sales_api.py`, chỉ đổi private→public)

Create `src/noble_agent/data/providers/_mapping.py`:

```python
"""Helper thuần (không I/O) dùng chung cho các DataProvider mirror cùng nguồn NBX
(sales_api HTTP + mongo nbx_*). Tách ra để 2 mirror không drift field-mapping.
"""

from __future__ import annotations

import unicodedata


def to_vnd(price_ty) -> int | None:
    """Giá nguồn theo tỷ (billions VND) -> VND int canonical."""
    try:
        return int(round(float(price_ty) * 1e9))
    except (TypeError, ValueError):
        return None


_STATUS_MAP = {
    "available": "available",
    "ready": "available",
    "sold": "sold",
    "locked": "booked",
    "hidden": "unknown",
}


def canon_status(raw) -> str:
    """Map enum status của nguồn -> canonical Unit.status."""
    return _STATUS_MAP.get((raw or "").strip().lower(), "unknown")


def fold(s: str) -> str:
    """Bỏ dấu, lowercase, gộp khoảng trắng — cho match region/tên.

    ``đ``/``Đ`` fold thủ công về ``d`` (ký tự Latin nguyên tử U+0110/U+0111,
    NFD không tách)."""
    s = (s or "").replace("đ", "d").replace("Đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


_REGION_SLUG_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mien_bac", ("mien bac", "phia bac", "bac bo", "ha noi", "hanoi", "hai phong", "quang ninh")),
    ("mien_trung", ("mien trung", "trung bo", "da nang", "danang", "hue", "nha trang", "khanh hoa", "quang nam")),
    ("mien_nam", ("mien nam", "phia nam", "nam bo", "sai gon", "saigon", "ho chi minh", "hcm", "tphcm",
                  "tp hcm", "binh duong", "dong nai", "long an", "can gio", "hoc mon")),
)


def region_to_slug(region: str) -> str:
    """Map region free-text -> macro area_region slug, hoặc '' nếu không phải macro."""
    f = fold(region)
    if not f:
        return ""
    if f.replace(" ", "_") in ("mien_bac", "mien_trung", "mien_nam"):
        return f.replace(" ", "_")
    for slug, phrases in _REGION_SLUG_ALIASES:
        if any(p in f for p in phrases):
            return slug
    return ""


_PRODUCT_TYPE_KW = {
    "chung_cu": ("cao_tang", "can_ho", "chung"),
    "biet_thu": ("thap_tang", "biet_thu", "villa"),
    "lien_ke": ("thap_tang", "lien_ke", "nha_pho", "shophouse"),
    "shophouse": ("thap_tang", "shophouse", "nha_pho"),
    "dat_nen": ("thap_tang", "dat_nen"),
    "van_phong": ("cao_tang", "van_phong", "office"),
}


def product_type_matches(api_type: str, product_type: str) -> bool:
    if not product_type:
        return True
    hay = (api_type or "").strip().lower()
    return any(kw in hay for kw in _PRODUCT_TYPE_KW.get(product_type, ()))


def hot_sort_key(item: dict) -> tuple:
    """Prefix rank: isHot desc, isFeatured desc, sortHot/sortOrder asc."""
    is_hot = 1 if item.get("isHot") else 0
    is_feat = 1 if item.get("isFeatured") else 0
    sort_hot = item.get("sortHot")
    sort_order = item.get("sortOrder")
    rank = sort_hot if sort_hot is not None else (sort_order if sort_order is not None else 10**9)
    return (-is_hot, -is_feat, rank)


def bedrooms(unit_type_name: str) -> int | None:
    s = (unit_type_name or "").strip().upper()
    if s.endswith("PN") and s[:-2].isdigit():
        return int(s[:-2])
    if s == "STUDIO":
        return 0
    return None
```

- [ ] **Step 2: Viết `test_mapping.py`**

Create `tests/unit/unified/providers/test_mapping.py`:

```python
from __future__ import annotations

import pytest

from noble_agent.data.providers import _mapping as m


@pytest.mark.parametrize("ty,vnd", [(2.88, 2_880_000_000), (0, 0), (None, None), ("x", None)])
def test_to_vnd(ty, vnd):
    assert m.to_vnd(ty) == vnd


@pytest.mark.parametrize("raw,exp", [
    ("available", "available"), ("ready", "available"), ("sold", "sold"),
    ("locked", "booked"), ("hidden", "unknown"), ("", "unknown"), (None, "unknown"), ("weird", "unknown"),
])
def test_canon_status(raw, exp):
    assert m.canon_status(raw) == exp


@pytest.mark.parametrize("region,slug", [
    ("miền bắc", "mien_bac"), ("Hà Nội", "mien_bac"), ("Sài Gòn", "mien_nam"),
    ("Đà Nẵng", "mien_trung"), ("Long Biên", ""), ("", ""),
])
def test_region_to_slug(region, slug):
    assert m.region_to_slug(region) == slug


@pytest.mark.parametrize("name,n", [("Studio", 0), ("2PN", 2), ("3 PN", None), ("Liền kề", None), ("", None)])
def test_bedrooms(name, n):
    assert m.bedrooms(name) == n


def test_product_type_matches_superset_low_rise():
    assert m.product_type_matches("thap_tang", "biet_thu") is True
    assert m.product_type_matches("cao_tang", "biet_thu") is False
    assert m.product_type_matches("cao_tang", "") is True


def test_hot_sort_key_orders_hot_first():
    hot = m.hot_sort_key({"isHot": True, "sortHot": 5})
    cold = m.hot_sort_key({"isHot": False, "sortOrder": 1})
    assert hot < cold


def test_fold_handles_d_stroke():
    assert m.fold("Đông Đô") == "dong do"
```

- [ ] **Step 3: Chạy test — kỳ vọng PASS** (module mới độc lập)

Run: `.venv/bin/python -m pytest tests/unit/unified/providers/test_mapping.py -q`
Expected: PASS (11 test).

- [ ] **Step 4: Refactor `sales_api.py` dùng `_mapping` + giữ alias**

Trong `src/noble_agent/data/providers/sales_api.py`:
1. Xoá các định nghĩa: `_to_vnd`, `_safe_json_obj` **(GIỮ — API-specific)**, `_bedrooms`, `_PRODUCT_TYPE_KW`, `_api_product_type_matches`, `_fold`, `_REGION_SLUG_ALIASES`, `_region_to_slug`, `_hot_sort_key`, `_STATUS_MAP`, `_canon_status`. (GIỮ lại `_safe_json_obj`.)
2. Thêm import + alias (đặt ngay sau khối import hiện có, trước `class _DNSCache`):

```python
from noble_agent.data.providers import _mapping

# Alias giữ call-site + test import (test_sales_api_provider import _canon_status, _region_to_slug).
_to_vnd = _mapping.to_vnd
_canon_status = _mapping.canon_status
_fold = _mapping.fold
_region_to_slug = _mapping.region_to_slug
_api_product_type_matches = _mapping.product_type_matches
_hot_sort_key = _mapping.hot_sort_key
_bedrooms = _mapping.bedrooms
```

Không đổi bất kỳ call-site nào khác (chúng vẫn gọi `_to_vnd(...)`, `_canon_status(...)`, v.v. qua alias).

- [ ] **Step 5: Chạy test sales_api — kỳ vọng PASS nguyên trạng**

Run: `.venv/bin/python -m pytest tests/unit/unified/providers/test_sales_api_provider.py tests/unit/unified/providers/test_mapping.py -q`
Expected: PASS (không regression).

- [ ] **Step 6: Lint + Commit**

```bash
make lint
git add src/noble_agent/data/providers/_mapping.py src/noble_agent/data/providers/sales_api.py tests/unit/unified/providers/test_mapping.py
git commit -m "refactor(providers): extract shared _mapping helpers from sales_api"
```

---

### Task 2: Viết lại `mongo.py` đọc `nbx_*`

**Files:**
- Rewrite: `src/noble_agent/data/providers/mongo.py`
- Test: `tests/unit/unified/providers/test_mongo_nbx.py` (create)
- Delete: `tests/unit/unified/providers/test_mongo_provider.py`

**Interfaces:**
- Consumes: `_mapping` (Task 1); `noble_agent.storage.mongo_client.get_db`; `noble_agent.data.providers._name_code_map.{all_codes,code_to_name_map}`.
- Produces: `class MongoProvider` thỏa `DataProvider` Protocol; collection reads `db.nbx_projects` / `db.nbx_units`. Module helper `_unit_type(raw)->tuple[str,str]`, `_resolve_project(db,code)->dict|None` (dùng trong test).

- [ ] **Step 1: Viết `test_mongo_nbx.py`** (fake db nbx, TDD)

Create `tests/unit/unified/providers/test_mongo_nbx.py`:

```python
"""MongoProvider đọc nbx_projects/nbx_units — DTO contract, fake in-memory db."""

from __future__ import annotations

import re

import pytest

from noble_agent.data.providers import base
from noble_agent.data.providers.mongo import MongoProvider


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _Coll:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query=None, projection=None):
        docs = self._docs
        q = query or {}
        pid = q.get("projectId")
        if isinstance(pid, dict) and "$in" in pid:
            allowed = set(pid["$in"])
            docs = [d for d in docs if d.get("projectId") in allowed]
        elif pid is not None:
            docs = [d for d in docs if d.get("projectId") == pid]
        return _Cursor(docs)

    async def find_one(self, query, projection=None):
        rx = (query or {}).get("projectCode", {})
        if isinstance(rx, dict) and "$regex" in rx:
            pat = re.compile(rx["$regex"], re.IGNORECASE)
            for d in self._docs:
                if pat.match(d.get("projectCode") or ""):
                    return d
            return None
        return self._docs[0] if self._docs else None


class _DB:
    def __init__(self, projects, units):
        self.nbx_projects = _Coll(projects)
        self.nbx_units = _Coll(units)


_PROJECTS = [
    {"_id": "u1", "projectCode": "VGP", "name": "VINHOMES GRAND PARK", "areaRegion": "mien_nam",
     "location": "TP Thủ Đức", "type": "cao_tang", "investor": "Vin Group", "isHot": True, "sortHot": 1,
     "overview": {"units_text": "10000 căn", "ownership": "Lâu dài", "scale": "271 ha", "product": "Căn hộ"}},
    {"_id": "u2", "projectCode": "GM", "name": "GRAND MARINA", "areaRegion": "mien_nam",
     "location": "Quận 1", "type": "cao_tang", "investor": "Masterise", "isHot": False, "sortOrder": 3,
     "overview": {"units_text": "4000 căn", "ownership": "Lâu dài", "scale": "10 ha", "product": "Căn hộ"}},
    {"_id": "u3", "projectCode": "IHHL", "name": "IMPERIA HOLIDAY HẠ LONG", "areaRegion": "mien_bac",
     "location": "Hạ Long", "type": "thap_tang", "investor": "MIK GROUP", "isHot": False, "sortOrder": 2,
     "overview": {"units_text": "500 căn", "ownership": "Lâu dài", "scale": "5 ha", "product": "Thấp tầng"}},
    # dự án không có projectCode -> bỏ qua
    {"_id": "u4", "projectCode": "", "name": "NO CODE", "areaRegion": "mien_bac", "type": "cao_tang"},
]
_UNITS = [
    {"_id": "c1", "code": "V-01", "projectId": "u1", "projectName": "VINHOMES GRAND PARK",
     "unitType": "STU", "price": 2.5, "priceTts": 2.3, "area": 30.0, "areaBuild": 32.0,
     "direction": "Đông", "status": "available", "image": None},
    {"_id": "c2", "code": "V-02", "projectId": "u1", "projectName": "VINHOMES GRAND PARK",
     "unitType": None, "price": 5.0, "priceTts": 0, "area": 60.0, "areaBuild": 60.0,
     "direction": "Tây Bắc Thông thủy 0 m² -->", "status": "available", "image": None},
    {"_id": "c3", "code": "H-01", "projectId": "u3", "projectName": "IMPERIA HOLIDAY HẠ LONG",
     "unitType": "LK", "price": 12.0, "priceTts": 10.0, "area": 120.0, "areaBuild": 150.0,
     "direction": "Nam", "status": "available", "image": None},
]


@pytest.fixture
def patched(monkeypatch):
    async def fake_get_db():
        return _DB(_PROJECTS, _UNITS)
    monkeypatch.setattr("noble_agent.data.providers.mongo.get_db", fake_get_db)
    return MongoProvider()


async def test_get_overview_maps_nbx_fields(patched):
    ov = await patched.get_overview("vgp")  # case-insensitive resolve
    assert ov is not None
    assert ov.code == "VGP" and ov.region == "mien_nam" and ov.district == "TP Thủ Đức"
    assert ov.total_units == "10000 căn" and ov.ownership == "Lâu dài"
    assert ov.land_area == "271 ha" and ov.product == "Căn hộ"
    assert ov.management is None and ov.total_investment_vnd is None


async def test_get_overview_none_for_unknown(patched):
    assert await patched.get_overview("ZZZ") is None


async def test_unit_mapping_price_ty_to_vnd_and_type(patched):
    units = await patched.search_units(base.UnitQuery(project_code="VGP", status="available"))
    assert units is not None
    u = next(x for x in units if x.unit_code == "V-01")
    assert u.price_vnd == 2_500_000_000 and u.price_early_vnd == 2_300_000_000
    assert u.unit_type == "Studio" and u.unit_type_group == "can_ho" and u.bedrooms == 0
    assert u.area_m2 == 30.0 and u.wall_area_m2 is None
    assert u.status == "available"
    other = next(x for x in units if x.unit_code == "V-02")
    assert other.unit_type == "Khác" and other.bedrooms is None


async def test_pricing_groups_by_type(patched):
    pt = await patched.get_pricing("VGP")
    assert pt is not None
    labels = {r.unit_type for r in pt.results}
    assert "Studio" in labels and "Khác" in labels


async def test_discover_ranks_hot_first(patched):
    d = await patched.discover_projects(base.DiscoverQuery(offset=0, limit=5))
    assert d.total == 3  # NO CODE bị bỏ
    assert d.projects[0].code == "VGP" and d.projects[0].hot is True


async def test_discover_region_macro_slug(patched):
    d = await patched.discover_projects(base.DiscoverQuery(region="miền bắc", limit=5))
    assert {p.code for p in d.projects} == {"IHHL"}


async def test_discover_investor_filter(patched):
    d = await patched.discover_projects(base.DiscoverQuery(investor="masterise", limit=5))
    assert {p.code for p in d.projects} == {"GM"}


async def test_inventory_summary(patched):
    inv = await patched.get_inventory_summary("VGP")
    assert inv.total == 2 and inv.available == 2
    types = {t.unit_type for t in inv.by_unit_type}
    assert "Studio" in types


async def test_recommend_cross_project_and_scoped(patched):
    allp = await patched.recommend_units(base.RecommendQuery(limit=6))
    assert allp is not None and len(allp.units) == 3  # tất cả available
    scoped = await patched.recommend_units(base.RecommendQuery(project_code="IHHL", limit=6))
    assert {u.project_code for u in scoped.units} == {"IHHL"}


async def test_recommend_budget_filter(patched):
    r = await patched.recommend_units(base.RecommendQuery(budget_max_vnd=3_000_000_000, limit=6))
    assert all(u.price_vnd <= 3_000_000_000 for u in r.units)


async def test_registry_from_warm(patched):
    await patched.warm()
    codes = set(patched.cached_codes())
    assert {"VGP", "GM", "IHHL"} <= codes
    assert patched.code_to_name()["VGP"] == "VINHOMES GRAND PARK"


async def test_registry_fallback_when_db_down(monkeypatch):
    async def down():
        return None
    monkeypatch.setattr("noble_agent.data.providers.mongo.get_db", down)
    p = MongoProvider()
    await p.warm()  # không set cache
    assert len(p.cached_codes()) > 0  # fallback _name_code_map roster


async def test_financial_capabilities_return_none(patched):
    assert await patched.get_payment_plans("VGP") is None
    assert await patched.get_loan_policies("VGP") is None
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL** (mongo.py còn schema cũ)

Run: `.venv/bin/python -m pytest tests/unit/unified/providers/test_mongo_nbx.py -q`
Expected: FAIL (get_overview trả None / AttributeError `nbx_projects`).

- [ ] **Step 3: Viết lại `src/noble_agent/data/providers/mongo.py`** (thay toàn bộ nội dung)

```python
"""MongoDB-backed DataProvider đọc bộ collection ``nbx_*`` (mirror NBX Sales API,
do job ingest ghi). Là bản mirror OFFLINE của roster sales_api: cùng canonical
code, cùng DTO, cùng contract.

Nguồn: ``nbx_projects`` (dự án, có ``projectCode`` canonical + ``overview{}`` +
hot flags) và ``nbx_units`` (căn hộ, join ``projectId == nbx_projects._id`` UUID).
Resolve code qua ``projectCode`` (case-insensitive) — KHÔNG dùng catalog.normalize.

``payment_plans``/``loan_policies``/``promotions``/``fees`` không có nguồn cấu
trúc trong nbx → luôn ``None`` (tool layer surfaces ESCALATE_SIGNAL).
``recommend_units`` trả RAW (không sort, không cắt) — feng-shui + cắt 6 do tool.
"""

from __future__ import annotations

import logging
import re
import time

from noble_agent.data.providers import _mapping, base
from noble_agent.data.providers._name_code_map import all_codes, code_to_name_map
from noble_agent.storage.mongo_client import get_db

logger = logging.getLogger("noble_agent.data.providers.mongo")


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# nbx_units.unitType là string viết tắt (LK/SL/ĐL/STU) hoặc null hoặc rác (HOT/KHE).
_ABBREV: dict[str, tuple[str, str]] = {
    "LK": ("Liền kề", "thap_tang"),
    "SL": ("Song lập", "thap_tang"),
    "ĐL": ("Đơn lập", "thap_tang"),
    "STU": ("Studio", "can_ho"),
}
# Tên loại hình đầy đủ hợp lệ (nbx_apartment_types) -> group, passthrough.
_TYPE_GROUP: dict[str, str] = {
    "STUDIO": "can_ho", "1PN": "can_ho", "2PN": "can_ho", "3PN": "can_ho", "PENTHOUSE": "can_ho",
    "LIỀN KỀ": "thap_tang", "SONG LẬP": "thap_tang", "ĐƠN LẬP": "thap_tang",
    "SHOPHOUSE": "thap_tang", "BIỆT THỰ": "thap_tang",
}


def _unit_type(raw) -> tuple[str, str]:
    """nbx_units.unitType -> (label hiển thị, group). Rác/null -> ('Khác', '')."""
    s = (raw or "").strip()
    if not s:
        return ("Khác", "")
    up = s.upper()
    if up in _ABBREV:
        return _ABBREV[up]
    if up in _TYPE_GROUP:
        return (s, _TYPE_GROUP[up])
    return ("Khác", "")


async def _resolve_project(db, code: str) -> dict | None:
    """App code -> full ``nbx_projects`` doc qua match ``projectCode`` (case-insensitive)."""
    c = (code or "").strip()
    if not c:
        return None
    return await db.nbx_projects.find_one({"projectCode": {"$regex": f"^{re.escape(c)}$", "$options": "i"}})


def _region_ok(doc: dict, region: str) -> bool:
    """Region macro slug khớp ``areaRegion``, hoặc district fold-match ``location``+``areaRegion``."""
    if not region:
        return True
    slug = _mapping.region_to_slug(region)
    if slug:
        return _mapping.fold(doc.get("areaRegion", "")) == slug
    hay = _mapping.fold((doc.get("location", "") or "") + " " + (doc.get("areaRegion", "") or ""))
    return _mapping.fold(region) in hay


class MongoProvider:
    name = "mongo"
    capabilities = frozenset(
        {
            base.Capability.LISTING,
            base.Capability.OVERVIEW,
            base.Capability.PRICING,
            base.Capability.UNIT_SEARCH,
            base.Capability.RECOMMEND,
            base.Capability.INVENTORY,
        }
    )

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}
        self._last_warm_ts = 0.0

    # ── unit mapping ───────────────────────────────────────────────────────
    def _unit_from(self, u: dict, code: str, project_name: str) -> base.Unit:
        label, group = _unit_type(u.get("unitType"))
        area = _to_float(u.get("area"))
        if area is None:
            area = _to_float(u.get("areaBuild"))
        return base.Unit(
            project_code=code,
            project_name=project_name,
            unit_code=u.get("code") or "",
            unit_type=label,
            unit_type_group=group,
            bedrooms=_mapping.bedrooms(label),
            area_m2=area,
            wall_area_m2=None,
            price_vnd=_mapping.to_vnd(u.get("price")),
            price_per_m2_vnd=None,
            price_early_vnd=_mapping.to_vnd(u.get("priceTts")),
            price_progress_vnd=None,
            price_loan_vnd=None,
            direction=(u.get("direction") or "").strip() or None,
            floor=None,
            view=None,
            status=_mapping.canon_status(u.get("status")),
            max_discount_pct=None,
            image_url=(u.get("image") or None),
        )

    async def _units_for(self, db, project_doc: dict) -> list[dict]:
        pid = project_doc.get("_id")
        return [u async for u in db.nbx_units.find({"projectId": pid})]

    # ── listing / overview ─────────────────────────────────────────────────
    async def list_projects(self, *, region: str = "") -> base.ProjectList | None:
        db = await get_db()
        if db is None:
            logger.warning("mongo provider: MongoDB unavailable")
            return None
        docs = [d async for d in db.nbx_projects.find({})]
        if not docs:
            return None
        coded = [d for d in docs if (d.get("projectCode") or "").strip()]

        def _summ(d: dict) -> base.ProjectSummary:
            return base.ProjectSummary(
                (d.get("projectCode") or "").strip(),
                d.get("name", "") or "",
                d.get("areaRegion", "") or "",
                d.get("type", "") or "",
            )

        if region:
            matched = [_summ(d) for d in coded if _region_ok(d, region)]
            if not matched:
                return base.ProjectList(0, [], region=region, note="Không tìm thấy khu vực này.")
            return base.ProjectList(len(matched), matched, region=region)
        subs = [_summ(d) for d in coded]
        return base.ProjectList(len(subs), subs)

    async def discover_projects(self, query: base.DiscoverQuery) -> base.ProjectDiscovery | None:
        db = await get_db()
        if db is None:
            logger.warning("mongo provider: MongoDB unavailable")
            return None
        docs = [d async for d in db.nbx_projects.find({})]
        if not docs:
            return None
        inv = _mapping.fold(query.investor) if query.investor else ""
        rows: list[tuple[tuple, base.ProjectSummary]] = []
        for idx, d in enumerate(docs):
            code = (d.get("projectCode") or "").strip()
            if not code:
                continue
            if not _region_ok(d, query.region):
                continue
            if not _mapping.product_type_matches(d.get("type", ""), query.product_type):
                continue
            if inv and inv not in _mapping.fold(d.get("investor", "")):
                continue
            summary = base.ProjectSummary(
                code=code,
                name=d.get("name", "") or "",
                region=d.get("areaRegion", "") or "",
                type=d.get("type", "") or "",
                investor=d.get("investor", "") or "",
                price_from_vnd=None,  # nbx projects không có giá cấp dự án
                hot=bool(d.get("isHot")),
            )
            rows.append((_mapping.hot_sort_key(d) + (idx,), summary))
        rows.sort(key=lambda r: r[0])
        total = len(rows)
        page = [s for _, s in rows[query.offset : query.offset + query.limit]]
        return base.ProjectDiscovery(total=total, projects=page)

    async def get_overview(self, project_code: str) -> base.ProjectOverview | None:
        db = await get_db()
        if db is None:
            logger.warning("mongo provider: MongoDB unavailable")
            return None
        doc = await _resolve_project(db, project_code)
        if not doc:
            return None
        ov = doc.get("overview") or {}
        return base.ProjectOverview(
            code=(doc.get("projectCode") or project_code),
            name=doc.get("name") or "",
            region=doc.get("areaRegion"),
            district=doc.get("location"),
            type=doc.get("type"),
            investor=doc.get("investor"),
            total_units=ov.get("units_text"),
            ownership=ov.get("ownership"),
            land_area=ov.get("scale"),
            description=doc.get("description"),
            product=ov.get("product"),
        )

    # ── pricing / inventory / search ─────────────────────────────────────────
    async def get_pricing(
        self, project_code: str, *, unit_type: str = "", max_price_vnd: int = 0
    ) -> base.PricingTable | None:
        db = await get_db()
        if db is None:
            return None
        doc = await _resolve_project(db, project_code)
        if not doc:
            return None
        raw = await self._units_for(db, doc)
        if not raw:
            return None
        code = (doc.get("projectCode") or project_code)
        pname = doc.get("name") or code
        groups: dict[str, dict] = {}
        for ru in raw:
            unit = self._unit_from(ru, code, pname)
            g = groups.setdefault(
                unit.unit_type or "Khác",
                {"group": unit.unit_type_group, "areas": [], "prices": [], "early": [], "total": 0, "avail": 0},
            )
            g["total"] += 1
            if unit.status == "available":
                g["avail"] += 1
            if unit.area_m2 is not None:
                g["areas"].append(unit.area_m2)
            if unit.price_vnd is not None:
                g["prices"].append(unit.price_vnd)
            if unit.price_early_vnd is not None:
                g["early"].append(unit.price_early_vnd)
        results = [
            base.UnitTypePricing(
                unit_type=label,
                group=g["group"],
                area_min_m2=min(g["areas"]) if g["areas"] else None,
                area_max_m2=max(g["areas"]) if g["areas"] else None,
                price_from_vnd=min(g["prices"]) if g["prices"] else None,
                price_to_vnd=max(g["prices"]) if g["prices"] else None,
                price_per_m2_from_vnd=None,
                price_per_m2_to_vnd=None,
                total_units=g["total"],
                available_units=g["avail"],
                price_early_from_vnd=min(g["early"]) if g["early"] else None,
                price_early_to_vnd=max(g["early"]) if g["early"] else None,
            )
            for label, g in groups.items()
        ]
        if unit_type:
            ut = unit_type.strip().upper()
            results = [r for r in results if ut in r.unit_type.upper() or ut in r.group.upper()]
        if max_price_vnd:
            results = [r for r in results if r.price_from_vnd is not None and r.price_from_vnd <= max_price_vnd]
        if not results:
            return None
        results.sort(key=lambda r: (r.price_from_vnd is None, r.price_from_vnd or 0))
        return base.PricingTable(code, results)

    async def search_units(self, query: base.UnitQuery) -> list[base.Unit] | None:
        db = await get_db()
        if db is None:
            return None
        doc = await _resolve_project(db, query.project_code)
        if not doc:
            return None
        raw = await self._units_for(db, doc)
        if not raw:
            return None
        code = (doc.get("projectCode") or query.project_code)
        pname = doc.get("name") or code
        out: list[base.Unit] = []
        for ru in raw:
            unit = self._unit_from(ru, code, pname)
            if (
                query.unit_type
                and query.unit_type.strip().upper() not in (unit.unit_type.upper() + unit.unit_type_group.upper())
            ):
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

    async def get_inventory_summary(self, project_code: str) -> base.InventorySummary | None:
        db = await get_db()
        if db is None:
            return None
        doc = await _resolve_project(db, project_code)
        if not doc:
            return None
        raw = await self._units_for(db, doc)
        if not raw:
            return None
        code = (doc.get("projectCode") or project_code)
        pname = doc.get("name") or code
        by_type: dict[str, dict] = {}
        by_dir: dict[str, int] = {}
        total = avail = 0
        for ru in raw:
            unit = self._unit_from(ru, code, pname)
            total += 1
            is_av = unit.status == "available"
            avail += 1 if is_av else 0
            t = by_type.setdefault(unit.unit_type or "Khác", {"total": 0, "available": 0, "prices": []})
            t["total"] += 1
            t["available"] += 1 if is_av else 0
            if unit.price_vnd is not None:
                t["prices"].append(unit.price_vnd)
            if unit.direction and is_av:
                by_dir[unit.direction] = by_dir.get(unit.direction, 0) + 1
        return base.InventorySummary(
            project_code=code,
            total=total,
            available=avail,
            by_unit_type=[
                base.InventoryByType(
                    unit_type=k,
                    total=v["total"],
                    available=v["available"],
                    price_from_vnd=min(v["prices"]) if v["prices"] else None,
                    price_to_vnd=max(v["prices"]) if v["prices"] else None,
                )
                for k, v in by_type.items()
            ],
            by_direction=[base.InventoryByDirection(d, n) for d, n in by_dir.items()],
        )

    # ── cross-project recommend (RAW) ────────────────────────────────────────
    async def recommend_units(self, query: base.RecommendQuery) -> base.UnitRecommendation | None:
        db = await get_db()
        if db is None:
            logger.warning("mongo provider: MongoDB unavailable")
            return None
        projs = [d async for d in db.nbx_projects.find({})]
        if not projs:
            return None
        if query.project_code:
            scope = query.project_code.strip().upper()
            projs = [d for d in projs if (d.get("projectCode") or "").strip().upper() == scope]
            if not projs:
                return base.UnitRecommendation(units=[])
        if query.region:
            projs = [d for d in projs if _region_ok(d, query.region)]
        if not projs:
            return base.UnitRecommendation(units=[])
        id2code = {d.get("_id"): (d.get("projectCode") or "").strip() for d in projs}
        id2name = {d.get("_id"): (d.get("name") or "").strip() for d in projs}
        units = [u async for u in db.nbx_units.find({"projectId": {"$in": list(id2code)}})]
        out: list[base.Unit] = []
        for ru in units:
            pid = ru.get("projectId")
            unit = self._unit_from(ru, id2code.get(pid, ""), id2name.get(pid, ""))
            if unit.status not in ("available", "unknown"):
                continue
            if query.bedrooms and unit.bedrooms != query.bedrooms:
                continue
            if query.budget_max_vnd and (unit.price_vnd is None or unit.price_vnd > query.budget_max_vnd):
                continue
            out.append(unit)
        return base.UnitRecommendation(out)

    # ── no structured source → hand off ──────────────────────────────────────
    async def get_payment_plans(self, project_code: str) -> None:
        return None

    async def get_loan_policies(self, project_code: str) -> None:
        return None

    async def get_promotions(self, project_code: str) -> None:
        return None

    async def get_project_fees(self, project_code: str) -> None:
        return None

    # ── registry ─────────────────────────────────────────────────────────────
    async def warm(self) -> None:
        self._last_warm_ts = time.monotonic()
        try:
            db = await get_db()
            if db is None:
                logger.info("mongo provider: Mongo unavailable; using fallback roster")
                return
            projection = {"projectCode": 1, "name": 1, "areaRegion": 1, "type": 1}
            new: dict[str, dict] = {}
            async for d in db.nbx_projects.find({}, projection):
                code = (d.get("projectCode") or "").strip()
                if not code:
                    continue
                new[code] = {
                    "code": code,
                    "name": d.get("name", "") or "",
                    "region": d.get("areaRegion", "") or "",
                    "type": d.get("type", "") or "",
                }
            if new:
                self._cache = new
                logger.info("mongo provider: warmed %d projects", len(self._cache))
        except Exception as exc:  # noqa: BLE001 — boot must survive
            logger.warning("mongo provider warm failed (using fallback): %s", exc)

    async def warm_if_stale(self, ttl_sec: float) -> None:
        if ttl_sec <= 0:
            return
        if (time.monotonic() - self._last_warm_ts) < ttl_sec:
            return
        await self.warm()

    def registry_rows(self) -> list[base.ProjectRegistryRow]:
        if self._cache:
            return [
                base.ProjectRegistryRow(v["code"], v["name"], v["region"], v["type"])
                for v in self._cache.values()
            ]
        c2n = code_to_name_map()
        return [base.ProjectRegistryRow(c, c2n.get(c, ""), "", "") for c in all_codes()]

    def cached_codes(self) -> list[str]:
        return list(self._cache) if self._cache else all_codes()

    def code_to_name(self) -> dict[str, str]:
        if self._cache:
            return {c: v["name"] for c, v in self._cache.items()}
        c2n = code_to_name_map()
        return {c: c2n.get(c, "") for c in all_codes()}
```

- [ ] **Step 4: Xoá test cũ + chạy test mới**

```bash
git rm tests/unit/unified/providers/test_mongo_provider.py
.venv/bin/python -m pytest tests/unit/unified/providers/test_mongo_nbx.py -q
```
Expected: PASS (14 test).

- [ ] **Step 5: Lint + Commit**

```bash
make lint
git add src/noble_agent/data/providers/mongo.py tests/unit/unified/providers/test_mongo_nbx.py
git commit -m "feat(providers): MongoProvider reads nbx_projects/nbx_units (mirror sales_api roster)"
```

---

### Task 3: Dọn `structured_data` shim + di trú test tool-level sang `nbx_*`

**Files:**
- Modify: `src/noble_agent/data/structured_data.py`
- Modify: `tests/unit/unified/test_project_financial_mongo.py`
- Modify: `tests/unit/unified/test_projects_info_mongo.py`
- Modify: `tests/unit/unified/test_recommend_units.py`

**Interfaces:**
- Consumes: `MongoProvider` (Task 2). Fake db mới dùng collection `nbx_projects`/`nbx_units`.

- [ ] **Step 1: Gỡ re-export helper private đã biến mất trong `structured_data.py`**

Trong `src/noble_agent/data/structured_data.py`:
1. Đổi block import (dòng 22–27) từ:

```python
from noble_agent.data.providers.mongo import (
    MongoProvider,
    _all_overview_fields_empty,  # re-export: directly unit-tested
    _resolve_du_an_id,  # re-export: directly unit-tested
    resolve_project_ref,  # re-export: alias-aware (db, code) -> (du_an_id, name)
)
```

thành:

```python
from noble_agent.data.providers.mongo import MongoProvider
```

2. Trong `__all__` (dòng 29–43) xoá 3 phần tử: `"resolve_project_ref"`, `"_all_overview_fields_empty"`, `"_resolve_du_an_id"`.

- [ ] **Step 2: Di trú fixture 3 file test tool-level sang `nbx_*`**

Với MỖI file (`test_project_financial_mongo.py`, `test_projects_info_mongo.py`, `test_recommend_units.py`), đọc file rồi áp đổi:

1. **Fake db:** đổi `_DB({"project_du_an": _Coll(projects), "project_can_ho": _Coll(units)})` → `_DB` có attr `nbx_projects` / `nbx_units`. Cập nhật `_Coll.find` để lọc theo `projectId` (thay `du_an_id`) và `_Coll.find_one` để match regex `projectCode` (xem `_Coll` mẫu trong `tests/unit/unified/providers/test_mongo_nbx.py` — copy y hệt class `_Coll`/`_Cursor`/`_DB`).
2. **Fixture project docs:** đổi field theo bảng dưới. Đặt `_id` = UUID string (vd `"u1"`), thêm `projectCode`.
3. **Fixture unit docs:** đổi field theo bảng; **đặt `price` (tỷ) = giá_VND_mong_muốn / 1e9** để assertion `price_vnd` giữ nguyên giá trị VND cũ (giảm churn). Tương tự `priceTts` cho `price_early_vnd`.
4. `bson.ObjectId` không còn cần cho `_id` (nbx dùng UUID string) — bỏ import nếu orphan.

**Bảng đổi field project (`project_du_an` → `nbx_projects`):**

| cũ | mới |
|---|---|
| `ma_du_an` | `projectCode` |
| `ten_thuong_mai` | `name` |
| `khu_vuc` | `areaRegion` (dùng slug `mien_bac`/`mien_nam`… hoặc để test district thì set `location`) |
| `vi_tri` | `location` |
| `loai_hinh_sp` | `type` (`cao_tang`/`thap_tang`) |
| `chu_dau_tu` | `investor` |
| overview fields (`tong_so_can`,`hinh_thuc_so_huu`,`dien_tich_dat_m2`…) | `overview.units_text`/`overview.ownership`/`overview.scale`/`overview.product` |

**Bảng đổi field unit (`project_can_ho` → `nbx_units`):**

| cũ | mới |
|---|---|
| `du_an_id` (str parent _id) | `projectId` (= parent `_id`) |
| `ma_can` | `code` |
| `gia_vnd` (VND int) | `price` (tỷ = gia_vnd/1e9) |
| `dien_tich_thong_thuy_m2` | `area` |
| `dien_tich_tim_tuong_m2` | `areaBuild` |
| `huong` | `direction` |
| `trang_thai` (`mở bán`…) | `status` (`available`/`sold`/`locked`) |
| `so_phong_ngu` / `loai_san_pham` | `unitType` (str: `STU`/`LK`/`2PN`… — bedrooms suy từ đây) |
| `gia_m2_vnd` | (bỏ — `price_per_m2_vnd` giờ luôn None) |
| `chiet_khau_toi_da_pct` | (bỏ — `max_discount_pct` giờ luôn None) |

5. **Cập nhật assertion đã đổi ngữ nghĩa:**
   - `price_per_m2_vnd`, `max_discount_pct`, `wall_area_m2` giờ luôn `None` → sửa assert tương ứng.
   - `bedroom_count`: chỉ khớp khi `unitType` là `STU`(→0) hoặc `NPN`; các loại thấp tầng → `None`. Chọn `unitType` fixture để giữ ý định test (vd test "2PN dưới 5 tỷ" → set `unitType="2PN"`).
   - `type`/`product_kind`: khớp label `_unit_type` (vd `LK`→`Liền kề`/`thap_tang`).
   - Region: nếu test lọc theo macro (`mien_bac`) set `areaRegion` slug; nếu lọc theo district set `location`.

- [ ] **Step 3: Chạy 3 file test — kỳ vọng PASS**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_project_financial_mongo.py tests/unit/unified/test_projects_info_mongo.py tests/unit/unified/test_recommend_units.py -q`
Expected: PASS (nếu assert nào phản ánh hành vi cũ đã bỏ như tim-tường/m² thì đã sửa ở Step 2.5).

- [ ] **Step 4: Lint + Commit**

```bash
make lint
git add src/noble_agent/data/structured_data.py tests/unit/unified/test_project_financial_mongo.py tests/unit/unified/test_projects_info_mongo.py tests/unit/unified/test_recommend_units.py
git commit -m "test+refactor: migrate mongo-backed tests to nbx_* fixtures; trim structured_data shim"
```

---

# PHASE B — Nắn `get_project_overview` + `get_project_financial`

### Task 4: `get_project_overview` hấp thụ khoảng giá tổng

**Files:**
- Modify: `src/noble_agent/agent/tools/projects_info.py:79-85`
- Modify: `src/noble_agent/agent/tools/schemas.py:150-172` (description)
- Test: `tests/unit/unified/test_projects_info_mongo.py`

**Interfaces:**
- Consumes: `provider.get_overview(code)->ProjectOverview|None`, `provider.get_pricing(code)->PricingTable|None`, `ser.overview_json(ov)->dict`.
- Produces: payload overview có thêm `price_from_vnd`/`price_to_vnd` (int|None).

- [ ] **Step 1: Viết test khoảng giá trong overview**

Thêm vào `tests/unit/unified/test_projects_info_mongo.py` (dùng fake db nbx đã có sau Task 3):

```python
async def test_overview_includes_price_range(patched_pi_db):
    out = json.loads(await pi.get_project_overview({"project_code": "VGP"}))
    assert "price_from_vnd" in out and "price_to_vnd" in out
    assert out["price_from_vnd"] == 2_500_000_000  # min price unit của VGP
    assert out["price_to_vnd"] == 5_000_000_000    # max price unit của VGP


async def test_overview_price_range_null_when_no_units(patched_pi_db):
    out = json.loads(await pi.get_project_overview({"project_code": "GM"}))  # GM không có unit
    assert out["price_from_vnd"] is None and out["price_to_vnd"] is None
```

(Điều chỉnh tên fixture/giá theo fixture thực tế của file sau Task 3; đảm bảo có 1 dự án có units và 1 dự án không.)

- [ ] **Step 2: Chạy test — kỳ vọng FAIL** (`KeyError: 'price_from_vnd'`)

Run: `.venv/bin/python -m pytest tests/unit/unified/test_projects_info_mongo.py -k price_range -q`
Expected: FAIL.

- [ ] **Step 3: Sửa `get_project_overview`** trong `src/noble_agent/agent/tools/projects_info.py`

Thay hàm (dòng 79–85):

```python
async def get_project_overview(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    code_or_name = (args.get("project_code", "") or "") or (args.get("project_name", "") or "")
    result = await provider.get_overview(code_or_name)
    if result is None:
        return ESCALATE_SIGNAL
    payload = ser.overview_json(result)
    # Gộp khoảng giá TỔNG (min price_from / max price_to trên mọi loại căn).
    pricing = await provider.get_pricing(result.code or code_or_name)
    lows = [r.price_from_vnd for r in pricing.results if r.price_from_vnd is not None] if pricing else []
    highs = [r.price_to_vnd for r in pricing.results if r.price_to_vnd is not None] if pricing else []
    payload["price_from_vnd"] = min(lows) if lows else None
    payload["price_to_vnd"] = max(highs) if highs else None
    return json.dumps(payload, ensure_ascii=False)
```

- [ ] **Step 4: Sửa description schema** `get_project_overview` trong `src/noble_agent/agent/tools/schemas.py` (dòng 154–158):

```python
            "description": (
                "Lấy tổng quan MỘT dự án: vị trí, loại hình, quy mô, chủ đầu tư, và KHOẢNG GIÁ "
                "(giá từ - đến). Dùng khi khách hỏi giới thiệu chung hoặc hỏi giá của một dự án. "
                "Ví dụ 'dự án đó thế nào', 'giá khoảng bao nhiêu'."
            ),
```

- [ ] **Step 5: Chạy test — kỳ vọng PASS**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_projects_info_mongo.py -q`
Expected: PASS.

- [ ] **Step 6: Lint + Commit**

```bash
make lint
git add src/noble_agent/agent/tools/projects_info.py src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_projects_info_mongo.py
git commit -m "feat(tools): get_project_overview includes overall price range"
```

---

### Task 5: Đổi tên `get_project_financial` → `get_financial_policy`, bỏ pricing + unit_type

**Files:**
- Modify: `src/noble_agent/agent/tools/project_financial.py`
- Modify: `src/noble_agent/agent/tools/schemas.py:174-201`
- Modify: `src/noble_agent/agent/tools/dispatcher.py:174-176`
- Modify: `src/noble_agent/agent/definitions/config.json`
- Modify: `src/noble_agent/agent/definitions/RULES.md`
- Test: `tests/unit/unified/test_project_financial_mongo.py`, `tests/unit/unified/test_auto_escalate.py`

**Interfaces:**
- Produces: hàm `project_financial.get_financial_policy(args)->str`; tool name `get_financial_policy` với `info_type ∈ {payment_plans, loan_policies, promotions, fees}`, không có param `unit_type`.

- [ ] **Step 1: Sửa test `test_project_financial_mongo.py`**

Trong file: đổi mọi tham chiếu `pf.get_project_financial` → `pf.get_financial_policy`; xoá/đổi các test dùng `info_type="pricing"` (pricing đã sang overview — nếu có test pricing ở đây, chuyển kỳ vọng sang ESCALATE hoặc xoá và để overview test lo). Thêm test:

```python
async def test_financial_policy_always_escalates(patched_pf_db):
    for it in ("payment_plans", "loan_policies", "promotions", "fees"):
        out = await pf.get_financial_policy({"project_code": "VGP", "info_type": it})
        assert out == pf.ESCALATE_SIGNAL


async def test_financial_policy_has_no_pricing_or_unit_type():
    from noble_agent.agent.tools import schemas
    props = schemas.SCHEMAS["get_financial_policy"]["function"]["parameters"]["properties"]
    assert "unit_type" not in props
    assert set(props["info_type"]["enum"]) == {"payment_plans", "loan_policies", "promotions", "fees"}
```

(`pf.ESCALATE_SIGNAL` — thêm import `from noble_agent.data.providers.base import ESCALATE_SIGNAL` trong `project_financial.py` đã có; expose trong test qua `pf.ESCALATE_SIGNAL`.)

- [ ] **Step 2: Chạy test — kỳ vọng FAIL** (`AttributeError: get_financial_policy` / KeyError schema)

Run: `.venv/bin/python -m pytest tests/unit/unified/test_project_financial_mongo.py -k "financial_policy" -q`
Expected: FAIL.

- [ ] **Step 3: Đổi `project_financial.py`** — rename hàm + bỏ nhánh pricing

Thay `get_project_financial` (dòng 21–41) bằng:

```python
async def get_financial_policy(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    project = args.get("project_code", "") or ""
    info_type = args.get("info_type", "payment_plans") or "payment_plans"
    fn = {
        "payment_plans": provider.get_payment_plans,
        "loan_policies": provider.get_loan_policies,
        "promotions": provider.get_promotions,
        "fees": provider.get_project_fees,
    }.get(info_type)
    if fn is None:
        return json.dumps({"error": f"Unknown info_type: {info_type}"}, ensure_ascii=False)
    result = await fn(project)
    if result is None:
        return ESCALATE_SIGNAL
    return json.dumps(result, ensure_ascii=False)
```

- [ ] **Step 4: Sửa schema** trong `src/noble_agent/agent/tools/schemas.py` — đổi key + name + description, bỏ `unit_type`, sửa enum:

```python
    "get_financial_policy": {
        "type": "function",
        "function": {
            "name": "get_financial_policy",
            "description": (
                "Lấy chính sách tài chính của một dự án: chính sách thanh toán, chính sách vay ngân "
                "hàng, ưu đãi, hoặc các loại phí. Dùng khi khách hỏi điều khoản tài chính (KHÔNG phải "
                "giá — giá dùng get_project_overview). Ví dụ 'trả góp thế nào', 'vay được bao nhiêu %'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical do find_project trả về; bỏ trống để dùng dự án đang quan tâm."
                        ),
                    },
                    "info_type": {
                        "type": "string",
                        "enum": ["payment_plans", "loan_policies", "promotions", "fees"],
                    },
                },
                "required": ["project_code", "info_type"],
            },
        },
    },
```

- [ ] **Step 5: Sửa dispatcher** `src/noble_agent/agent/tools/dispatcher.py` (dòng 174–176):

```python
        if name == "get_financial_policy":
            _require(...)  # giữ nguyên args guard hiện có nếu có
            return await project_financial.get_financial_policy(args)
```
(Giữ nguyên phần guard/`_require` nếu dòng 175 có; chỉ đổi tên `name` so sánh + tên hàm gọi.)

- [ ] **Step 6: Sửa `config.json`** — trong `"tools"` đổi `"get_project_financial"` → `"get_financial_policy"`.

- [ ] **Step 7: Sửa `RULES.md`** — hàng tool-catalog `get_project_financial`: đổi tên thành `get_financial_policy`, mô tả "chính sách thanh toán/vay/ưu đãi/phí (không còn giá — giá hỏi qua get_project_overview)". Nếu có hàng nào nhắc `get_project_overview` thì bổ sung "kèm khoảng giá".

- [ ] **Step 8: Sửa `test_auto_escalate.py`** — nếu test gọi tool tên `get_project_financial` hoặc patch `sd.get_project_pricing` cho nhánh pricing: đổi sang `get_financial_policy` + patch method chính sách (`sd.get_payment_plans`…) trả None; nếu test kiểm auto-escalate qua overview-pricing thì cập nhật theo hành vi mới. Đọc file, chỉnh các assertion tên tool cho khớp.

- [ ] **Step 9: Chạy test liên quan — kỳ vọng PASS**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_project_financial_mongo.py tests/unit/unified/test_auto_escalate.py tests/unit/unified/test_agent_def.py -q`
Expected: PASS (`test_agent_def` xác nhận tool set: có `get_financial_policy`, không có `get_project_financial`, count không đổi = 12).

- [ ] **Step 10: Lint + Commit**

```bash
make lint
git add src/noble_agent/agent/tools/project_financial.py src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/dispatcher.py src/noble_agent/agent/definitions/config.json src/noble_agent/agent/definitions/RULES.md tests/unit/unified/test_project_financial_mongo.py tests/unit/unified/test_auto_escalate.py
git commit -m "feat(tools): rename get_project_financial->get_financial_policy, drop pricing+unit_type"
```

---

### Task 6: Verify toàn bộ

**Files:** (none — verification)

- [ ] **Step 1: Full unit suite, đối chiếu baseline**

Run: `.venv/bin/python -m pytest tests/unit -q 2>&1 | tail -30`
Expected: Không có failure MỚI ngoài baseline pre-existing đã biết (2 USD-normalize, 2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt "Tên:"). Nếu có failure mới → điều tra tại task tương ứng.

- [ ] **Step 2: Lint toàn bộ file đã chạm**

Run: `make lint`
Expected: sạch.

- [ ] **Step 3: Smoke code-level — agent load + tool set**

Run:
```bash
.venv/bin/python -c "
from noble_agent.agent.base import load_agent_def
from pathlib import Path
d = load_agent_def(Path('src/noble_agent/agent/definitions'))
names = set(d.tool_names)
assert 'get_financial_policy' in names, names
assert 'get_project_financial' not in names, names
print('tools:', len(names), 'OK')
"
```
Expected: in `tools: 12 OK`.

- [ ] **Step 4: Smoke provider mongo (live) — nếu có Mongo dev**

Run:
```bash
NOBLE_DATA_SOURCE=mongo .venv/bin/python -c "
import asyncio
from noble_agent.config import get_settings
from noble_agent.data import providers
async def main():
    p = providers.get_provider(get_settings())
    await p.warm()
    print('codes:', len(p.cached_codes()))
    ov = await p.get_overview(p.cached_codes()[0])
    print('overview ok:', ov is not None and ov.code)
    d = await p.discover_projects(providers.base.__dict__['DiscoverQuery'](limit=3)) if False else None
asyncio.run(main())
"
```
Expected: `codes: N` (N>0), `overview ok: <CODE>`. (Bỏ qua nếu không có Mongo dev — đã cover bằng fake-db test.)

- [ ] **Step 5: SMOKE.md thủ công** — chạy checklist `src/noble_agent/SMOKE.md` cho phần chạm prompt/tool (đổi tên tool + description overview/financial): mở `/chat`, hỏi "giới thiệu + giá dự án X" → gọi `get_project_overview` có khoảng giá; hỏi "trả góp thế nào" → `get_financial_policy` → auto-escalate.

---

## Self-Review

**Spec coverage:**
- A.1 định vị mirror → Task 2 (mongo.py). ✓
- A.2 `_mapping.py` + refactor sales_api → Task 1. ✓
- A.3 field mapping (unit + overview + abbrev map) → Task 2 Step 3. ✓
- A.4 hành vi từng method (list/discover/overview/pricing/inventory/search/recommend/registry/policy=None) → Task 2. ✓
- A.5 dọn `structured_data` → Task 3 Step 1. ✓
- B.1 overview khoảng giá tổng → Task 4. ✓
- B.2 rename + bỏ pricing/unit_type → Task 5. ✓
- B.3 ripple (schemas/dispatcher/config/RULES/serialize) → Task 4 Step 4 + Task 5 Steps 4–7 (`_serialize` giữ nguyên, compose trong tool — đúng spec). ✓
- Testing (test_mapping, test_mongo_nbx, di trú, verify) → Tasks 1,2,3,6. ✓
- Ngoài phạm vi (articles/apartment_types-runtime/media/catalog/direction-clean) → không có task (đúng). ✓

**Placeholder scan:** Task 3 Step 2 + Task 5 Step 8 yêu cầu "đọc file rồi áp bảng đổi field" — không phải placeholder mà là biến đổi cơ học có bảng ánh xạ tường minh + mẫu `_Coll` cụ thể; giá trị assert giữ nguyên nhờ mẹo `price=vnd/1e9`. Chấp nhận (không thể inline nguyên 3 file test lớn mà không đọc; executor có repo).

**Type consistency:** `_mapping.to_vnd/canon_status/region_to_slug/product_type_matches/hot_sort_key/bedrooms/fold` dùng nhất quán ở `mongo.py` + alias `sales_api`. `_unit_type` trả `tuple[str,str]`. `get_financial_policy` dùng thống nhất ở dispatcher/schemas/test. Tool count 12 (rename, không đổi số). ✓
