# SaaS Slice #1 — Externalize Tenant Store + Provisioning Contract — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a tenant bundle a mutable MinIO-stored artifact that a process materializes to a local dir at boot (store-first, in-wheel fallback), plus a library + `noble-tenant` CLI to provision (create/update/disable/validate) tenants.

**Architecture:** A new `noble_agent.tenant` sub-package gains a store abstraction (`TenantStore` Protocol + `MinioTenantStore` over boto3 + `FakeTenantStore` for tests), a pure validator, an idempotent materializer, a provisioning library, and a CLI. `tenant/loader.py` gains a store-first resolution branch that materializes an active tenant's bundle and imports its custom tools by file-path; everything stays byte-identical when `TENANT_STORE_ENABLED=false` (default).

**Tech Stack:** Python 3.11+, `boto3` (already a dependency, `>=1.40`), `tomllib` (stdlib), `ast`/`compile` (stdlib), pydantic-settings, pytest (`asyncio_mode=auto`).

## Global Constraints

- **Branch:** work on `feat/refactor2`. NEVER touch `develop` (no checkout/merge/push/fetch). Local commits on the feature branch only.
- **Backward compatible:** `TENANT_STORE_ENABLED=false` (default) → behavior byte-identical to today; the existing ~1450 unit tests stay green and need NO MinIO. `noble` / `demo_acme` keep loading from the in-wheel package.
- **Secrets:** `MINIO_ROOT_PASSWORD` lives only in the gitignored `.env`. Never hardcode it; `.env.example` carries a placeholder only.
- **No new dependency:** use the already-present `boto3>=1.40`. Import it lazily (function/method-local) so `make test-unit` collects without contacting MinIO.
- **Bucket:** `hotline-tenants`. **Store layout:** `s3://<bucket>/<tenant_id>/{_meta.json, manifest.toml, persona/*, tools/*}`.
- **tenant_id slug:** `^[a-z0-9][a-z0-9_-]{1,62}$`.
- **Validation MUST NOT import/execute tenant tool code** — static AST + `compile()` only. (Execution happens only at boot on the admin-trusted loader path.)
- **Ruff:** line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make lint` before each commit touching source.
- **Tests dir:** `tests/unit/tenant/`. Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

**New:**
- `src/noble_agent/tenant/store.py` — bundle models (`TenantMeta`, `Bundle`), `bundle_hash()`, `TenantStore` Protocol, `FakeTenantStore` (in-memory), `MinioTenantStore` (boto3).
- `src/noble_agent/tenant/validation.py` — `parse_manifest()`, `tool_names_declared()`, `validate_bundle()` → `ValidationReport`.
- `src/noble_agent/tenant/materialize.py` — `materialize_tenant()` (idempotent, atomic swap).
- `src/noble_agent/tenant/provisioning.py` — `create_tenant`/`update_tenant`/`set_status`/`disable_tenant`/`list_tenants`/`get_tenant`/`import_from_package`.
- `src/noble_agent/tenant/cli.py` — `noble-tenant` argparse entrypoint `main()`.
- `tests/unit/tenant/test_store.py`, `test_validation.py`, `test_materialize.py`, `test_provisioning.py`, `test_loader_store.py`, `test_cli.py`.

**Modify:**
- `src/noble_agent/config.py` — 6 new settings.
- `src/noble_agent/tenant/loader.py` — store-first resolution + materialized tool import.
- `pyproject.toml` — `noble-tenant` console script.
- `.env.example` — document the 6 settings.

---

## Task 1: Config settings + `.env.example`

**Files:**
- Modify: `src/noble_agent/config.py` (add 6 fields near `tenant_id`, ~line 82)
- Modify: `.env.example`
- Test: `tests/unit/tenant/test_store.py` (first test only; file grows in Task 2)

**Interfaces:**
- Produces: `settings.tenant_store_enabled: bool`, `settings.minio_endpoint: str`, `settings.minio_root_user: str`, `settings.minio_root_password: str`, `settings.tenant_bucket: str` (default `"hotline-tenants"`), `settings.tenant_materialize_dir: str` (default `"/var/lib/noble/tenants"`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/tenant/test_store.py`:
```python
from noble_agent.config import UnifiedSettings


def test_tenant_store_settings_defaults():
    s = UnifiedSettings(_env_file=None)
    assert s.tenant_store_enabled is False
    assert s.tenant_bucket == "hotline-tenants"
    assert s.tenant_materialize_dir == "/var/lib/noble/tenants"
    assert s.minio_endpoint == ""
    assert s.minio_root_user == ""
    assert s.minio_root_password == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_store.py::test_tenant_store_settings_defaults -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'tenant_store_enabled'`.

- [ ] **Step 3: Add the settings**

In `src/noble_agent/config.py`, immediately after the `tenant_id: str = "noble"` line, add:
```python
    # ── multi-tenant store (SaaS slice #1) ─────────────────────────────────────
    tenant_store_enabled: bool = Field(False, alias="TENANT_STORE_ENABLED")
    minio_endpoint: str = Field("", alias="MINIO_ENDPOINT")
    minio_root_user: str = Field("", alias="MINIO_ROOT_USER")
    minio_root_password: str = Field("", alias="MINIO_ROOT_PASSWORD")
    tenant_bucket: str = Field("hotline-tenants", alias="TENANT_BUCKET")
    tenant_materialize_dir: str = Field("/var/lib/noble/tenants", alias="TENANT_MATERIALIZE_DIR")
```
(If `Field` is not already imported at the top of `config.py`, it is — the file already uses `Field(...)` widely.)

- [ ] **Step 4: Document in `.env.example`**

Append to `.env.example`:
```bash
# ── Multi-tenant store (SaaS slice #1) ──────────────────────────────────────
# Master flag. false (default) = pure in-wheel tenants (offline, unchanged).
TENANT_STORE_ENABLED=false
# MinIO / S3-compatible object store holding tenant bundles.
MINIO_ENDPOINT=http://10.50.13.220:9000
MINIO_ROOT_USER=santa_minio_admin
MINIO_ROOT_PASSWORD=changeme
TENANT_BUCKET=hotline-tenants
# Local dir tenant bundles are synced into at boot.
TENANT_MATERIALIZE_DIR=/var/lib/noble/tenants
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/tenant/test_store.py::test_tenant_store_settings_defaults -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add src/noble_agent/config.py .env.example tests/unit/tenant/test_store.py
git commit -m "feat(tenant): add MinIO tenant-store settings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Bundle models + hash + Protocol + FakeTenantStore

**Files:**
- Create: `src/noble_agent/tenant/store.py`
- Test: `tests/unit/tenant/test_store.py`

**Interfaces:**
- Produces:
  - `TenantMeta(tenant_id: str, status: str, version: int, bundle_hash: str, created_at: str = "", updated_at: str = "")` — frozen dataclass.
  - `Bundle(tenant_id: str, manifest_text: str, files: dict[str, str], meta: TenantMeta)` — frozen dataclass. `files` maps a bundle-relative path (e.g. `"persona/SOUL.md"`, `"tools/loan.py"`) → UTF-8 text; it EXCLUDES `manifest.toml` and `_meta.json`.
  - `bundle_hash(manifest_text: str, files: dict[str, str]) -> str` — deterministic `"sha256:<hex>"`.
  - `TenantStore` Protocol: `read_meta(tenant_id) -> TenantMeta | None`, `list_ids() -> list[str]`, `read_bundle(tenant_id) -> Bundle | None`, `write_bundle(bundle: Bundle) -> None`.
  - `FakeTenantStore()` — in-memory `TenantStore` for tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/tenant/test_store.py`:
