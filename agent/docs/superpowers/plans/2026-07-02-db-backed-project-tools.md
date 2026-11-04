# DB-Backed Project Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `list_projects` / `get_project_overview` / `match_projects` read live MongoDB (`project_du_an`), align the app's canonical project code to the DB `ma_du_an` (which the RAG corpus already uses), and source the `noble_search` / `send_via_app` project-code enums dynamically from the DB.

**Architecture:** A new `db_project_registry` loads `project_du_an` once at startup into a sync-readable cache (with a bundled fallback). `catalog.py` gets a surgical 4-code rename so `normalize()` returns DB codes (fixing a latent RAG-filter miss for 4 projects). `structured_data.py` is replaced with the async Mongo layer ported from `feat/seperate-service`; `projects_info.py` and `project_financial.py` become async Mongo callers. Tool schemas inject their project enums from the registry at build time.

**Tech Stack:** Python 3.11+, `motor` (async Mongo, already wired via `storage.mongo_client`), pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- **Branch:** work only on `feat/connect-db`. Local commits fine; NO push/merge/PR, do not touch `develop`.
- **Canonical project code = DB `ma_du_an`, verbatim case** (`Alumi` stays mixed-case, matching Qdrant `project_id`). Never `.upper()` a code that will be used as a RAG filter or echoed to the caller.
- **Ruff:** line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make format` before each commit.
- **Escalate sentinel:** the exact string `"Thông tin đã được chuyển đến chuyên viên tư vấn"` (`structured_data.ESCALATE_SIGNAL`).
- **Mongo may be down at import/startup** — sync accessors must never do I/O and must fall back to a bundled code list; `warm()` must swallow all exceptions.
- **Tooling caveat:** the `rtk` shell hook can corrupt `grep`/`diff`/`git show` text output. Verify file contents with the Read tool, and if a Bash command's output looks mangled, re-run it as `rtk proxy <cmd>`.

Mapping reference (DB field → tool field), used in several tasks:

| project_du_an field | tool field |
|---|---|
| `ma_du_an` | `code` (verbatim) |
| `ten_thuong_mai` | `name` |
| `khu_vuc` | `region` |
| `vi_tri` | `district` |
| `loai_hinh_sp` | `type` |
| `tong_so_can` | `units` |
| `don_vi_van_hanh` | `management` |
| `chu_dau_tu` | `investor` |
| `hinh_thuc_so_huu` | `ownership` |
| `tien_do_ban_giao` | `handover` |
| `dien_tich_dat_m2` | `land_area_m2` (raw string) |
| `tong_muc_dau_tu_vnd` | `total_investment_vnd` (int|None) |

15 DB codes (as of 2026-07-02): `NCLB, NCTH, NCR, NPLB, NPTH, NTTL, SLC, SSC, SGR, SGI, SRP, SCHN, SBR, ALLUVIA, Alumi`.

---

### Task 1: `db_project_registry` — the dynamic DB code source

**Files:**
- Create: `src/noble_agent/data/db_project_registry.py`
- Test: `tests/unit/unified/test_db_project_registry.py`

**Interfaces:**
- Produces:
  - `async warm() -> None` — load `project_du_an` into the module cache; swallows all errors.
  - `cached_codes() -> list[str]` — sync, no I/O; warmed codes or `_FALLBACK_CODES`.
  - `code_to_name() -> dict[str, str]` — sync, no I/O; warmed `{code: name}` or fallback.
  - `set_cache_for_tests(rows: dict[str, dict] | None) -> None` — test hook.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_db_project_registry.py
"""db_project_registry — sync cache accessors + fallback (no live Mongo)."""

from __future__ import annotations

from noble_agent.data import db_project_registry as reg


def test_cached_codes_fallback_when_cold():
    reg.set_cache_for_tests(None)
    codes = reg.cached_codes()
    assert len(codes) == 15
    assert "ALLUVIA" in codes and "Alumi" in codes and "SLC" in codes and "NCR" in codes
    # Fallback must NOT carry the stale app codes.
    for stale in ("ASM", "SSLC", "NCRS", "ALUMI"):
        assert stale not in codes


def test_cached_codes_and_names_use_warm_cache():
    reg.set_cache_for_tests(
        {"XYZ": {"code": "XYZ", "name": "Test Project", "region": "HN", "type": "Cao tầng"}}
    )
    assert reg.cached_codes() == ["XYZ"]
    assert reg.code_to_name() == {"XYZ": "Test Project"}
    reg.set_cache_for_tests(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/unified/test_db_project_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: noble_agent.data.db_project_registry`.

