# Recommend Units + Feng Shui Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `match_projects` into `recommend_units` — a consultative tool that recommends specific units across projects, filtered by budget/bedroom/region and ranked with a deterministic, code-computed feng-shui overlay.

**Architecture:** A new pure module `agent/feng_shui.py` computes favorable directions (Bát trạch → nạp âm → địa chi degradation ladder). A new data fn `structured_data.recommend_units_data` scans `project_can_ho` across region-filtered projects, hard-filters by budget/bedroom, soft-ranks feng-shui matches first. The tool executor in `projects_info.py` wires them together with a con-giáp guard (mirrors the booking guard) and shapes the payload.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode=auto`), Motor/Mongo (faked in tests via `mongo_client.set_db_for_tests`).

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-14-recommend-units-feng-shui-design.md` (verbatim source of truth for tables/algorithms).
- Branch: `feat/refactor2`. Local commits only; never touch `develop`.
- Tool count stays **10**. `search_units` and the `Customer` model are NOT modified.
- Feng shui output is **directions only** (no màu/tầng/tử vi); birth hour ignored.
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`.
- Feng-shui is a **soft** signal: never a hard exclusion filter.
- Run `make test-unit` before each commit; it must stay green (modulo the ~65 pre-existing unrelated failures — catalog/mongo/qdrant drift).

---

### Task 1: Pure feng-shui module

**Files:**
- Create: `src/noble_agent/agent/feng_shui.py`
- Test: `tests/unit/unified/test_feng_shui.py`

**Interfaces:**
- Consumes: nothing (pure, stdlib only).
- Produces:
  - `FengShuiResult` (frozen dataclass): `applied: bool`, `method: str|None`, `menh: str|None`, `cung_phi: str|None`, `group: str|None`, `good_directions: frozenset[str]`, `note: str|None`.
  - `compute(*, birth_year=None, gender=None, menh=None, zodiac=None) -> FengShuiResult`.
  - `direction_matches(unit_huong: str, good: frozenset[str]) -> bool`.
  - `normalize_direction(raw: str) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_feng_shui.py`:

```python
"""Pure feng-shui module: Bát trạch / nạp âm / địa chi + direction matching."""
from __future__ import annotations

from noble_agent.agent import feng_shui as fs


# ── Bát trạch (year + gender) ──────────────────────────────────────────────────

def test_bat_trach_1990_male_is_kham_east():
    r = fs.compute(birth_year=1990, gender="M")
    assert r.applied and r.method == "bat_trach"
    assert r.cung_phi == "Khảm"
    assert r.group == "Đông Tứ Mệnh"
    assert r.good_directions == frozenset({"Bắc", "Nam", "Đông", "Đông Nam"})


def test_bat_trach_1990_female_is_can_west():
    r = fs.compute(birth_year=1990, gender="F")
    assert r.cung_phi == "Cấn"
    assert r.group == "Tây Tứ Mệnh"
    assert r.good_directions == frozenset({"Tây", "Tây Bắc", "Tây Nam", "Đông Bắc"})


def test_bat_trach_post_2000_uses_2000_formula():
    # 2001 male: digit_root(01)=1 -> 9-1=8 -> Cấn (Tây Tứ Mệnh)
    r = fs.compute(birth_year=2001, gender="M")
    assert r.cung_phi == "Cấn" and r.group == "Tây Tứ Mệnh"


# ── nạp âm (year only, no gender) ──────────────────────────────────────────────

def test_nap_am_anchors():
    assert fs.compute(birth_year=1984).menh == "Kim"   # Giáp Tý
    assert fs.compute(birth_year=1988).menh == "Mộc"   # Mậu Thìn
    assert fs.compute(birth_year=1990).menh == "Thổ"   # Canh Ngọ


def test_year_without_gender_is_ngu_hanh_not_bat_trach():
    r = fs.compute(birth_year=1990)
    assert r.method == "ngu_hanh" and r.cung_phi is None
    assert r.good_directions == frozenset({"Tây Nam", "Đông Bắc", "Nam"})  # Thổ


# ── menh stated directly ───────────────────────────────────────────────────────

def test_menh_moc_direct():
    r = fs.compute(menh="moc")
    assert r.method == "ngu_hanh" and r.menh == "Mộc"
    assert r.good_directions == frozenset({"Đông", "Bắc"})


# ── zodiac fallback (địa chi) ──────────────────────────────────────────────────

def test_zodiac_ti_is_hoa_estimate_with_note():
    r = fs.compute(zodiac="ti")
    assert r.method == "dia_chi" and r.menh == "Hỏa"
    assert r.good_directions == frozenset({"Nam", "Đông", "Đông Nam"})
    assert r.note and "ước lượng" in r.note


# ── priority: birth_year beats menh/zodiac ─────────────────────────────────────

def test_birth_year_takes_priority():
    r = fs.compute(birth_year=1990, gender="M", menh="hoa", zodiac="ti")
    assert r.method == "bat_trach"


def test_no_signal_not_applied():
    r = fs.compute()
    assert r.applied is False and r.good_directions == frozenset()


