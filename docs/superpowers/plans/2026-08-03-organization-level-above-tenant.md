> ⚠ **ĐÃ BỊ THAY THẾ 2026-08-15** bởi
> `odyssey-portal-backend/docs/superpowers/specs/2026-08-15-bo-organization-design.md`.
> Tầng tổ chức mô tả ở đây đã bị gỡ khỏi hệ thống (migration `0105`/`0106`).
> Giữ lại làm hồ sơ vì sao nó từng tồn tại — **đừng thi công theo**.

# Organization Level Above Tenant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an organization tier above tenant: tenant_id becomes globally-unique, opaque, org-prefixed (`org_<rand8>_<slug>_<rand4>`); MinIO tenant bundles regroup under `<org_id>/<tenant_id>/`; org is derived from tenant_id by pure prefix-parse.

**Architecture:** A new pure `tenant/identity.py` owns the id format (mint + parse). `MinioTenantStore` gains a `_prefix()` that nests every key under `<org>/<tenant>/` and a two-level `list_ids()`. Provisioning mints ids from `(org_id, display_name)`. Postgres, gateway, worker, app_session, facade, `TenantContext`/`TenantMeta` are **unchanged** — tenant_id (globally unique) already isolates, and the Portal owns the `tenant_data` DDL.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode=auto`), boto3 (MinIO/S3), ruff (line-length 120).

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-08-03-organization-level-above-tenant-design.md`.
- Branch: `feat/share-agent`. Local commits only — **no push, no PR, never touch `develop`**.
- `org_id` format: `^org_[a-z0-9]{6,32}$` (the `<rand>` part contains NO `_`).
- `tenant_id` format: `^org_[a-z0-9]{6,32}_[a-z0-9][a-z0-9_-]*$` (globally unique, opaque).
- `org_of(tenant_id)` = first two `_`-segments joined (`org_<rand>`). Pure, no I/O. Fail-loud (raise `ValueError`) on a non-conforming id.
- MinIO object key layout: `<org_id>/<tenant_id>/<rest>` for EVERY object (manifest, `_meta.json`, `_creds.json`, `pointer.json`, `_heartbeat.json`, `versions/<n>/…`, `draft/…`).
- **Do NOT** add `org_id` columns / `app.current_org` GUC / SQL policy changes (D5). **Do NOT** change `tenant_conn`, gateway auth, worker `_job_tenant`, `app_session` token mint, `ws_handler`, `text_chat`, `facade` (D6). **Do NOT** add an `org_id` field to `TenantContext`/`TenantMeta` (unused → YAGNI; also avoids `org_of` raising on legacy in-wheel ids).
- `FakeTenantStore` stays a flat in-memory dict keyed by tenant_id (NOT org-nested) — it is a logical test double; the org-prefix gate lives only in `MinioTenantStore`.
- Local materialize dirs (`materialize.py`, `version_resolver.py`) stay keyed by `tenant_id` only (already globally unique) — do NOT nest them under org.
- Legacy tenants (`noble`, `acme`, `du_test`, …) are migrated to the new format (Task 4/5). No legacy-read branch in `MinioTenantStore`.
- Run the relevant test file after every implementation step; commit at the end of each task.

---

### Task 1: `tenant/identity.py` — id format (mint + parse)

The pure source of truth for org/tenant id shape. Everything else depends on it.

**Files:**
- Create: `src/noble_agent/tenant/identity.py`
- Test: `tests/unit/tenant/test_identity.py`

**Interfaces:**
- Produces:
  - `ORG_RE: re.Pattern`, `TENANT_RE: re.Pattern`
  - `slugify(name: str) -> str`
  - `new_org_id(*, rand: str | None = None) -> str` — `f"org_{rand or secrets.token_hex(4)}"`
  - `new_tenant_id(org_id: str, name: str, *, rand: str | None = None) -> str` — `f"{org_id}_{slugify(name)}_{rand or secrets.token_hex(2)}"`
  - `org_of(tenant_id: str) -> str` — raises `ValueError` if not `TENANT_RE`
  - `is_valid_org_id(s: str) -> bool`, `is_valid_tenant_id(s: str) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/tenant/test_identity.py
import pytest
from noble_agent.tenant import identity as idy


def test_new_org_id_format():
    oid = idy.new_org_id(rand="a1b2c3d4")
    assert oid == "org_a1b2c3d4"
    assert idy.is_valid_org_id(oid)


def test_new_org_id_default_is_valid():
    assert idy.is_valid_org_id(idy.new_org_id())  # secrets-backed, no underscore


def test_slugify_folds_spaces_and_case():
    assert idy.slugify("  Noble  Real Estate ") == "noble-real-estate"
    assert idy.slugify(" Acme!! 2 ") == "acme-2"
    assert idy.slugify("") == "t"  # never empty


def test_new_tenant_id_carries_org_prefix():
    tid = idy.new_tenant_id("org_a1b2c3d4", "Sales North", rand="9f2a")
    assert tid == "org_a1b2c3d4_sales-north_9f2a"
    assert idy.is_valid_tenant_id(tid)


def test_org_of_parses_prefix_ignoring_slug_underscores():
    # slug/suffix underscores must not confuse the parse (first 2 segments only).
    tid = "org_a1b2c3d4_sales_north_9f2a"
    assert idy.org_of(tid) == "org_a1b2c3d4"


def test_org_of_roundtrips_generated_id():
    oid = idy.new_org_id(rand="deadbeef")
    tid = idy.new_tenant_id(oid, "X")
    assert idy.org_of(tid) == oid


def test_org_of_rejects_legacy_id():
    for bad in ("noble", "acme", "demo_acme", "org_short_x", ""):
        with pytest.raises(ValueError):
            idy.org_of(bad)


def test_new_tenant_id_rejects_bad_org():
    with pytest.raises(ValueError):
        idy.new_tenant_id("noble", "x")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_identity.py -q`
