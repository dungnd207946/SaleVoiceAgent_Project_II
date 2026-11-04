# SP2 — KB backfill (Mongo `nbx_*` → Postgres KB) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone `migration/kb_backfill/` tool that idempotently backfills `tenant_data.projects` + `tenant_data.units` (tenant `noble`, `status='published'`) from the live Mongo `nbx_projects`/`nbx_units`, so the SP1 `pg_kb` provider serves real data.

**Architecture:** Four small modules — `transform.py` (pure mapping, the tested core), `mongo_source.py` (pymongo read), `pg_sink.py` (asyncpg upsert-project + replace-units-per-project), `__main__.py` (CLI + orchestration + stats). Self-contained: it does NOT import `noble_agent`; it connects to Mongo (source) and Postgres (admin/superuser DSN → RLS bypassed, `tenant_id` written explicitly). Assumes the SP1 schema is already applied.

**Tech Stack:** Python 3.11+, pymongo (read), asyncpg (write), python-dotenv (.env), pytest.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-08-03-sp2-kb-mongo-to-postgres-migration-design.md`.
- Branch: current `feat/share-agent`. NEVER touch `develop`. No new branch/worktree, no push/PR without explicit instruction. Local commits only.
- The tool lives in `migration/kb_backfill/` — OUTSIDE `src/noble_agent` — and MUST NOT import `noble_agent`. It reuses only the SQL contract (the SP1 tables already exist in `tenant_data`).
- Scope is `projects` + `units` ONLY. Do NOT write `zones`/`documents`/`media`.
- tenant = `noble` (CLI `--tenant`, default `noble`); every written row carries `tenant_id` explicitly; `status='published'`; `projects.sale_phase` default `'dang_ban'`.
- Canonical units: `price_vnd` = nbx `price` (tỷ) × 1e9 as int; areas = float m²; enums = the standardized `02a` values (`sale_status` ∈ available|booked|sold; `direction` ∈ dong|tay|nam|bac|dong_bac|dong_nam|tay_bac|tay_nam; `product_type` ∈ the 12 unit types).
- Best-effort mapping: map when possible, NULL/default when not, never hard-fail on an unmapped enum — instead COUNT it in the run stats.
- Idempotent: re-run converges (projects upsert on `(tenant_id, project_code)`; units delete-then-insert per project in one transaction).
- Postgres write DSN is the admin/superuser DSN (RLS bypassed for superuser; write `tenant_id` explicitly). Docker `sp-e-postgres` is available; admin DSN derivable from `docker-compose.pg.yml` (`postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey`).
- Live Mongo: the tool loads the repo `.env` (`MONGODB_URI`/`MONGODB_DATABASE`) itself via python-dotenv; it does NOT read `noble_agent.config`.
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. `from __future__ import annotations`.

**nbx source shape (from the retired `nbx_mongo.py`, recovered at git `fd500e0`):**
- `nbx_projects`: `_id` (UUID), `projectCode`, `name`, `areaRegion`, `location`, `type` (`cao_tang`|`thap_tang`|`hon_hop`), `investor`, `description`, `overview` (embedded object OR double-encoded JSON string; keys used: `scale`, `ownership`), `isHot`/`isFeatured`/`sortHot`/`sortOrder`.
- `nbx_units`: `_id` (UUID), `projectId` (= `str(nbx_projects._id)`), `code`, `unitType` (`{name, group}`; `name` like `"2PN"`/`"STUDIO"`), `area` (thông thủy), `areaBuild` (tim tường), `price` (tỷ), `priceTts` (tỷ), `direction` (free text), `status` (`available`/`ready`/`sold`/`locked`/`hidden`), `image`.

---

## File Structure

- `migration/kb_backfill/__init__.py` — empty package marker.
- `migration/kb_backfill/transform.py` — pure mapping (helpers + `project_row` + `unit_row`). NO I/O.
- `migration/kb_backfill/mongo_source.py` — pymongo reads.
- `migration/kb_backfill/pg_sink.py` — asyncpg upsert/replace.
- `migration/kb_backfill/__main__.py` — CLI + orchestration + stats.
- `migration/kb_backfill/requirements.txt` — `pymongo`, `asyncpg`, `python-dotenv`.
- `migration/kb_backfill/tests/test_transform.py` — pure-function unit tests (offline).
- `migration/kb_backfill/tests/test_mongo_source.py` — fake-db reads.
- `migration/kb_backfill/tests/test_pg_sink_live.py` — live docker-PG integration (guarded/skip).
- `migration/kb_backfill/README.md` — how to run (folded into Task 4).

Run tests with `python -m pytest migration/kb_backfill/tests -v` from the repo root.

---

## Task 1: `transform.py` — pure mapping core + tests

**Files:**
- Create: `migration/kb_backfill/__init__.py`, `migration/kb_backfill/transform.py`, `migration/kb_backfill/tests/__init__.py`, `migration/kb_backfill/tests/test_transform.py`

**Interfaces:**
- Produces (later tasks consume):
  - `unit_row(u: dict, project_code: str, project_type: str, stats: dict) -> dict` — column→value dict for `tenant_data.units` (no `tenant_id`/`status`; the sink adds those). Keys: `unit_code, product_type, bedrooms, direction, area_built_m2, area_wall_m2, price_vnd, price_per_m2_vnd, sale_status, image_url`.
  - `project_row(doc: dict, unit_rows: list[dict]) -> dict` — column→value dict for `tenant_data.projects` (no `tenant_id`/`status`). Keys: `project_code, name, category, region, address, investor, product_scale, ownership_form, overview, sale_phase`.
  - `project_code_of(doc: dict) -> str` — `(doc.get("projectCode") or "").strip().upper()`.
  - `stats` is a `dict[str,int]` the caller passes in; transform increments `direction_unmapped`, `product_type_null`, `sale_status_fallback`.

- [ ] **Step 1: Write the failing tests** `migration/kb_backfill/tests/test_transform.py`:

```python
from kb_backfill import transform as t