# ── direction normalization / matching ─────────────────────────────────────────

def test_direction_matches_accent_case_abbrev():
    good = frozenset({"Đông Nam"})
    assert fs.direction_matches("Đông Nam", good)
    assert fs.direction_matches("đông nam", good)
    assert fs.direction_matches("Đông-Nam", good)
    assert fs.direction_matches("DN", good)


def test_direction_no_match_and_garbage():
    good = frozenset({"Đông Nam"})
    assert fs.direction_matches("Tây Bắc", good) is False
    assert fs.direction_matches("", good) is False
    assert fs.direction_matches("view hồ", good) is False


def test_normalize_direction_handles_d_stroke():
    assert fs.normalize_direction("Đông") == "Đông"
    assert fs.normalize_direction("bắc") == "Bắc"
    assert fs.normalize_direction("xyz") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_feng_shui.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.agent.feng_shui'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/noble_agent/agent/feng_shui.py`:

```python
"""Deterministic feng-shui direction advice (Bát trạch + ngũ hành).

Pure, no I/O. ``compute(...)`` picks the strongest method the supplied customer
data allows (degradation ladder):

  birth_year + gender  -> Bát trạch (cung phi -> Đông/Tây Tứ Mệnh -> 4 hướng)
  birth_year           -> nạp âm ngũ hành -> hướng hợp
  menh (stated)        -> ngũ hành -> hướng hợp
  zodiac (con giáp)    -> địa chi ngũ hành (estimate) -> hướng hợp
  nothing              -> not applied

Output is always DIRECTIONS only (no colour/floor/tử vi). Birth hour is ignored.
See docs/superpowers/specs/2026-07-14-recommend-units-feng-shui-design.md.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class FengShuiResult:
    applied: bool
    method: str | None
    menh: str | None
    cung_phi: str | None
    group: str | None
    good_directions: frozenset[str]
    note: str | None


# 8 canonical directions
BAC, NAM, DONG, TAY = "Bắc", "Nam", "Đông", "Tây"
DB, DN, TB, TN = "Đông Bắc", "Đông Nam", "Tây Bắc", "Tây Nam"

EAST = frozenset({BAC, NAM, DONG, DN})  # Đông Tứ Mệnh
WEST = frozenset({TAY, TB, TN, DB})     # Tây Tứ Mệnh

# Kua (cung phi) -> (cung name, group dirs)
_KUA: dict[int, tuple[str, frozenset[str]]] = {
    1: ("Khảm", EAST), 9: ("Ly", EAST), 3: ("Chấn", EAST), 4: ("Tốn", EAST),
    6: ("Càn", WEST), 2: ("Khôn", WEST), 8: ("Cấn", WEST), 7: ("Đoài", WEST),
}

# Ngũ hành bản mệnh -> hướng hợp (bản mệnh + hành tương sinh nuôi bản mệnh)
_MENH_DIRS: dict[str, frozenset[str]] = {
    "Kim": WEST,
    "Mộc": frozenset({DONG, BAC}),
    "Thủy": frozenset({BAC, TAY, TB}),
    "Hỏa": frozenset({NAM, DONG, DN}),
    "Thổ": frozenset({TN, DB, NAM}),
}

# Con giáp key -> địa chi ngũ hành (fallback estimate)
_CHI_MENH: dict[str, str] = {
    "ty": "Thủy", "suu": "Thổ", "dan": "Mộc", "mao": "Mộc", "thin": "Thổ", "ti": "Hỏa",
    "ngo": "Hỏa", "mui": "Thổ", "than": "Kim", "dau": "Kim", "tuat": "Thổ", "hoi": "Thủy",
}

# Nạp âm ngũ hành over the 60-year cycle, one element per 2-year pair
# (pair 0 = Giáp Tý, years where (year-4) % 60 in {0, 1}).
_NAP_AM_PAIRS: tuple[str, ...] = (
    "Kim", "Hỏa", "Mộc", "Thổ", "Kim", "Hỏa", "Thủy", "Thổ", "Kim", "Mộc",
    "Thủy", "Thổ", "Hỏa", "Mộc", "Thủy", "Kim", "Hỏa", "Mộc", "Thổ", "Kim",
    "Hỏa", "Thủy", "Thổ", "Kim", "Mộc", "Thủy", "Thổ", "Hỏa", "Mộc", "Thủy",
)

# menh param value -> canonical element
_MENH_CANON: dict[str, str] = {
    "kim": "Kim", "moc": "Mộc", "thuy": "Thủy", "hoa": "Hỏa", "tho": "Thổ",
}


def _digit_root(n: int) -> int:
    n = abs(int(n))
    while n > 9:
        n = sum(int(c) for c in str(n))
    return n


def _nap_am(birth_year: int) -> str:
    return _NAP_AM_PAIRS[((birth_year - 4) % 60) // 2]


def _kua(birth_year: int, gender: str) -> int:
    d = _digit_root(birth_year % 100)
    if gender == "M":
        k = (9 - d) if birth_year >= 2000 else (10 - d)
    else:
        k = (d + 6) if birth_year >= 2000 else (d + 5)
    k = _digit_root(k)
    if k == 5:
        return 2 if gender == "M" else 8
    return k or 9


def compute(*, birth_year=None, gender=None, menh=None, zodiac=None) -> FengShuiResult:
    g = gender if gender in ("M", "F") else None
    if birth_year:
        element = _nap_am(int(birth_year))
        if g:
            cung, dirs = _KUA[_kua(int(birth_year), g)]
            grp = "Đông Tứ Mệnh" if dirs is EAST else "Tây Tứ Mệnh"
            return FengShuiResult(True, "bat_trach", element, cung, grp, dirs, None)
        return FengShuiResult(True, "ngu_hanh", element, None, None, _MENH_DIRS[element], None)
    if menh:
        e = _MENH_CANON.get(str(menh).strip().lower())
        if e:
            return FengShuiResult(True, "ngu_hanh", e, None, None, _MENH_DIRS[e], None)
    if zodiac:
        e = _CHI_MENH.get(str(zodiac).strip().lower())
        if e:
            return FengShuiResult(
                True, "dia_chi", e, None, None, _MENH_DIRS[e],
                "ước lượng từ con giáp, nên xác nhận năm sinh",
            )
    return FengShuiResult(False, None, None, None, None, frozenset(), None)


# ── direction normalization ───────────────────────────────────────────────────


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# accent-free, lower-case, đ->d token -> canonical direction
_DIR_ALIASES: dict[str, str] = {
    "bac": BAC, "nam": NAM, "dong": DONG, "tay": TAY,
    "dong bac": DB, "dong nam": DN, "tay bac": TB, "tay nam": TN,
    "db": DB, "dn": DN, "tb": TB, "tn": TN,
}


def normalize_direction(raw: str) -> str | None:
    t = _strip_accents((raw or "").strip().lower()).replace("đ", "d")
    t = t.replace("-", " ").replace("_", " ").replace("/", " ")
    t = " ".join(t.split())
    return _DIR_ALIASES.get(t)


def direction_matches(unit_huong: str, good: frozenset[str]) -> bool:
    d = normalize_direction(unit_huong)
    return d is not None and d in good
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_feng_shui.py -q`
Expected: PASS (all tests). Then `ruff check src/noble_agent/agent/feng_shui.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/feng_shui.py tests/unit/unified/test_feng_shui.py
git commit -m "feat(feng-shui): deterministic Bát trạch / ngũ hành direction module"
```