- [ ] **Step 3: Write the module**

```python
# src/noble_agent/data/db_project_registry.py
"""DB-sourced project registry — the dynamic project-code dict.

Loads the canonical roster from MongoDB ``project_du_an`` once at startup into an
in-memory cache keyed by ``ma_du_an`` (VERBATIM case, matching the Qdrant
``project_id`` payload). The sync accessors (:func:`cached_codes`,
:func:`code_to_name`) never touch Mongo — they return the warmed cache or a
bundled fallback — so tool-schema construction can call them synchronously.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("noble_agent.data.db_project_registry")

# 15 ma_du_an codes as of 2026-07-02 — the fallback so schema enums are never
# empty when Mongo is unreachable at startup. Case verbatim (note: "Alumi").
_FALLBACK_CODES: tuple[str, ...] = (
    "NCLB", "NCTH", "NCR", "NPLB", "NPTH", "NTTL", "SLC", "SSC",
    "SGR", "SGI", "SRP", "SCHN", "SBR", "ALLUVIA", "Alumi",
)
_FALLBACK_NAMES: dict[str, str] = {
    "NCLB": "Noble Crystal Long Biên",
    "NCTH": "Noble Crystal Tây Hồ",
    "NCR": "Noble Crystal Riverside",
    "NPLB": "Noble Palace Long Biên",
    "NPTH": "Noble Palace Tây Hồ",
    "NTTL": "Noble Palace Tây Thăng Long",
    "SLC": "Sunshine Legend City",
    "SSC": "Sunshine Sky City",
    "SGR": "Sunshine Golden River",
    "SGI": "Sunshine Green Iconic",
    "SRP": "Sunshine River Park",
    "SCHN": "Sunshine City Hà Nội",
    "SBR": "Sunshine Bay Retreat",
    "ALLUVIA": "Alluvia Sunshine Marina",
    "Alumi": "Alumi",
}

_cache: dict[str, dict] = {}


async def warm() -> None:
    """Load ``project_du_an`` into the cache. Call once at startup. A failure
    (Mongo down/missing) leaves the cache empty → sync accessors use fallback."""
    from noble_agent.storage.mongo_client import get_db

    try:
        db = await get_db()
        if db is None:
            logger.info("db_project_registry: Mongo unavailable; using fallback codes")
            return
        projection = {"ma_du_an": 1, "ten_thuong_mai": 1, "khu_vuc": 1, "loai_hinh_sp": 1}
        new: dict[str, dict] = {}
        async for d in db.project_du_an.find({}, projection):
            code = (d.get("ma_du_an") or "").strip()
            if not code:
                continue
            new[code] = {
                "code": code,
                "name": (d.get("ten_thuong_mai") or "").strip(),
                "region": (d.get("khu_vuc") or "").strip(),
                "type": (d.get("loai_hinh_sp") or "").strip(),
            }
        if new:
            _cache.clear()
            _cache.update(new)
            logger.info("db_project_registry: warmed %d projects", len(_cache))
    except Exception as exc:  # noqa: BLE001 — boot must survive
        logger.warning("db_project_registry.warm failed (using fallback): %s", exc)


def cached_codes() -> list[str]:
    """Project codes from the warmed cache, or the bundled fallback. Sync, no I/O."""
    if _cache:
        return list(_cache.keys())
    return list(_FALLBACK_CODES)


def code_to_name() -> dict[str, str]:
    """``{code: commercial name}`` from cache, or fallback. Sync, no I/O."""
    if _cache:
        return {c: v.get("name", "") for c, v in _cache.items()}
    return dict(_FALLBACK_NAMES)


def set_cache_for_tests(rows: dict[str, dict] | None) -> None:
    """Test hook: inject/clear the cache without hitting Mongo."""
    _cache.clear()
    if rows:
        _cache.update(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/unified/test_db_project_registry.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
make format
git add src/noble_agent/data/db_project_registry.py tests/unit/unified/test_db_project_registry.py
git commit -m "feat(data): db_project_registry — dynamic project codes from project_du_an"
```

---

### Task 2: `catalog.py` — align 4 codes to DB, case-insensitive lookup