def test_price_ty_to_vnd():
    assert t._to_vnd(5.62) == 5_620_000_000
    assert t._to_vnd(None) is None
    assert t._to_vnd("") is None


def test_bedrooms():
    assert t._bedrooms("2PN") == 2
    assert t._bedrooms("STUDIO") == 0
    assert t._bedrooms("") is None


def test_direction_fold():
    st = {}
    assert t._fold_direction("Đông Nam", st) == "dong_nam"
    assert t._fold_direction("tay-bac", st) == "tay_bac"
    assert t._fold_direction("Đông", st) == "dong"
    assert t._fold_direction("xyz", st) is None
    assert st["direction_unmapped"] == 1  # only the junk value counted


def test_sale_status():
    st = {}
    assert t._sale_status("available", st) == "available"
    assert t._sale_status("ready", st) == "available"
    assert t._sale_status("sold", st) == "sold"
    assert t._sale_status("locked", st) == "booked"
    assert t._sale_status("hidden", st) == "available"  # fallback
    assert st["sale_status_fallback"] == 1


def test_product_type():
    st = {}
    assert t._product_type("STUDIO", "cao_tang", st) == "studio"
    assert t._product_type("2PN", "cao_tang", st) == "chung_cu"
    assert t._product_type("", "thap_tang", st) == "biet_thu"
    assert t._product_type("", "hon_hop", st) == "chung_cu"
    assert t._product_type("", "", st) is None
    assert st["product_type_null"] == 1


def test_unit_row_maps_and_derives_price_per_m2():
    st = {}
    u = {"code": "S3.06.08", "unitType": {"name": "2PN", "group": "g"},
         "area": "78.4", "areaBuild": "85.2", "price": 5.62, "priceTts": 5.5,
         "direction": "Đông Nam", "status": "available", "image": "http://x/a.jpg"}
    row = t.unit_row(u, "NPLB", "cao_tang", st)
    assert row["unit_code"] == "S3.06.08"
    assert row["product_type"] == "chung_cu"
    assert row["bedrooms"] == 2
    assert row["direction"] == "dong_nam"
    assert row["area_built_m2"] == 78.4 and row["area_wall_m2"] == 85.2
    assert row["price_vnd"] == 5_620_000_000
    assert row["price_per_m2_vnd"] == round(5_620_000_000 / 78.4)
    assert row["sale_status"] == "available"
    assert row["image_url"] == "http://x/a.jpg"


def test_unit_row_price_per_m2_none_when_area_missing():
    st = {}
    row = t.unit_row({"code": "U1", "unitType": {"name": "1PN"}, "price": 3.0,
                      "area": None, "status": "available"}, "P", "cao_tang", st)
    assert row["price_per_m2_vnd"] is None