---

### Task 2: Cross-project unit recommender data fn

**Files:**
- Modify: `src/noble_agent/data/structured_data.py` (add `recommend_units_data`; import `feng_shui`)
- Test: `tests/unit/unified/test_recommend_units.py` (create; data-layer tests only in this task)

**Interfaces:**
- Consumes: `feng_shui.direction_matches` (Task 1); existing `structured_data` helpers `_is_available`, `_to_int`, `_to_float`, `_unit_type_label`, `_region_matches`, `get_db`.
- Produces: `recommend_units_data(*, region="", budget_max=0, bedrooms=0, good_directions=frozenset(), limit=6) -> dict | None`. Returns `None` iff Mongo down or `project_du_an` empty; else `{"units": [ {unit fields...} ]}` (possibly empty list). Each unit dict has keys: `unit_code, type, bedroom_count, clear_area_m2, direction, view, price_vnd, price_per_m2_vnd, project_code, project_name, feng_shui_match, direction_label`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_recommend_units.py`. Note the fake db adds `$in` support (the existing helpers in `test_projects_info_mongo.py` don't have it):

```python
"""recommend_units_data (cross-project scan) + recommend_units tool (guard/note)."""
from __future__ import annotations

import json
import re

import pytest
from bson import ObjectId

from noble_agent.data import structured_data as sd
from noble_agent.storage import mongo_client


def _match(doc: dict, query: dict) -> bool:
    for k, v in query.items():
        dv = doc.get(k)
        if isinstance(v, dict) and "$regex" in v:
            flags = re.I if "i" in v.get("$options", "") else 0
            if dv is None or not re.search(v["$regex"], str(dv), flags):
                return False
        elif isinstance(v, dict) and "$in" in v:
            if dv not in v["$in"]:
                return False
        elif dv != v:
            return False
    return True


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
        self.docs = docs

    async def find_one(self, query, projection=None):
        for d in self.docs:
            if _match(d, query):
                return d
        return None

    def find(self, query):
        return _Cursor([d for d in self.docs if _match(d, query)])


class _DB:
    def __init__(self, collections):
        self._c = collections

    def __getattr__(self, name):
        return self._c[name]

    def __getitem__(self, name):
        return self._c[name]


_HN_ID = ObjectId("141000000000000000000001")
_HY_ID = ObjectId("091000000000000000000001")


def _unit(did, ma, pn, gia, huong, trang_thai="Mở bán"):
    return {
        "du_an_id": str(did), "ma_can": ma, "so_phong_ngu": pn, "gia_vnd": str(gia),
        "gia_m2_vnd": "50000000", "dien_tich_thong_thuy_m2": "75.0",
        "huong": huong, "tam_nhin": "Hồ", "trang_thai": trang_thai,
        "loai_san_pham": "Căn hộ",
    }