**Files:**
- Modify: `src/noble_agent/agent/catalog.py`
- Test: `tests/unit/test_catalog_db_codes.py`

**Interfaces:**
- Produces (unchanged signatures, new behavior): `catalog.normalize(raw) -> str` now returns DB codes (`NCR`/`SLC`/`ALLUVIA`/`Alumi`); `catalog.by_code(code) -> Project | None` is case-insensitive.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_db_codes.py
"""catalog.normalize returns DB ma_du_an codes; by_code is case-insensitive."""

from __future__ import annotations

import pytest

from noble_agent.agent import catalog


@pytest.mark.parametrize(
    "raw,code",
    [
        ("NCR", "NCR"), ("ncr", "NCR"), ("NCRS", "NCR"), ("crystal riverside", "NCR"),
        ("SLC", "SLC"), ("SSLC", "SLC"), ("legend city", "SLC"),
        ("ALLUVIA", "ALLUVIA"), ("alluvia sunshine marina", "ALLUVIA"), ("asm", "ALLUVIA"),
        ("Alumi", "Alumi"), ("ALUMI", "Alumi"), ("alumi", "Alumi"), ("alluvia city", "Alumi"),
        ("NCLB", "NCLB"), ("noble crystal long biên", "NCLB"),
    ],
)
def test_normalize_returns_db_codes(raw, code):
    assert catalog.normalize(raw) == code


def test_ambiguous_tokens_still_empty():
    assert catalog.normalize("crystal") == ""
    assert catalog.normalize("sunshine") == ""
    assert catalog.normalize("") == ""


def test_by_code_case_insensitive():
    assert catalog.by_code("Alumi").code == "Alumi"
    assert catalog.by_code("alumi").code == "Alumi"
    assert catalog.by_code("ALUMI").code == "Alumi"
    assert catalog.by_code("NCR").code == "NCR"


def test_valid_codes_have_no_stale_app_codes():
    for stale in ("ASM", "SSLC", "NCRS", "ALUMI"):
        assert stale not in catalog.VALID_CODES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_catalog_db_codes.py -q`
Expected: FAIL (e.g. `normalize('ALLUVIA')` returns `''`; `by_code('Alumi')` is None).

- [ ] **Step 3: Rename the 4 codes**

Edit `src/noble_agent/agent/catalog.py`. Change ONLY these 4 `code` string literals in `_REGISTRY` (leave every alias tuple untouched):

- Line 89: `"SSLC",` → `"SLC",`
- Line 102: `"NCRS",` → `"NCR",`
- Line 194: `"ASM",` → `"ALLUVIA",`
- Line 204: `"ALUMI",` → `"Alumi",`

- [ ] **Step 4: Add a case-insensitive lookup and use it**

In `src/noble_agent/agent/catalog.py`, after the line:

```python
_BY_ID: dict[int, Project] = {p.id: p for p in _REGISTRY}
```

add:

```python
# Case-insensitive code lookup — codes are compared upper() but the stored
# Project.code keeps DB casing (e.g. "Alumi"), so we map UPPER -> Project.
_BY_CODE_CI: dict[str, Project] = {p.code.upper(): p for p in _REGISTRY}
```

In `normalize()`, replace this block:

```python
        up = s.upper()
        if up in VALID_CODES:
            return up
        low = s.lower()
```

with:

```python
        proj = _BY_CODE_CI.get(s.upper())
        if proj:
            return proj.code
        low = s.lower()
```

In `by_code()`, replace:

```python
    return _BY_CODE.get(code.upper())
```

with:

```python
    return _BY_CODE_CI.get(code.upper())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_catalog_db_codes.py -q`
Expected: PASS.

- [ ] **Step 6: Guard against regressions in existing catalog tests**

Run: `.venv/bin/pytest tests/ -k catalog -q`
Expected: PASS. If an existing test asserts an old app code (`ASM`/`SSLC`/`NCRS`/`ALUMI`), update that expectation to the DB code and note it in the commit body.

- [ ] **Step 7: Commit**

```bash
make format
git add src/noble_agent/agent/catalog.py tests/unit/test_catalog_db_codes.py
git commit -m "fix(catalog): align 4 project codes to DB ma_du_an + case-insensitive by_code