Expected: FAIL — `ModuleNotFoundError: noble_agent.tenant.identity`.

- [ ] **Step 3: Implement `identity.py`**

```python
# src/noble_agent/tenant/identity.py
"""Org/tenant id format — mint + parse. Pure, no I/O.

tenant_id is globally unique and opaque: ``org_<rand8>_<slug>_<rand4>``. The org
is the first two ``_``-segments (``org_<rand8>``) and is recovered by prefix
parse — no store lookup, no request carrier. Fail-loud on a non-conforming id.
"""

from __future__ import annotations

import re
import secrets

ORG_RE = re.compile(r"^org_[a-z0-9]{6,32}$")
TENANT_RE = re.compile(r"^org_[a-z0-9]{6,32}_[a-z0-9][a-z0-9_-]*$")


def is_valid_org_id(s: str) -> bool:
    return bool(ORG_RE.match(s or ""))


def is_valid_tenant_id(s: str) -> bool:
    return bool(TENANT_RE.match(s or ""))


def slugify(name: str) -> str:
    """Fold a display name to ``[a-z0-9-]`` (spaces/punct → single '-'); never empty."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "t"


def new_org_id(*, rand: str | None = None) -> str:
    oid = f"org_{rand or secrets.token_hex(4)}"
    if not is_valid_org_id(oid):
        raise ValueError(f"generated org_id is invalid: {oid!r}")
    return oid


def new_tenant_id(org_id: str, name: str, *, rand: str | None = None) -> str:
    if not is_valid_org_id(org_id):
        raise ValueError(f"org_id is not valid: {org_id!r}")
    tid = f"{org_id}_{slugify(name)}_{rand or secrets.token_hex(2)}"
    if not is_valid_tenant_id(tid):  # defensive; slugify + valid org guarantee this
        raise ValueError(f"generated tenant_id is invalid: {tid!r}")
    return tid


def org_of(tenant_id: str) -> str:
    """The org id embedded in a tenant id. Raises ValueError if malformed."""
    if not is_valid_tenant_id(tenant_id):
        raise ValueError(f"tenant_id is not org-formatted: {tenant_id!r}")
    parts = tenant_id.split("_", 2)  # ["org", "<rand>", "<slug>_<rand4>"]
    return f"{parts[0]}_{parts[1]}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_identity.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenant/identity.py tests/unit/tenant/test_identity.py
git add src/noble_agent/tenant/identity.py tests/unit/tenant/test_identity.py
git commit -m "feat(tenant): org/tenant id format (identity.py) — mint + prefix-parse"
```

---

### Task 2: `current_org()` — ambient org (tolerant)

**Files:**
- Modify: `src/noble_agent/tenant/current.py` (append a function)
- Test: `tests/unit/tenant/test_current.py` (append cases)

**Interfaces:**
- Consumes: `identity.org_of` (Task 1), `current_tenant()` (existing).
- Produces: `current_org() -> str | None` — `org_of(current_tenant())`, or `None` when the ambient tenant is not org-formatted (legacy/in-wheel). Never raises.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/tenant/test_current.py`)

```python
def test_current_org_derives_from_tenant():
    from noble_agent.tenant.current import current_org, use_tenant

    with use_tenant("org_a1b2c3d4_sales_9f2a"):
        assert current_org() == "org_a1b2c3d4"