def _seed(projects=None, units=None):
    if projects is None:
        projects = [
            {"_id": _HN_ID, "ma_du_an": "NPTTL", "ten_thuong_mai": "Noble Palace TTL", "khu_vuc": "Hà Nội"},
            {"_id": _HY_ID, "ma_du_an": "NCR", "ten_thuong_mai": "Noble Crystal", "khu_vuc": "Hưng Yên"},
        ]
    if units is None:
        units = [
            _unit(_HN_ID, "A-01", 2, 3_000_000_000, "Đông Nam"),
            _unit(_HN_ID, "A-02", 2, 4_500_000_000, "Tây Bắc"),
            _unit(_HN_ID, "A-03", 3, 6_000_000_000, "Nam"),
            _unit(_HY_ID, "B-01", 2, 2_500_000_000, "Bắc"),
            _unit(_HN_ID, "A-04", 2, 3_500_000_000, "Nam", trang_thai="Đã bán hết"),
        ]
    return _DB({"project_du_an": _Coll(projects), "project_can_ho": _Coll(units)})


@pytest.fixture(autouse=True)
def _inject_db():
    mongo_client.set_db_for_tests(_seed())
    yield
    mongo_client.set_db_for_tests(None)


async def test_budget_and_bedroom_hard_filter():
    # <= 3.5 tỷ, 2PN, all regions. A-04 excluded (sold), A-03 excluded (3PN),
    # A-02 excluded (4.5 tỷ). Left: A-01 (3.0), B-01 (2.5).
    out = await sd.recommend_units_data(budget_max=3.5, bedrooms=2)
    codes = {u["unit_code"] for u in out["units"]}
    assert codes == {"A-01", "B-01"}


async def test_region_filter_scopes_projects():
    out = await sd.recommend_units_data(region="Hưng Yên")
    assert {u["unit_code"] for u in out["units"]} == {"B-01"}


async def test_feng_shui_match_ranked_first():
    # good = {Nam, Đông, Đông Nam} (Hỏa). Among 2PN available: A-01(Đông Nam=match),
    # A-02(Tây Bắc=no), B-01(Bắc=no). Match must sort ahead of cheaper non-match.
    good = frozenset({"Nam", "Đông", "Đông Nam"})
    out = await sd.recommend_units_data(bedrooms=2, good_directions=good)
    units = out["units"]
    assert units[0]["unit_code"] == "A-01" and units[0]["feng_shui_match"] is True
    assert units[0]["direction_label"] == "hợp hướng"
    assert all(u["feng_shui_match"] is False for u in units[1:])


async def test_region_miss_returns_empty_not_none():
    out = await sd.recommend_units_data(region="Đà Nẵng")
    assert out == {"units": []}


async def test_no_projects_returns_none():
    mongo_client.set_db_for_tests(_seed(projects=[]))
    assert await sd.recommend_units_data() is None