NCRS->NCR, SSLC->SLC, ASM->ALLUVIA, ALUMI->Alumi so normalize() returns the
codes the Qdrant corpus is keyed on, fixing a silent 0-hit RAG filter for those
4 projects. Alias engine untouched."
```

---

### Task 3: Port the async Mongo `structured_data` + async `project_financial`

**Files:**
- Overwrite: `src/noble_agent/data/structured_data.py` (port from `feat/seperate-service`, then adapt)
- Overwrite: `src/noble_agent/agent/tools/project_financial.py` (port async version verbatim)
- Test: `tests/unit/unified/test_project_financial_mongo.py` (port from `feat/seperate-service`)

**Interfaces:**
- Consumes: `catalog.normalize` (Task 2), `storage.mongo_client.get_db` + `set_db_for_tests` (already present).
- Produces: `structured_data.ESCALATE_SIGNAL: str`; async `get_project_pricing/get_payment_plans/get_loan_policies/get_promotions/get_project_fees/search_units`; async `get_project_overview_data/list_projects_data`; helpers `_resolve_du_an_id`, `_fetch_units`, `_fetch_project_doc`, `_build_overview`, `_all_overview_fields_empty`, `_region_matches`.

- [ ] **Step 1: Port the three files from `feat/seperate-service`**

```bash
git show feat/seperate-service:src/noble_agent/data/structured_data.py > src/noble_agent/data/structured_data.py
git show feat/seperate-service:src/noble_agent/agent/tools/project_financial.py > src/noble_agent/agent/tools/project_financial.py
git show feat/seperate-service:tests/unit/unified/test_project_financial_mongo.py > tests/unit/unified/test_project_financial_mongo.py
```

Verify each landed with the Read tool (do NOT trust `git show`/`diff` under the rtk hook).

- [ ] **Step 2: Adapt `structured_data.py` to use `catalog` instead of the removed `project_registry` + drop `_CODE_ALIASES`**

In `src/noble_agent/data/structured_data.py`:

Replace the import line:

```python
from noble_agent.data.project_registry import normalize_project
```

with:

```python
from noble_agent.agent import catalog
```

Delete the entire `_CODE_ALIASES` block (the `dict[str, str]` mapping `NCRS/SSLC/ASM`).

In `_resolve_du_an_id`, replace:

```python
    mongo_code = _CODE_ALIASES.get(code, code)
```

with:

```python
    mongo_code = catalog.normalize(code) or code
```

In `_fetch_project_doc`, replace:

```python
    mongo_code = _CODE_ALIASES.get(c, c)
```

with:

```python
    mongo_code = catalog.normalize(c) or c
```

In `get_project_overview_data`, replace:

```python
    code = normalize_project(code_or_name) or (code_or_name or "").strip().upper()
```

with:

```python
    code = catalog.normalize(code_or_name) or (code_or_name or "").strip()
```

- [ ] **Step 3: Run the ported financial test to verify it passes**

Run: `.venv/bin/pytest tests/unit/unified/test_project_financial_mongo.py -q`
Expected: PASS (11 passed). The alias test (`_resolve_du_an_id(db, "NCRS") == str(_NCR_ID)`) passes because `catalog.normalize("NCRS")` → `"NCR"`.
If it fails on an import of `_CODE_ALIASES` or `normalize_project`, grep the test (via `rtk proxy grep`) and update it to call `catalog.normalize` — but per prior inspection it imports neither.

- [ ] **Step 4: Confirm `project_financial.py` is now the async version**

Read `src/noble_agent/agent/tools/project_financial.py` and confirm it uses `await _sd.get_project_pricing(...)` and `return _sd.ESCALATE_SIGNAL` on `None`/empty. (This replaces the sync mock caller that shipped on this branch.)

- [ ] **Step 5: Run the full unit suite for import health**

Run: `.venv/bin/pytest tests/unit -q`
Expected: PASS or only failures owned by later tasks (`projects_info`, `schemas`, `project_registry` removal). No import errors from `structured_data`.

- [ ] **Step 6: Commit**

```bash
make format
git add src/noble_agent/data/structured_data.py src/noble_agent/agent/tools/project_financial.py tests/unit/unified/test_project_financial_mongo.py
git commit -m "feat(data): structured_data + project_financial → async MongoDB (project_du_an/project_can_ho)