def test_current_org_none_for_legacy(monkeypatch):
    from noble_agent.tenant.current import current_org, use_tenant

    with use_tenant("noble"):  # legacy id → not org-formatted
        assert current_org() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_current.py -q`
Expected: FAIL — `ImportError: cannot import name 'current_org'`.

- [ ] **Step 3: Implement** (append to `src/noble_agent/tenant/current.py`)

```python
def current_org() -> str | None:
    """The org of the current tenant (parsed), or None if not org-formatted.

    Tolerant by design: legacy / in-wheel single-tenant ids (e.g. ``noble``) have
    no org — callers (logging, future guards) treat None as "no org". Never raises.
    """
    from noble_agent.tenant.identity import org_of

    try:
        return org_of(current_tenant())
    except ValueError:
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_current.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenant/current.py tests/unit/tenant/test_current.py
git add src/noble_agent/tenant/current.py tests/unit/tenant/test_current.py
git commit -m "feat(tenant): current_org() derives org from ambient tenant (tolerant)"
```

---

### Task 3: `MinioTenantStore` — org-nested key layout

The core change. Every MinIO key nests under `<org>/<tenant>/`; `list_ids()` becomes a two-level scan. `FakeTenantStore` is untouched.

**Files:**
- Modify: `src/noble_agent/tenant/store.py` (`MinioTenantStore` only)
- Modify: `tests/unit/tenant/test_store.py`, `tests/unit/tenant/test_store_versioning.py`, `tests/unit/gateway/test_store_creds.py` (switch legacy ids → new-format ids; assert org-nested keys)
- Test: add cases to `tests/unit/tenant/test_store.py`

**Interfaces:**
- Consumes: `identity.org_of` (Task 1).
- Produces: `MinioTenantStore` public method signatures UNCHANGED (all still take `tenant_id`); only key layout + `list_ids` behavior change. New private `MinioTenantStore._prefix(tenant_id: str) -> str` → `f"{org_of(tenant_id)}/{tenant_id}"`.

- [ ] **Step 1: Write the failing test** (append to `tests/unit/tenant/test_store.py`; note the module already defines `_FakeS3` and `_meta`)

```python
_T1 = "org_a1b2c3d4_acme_0001"
_T2 = "org_beef1234_globex_0002"  # different org


def test_minio_keys_are_org_nested():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "data_source='pg_kb'", {"persona/SOUL.md": "s"}, _meta_for(_T1)))
    assert "org_a1b2c3d4/org_a1b2c3d4_acme_0001/manifest.toml" in s3.objects
    assert "org_a1b2c3d4/org_a1b2c3d4_acme_0001/_meta.json" in s3.objects
    got = store.read_bundle(_T1)
    assert got.files == {"persona/SOUL.md": "s"}
    store.write_heartbeat(_T1, {"running_version": 3})
    assert "org_a1b2c3d4/org_a1b2c3d4_acme_0001/_heartbeat.json" in s3.objects
    assert store.read_heartbeat(_T1)["running_version"] == 3


def test_minio_list_ids_across_orgs():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "m", {}, _meta_for(_T1)))
    store.write_bundle(Bundle(_T2, "m", {}, _meta_for(_T2)))
    assert store.list_ids() == sorted([_T1, _T2])


def test_minio_read_bundle_excludes_siblings_when_nested():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "m", {"persona/SOUL.md": "s"}, _meta_for(_T1)))
    store.write_heartbeat(_T1, {"status_hint": "serving"})
    store.write_creds_raw(_T1, "[]")
    assert store.read_bundle(_T1).files == {"persona/SOUL.md": "s"}
```

Also add a helper near `_meta`:

```python
def _meta_for(tid, h="sha256:x"):
    return TenantMeta(tenant_id=tid, status="active", version=1, bundle_hash=h)
```

And **update the existing legacy-id store tests** in the same file to new-format ids: replace `"acme"`/`"globex"` with `_T1`/`_T2` and the asserted keys `"acme/…"` with the org-nested keys (e.g. `"org_a1b2c3d4/org_a1b2c3d4_acme_0001/_meta.json"`). Do the same migration in `tests/unit/tenant/test_store_versioning.py` and `tests/unit/gateway/test_store_creds.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_store.py -q`
Expected: FAIL — new tests fail because keys are still flat `<tenant>/…` (and `_prefix` doesn't exist / `org_of` raises on the legacy ids the old code paths still assume).

- [ ] **Step 3: Implement the org-nested layout in `MinioTenantStore`**

Add the helper and rewrite every key. In `src/noble_agent/tenant/store.py`, inside `class MinioTenantStore`, add right after `from_settings`:

```python
    def _prefix(self, tenant_id: str) -> str:
        """Object-key prefix ``<org>/<tenant>`` (org parsed from the tenant id)."""
        from noble_agent.tenant.identity import org_of

        return f"{org_of(tenant_id)}/{tenant_id}"