def test_project_row_category_derived_from_units():
    doc = {"projectCode": "nplb", "name": "Noble Palace", "areaRegion": "Long Biên",
           "location": "Q. Long Biên", "type": "hon_hop", "investor": "Noble",
           "description": "Đại đô thị", "overview": {"scale": "2400 sp", "ownership": "Lâu dài"}}
    units = [{"product_type": "chung_cu"}, {"product_type": "biet_thu"}, {"product_type": "chung_cu"}, {"product_type": None}]
    row = t.project_row(doc, units)
    assert row["project_code"] == "NPLB"
    assert row["category"] == ["biet_thu", "chung_cu"]  # sorted distinct, None dropped
    assert row["region"] == "Long Biên" and row["address"] == "Q. Long Biên"
    assert row["investor"] == "Noble" and row["product_scale"] == "2400 sp"
    assert row["ownership_form"] == "Lâu dài" and row["overview"] == "Đại đô thị"
    assert row["sale_phase"] == "dang_ban"


def test_project_row_category_fallback_from_type_when_no_units():
    row = t.project_row({"projectCode": "P1", "type": "cao_tang"}, [])
    assert row["category"] == ["chung_cu"]


def test_project_row_overview_double_encoded_string():
    doc = {"projectCode": "P1", "type": "cao_tang",
           "overview": '{"scale": "100 căn", "ownership": "50 năm"}'}
    row = t.project_row(doc, [])
    assert row["product_scale"] == "100 căn" and row["ownership_form"] == "50 năm"


def test_project_code_of_empty():
    assert t.project_code_of({"projectCode": ""}) == ""
    assert t.project_code_of({"projectCode": " nplb "}) == "NPLB"
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError: kb_backfill`). Run from repo root: `python -m pytest migration/kb_backfill/tests/test_transform.py -v`. (If the import can't resolve, add an empty `migration/kb_backfill/__init__.py` and run pytest with `rootdir=migration` or `PYTHONPATH=migration`; the plan's Task 4 adds a `conftest`/`pytest.ini` so `kb_backfill` imports — for Task 1, run `PYTHONPATH=migration python -m pytest migration/kb_backfill/tests/test_transform.py -v`.)

- [ ] **Step 3: Implement** `migration/kb_backfill/transform.py`:

```python
"""Pure Mongo-nbx → Postgres-KB row mapping (no I/O). See the SP2 spec §4."""
from __future__ import annotations

import json
import unicodedata


def _to_vnd(price_ty) -> int | None:
    try:
        return int(round(float(price_ty) * 1e9))
    except (TypeError, ValueError):
        return None


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _bedrooms(unit_type_name: str) -> int | None:
    s = (unit_type_name or "").strip().upper()
    if s.endswith("PN") and s[:-2].strip().isdigit():
        return int(s[:-2].strip())
    if s == "STUDIO":
        return 0
    return None