Port the Mongo layer from feat/seperate-service; resolve codes via catalog
(now DB-aligned) instead of the static project_registry; drop _CODE_ALIASES."
```

---

### Task 4: `projects_info.py` — 3 tools read MongoDB

**Files:**
- Overwrite: `src/noble_agent/agent/tools/projects_info.py`
- Test: `tests/unit/unified/test_projects_info_mongo.py` (port from `feat/seperate-service`)

**Interfaces:**
- Consumes: `structured_data.list_projects_data`, `structured_data.get_project_overview_data`, `structured_data.ESCALATE_SIGNAL` (Task 3).
- Produces: async `list_projects(args)`, `get_project_overview(args)`, `match_projects(args)` returning JSON string or the sentinel.

- [ ] **Step 1: Port the test from `feat/seperate-service`**

```bash
git show feat/seperate-service:tests/unit/unified/test_projects_info_mongo.py > tests/unit/unified/test_projects_info_mongo.py
```

Verify with the Read tool. This test seeds a fake `project_du_an` with codes `NTTL`/`NCR`/`SGI`, asserts field mapping, `code` echoed verbatim, dropped registry-only keys absent, empty→`""`, all-empty/unknown/empty-db/db-down→`ESCALATE_SIGNAL`, and the `NCRS`→`NCR` alias echo.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/unified/test_projects_info_mongo.py -q`
Expected: FAIL — the current `projects_info` reads the static `project_registry`, so field mapping / sentinel assertions fail.

- [ ] **Step 3: Rewrite `projects_info.py`**

```python
# src/noble_agent/agent/tools/projects_info.py
"""Project info tools: list_projects, get_project_overview, match_projects.

Read live ``project_du_an`` (one collection, no join) via ``data.structured_data``.
A data fn returning ``None`` (unknown project / all-empty fields / empty collection
/ Mongo down) surfaces :data:`~noble_agent.data.structured_data.ESCALATE_SIGNAL`
so Luna hands off to a human advisor. ``code`` is the raw ``ma_du_an`` (verbatim
case) so it matches the Qdrant ``project_id`` used by ``noble_search``.
"""

from __future__ import annotations

import json

from noble_agent.data import structured_data as sd


async def list_projects(args: dict) -> str:
    result = await sd.list_projects_data(region=args.get("region", "") or "")
    if result is None:
        return sd.ESCALATE_SIGNAL
    return json.dumps(result, ensure_ascii=False)


async def get_project_overview(args: dict) -> str:
    code_or_name = (args.get("project_code", "") or "") or (args.get("project_name", "") or "")
    result = await sd.get_project_overview_data(code_or_name)
    if result is None:
        return sd.ESCALATE_SIGNAL
    return json.dumps(result, ensure_ascii=False)


async def match_projects(args: dict) -> str:
    listing = await sd.list_projects_data(region=args.get("region", "") or "")
    if listing is None:
        return sd.ESCALATE_SIGNAL
    projects = [
        {
            "code": p.get("code", ""),
            "name": p.get("name", ""),
            "region": p.get("region", ""),
            "type": p.get("type", ""),
        }
        for p in listing.get("projects", [])
    ]
    return json.dumps(
        {
            "projects": projects,
            "customer_criteria": {
                "purpose": args.get("purpose", ""),
                "budget_max": args.get("budget_max"),
                "region": args.get("region", ""),
                "bedrooms": args.get("bedrooms"),
            },
            "instruction": (
                "Dựa trên criteria của khách, chọn dự án phù hợp nhất từ danh sách. "
                "Dùng get_project_financial để xác nhận giá nếu cần."
            ),
        },
        ensure_ascii=False,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/unit/unified/test_projects_info_mongo.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make format
git add src/noble_agent/agent/tools/projects_info.py tests/unit/unified/test_projects_info_mongo.py
git commit -m "feat(tools): list/overview/match_projects → MongoDB project_du_an

Empty field -> ''; all-empty/unknown/empty-db/db-down -> ESCALATE_SIGNAL; code
echoed as raw ma_du_an (verbatim case) to match the RAG project_id."
```

---

### Task 5: Dynamic project enums in tool schemas

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py`
- Test: `tests/unit/unified/test_schemas_dynamic_enum.py`

**Interfaces:**
- Consumes: `db_project_registry.cached_codes` (Task 1).
- Produces: `schemas_for(names)` returns copies whose `noble_search.project_filter.enum` = `[""] + cached_codes()` and `send_via_app.project_code.items.enum` = `cached_codes()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_schemas_dynamic_enum.py
"""noble_search / send_via_app project enums come from db_project_registry."""