```

Then replace every `f"{tenant_id}/…"` / `f"{bundle.tenant_id}/"` literal with the prefixed form. Concretely:

- `_read_version_info`: `f"{self._prefix(tenant_id)}/{_VERSIONS_DIR}/{version}/{_VERSION}"`
- `_meta_doc`: `f"{self._prefix(tenant_id)}/{_META}"`
- `read_meta`: the two `self._get_text(f"{tenant_id}/{_MANIFEST}")` / `f"{tenant_id}/{_META}"` reads → `self._prefix(tenant_id)`-based.
- `read_bundle`: `manifest = self._get_text(f"{self._prefix(tenant_id)}/{_MANIFEST}") or ""`; `prefix = f"{self._prefix(tenant_id)}/"` (the rel-strip logic below is unchanged since it keys off `len(prefix)`).
- `read_pointer` / `write_pointer`: `f"{self._prefix(tenant_id)}/{_POINTER}"`.
- `list_versions`: `prefix = f"{self._prefix(tenant_id)}/{_VERSIONS_DIR}/"`; the legacy-`[1]` branch reads `f"{self._prefix(tenant_id)}/{_MANIFEST}"`.
- `read_version_bundle` / `write_version_bundle`: `prefix = f"{self._prefix(tenant_id)}/{_VERSIONS_DIR}/{version}/"`.
- `read_draft` / `write_draft` / `delete_draft`: `prefix = f"{self._prefix(tenant_id)}/{_DRAFT_DIR}/"`.
- `write_status`: `Key=f"{self._prefix(tenant_id)}/{_META}"`.
- `write_bundle`: `base = f"{self._prefix(bundle.tenant_id)}/"`.
- `read_creds_raw` / `write_creds_raw`: `f"{self._prefix(tenant_id)}/{_CREDS}"`.
- `read_heartbeat` / `write_heartbeat`: `f"{self._prefix(tenant_id)}/{_HEARTBEAT}"`.

Rewrite `list_ids` to a two-level scan:

```python
    def list_ids(self) -> list[str]:
        out: list[str] = []
        orgs = self._c.list_objects_v2(Bucket=self._bucket, Prefix="", Delimiter="/")
        for op in orgs.get("CommonPrefixes", []):
            org_prefix = op["Prefix"]  # "org_<rand>/"
            sub = self._c.list_objects_v2(Bucket=self._bucket, Prefix=org_prefix, Delimiter="/")
            for tp in sub.get("CommonPrefixes", []):
                tid = tp["Prefix"][len(org_prefix):].rstrip("/")
                out.append(tid)
        return sorted(out)
```

Update the module docstring line 3-5 to say `<org_id>/<tenant_id>/`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_store.py tests/unit/tenant/test_store_versioning.py tests/unit/gateway/test_store_creds.py -q`
Expected: PASS (all, incl. the migrated legacy-id tests).

- [ ] **Step 5: Regression — store consumers on Fake are unaffected**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_provisioning.py tests/unit/tenant/test_heartbeat.py tests/unit/tenant/test_materialize.py tests/unit/tenant/test_version_resolver.py -q`
Expected: PASS unchanged (these use `FakeTenantStore`, which is not org-nested).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenant/store.py tests/unit/tenant/test_store.py tests/unit/tenant/test_store_versioning.py tests/unit/gateway/test_store_creds.py
git add src/noble_agent/tenant/store.py tests/unit/tenant/test_store.py tests/unit/tenant/test_store_versioning.py tests/unit/gateway/test_store_creds.py
git commit -m "feat(tenant): MinioTenantStore nests keys under <org>/<tenant>/ + 2-level list_ids"
```

---

### Task 4: provisioning — mint from (org, name), list-by-org, legacy migration

**Files:**
- Modify: `src/noble_agent/tenant/provisioning.py` (add functions; `create_tenant` signature UNCHANGED)
- Modify: `src/noble_agent/tenant/store.py` (add `MinioTenantStore.migrate_legacy_layout`)
- Modify: `src/noble_agent/tenant/loader.py` (`_context_from_dir` uses path-authoritative tenant_id)
- Test: `tests/unit/tenant/test_provisioning_org.py` (new), append to `tests/unit/tenant/test_store.py`

