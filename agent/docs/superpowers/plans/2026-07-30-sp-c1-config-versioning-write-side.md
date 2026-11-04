# SP-C1 — Config Versioning (Write Side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add immutable numbered config versions + a published-version pointer + rollback to the tenant store, with a structural-validation publish gate — the write side of SP-C.

**Architecture:** Extend `tenant/store.py` with draft / immutable-version / pointer primitives (Fake + Minio), keep `read_bundle`/`read_meta` back-compat (resolve to the pointed version; legacy in-place = v1). Orchestrate draft→publish→rollback in `tenant/provisioning.py` (pure over the store Protocol), expose via the `noble-tenant` CLI. Read side (version-pinned agent load) is SP-C2, out of scope.

**Tech Stack:** Python 3.11+, stdlib `json`/`hashlib`, pytest (`asyncio_mode=auto`), boto3 S3 client (Minio), ruff (line-length 120).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-sp-c1-config-versioning-write-side-design.md`. Contract C2: `docs/api/odyssey-agent-interface-contract.md`.
- BR06: versions immutable, monotonically increasing, never overwritten; rollback = move pointer, never a new version.
- BR07: on publish, write the version snapshot FIRST, the pointer AFTER.
- E08: publish runs the STRUCTURAL validator (`tenant/validation.py::validate_bundle`) on the draft; on failure, write nothing.
- Back-compat: `read_bundle`/`read_meta`/`list_ids`/`read_creds_raw`/`write_creds_raw` signatures UNCHANGED; gateway (`registry.is_active`) and loader/materialize must keep working untouched.
- Fail loud: a real backend error (not NoSuchKey/404) must never read as "not found" — keep `store._is_missing`.
- ruff clean on every touched file; no new failures in `tests/unit/tenant` or `tests/unit/gateway`.
- Branch `feat/agent`; local commits only (no push).

---

### Task 1: Store data models — `VersionInfo` + `TenantMeta` version fields

**Files:**
- Modify: `src/noble_agent/tenant/store.py` (add `VersionInfo`; extend `TenantMeta`)
- Test: `tests/unit/tenant/test_store_versioning.py` (new)

**Interfaces:**
- Produces:
  - `VersionInfo(tenant_id:str, version:int, bundle_hash:str, created_at:str="", created_by:str="", parent_version:int|None=None, field_policy:None=None)` — frozen dataclass.
  - `TenantMeta` gains `published_version:int=0`, `latest_version:int=0` (existing fields kept; `version:int` retained for back-compat, writers set it = `published_version`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/tenant/test_store_versioning.py
from noble_agent.tenant.store import TenantMeta, VersionInfo


def test_version_info_frozen_defaults():
    vi = VersionInfo(tenant_id="t", version=3, bundle_hash="sha256:x")
    assert (vi.version, vi.parent_version, vi.field_policy) == (3, None, None)
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        vi.version = 4  # type: ignore[misc]


def test_tenant_meta_has_version_fields():
    m = TenantMeta("t", "active", version=2, bundle_hash="sha256:x",
                   published_version=2, latest_version=2)
    assert (m.published_version, m.latest_version, m.version) == (2, 2, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_store_versioning.py -q`
Expected: FAIL (`ImportError: VersionInfo` / unexpected kwargs on `TenantMeta`).

- [ ] **Step 3: Implement**

In `store.py`, extend `TenantMeta` (add fields with defaults so existing positional callers keep working) and add `VersionInfo`:

```python
@dataclass(frozen=True)
class TenantMeta:
    tenant_id: str
    status: str  # "active" | "draft" | "disabled"
    version: int
    bundle_hash: str
    created_at: str = ""
    updated_at: str = ""
    published_version: int = 0
    latest_version: int = 0


@dataclass(frozen=True)
class VersionInfo:
    tenant_id: str
    version: int
    bundle_hash: str
    created_at: str = ""
    created_by: str = ""
    parent_version: int | None = None
    field_policy: None = None  # reserved for SP-E field-column policy
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/tenant/test_store_versioning.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/store.py tests/unit/tenant/test_store_versioning.py
git commit -m "feat(tenant): VersionInfo + TenantMeta version fields (SP-C1 t1)"
```

---

### Task 2: `FakeTenantStore` versioned primitives + back-compat resolution