async def test_db_down_returns_none(monkeypatch):
    async def _no_db():
        return None

    monkeypatch.setattr(sd, "get_db", _no_db)
    assert await sd.recommend_units_data() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_recommend_units.py -q`
Expected: FAIL — `AttributeError: module 'noble_agent.data.structured_data' has no attribute 'recommend_units_data'`.

- [ ] **Step 3: Write minimal implementation**

In `src/noble_agent/data/structured_data.py`, add the import near the top (after the existing `from noble_agent.agent import catalog`):

```python
from noble_agent.agent import feng_shui
```

Then append this function (after `list_projects_data`):

```python
async def recommend_units_data(
    *,
    region: str = "",
    budget_max: float = 0,
    bedrooms: int = 0,
    good_directions: frozenset[str] = frozenset(),
    limit: int = 6,
) -> dict | None:
    """Cross-project unit recommender. ``None`` only when Mongo is down or
    ``project_du_an`` is empty (a true system gap → tool escalates). A region
    that matches no project, or filters that exclude every unit, returns
    ``{"units": []}`` so the tool asks the caller to broaden, not hand off.
    """
    db = await get_db()
    if db is None:
        logger.warning("structured_data: MongoDB unavailable")
        return None
    proj = [d async for d in db.project_du_an.find({})]
    if not proj:
        return None
    if region:
        proj = [d for d in proj if _region_matches(d.get("khu_vuc", ""), region)]
    if not proj:
        return {"units": []}

    id2name = {str(d["_id"]): (d.get("ten_thuong_mai") or "").strip() for d in proj}
    id2code = {str(d["_id"]): (d.get("ma_du_an") or "").strip() for d in proj}
    units = [u async for u in db.project_can_ho.find({"du_an_id": {"$in": list(id2name)}})]

    budget_vnd = budget_max * 1e9 if budget_max else 0
    out: list[dict] = []
    for u in units:
        if not _is_available(u.get("trang_thai", "")):
            continue
        if bedrooms and u.get("so_phong_ngu") != bedrooms:
            continue
        price = _to_int(u.get("gia_vnd"))
        if budget_vnd and (price is None or price > budget_vnd):
            continue
        fs_match = bool(good_directions) and feng_shui.direction_matches(u.get("huong", ""), good_directions)
        did = u.get("du_an_id", "")
        out.append(
            {
                "unit_code": u.get("ma_can") or "",
                "type": _unit_type_label(u),
                "bedroom_count": u.get("so_phong_ngu"),
                "clear_area_m2": _to_float(u.get("dien_tich_thong_thuy_m2")),
                "direction": (u.get("huong") or "").strip(),
                "view": (u.get("tam_nhin") or "").strip(),
                "price_vnd": price,
                "price_per_m2_vnd": _to_int(u.get("gia_m2_vnd")),
                "project_code": id2code.get(did, ""),
                "project_name": id2name.get(did, ""),
                "feng_shui_match": fs_match,
                "direction_label": "hợp hướng" if fs_match else "",
            }
        )

    out.sort(key=lambda x: (not x["feng_shui_match"], x["price_vnd"] if x["price_vnd"] is not None else 10**18))
    return {"units": out[:limit]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_recommend_units.py -q`
Expected: PASS (6 tests). Then `ruff check src/noble_agent/data/structured_data.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/data/structured_data.py tests/unit/unified/test_recommend_units.py
git commit -m "feat(recommend-units): cross-project unit scan with feng-shui soft rank"
```

---

### Task 3: `recommend_units` tool — executor, schema, wiring

**Files:**
- Modify: `src/noble_agent/agent/tools/projects_info.py` (replace `match_projects` with `recommend_units`; import `feng_shui`)
- Modify: `src/noble_agent/agent/tools/schemas.py` (replace the `match_projects` SCHEMAS entry with `recommend_units`)
- Modify: `src/noble_agent/agent/tools/dispatcher.py:123-124` (rename branch, pass `state`/`customer`)
- Modify: `src/noble_agent/agent/definitions/config.json` (`match_projects` → `recommend_units`)
- Test: `tests/unit/unified/test_recommend_units.py` (append executor tests)

**Interfaces:**
- Consumes: `recommend_units_data` (Task 2); `feng_shui.compute` (Task 1); the `State` (has `.scratchpad: dict`) and `Customer` (has `.gender`) models.
- Produces: `projects_info.recommend_units(args: dict, *, state, customer) -> str` (JSON string). Dispatcher calls it as `recommend_units(args, state=self.state, customer=self.customer)`. Guard scratchpad key `"fengshui_guard_attempts"`, cap 2.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/unified/test_recommend_units.py` (reuses the `_inject_db` fixture + seed above):

```python
# ── executor: projects_info.recommend_units ────────────────────────────────────
from types import SimpleNamespace  # noqa: E402

from noble_agent.agent.tools import projects_info as pi  # noqa: E402


def _state():
    return SimpleNamespace(scratchpad={})


def _customer(gender=None):
    return SimpleNamespace(gender=gender)


async def test_no_feng_shui_signal_omits_block_and_ranks_by_price():
    st = _state()
    res = await pi.recommend_units({"bedrooms": 2}, state=st, customer=_customer())
    out = json.loads(res)
    assert "feng_shui" not in out
    prices = [u["price_vnd"] for u in out["units"]]
    assert prices == sorted(prices)
    assert out["counts"]["feng_shui_match"] == 0


async def test_birth_year_with_profile_gender_bat_trach():
    st = _state()
    # 1990 male -> Khảm (Đông Tứ Mệnh): {Bắc, Nam, Đông, Đông Nam}
    res = await pi.recommend_units({"bedrooms": 2, "birth_year": 1990}, state=st, customer=_customer("M"))
    out = json.loads(res)
    assert out["feng_shui"]["method"] == "bat_trach"
    assert out["feng_shui"]["cung_phi"] == "Khảm"
    # A-01 (Đông Nam) matches -> ranked first, labelled
    assert out["units"][0]["unit_code"] == "A-01"
    assert out["counts"]["feng_shui_match"] == 1


async def test_zodiac_only_guard_asks_twice_then_falls_back():
    st = _state()
    for _ in range(2):
        res = await pi.recommend_units({"zodiac": "ti"}, state=st, customer=_customer())
        out = json.loads(res)
        assert out["needs_info"] is True and "năm sinh" in out["message"]
    # 3rd call: guard exhausted -> địa chi estimate applied (Tị -> Hỏa)
    res = await pi.recommend_units({"zodiac": "ti"}, state=st, customer=_customer())
    out = json.loads(res)
    assert "needs_info" not in out
    assert out["feng_shui"]["method"] == "dia_chi" and out["feng_shui"]["menh"] == "Hỏa"


async def test_birth_year_resets_guard_counter():
    st = _state()
    st.scratchpad["fengshui_guard_attempts"] = 1
    await pi.recommend_units({"birth_year": 1990}, state=st, customer=_customer("M"))
    assert st.scratchpad["fengshui_guard_attempts"] == 0


async def test_note_when_feng_shui_applied_but_zero_match():
    st = _state()
    # menh Kim -> {Tây, Tây Bắc, Tây Nam, Đông Bắc}. Restrict to 3PN: only A-03 (Nam) -> no match.
    res = await pi.recommend_units({"bedrooms": 3, "menh": "kim"}, state=st, customer=_customer())
    out = json.loads(res)
    assert out["counts"]["feng_shui_match"] == 0
    assert "note" in out and "hợp hướng" in out["note"]


async def test_empty_result_instructs_broaden_no_note():
    st = _state()
    res = await pi.recommend_units({"region": "Đà Nẵng", "menh": "kim"}, state=st, customer=_customer())
    out = json.loads(res)
    assert out["units"] == []
    assert "nới ngân sách" in out["instruction"]
    assert "note" not in out


async def test_db_down_escalates():
    st = _state()

    async def _no_db():
        return None

    import pytest as _pt  # local to avoid top-level unused when trimmed

    with _pt.MonkeyPatch.context() as mp:
        mp.setattr(sd, "get_db", _no_db)
        res = await pi.recommend_units({"bedrooms": 2}, state=st, customer=_customer())
    assert res == sd.ESCALATE_SIGNAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_recommend_units.py -q`
Expected: FAIL — `AttributeError: module ... 'projects_info' has no attribute 'recommend_units'`.

- [ ] **Step 3: Write minimal implementation**

**(a)** In `src/noble_agent/agent/tools/projects_info.py`: add `from noble_agent.agent import feng_shui` to the imports, then **delete** the `match_projects` function and add:

```python
_FS_GUARD_KEY = "fengshui_guard_attempts"
_FS_GUARD_MAX = 2


def _fs_block(fs: feng_shui.FengShuiResult) -> dict:
    return {
        "applied": True,
        "method": fs.method,
        "menh": fs.menh,
        "cung_phi": fs.cung_phi,
        "group": fs.group,
        "good_directions": sorted(fs.good_directions),
        "note": fs.note,
    }


async def recommend_units(args: dict, *, state, customer) -> str:
    """Recommend specific units across projects (budget/bedroom/region hard
    filters) with an optional, code-computed feng-shui soft ranking + label.
    """
    birth_year = args.get("birth_year")
    gender = args.get("gender") or customer.gender
    menh, zodiac = args.get("menh"), args.get("zodiac")

    # Con-giáp guard: only a zodiac (no year, no menh) → prefer a real birth
    # year before the weaker địa-chi estimate. Ask at most twice (mirrors the
    # booking guard); the 3rd call falls through to compute() using the zodiac.
    if zodiac and not birth_year and not menh:
        attempts = int(state.scratchpad.get(_FS_GUARD_KEY, 0))
        if attempts < _FS_GUARD_MAX:
            state.scratchpad[_FS_GUARD_KEY] = attempts + 1
            return json.dumps(
                {
                    "ok": False,
                    "needs_info": True,
                    "message": (
                        "Khách mới cho con giáp, chưa có năm sinh. Hãy hỏi năm sinh dương lịch để "
                        "tư vấn hướng hợp mệnh chính xác (vd 'anh tuổi Tị là sinh năm nào ạ?'). "
                        "Nếu khách không nhớ, cứ tư vấn theo tiêu chí khác."
                    ),
                },
                ensure_ascii=False,
            )

    fs = None
    if birth_year or menh or zodiac:
        fs = feng_shui.compute(birth_year=birth_year, gender=gender, menh=menh, zodiac=zodiac)
        if birth_year or menh:
            state.scratchpad[_FS_GUARD_KEY] = 0  # real data arrived → reset the ask counter

    good = fs.good_directions if (fs and fs.applied) else frozenset()
    data = await sd.recommend_units_data(
        region=args.get("region", "") or "",
        budget_max=args.get("budget_max") or 0,
        bedrooms=args.get("bedrooms") or 0,
        good_directions=good,
        limit=6,
    )
    if data is None:
        return sd.ESCALATE_SIGNAL

    units = data["units"]
    fs_match = sum(1 for u in units if u.get("feng_shui_match"))
    payload: dict = {
        "units": units,
        "counts": {"total": len(units), "feng_shui_match": fs_match},
        "criteria": {
            "budget_max": args.get("budget_max"),
            "region": args.get("region", ""),
            "bedrooms": args.get("bedrooms"),
            "purpose": args.get("purpose", ""),
        },
        "instruction": "Giới thiệu 2-3 căn nổi bật (dự án + hướng + giá), dẫn dắt khách.",
    }
    if fs and fs.applied:
        payload["feng_shui"] = _fs_block(fs)
    if not units:
        payload["instruction"] = (
            "Không có căn khớp tiêu chí. Hãy gợi ý khách nới ngân sách hoặc đổi khu vực, đừng bịa căn."
        )
    elif fs and fs.applied and fs_match == 0:
        payload["note"] = (
            "Không có căn nào hợp hướng mệnh của khách. Hãy nói rõ điều này, gợi ý vài căn hợp "
            "ngân sách để tham khảo, và mời khách chuyển chuyên viên tư vấn chuyên sâu nếu muốn."
        )
    return json.dumps(payload, ensure_ascii=False)
```

**(b)** In `src/noble_agent/agent/tools/schemas.py`: replace the whole `"match_projects": { ... }` entry with:

```python
    "recommend_units": {
        "type": "function",
        "function": {
            "name": "recommend_units",
            "description": (
                "Gợi ý các CĂN HỘ cụ thể phù hợp khi khách chưa biết chọn gì hoặc muốn được tư "
                "vấn — lọc xuyên nhiều dự án theo ngân sách, khu vực, số phòng ngủ, và ưu tiên căn "
                "HỢP PHONG THỦY nếu khách cho năm sinh / mệnh / tuổi. Khác search_units (tra cứu "
                "căn trong MỘT dự án khách đã nêu rõ). Ví dụ 'tầm 4 tỷ ở Tây Hồ nên xem căn nào', "
                "'anh sinh năm 1990 hợp căn hướng nào', 'anh mệnh Mộc có căn nào hợp'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "budget_max": {"type": "number", "description": "Ngân sách tối đa (tỷ VNĐ). Lọc cứng."},
                    "region": {"type": "string", "description": "Khu vực khách muốn (đúng lời khách)."},
                    "bedrooms": {"type": "integer", "description": "Số phòng ngủ mong muốn."},
                    "purpose": {"type": "string", "description": "Mục đích ở/đầu tư (chỉ để tư vấn, KHÔNG lọc)."},
                    "birth_year": {
                        "type": "integer",
                        "description": "Năm sinh DƯƠNG LỊCH (yyyy, vd 1990). Chỉ truyền khi khách quan tâm phong thủy.",
                    },
                    "gender": {
                        "type": "string",
                        "enum": ["M", "F"],
                        "description": "Giới tính để tính cung phi bát trạch. Bỏ trống → lấy từ hồ sơ.",
                    },
                    "menh": {
                        "type": "string",
                        "enum": ["kim", "moc", "thuy", "hoa", "tho"],
                        "description": "Ngũ hành bản mệnh khi khách khai thẳng ('anh mệnh Mộc').",
                    },
                    "zodiac": {
                        "type": "string",
                        "enum": ["ty", "suu", "dan", "mao", "thin", "ti", "ngo", "mui", "than", "dau", "tuat", "hoi"],
                        "description": "Con giáp khi khách chỉ nói tuổi ('tuổi Tị'). Ưu tiên hỏi năm sinh để chính xác.",
                    },
                },
                "required": [],
            },
        },
    },
```

**(c)** In `src/noble_agent/agent/tools/dispatcher.py`, replace the branch:

```python
        if name == "match_projects":
            return await projects_info.match_projects(args)
```
with:
```python
        if name == "recommend_units":
            return await projects_info.recommend_units(args, state=self.state, customer=self.customer)
```

**(d)** In `src/noble_agent/agent/definitions/config.json`, change `"match_projects"` to `"recommend_units"` in the `"tools"` array.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_recommend_units.py -q`
Expected: PASS (all 13 tests). Then:
- `ruff check src/noble_agent/agent/tools/` → clean.
- `python -c "import json; d=json.load(open('src/noble_agent/agent/definitions/config.json')); assert 'recommend_units' in d['tools'] and 'match_projects' not in d['tools']; assert len(d['tools'])==10"` → no error.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/projects_info.py src/noble_agent/agent/tools/schemas.py \
        src/noble_agent/agent/tools/dispatcher.py src/noble_agent/agent/definitions/config.json \
        tests/unit/unified/test_recommend_units.py
git commit -m "feat(recommend-units): tool executor + schema + wiring (rename match_projects)"
```

---

### Task 4: RULES.md + retire old `match_projects` references

**Files:**
- Modify: `src/noble_agent/agent/definitions/RULES.md` (4 references + new feng-shui rule)
- Modify: `tests/unit/unified/test_tool_schemas.py:32-48` (rename in the expected-tools set)
- Modify: `tests/unit/unified/test_projects_info_mongo.py` (drop the 3 obsolete `match_projects` tests + docstring)
- Modify: `tests/bench/test_tool_latency.py:101` (rename the bench helper — best-effort, opt-in suite)

**Interfaces:**
- Consumes: the `recommend_units` tool name (Task 3).
- Produces: nothing new; brings prompt + existing tests in line with the rename.

- [ ] **Step 1: Update RULES.md**

In `src/noble_agent/agent/definitions/RULES.md`:

Line ~19 — replace `search_units / match_projects / noble_search / booking).` with
`search_units / recommend_units / noble_search / booking).`

Line ~115 — replace `NHIỀU dự án (list_projects / match_projects) — chỉ gửi khi đang tập trung` with
`NHIỀU dự án (list_projects / recommend_units) — chỉ gửi khi đang tập trung`

Line ~127 (tool-catalog row) — replace
`| "Gợi ý dự án phù hợp ngân sách Y / khu Z" | match_projects(...) |`
with
`| "Gợi ý căn phù hợp / nên xem căn nào / hợp tuổi-mệnh-năm sinh của tôi" | recommend_units(budget_max, region, bedrooms, và birth_year/gender/menh/zodiac nếu khách hỏi phong thủy) |`

Line ~135 (escalate signal paragraph) — replace `list_projects hoặc match_projects trả về đúng câu` with
`list_projects hoặc recommend_units trả về đúng câu`

Then add a new numbered rule in the operational-protocol section (after the booking rule 6; renumber only if the file numbers rules — otherwise append as a bullet under the tools section). Use this text:

```markdown
- **Phong thủy (recommend_units):** khi khách hỏi theo tuổi / mệnh / năm sinh
  ("tôi tuổi Tị hợp căn nào", "anh mệnh Mộc", "sinh năm 1990 hợp hướng nào") →
  gọi recommend_units và truyền tín hiệu phong thủy: birth_year (năm DƯƠNG
  LỊCH) + gender nếu biết; hoặc menh (kim/moc/thuy/hoa/tho) khi khách khai
  thẳng; hoặc zodiac (con giáp) khi khách chỉ nói tuổi. Nếu khách chỉ cho con
  giáp mà chưa có năm sinh, tool sẽ nhắc hỏi năm sinh — hãy hỏi (tối đa 2 lần).
  TUYỆT ĐỐI không tự bịa hướng/mệnh; hệ thống tính bằng code. Giờ sinh không
  cần cho phong thủy nhà. Nếu tool báo không có căn hợp hướng, nói thật điều đó,
  gợi ý căn hợp ngân sách, và mời chuyển chuyên viên nếu khách muốn tư vấn sâu.
```

- [ ] **Step 2: Update the tool-schema test**

In `tests/unit/unified/test_tool_schemas.py`, in `test_thirteen_tools_present` replace the line `"match_projects",` with `"recommend_units",`.

- [ ] **Step 3: Drop obsolete match_projects tests**

In `tests/unit/unified/test_projects_info_mongo.py`:
- Update the module docstring line 1: `"""Mongo-backed list_projects / get_project_overview / match_projects.` → `"""Mongo-backed list_projects / get_project_overview.`
- Delete the entire `# ── match_projects ──` section: the three functions `test_match_projects_uses_mongo_candidates`, `test_match_projects_region_filter`, `test_match_projects_empty_db_escalates` (they exercise removed behavior; `recommend_units` is covered by `test_recommend_units.py`).

- [ ] **Step 4: Rename the bench helper (best-effort)**

In `tests/bench/test_tool_latency.py`, rename `test_tool_match_projects` → `test_tool_recommend_units` and update the body so any call to `pi.match_projects(...)` / dispatch name `"match_projects"` becomes `recommend_units` (executor now needs `state=`/`customer=`; pass the bench's existing session objects, or mark `@pytest.mark.skip("recommend_units signature changed")` if the bench harness can't supply them). This suite is opt-in (`-m bench`) and not in `make test-unit`.

- [ ] **Step 5: Run the affected unit tests + full unit suite**

Run:
```bash
pytest tests/unit/unified/test_tool_schemas.py tests/unit/unified/test_projects_info_mongo.py \
       tests/unit/unified/test_recommend_units.py tests/unit/unified/test_feng_shui.py -q
```
Expected: PASS (no `match_projects` references remain in these files). Then:
```bash
grep -rn "match_projects" src/noble_agent tests/unit
```
Expected: no matches under `src/noble_agent` or `tests/unit` (prompt_versions snapshots are historical and out of scope). Then `make test-unit` — green modulo the ~65 pre-existing unrelated failures.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/definitions/RULES.md tests/unit/unified/test_tool_schemas.py \
        tests/unit/unified/test_projects_info_mongo.py tests/bench/test_tool_latency.py
git commit -m "docs(rules)+test: retire match_projects, document recommend_units feng-shui"
```

---

## Post-implementation

- Run `src/noble_agent/SMOKE.md` items that touch the tool catalog / prompt (this change touches both the tool set and RULES.md).
- Update `CLAUDE.md`: the tool-catalog summary (`agent/tools/` row still says 10 tools — names change: `match_projects` → `recommend_units`), the "Adding a new tool" section is unaffected, and append a Change Log row dated 2026-07-14 describing the `recommend_units` + feng-shui redesign. Do this in the same commit as Task 4 or a follow-up.

## Self-review notes

- **Spec coverage:** feng_shui module (Task 1) ↔ spec §Component 1; guard (Task 3) ↔ §Component 2; `recommend_units_data` (Task 2) ↔ §Component 3; executor + omit-empty-block + note (Task 3) ↔ §Component 4; schema (Task 3) ↔ §Component 5; dispatcher/config/RULES (Tasks 3–4) ↔ §Component 6; both test files ↔ §Testing.
- **Type consistency:** `recommend_units(args, *, state, customer)` signature matches the dispatcher call in Task 3; `recommend_units_data(...)` kwargs match between Tasks 2 and 3; `FengShuiResult` fields used by `_fs_block` match Task 1's dataclass; `_FS_GUARD_KEY = "fengshui_guard_attempts"` is identical in executor and tests.
- **Feng-shui-not-applied path:** `feng_shui` key omitted (Task 3 test `test_no_feng_shui_signal_omits_block_and_ranks_by_price`) — matches spec base case.