from __future__ import annotations

from noble_agent.agent.tools import schemas
from noble_agent.data import db_project_registry as reg


def _by_name(names):
    return {s["function"]["name"]: s for s in schemas.schemas_for(names)}


def test_enums_from_warm_cache():
    reg.set_cache_for_tests(
        {
            "ALLUVIA": {"code": "ALLUVIA", "name": "A", "region": "", "type": ""},
            "SLC": {"code": "SLC", "name": "S", "region": "", "type": ""},
        }
    )
    s = _by_name(["noble_search", "send_via_app"])
    ns = s["noble_search"]["function"]["parameters"]["properties"]["project_filter"]["enum"]
    sva = s["send_via_app"]["function"]["parameters"]["properties"]["project_code"]["items"]["enum"]
    assert ns == ["", "ALLUVIA", "SLC"]
    assert sva == ["ALLUVIA", "SLC"]
    reg.set_cache_for_tests(None)


def test_enum_fallback_when_cold_has_db_codes_no_stale():
    reg.set_cache_for_tests(None)
    s = _by_name(["noble_search"])
    enum = s["noble_search"]["function"]["parameters"]["properties"]["project_filter"]["enum"]
    assert enum[0] == "" and len(enum) == 16
    assert "ALLUVIA" in enum and "Alumi" in enum
    for stale in ("ASM", "SSLC", "NCRS", "ALUMI"):
        assert stale not in enum


def test_schemas_for_does_not_mutate_base():
    reg.set_cache_for_tests({"ONLY": {"code": "ONLY", "name": "", "region": "", "type": ""}})
    _by_name(["noble_search"])
    reg.set_cache_for_tests(None)
    # A second call with a cold cache must fall back cleanly, proving the first
    # call did not bake "ONLY" into the shared SCHEMAS literal.
    enum = _by_name(["noble_search"])["noble_search"]["function"]["parameters"]["properties"]["project_filter"]["enum"]
    assert "ONLY" not in enum
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/unified/test_schemas_dynamic_enum.py -q`
Expected: FAIL — the enums are still the hardcoded app-code arrays.

- [ ] **Step 3: Remove the two hardcoded enum arrays**

In `src/noble_agent/agent/tools/schemas.py`:

Delete the `noble_search.project_filter` enum (the `"enum": [ "", "NCLB", ... "ALUMI" ]` block, ~lines 88-105) so the property is just:

```python
                    "project_filter": {
                        "type": "string",
                        "description": "Mã dự án để lọc (để trống nếu tìm tất cả).",
                    },
```

Delete the `send_via_app.project_code.items` enum (~lines 391-407) so `items` is just:

```python
                        "items": {
                            "type": "string",
                        },
```

- [ ] **Step 4: Inject enums in `schemas_for`**

At the top of `src/noble_agent/agent/tools/schemas.py`, add after `from __future__ import annotations`:

```python
import copy
```

Replace the whole `schemas_for` function at the end of the file with:

```python
def _with_project_enum(schema: dict, name: str) -> dict:
    """Return a copy of ``schema`` with its project-code enum filled from the
    DB-sourced registry (sync, cache-or-fallback). Never mutates the shared
    SCHEMAS literal."""
    from noble_agent.data import db_project_registry

    codes = db_project_registry.cached_codes()
    s = copy.deepcopy(schema)
    props = s["function"]["parameters"]["properties"]
    if name == "noble_search":
        props["project_filter"]["enum"] = ["", *codes]
    elif name == "send_via_app":
        props["project_code"]["items"]["enum"] = list(codes)
    return s


def schemas_for(names: list[str]) -> list[dict]:
    """Trả về schemas đã filter theo danh sách tên (giữ thứ tự, skip unknown).

    ``noble_search`` / ``send_via_app`` có enum mã dự án được bơm động từ
    ``db_project_registry`` (mã DB, đã warm lúc startup; rơi về fallback nếu chưa)."""
    out: list[dict] = []
    for name in names:
        if name not in SCHEMAS:
            continue
        if name in ("noble_search", "send_via_app"):
            out.append(_with_project_enum(SCHEMAS[name], name))
        else:
            out.append(SCHEMAS[name])
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/unified/test_schemas_dynamic_enum.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
make format
git add src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_schemas_dynamic_enum.py
git commit -m "feat(tools): project enums (noble_search/send_via_app) sourced from db_project_registry"
```

---

### Task 6: Warm the registry at startup (both transports)

**Files:**
- Modify: `src/noble_agent/server/http.py` (`_run_server_async`, ~line 1002-1004)
- Modify: `src/noble_agent/transport/livekit/worker.py` (`_prewarm`, ~line 127-131)

**Interfaces:**
- Consumes: `db_project_registry.warm` (Task 1).

- [ ] **Step 1: Wire the aiortc path**

In `src/noble_agent/server/http.py`, in `_run_server_async`, immediately after:

```python
    await _maybe_reconcile_qdrant()