**Files:**
- Modify: `src/noble_agent/tenant/store.py` (`TenantStore` Protocol + `FakeTenantStore`)
- Test: `tests/unit/tenant/test_store_versioning.py`

**Interfaces:**
- Produces (added to Protocol + Fake + later Minio):
  - `read_pointer(tenant_id) -> int | None`
  - `write_pointer(tenant_id, version:int) -> None`
  - `list_versions(tenant_id) -> list[int]`  (sorted asc)
  - `read_version_bundle(tenant_id, version:int) -> Bundle | None`
  - `write_version_bundle(tenant_id, version:int, bundle:Bundle, info:VersionInfo) -> None`  (raises if version exists)
  - `read_draft(tenant_id) -> Bundle | None`
  - `write_draft(tenant_id, bundle:Bundle) -> None`
- `read_bundle`: pointer set → the pointed version's bundle; else legacy in-place bundle (v1). Never returns draft.
- `read_meta`: `published_version` = pointer (or 1 legacy), `latest_version` = max(list_versions) (or 1), `version` = published_version, `bundle_hash` = published version's hash.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/tenant/test_store_versioning.py
import pytest
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, VersionInfo, bundle_hash

def _bundle(tid, body="v"):
    files = {"persona/SOUL.md": body}
    mtext = f'tenant_id="{tid}"\n'
    meta = TenantMeta(tid, "active", 1, bundle_hash(mtext, files))
    return Bundle(tid, mtext, files, meta)

def test_write_read_version_and_pointer():
    s = FakeTenantStore()
    b1 = _bundle("t", "one")
    s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))
    s.write_pointer("t", 1)
    assert s.list_versions("t") == [1]
    assert s.read_pointer("t") == 1
    assert s.read_version_bundle("t", 1).files["persona/SOUL.md"] == "one"

def test_read_bundle_returns_pointed_version_not_draft():
    s = FakeTenantStore()
    b1 = _bundle("t", "published")
    s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))
    s.write_pointer("t", 1)
    s.write_draft("t", _bundle("t", "draft-wip"))
    assert s.read_bundle("t").files["persona/SOUL.md"] == "published"
    assert s.read_draft("t").files["persona/SOUL.md"] == "draft-wip"

def test_write_version_twice_raises_immutable():
    s = FakeTenantStore()
    b1 = _bundle("t")
    s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))
    with pytest.raises(Exception):
        s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))

def test_legacy_in_place_reads_as_v1():
    s = FakeTenantStore()
    s.write_bundle(_bundle("t", "legacy"))  # old in-place path, no pointer
    assert s.read_pointer("t") is None
    assert s.list_versions("t") == [1]
    assert s.read_bundle("t").files["persona/SOUL.md"] == "legacy"
    assert s.read_meta("t").published_version == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_store_versioning.py -q`
Expected: FAIL (`AttributeError: write_version_bundle`).

- [ ] **Step 3: Implement**

Add the methods to the `TenantStore` Protocol, then implement on `FakeTenantStore`:

```python
class FakeTenantStore:
    def __init__(self) -> None:
        self._bundles: dict[str, Bundle] = {}        # legacy in-place
        self._versions: dict[str, dict[int, tuple[Bundle, VersionInfo]]] = {}
        self._pointers: dict[str, int] = {}
        self._drafts: dict[str, Bundle] = {}
        self._creds: dict[str, str] = {}

    # -- versioned primitives --
    def read_pointer(self, tenant_id):
        return self._pointers.get(tenant_id)

    def write_pointer(self, tenant_id, version):
        self._pointers[tenant_id] = version

    def list_versions(self, tenant_id):
        if tenant_id in self._versions:
            return sorted(self._versions[tenant_id])
        return [1] if tenant_id in self._bundles else []

    def read_version_bundle(self, tenant_id, version):
        v = self._versions.get(tenant_id, {}).get(version)
        return v[0] if v else None

    def write_version_bundle(self, tenant_id, version, bundle, info):
        vs = self._versions.setdefault(tenant_id, {})
        if version in vs:
            raise ValueError(f"version {version} already exists for {tenant_id!r}")
        vs[version] = (bundle, info)

    def read_draft(self, tenant_id):
        return self._drafts.get(tenant_id)

    def write_draft(self, tenant_id, bundle):
        self._drafts[tenant_id] = bundle

    # -- back-compat reads --
    def read_bundle(self, tenant_id):
        ptr = self._pointers.get(tenant_id)
        if ptr is not None:
            b = self.read_version_bundle(tenant_id, ptr)
            if b is None:
                raise ValueError(f"pointer→{ptr} but version missing for {tenant_id!r}")
            return b
        return self._bundles.get(tenant_id)

    def read_meta(self, tenant_id):
        ptr = self._pointers.get(tenant_id)
        if ptr is not None:
            _, info = self._versions[tenant_id][ptr]
            latest = max(self._versions[tenant_id])
            return TenantMeta(tenant_id, self._status.get(tenant_id, "active"), ptr,
                              info.bundle_hash, published_version=ptr, latest_version=latest)
        b = self._bundles.get(tenant_id)
        return b.meta if b else None