def _fold(s: str) -> str:
    s = (s or "").replace("đ", "d").replace("Đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


# folded free-text direction -> canonical 8-enum (both token orders covered).
_DIR_MAP = {
    "dong": "dong", "tay": "tay", "nam": "nam", "bac": "bac",
    "dong bac": "dong_bac", "bac dong": "dong_bac",
    "dong nam": "dong_nam", "nam dong": "dong_nam",
    "tay bac": "tay_bac", "bac tay": "tay_bac",
    "tay nam": "tay_nam", "nam tay": "tay_nam",
}


def _fold_direction(raw, stats: dict) -> str | None:
    if not raw:
        return None
    f = _fold(str(raw)).replace("-", " ").replace("_", " ")
    f = " ".join(f.split())
    hit = _DIR_MAP.get(f)
    if hit is None:
        stats["direction_unmapped"] = stats.get("direction_unmapped", 0) + 1
    return hit


_STATUS_MAP = {"available": "available", "ready": "available", "sold": "sold", "locked": "booked"}


def _sale_status(raw, stats: dict) -> str:
    s = (raw or "").strip().lower()
    hit = _STATUS_MAP.get(s)
    if hit is None:
        stats["sale_status_fallback"] = stats.get("sale_status_fallback", 0) + 1
        return "available"
    return hit


# project `type` -> default single product_type when a unit's own type is unknown.
_TYPE_DEFAULT = {"cao_tang": "chung_cu", "thap_tang": "biet_thu", "hon_hop": "chung_cu"}


def _product_type(unit_type_name: str, project_type: str, stats: dict) -> str | None:
    if (unit_type_name or "").strip().upper() == "STUDIO":
        return "studio"
    hit = _TYPE_DEFAULT.get((project_type or "").strip().lower())
    if hit is None:
        stats["product_type_null"] = stats.get("product_type_null", 0) + 1
    return hit


def _category_from_type(project_type: str) -> list[str]:
    t = (project_type or "").strip().lower()
    if t == "hon_hop":
        return ["chung_cu", "biet_thu"]
    d = _TYPE_DEFAULT.get(t)
    return [d] if d else []


def _overview_obj(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def project_code_of(doc: dict) -> str:
    return (doc.get("projectCode") or "").strip().upper()


def unit_row(u: dict, project_code: str, project_type: str, stats: dict) -> dict:
    ut = u.get("unitType") or {}
    area = _to_float(u.get("area"))
    price = _to_vnd(u.get("price"))
    ppm2 = round(price / area) if (price is not None and area) else None
    return {
        "project_code": project_code,
        "unit_code": u.get("code") or "",
        "product_type": _product_type(ut.get("name", ""), project_type, stats),
        "bedrooms": _bedrooms(ut.get("name", "")),
        "direction": _fold_direction(u.get("direction"), stats),
        "area_built_m2": area,
        "area_wall_m2": _to_float(u.get("areaBuild")),
        "price_vnd": price,
        "price_per_m2_vnd": ppm2,
        "sale_status": _sale_status(u.get("status"), stats),
        "image_url": u.get("image") or None,
    }


def project_row(doc: dict, unit_rows: list[dict]) -> dict:
    ov = _overview_obj(doc.get("overview"))
    cats = sorted({r["product_type"] for r in unit_rows if r.get("product_type")})
    if not cats:
        cats = _category_from_type(doc.get("type", ""))
    return {
        "project_code": project_code_of(doc),
        "name": doc.get("name") or "",
        "category": cats,
        "region": doc.get("areaRegion") or None,
        "address": doc.get("location") or None,
        "investor": doc.get("investor") or None,
        "product_scale": ov.get("scale") or None,
        "ownership_form": ov.get("ownership") or None,
        "overview": doc.get("description") or None,
        "sale_phase": "dang_ban",
    }
```

- [ ] **Step 4: Run → PASS.** `PYTHONPATH=migration python -m pytest migration/kb_backfill/tests/test_transform.py -v`. Then `ruff check migration/kb_backfill/transform.py migration/kb_backfill/tests/test_transform.py` (0 issues).

- [ ] **Step 5: Commit.**
```bash
git add migration/kb_backfill/__init__.py migration/kb_backfill/transform.py migration/kb_backfill/tests/
git commit -m "feat(kb-backfill): pure nbx→KB transform (projects+units) + tests"
```

---

## Task 2: `mongo_source.py` — pymongo reads

**Files:**
- Create: `migration/kb_backfill/mongo_source.py`, `migration/kb_backfill/tests/test_mongo_source.py`

**Interfaces:**
- Produces: `read_projects(db) -> list[dict]` (all `nbx_projects` docs whose `projectCode` is non-empty), `read_units(db, project_oid: str) -> list[dict]` (`nbx_units` where `projectId == project_oid`). `db` is a pymongo `Database` (or any object exposing `.nbx_projects.find` / `.nbx_units.find`). Also `connect(uri: str, dbname: str) -> db` (pymongo `MongoClient(uri)[dbname]`).

- [ ] **Step 1: Write the failing test** `tests/test_mongo_source.py` with a fake db:

```python
from types import SimpleNamespace
from kb_backfill import mongo_source as ms


class _Coll:
    def __init__(self, docs): self._docs = docs
    def find(self, query=None):
        query = query or {}
        if "projectId" in query:
            return [d for d in self._docs if d.get("projectId") == query["projectId"]]
        return list(self._docs)


def _db(projects, units):
    return SimpleNamespace(nbx_projects=_Coll(projects), nbx_units=_Coll(units))


def test_read_projects_skips_empty_code():
    db = _db([{"projectCode": "NPLB"}, {"projectCode": ""}, {"projectCode": "  "}, {}], [])
    got = ms.read_projects(db)
    assert [d["projectCode"] for d in got] == ["NPLB"]


def test_read_units_by_project():
    db = _db([], [{"projectId": "a", "code": "U1"}, {"projectId": "b", "code": "U2"}])
    assert [u["code"] for u in ms.read_units(db, "a")] == ["U1"]
```

- [ ] **Step 2: Run → FAIL.** `PYTHONPATH=migration python -m pytest migration/kb_backfill/tests/test_mongo_source.py -v`.

- [ ] **Step 3: Implement** `mongo_source.py`:

```python
"""pymongo reads of the nbx_* mirror (read-only source for the KB backfill)."""
from __future__ import annotations


def connect(uri: str, dbname: str):
    from pymongo import MongoClient  # lazy: keep transform tests import-light
    return MongoClient(uri)[dbname]


def read_projects(db) -> list[dict]:
    return [d for d in db.nbx_projects.find({}) if (d.get("projectCode") or "").strip()]


def read_units(db, project_oid: str) -> list[dict]:
    return list(db.nbx_units.find({"projectId": project_oid}))
```

- [ ] **Step 4: Run → PASS.** Then `ruff check migration/kb_backfill/mongo_source.py migration/kb_backfill/tests/test_mongo_source.py`.

- [ ] **Step 5: Commit.**
```bash
git add migration/kb_backfill/mongo_source.py migration/kb_backfill/tests/test_mongo_source.py
git commit -m "feat(kb-backfill): pymongo nbx_* source reads"
```

---

## Task 3: `pg_sink.py` — asyncpg upsert-project + replace-units (live-tested)

**Files:**
- Create: `migration/kb_backfill/pg_sink.py`, `migration/kb_backfill/tests/test_pg_sink_live.py`

**Interfaces:**
- Consumes: `project_row`/`unit_row` dicts (Task 1).
- Produces: `async connect(dsn: str) -> asyncpg.Connection`; `async upsert_project(conn, tenant: str, row: dict) -> None`; `async replace_units(conn, tenant: str, project_code: str, rows: list[dict]) -> None` (DELETE this project's units then batch-INSERT, in the caller's transaction). Both add `tenant_id=tenant` and `status='published'` themselves.

- [ ] **Step 1: Write the failing LIVE test** `tests/test_pg_sink_live.py` (guarded by `KB_BACKFILL_PG_DSN`, SKIP when unset — mirrors the SP1 live-test guard):

```python
import os
import pytest
import asyncio

DSN = os.environ.get("KB_BACKFILL_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="KB_BACKFILL_PG_DSN not set")


@pytest.mark.asyncio
async def test_upsert_and_replace_units_idempotent():
    from kb_backfill import pg_sink
    conn = await pg_sink.connect(DSN)
    try:
        proj = {"project_code": "SP2T", "name": "SP2 Test", "category": ["chung_cu"],
                "region": "R", "address": "A", "investor": "I", "product_scale": "s",
                "ownership_form": "o", "overview": "ov", "sale_phase": "dang_ban"}
        units = [{"project_code": "SP2T", "unit_code": "U1", "product_type": "chung_cu",
                  "bedrooms": 2, "direction": "dong_nam", "area_built_m2": 70.0,
                  "area_wall_m2": 75.0, "price_vnd": 3_000_000_000,
                  "price_per_m2_vnd": 42_857_143, "sale_status": "available", "image_url": None}]
        async with conn.transaction():
            await pg_sink.upsert_project(conn, "noble", proj)
            await pg_sink.replace_units(conn, "noble", "SP2T", units)
        # re-run (idempotent): counts stay 1/1
        async with conn.transaction():
            await pg_sink.upsert_project(conn, "noble", {**proj, "name": "SP2 Test v2"})
            await pg_sink.replace_units(conn, "noble", "SP2T", units)
        n_proj = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.projects WHERE tenant_id='noble' AND project_code='SP2T'")
        n_unit = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.units WHERE tenant_id='noble' AND project_code='SP2T'")
        name = await conn.fetchval(
            "SELECT name FROM tenant_data.projects WHERE tenant_id='noble' AND project_code='SP2T'")
        assert n_proj == 1 and n_unit == 1 and name == "SP2 Test v2"
    finally:
        await conn.execute("DELETE FROM tenant_data.projects WHERE tenant_id='noble' AND project_code='SP2T'")
        await conn.close()
```

- [ ] **Step 2: Run → FAIL/SKIP.** Without the DSN it SKIPs. To actually run it, derive the docker DSN and export it:
`KB_BACKFILL_PG_DSN='postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey' PYTHONPATH=migration python -m pytest migration/kb_backfill/tests/test_pg_sink_live.py -v` → FAIL (module missing) first.

- [ ] **Step 3: Implement** `pg_sink.py`:

```python
"""asyncpg sink for the KB backfill. Uses the admin/superuser DSN (RLS bypassed);
tenant_id is written explicitly. Units are replaced per-project (delete+insert)
since the units table has no natural unique key."""
from __future__ import annotations

_PROJECT_COLS = ("project_code", "name", "category", "region", "address", "investor",
                 "product_scale", "ownership_form", "overview", "sale_phase")
_UNIT_COLS = ("project_code", "unit_code", "product_type", "bedrooms", "direction",
              "area_built_m2", "area_wall_m2", "price_vnd", "price_per_m2_vnd",
              "sale_status", "image_url")


async def connect(dsn: str):
    import asyncpg
    return await asyncpg.connect(dsn)


async def upsert_project(conn, tenant: str, row: dict) -> None:
    cols = ["tenant_id", "status", *_PROJECT_COLS]
    vals = [tenant, "published", *[row.get(c) for c in _PROJECT_COLS]]
    ph = ", ".join(f"${i+1}" for i in range(len(cols)))
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in ("status", *_PROJECT_COLS) if c != "project_code")
    sql = (
        f"INSERT INTO tenant_data.projects ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT (tenant_id, project_code) DO UPDATE SET {updates}, updated_at=now()"
    )
    await conn.execute(sql, *vals)


async def replace_units(conn, tenant: str, project_code: str, rows: list[dict]) -> None:
    await conn.execute(
        "DELETE FROM tenant_data.units WHERE tenant_id=$1 AND project_code=$2", tenant, project_code)
    if not rows:
        return
    cols = ["tenant_id", "status", *_UNIT_COLS]
    ph = ", ".join(f"${i+1}" for i in range(len(cols)))
    sql = f"INSERT INTO tenant_data.units ({', '.join(cols)}) VALUES ({ph})"
    await conn.executemany(sql, [[tenant, "published", *[r.get(c) for c in _UNIT_COLS]] for r in rows])
```

- [ ] **Step 4: Run → PASS** (with the docker DSN exported). Confirm SKIP when the DSN is unset. `ruff check migration/kb_backfill/pg_sink.py migration/kb_backfill/tests/test_pg_sink_live.py`.

- [ ] **Step 5: Commit.**
```bash
git add migration/kb_backfill/pg_sink.py migration/kb_backfill/tests/test_pg_sink_live.py
git commit -m "feat(kb-backfill): asyncpg sink (upsert project + replace units), live-tested idempotent"
```

---

## Task 4: `__main__.py` — CLI, orchestration, stats + requirements + README

**Files:**
- Create: `migration/kb_backfill/__main__.py`, `migration/kb_backfill/requirements.txt`, `migration/kb_backfill/README.md`, `migration/kb_backfill/conftest.py`
- Test: extend `tests/test_transform.py`? No — add `tests/test_orchestrate.py` (dry-run over a fake source, no PG).

**Interfaces:**
- Consumes: `mongo_source`, `transform`, `pg_sink`.
- Produces: `async run(db, tenant: str, sink_conn=None, dry_run: bool=False) -> dict` (returns the stats dict); `main(argv=None)` (argparse CLI). `run` loops projects, builds unit rows (which feeds `project_row`'s category), and — unless `dry_run` — upserts each project + replaces its units in one per-project transaction on `sink_conn`.

- [ ] **Step 1: Add `conftest.py`** so `kb_backfill` imports without `PYTHONPATH`:
```python
# migration/kb_backfill/conftest.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # migration/ on path
```
(Place at `migration/kb_backfill/conftest.py`; pytest adds its dir's parent — `migration/` — so `import kb_backfill` resolves. After this, tests run with a bare `python -m pytest migration/kb_backfill/tests -v`.)

- [ ] **Step 2: Write the failing orchestration test** `tests/test_orchestrate.py`:

```python
import pytest
from types import SimpleNamespace
from kb_backfill import __main__ as m


class _Coll:
    def __init__(self, docs): self._docs = docs
    def find(self, query=None):
        query = query or {}
        if "projectId" in query:
            return [d for d in self._docs if d.get("projectId") == query["projectId"]]
        return list(self._docs)


@pytest.mark.asyncio
async def test_run_dry_counts_and_skips_empty_code():
    projects = [
        {"_id": "oid1", "projectCode": "NPLB", "name": "N", "type": "cao_tang"},
        {"_id": "oid2", "projectCode": "", "name": "skip", "type": "cao_tang"},
    ]
    units = [{"projectId": "oid1", "code": "U1", "unitType": {"name": "2PN"},
              "price": 3.0, "area": "70", "status": "available", "direction": "Đông"}]
    db = SimpleNamespace(nbx_projects=_Coll(projects), nbx_units=_Coll(units))
    stats = await m.run(db, "noble", sink_conn=None, dry_run=True)
    assert stats["projects_migrated"] == 1
    assert stats["units_migrated"] == 1
    assert stats["projects_skipped_no_code"] == 1
```

- [ ] **Step 3: Run → FAIL.** `python -m pytest migration/kb_backfill/tests/test_orchestrate.py -v`.

- [ ] **Step 4: Implement** `__main__.py`:

```python
"""KB backfill CLI: Mongo nbx_* -> Postgres tenant_data.projects/units (tenant noble).

Usage:
  python -m kb_backfill [--mongo-uri ...] [--mongo-db ...] [--pg-dsn ...]
                        [--tenant noble] [--dry-run] [--limit N]
Defaults read the repo .env (MONGODB_URI / MONGODB_DATABASE / POSTGRES_ADMIN_DSN).
"""
from __future__ import annotations

import argparse
import asyncio
import os

from kb_backfill import mongo_source, pg_sink, transform


async def run(db, tenant: str, sink_conn=None, dry_run: bool = False, limit: int = 0) -> dict:
    stats = {"projects_migrated": 0, "units_migrated": 0, "projects_skipped_no_code": 0,
             "direction_unmapped": 0, "product_type_null": 0, "sale_status_fallback": 0}
    all_docs = list(db.nbx_projects.find({}))
    stats["projects_skipped_no_code"] = sum(1 for d in all_docs if not (d.get("projectCode") or "").strip())
    docs = mongo_source.read_projects(db)
    if limit:
        docs = docs[:limit]
    for doc in docs:
        code = transform.project_code_of(doc)
        ptype = (doc.get("type") or "")
        raw_units = mongo_source.read_units(db, str(doc.get("_id")))
        unit_rows = [transform.unit_row(u, code, ptype, stats) for u in raw_units]
        proj = transform.project_row(doc, unit_rows)
        if not dry_run:
            async with sink_conn.transaction():
                await pg_sink.upsert_project(sink_conn, tenant, proj)
                await pg_sink.replace_units(sink_conn, tenant, code, unit_rows)
        stats["projects_migrated"] += 1
        stats["units_migrated"] += len(unit_rows)
    return stats


def _load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv()  # repo-root .env


async def _amain(args) -> None:
    db = mongo_source.connect(args.mongo_uri, args.mongo_db)
    conn = None
    if not args.dry_run:
        conn = await pg_sink.connect(args.pg_dsn)
    try:
        stats = await run(db, args.tenant, sink_conn=conn, dry_run=args.dry_run, limit=args.limit)
    finally:
        if conn is not None:
            await conn.close()
    print("KB backfill stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def main(argv=None) -> None:
    _load_env()
    p = argparse.ArgumentParser(prog="kb_backfill")
    p.add_argument("--mongo-uri", default=os.environ.get("MONGODB_URI", ""))
    p.add_argument("--mongo-db", default=os.environ.get("MONGODB_DATABASE", "noble_agent"))
    p.add_argument("--pg-dsn", default=os.environ.get("POSTGRES_ADMIN_DSN", ""))
    p.add_argument("--tenant", default="noble")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run → PASS.** `python -m pytest migration/kb_backfill/tests -v` (all files). `ruff check migration/kb_backfill/`.

- [ ] **Step 6: Write `requirements.txt` + `README.md`.**
`requirements.txt`:
```
pymongo>=4
asyncpg>=0.29
python-dotenv>=1
```
`README.md`: one screen — what it does, `pip install -r requirements.txt`, the `python -m kb_backfill --dry-run` and real-run commands (from repo root, `PYTHONPATH=migration` or after `pip install -e` note), the DSN/URI env vars, and the "projects+units only, tenant noble, idempotent" contract.

- [ ] **Step 7: Commit.**
```bash
git add migration/kb_backfill/__main__.py migration/kb_backfill/requirements.txt migration/kb_backfill/README.md migration/kb_backfill/conftest.py migration/kb_backfill/tests/test_orchestrate.py
git commit -m "feat(kb-backfill): CLI + orchestration + stats + requirements/README"
```

---

## Task 5: Live end-to-end run + SP1 provider readback + idempotency

**Files:**
- Modify (only if the live dry-run reveals unmapped `direction` values worth adding): `migration/kb_backfill/transform.py` (`_DIR_MAP`) + a test case.

**Interfaces:** none produced; this is the verification + data-load task.

- [ ] **Step 1: Live dry-run over the real Mongo.** From repo root (venv active): `python -m kb_backfill --dry-run` (uses `.env` `MONGODB_URI`/`MONGODB_DATABASE`). Record the printed stats. Note `direction_unmapped`/`product_type_null` counts.

- [ ] **Step 2: If `direction_unmapped` > 0, inspect the raw values** — one-off: `python -c "from dotenv import load_dotenv; load_dotenv(); import os; from pymongo import MongoClient; db=MongoClient(os.environ['MONGODB_URI'])[os.environ.get('MONGODB_DATABASE','noble_agent')]; print(sorted({(u.get('direction') or '').strip() for u in db.nbx_units.find({})}))"`. For each real value that SHOULD map to a canonical direction but doesn't, add it to `_DIR_MAP` (folded key) + add a `test_direction_fold` case. Re-run the transform tests. Leave genuinely-directionless values as NULL. Commit if changed:
```bash
git add migration/kb_backfill/transform.py migration/kb_backfill/tests/test_transform.py
git commit -m "fix(kb-backfill): extend direction fold map for live nbx values"
```

- [ ] **Step 3: Real run into docker Postgres.** Ensure the SP1 schema is applied (it is, from SP1 Task 1; if unsure, re-run `noble-tenant pg-apply-schema` against the admin DSN — idempotent). Then:
`POSTGRES_ADMIN_DSN='postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey' python -m kb_backfill` (from repo root; `--pg-dsn` also accepts it explicitly). Record stats.

- [ ] **Step 4: Verify counts + provider readback.** Write a throwaway check script (or a one-off python) that:
  - counts rows: `SELECT count(*) FROM tenant_data.projects WHERE tenant_id='noble' AND project_code<>'__ALL__'` and `... units ...` — match the run stats.
  - drives the SP1 provider end-to-end: set `POSTGRES_DSN` to the same DSN, then
    ```python
    import asyncio, os
    from noble_agent.tenant.current import use_tenant
    from noble_agent.data.providers.postgres_kb import PostgresKBProvider
    async def go():
        with use_tenant("noble"):
            p = PostgresKBProvider()
            await p.warm()
            codes = p.cached_codes()
            ov = await p.get_overview(codes[0])
            disc = await p.discover_projects(__import__("noble_agent.data.providers.base", fromlist=["DiscoverQuery"]).DiscoverQuery(limit=5))
        print(len(codes), ov and ov.name, disc.total)
    asyncio.run(go())
    ```
    Confirm `cached_codes()` is non-empty, `get_overview` returns a real project, `discover_projects.total` > 0. (This proves SP1 reads what SP2 wrote — the end-to-end goal. Note: this check imports `noble_agent`, so run it from a shell with the agent venv + `POSTGRES_DSN`/`POSTGRES_ENABLED=true` — it is a manual verification, NOT part of the `kb_backfill` package.)
- [ ] **Step 5: Idempotency.** Re-run `python -m kb_backfill` a second time; re-count — row counts unchanged.
- [ ] **Step 6: Record results** in the report/ledger: dry-run stats, real-run stats, provider-readback output, idempotency confirmation. No commit needed unless Step 2 changed code.

---

## Self-Review

**Spec coverage:** §2 location/independence/connections → Tasks 1-4 (package outside src, no noble_agent import, pymongo/asyncpg/dotenv, admin DSN). §3 modules → Task 1 (transform), Task 2 (mongo_source), Task 3 (pg_sink), Task 4 (__main__). §4.1/§4.2 field mapping → Task 1 `project_row`/`unit_row` (every listed column, category-from-units, price_per_m2 derive, NULLs). §5 idempotency/RLS → Task 3 (upsert + replace-units) + admin-DSN bypass. §6 testing → Task 1 (transform units), Task 3 (live sink), Task 4 (dry-run orchestration), Task 5 (live dry-run + real run + provider readback + idempotency). §7 deps → Task 4 requirements.txt. §8 open items: #1 direction fold refinement → Task 5 Step 2; #2 overview text (default NO) → honored in Task 1 (`overview`=`description` only); #3 product_type coarse → Task 1 mapper + Task 5 can refine; #4 pymongo import → Task 4 requirements + lazy import in Task 2.

**Placeholder scan:** no TBD/TODO; every code step has real code; every test has real assertions.

**Type consistency:** `project_row`/`unit_row`/`project_code_of` signatures identical across Task 1 (def), Task 3 (sink consumes the dicts by `_PROJECT_COLS`/`_UNIT_COLS` keys — which match the dict keys emitted in Task 1: project keys `project_code,name,category,region,address,investor,product_scale,ownership_form,overview,sale_phase`; unit keys `project_code,unit_code,product_type,bedrooms,direction,area_built_m2,area_wall_m2,price_vnd,price_per_m2_vnd,sale_status,image_url`), and Task 4 (`run` calls them). `stats` keys (`direction_unmapped`/`product_type_null`/`sale_status_fallback`) written in Task 1 and initialized in Task 4's `run`. `pg_sink.connect`/`upsert_project`/`replace_units` signatures match between Task 3 (def) and Task 4 (call). Note: `_PROJECT_COLS` in Task 3 excludes `overview`? — CHECK: it includes `overview` ✓ (listed). The sink adds `tenant_id`+`status`; transform dicts do NOT carry those ✓ (matches Task 1 Interfaces).