```python
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, bundle_hash


def _meta(h="sha256:x"):
    return TenantMeta(tenant_id="acme", status="active", version=1, bundle_hash=h)


def test_bundle_hash_is_deterministic_and_order_independent():
    a = bundle_hash("m=1", {"persona/SOUL.md": "s", "tools/x.py": "x"})
    b = bundle_hash("m=1", {"tools/x.py": "x", "persona/SOUL.md": "s"})
    assert a == b and a.startswith("sha256:")


def test_bundle_hash_changes_with_content():
    assert bundle_hash("m=1", {"a": "1"}) != bundle_hash("m=1", {"a": "2"})
    assert bundle_hash("m=1", {"a": "1"}) != bundle_hash("m=2", {"a": "1"})


def test_fake_store_roundtrip():
    store = FakeTenantStore()
    assert store.read_meta("acme") is None
    assert store.list_ids() == []
    b = Bundle("acme", "data_source='nbx'", {"persona/SOUL.md": "s"}, _meta())
    store.write_bundle(b)
    assert store.list_ids() == ["acme"]
    assert store.read_meta("acme").status == "active"
    got = store.read_bundle("acme")
    assert got.manifest_text == "data_source='nbx'"
    assert got.files == {"persona/SOUL.md": "s"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` for the new names.

- [ ] **Step 3: Implement `store.py` (models + hash + fake)**