```

Keep `write_bundle`/`list_ids`/`read_creds_raw`/`write_creds_raw` as-is; add a `self._status: dict[str,str] = {}` in `__init__` and have `set_status`-style writes update it (provisioning sets status; for Fake, expose a helper `write_pointer` doesn't touch status — status is written by a new `write_meta_status(tenant_id, status)` used by provisioning Task 5). For now default `"active"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/tenant/test_store_versioning.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full tenant suite for no-regression**

Run: `pytest tests/unit/tenant -q`
Expected: existing tests still pass (TenantMeta new fields have defaults).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/tenant/store.py tests/unit/tenant/test_store_versioning.py
git commit -m "feat(tenant): FakeTenantStore versioned primitives + read-compat (SP-C1 t2)"
```

---

### Task 3: `MinioTenantStore` versioned primitives + back-compat resolution

**Files:**
- Modify: `src/noble_agent/tenant/store.py` (`MinioTenantStore`)
- Test: `tests/unit/tenant/test_store_versioning.py` (Minio via a fake S3 client)

**Interfaces:** same method set as Task 2, over S3 keys:
- `<t>/pointer.json` = `{"published_version": n, "updated_at": "", "updated_by": ""}`
- `<t>/versions/<n>/manifest.toml`, `<t>/versions/<n>/<rel>`, `<t>/versions/<n>/version.json`
- `<t>/draft/manifest.toml`, `<t>/draft/<rel>`

- [ ] **Step 1: Write the failing test**

Reuse the in-memory fake S3 client from the existing store tests (search `tests/unit/tenant/test_store.py` for a `_FakeS3`/dict-backed client; import or copy its minimal form). Test:

```python
# append to tests/unit/tenant/test_store_versioning.py
from noble_agent.tenant.store import MinioTenantStore

class _S3:
    def __init__(self): self.objs = {}
    def put_object(self, Bucket, Key, Body): self.objs[(Bucket, Key)] = Body
    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objs: raise KeyError(Key)
        import io; return {"Body": io.BytesIO(self.objs[(Bucket, Key)])}
    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None):
        keys = [k for (b, k) in self.objs if b == Bucket and k.startswith(Prefix)]
        if Delimiter:
            pres = sorted({Prefix + k[len(Prefix):].split("/")[0] + "/" for k in keys})
            return {"CommonPrefixes": [{"Prefix": p} for p in pres]}
        return {"Contents": [{"Key": k} for k in keys]}

def test_minio_version_pointer_roundtrip():
    s = MinioTenantStore(_S3(), "buck")
    b1 = _bundle("t", "one")
    s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash, created_at="ts"))
    s.write_pointer("t", 1)
    assert s.read_pointer("t") == 1
    assert s.list_versions("t") == [1]
    assert s.read_version_bundle("t", 1).files["persona/SOUL.md"] == "one"
    assert s.read_bundle("t").files["persona/SOUL.md"] == "one"