```

add:

```python
    from noble_agent.data import db_project_registry

    await db_project_registry.warm()
```

- [ ] **Step 2: Wire the LiveKit worker path**

The worker `_prewarm` is synchronous (called as `_asyncio.run(...)` for other steps). In `src/noble_agent/transport/livekit/worker.py`, inside `_prewarm`, immediately before the final `logger.info("prewarm complete ...")` line, add:

```python
    try:
        from noble_agent.data import db_project_registry

        _asyncio.run(db_project_registry.warm())
    except Exception as exc:  # noqa: BLE001 — prewarm must never abort the worker
        logger.warning("prewarm: db_project_registry.warm failed: %s", exc)
```

(Use the module's existing `import asyncio as _asyncio` alias — confirm the alias name via Read before editing; if it is imported as `asyncio`, use that.)

- [ ] **Step 3: Verify import health (no live Mongo needed)**

Run: `.venv/bin/python -c "import noble_agent.server.http, noble_agent.transport.livekit.worker; print('import ok')"`
Expected: `import ok` (import must not require Mongo — `warm()` only runs at startup call time).

- [ ] **Step 4: Commit**

```bash
make format
git add src/noble_agent/server/http.py src/noble_agent/transport/livekit/worker.py
git commit -m "feat(startup): warm db_project_registry at boot (aiortc + livekit)"
```

---

### Task 7: Remove the static `project_registry` + consistency/doc updates

**Files:**
- Delete: `src/noble_agent/data/project_registry.py`
- Delete: `tests/unit/test_data_project_registry.py`
- Modify: `src/noble_agent/agent/rag/flat_store.py` (PROJECT_MAP, ~lines 118-128)
- Modify: `src/noble_agent/agent/definitions/RULES.md` (~lines 42-43)
- Modify: `scripts/gen_responses/scenarios.py` (~line 41 comment)
- Modify: `CLAUDE.md` (Change Log + RAG/tool sections)

- [ ] **Step 1: Confirm `project_registry` has no remaining importers**

Run: `rtk proxy grep -rn "project_registry" src/ tests/ scripts/ --include=*.py`
Expected: matches ONLY in `data/project_registry.py` itself and `tests/unit/test_data_project_registry.py`. If any other `src/` module still imports it, STOP — that consumer must be migrated first (re-scope this task). `structured_data` must no longer import it (Task 3).

- [ ] **Step 2: Delete the module + its test**

```bash
git rm src/noble_agent/data/project_registry.py tests/unit/test_data_project_registry.py
```

- [ ] **Step 3: Align `flat_store.py` PROJECT_MAP to DB codes**

In `src/noble_agent/agent/rag/flat_store.py`, change the 4 divergent values (keys unchanged):

- `"noble_sunshine_legend_city": "SSLC",` → `"noble_sunshine_legend_city": "SLC",`
- `"noble_crystal_riverside": "NCRS",` → `"noble_crystal_riverside": "NCR",`
- `"alluvia_sunshine_marina": "ASM",` → `"alluvia_sunshine_marina": "ALLUVIA",`
- `"alumi": "ALUMI",` → `"alumi": "Alumi",`

- [ ] **Step 4: Update the canonical-code list in `RULES.md`**

In `src/noble_agent/agent/definitions/RULES.md` line 42-43, replace the code roster
`NCLB / NCTH / NPLB / NTTL / SSLC / NCRS / NPTH / SSC / SGR / SGI / SRP / SCHN / SBR / ASM / ALUMI`
with
`NCLB / NCTH / NPLB / NTTL / SLC / NCR / NPTH / SSC / SGR / SGI / SRP / SCHN / SBR / ALLUVIA / Alumi`.

- [ ] **Step 5: Fix the stale comment in the response-gen script**

In `scripts/gen_responses/scenarios.py` (~line 41), change the comment
`# --- Project Overview outputs (from project_registry.py) ---` to
`# --- Project Overview outputs (from MongoDB project_du_an via structured_data) ---`.
(Comment only — do not change scenario data unless a test breaks.)

