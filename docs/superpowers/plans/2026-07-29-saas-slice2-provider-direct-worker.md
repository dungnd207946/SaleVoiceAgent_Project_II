# SaaS Slice #2 — Provider gọi thẳng worker qua URL + credential riêng — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cấp credential per-tenant lúc provisioning và dựng một ingress gateway nhận-diện-tenant, để backend của provider stream **voice** (bridge vào LiveKit room nội bộ) và **chat** (reverse-proxy WS) thẳng tới worker của đúng tenant, không chạm control plane trên đường setup.

**Architecture:** Gateway dùng chung (stateless) đứng trước LiveKit: resolve tenant từ Host → verify `Bearer <tenant-cred>` từ cache → voice bridge vào LiveKit room (dispatch `agent-<tenant>`) / chat reverse-proxy WS tới `text_chat` của worker. Credential dài hạn, chỉ lưu hash trong tenant store, verify cục bộ tại gateway (control plane ngoài path → giữ E01). Worker LiveKit giữ nguyên media path; chỉ đổi `agent_name` theo tenant + đọc identity metadata để seed Customer (voice).

**Tech Stack:** Python 3.11+, `websockets` (WS server/client — đã là dep), `livekit.api` (mint token — đã là dep), `boto3`/MinIO (tenant store — slice #1), pydantic-settings (config), pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-29-saas-slice2-provider-direct-worker-design.md` (đọc trước).
- Branch: `feat/refactor2`. **Không** đụng `develop`. Commit local trên feature branch OK; không push/PR nếu không được yêu cầu.
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Pytest `asyncio_mode=auto`.
- **Bất biến bảo mật:** plaintext credential **không bao giờ** được lưu (chỉ hash + salt). Gateway verify từ **cache đọc store**, **không** gọi Portal/provisioning API sống. Gateway **không import/thực thi** code tenant.
- **Zero-regression cho path hiện tại:** khi không có tenant nào dùng gateway, worker + `/chat` + LiveKit hoạt động y như trước. Gate: `make test-unit` không thêm failure ngoài baseline đã biết (2 USD-normalize, 2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:', 1 send_media local-.env, 1 test_project_financial_mongo::test_pricing_unit_type_filter).
- Style: dependency-injection cho store/minter/clock để test offline (mirror slice #1: `FakeTenantStore`, fake S3 client).
- Credential plaintext format: **`tnt_` + `secrets.token_urlsafe(32)`**. Tenant xác định bằng **Host subdomain**, không parse tenant từ token.
- Tên dispatch agent: **`agent-<tenant_id>`** (pure function của tenant_id, dùng chung worker + gateway — không được drift).

---

## File Structure

**Tạo mới:**
- `src/noble_agent/tenant/credentials.py` — logic credential thuần: `CredentialEntry`, generate/verify/hash, serialize/parse.
- `src/noble_agent/tenant/naming.py` — `agent_dispatch_name(tenant_id)` (pure, dùng chung).
- `src/noble_agent/gateway/__init__.py` — package rỗng.
- `src/noble_agent/gateway/registry.py` — `CredentialRegistry` cache TTL đọc store.
- `src/noble_agent/gateway/auth.py` — `tenant_from_host`, `authorize`.
- `src/noble_agent/gateway/livekit_bridge.py` — `room_name`, `build_dispatch_token` (pure phần dựng token).
- `src/noble_agent/gateway/server.py` — WS server, route `/v1/stream` + `/v1/chat`, handshake, console entry `run_gateway`.
- Tests: `tests/unit/gateway/test_credentials.py`, `test_store_creds.py`, `test_provisioning_creds.py`, `test_cli_creds.py`, `test_registry.py`, `test_auth.py`, `test_livekit_bridge.py`, `test_server_routing.py`, `test_chat_proxy.py`, `test_worker_identity_seed.py`.

**Sửa:**
- `src/noble_agent/config.py:83-89` — thêm block settings gateway (§4.5 spec).
- `src/noble_agent/tenant/store.py` — thêm `read_creds_raw`/`write_creds_raw` (Protocol + Fake + Minio).
- `src/noble_agent/tenant/provisioning.py` — `issue_credential`/`revoke_credential`/`list_credentials`/`endpoint_url` + `create_tenant` auto-issue tuỳ chọn.
- `src/noble_agent/tenant/cli.py` — `issue-cred`/`revoke-cred`/`list-creds`.
- `src/noble_agent/server/app_session.py` — trích `identity_to_fields(identity) -> dict` (DRY, dùng lại ở provision_session + worker).
- `src/noble_agent/transport/livekit/worker.py:189-205,226` — đọc `caller.metadata` → seed Customer; `agent_name=agent_dispatch_name(settings.tenant_id)`.
- `pyproject.toml` — console script `noble-gateway`.
- `.env.example`, `CLAUDE.md` (changelog), `src/noble_agent/SMOKE.md`.

---

## Task 1: Config settings + `agent_dispatch_name`

**Files:**
- Modify: `src/noble_agent/config.py` (sau dòng 89, trong block multi-tenant)
- Create: `src/noble_agent/tenant/naming.py`
- Test: `tests/unit/gateway/test_credentials.py` (thêm 1 case naming — hoặc `tests/unit/tenant/test_naming.py`)

**Interfaces:**
- Produces: `agent_dispatch_name(tenant_id: str) -> str`; settings fields `tenant_endpoint_template`, `gateway_host`, `gateway_port`, `gateway_cred_cache_ttl_sec`, `gateway_base_domain`, `gateway_worker_secret`, `worker_chat_internal_url_template`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/tenant/test_naming.py
from noble_agent.tenant.naming import agent_dispatch_name

def test_agent_dispatch_name():
    assert agent_dispatch_name("noble") == "agent-noble"
    assert agent_dispatch_name("acme-corp") == "agent-acme-corp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.tenant.naming`

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/tenant/naming.py
"""Pure tenant-name derivations shared by worker registration + gateway dispatch."""
from __future__ import annotations


def agent_dispatch_name(tenant_id: str) -> str:
    """LiveKit agent_name a tenant's worker registers under / the gateway dispatches."""
    return f"agent-{tenant_id}"
```

Thêm vào `config.py` ngay sau dòng 89 (`tenant_materialize_dir`):

```python
    # ── SaaS slice #2: provider-facing gateway ─────────────────────────────────
    tenant_endpoint_template: str = Field("wss://{tenant_id}.agents.noblex.vn", alias="TENANT_ENDPOINT_TEMPLATE")
    gateway_base_domain: str = Field("agents.noblex.vn", alias="GATEWAY_BASE_DOMAIN")
    gateway_host: str = Field("0.0.0.0", alias="GATEWAY_HOST")
    gateway_port: int = Field(9200, alias="GATEWAY_PORT")
    gateway_cred_cache_ttl_sec: float = Field(30.0, alias="GATEWAY_CRED_CACHE_TTL_SEC")
    gateway_worker_secret: str = Field("", alias="GATEWAY_WORKER_SECRET")
    worker_chat_internal_url_template: str = Field(
        "ws://agent-{tenant_id}:8766/chat", alias="WORKER_CHAT_INTERNAL_URL_TEMPLATE"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/tenant/test_naming.py -v && python -c "from noble_agent.config import UnifiedSettings; s=UnifiedSettings(_env_file=None); print(s.gateway_port, s.gateway_base_domain)"`
Expected: PASS; prints `9200 agents.noblex.vn`

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/naming.py src/noble_agent/config.py tests/unit/tenant/test_naming.py
git commit -m "feat(gateway): tenant agent-name helper + slice #2 gateway settings"
```

---

## Task 2: Credential core (`tenant/credentials.py`)

**Files:**
- Create: `src/noble_agent/tenant/credentials.py`
- Test: `tests/unit/gateway/test_credentials.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) CredentialEntry(key_id: str, salt: str, hash: str, created_at: str, revoked_at: str = "")`
  - `generate_credential(*, now: str) -> tuple[str, CredentialEntry]` — returns `(plaintext, entry)`; plaintext starts with `tnt_`.
  - `verify(plaintext: str, entries: list[CredentialEntry]) -> CredentialEntry | None` — matched non-revoked entry, else None.
  - `serialize_creds(entries: list[CredentialEntry]) -> str` / `parse_creds(raw: str) -> list[CredentialEntry]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_credentials.py
from noble_agent.tenant import credentials as c

def test_generate_verify_roundtrip():
    plaintext, entry = c.generate_credential(now="2026-07-29T00:00:00+00:00")
    assert plaintext.startswith("tnt_")
    assert entry.hash and entry.salt and entry.key_id
    assert c.verify(plaintext, [entry]) is entry

def test_verify_rejects_wrong_and_revoked():
    good, e = c.generate_credential(now="t")
    other, _ = c.generate_credential(now="t")
    assert c.verify(other, [e]) is None          # wrong secret
    assert c.verify("no-prefix", [e]) is None     # bad format
    revoked = c.CredentialEntry(e.key_id, e.salt, e.hash, e.created_at, revoked_at="t2")
    assert c.verify(good, [revoked]) is None      # revoked

def test_hash_never_contains_plaintext_and_roundtrips_serialization():
    plaintext, e = c.generate_credential(now="t")
    raw = c.serialize_creds([e])
    assert plaintext not in raw and "tnt_" not in raw
    assert c.parse_creds(raw) == [e]
    assert c.verify(plaintext, c.parse_creds(raw)) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_credentials.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/tenant/credentials.py
"""Per-tenant API credential: generate/verify/hash + JSON (de)serialization.

Only a salted SHA-256 HASH is ever persisted — the plaintext (a 32-byte
urlsafe secret) is returned once at issue time and never stored. Tenant is
identified out-of-band (Host subdomain), so the token carries no tenant id.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass

_PREFIX = "tnt_"


@dataclass(frozen=True)
class CredentialEntry:
    key_id: str
    salt: str  # hex
    hash: str  # hex sha256(salt_bytes + plaintext_bytes)
    created_at: str
    revoked_at: str = ""


def _hash(salt_hex: str, plaintext: str) -> str:
    return hashlib.sha256(bytes.fromhex(salt_hex) + plaintext.encode("utf-8")).hexdigest()


def generate_credential(*, now: str) -> tuple[str, CredentialEntry]:
    plaintext = _PREFIX + secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    entry = CredentialEntry(secrets.token_hex(4), salt, _hash(salt, plaintext), now)
    return plaintext, entry


def verify(plaintext: str, entries: list[CredentialEntry]) -> CredentialEntry | None:
    if not plaintext or not plaintext.startswith(_PREFIX):
        return None
    for e in entries:
        if e.revoked_at:
            continue
        if hmac.compare_digest(e.hash, _hash(e.salt, plaintext)):
            return e
    return None


def serialize_creds(entries: list[CredentialEntry]) -> str:
    return json.dumps([asdict(e) for e in entries])


def parse_creds(raw: str) -> list[CredentialEntry]:
    return [CredentialEntry(**d) for d in json.loads(raw or "[]")]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_credentials.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/credentials.py tests/unit/gateway/test_credentials.py
git commit -m "feat(tenant): per-tenant credential core (salted-hash, no plaintext at rest)"
```

---

## Task 3: Store credential I/O (`read_creds_raw`/`write_creds_raw`)

**Files:**
- Modify: `src/noble_agent/tenant/store.py` (Protocol + `FakeTenantStore` + `MinioTenantStore`)
- Test: `tests/unit/gateway/test_store_creds.py`

**Interfaces:**
- Consumes: `TenantStore` (slice #1), the fake S3 client pattern from slice #1 tests.
- Produces: `TenantStore.read_creds_raw(tenant_id) -> str | None`, `TenantStore.write_creds_raw(tenant_id, raw: str) -> None`; constant `_CREDS = "_creds.json"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_store_creds.py
from noble_agent.tenant.store import FakeTenantStore

def test_fake_store_creds_roundtrip():
    st = FakeTenantStore()
    assert st.read_creds_raw("t1") is None
    st.write_creds_raw("t1", '[{"key_id":"a"}]')
    assert st.read_creds_raw("t1") == '[{"key_id":"a"}]'
    # creds live outside the bundle listing (not a tenant of their own)
    assert "t1" not in st.list_ids()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_store_creds.py -v`
Expected: FAIL — `AttributeError: 'FakeTenantStore' object has no attribute 'read_creds_raw'`

- [ ] **Step 3: Write minimal implementation**

Trong `store.py`: thêm `_CREDS = "_creds.json"` cạnh `_MANIFEST`/`_META`. Thêm 2 method vào `TenantStore` Protocol:

```python
    def read_creds_raw(self, tenant_id: str) -> str | None: ...
    def write_creds_raw(self, tenant_id: str, raw: str) -> None: ...
```

`FakeTenantStore` — thêm `self._creds: dict[str, str] = {}` trong `__init__`:

```python
    def read_creds_raw(self, tenant_id: str) -> str | None:
        return self._creds.get(tenant_id)

    def write_creds_raw(self, tenant_id: str, raw: str) -> None:
        self._creds[tenant_id] = raw
```

`MinioTenantStore`:

```python
    def read_creds_raw(self, tenant_id: str) -> str | None:
        return self._get_text(f"{tenant_id}/{_CREDS}")

    def write_creds_raw(self, tenant_id: str, raw: str) -> None:
        self._c.put_object(Bucket=self._bucket, Key=f"{tenant_id}/{_CREDS}", Body=raw.encode("utf-8"))
```

Lưu ý: `read_bundle` đã bỏ qua `_META`/`_MANIFEST` khi liệt kê files — thêm `_CREDS` vào bộ loại trừ ở dòng `if rel in (_META, _MANIFEST) or not rel:` → `if rel in (_META, _MANIFEST, _CREDS) or not rel:` để hash bundle không bao giờ nuốt `_creds.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_store_creds.py tests/unit/tenant -v`
Expected: PASS; slice #1 tenant tests vẫn xanh.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/store.py tests/unit/gateway/test_store_creds.py
git commit -m "feat(tenant): store read/write _creds.json (excluded from bundle hash)"
```

---

## Task 4: Provisioning credential API + `endpoint_url`

**Files:**
- Modify: `src/noble_agent/tenant/provisioning.py`
- Test: `tests/unit/gateway/test_provisioning_creds.py`

**Interfaces:**
- Consumes: `credentials` (T2), store creds I/O (T3), `_now` (existing).
- Produces:
  - `issue_credential(store, tenant_id, *, now=None) -> str`
  - `revoke_credential(store, tenant_id, key_id, *, now=None) -> None`
  - `list_credentials(store, tenant_id) -> list[dict]` (chỉ `key_id/created_at/revoked_at`)
  - `endpoint_url(tenant_id, settings) -> dict` (`{"voice": ..., "chat": ...}`)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_provisioning_creds.py
import pytest
from types import SimpleNamespace
from noble_agent.tenant import provisioning as prov, credentials as c
from noble_agent.tenant.store import FakeTenantStore, Bundle, TenantMeta

def _seed(st, tid="t1"):
    st.write_bundle(Bundle(tid, "tenant_id='t1'", {}, TenantMeta(tid, "active", 1, "sha256:x")))

def test_issue_then_verify_and_list():
    st = FakeTenantStore(); _seed(st)
    plaintext = prov.issue_credential(st, "t1", now="t")
    entries = c.parse_creds(st.read_creds_raw("t1"))
    assert c.verify(plaintext, entries) is not None
    listed = prov.list_credentials(st, "t1")
    assert len(listed) == 1 and "hash" not in listed[0] and listed[0]["revoked_at"] == ""

def test_revoke_disables_verify():
    st = FakeTenantStore(); _seed(st)
    plaintext = prov.issue_credential(st, "t1", now="t")
    key_id = prov.list_credentials(st, "t1")[0]["key_id"]
    prov.revoke_credential(st, "t1", key_id, now="t2")
    assert c.verify(plaintext, c.parse_creds(st.read_creds_raw("t1"))) is None

def test_issue_unknown_tenant_raises():
    with pytest.raises(ValueError):
        prov.issue_credential(FakeTenantStore(), "ghost", now="t")

def test_endpoint_url_renders_voice_and_chat():
    s = SimpleNamespace(tenant_endpoint_template="wss://{tenant_id}.agents.noblex.vn")
    assert prov.endpoint_url("t1", s) == {
        "voice": "wss://t1.agents.noblex.vn/v1/stream",
        "chat": "wss://t1.agents.noblex.vn/v1/chat",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_provisioning_creds.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'issue_credential'`

- [ ] **Step 3: Write minimal implementation**

Thêm vào `provisioning.py` (import `from noble_agent.tenant import credentials`):

```python
def issue_credential(store, tenant_id: str, *, now: str | None = None) -> str:
    if store.read_meta(tenant_id) is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    entries = credentials.parse_creds(store.read_creds_raw(tenant_id) or "[]")
    plaintext, entry = credentials.generate_credential(now=_now(now))
    entries.append(entry)
    store.write_creds_raw(tenant_id, credentials.serialize_creds(entries))
    return plaintext


def revoke_credential(store, tenant_id: str, key_id: str, *, now: str | None = None) -> None:
    from dataclasses import replace

    entries = credentials.parse_creds(store.read_creds_raw(tenant_id) or "[]")
    updated = [
        replace(e, revoked_at=_now(now)) if (e.key_id == key_id and not e.revoked_at) else e for e in entries
    ]
    store.write_creds_raw(tenant_id, credentials.serialize_creds(updated))


def list_credentials(store, tenant_id: str) -> list[dict]:
    entries = credentials.parse_creds(store.read_creds_raw(tenant_id) or "[]")
    return [{"key_id": e.key_id, "created_at": e.created_at, "revoked_at": e.revoked_at} for e in entries]


def endpoint_url(tenant_id: str, settings) -> dict:
    base = settings.tenant_endpoint_template.format(tenant_id=tenant_id).rstrip("/")
    return {"voice": f"{base}/v1/stream", "chat": f"{base}/v1/chat"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_provisioning_creds.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/provisioning.py tests/unit/gateway/test_provisioning_creds.py
git commit -m "feat(tenant): provisioning issue/revoke/list credential + endpoint_url"
```

---

## Task 5: CLI credential commands

**Files:**
- Modify: `src/noble_agent/tenant/cli.py`
- Test: `tests/unit/gateway/test_cli_creds.py`

**Interfaces:**
- Consumes: provisioning creds API (T4), `main(argv, *, store=None)` (existing DI seam).
- Produces: CLI subcommands `issue-cred <tenant>`, `revoke-cred <tenant> <key_id>`, `list-creds <tenant>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_cli_creds.py
from noble_agent.tenant import cli
from noble_agent.tenant.store import FakeTenantStore, Bundle, TenantMeta

def _store():
    st = FakeTenantStore()
    st.write_bundle(Bundle("t1", "tenant_id='t1'", {}, TenantMeta("t1", "active", 1, "sha256:x")))
    return st

def test_issue_cred_prints_plaintext(capsys):
    st = _store()
    rc = cli.main(["issue-cred", "t1"], store=st)
    out = capsys.readouterr().out
    assert rc == 0 and "tnt_" in out
    assert st.read_creds_raw("t1") is not None

def test_list_and_revoke_cred(capsys):
    st = _store()
    cli.main(["issue-cred", "t1"], store=st)
    cli.main(["list-creds", "t1"], store=st)
    key_id = capsys.readouterr().out.split()[0]
    rc = cli.main(["revoke-cred", "t1", key_id], store=st)
    assert rc == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_cli_creds.py -v`
Expected: FAIL — argparse exits on unknown command `issue-cred`.

- [ ] **Step 3: Write minimal implementation**

Trong `cli.py`, thêm parsers (sau `import-from-package`):

```python
    p_issue = sub.add_parser("issue-cred")
    p_issue.add_argument("tenant_id")

    p_revoke = sub.add_parser("revoke-cred")
    p_revoke.add_argument("tenant_id")
    p_revoke.add_argument("key_id")

    p_lc = sub.add_parser("list-creds")
    p_lc.add_argument("tenant_id")
```

Và các nhánh (sau `import-from-package`, trước `return 2`):

```python
    if args.cmd == "issue-cred":
        plaintext = prov.issue_credential(st, args.tenant_id)
        print(plaintext)
        return 0
    if args.cmd == "revoke-cred":
        prov.revoke_credential(st, args.tenant_id, args.key_id)
        print(f"revoked {args.key_id}")
        return 0
    if args.cmd == "list-creds":
        for m in prov.list_credentials(st, args.tenant_id):
            print(f"{m['key_id']}\t{m['created_at']}\t{'revoked' if m['revoked_at'] else 'active'}")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_cli_creds.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/cli.py tests/unit/gateway/test_cli_creds.py
git commit -m "feat(tenant): noble-tenant issue-cred/revoke-cred/list-creds"
```

---

## Task 6: Gateway credential registry (cache TTL)

**Files:**
- Create: `src/noble_agent/gateway/__init__.py` (rỗng), `src/noble_agent/gateway/registry.py`
- Test: `tests/unit/gateway/test_registry.py`

**Interfaces:**
- Consumes: `TenantStore` (read_creds_raw, read_meta), `credentials.parse_creds`.
- Produces: `CredentialRegistry(store, ttl_sec: float, *, clock=time.monotonic)` với `entries_for(tenant_id) -> list[CredentialEntry]` (cached, refresh khi quá TTL) và `is_active(tenant_id) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_registry.py
from noble_agent.gateway.registry import CredentialRegistry
from noble_agent.tenant.store import FakeTenantStore, Bundle, TenantMeta
from noble_agent.tenant import provisioning as prov

class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t

def _store():
    st = FakeTenantStore()
    st.write_bundle(Bundle("t1", "tenant_id='t1'", {}, TenantMeta("t1", "active", 1, "sha256:x")))
    return st

def test_entries_cached_until_ttl():
    st, clk = _store(), Clock()
    reg = CredentialRegistry(st, ttl_sec=30.0, clock=clk)
    prov.issue_credential(st, "t1", now="t")
    assert len(reg.entries_for("t1")) == 1
    prov.issue_credential(st, "t1", now="t")          # store now has 2
    assert len(reg.entries_for("t1")) == 1            # still cached
    clk.t = 31.0
    assert len(reg.entries_for("t1")) == 2            # refreshed after TTL

def test_is_active():
    st = _store()
    reg = CredentialRegistry(st, ttl_sec=30.0)
    assert reg.is_active("t1") is True
    assert reg.is_active("ghost") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_registry.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/gateway/registry.py
"""In-process TTL cache of per-tenant credentials + active-status, read from
the tenant store. Verify path reads THIS, never a live control-plane API — so
the control plane being down never blocks new-call setup (HT_01 E01)."""
from __future__ import annotations

import time

from noble_agent.tenant import credentials
from noble_agent.tenant.credentials import CredentialEntry
from noble_agent.tenant.store import TenantStore


class CredentialRegistry:
    def __init__(self, store: TenantStore, ttl_sec: float, *, clock=time.monotonic) -> None:
        self._store = store
        self._ttl = ttl_sec
        self._clock = clock
        self._cache: dict[str, tuple[float, list[CredentialEntry]]] = {}

    def entries_for(self, tenant_id: str) -> list[CredentialEntry]:
        now = self._clock()
        hit = self._cache.get(tenant_id)
        if hit is not None and (now - hit[0]) < self._ttl:
            return hit[1]
        entries = credentials.parse_creds(self._store.read_creds_raw(tenant_id) or "[]")
        self._cache[tenant_id] = (now, entries)
        return entries

    def is_active(self, tenant_id: str) -> bool:
        meta = self._store.read_meta(tenant_id)
        return meta is not None and meta.status == "active"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_registry.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/__init__.py src/noble_agent/gateway/registry.py tests/unit/gateway/test_registry.py
git commit -m "feat(gateway): TTL credential registry (store-backed, offline verify)"
```

---

## Task 7: Gateway auth (Host → tenant, Bearer verify)

**Files:**
- Create: `src/noble_agent/gateway/auth.py`
- Test: `tests/unit/gateway/test_auth.py`

**Interfaces:**
- Consumes: `CredentialRegistry` (T6), `credentials.verify`.
- Produces:
  - `tenant_from_host(host: str, base_domain: str) -> str | None`
  - `@dataclass(frozen=True) AuthResult(ok: bool, tenant_id: str = "", key_id: str = "", reason: str = "")`
  - `authorize(host: str, authorization: str, *, registry, base_domain: str) -> AuthResult`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_auth.py
from noble_agent.gateway.auth import tenant_from_host, authorize
from noble_agent.gateway.registry import CredentialRegistry
from noble_agent.tenant.store import FakeTenantStore, Bundle, TenantMeta
from noble_agent.tenant import provisioning as prov

BASE = "agents.noblex.vn"

def test_tenant_from_host():
    assert tenant_from_host("t1.agents.noblex.vn", BASE) == "t1"
    assert tenant_from_host("t1.agents.noblex.vn:9200", BASE) == "t1"
    assert tenant_from_host("agents.noblex.vn", BASE) is None      # no subdomain
    assert tenant_from_host("t1.evil.com", BASE) is None           # wrong base

def _reg_with_cred(tid="t1", active="active"):
    st = FakeTenantStore()
    st.write_bundle(Bundle(tid, f"tenant_id='{tid}'", {}, TenantMeta(tid, active, 1, "sha256:x")))
    plaintext = prov.issue_credential(st, tid, now="t")
    return CredentialRegistry(st, ttl_sec=30.0), plaintext

def test_authorize_happy():
    reg, cred = _reg_with_cred()
    r = authorize("t1.agents.noblex.vn", f"Bearer {cred}", registry=reg, base_domain=BASE)
    assert r.ok and r.tenant_id == "t1" and r.key_id

def test_authorize_rejects():
    reg, cred = _reg_with_cred()
    _, other = _reg_with_cred("t2")
    assert not authorize("bad.host", f"Bearer {cred}", registry=reg, base_domain=BASE).ok      # host
    assert not authorize("t1.agents.noblex.vn", "", registry=reg, base_domain=BASE).ok          # no header
    assert not authorize("t1.agents.noblex.vn", f"Bearer {other}", registry=reg, base_domain=BASE).ok  # wrong tenant's cred

def test_authorize_rejects_inactive():
    reg, cred = _reg_with_cred(active="disabled")
    assert not authorize("t1.agents.noblex.vn", f"Bearer {cred}", registry=reg, base_domain=BASE).ok
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_auth.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/gateway/auth.py
"""Gateway request authorization: tenant from Host subdomain + Bearer verify."""
from __future__ import annotations

from dataclasses import dataclass

from noble_agent.tenant import credentials

_BEARER = "Bearer "


def tenant_from_host(host: str, base_domain: str) -> str | None:
    host = (host or "").split(":", 1)[0].strip().lower()
    suffix = "." + base_domain.strip().lower()
    if not host.endswith(suffix):
        return None
    sub = host[: -len(suffix)]
    return sub or None


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    tenant_id: str = ""
    key_id: str = ""
    reason: str = ""


def authorize(host: str, authorization: str, *, registry, base_domain: str) -> AuthResult:
    tenant = tenant_from_host(host, base_domain)
    if tenant is None:
        return AuthResult(False, reason="bad_host")
    if not registry.is_active(tenant):
        return AuthResult(False, tenant_id=tenant, reason="tenant_inactive")
    if not authorization or not authorization.startswith(_BEARER):
        return AuthResult(False, tenant_id=tenant, reason="no_bearer")
    plaintext = authorization[len(_BEARER) :]
    entry = credentials.verify(plaintext, registry.entries_for(tenant))
    if entry is None:
        return AuthResult(False, tenant_id=tenant, reason="bad_credential")
    return AuthResult(True, tenant_id=tenant, key_id=entry.key_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/auth.py tests/unit/gateway/test_auth.py
git commit -m "feat(gateway): Host→tenant resolution + Bearer credential authorization"
```

---

## Task 8: LiveKit bridge helpers (room name + dispatch token)

**Files:**
- Create: `src/noble_agent/gateway/livekit_bridge.py`
- Test: `tests/unit/gateway/test_livekit_bridge.py`

**Interfaces:**
- Consumes: `agent_dispatch_name` (T1).
- Produces:
  - `room_name(tenant_id: str, call_id: str) -> str`
  - `build_dispatch_token(tenant_id, identity_json, *, api_key, api_secret, url, minter) -> tuple[str, str, str]` — returns `(jwt, url, room)`; token grants join to a fresh room, embeds `RoomAgentDispatch(agent_name=agent-<tenant>)`, and carries `identity_json` as participant metadata. `minter` is injected (default `livekit.api.AccessToken`) for offline tests.

Note (design fidelity): mirror `server/app_session.py:_mint_livekit_token` (lines 204-239). Difference: `agent_name=agent_dispatch_name(tenant_id)` and `.with_metadata(identity_json)` so the worker can seed Customer from it (Task 10).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_livekit_bridge.py
from noble_agent.gateway import livekit_bridge as b

def test_room_name_scoped_and_unique():
    r1 = b.room_name("t1", "call-abc")
    assert r1.startswith("t1-") and "call-abc" in r1

class FakeToken:
    def __init__(self, *a, **k): self.calls = []
    def with_identity(self, v): self.calls.append(("identity", v)); return self
    def with_name(self, v): self.calls.append(("name", v)); return self
    def with_metadata(self, v): self.calls.append(("metadata", v)); return self
    def with_grants(self, v): self.calls.append(("grants", v)); return self
    def with_room_config(self, v): self.calls.append(("room_config", v)); return self
    def to_jwt(self): return "JWT"

def test_build_dispatch_token_uses_tenant_agent_and_metadata():
    tok = FakeToken()
    jwt, url, room = b.build_dispatch_token(
        "t1", '{"name":"An"}', api_key="k", api_secret="s", url="wss://lk", minter=lambda *a, **k: tok
    )
    assert jwt == "JWT" and url == "wss://lk" and room.startswith("t1-")
    kinds = dict(tok.calls)
    assert kinds["metadata"] == '{"name":"An"}'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_livekit_bridge.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/gateway/livekit_bridge.py
"""Bridge helpers: mint a room-join token that (a) dispatches the tenant's
worker (agent-<tenant>) and (b) carries the end-user identity as participant
metadata for the worker to seed Customer. Pure token/room logic — the actual
audio relay is wired in server.py and covered by smoke tests."""
from __future__ import annotations

import secrets
import time

from noble_agent.tenant.naming import agent_dispatch_name

_ROOM_EMPTY_TIMEOUT_S = 5


def room_name(tenant_id: str, call_id: str) -> str:
    return f"{tenant_id}-{call_id}-{int(time.time() * 1000)}-{secrets.token_hex(2)}"


def build_dispatch_token(
    tenant_id: str,
    identity_json: str,
    *,
    api_key: str,
    api_secret: str,
    url: str,
    call_id: str = "call",
    minter=None,
) -> tuple[str, str, str]:
    from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

    minter = minter or AccessToken
    room = room_name(tenant_id, call_id)
    identity = f"caller-{room}"
    token = (
        minter(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_metadata(identity_json or "")
        .with_grants(VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True))
        .with_room_config(
            RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=agent_dispatch_name(tenant_id))],
                empty_timeout=_ROOM_EMPTY_TIMEOUT_S,
            )
        )
        .to_jwt()
    )
    return token, url, room
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_livekit_bridge.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/livekit_bridge.py tests/unit/gateway/test_livekit_bridge.py
git commit -m "feat(gateway): LiveKit dispatch-token builder (agent-<tenant> + identity metadata)"
```

---

## Task 9: Gateway server — routing, handshake, voice bridge + console script

**Files:**
- Create: `src/noble_agent/gateway/server.py`
- Modify: `pyproject.toml` (console script)
- Test: `tests/unit/gateway/test_server_routing.py`

**Interfaces:**
- Consumes: `authorize` (T7), `build_dispatch_token` (T8), `CredentialRegistry` (T6), settings (T1).
- Produces:
  - `route(path: str) -> str | None` — `"voice"` cho `/v1/stream`, `"chat"` cho `/v1/chat`, else None.
  - `parse_handshake(raw: str) -> dict` — JSON `{identity?: {...}, call_id?: str}`; `{}` khi hỏng.
  - `run_gateway()` — console entry (bind `settings.gateway_host:gateway_port`, `websockets.serve`).

Note: `run_gateway` + the audio relay loop are integration-level (need LiveKit + a real WS client) → covered by SMOKE.md, not unit. Unit tests cover the pure decision functions (`route`, `parse_handshake`) and that a bad-auth connection is rejected before any bridge call.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_server_routing.py
from noble_agent.gateway import server as s

def test_route():
    assert s.route("/v1/stream") == "voice"
    assert s.route("/v1/stream?x=1") == "voice"
    assert s.route("/v1/chat") == "chat"
    assert s.route("/other") is None

def test_parse_handshake():
    assert s.parse_handshake('{"identity":{"full_name":"An"},"call_id":"c1"}') == {
        "identity": {"full_name": "An"}, "call_id": "c1"
    }
    assert s.parse_handshake("not json") == {}
    assert s.parse_handshake("") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_server_routing.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/gateway/server.py
"""Provider-facing ingress gateway (SaaS slice #2).

One authenticated WS entry per tenant subdomain:
  /v1/stream  → verify → bridge provider audio into the tenant's LiveKit room
  /v1/chat    → verify → reverse-proxy WS to the tenant worker's /chat

Serving-plane infra (peer of the LiveKit server), NOT the control plane:
verifies from a store-backed cache, never calls a live Portal API, never
imports or executes tenant code.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

logger = logging.getLogger("gateway")


def route(path: str) -> str | None:
    p = urlparse(path or "/").path
    if p == "/v1/stream":
        return "voice"
    if p == "/v1/chat":
        return "chat"
    return None


def parse_handshake(raw: str) -> dict:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def run_gateway() -> None:  # pragma: no cover — integration entry
    import asyncio

    from noble_agent.config import get_settings
    from noble_agent.gateway.registry import CredentialRegistry
    from noble_agent.tenant.store import MinioTenantStore

    settings = get_settings()
    registry = CredentialRegistry(
        MinioTenantStore.from_settings(settings), ttl_sec=settings.gateway_cred_cache_ttl_sec
    )
    asyncio.run(_serve(settings, registry))
```

Thêm `_serve` + `_handle` (integration, `# pragma: no cover` cho phần relay). Khung:

```python
async def _serve(settings, registry) -> None:  # pragma: no cover
    import websockets

    async def handler(ws):
        await _handle(ws, settings, registry)

    async with websockets.serve(handler, settings.gateway_host, settings.gateway_port):
        await asyncio.Future()


async def _handle(ws, settings, registry) -> None:  # pragma: no cover
    from noble_agent.gateway.auth import authorize

    path = getattr(ws, "path", "/")
    mode = route(path)
    if mode is None:
        await ws.close(code=4004, reason="unknown_route")
        return
    host = ws.request_headers.get("Host", "")
    authz = ws.request_headers.get("Authorization", "")
    result = authorize(host, authz, registry=registry, base_domain=settings.gateway_base_domain)
    if not result.ok:
        await ws.close(code=4001, reason=result.reason)
        return
    first = await ws.recv()
    hs = parse_handshake(first if isinstance(first, str) else "")
    identity_json = json.dumps(hs.get("identity") or {}, ensure_ascii=False)
    call_id = str(hs.get("call_id") or "call")
    if mode == "voice":
        await _bridge_voice(ws, settings, result.tenant_id, identity_json, call_id)
    else:
        from noble_agent.gateway.chat_proxy import proxy_chat  # Task 10

        await proxy_chat(ws, settings, result.tenant_id, hs.get("identity") or {})
```

`_bridge_voice` (integration, pragma): dùng `build_dispatch_token(...)` để lấy `(jwt, url, room)`, join room bằng LiveKit client SDK như một participant, publish audio nhận từ `ws` và forward audio agent về `ws`. Chi tiết relay khớp `voice/service/protocol.py` (binary=PCM16, text=JSON control) — smoke, không unit.

`pyproject.toml` `[project.scripts]`: thêm `noble-gateway = "noble_agent.gateway.server:run_gateway"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_server_routing.py -v && pip install -e . >/dev/null && which noble-gateway`
Expected: PASS (2 tests); `noble-gateway` resolves.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/server.py pyproject.toml tests/unit/gateway/test_server_routing.py
git commit -m "feat(gateway): WS server routing + handshake + voice-bridge skeleton + noble-gateway script"
```

---

## Task 10: Chat reverse-proxy (+ inject `set_customer`)

**Files:**
- Create: `src/noble_agent/gateway/chat_proxy.py`
- Test: `tests/unit/gateway/test_chat_proxy.py`

**Interfaces:**
- Consumes: settings (`worker_chat_internal_url_template`, `gateway_worker_secret`), the worker's existing `/chat` `set_customer` message contract (`{"type":"set_customer","identity":{...}}`).
- Produces:
  - `worker_chat_url(tenant_id: str, settings) -> str`
  - `first_messages(identity: dict) -> list[str]` — the JSON message(s) the gateway sends to the worker before relaying client traffic (a `set_customer` when identity is non-empty, else nothing).
  - `proxy_chat(client_ws, settings, tenant_id, identity)` — connect to worker `/chat`, send `first_messages`, then bi-directional relay (integration, pragma).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_chat_proxy.py
from types import SimpleNamespace
from noble_agent.gateway.chat_proxy import worker_chat_url, first_messages
import json

def test_worker_chat_url():
    s = SimpleNamespace(worker_chat_internal_url_template="ws://agent-{tenant_id}:8766/chat")
    assert worker_chat_url("t1", s) == "ws://agent-t1:8766/chat"

def test_first_messages_seeds_identity():
    msgs = first_messages({"full_name": "An", "phone": "090"})
    assert len(msgs) == 1
    d = json.loads(msgs[0])
    assert d["type"] == "set_customer" and d["identity"]["full_name"] == "An"

def test_first_messages_empty_identity():
    assert first_messages({}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_chat_proxy.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/gateway/chat_proxy.py
"""Chat reverse-proxy: verify at the gateway, then pipe the provider WS to the
tenant worker's existing /chat handler. Identity is seeded by sending the
worker's own `set_customer` message first — so the worker's chat path needs no
change for slice #2."""
from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger("gateway")


def worker_chat_url(tenant_id: str, settings) -> str:
    return settings.worker_chat_internal_url_template.format(tenant_id=tenant_id)


def first_messages(identity: dict) -> list[str]:
    if not identity:
        return []
    return [json.dumps({"type": "set_customer", "identity": identity}, ensure_ascii=False)]


async def proxy_chat(client_ws, settings, tenant_id: str, identity: dict) -> None:  # pragma: no cover — integration
    import websockets

    url = worker_chat_url(tenant_id, settings)
    headers = {}
    if settings.gateway_worker_secret:
        headers["X-Gateway-Secret"] = settings.gateway_worker_secret
    async with websockets.connect(url, additional_headers=headers) as worker_ws:
        for msg in first_messages(identity):
            await worker_ws.send(msg)

        async def c2w():
            async for m in client_ws:
                await worker_ws.send(m)

        async def w2c():
            async for m in worker_ws:
                await client_ws.send(m)

        await asyncio.gather(c2w(), w2c(), return_exceptions=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_chat_proxy.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/chat_proxy.py tests/unit/gateway/test_chat_proxy.py
git commit -m "feat(gateway): chat reverse-proxy + set_customer identity seeding"
```

---

## Task 11: Worker touch — voice identity seed + tenant agent_name

**Files:**
- Modify: `src/noble_agent/server/app_session.py` (trích `identity_to_fields`)
- Modify: `src/noble_agent/transport/livekit/worker.py:189-205,226`
- Test: `tests/unit/gateway/test_worker_identity_seed.py`

**Interfaces:**
- Consumes: `agent_dispatch_name` (T1), `StateRepo` (existing), `Customer` (existing).
- Produces: `app_session.identity_to_fields(identity: dict) -> dict` (extracted, pure) — the exact mapping `provision_session` uses (full_name→name+full_name, phone, gender via `_normalize_gender`, is_noble_customer bool, folded `noble_info`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gateway/test_worker_identity_seed.py
from noble_agent.server.app_session import identity_to_fields

def test_identity_to_fields_maps_like_provision():
    fields = identity_to_fields({"full_name": "An", "phone": "090", "gender": "nam",
                                 "is_noble_customer": True, "email": "a@b.c"})
    assert fields["full_name"] == "An" and fields["name"] == "An"
    assert fields["phone"] == "090" and fields["gender"] == "M"
    assert fields["is_noble_customer"] is True and "email: a@b.c" in fields["noble_info"]

def test_identity_to_fields_empty():
    assert identity_to_fields({}) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_worker_identity_seed.py -v`
Expected: FAIL — `ImportError: cannot import name 'identity_to_fields'`

- [ ] **Step 3: Write minimal implementation**

Trong `app_session.py`, trích hàm thuần (đặt trước `provision_session`) và gọi lại từ trong `provision_session` (thay block dòng 91-104):

```python
def identity_to_fields(identity: dict) -> dict:
    """Map the app/provider `identity` shape onto Customer fields. Pure; shared
    by provision_session (chat), the /chat set_customer handler, and the LiveKit
    worker's voice identity seed."""
    fields: dict = {}
    if identity.get("full_name"):
        fields["full_name"] = identity["full_name"]
        fields["name"] = identity["full_name"]
    if identity.get("phone"):
        fields["phone"] = identity["phone"]
    gender = _normalize_gender(identity.get("gender"))
    if gender:
        fields["gender"] = gender
    if isinstance(identity.get("is_noble_customer"), bool):
        fields["is_noble_customer"] = identity["is_noble_customer"]
    noble_info = _compose_noble_info(identity)
    if noble_info:
        fields["noble_info"] = noble_info
    return fields
```

Trong `provision_session`, thay build thủ công bằng: `fields = {"noble_user_id": noble_user_id, **identity_to_fields(identity)}`.

Trong `worker.py` `entrypoint`, sau `caller = await ctx.wait_for_participant()` (dòng ~184-189), seed Customer từ metadata:

```python
    # Slice #2: gateway puts the end-user identity in the caller's participant
    # metadata (JSON). Seed Customer before the session starts so the frozen
    # customer block picks it up — same field mapping as app_session.
    import json as _json

    from noble_agent.server.app_session import identity_to_fields
    from noble_agent.storage.models import Customer
    from noble_agent.storage.redis_client import get_redis
    from noble_agent.storage.repo import StateRepo

    try:
        identity = _json.loads(caller.metadata) if getattr(caller, "metadata", "") else {}
    except (ValueError, TypeError):
        identity = {}
    if isinstance(identity, dict) and identity:
        fields = identity_to_fields(identity)
        if fields:
            redis = await get_redis()
            repo = StateRepo(redis_client=redis, ttl_seconds=settings.session_ttl_seconds)
            meta, customer, state = await repo.load(ctx.room.name)
            merged = customer.model_dump()
            for k, v in fields.items():
                if isinstance(v, bool) or v:
                    merged[k] = v
            await repo.save_all(ctx.room.name, meta, Customer.model_validate(merged), state)
```

Đổi đăng ký agent_name (dòng 226): `agent_name=agent_dispatch_name(settings.tenant_id),` (thêm `from noble_agent.tenant.naming import agent_dispatch_name` ở đầu `worker.py`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/gateway/test_worker_identity_seed.py tests/unit/unified/test_simulate_customer.py -v`
Expected: PASS; `app_session`/simulate tests không hồi quy.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/app_session.py src/noble_agent/transport/livekit/worker.py tests/unit/gateway/test_worker_identity_seed.py
git commit -m "feat(worker): voice identity seed from caller metadata + tenant agent_name"
```

---

## Task 12: Docs — .env.example, CLAUDE.md changelog, SMOKE.md

**Files:**
- Modify: `.env.example`, `CLAUDE.md`, `src/noble_agent/SMOKE.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: `.env.example`** — thêm block:

```bash
# ── SaaS slice #2: provider-facing gateway ─────────────────────────────
TENANT_ENDPOINT_TEMPLATE=wss://{tenant_id}.agents.noblex.vn
GATEWAY_BASE_DOMAIN=agents.noblex.vn
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=9200
GATEWAY_CRED_CACHE_TTL_SEC=30
GATEWAY_WORKER_SECRET=
WORKER_CHAT_INTERNAL_URL_TEMPLATE=ws://agent-{tenant_id}:8766/chat
```

- [ ] **Step 2: `CLAUDE.md`** — thêm 1 dòng Change Log (2026-07-29, SaaS slice #2): gateway nhận-diện-tenant + credential per-tenant; voice bridge vào LiveKit, chat reverse-proxy; worker chạm tối thiểu (agent_name + voice metadata seed); default-off (không tenant nào trỏ gateway → path cũ nguyên vẹn). Tham chiếu spec + plan này.

- [ ] **Step 3: `SMOKE.md`** — thêm mục smoke slice #2:
  - `noble-tenant create t1 --dir ... --status active && noble-tenant issue-cred t1` → nhận `tnt_...`.
  - Voice: provider WS `/v1/stream` (Host `t1.<base>`, Bearer) → nghe agent nói; dispatch `agent-t1`; cross-tenant cred → 4001.
  - Chat: provider WS `/v1/chat` → token/tool_done; identity seed phản ánh lượt đầu.

- [ ] **Step 4: Verify docs render + full gate**

Run: `make lint && make test-unit 2>&1 | tail -5`
Expected: ruff sạch trên file mới; failures chỉ trong baseline đã biết (Global Constraints).

- [ ] **Step 5: Commit**

```bash
git add .env.example CLAUDE.md src/noble_agent/SMOKE.md
git commit -m "docs: record SaaS slice #2 (provider gateway) in CLAUDE.md + SMOKE + .env.example"
```

---

## Self-Review

**1. Spec coverage:**
- §2 Credential model → T2, T3, T4. ✓
- §3 Provisioning (issue/revoke/list/endpoint) + CLI → T4, T5. ✓
- §4.3 Gateway (Host→tenant, verify from cache, voice bridge, chat proxy, handshake, no-execution) → T6, T7, T8, T9, T10. ✓
- §4.4 Worker touch (agent_name + 6b voice seed) → T11. ✓ (chat seed = gateway `set_customer`, T10 — worker chat unchanged, khớp phát hiện code.)
- §4.5 Settings → T1, T12. ✓
- §5 Invariants (offline verify/E01, no-execution, isolation) → T6 (cache), T7 (per-tenant), T9 (no tenant-code import). ✓
- §6 Out of scope (SIP, native-LiveKit fast-path, SP-C/D/E) → không có task (đúng). ✓
- §7 Testing → mỗi task có unit; relay/`run_gateway` là smoke (SMOKE.md, T12) — ghi rõ pragma. ✓

**2. Placeholder scan:** không có TBD/TODO; các phần integration (`_serve`/`_bridge_voice`/`proxy_chat` relay/`run_gateway`) đánh dấu `# pragma: no cover — integration` có chủ đích, đã có khung code thật + smoke ở T12, không phải placeholder logic.

**3. Type consistency:** `agent_dispatch_name(tenant_id)` (T1) dùng nhất quán T8/T11. `CredentialEntry` (T2) dùng T3/T4/T6/T7. `authorize(...).tenant_id/key_id` (T7) dùng T9. `identity_to_fields` (T11) dùng T9(chat set_customer contract)/T10/worker. `read_creds_raw/write_creds_raw` (T3) dùng T4/T6. Endpoint keys `voice`/`chat` (T4) khớp route (T9). Nhất quán.

**Rủi ro còn lại (ghi ở spec §8):** service discovery chat proxy (K8s), thu hồi credential trễ tối đa TTL, rate-limit hoãn. Định dạng khung audio WS relay chốt khi implement `_bridge_voice` theo `voice/service/protocol.py`.