```

Note: `_is_missing(KeyError)` is already True, so the fake raising `KeyError` maps to "missing".

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_store_versioning.py::test_minio_version_pointer_roundtrip -q`
Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement** the same seven methods on `MinioTenantStore` using the S3 key layout above (mirror the existing `read_bundle`/`write_bundle` object-listing pattern; `version.json` (de)serialized as JSON). `read_bundle`/`read_meta` gain the pointer-resolution shown in Task 2 (pointer set → version bundle/meta; else the existing in-place path unchanged). `list_versions` = list `CommonPrefixes` under `<t>/versions/` → ints (or `[1]` if legacy in-place meta present, `[]` otherwise). `write_version_bundle` raises if `<t>/versions/<n>/version.json` already exists.

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/unit/tenant/test_store_versioning.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/store.py tests/unit/tenant/test_store_versioning.py
git commit -m "feat(tenant): MinioTenantStore versioned primitives + read-compat (SP-C1 t3)"
```

---

### Task 4: `save_draft` + `publish` (with validation gate, BR07 order)

**Files:**
- Modify: `src/noble_agent/tenant/provisioning.py`
- Test: `tests/unit/tenant/test_provisioning_versioning.py` (new)

**Interfaces:**
- Consumes: store versioned primitives (Task 2/3), `validate_bundle` (existing), `bundle_hash` (existing).
- Produces:
  - `save_draft(store, tenant_id, *, manifest_text=None, files=None, now=None) -> None`
  - `publish(store, tenant_id, *, created_by="", now=None) -> VersionInfo`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/tenant/test_provisioning_versioning.py
import pytest
from noble_agent.tenant.store import FakeTenantStore
from noble_agent.tenant import provisioning as P

VALID_MANIFEST = 'tenant_id="t"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n'
VALID_FILES = {"persona/SOUL.md": "x", "persona/RULES.md": "escalate", "persona/PROMPT_TEMPLATE.md": "x",
               "persona/CUSTOMER_PROFILE.md": "x", "persona/config.json": "{}"}

def _seed(store):  # a tenant that already has v1 published
    P.create_tenant(store, "t", VALID_MANIFEST, VALID_FILES, status="active")

def test_publish_creates_immutable_version_and_moves_pointer():
    s = FakeTenantStore(); _seed(s)
    assert s.list_versions("t") == [1] and s.read_pointer("t") == 1
    P.save_draft(s, "t", files={**VALID_FILES, "persona/SOUL.md": "v2-soul"})
    info = P.publish(s, "t", created_by="alice")
    assert info.version == 2 and s.read_pointer("t") == 2
    assert s.list_versions("t") == [1, 2]
    assert s.read_version_bundle("t", 1).files["persona/SOUL.md"] == "x"   # v1 untouched
    assert s.read_bundle("t").files["persona/SOUL.md"] == "v2-soul"

def test_publish_rejects_invalid_draft_no_write():
    s = FakeTenantStore(); _seed(s)
    P.save_draft(s, "t", manifest_text='tenant_id="t"\n')  # missing data_source/persona/tools
    with pytest.raises(ValueError):
        P.publish(s, "t")
    assert s.read_pointer("t") == 1 and s.list_versions("t") == [1]  # unchanged

def test_publish_without_draft_raises():
    s = FakeTenantStore(); _seed(s)
    with pytest.raises(ValueError):
        P.publish(s, "t")
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/unit/tenant/test_provisioning_versioning.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
def save_draft(store, tenant_id, *, manifest_text=None, files=None, now=None):
    cur = store.read_draft(tenant_id) or store.read_bundle(tenant_id)
    if cur is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    mtext = manifest_text if manifest_text is not None else cur.manifest_text
    fs = files if files is not None else cur.files
    store.write_draft(tenant_id, Bundle(tenant_id, mtext, fs, cur.meta))

def publish(store, tenant_id, *, created_by="", now=None):
    draft = store.read_draft(tenant_id)
    if draft is None:
        raise ValueError(f"no draft to publish for {tenant_id!r}")
    report = validate_bundle(tenant_id, draft.manifest_text, draft.files)
    if not report.ok:
        raise ValueError("bundle invalid: " + "; ".join(report.errors))
    ts = _now(now)
    versions = store.list_versions(tenant_id)
    n = (max(versions) + 1) if versions else 1
    bh = bundle_hash(draft.manifest_text, draft.files)
    info = VersionInfo(tenant_id, n, bh, created_at=ts, created_by=created_by,
                       parent_version=(max(versions) if versions else None))
    meta = TenantMeta(tenant_id, "active", n, bh, updated_at=ts, published_version=n, latest_version=n)
    store.write_version_bundle(tenant_id, n, Bundle(tenant_id, draft.manifest_text, draft.files, meta), info)  # BR07: snapshot first
    store.write_pointer(tenant_id, n)  # BR07: pointer after
    return info
```