**Interfaces:**
- Consumes: `identity.new_tenant_id`/`org_of`/`is_valid_tenant_id` (Task 1), `MinioTenantStore._prefix` (Task 3), existing `create_tenant`, `list_tenants`.
- Produces:
  - `provision_tenant(store, *, org_id, name, manifest_text, files, status="draft", now=None, rand=None) -> tuple[str, TenantMeta]` — mints `tenant_id = new_tenant_id(org_id, name, rand=rand)`, calls `create_tenant`, returns `(tenant_id, meta)`.
  - `list_orgs(store) -> list[str]` — sorted distinct `org_of(m.tenant_id)` over `list_tenants` (ids that don't parse are skipped).
  - `list_tenants(store, *, org_id: str | None = None) -> list[TenantMeta]` — existing, gains optional `org_id` filter.
  - `MinioTenantStore.migrate_legacy_layout(org_id, *, purge=False) -> dict[str, str]` — copies each legacy flat `<old>/…` bundle+creds to a freshly-minted `<org>/<new_id>/…`; returns `{old_id: new_id}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/tenant/test_provisioning_org.py
from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.identity import org_of
from noble_agent.tenant.store import FakeTenantStore

_MANIFEST = 'data_source = "pg_kb"\npersona_dir = "persona"\n[tools]\nenabled = ["kb_search"]\n'
_FILES = {
    "persona/config.json": "{}",
    "persona/SOUL.md": "s",
    "persona/RULES.md": "r",
    "persona/PROMPT_TEMPLATE.md": "p",
    "persona/CUSTOMER_PROFILE.md": "c",
}


def test_provision_tenant_mints_org_prefixed_id():
    store = FakeTenantStore()
    tid, meta = prov.provision_tenant(
        store, org_id="org_a1b2c3d4", name="Sales North",
        manifest_text=_MANIFEST, files=_FILES, status="active", rand="9f2a",
    )
    assert tid == "org_a1b2c3d4_sales-north_9f2a"
    assert org_of(tid) == "org_a1b2c3d4"
    assert meta.status == "active"
    assert store.read_meta(tid) is not None


def test_list_orgs_and_list_tenants_by_org():
    store = FakeTenantStore()
    prov.provision_tenant(store, org_id="org_a1b2c3d4", name="a", manifest_text=_MANIFEST, files=_FILES, status="active", rand="1111")
    prov.provision_tenant(store, org_id="org_a1b2c3d4", name="b", manifest_text=_MANIFEST, files=_FILES, status="active", rand="2222")
    prov.provision_tenant(store, org_id="org_beef5678", name="c", manifest_text=_MANIFEST, files=_FILES, status="active", rand="3333")
    assert prov.list_orgs(store) == ["org_a1b2c3d4", "org_beef5678"]
    assert len(prov.list_tenants(store, org_id="org_a1b2c3d4")) == 2
    assert len(prov.list_tenants(store, org_id="org_beef5678")) == 1
    assert len(prov.list_tenants(store)) == 3
```

And the migration test (append to `tests/unit/tenant/test_store.py`, uses `_FakeS3`):

```python
def test_migrate_legacy_layout_moves_bundle_under_org():
    s3 = _FakeS3()
    # seed a LEGACY flat tenant "noble" (old <tenant>/… layout) + creds
    s3.put_object(Bucket="b", Key="noble/manifest.toml", Body="data_source='pg_kb'")
    s3.put_object(Bucket="b", Key="noble/persona/SOUL.md", Body="s")
    s3.put_object(Bucket="b", Key="noble/_meta.json",
                  Body=json.dumps({"tenant_id": "noble", "status": "active", "bundle_hash": "sha256:x"}))
    s3.put_object(Bucket="b", Key="noble/_creds.json", Body="[]")
    store = MinioTenantStore(s3, "b")

    mapping = store.migrate_legacy_layout("org_a1b2c3d4", purge=True)

    new_id = mapping["noble"]
    assert new_id.startswith("org_a1b2c3d4_noble_")
    # new bundle readable via the normal (org-nested) path
    assert store.read_bundle(new_id).files == {"persona/SOUL.md": "s"}
    assert store.read_creds_raw(new_id) == "[]"
    # legacy flat keys purged
    assert not any(k.startswith("noble/") for k in s3.objects)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_provisioning_org.py tests/unit/tenant/test_store.py -q`
Expected: FAIL — `provision_tenant`/`list_orgs`/`migrate_legacy_layout` missing; `list_tenants` has no `org_id` kwarg.

- [ ] **Step 3a: Implement provisioning functions** (`src/noble_agent/tenant/provisioning.py`)

Add near the top import: `from noble_agent.tenant.identity import new_tenant_id, org_of`.

```python
def provision_tenant(
    store: TenantStore,
    *,
    org_id: str,
    name: str,
    manifest_text: str,
    files: dict[str, str],
    status: str = "draft",
    now: str | None = None,
    rand: str | None = None,
) -> tuple[str, TenantMeta]:
    """Mint a globally-unique, org-prefixed tenant id from (org_id, display name)
    and create the bundle. Returns (tenant_id, meta)."""
    tenant_id = new_tenant_id(org_id, name, rand=rand)
    meta = create_tenant(store, tenant_id, manifest_text, files, status=status, now=now)
    return tenant_id, meta


def list_orgs(store: TenantStore) -> list[str]:
    """Distinct org ids derived from the store's tenants (unparseable ids skipped)."""
    orgs: set[str] = set()
    for m in list_tenants(store):
        try:
            orgs.add(org_of(m.tenant_id))
        except ValueError:
            continue
    return sorted(orgs)
```

Change `list_tenants` to accept an optional org filter:

```python
def list_tenants(store: TenantStore, *, org_id: str | None = None) -> list[TenantMeta]:
    metas = [m for m in (store.read_meta(i) for i in store.list_ids()) if m is not None]
    if org_id is None:
        return metas
    out = []
    for m in metas:
        try:
            if org_of(m.tenant_id) == org_id:
                out.append(m)
        except ValueError:
            continue
    return out
```

- [ ] **Step 3b: Implement `migrate_legacy_layout`** (`MinioTenantStore` in `src/noble_agent/tenant/store.py`)

```python
    # -- one-off legacy→org-nested migration --------------------------------
    def _legacy_top_prefixes(self) -> list[str]:
        """Top-level prefixes NOT already org-formatted (old flat tenants)."""
        from noble_agent.tenant.identity import is_valid_org_id

        resp = self._c.list_objects_v2(Bucket=self._bucket, Prefix="", Delimiter="/")
        return [
            p["Prefix"].rstrip("/")
            for p in resp.get("CommonPrefixes", [])
            if not is_valid_org_id(p["Prefix"].rstrip("/"))
        ]

    def migrate_legacy_layout(self, org_id: str, *, purge: bool = False) -> dict[str, str]:
        """Copy each legacy flat ``<old>/…`` bundle (+creds) to a freshly-minted
        ``<org>/<new_id>/…``. Returns {old_id: new_id}. New tenants start at v1
        (version history is NOT carried). ``purge=True`` deletes the old keys."""
        from noble_agent.tenant.identity import new_tenant_id

        mapping: dict[str, str] = {}
        for old in self._legacy_top_prefixes():
            manifest = self._get_text(f"{old}/{_MANIFEST}")
            if manifest is None:
                continue  # not a bundle (e.g. a stray object)
            listing = self._c.list_objects_v2(Bucket=self._bucket, Prefix=f"{old}/")
            files: dict[str, str] = {}
            creds: str | None = None
            for obj in listing.get("Contents", []):
                key = obj["Key"]
                rel = key[len(old) + 1:]
                if not rel or rel == _MANIFEST:
                    continue
                if rel == _CREDS:
                    creds = self._get_text(key)
                    continue
                if rel in (_META, _POINTER, _HEARTBEAT) or rel.startswith((f"{_VERSIONS_DIR}/", f"{_DRAFT_DIR}/")):
                    continue
                text = self._get_text(key)
                if text is not None:
                    files[rel] = text
            new_id = new_tenant_id(org_id, old)
            meta = TenantMeta(new_id, "active", 1, bundle_hash(manifest, files))
            self.write_bundle(Bundle(new_id, manifest, files, meta))
            if creds is not None:
                self.write_creds_raw(new_id, creds)
            mapping[old] = new_id
            if purge:
                delete = getattr(self._c, "delete_object", None)
                if callable(delete):
                    for obj in listing.get("Contents", []):
                        delete(Bucket=self._bucket, Key=obj["Key"])
        return mapping
```

Add `delete_object` to the test `_FakeS3` (if absent) so `purge=True` works:

```python
    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)
```

- [ ] **Step 3c: Make `_context_from_dir` path-authoritative for tenant_id** (`src/noble_agent/tenant/loader.py`)

A minted tenant's manifest may not carry the generated id, so the loader must trust the resolved id, not the manifest. Change line 92 from `tenant_id=data.get("tenant_id", tenant_id),` to:

```python
        tenant_id=tenant_id,  # path/resolver is authoritative (minted ids aren't in the manifest)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_provisioning_org.py tests/unit/tenant/test_store.py tests/unit/tenant/test_loader.py tests/unit/tenant/test_context.py -q`
Expected: PASS. If `test_context.py`/`test_loader.py` asserted manifest-tenant_id precedence, update that assertion to expect the path-authoritative id.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenant/provisioning.py src/noble_agent/tenant/store.py src/noble_agent/tenant/loader.py tests/unit/tenant/test_provisioning_org.py tests/unit/tenant/test_store.py
git add -A
git commit -m "feat(tenant): provision_tenant mints org-prefixed id; list-by-org; legacy layout migration"
```

---

### Task 5: `noble-tenant` CLI — org subcommands

**Files:**
- Modify: `src/noble_agent/tenant/cli.py`
- Test: `tests/unit/tenant/test_cli_org.py` (new)

**Interfaces:**
- Consumes: `identity.new_org_id` (Task 1), `provisioning.provision_tenant`/`list_orgs`/`list_tenants(org_id=)` (Task 4), `MinioTenantStore.migrate_legacy_layout` (Task 4).
- Produces: subcommands `create-org`, `create-tenant --org --name --dir [--status]`, `list-orgs`, `list [--org]`, `migrate-org-layout --org [--purge]`. (The existing `create <tenant_id> --dir` stays for back-compat/tests but is no longer the org path.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/tenant/test_cli_org.py
from noble_agent.tenant.cli import main
from noble_agent.tenant.store import FakeTenantStore

_DIR = None  # built in a tmp_path fixture below


def _write_bundle_dir(tmp_path):
    (tmp_path / "persona").mkdir()
    (tmp_path / "manifest.toml").write_text(
        'data_source = "pg_kb"\npersona_dir = "persona"\n[tools]\nenabled = ["kb_search"]\n'
    )
    for f in ("config.json", "SOUL.md", "RULES.md", "PROMPT_TEMPLATE.md", "CUSTOMER_PROFILE.md"):
        (tmp_path / "persona" / f).write_text("{}" if f.endswith(".json") else "x")
    return str(tmp_path)


def test_create_org_prints_id(capsys):
    store = FakeTenantStore()
    rc = main(["create-org", "--name", "Noble"], store=store)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("org_")


def test_create_tenant_under_org(tmp_path, capsys):
    store = FakeTenantStore()
    d = _write_bundle_dir(tmp_path)
    rc = main(["create-tenant", "--org", "org_a1b2c3d4", "--name", "Sales", "--dir", d, "--status", "active"], store=store)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "org_a1b2c3d4_sales_" in out
    assert len(store.list_ids()) == 1


def test_list_orgs_cli(tmp_path, capsys):
    store = FakeTenantStore()
    d = _write_bundle_dir(tmp_path)
    main(["create-tenant", "--org", "org_a1b2c3d4", "--name", "x", "--dir", d, "--status", "active"], store=store)
    capsys.readouterr()
    rc = main(["list-orgs"], store=store)
    assert rc == 0
    assert "org_a1b2c3d4" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_cli_org.py -q`
Expected: FAIL — unknown subcommands `create-org`/`create-tenant`/`list-orgs`.

- [ ] **Step 3: Implement the subcommands** (`src/noble_agent/tenant/cli.py`)

Register parsers (after the existing `list` parser block):

```python
    p_co = sub.add_parser("create-org")
    p_co.add_argument("--name", required=True)

    sub.add_parser("list-orgs")

    p_ct = sub.add_parser("create-tenant")
    p_ct.add_argument("--org", required=True)
    p_ct.add_argument("--name", required=True)
    p_ct.add_argument("--dir", required=True)
    p_ct.add_argument("--status", default="draft", choices=["draft", "active", "disabled"])

    p_mig = sub.add_parser("migrate-org-layout")
    p_mig.add_argument("--org", required=True)
    p_mig.add_argument("--purge", action="store_true")
```

Add an `--org` filter to the existing `list` parser: `sub.add_parser("list")` → capture it and `p_list.add_argument("--org", default=None)`.

Add handlers (in the `st = _get_store(store)` block; place `create-org`/`list-orgs`/`create-tenant`/`migrate-org-layout` handlers alongside the others):

```python
    if args.cmd == "create-org":
        from noble_agent.tenant.identity import new_org_id

        print(new_org_id())  # mint + print; the real org record lives in the Portal control-plane
        return 0
    if args.cmd == "list-orgs":
        for oid in prov.list_orgs(st):
            print(oid)
        return 0
    if args.cmd == "create-tenant":
        manifest_text, files, _ = _read_dir_bundle(args.dir)
        tid, meta = prov.provision_tenant(
            st, org_id=args.org, name=args.name, manifest_text=manifest_text, files=files, status=args.status
        )
        print(f"created {tid} v{meta.version} status={meta.status}")
        return 0
    if args.cmd == "migrate-org-layout":
        if not hasattr(st, "migrate_legacy_layout"):
            print("ERROR: store does not support migration (needs MinioTenantStore)")
            return 1
        mapping = st.migrate_legacy_layout(args.org, purge=args.purge)
        for old, new in sorted(mapping.items()):
            print(f"{old} -> {new}")
        print(f"migrated {len(mapping)} tenant(s){' (purged legacy keys)' if args.purge else ''}")
        return 0
```

Update the existing `list` handler to honor `--org`:

```python
    if args.cmd == "list":
        for m in prov.list_tenants(st, org_id=args.org):
            print(f"{m.tenant_id}\t{m.status}\tv{m.version}")
        return 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_cli_org.py tests/unit/tenant/test_cli.py -q`
Expected: PASS (new org tests + existing CLI tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenant/cli.py tests/unit/tenant/test_cli_org.py
git add src/noble_agent/tenant/cli.py tests/unit/tenant/test_cli_org.py
git commit -m "feat(tenant): noble-tenant CLI org subcommands (create-org, create-tenant, list-orgs, migrate-org-layout)"
```

---

### Task 6: Isolation gate — two orgs, same display name, no bleed

Proves the whole point: two orgs each create a tenant with the SAME display name → distinct globally-unique ids → no store/context bleed when interleaved in one process.

**Files:**
- Test: `tests/unit/tenant/test_org_isolation.py` (new)

**Interfaces:**
- Consumes: `provisioning.provision_tenant` (Task 4), `identity.org_of` (Task 1), `MinioTenantStore` + `_FakeS3` layout (Task 3).

- [ ] **Step 1: Write the test**

```python
# tests/unit/tenant/test_org_isolation.py
"""Two orgs, same display name → distinct org-prefixed ids, org-nested storage,
no bleed. The org tier's reason for existing."""
import io
import json


class _FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None):  # noqa: N803
        if Delimiter:
            prefixes = set()
            for k in self.objects:
                if k.startswith(Prefix):
                    rest = k[len(Prefix):]
                    if Delimiter in rest:
                        prefixes.add(Prefix + rest.split(Delimiter, 1)[0] + Delimiter)
            return {"CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)]}
        return {"Contents": [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)]}


_MANIFEST = 'data_source = "pg_kb"\npersona_dir = "persona"\n[tools]\nenabled = ["kb_search"]\n'
_FILES = {
    "persona/config.json": "{}", "persona/SOUL.md": "s", "persona/RULES.md": "r",
    "persona/PROMPT_TEMPLATE.md": "p", "persona/CUSTOMER_PROFILE.md": "c",
}


def test_same_name_two_orgs_do_not_bleed():
    from noble_agent.tenant import provisioning as prov
    from noble_agent.tenant.identity import org_of
    from noble_agent.tenant.store import MinioTenantStore

    store = MinioTenantStore(_FakeS3(), "hotline-tenants")
    t_a, _ = prov.provision_tenant(store, org_id="org_a1b2c3d4", name="Sales", manifest_text=_MANIFEST, files=_FILES, status="active", rand="aaaa")
    t_b, _ = prov.provision_tenant(store, org_id="org_beef5678", name="Sales", manifest_text=_MANIFEST, files=_FILES, status="active", rand="bbbb")

    assert t_a != t_b
    assert org_of(t_a) == "org_a1b2c3d4"
    assert org_of(t_b) == "org_beef5678"
    # each tenant reads back its OWN org bundle, keyed under its own org prefix
    assert store.read_meta(t_a).tenant_id == t_a
    assert store.read_meta(t_b).tenant_id == t_b
    assert prov.list_tenants(store, org_id="org_a1b2c3d4") == [m for m in [store.read_meta(t_a)]]
    assert sorted(store.list_ids()) == sorted([t_a, t_b])
```

- [ ] **Step 2: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/tenant/test_org_isolation.py -q`
Expected: PASS.

- [ ] **Step 3: Full tenant-suite regression**

Run: `.venv/bin/python -m pytest tests/unit/tenant -q`
Expected: PASS (0 new failures vs the documented baseline). Investigate any red that isn't in the known baseline.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/tenant/test_org_isolation.py
git commit -m "test(tenant): org isolation gate — same display name across two orgs, no bleed"
```

---

## Self-Review

**Spec coverage:**
- §3.A Định danh org → Task 1 (`identity.py`), Task 2 (`current_org`).
- §3.B MinIO reorg → Task 3 (`MinioTenantStore` 2-level).
- §3.C Provisioning + CLI → Task 4 (provision_tenant/list-by-org/migrate) + Task 5 (CLI).
- §5 Migration (MinIO half) → Task 4 `migrate_legacy_layout` + Task 5 CLI `migrate-org-layout`. The Postgres-rename half is Portal-coordinated ops, explicitly out of scope (Global Constraints / spec §5) — no task, by design.
- §6 Testing → Tasks 1–6 each ship tests; Task 6 is the isolation gate.
- §7 Không làm → enforced by Global Constraints (no SQL/GUC/boundary/context-field changes).

**Deviations from the spec (deliberate, safer):**
- Spec §4.C proposed `org_id` fields on `TenantContext`/`TenantMeta` and a manifest `[org].id`. Plan DROPS them: nothing consumes them, and computing them via `org_of` would raise on legacy in-wheel ids (`noble`). Org is derived on demand via `identity.org_of` / `current_org()` instead. (Recorded here so the spec-reader isn't surprised.)
- Spec §4.G proposed persisting an `<org>/_org.json` record + org store methods. Plan DROPS it: the org registry (name/lifecycle) is Portal-owned (`control.organizations`); this repo keeps org as a derived namespace only. `create-org` just mints an id; `list-orgs` derives from tenants.
- `create_tenant(store, tenant_id, …)` keeps its signature (used by existing tests); the org path is the new `provision_tenant`.

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `org_of`/`new_org_id`/`new_tenant_id`/`is_valid_*` names identical across Tasks 1–6; `provision_tenant` returns `(tenant_id, meta)` consistently; `_prefix(tenant_id)` used consistently in Task 3; `migrate_legacy_layout(org_id, *, purge)` consistent in Tasks 4–5.

**Known-baseline note:** the tenant suite has documented pre-existing reds elsewhere in the repo; scope the "0 new failures" check to `tests/unit/tenant`.