Create `src/noble_agent/tenant/store.py`:
```python
"""Tenant bundle models + store abstraction (SaaS slice #1).

A bundle = manifest.toml + persona/* + optional tools/*, stored under an
S3/MinIO prefix ``<tenant_id>/`` with a sibling ``_meta.json`` carrying
orchestration metadata (status/version/bundle_hash).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_MANIFEST = "manifest.toml"
_META = "_meta.json"


@dataclass(frozen=True)
class TenantMeta:
    tenant_id: str
    status: str          # "active" | "draft" | "disabled"
    version: int
    bundle_hash: str
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Bundle:
    tenant_id: str
    manifest_text: str
    files: dict[str, str]   # rel path -> UTF-8 text; excludes manifest.toml & _meta.json
    meta: TenantMeta


def bundle_hash(manifest_text: str, files: dict[str, str]) -> str:
    """Deterministic content hash over manifest + files (path-sorted)."""
    h = hashlib.sha256()
    items = sorted([(_MANIFEST, manifest_text), *files.items()])
    for path, content in items:
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(content.encode("utf-8"))
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


@runtime_checkable
class TenantStore(Protocol):
    def read_meta(self, tenant_id: str) -> TenantMeta | None: ...
    def list_ids(self) -> list[str]: ...
    def read_bundle(self, tenant_id: str) -> Bundle | None: ...
    def write_bundle(self, bundle: Bundle) -> None: ...


class FakeTenantStore:
    """In-memory TenantStore for tests."""

    def __init__(self) -> None:
        self._bundles: dict[str, Bundle] = {}

    def read_meta(self, tenant_id: str) -> TenantMeta | None:
        b = self._bundles.get(tenant_id)
        return b.meta if b else None

    def list_ids(self) -> list[str]:
        return sorted(self._bundles)

    def read_bundle(self, tenant_id: str) -> Bundle | None:
        return self._bundles.get(tenant_id)

    def write_bundle(self, bundle: Bundle) -> None:
        self._bundles[bundle.tenant_id] = bundle
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_store.py -v`
Expected: PASS (all 4 tests + Task 1's settings test).

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/tenant/store.py tests/unit/tenant/test_store.py
git commit -m "feat(tenant): bundle models, content hash, TenantStore + fake

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `MinioTenantStore` (boto3, injectable client)

**Files:**
- Modify: `src/noble_agent/tenant/store.py`
- Test: `tests/unit/tenant/test_store.py`

**Interfaces:**
- Consumes: `TenantMeta`, `Bundle`, settings from Task 1.
- Produces:
  - `MinioTenantStore(client, bucket: str)` implementing `TenantStore`, plus `write_bundle` (puts `manifest.toml`, each file, and `_meta.json`).
  - `MinioTenantStore.from_settings(settings) -> MinioTenantStore` — lazy `import boto3`, builds an S3 client with `endpoint_url=settings.minio_endpoint`.
- The injected `client` must expose the boto3 S3 methods used: `put_object(Bucket, Key, Body)`, `get_object(Bucket, Key)` (returns `{"Body": <stream with .read()>}`), `list_objects_v2(Bucket, Prefix, Delimiter=...)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/tenant/test_store.py`:
```python
import io
import json

from noble_agent.tenant.store import MinioTenantStore


class _FakeS3:
    """Minimal in-memory stand-in for the boto3 S3 client surface we use."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}  # key -> body

    def put_object(self, Bucket, Key, Body):  # noqa: N803 (boto3 kwarg names)
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
        contents = [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)]
        return {"Contents": contents}


def test_minio_store_write_then_read(monkeypatch):
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    b = Bundle("acme", "data_source='nbx'",
               {"persona/SOUL.md": "s", "tools/loan.py": "x"}, _meta("sha256:h1"))
    store.write_bundle(b)
    # _meta.json + manifest.toml + 2 files persisted under the acme/ prefix.
    assert json.loads(s3.objects["acme/_meta.json"])["bundle_hash"] == "sha256:h1"
    assert s3.objects["acme/manifest.toml"] == b"data_source='nbx'"
    got = store.read_bundle("acme")
    assert got.manifest_text == "data_source='nbx'"
    assert got.files == {"persona/SOUL.md": "s", "tools/loan.py": "x"}
    assert store.read_meta("acme").bundle_hash == "sha256:h1"


def test_minio_store_list_ids():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle("acme", "m", {}, _meta()))
    store.write_bundle(Bundle("globex", "m", {}, _meta()))
    assert store.list_ids() == ["acme", "globex"]


def test_minio_store_read_missing_is_none():
    store = MinioTenantStore(_FakeS3(), "hotline-tenants")
    assert store.read_meta("nope") is None
    assert store.read_bundle("nope") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_store.py -k minio -v`
Expected: FAIL — `ImportError: cannot import name 'MinioTenantStore'`.

- [ ] **Step 3: Implement `MinioTenantStore`**

Append to `src/noble_agent/tenant/store.py` (add `import json` at the top with the stdlib imports):
```python
class MinioTenantStore:
    """TenantStore backed by an S3/MinIO client (injected for tests)."""

    def __init__(self, client, bucket: str) -> None:
        self._c = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings) -> "MinioTenantStore":
        import boto3  # lazy: keep test collection offline

        client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
        )
        return cls(client, settings.tenant_bucket)

    # -- reads -------------------------------------------------------------
    def _get_text(self, key: str) -> str | None:
        try:
            resp = self._c.get_object(Bucket=self._bucket, Key=key)
        except Exception:
            return None
        return resp["Body"].read().decode("utf-8")

    def read_meta(self, tenant_id: str) -> TenantMeta | None:
        raw = self._get_text(f"{tenant_id}/{_META}")
        if raw is None:
            return None
        d = json.loads(raw)
        return TenantMeta(
            tenant_id=d.get("tenant_id", tenant_id),
            status=d["status"],
            version=int(d["version"]),
            bundle_hash=d["bundle_hash"],
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )

    def list_ids(self) -> list[str]:
        resp = self._c.list_objects_v2(Bucket=self._bucket, Prefix="", Delimiter="/")
        return sorted(p["Prefix"].rstrip("/") for p in resp.get("CommonPrefixes", []))

    def read_bundle(self, tenant_id: str) -> Bundle | None:
        meta = self.read_meta(tenant_id)
        if meta is None:
            return None
        manifest = self._get_text(f"{tenant_id}/{_MANIFEST}") or ""
        prefix = f"{tenant_id}/"
        listing = self._c.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        files: dict[str, str] = {}
        for obj in listing.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix):]
            if rel in (_META, _MANIFEST) or not rel:
                continue
            text = self._get_text(key)
            if text is not None:
                files[rel] = text
        return Bundle(tenant_id, manifest, files, meta)

    # -- writes ------------------------------------------------------------
    def write_bundle(self, bundle: Bundle) -> None:
        base = f"{bundle.tenant_id}/"
        self._c.put_object(Bucket=self._bucket, Key=base + _MANIFEST,
                           Body=bundle.manifest_text.encode("utf-8"))
        for rel, content in bundle.files.items():
            self._c.put_object(Bucket=self._bucket, Key=base + rel,
                               Body=content.encode("utf-8"))
        meta = bundle.meta
        meta_doc = {
            "tenant_id": meta.tenant_id, "status": meta.status,
            "version": meta.version, "bundle_hash": meta.bundle_hash,
            "created_at": meta.created_at, "updated_at": meta.updated_at,
        }
        self._c.put_object(Bucket=self._bucket, Key=base + _META,
                           Body=json.dumps(meta_doc).encode("utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_store.py -v`
Expected: PASS (all store tests).

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/tenant/store.py tests/unit/tenant/test_store.py
git commit -m "feat(tenant): MinioTenantStore over boto3 (injectable client)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Bundle validation (`validation.py`)

**Files:**
- Create: `src/noble_agent/tenant/validation.py`
- Test: `tests/unit/tenant/test_validation.py`

**Interfaces:**
- Consumes: `noble_agent.agent.tools.registry.resolve`.
- Produces:
  - `parse_manifest(text: str) -> dict` — raises `ValueError` on bad TOML or missing required keys (`data_source`, `persona_dir`, `[tools].enabled`).
  - `tool_names_declared(py_src: str) -> set[str]` — static AST scan for `@tool(name="…")` decorator calls; `set()` on syntax error.
  - `SLUG_RE` (compiled), `REQUIRED_PERSONA_FILES` (tuple).
  - `ValidationReport(errors: list[str], warnings: list[str])` with `.ok` property.
  - `validate_bundle(tenant_id, manifest_text, files, *, existing_ids=()) -> ValidationReport`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/tenant/test_validation.py`:
```python
from noble_agent.tenant.validation import (
    parse_manifest,
    tool_names_declared,
    validate_bundle,
)

_GOOD_MANIFEST = """\
tenant_id = "acme"
data_source = "nbx"
persona_dir = "persona"
[tools]
enabled = ["kb_search", "check_loan"]
"""

_PERSONA = {
    "persona/config.json": '{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}',
    "persona/SOUL.md": "soul",
    "persona/RULES.md": "rules",
    "persona/PROMPT_TEMPLATE.md": "tmpl",
    "persona/CUSTOMER_PROFILE.md": "cust",
}

_LOAN_TOOL = '''\
from noble_agent.agent.tools.registry import tool
@tool(name="check_loan", schema={}, tenant="acme")
async def check_loan(args, *, provider, tenant, **_):
    return "ok"
'''


def test_parse_manifest_ok():
    d = parse_manifest(_GOOD_MANIFEST)
    assert d["data_source"] == "nbx"
    assert d["tools"]["enabled"] == ["kb_search", "check_loan"]


def test_parse_manifest_bad_toml_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_manifest("this is = = not toml")


def test_parse_manifest_missing_key_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_manifest('data_source = "nbx"\npersona_dir = "persona"\n')


def test_tool_names_declared_extracts_without_executing():
    assert tool_names_declared(_LOAN_TOOL) == {"check_loan"}


def test_tool_names_declared_syntax_error_returns_empty():
    assert tool_names_declared("def broken(:\n") == set()


def test_validate_good_bundle_passes():
    files = {**_PERSONA, "tools/loan.py": _LOAN_TOOL}
    r = validate_bundle("acme", _GOOD_MANIFEST, files)
    assert r.ok, r.errors


def test_validate_rejects_bad_slug():
    r = validate_bundle("Bad Slug!", _GOOD_MANIFEST, {**_PERSONA, "tools/loan.py": _LOAN_TOOL})
    assert not r.ok
    assert any("slug" in e.lower() for e in r.errors)


def test_validate_rejects_duplicate_id():
    files = {**_PERSONA, "tools/loan.py": _LOAN_TOOL}
    r = validate_bundle("acme", _GOOD_MANIFEST, files, existing_ids=("acme",))
    assert not r.ok
    assert any("exist" in e.lower() for e in r.errors)


def test_validate_rejects_unresolvable_enabled_tool():
    m = _GOOD_MANIFEST.replace('"check_loan"', '"nonexistent_tool"')
    r = validate_bundle("acme", m, dict(_PERSONA))  # no tools/ providing it
    assert not r.ok
    assert any("nonexistent_tool" in e for e in r.errors)


def test_validate_rejects_missing_persona_file():
    files = {k: v for k, v in _PERSONA.items() if k != "persona/SOUL.md"}
    files["tools/loan.py"] = _LOAN_TOOL
    r = validate_bundle("acme", _GOOD_MANIFEST, files)
    assert not r.ok
    assert any("SOUL.md" in e for e in r.errors)


def test_validate_rejects_tool_syntax_error():
    files = {**_PERSONA, "tools/loan.py": "def broken(:\n"}
    m = _GOOD_MANIFEST.replace('"check_loan"', '"kb_search"')  # keep enabled resolvable
    r = validate_bundle("acme", m, files)
    assert not r.ok
    assert any("syntax" in e.lower() or "compile" in e.lower() for e in r.errors)


def test_validate_warns_on_non_allowlisted_import():
    tool_src = _LOAN_TOOL + "\nimport os\n"
    files = {**_PERSONA, "tools/loan.py": tool_src}
    r = validate_bundle("acme", _GOOD_MANIFEST, files)
    assert r.ok  # a warning, not an error
    assert any("os" in w for w in r.warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_validation.py -v`
Expected: FAIL — module/name import errors.

- [ ] **Step 3: Implement `validation.py`**

Create `src/noble_agent/tenant/validation.py`:
```python
"""Static tenant-bundle validation (SaaS slice #1).

Pure + side-effect-free: parses the manifest, checks persona presence, checks
every enabled tool resolves (built-in OR declared by a bundle tools/*.py via a
STATIC ast scan), and compiles custom tool files. It MUST NOT import/execute
tenant code — execution happens only at boot on the trusted loader path.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from dataclasses import dataclass, field

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
REQUIRED_PERSONA_FILES = ("config.json", "SOUL.md", "RULES.md", "PROMPT_TEMPLATE.md", "CUSTOMER_PROFILE.md")
_IMPORT_ALLOWLIST = ("noble_agent", "typing", "datetime", "json", "math", "re", "decimal", "collections", "dataclasses")
_REQUIRED_MANIFEST_KEYS = ("data_source", "persona_dir")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_manifest(text: str) -> dict:
    """Parse + minimally validate a manifest. Raises ValueError on any problem."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"manifest is not valid TOML: {e}") from e
    missing = [k for k in _REQUIRED_MANIFEST_KEYS if not data.get(k)]
    if not (data.get("tools") or {}).get("enabled"):
        missing.append("tools.enabled")
    if missing:
        raise ValueError(f"manifest missing required key(s): {', '.join(missing)}")
    return data


def tool_names_declared(py_src: str) -> set[str]:
    """Names declared by @tool(name="…") decorators, via a STATIC ast scan."""
    try:
        tree = ast.parse(py_src)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            is_tool = (isinstance(fn, ast.Name) and fn.id == "tool") or (
                isinstance(fn, ast.Attribute) and fn.attr == "tool"
            )
            if not is_tool:
                continue
            for kw in dec.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    names.add(str(kw.value.value))
    return names


def _imported_top_modules(py_src: str) -> set[str]:
    try:
        tree = ast.parse(py_src)
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def validate_bundle(tenant_id, manifest_text, files, *, existing_ids=()) -> ValidationReport:
    from noble_agent.agent.tools import builtins as _builtins  # ensure built-ins registered
    from noble_agent.agent.tools.registry import resolve

    _ = _builtins  # imported for its registration side effect
    report = ValidationReport()

    if not SLUG_RE.match(tenant_id or ""):
        report.errors.append(f"tenant_id is not a valid slug: {tenant_id!r}")
    if tenant_id in tuple(existing_ids):
        report.errors.append(f"tenant already exists: {tenant_id!r}")

    try:
        manifest = parse_manifest(manifest_text)
    except ValueError as e:
        report.errors.append(str(e))
        return report  # can't proceed without a manifest

    persona_dir = str(manifest.get("persona_dir") or "persona").strip("/")
    for fname in REQUIRED_PERSONA_FILES:
        key = f"{persona_dir}/{fname}"
        if key not in files:
            report.errors.append(f"missing persona file: {key}")
    cfg_key = f"{persona_dir}/config.json"
    if cfg_key in files:
        try:
            json.loads(files[cfg_key])
        except ValueError:
            report.errors.append(f"{cfg_key} is not valid JSON")

    # Custom tool files: compile + collect declared names + import warnings.
    declared: set[str] = set()
    for rel, src in files.items():
        if not (rel.startswith("tools/") and rel.endswith(".py")):
            continue
        try:
            compile(src, rel, "exec")
        except SyntaxError as e:
            report.errors.append(f"{rel} fails to compile (syntax error): {e}")
            continue
        declared |= tool_names_declared(src)
        for mod in _imported_top_modules(src):
            if mod not in _IMPORT_ALLOWLIST:
                report.warnings.append(f"{rel} imports non-allowlisted module '{mod}' (review for slice #3 sandbox)")

    enabled = (manifest.get("tools") or {}).get("enabled") or []
    for name in enabled:
        if resolve("*", name) is not None or name in declared:
            continue
        report.errors.append(f"enabled tool '{name}' resolves to neither a built-in nor a bundle tool")

    return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_validation.py -v`
Expected: PASS (all 13 tests).

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/tenant/validation.py tests/unit/tenant/test_validation.py
git commit -m "feat(tenant): static bundle validation (manifest/persona/tools)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Materializer (`materialize.py`)

**Files:**
- Create: `src/noble_agent/tenant/materialize.py`
- Test: `tests/unit/tenant/test_materialize.py`

**Interfaces:**
- Consumes: `TenantStore`, `Bundle`, `TenantMeta` (Task 2).
- Produces: `materialize_tenant(store, tenant_id: str, dest_root) -> Path` — writes `<dest_root>/<tenant_id>/{manifest.toml, <files…>, .bundle_hash}`; idempotent (skips when the on-disk `.bundle_hash` marker equals `meta.bundle_hash`); atomic (temp dir + rename swap); raises `FileNotFoundError` when the tenant is absent from the store.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/tenant/test_materialize.py`:
```python
from pathlib import Path

import pytest

from noble_agent.tenant.materialize import materialize_tenant
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, bundle_hash


def _bundle(tid="acme", soul="soul"):
    files = {"persona/SOUL.md": soul, "tools/loan.py": "x"}
    manifest = "data_source='nbx'"
    h = bundle_hash(manifest, files)
    meta = TenantMeta(tid, "active", 1, h)
    return Bundle(tid, manifest, files, meta)


def test_materialize_writes_tree(tmp_path):
    store = FakeTenantStore()
    store.write_bundle(_bundle())
    dest = materialize_tenant(store, "acme", tmp_path)
    assert dest == tmp_path / "acme"
    assert (dest / "manifest.toml").read_text() == "data_source='nbx'"
    assert (dest / "persona" / "SOUL.md").read_text() == "soul"
    assert (dest / "tools" / "loan.py").read_text() == "x"
    assert (dest / ".bundle_hash").read_text().strip().startswith("sha256:")


def test_materialize_is_idempotent_and_skips_rewrite(tmp_path, monkeypatch):
    store = FakeTenantStore()
    store.write_bundle(_bundle())
    materialize_tenant(store, "acme", tmp_path)
    # Second call must NOT re-read the bundle (hash marker matches).
    def _boom(_):
        raise AssertionError("read_bundle should not be called when hash matches")
    monkeypatch.setattr(store, "read_bundle", _boom)
    dest = materialize_tenant(store, "acme", tmp_path)
    assert (dest / "persona" / "SOUL.md").read_text() == "soul"


def test_materialize_refreshes_on_hash_change(tmp_path):
    store = FakeTenantStore()
    store.write_bundle(_bundle(soul="v1"))
    materialize_tenant(store, "acme", tmp_path)
    store.write_bundle(_bundle(soul="v2"))  # new hash
    dest = materialize_tenant(store, "acme", tmp_path)
    assert (dest / "persona" / "SOUL.md").read_text() == "v2"


def test_materialize_missing_tenant_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        materialize_tenant(FakeTenantStore(), "ghost", tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_materialize.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.tenant.materialize`.

- [ ] **Step 3: Implement `materialize.py`**

Create `src/noble_agent/tenant/materialize.py`:
```python
"""Materialize a store bundle → a local dir (SaaS slice #1).

Idempotent by ``bundle_hash`` (skips the download when the on-disk marker
matches) and atomic (writes to a temp dir, then renames into place) so a
partial sync never leaves a half-written bundle the loader would read.
"""

from __future__ import annotations

import shutil
from pathlib import Path

_MARKER = ".bundle_hash"


def materialize_tenant(store, tenant_id: str, dest_root) -> Path:
    meta = store.read_meta(tenant_id)
    if meta is None:
        raise FileNotFoundError(f"tenant not in store: {tenant_id!r}")

    dest_root = Path(dest_root)
    dest = dest_root / tenant_id
    marker = dest / _MARKER
    if dest.is_dir() and marker.is_file() and marker.read_text(encoding="utf-8").strip() == meta.bundle_hash:
        return dest  # already up to date

    bundle = store.read_bundle(tenant_id)
    if bundle is None:
        raise FileNotFoundError(f"tenant not in store: {tenant_id!r}")

    tmp = dest_root / f".{tenant_id}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    (tmp / "manifest.toml").write_text(bundle.manifest_text, encoding="utf-8")
    for rel, content in bundle.files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (tmp / _MARKER).write_text(meta.bundle_hash, encoding="utf-8")

    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_materialize.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/tenant/materialize.py tests/unit/tenant/test_materialize.py
git commit -m "feat(tenant): idempotent atomic bundle materializer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Provisioning library (`provisioning.py`)

**Files:**
- Create: `src/noble_agent/tenant/provisioning.py`
- Test: `tests/unit/tenant/test_provisioning.py`

**Interfaces:**
- Consumes: `TenantStore`, `Bundle`, `TenantMeta`, `bundle_hash` (Task 2); `validate_bundle` (Task 4); `loader._tenants_root` (Task 7 leaves this untouched — it already exists).
- Produces (all take a `store: TenantStore` first arg; `now` is an injectable ISO timestamp defaulting to `datetime.now(UTC).isoformat()`):
  - `create_tenant(store, tenant_id, manifest_text, files, *, status="draft", now=None) -> TenantMeta` — raises `ValueError` if the tenant exists or validation fails.
  - `update_tenant(store, tenant_id, *, manifest_text=None, files=None, status=None, now=None) -> TenantMeta` — merges over the existing bundle, re-validates (skipping the uniqueness check), bumps `version`, recomputes hash.
  - `set_status(store, tenant_id, status, *, now=None) -> TenantMeta`; `disable_tenant(store, tenant_id, *, now=None) -> TenantMeta`.
  - `list_tenants(store) -> list[TenantMeta]`; `get_tenant(store, tenant_id) -> Bundle`.
  - `import_from_package(store, tenant_id, *, status="active", now=None) -> TenantMeta` — reads the in-wheel `tenants/<id>/` dir and creates it in the store.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/tenant/test_provisioning.py`:
```python
import pytest

from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.store import FakeTenantStore

_MANIFEST = """\
tenant_id = "acme"
data_source = "nbx"
persona_dir = "persona"
[tools]
enabled = ["kb_search"]
"""
_PERSONA = {
    "persona/config.json": '{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}',
    "persona/SOUL.md": "soul",
    "persona/RULES.md": "rules",
    "persona/PROMPT_TEMPLATE.md": "tmpl",
    "persona/CUSTOMER_PROFILE.md": "cust",
}
_NOW = "2026-07-29T00:00:00+00:00"


def test_create_then_get():
    store = FakeTenantStore()
    meta = prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), status="active", now=_NOW)
    assert meta.version == 1 and meta.status == "active"
    assert meta.created_at == _NOW
    b = prov.get_tenant(store, "acme")
    assert b.files["persona/SOUL.md"] == "soul"


def test_create_duplicate_raises():
    store = FakeTenantStore()
    prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), now=_NOW)
    with pytest.raises(ValueError):
        prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), now=_NOW)


def test_create_invalid_bundle_raises():
    store = FakeTenantStore()
    bad = {k: v for k, v in _PERSONA.items() if k != "persona/RULES.md"}
    with pytest.raises(ValueError):
        prov.create_tenant(store, "acme", _MANIFEST, bad, now=_NOW)


def test_update_bumps_version_and_hash():
    store = FakeTenantStore()
    m1 = prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), now=_NOW)
    files2 = {**_PERSONA, "persona/SOUL.md": "soul-v2"}
    m2 = prov.update_tenant(store, "acme", files=files2, now="2026-07-30T00:00:00+00:00")
    assert m2.version == 2
    assert m2.bundle_hash != m1.bundle_hash
    assert m2.created_at == _NOW  # preserved
    assert prov.get_tenant(store, "acme").files["persona/SOUL.md"] == "soul-v2"


def test_disable_and_list():
    store = FakeTenantStore()
    prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), status="active", now=_NOW)
    prov.disable_tenant(store, "acme", now=_NOW)
    metas = prov.list_tenants(store)
    assert len(metas) == 1 and metas[0].status == "disabled"


def test_import_from_package_seeds_noble():
    store = FakeTenantStore()
    meta = prov.import_from_package(store, "noble", now=_NOW)
    assert meta.status == "active"
    b = prov.get_tenant(store, "noble")
    assert "persona/SOUL.md" in b.files
    assert "manifest" in b.manifest_text or "tenant_id" in b.manifest_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_provisioning.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `provisioning.py`**

Create `src/noble_agent/tenant/provisioning.py`:
```python
"""Provisioning library — create/update/disable/list tenant bundles (slice #1).

Pure over an injected TenantStore. Validates before every write; never
executes tenant tool code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from noble_agent.tenant.store import Bundle, TenantMeta, bundle_hash
from noble_agent.tenant.validation import validate_bundle


def _now(now: str | None) -> str:
    return now or datetime.now(UTC).isoformat()


def create_tenant(store, tenant_id, manifest_text, files, *, status="draft", now=None) -> TenantMeta:
    if store.read_meta(tenant_id) is not None:
        raise ValueError(f"tenant already exists: {tenant_id!r}")
    report = validate_bundle(tenant_id, manifest_text, files, existing_ids=store.list_ids())
    if not report.ok:
        raise ValueError("bundle invalid: " + "; ".join(report.errors))
    ts = _now(now)
    meta = TenantMeta(tenant_id, status, 1, bundle_hash(manifest_text, files), created_at=ts, updated_at=ts)
    store.write_bundle(Bundle(tenant_id, manifest_text, files, meta))
    return meta


def update_tenant(store, tenant_id, *, manifest_text=None, files=None, status=None, now=None) -> TenantMeta:
    cur = store.read_bundle(tenant_id)
    if cur is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    new_manifest = manifest_text if manifest_text is not None else cur.manifest_text
    new_files = files if files is not None else cur.files
    report = validate_bundle(tenant_id, new_manifest, new_files)  # no uniqueness check on update
    if not report.ok:
        raise ValueError("bundle invalid: " + "; ".join(report.errors))
    meta = TenantMeta(
        tenant_id,
        status or cur.meta.status,
        cur.meta.version + 1,
        bundle_hash(new_manifest, new_files),
        created_at=cur.meta.created_at,
        updated_at=_now(now),
    )
    store.write_bundle(Bundle(tenant_id, new_manifest, new_files, meta))
    return meta


def set_status(store, tenant_id, status, *, now=None) -> TenantMeta:
    cur = store.read_bundle(tenant_id)
    if cur is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    meta = TenantMeta(
        tenant_id, status, cur.meta.version, cur.meta.bundle_hash,
        created_at=cur.meta.created_at, updated_at=_now(now),
    )
    store.write_bundle(Bundle(tenant_id, cur.manifest_text, cur.files, meta))
    return meta


def disable_tenant(store, tenant_id, *, now=None) -> TenantMeta:
    return set_status(store, tenant_id, "disabled", now=now)


def list_tenants(store) -> list[TenantMeta]:
    return [m for m in (store.read_meta(i) for i in store.list_ids()) if m is not None]


def get_tenant(store, tenant_id) -> Bundle:
    b = store.read_bundle(tenant_id)
    if b is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    return b


def _read_package_bundle(tenant_id: str) -> tuple[str, dict[str, str]]:
    from noble_agent.tenant.loader import _tenants_root

    root = _tenants_root() / tenant_id
    if not root.is_dir():
        raise ValueError(f"package tenant not found: {tenant_id!r}")
    manifest_text = (root / "manifest.toml").read_text(encoding="utf-8")
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in ("manifest.toml", "_meta.json") or rel.endswith(".pyc") or "__pycache__" in rel:
            continue
        files[rel] = path.read_text(encoding="utf-8")
    return manifest_text, files


def import_from_package(store, tenant_id, *, status="active", now=None) -> TenantMeta:
    manifest_text, files = _read_package_bundle(tenant_id)
    return create_tenant(store, tenant_id, manifest_text, files, status=status, now=now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_provisioning.py -v`
Expected: PASS (6 tests). Note: `import_from_package("noble")` reads the real in-wheel `noble` bundle — its enabled tools are all built-ins, so validation passes.

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/tenant/provisioning.py tests/unit/tenant/test_provisioning.py
git commit -m "feat(tenant): provisioning library (create/update/disable/import)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Loader store-first resolution + materialized tool import

**Files:**
- Modify: `src/noble_agent/tenant/loader.py`
- Test: `tests/unit/tenant/test_loader_store.py`

**Interfaces:**
- Consumes: `MinioTenantStore.from_settings` (Task 3), `materialize_tenant` (Task 5), existing `_tenants_root`, `_import_tenant_tools`.
- Produces:
  - `_resolve_tenant_dir(tenant_id, settings) -> tuple[Path, bool]` — returns `(dir, is_materialized)`; store-first when `settings.tenant_store_enabled` and an `active` tenant exists, else the in-wheel package dir (raises `FileNotFoundError` if neither).
  - `_import_tenant_tools_from_dir(tenant_id, tools_dir: Path) -> None` — imports each `tools/*.py` via `spec_from_file_location` so `@tool` self-registers.
  - `load_tenant(tenant_id, settings)` — unchanged signature; now uses `_resolve_tenant_dir` + the right tool-import path.
  - The existing `_import_tenant_tools(tenant_id)` (package import) is **unchanged** so the current `test_custom_tool_loading.py` stays green.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/tenant/test_loader_store.py`:
```python
from types import SimpleNamespace

import pytest

from noble_agent.agent.tools import registry as reg
from noble_agent.tenant import loader
from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.store import FakeTenantStore

_MANIFEST = """\
tenant_id = "acme"
data_source = "nbx"
persona_dir = "persona"
[tools]
enabled = ["kb_search", "check_loan"]
"""
_CONFIG = '{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}'
_TOOL = '''\
from noble_agent.agent.tools.registry import tool
@tool(name="check_loan", schema={"type":"function","function":{"name":"check_loan","description":"d","parameters":{"type":"object","properties":{}}}}, tenant="acme")
async def check_loan(args, *, provider, tenant, **_):
    return "ok"
'''


def _seed(store):
    files = {
        "persona/config.json": _CONFIG,
        "persona/SOUL.md": "soul",
        "persona/RULES.md": "rules",
        "persona/PROMPT_TEMPLATE.md": "tmpl",
        "persona/CUSTOMER_PROFILE.md": "cust",
        "tools/loan.py": _TOOL,
    }
    prov.create_tenant(store, "acme", _MANIFEST, files, status="active", now="2026-07-29T00:00:00+00:00")


@pytest.fixture(autouse=True)
def _clean():
    reg.clear_tenant_for_tests("acme")
    yield
    reg.clear_tenant_for_tests("acme")


def test_store_disabled_falls_back_to_package(tmp_path):
    s = SimpleNamespace(tenant_store_enabled=False)
    d, is_mat = loader._resolve_tenant_dir("noble", s)
    assert is_mat is False
    assert d.name == "noble"


def test_store_active_tenant_materializes(tmp_path, monkeypatch):
    store = FakeTenantStore()
    _seed(store)
    monkeypatch.setattr(loader, "_build_store", lambda settings: store)
    s = SimpleNamespace(tenant_store_enabled=True, tenant_materialize_dir=str(tmp_path))
    d, is_mat = loader._resolve_tenant_dir("acme", s)
    assert is_mat is True
    assert (d / "persona" / "SOUL.md").read_text() == "soul"


def test_load_tenant_from_store_end_to_end(tmp_path, monkeypatch):
    store = FakeTenantStore()
    _seed(store)
    monkeypatch.setattr(loader, "_build_store", lambda settings: store)
    s = SimpleNamespace(
        tenant_store_enabled=True, tenant_materialize_dir=str(tmp_path),
    )
    ctx = loader.load_tenant("acme", s)
    assert ctx.tenant_id == "acme"
    assert ctx.data_source == "nbx"
    assert ctx.persona_dir.is_absolute()
    assert "check_loan" in ctx.enabled_tools
    # The materialized custom tool self-registered under the tenant.
    assert reg.resolve("acme", "check_loan") is not None
    assert reg.resolve("noble", "check_loan") is None


def test_draft_tenant_not_served_falls_back(tmp_path, monkeypatch):
    store = FakeTenantStore()
    prov.import_from_package(store, "noble", status="draft", now="2026-07-29T00:00:00+00:00")
    monkeypatch.setattr(loader, "_build_store", lambda settings: store)
    s = SimpleNamespace(tenant_store_enabled=True, tenant_materialize_dir=str(tmp_path))
    d, is_mat = loader._resolve_tenant_dir("noble", s)
    assert is_mat is False  # draft is not served → package fallback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_loader_store.py -v`
Expected: FAIL — `_resolve_tenant_dir` / `_build_store` don't exist.

- [ ] **Step 3: Modify `loader.py`**

In `src/noble_agent/tenant/loader.py`, add imports at the top (after the existing imports):
```python
from importlib import util as _importlib_util
```
Add a store-builder + resolver (place above `load_tenant`):
```python
def _build_store(settings):
    """Build the tenant store from settings (seam for tests)."""
    from noble_agent.tenant.store import MinioTenantStore

    return MinioTenantStore.from_settings(settings)


def _resolve_tenant_dir(tenant_id: str, settings) -> tuple[Path, bool]:
    """Return (bundle_dir, is_materialized). Store-first (active only), else
    the in-wheel package dir. Raises FileNotFoundError if neither exists."""
    if getattr(settings, "tenant_store_enabled", False):
        from noble_agent.tenant.materialize import materialize_tenant

        store = _build_store(settings)
        meta = store.read_meta(tenant_id)
        if meta is not None and meta.status == "active":
            d = materialize_tenant(store, tenant_id, settings.tenant_materialize_dir)
            return d, True
    pkg = _tenants_root() / tenant_id
    if not pkg.is_dir():
        raise FileNotFoundError(f"tenant dir not found: {pkg}")
    return pkg, False
```
Add the materialized-tenant tool importer:
```python
def _import_tenant_tools_from_dir(tenant_id: str, tools_dir: Path) -> None:
    """Import each tools/*.py from a materialized bundle by file path so
    @tool-decorated executors self-register. No-op if the dir is absent."""
    if not tools_dir.is_dir():
        return
    for py in sorted(tools_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        mod_name = f"noble_agent._tenant_tools.{tenant_id}.{py.stem}"
        spec = _importlib_util.spec_from_file_location(mod_name, py)
        if spec is None or spec.loader is None:
            continue
        module = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
```
Rewrite `load_tenant` to use the resolver. Replace the current body's directory resolution + tool import. The new body:
```python
def load_tenant(tenant_id: str, settings) -> TenantContext:
    tenant_dir, is_materialized = _resolve_tenant_dir(tenant_id, settings)
    manifest_path = tenant_dir / "manifest.toml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.toml not found for tenant {tenant_id!r}: {manifest_path}")
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"manifest.toml for tenant {tenant_id!r} is not valid TOML: {e}") from e

    data_source = data.get("data_source")
    persona_rel = data.get("persona_dir")
    tools = (data.get("tools") or {}).get("enabled")
    required = (("data_source", data_source), ("persona_dir", persona_rel), ("tools.enabled", tools))
    missing = [k for k, v in required if not v]
    if missing:
        raise ValueError(f"manifest.toml for tenant {tenant_id!r} missing required key(s): {', '.join(missing)}")

    brand = {str(k): str(v) for k, v in (data.get("brand") or {}).items()}
    if is_materialized:
        _import_tenant_tools_from_dir(tenant_id, tenant_dir / "tools")
    else:
        _import_tenant_tools(tenant_id)
    return TenantContext(
        tenant_id=data.get("tenant_id", tenant_id),
        data_source=str(data_source),
        persona_dir=(tenant_dir / str(persona_rel)).resolve(),
        enabled_tools=tuple(str(t) for t in tools),
        rankers=frozenset(str(r) for r in ((data.get("tools") or {}).get("rankers") or [])),
        media_channel=str((data.get("tools") or {}).get("media_channel") or "none"),
        brand=brand,
    )
```
Leave `_import_tenant_tools(tenant_id)`, `_tenants_root`, `get_tenant_context`, `reset_tenant_context_for_tests` **unchanged**.

- [ ] **Step 4: Run the new tests + the existing loader/tool tests**

Run: `pytest tests/unit/tenant/test_loader_store.py tests/unit/tenant/test_loader.py tests/unit/tenant/test_custom_tool_loading.py -v`
Expected: PASS (new store tests + the 4 existing loader tests + the 4 existing custom-tool tests — no regressions).

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/tenant/loader.py tests/unit/tenant/test_loader_store.py
git commit -m "feat(tenant): loader store-first resolution + materialized tool import

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `noble-tenant` CLI + console script

**Files:**
- Create: `src/noble_agent/tenant/cli.py`
- Modify: `pyproject.toml` (`[project.scripts]`)
- Test: `tests/unit/tenant/test_cli.py`

**Interfaces:**
- Consumes: `provisioning` (Task 6), `validation.validate_bundle` (Task 4), `MinioTenantStore.from_settings` (Task 3), `get_settings` (config).
- Produces: `main(argv: list[str] | None = None) -> int` with subcommands `create`, `update`, `show`, `list`, `activate`, `disable`, `validate`, `import-from-package`. A `--store` seam lets tests inject a `FakeTenantStore`; without it the CLI builds `MinioTenantStore.from_settings(get_settings())`.
- Bundle dir layout on disk for `create/update/validate --dir`: `<dir>/manifest.toml` + `<dir>/persona/*` + optional `<dir>/tools/*.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/tenant/test_cli.py`:
```python
from noble_agent.tenant import cli
from noble_agent.tenant.store import FakeTenantStore


def _write_bundle(dirpath):
    (dirpath / "manifest.toml").write_text(
        'tenant_id = "acme"\ndata_source = "nbx"\npersona_dir = "persona"\n'
        '[tools]\nenabled = ["kb_search"]\n', encoding="utf-8")
    persona = dirpath / "persona"
    persona.mkdir()
    (persona / "config.json").write_text('{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}', encoding="utf-8")
    for fn in ("SOUL.md", "RULES.md", "PROMPT_TEMPLATE.md", "CUSTOMER_PROFILE.md"):
        (persona / fn).write_text("x", encoding="utf-8")


def test_cli_validate_ok(tmp_path, capsys):
    _write_bundle(tmp_path)
    rc = cli.main(["validate", "--dir", str(tmp_path)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_cli_validate_reports_errors(tmp_path, capsys):
    _write_bundle(tmp_path)
    (tmp_path / "persona" / "SOUL.md").unlink()
    rc = cli.main(["validate", "--dir", str(tmp_path)])
    assert rc == 1
    assert "SOUL.md" in capsys.readouterr().out


def test_cli_create_then_list(tmp_path, capsys):
    _write_bundle(tmp_path)
    store = FakeTenantStore()
    rc = cli.main(["create", "acme", "--dir", str(tmp_path), "--status", "active"], store=store)
    assert rc == 0
    rc = cli.main(["list"], store=store)
    assert rc == 0
    out = capsys.readouterr().out
    assert "acme" in out and "active" in out


def test_cli_disable(tmp_path, capsys):
    _write_bundle(tmp_path)
    store = FakeTenantStore()
    cli.main(["create", "acme", "--dir", str(tmp_path), "--status", "active"], store=store)
    rc = cli.main(["disable", "acme"], store=store)
    assert rc == 0
    assert store.read_meta("acme").status == "disabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_cli.py -v`
Expected: FAIL — `noble_agent.tenant.cli` does not exist.

- [ ] **Step 3: Implement `cli.py`**

Create `src/noble_agent/tenant/cli.py`:
```python
"""noble-tenant CLI — provision tenant bundles into the store (slice #1)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.validation import validate_bundle


def _read_dir_bundle(dirpath: str) -> tuple[str, dict[str, str], str]:
    """Return (manifest_text, files, tenant_id_from_manifest_or_empty)."""
    root = Path(dirpath)
    manifest_text = (root / "manifest.toml").read_text(encoding="utf-8")
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in ("manifest.toml", "_meta.json") or rel.endswith(".pyc") or "__pycache__" in rel:
            continue
        files[rel] = path.read_text(encoding="utf-8")
    import tomllib

    tid = str(tomllib.loads(manifest_text).get("tenant_id", ""))
    return manifest_text, files, tid


def _get_store(injected):
    if injected is not None:
        return injected
    from noble_agent.config import get_settings
    from noble_agent.tenant.store import MinioTenantStore

    return MinioTenantStore.from_settings(get_settings())


def main(argv: list[str] | None = None, *, store=None) -> int:
    parser = argparse.ArgumentParser(prog="noble-tenant")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--dir", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("tenant_id")
    p_create.add_argument("--dir", required=True)
    p_create.add_argument("--status", default="draft", choices=["draft", "active", "disabled"])

    p_update = sub.add_parser("update")
    p_update.add_argument("tenant_id")
    p_update.add_argument("--dir", required=True)

    p_show = sub.add_parser("show")
    p_show.add_argument("tenant_id")

    sub.add_parser("list")

    p_act = sub.add_parser("activate")
    p_act.add_argument("tenant_id")

    p_dis = sub.add_parser("disable")
    p_dis.add_argument("tenant_id")

    p_imp = sub.add_parser("import-from-package")
    p_imp.add_argument("tenant_id")

    args = parser.parse_args(argv)

    if args.cmd == "validate":
        manifest_text, files, tid = _read_dir_bundle(args.dir)
        report = validate_bundle(tid or "placeholder", manifest_text, files)
        for w in report.warnings:
            print(f"WARN: {w}")
        if report.ok:
            print("OK")
            return 0
        for e in report.errors:
            print(f"ERROR: {e}")
        return 1

    st = _get_store(store)

    if args.cmd == "create":
        manifest_text, files, _ = _read_dir_bundle(args.dir)
        meta = prov.create_tenant(st, args.tenant_id, manifest_text, files, status=args.status)
        print(f"created {meta.tenant_id} v{meta.version} status={meta.status}")
        return 0
    if args.cmd == "update":
        manifest_text, files, _ = _read_dir_bundle(args.dir)
        meta = prov.update_tenant(st, args.tenant_id, manifest_text=manifest_text, files=files)
        print(f"updated {meta.tenant_id} v{meta.version}")
        return 0
    if args.cmd == "show":
        b = prov.get_tenant(st, args.tenant_id)
        print(f"{b.meta.tenant_id} v{b.meta.version} status={b.meta.status} files={sorted(b.files)}")
        return 0
    if args.cmd == "list":
        for m in prov.list_tenants(st):
            print(f"{m.tenant_id}\t{m.status}\tv{m.version}")
        return 0
    if args.cmd == "activate":
        m = prov.set_status(st, args.tenant_id, "active")
        print(f"{m.tenant_id} status={m.status}")
        return 0
    if args.cmd == "disable":
        m = prov.disable_tenant(st, args.tenant_id)
        print(f"{m.tenant_id} status={m.status}")
        return 0
    if args.cmd == "import-from-package":
        m = prov.import_from_package(st, args.tenant_id)
        print(f"imported {m.tenant_id} status={m.status}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 4: Add the console script**

In `pyproject.toml`, under `[project.scripts]`, add:
```toml
noble-tenant = "noble_agent.tenant.cli:main"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_cli.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Full tenant suite + lint + commit**

Run: `pytest tests/unit/tenant/ -v` → all green.
```bash
make lint
git add src/noble_agent/tenant/cli.py pyproject.toml tests/unit/tenant/test_cli.py
git commit -m "feat(tenant): noble-tenant CLI + console script

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Full-suite regression gate + docs

**Files:**
- Modify: `CLAUDE.md` (Change Log row + tenant layout note)
- No source changes.

**Interfaces:** none.

- [ ] **Step 1: Run the full unit suite**

Run: `make test-unit`
Expected: the pre-existing baseline of known failures ONLY (per CLAUDE.md: ~7–8 baseline reds — USD-normalize, qdrant_adapter×2, qdrant_store, snapshot_short_term, prompt 'Tên:', local-.env media). **ZERO new failures** from this slice. If any new failure traces to this slice, fix it before continuing.

- [ ] **Step 2: Confirm the store-disabled path is byte-identical**

Run: `pytest tests/unit/tenant/test_loader.py tests/unit/tenant/test_custom_tool_loading.py tests/unit/tenant/test_context.py -v`
Expected: PASS unchanged (proves default `TENANT_STORE_ENABLED=false` behavior is intact).

- [ ] **Step 3: Update `CLAUDE.md`**

Add a Change Log row (top of the table) dated `2026-07-29` summarizing: MinIO tenant store + `noble-tenant` CLI + loader store-first/fallback + materialized tool import; flag `TENANT_STORE_ENABLED=false` default → no behavior change; reference this plan + the spec. Add a short note to the `tenant/` layout row that bundles can now come from MinIO (materialized) as well as the in-wheel package.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record SaaS slice #1 (MinIO tenant store) in CLAUDE.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage** — every spec §:
- §4 bundle representation → Task 2 (models/hash) + Task 3 (MinIO layout `_meta.json`/`manifest.toml`/files).
- §5 loader (store-first, materialize idempotent+atomic, file-path tool import, package fallback) → Task 5 (materialize) + Task 7 (loader).
- §6.1 library API → Task 6. §6.2 CLI → Task 8. §6.3 validation (5 checks + AST-not-execute + import warning) → Task 4. §6.4 lifecycle (draft/active/disabled, no hot-reload) → Task 6 (`set_status`/`disable`) + Task 7 (only `active` served).
- §7 store client + `from_settings` → Task 3; config settings → Task 1.
- §8 backward-compat + tests → Task 7 Step 4 (existing tests) + Task 9 (full-suite gate); `TENANT_STORE_ENABLED=false` default → Task 1.
- §9/§10 rationale/gaps → documentation only (no task needed).

**2. Placeholder scan** — no "TBD/TODO/handle edge cases/similar to Task N"; every code step has real code; every test step has real assertions.

**3. Type consistency** — `TenantMeta`/`Bundle`/`bundle_hash(manifest_text, files)`/`TenantStore` (`read_meta`/`list_ids`/`read_bundle`/`write_bundle`) are defined in Task 2 and used verbatim in Tasks 3/5/6/7. `validate_bundle(tenant_id, manifest_text, files, *, existing_ids=())` defined in Task 4, called with those args in Task 6. `materialize_tenant(store, tenant_id, dest_root)` defined in Task 5, called in Task 7. `_build_store`/`_resolve_tenant_dir`/`_import_tenant_tools_from_dir` defined in Task 7 and monkeypatched by name in its tests. CLI `main(argv, *, store=None)` matches its tests.