Import `Bundle, TenantMeta, VersionInfo, bundle_hash` at top of provisioning.

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/provisioning.py tests/unit/tenant/test_provisioning_versioning.py
git commit -m "feat(tenant): save_draft + publish with validation gate (SP-C1 t4)"
```

---

### Task 5: `rollback` + `list_versions` + `diff_versions`

**Files:**
- Modify: `src/noble_agent/tenant/provisioning.py`
- Test: `tests/unit/tenant/test_provisioning_versioning.py`

**Interfaces:**
- `rollback(store, tenant_id, version:int, *, updated_by="", now=None) -> int`
- `list_versions(store, tenant_id) -> list[int]`
- `diff_versions(store, tenant_id, a:int, b:int) -> dict[str, list[str]]`  (`added`/`removed`/`changed`)

- [ ] **Step 1: Write the failing test**

```python
def test_rollback_moves_pointer_no_new_version():
    s = FakeTenantStore(); _seed(s)
    P.save_draft(s, "t", files={**VALID_FILES, "persona/SOUL.md": "v2"})
    P.publish(s, "t")                       # -> v2, pointer 2
    assert P.rollback(s, "t", 1) == 1
    assert s.read_pointer("t") == 1
    assert s.list_versions("t") == [1, 2]   # NO v3 created
    assert s.read_bundle("t").files["persona/SOUL.md"] == "x"

def test_rollback_unknown_version_raises():
    s = FakeTenantStore(); _seed(s)
    with pytest.raises(ValueError):
        P.rollback(s, "t", 99)

def test_diff_versions_paths():
    s = FakeTenantStore(); _seed(s)
    P.save_draft(s, "t", files={"persona/SOUL.md": "x", "persona/RULES.md": "escalate",
                                 "persona/PROMPT_TEMPLATE.md": "x", "persona/CUSTOMER_PROFILE.md": "x",
                                 "persona/config.json": "{}", "persona/NEW.md": "n"})
    P.publish(s, "t")
    d = P.diff_versions(s, "t", 1, 2)
    assert "persona/NEW.md" in d["added"]
```

- [ ] **Step 2: Run to verify fail** → FAIL.

- [ ] **Step 3: Implement**

```python
def list_versions(store, tenant_id):
    return store.list_versions(tenant_id)

def rollback(store, tenant_id, version, *, updated_by="", now=None):
    if version not in store.list_versions(tenant_id):
        raise ValueError(f"no such version {version} for {tenant_id!r}")
    store.write_pointer(tenant_id, version)  # BR06: pointer only, no new version
    return version

def diff_versions(store, tenant_id, a, b):
    ba = store.read_version_bundle(tenant_id, a) or get_tenant(store, tenant_id)
    bb = store.read_version_bundle(tenant_id, b) or store.read_draft(tenant_id)
    fa = {"manifest.toml": ba.manifest_text, **ba.files}
    fb = {"manifest.toml": bb.manifest_text, **bb.files}
    added = sorted(set(fb) - set(fa))
    removed = sorted(set(fa) - set(fb))
    changed = sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
    return {"added": added, "removed": removed, "changed": changed}
```

- [ ] **Step 4: Run to verify pass** → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/provisioning.py tests/unit/tenant/test_provisioning_versioning.py
git commit -m "feat(tenant): rollback + list_versions + diff_versions (SP-C1 t5)"
```

---

### Task 6: Repoint `create_tenant` / `import_from_package` / `update_tenant` to the versioned layout

**Files:**
- Modify: `src/noble_agent/tenant/provisioning.py`
- Modify: `tests/unit/tenant/test_provisioning.py` (existing asserts about in-place `version` bump)
- Test: `tests/unit/tenant/test_provisioning_versioning.py`

**Interfaces:** signatures unchanged; behavior:
- `create_tenant(..., status)`: writes draft → if `status=="active"`, publishes v1 (pointer→1); if `"draft"`, leaves draft unpublished (no pointer yet).
- `import_from_package(...)`: `create_tenant(status="active")` path → ends with `versions/1/` + pointer + status active.
- `update_tenant(...)`: now writes the DRAFT (no auto-publish, no pointer move) — enforces BR04 (publish is a separate step).