- [ ] **Step 6: Run the full unit suite + lint**

Run: `.venv/bin/pytest tests/unit -q && make lint`
Expected: PASS. If a leftover test imports `data.project_registry`, delete/repoint it and note it in the commit.

- [ ] **Step 7: Update `CLAUDE.md`**

Add a Change Log row (top of the table) dated `2026-07-02`:

> **list_projects/get_project_overview/match_projects → MongoDB (`project_du_an`); canonical project code aligned to DB `ma_du_an`.** Ported the async Mongo `structured_data` + `project_financial` from `feat/seperate-service`; new `data/db_project_registry.py` loads `project_du_an` at startup (sync `cached_codes`/`code_to_name` + bundled fallback) and feeds the dynamic `noble_search.project_filter` / `send_via_app.project_code` enums. `catalog.py` codes renamed `NCRS→NCR / SSLC→SLC / ASM→ALLUVIA / ALUMI→Alumi` (fixes a silent 0-hit Qdrant filter for those 4 projects; alias engine untouched). Deleted the static `data/project_registry.py`. Branch `feat/connect-db`.

Also update the RAG/tool sections that reference `project_registry`, the 15-code roster (drop the app-only codes), and note the `noble_search` enum is now DB-sourced.

- [ ] **Step 8: Commit**

```bash
make format
git add -A
git commit -m "chore: remove static project_registry; align RULES/flat_store/docs to DB codes"
```

---

### Task 8: Full-suite verification + RAG smoke

- [ ] **Step 1: Unit + lint**

Run: `make test-unit && make lint`
Expected: PASS (no failures, no ruff errors). If output looks truncated/garbled, re-run as `rtk proxy make test-unit`.

- [ ] **Step 2: RAG retrieval smoke for the previously-broken projects**

With Mongo + Qdrant reachable (this branch's `.env` points at the live stack), confirm a project_filter search for a divergent project now returns hits:

```bash
.venv/bin/python - <<'PY'
import asyncio
from noble_agent.agent.rag import noble_kb
async def main():
    for code in ("ALLUVIA", "SLC", "NCR", "Alumi"):
        out = await noble_kb.query_noble_kb(query="tiện ích dự án", project_filter=code)
        print(code, "->", "HIT" if out.strip() else "EMPTY", f"({len(out)} chars)")
asyncio.run(main())
PY
```
Expected: `HIT` for all four (previously `EMPTY` because the filter used app codes). If a call errors on signature, adjust to the real `noble_kb.query_noble_kb` parameters (verify via Read).

- [ ] **Step 3: Estate eval smoke (answer quality, optional but recommended)**

Run: `make eval-estate-smoke`
Expected: completes; spot-check that answers for Alluvia/Legend City/Riverside/Alumi are grounded (not "no data").

- [ ] **Step 4: Final commit if any verification fixups were needed**

```bash
make format
git add -A
git commit -m "test: full-suite + RAG smoke verification for DB-backed project tools"
```

---

## Self-Review

**Spec coverage:**
- §2.1 db_project_registry → Task 1. ✅
- §2.2 structured_data port + project_financial async → Task 3. ✅
- §2.3 projects_info rewrite → Task 4. ✅
- §2.4 catalog surgical + case handling → Task 2. ✅
- §2.5 dynamic enums (both noble_search AND send_via_app) → Task 5. ✅
- §2.6 startup warm (aiortc + livekit) → Task 6. ✅
- §2.7 remove project_registry + docs → Task 7. ✅
- §3 error handling (fallback, escalate) → covered in Tasks 1/3/4 tests. ✅
- §4 testing (unit + eval-estate-smoke) → Tasks 1-5 unit + Task 8 smoke. ✅
- §6 CLAUDE.md update → Task 7 Step 7. ✅

**Placeholder scan:** No TBD/TODO; all code shown; ported files use deterministic `git show`.

**Type consistency:** `cached_codes()`/`code_to_name()`/`warm()`/`set_cache_for_tests()` names match across Tasks 1/5/6. `ESCALATE_SIGNAL` and the async data-fn names match across Tasks 3/4. `_BY_CODE_CI` defined and used within Task 2 only.