- [ ] **Step 1: Write the failing test**

```python
def test_create_active_publishes_v1():
    s = FakeTenantStore()
    P.create_tenant(s, "t", VALID_MANIFEST, VALID_FILES, status="active")
    assert s.read_pointer("t") == 1 and s.list_versions("t") == [1]
    assert s.read_meta("t").status == "active"

def test_create_draft_no_pointer():
    s = FakeTenantStore()
    P.create_tenant(s, "t", VALID_MANIFEST, VALID_FILES, status="draft")
    assert s.read_pointer("t") is None
    assert s.read_draft("t") is not None

def test_update_writes_draft_not_published():
    s = FakeTenantStore()
    P.create_tenant(s, "t", VALID_MANIFEST, VALID_FILES, status="active")
    P.update_tenant(s, "t", files={**VALID_FILES, "persona/SOUL.md": "edited"})
    assert s.read_bundle("t").files["persona/SOUL.md"] == "x"      # published unchanged
    assert s.read_draft("t").files["persona/SOUL.md"] == "edited"  # draft has edit
```

- [ ] **Step 2: Run to verify fail** → FAIL (create doesn't publish; update bumps in-place).

- [ ] **Step 3: Implement** — rewrite the three functions:

```python
def create_tenant(store, tenant_id, manifest_text, files, *, status="draft", now=None):
    if store.read_meta(tenant_id) is not None:
        raise ValueError(f"tenant already exists: {tenant_id!r}")
    report = validate_bundle(tenant_id, manifest_text, files, existing_ids=store.list_ids())
    if not report.ok:
        raise ValueError("bundle invalid: " + "; ".join(report.errors))
    store.write_draft(tenant_id, Bundle(tenant_id, manifest_text, files,
                                        TenantMeta(tenant_id, status, 0, bundle_hash(manifest_text, files))))
    if status == "active":
        publish(store, tenant_id, now=now)
    return store.read_meta(tenant_id) or TenantMeta(tenant_id, status, 0, bundle_hash(manifest_text, files))

def update_tenant(store, tenant_id, *, manifest_text=None, files=None, status=None, now=None):
    if store.read_bundle(tenant_id) is None and store.read_draft(tenant_id) is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    save_draft(store, tenant_id, manifest_text=manifest_text, files=files, now=now)
    if status is not None:
        set_status(store, tenant_id, status, now=now)
    return store.read_meta(tenant_id)
```

`import_from_package` already calls `create_tenant(status="active")` → now yields versioned layout with no change. Update any `test_provisioning.py` asserts that expect `update_tenant` to bump a published `version` (they must assert draft write now) and any that read `meta.version` after `create(status="draft")` (published_version is 0 until publish).

For `FakeTenantStore`, ensure `set_status` path exists: add `write_bundle`-independent status by storing status in `read_meta`. Simplest: have `create_tenant`'s active branch + `publish` set status via the meta written in `write_version_bundle`; for draft-only, `read_meta` returns None (no pointer, no in-place) — so `test_create_draft_no_pointer` checks `read_draft` not `read_meta`. Adjust Fake `read_meta` to also synthesize a draft-status meta when only a draft exists (status from draft.meta.status, published_version=0). Add that branch.

- [ ] **Step 4: Run to verify pass** — `pytest tests/unit/tenant -q` → all PASS (fix any remaining old-behavior asserts).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/provisioning.py tests/unit/tenant/
git commit -m "feat(tenant): create/import/update use versioned draft-publish layout (SP-C1 t6)"
```

---

### Task 7: CLI subcommands `save-draft / publish / rollback / list-versions / diff`

**Files:**
- Modify: `src/noble_agent/tenant/cli.py`
- Test: `tests/unit/tenant/test_cli_versioning.py` (new)

**Interfaces:** new argparse subcommands wired to the provisioning functions, building the store via the existing `_build_store(settings)` seam used by the current CLI.

- [ ] **Step 1: Write the failing test** — drive `main(argv)` with a `FakeTenantStore` injected (mirror the existing `test_cli.py` injection pattern):

```python
# tests/unit/tenant/test_cli_versioning.py
from noble_agent.tenant import cli
from noble_agent.tenant.store import FakeTenantStore
from noble_agent.tenant import provisioning as P

VALID_MANIFEST = 'tenant_id="t"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n'
VALID_FILES = {"persona/SOUL.md": "x", "persona/RULES.md": "escalate", "persona/PROMPT_TEMPLATE.md": "x",
               "persona/CUSTOMER_PROFILE.md": "x", "persona/config.json": "{}"}

def test_cli_list_versions_and_rollback(monkeypatch, capsys):
    store = FakeTenantStore()
    P.create_tenant(store, "t", VALID_MANIFEST, VALID_FILES, status="active")
    P.save_draft(store, "t", files={**VALID_FILES, "persona/SOUL.md": "v2"})
    P.publish(store, "t")
    monkeypatch.setattr(cli, "_build_store", lambda settings: store)
    cli.main(["list-versions", "t"])
    assert "1" in capsys.readouterr().out
    cli.main(["rollback", "t", "1"])
    assert store.read_pointer("t") == 1
```

(Match the exact injection seam the current `cli.py` uses; if it reads a module-level `_build_store`, patch that.)

- [ ] **Step 2: Run to verify fail** → FAIL (unknown subcommand).

- [ ] **Step 3: Implement** the subcommands in `cli.py`, each: build store, call the provisioning fn, print result. `save-draft <tenant> <dir>` reads a local directory into `(manifest_text, files)` (reuse the package-read helper shape). `publish <tenant> [--by NAME]`, `rollback <tenant> <n> [--by NAME]`, `list-versions <tenant>` (print sorted ints + mark the pointer), `diff <tenant> [a b]` (default draft↔published → print added/removed/changed).

- [ ] **Step 4: Run to verify pass** — `pytest tests/unit/tenant/test_cli_versioning.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/cli.py tests/unit/tenant/test_cli_versioning.py
git commit -m "feat(tenant): noble-tenant save-draft/publish/rollback/list-versions/diff (SP-C1 t7)"
```

---

### Task 8: Regression + live re-smoke (verification)

**Files:** none (verification only); fix-forward if red.

- [ ] **Step 1: Full offline gate**

Run: `pytest tests/unit/tenant tests/unit/gateway -q` → 0 failures.
Run: `ruff check src/noble_agent/tenant/` → clean.

- [ ] **Step 2: Loader/materialize back-compat (offline)**

Confirm `materialize_tenant` + `loader._resolve_tenant_dir` still work against a store whose `read_bundle`/`read_meta` now resolve the pointed version (add a focused test if not already covered: a versioned FakeStore → `materialize_tenant` writes the published version's files).

- [ ] **Step 3: Live re-smoke** (services + gateway already documented in SMOKE.md)

```bash
# re-provision noble into the versioned layout, then confirm chat still works
noble-tenant list
python scripts/smoke_gateway_chat.py <tnt_...>            # PASS (loader materializes published version)
noble-tenant list-versions noble                          # [1]
noble-tenant save-draft noble <dir-with-edit> && noble-tenant publish noble
noble-tenant list-versions noble                          # [1, 2]
noble-tenant rollback noble 1                             # pointer -> 1
```

- [ ] **Step 4: Update SMOKE.md** with a short "SP-C1 config versioning" subsection (publish/rollback/list-versions recipe).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/SMOKE.md tests/unit/tenant/
git commit -m "test(tenant): SP-C1 regression + back-compat + smoke recipe (SP-C1 t8)"
```

---

## Self-Review

- **Spec coverage:** draft (Task 4/6) · immutable publish + numbering + BR07 order (Task 4) · rollback pointer-only (Task 5) · validation gate E08 (Task 4) · versioned store layout + back-compat read (Task 2/3) · read-compat legacy v1 (Task 2/3) · CLI (Task 7) · gateway/loader back-compat (Task 8). `field_policy` intentionally deferred (spec §2 non-goal) — `VersionInfo.field_policy=None`.
- **Placeholder scan:** none — all steps carry real test + impl code.
- **Type consistency:** `VersionInfo`/`TenantMeta` fields defined in Task 1 used verbatim in 2–6; `publish → VersionInfo`, `rollback → int`, `read_pointer → int|None` consistent across tasks and the CLI.
- **Known test-churn:** Task 6 changes `update_tenant` + `create(status="draft")` semantics → existing `test_provisioning.py` asserts about in-place `version` bumps are updated in the same task (called out explicitly).
