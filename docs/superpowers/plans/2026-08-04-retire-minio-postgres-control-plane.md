# Retire MinIO — Postgres control-plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khi `AGENT_CONFIG_SOURCE=db`, agent (gateway + worker + heartbeat) đọc control-plane trực tiếp từ Postgres, không dựng `MinioTenantStore` trên đường serving — trong khi đường legacy (`AGENT_CONFIG_SOURCE≠db`, in-wheel `noble`) giữ byte-identical.

**Architecture:** Một công tắc duy nhất `settings.agent_config_source=="db"` rẽ 4 mảnh (gateway credential, worker version, worker tenant-context/provider-source, heartbeat) sang lối đọc Postgres qua `tenant_conn` (RLS scope). Các bề mặt đọc là `agent_api.*` view do Portal ship (contract: `docs/handoff/agent-postgres-read-contract.md`); ghi duy nhất `control.agent_heartbeats`. Credential đổi từ salted-hash (MinIO) sang `sha256(plaintext)` trần (Portal). MinIO store + CLI giữ code, chỉ gỡ khỏi serving.

**Tech Stack:** Python 3.11+, asyncpg (lazy), pydantic-settings, websockets, pytest (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- Branch `feat/share-agent`. Commit local; **KHÔNG** push/PR/merge/`develop`.
- Đường legacy phải **byte-identical**: `agent_config_source` mặc định `"legacy"` ⇒ mọi nhánh mới bị bỏ qua, MinIO chạy như cũ. In-wheel `noble` (id không hợp lệ org) né `org_of`.
- RLS: agent connect role chung `odyssey_agent`; mỗi txn scope qua `tenant_conn(pool, tenant_id)`. KHÔNG sửa SQL Portal-owned; chỉ đọc `agent_api.*` + ghi `control.agent_heartbeats`.
- Reader `storage/agent_config_store.py` gọi VIEW **không kèm schema** (`FROM agent_published_config`) — GIỮ NGUYÊN, không sửa.
- Credential db-path: băm `sha256(plaintext)` trần (hex), **bỏ** ràng buộc prefix `tnt_`.
- GUC: `tenant_conn` set **cả** `app.current_tenant` **và** `app.tenant_id` (cùng giá trị) mỗi txn.
- ruff sạch trên file đụng; đừng sửa lint có sẵn ngoài phạm vi. TDD, commit nhỏ, mỗi task 1 deliverable test được.
- Sau khi land: cập nhật `CLAUDE.md` (mục storage/flows + Change Log) trong Slice D. Chạy `src/noble_agent/SMOKE.md` sau khi đụng gateway/turn-loop/transport.
- Ruff/pytest chạy trong venv: `source .venv/bin/activate`.

---

## File Structure

**Tạo mới:**
- `src/noble_agent/storage/agent_control_store.py` — reader `agent_api.tenant_status` / `tenant_keys` / `deployments` (Postgres control-plane, RLS).
- `src/noble_agent/gateway/pg_registry.py` — `PostgresCredentialRegistry` (is_active + verify_bearer, TTL cache).
- `src/noble_agent/tenant/db_context.py` — `context_from_config` + db-context cache cho provider-source.
- `src/noble_agent/tenant/pg_heartbeat.py` — `PgHeartbeatWriter` + `PgHeartbeatSupervisor` + `ActiveTenantTracker`.
- Tests tương ứng dưới `tests/unit/{storage,gateway,tenant}/`.

**Sửa:**
- `src/noble_agent/storage/postgres_client.py` — `tenant_conn` set 2 GUC.
- `src/noble_agent/gateway/auth.py` — dùng `registry.verify_bearer` (bỏ nhánh `credentials.verify` trực tiếp).
- `src/noble_agent/gateway/registry.py` — thêm `verify_bearer` cho `CredentialRegistry` (MinIO, giữ hành vi salted).
- `src/noble_agent/gateway/server.py` — chọn registry theo `agent_config_source`.
- `src/noble_agent/agent/facade.py` — `_resolve_current_version` async + nhánh db; `_build_runner_for_version` nhánh db.
- `src/noble_agent/tenant/loader.py` — `get_tenant_context` nhánh db (không MinIO).
- `src/noble_agent/data/providers/__init__.py` — `_active_source` an toàn ở db-mode (không cần MinIO).
- `src/noble_agent/tenant/heartbeat.py` — `should_emit` cho db-mode.
- `src/noble_agent/server/http.py` + `src/noble_agent/transport/livekit/worker.py` — chọn supervisor Postgres ở db-mode (kind chat/voice).
- `CLAUDE.md` — mục storage/flows + Change Log (Slice D).

---

## FOUNDATION

### Task F1: `tenant_conn` set cả hai GUC (`app.current_tenant` + `app.tenant_id`)

**Files:**
- Modify: `src/noble_agent/storage/postgres_client.py:56-67`
- Test: `tests/unit/storage/test_tenant_conn_guc.py` (create)

**Interfaces:**
- Produces: `tenant_conn(pool, tenant_id)` — không đổi signature; nay set 2 GUC. Slice A/B/C dựa vào việc `app.tenant_id` được set để RLS Portal-owned bind đúng.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/storage/test_tenant_conn_guc.py
import pytest
from noble_agent.storage.postgres_client import tenant_conn


class _FakeConn:
    def __init__(self): self.calls = []
    def transaction(self):
        conn = self
        class _Txn:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Txn()
    async def execute(self, sql, *args): self.calls.append((sql, args))


class _FakePool:
    def __init__(self, conn): self._conn = conn
    def acquire(self):
        conn = self._conn
        class _Acq:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Acq()


async def test_tenant_conn_sets_both_gucs():
    conn = _FakeConn()
    async with tenant_conn(_FakePool(conn), "t1") as c:
        assert c is conn
    guc_calls = [args[0] for sql, args in conn.calls if "set_config" in sql]
    keys = [sql.split("'")[1] for sql, _ in conn.calls if "set_config" in sql]
    assert set(keys) == {"app.current_tenant", "app.tenant_id"}
    assert all(a == "t1" for a in guc_calls)
```

- [ ] **Step 2: Chạy để xác nhận fail**

Run: `source .venv/bin/activate && pytest tests/unit/storage/test_tenant_conn_guc.py -v`
Expected: FAIL (chỉ set `app.current_tenant`).

- [ ] **Step 3: Sửa `tenant_conn`**

```python
# postgres_client.py — trong tenant_conn, thay 1 dòng set_config bằng 2:
            await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
```
Cập nhật docstring: "sets BOTH `app.current_tenant` (agent-owned data-plane RLS) and `app.tenant_id` (Portal-owned control-plane RLS)".

- [ ] **Step 4: Chạy test pass**

Run: `pytest tests/unit/storage/test_tenant_conn_guc.py -v` → PASS.
Regression: `pytest tests/unit/unified/providers -q` (đường pg_kb dùng tenant_conn) — 0 new fail.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/storage/postgres_client.py tests/unit/storage/test_tenant_conn_guc.py
git commit -m "feat(pg): tenant_conn sets both app.current_tenant and app.tenant_id GUCs"
```

---

## SLICE A — Gateway credential từ Postgres

### Task A1: control-store reader (`tenant_status` + `tenant_keys`)

**Files:**
- Create: `src/noble_agent/storage/agent_control_store.py`
- Test: `tests/unit/storage/test_agent_control_store.py`

**Interfaces:**
- Produces:
  - `async read_tenant_active(tenant_id, *, pool=None) -> bool` — đọc `agent_api.tenant_status`; 0 dòng → False.
  - `async read_tenant_key_hashes(tenant_id, *, pool=None) -> set[str]` — sha256 của các key `active=true` từ `agent_api.tenant_keys`.
  - `async read_deployment_id(tenant_id, kind, *, pool=None) -> int | None` — id lớn nhất trong `agent_api.deployments` khớp `kind`.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/storage/test_agent_control_store.py
import pytest
from noble_agent.storage import agent_control_store as acs


class _Conn:
    def __init__(self, rows_by_sql): self._rows = rows_by_sql
    def transaction(self):
        c = self
        class _T:
            async def __aenter__(self): return c
            async def __aexit__(self, *a): return False
        return _T()
    async def execute(self, *a): pass
    async def fetchval(self, sql, *a):
        return self._rows.get(("val", sql.split()[3] if len(sql.split()) > 3 else sql))
    async def fetch(self, sql, *a): return self._rows.get("keys", [])
    async def fetchrow(self, sql, *a): return self._rows.get("row")


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self):
        c = self._c
        class _A:
            async def __aenter__(self): return c
            async def __aexit__(self, *a): return False
        return _A()


async def test_read_tenant_active_true():
    conn = _Conn({"row": {"active": True}})
    assert await acs.read_tenant_active("t1", pool=_Pool(conn)) is True


async def test_read_tenant_active_no_row_false():
    conn = _Conn({"row": None})
    assert await acs.read_tenant_active("t1", pool=_Pool(conn)) is False


async def test_read_tenant_key_hashes():
    conn = _Conn({"keys": [{"key_sha256": "aa", "active": True},
                           {"key_sha256": "bb", "active": False}]})
    assert await acs.read_tenant_key_hashes("t1", pool=_Pool(conn)) == {"aa"}


async def test_read_deployment_id_picks_max():
    conn = _Conn({"row": {"id": 7}})
    assert await acs.read_deployment_id("t1", "chat", pool=_Pool(conn)) == 7
```

- [ ] **Step 2: Chạy fail**

Run: `pytest tests/unit/storage/test_agent_control_store.py -v` → FAIL (module chưa có).

- [ ] **Step 3: Viết reader**

```python
# src/noble_agent/storage/agent_control_store.py
"""Đọc control-plane Portal cho gateway auth + heartbeat, qua các view
agent_api.* (RLS scope theo current_tenant). Contract: docs/handoff/
agent-postgres-read-contract.md."""
from __future__ import annotations

import logging

logger = logging.getLogger("noble_agent.storage.agent_control")

_SQL_STATUS = "SELECT active FROM agent_api.tenant_status WHERE tenant_id = $1"
_SQL_KEYS = "SELECT key_sha256, active FROM agent_api.tenant_keys WHERE tenant_id = $1"
_SQL_DEPLOY = ("SELECT id FROM agent_api.deployments WHERE tenant_id = $1 AND kind = $2 "
               "ORDER BY id DESC LIMIT 1")


async def _pool(pool):
    if pool is not None:
        return pool
    from noble_agent.storage.postgres_client import get_pool
    return await get_pool()


async def read_tenant_active(tenant_id: str, *, pool=None) -> bool:
    from noble_agent.storage.postgres_client import tenant_conn
    p = await _pool(pool)
    async with tenant_conn(p, tenant_id) as conn:
        row = await conn.fetchrow(_SQL_STATUS, tenant_id)
    return bool(row and row["active"])


async def read_tenant_key_hashes(tenant_id: str, *, pool=None) -> set[str]:
    from noble_agent.storage.postgres_client import tenant_conn
    p = await _pool(pool)
    async with tenant_conn(p, tenant_id) as conn:
        rows = await conn.fetch(_SQL_KEYS, tenant_id)
    return {r["key_sha256"] for r in rows if r["active"]}


async def read_deployment_id(tenant_id: str, kind: str, *, pool=None) -> int | None:
    from noble_agent.storage.postgres_client import tenant_conn
    p = await _pool(pool)
    async with tenant_conn(p, tenant_id) as conn:
        row = await conn.fetchrow(_SQL_DEPLOY, tenant_id, kind)
    return int(row["id"]) if row else None
```

- [ ] **Step 4: Chạy pass**

Run: `pytest tests/unit/storage/test_agent_control_store.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/storage/agent_control_store.py tests/unit/storage/test_agent_control_store.py
git commit -m "feat(pg): agent_control_store reader for tenant_status/tenant_keys/deployments"
```

### Task A2: `PostgresCredentialRegistry`

**Files:**
- Create: `src/noble_agent/gateway/pg_registry.py`
- Test: `tests/unit/gateway/test_pg_registry.py`

**Interfaces:**
- Consumes: `agent_control_store.read_tenant_active`, `read_tenant_key_hashes` (Task A1).
- Produces: `PostgresCredentialRegistry(ttl_sec, *, clock=time.monotonic, reader=agent_control_store)` với **async** `is_active(tenant)->bool` + **async** `verify_bearer(tenant, plaintext)->str|None` (trả key_id = 12 hex đầu của sha256, hoặc None). TTL-cache key-hash set per tenant.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/gateway/test_pg_registry.py
import hashlib
import pytest
from noble_agent.gateway.pg_registry import PostgresCredentialRegistry


class _FakeReader:
    def __init__(self, active, hashes):
        self._active, self._hashes = active, hashes
        self.key_calls = 0
    async def read_tenant_active(self, tenant_id, *, pool=None): return self._active
    async def read_tenant_key_hashes(self, tenant_id, *, pool=None):
        self.key_calls += 1
        return set(self._hashes)


def _sha(tok): return hashlib.sha256(tok.encode()).hexdigest()


async def test_is_active_delegates():
    reg = PostgresCredentialRegistry(30, reader=_FakeReader(True, set()))
    assert await reg.is_active("t1") is True
    reg2 = PostgresCredentialRegistry(30, reader=_FakeReader(False, set()))
    assert await reg2.is_active("t1") is False


async def test_verify_bearer_matches_sha256_plain():
    tok = "whatever-portal-token"
    reg = PostgresCredentialRegistry(30, reader=_FakeReader(True, {_sha(tok)}))
    assert await reg.verify_bearer("t1", tok) == _sha(tok)[:12]
    assert await reg.verify_bearer("t1", "wrong") is None


async def test_verify_bearer_ttl_cache():
    reader = _FakeReader(True, {_sha("x")})
    t = [0.0]
    reg = PostgresCredentialRegistry(30, reader=reader, clock=lambda: t[0])
    await reg.verify_bearer("t1", "x"); await reg.verify_bearer("t1", "x")
    assert reader.key_calls == 1  # cached
    t[0] = 31.0
    await reg.verify_bearer("t1", "x")
    assert reader.key_calls == 2  # expired → refetch
```

- [ ] **Step 2: Chạy fail** → module chưa có.

- [ ] **Step 3: Viết registry**

```python
# src/noble_agent/gateway/pg_registry.py
"""Gateway credential registry đọc Postgres control-plane (db-mode).

is_active + verify_bearer khớp bề mặt CredentialRegistry (MinIO) để auth.authorize
dùng chung. Verify = sha256(plaintext) trần so với agent_api.tenant_keys (TTL-cache
per tenant). Bất kỳ lỗi DB nào → coi như không hợp lệ (fail-closed, log)."""
from __future__ import annotations

import hashlib
import logging
import time

logger = logging.getLogger("gateway.pg_registry")


class PostgresCredentialRegistry:
    def __init__(self, ttl_sec: float, *, clock=time.monotonic, reader=None):
        if reader is None:
            from noble_agent.storage import agent_control_store as reader
        self._reader = reader
        self._ttl = ttl_sec
        self._clock = clock
        self._cache: dict[str, tuple[float, set[str]]] = {}

    async def is_active(self, tenant_id: str) -> bool:
        try:
            return await self._reader.read_tenant_active(tenant_id)
        except Exception:
            logger.warning("pg_registry: is_active read failed for %s", tenant_id, exc_info=True)
            return False

    async def _hashes(self, tenant_id: str) -> set[str]:
        now = self._clock()
        hit = self._cache.get(tenant_id)
        if hit is not None and (now - hit[0]) < self._ttl:
            return hit[1]
        hashes = await self._reader.read_tenant_key_hashes(tenant_id)
        self._cache[tenant_id] = (now, hashes)
        return hashes

    async def verify_bearer(self, tenant_id: str, plaintext: str) -> str | None:
        if not plaintext:
            return None
        digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        try:
            hashes = await self._hashes(tenant_id)
        except Exception:
            logger.warning("pg_registry: key read failed for %s", tenant_id, exc_info=True)
            return None
        return digest[:12] if digest in hashes else None
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/gateway/test_pg_registry.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/pg_registry.py tests/unit/gateway/test_pg_registry.py
git commit -m "feat(gateway): PostgresCredentialRegistry (sha256-plain verify, TTL cache)"
```

### Task A3: `auth.authorize` dùng `verify_bearer` (+ MinIO registry giữ hành vi)

**Files:**
- Modify: `src/noble_agent/gateway/auth.py:80-88`, `src/noble_agent/gateway/registry.py`
- Test: `tests/unit/gateway/test_auth.py` (cập nhật), `tests/unit/gateway/test_registry.py` (thêm verify_bearer)

**Interfaces:**
- Consumes: registry với **async** `is_active` + **async** `verify_bearer` (A2), hoặc MinIO registry (đồng bộ → bọc). `authorize` phải **async** để await registry.
- Produces: `async authorize(host, authorization, *, registry, base_domain) -> AuthResult` — logic + reason-codes không đổi; verify qua `registry.verify_bearer(tenant, plaintext)`.

> **Lưu ý MinIO registry (đồng bộ) vs PG registry (async):** để `authorize` await được cả hai, thêm `verify_bearer` async trên CẢ hai; MinIO `is_active`/`verify_bearer` bọc phần đồng bộ. `_handle` (server.py) đã await `authorize` (Task A4).

- [ ] **Step 1: Cập nhật test (fail)**

```python
# tests/unit/gateway/test_registry.py — thêm:
async def test_minio_registry_verify_bearer(...):
    # store trả 1 CredentialEntry hợp lệ cho "tnt_abc"
    reg = CredentialRegistry(fake_store, ttl_sec=30)
    assert await reg.verify_bearer("t1", "tnt_abc") == "<key_id>"
    assert await reg.verify_bearer("t1", "tnt_wrong") is None
```
```python
# tests/unit/gateway/test_auth.py — đổi sang async + registry có verify_bearer:
class _Reg:
    def __init__(self, active, keyid): self._a, self._k = active, keyid
    async def is_active(self, t): return self._a
    async def verify_bearer(self, t, p): return self._k if p == "good" else None

async def test_authorize_ok():
    r = await authorize("t1.agents.noblex.vn", "Bearer good", registry=_Reg(True, "k1"),
                        base_domain="agents.noblex.vn")
    assert r.ok and r.tenant_id == "t1" and r.key_id == "k1"

async def test_authorize_bad_credential():
    r = await authorize("t1.agents.noblex.vn", "Bearer bad", registry=_Reg(True, None),
                        base_domain="agents.noblex.vn")
    assert not r.ok and r.reason == "bad_credential"

async def test_authorize_inactive():
    r = await authorize("t1.agents.noblex.vn", "Bearer good", registry=_Reg(False, "k1"),
                        base_domain="agents.noblex.vn")
    assert not r.ok and r.reason == "tenant_inactive"
```

- [ ] **Step 2: Chạy fail** → `authorize` chưa async / MinIO chưa có verify_bearer.

- [ ] **Step 3: Sửa code**

```python
# gateway/registry.py — thêm 2 method async (giữ salted verify):
    async def is_active(self, tenant_id: str) -> bool:   # đổi thành async
        meta = self._store.read_meta(tenant_id)
        return meta is not None and meta.status == "active"

    async def verify_bearer(self, tenant_id: str, plaintext: str) -> str | None:
        e = credentials.verify(plaintext, self.entries_for(tenant_id))
        return e.key_id if e is not None else None
```
```python
# gateway/auth.py — authorize thành async, đổi block verify:
async def authorize(host, authorization, *, registry, base_domain) -> AuthResult:
    tenant = tenant_from_host(host, base_domain)
    if tenant is None:
        return AuthResult(False, reason="bad_host")
    if not await registry.is_active(tenant):
        return AuthResult(False, tenant_id=tenant, reason="tenant_inactive")
    if not authorization or not authorization.startswith(_BEARER):
        return AuthResult(False, tenant_id=tenant, reason="no_bearer")
    plaintext = authorization[len(_BEARER):]
    key_id = await registry.verify_bearer(tenant, plaintext)
    if key_id is None:
        return AuthResult(False, tenant_id=tenant, reason="bad_credential")
    return AuthResult(True, tenant_id=tenant, key_id=key_id)
```
Bỏ `from noble_agent.tenant import credentials` khỏi auth.py nếu orphaned.

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/gateway/test_auth.py tests/unit/gateway/test_registry.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/auth.py src/noble_agent/gateway/registry.py tests/unit/gateway/test_auth.py tests/unit/gateway/test_registry.py
git commit -m "refactor(gateway): authorize via async registry.verify_bearer (unify MinIO + PG)"
```

### Task A4: `server.py` chọn registry theo `agent_config_source` + await authorize

**Files:**
- Modify: `src/noble_agent/gateway/server.py:66-77` (`run_gateway`) + `:102` (`_handle` await authorize)
- Test: `tests/unit/gateway/test_registry_selection.py`

**Interfaces:**
- Consumes: `PostgresCredentialRegistry` (A2), `CredentialRegistry` (A3).
- Produces: `build_registry(settings)` — hàm thuần trả registry đúng loại theo `settings.agent_config_source`.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/gateway/test_registry_selection.py
from types import SimpleNamespace
from noble_agent.gateway.server import build_registry
from noble_agent.gateway.pg_registry import PostgresCredentialRegistry
from noble_agent.gateway.registry import CredentialRegistry


def _s(source, **kw):
    return SimpleNamespace(agent_config_source=source, gateway_cred_cache_ttl_sec=30.0,
                           minio_endpoint="http://x", tenant_bucket="b",
                           minio_root_user="u", minio_root_password="p", **kw)

def test_build_registry_db_mode():
    assert isinstance(build_registry(_s("db")), PostgresCredentialRegistry)

def test_build_registry_legacy_mode(monkeypatch):
    # legacy dựng MinIO store — patch để không cần boto3 live
    monkeypatch.setattr("noble_agent.tenant.store.MinioTenantStore.from_settings",
                        staticmethod(lambda s: object()))
    assert isinstance(build_registry(_s("legacy")), CredentialRegistry)
```

- [ ] **Step 2: Chạy fail** → `build_registry` chưa có.

- [ ] **Step 3: Viết `build_registry` + rẽ nhánh + await**

```python
# gateway/server.py — thêm hàm + dùng trong run_gateway:
def build_registry(settings):
    if settings.agent_config_source == "db":
        from noble_agent.gateway.pg_registry import PostgresCredentialRegistry
        return PostgresCredentialRegistry(settings.gateway_cred_cache_ttl_sec)
    from noble_agent.gateway.registry import CredentialRegistry
    from noble_agent.tenant.store import MinioTenantStore
    return CredentialRegistry(MinioTenantStore.from_settings(settings),
                              ttl_sec=settings.gateway_cred_cache_ttl_sec)

# run_gateway(): registry = build_registry(settings)
# _handle(): result = await authorize(host, authz, registry=registry, base_domain=...)
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/gateway/test_registry_selection.py -v`; `pytest tests/unit/gateway -q` 0 new fail.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/server.py tests/unit/gateway/test_registry_selection.py
git commit -m "feat(gateway): select PG vs MinIO credential registry by AGENT_CONFIG_SOURCE"
```

---

## SLICE B — Worker tenant-context + version từ Postgres

### Task B1: `context_from_config` + db-context cache

**Files:**
- Create: `src/noble_agent/tenant/db_context.py`
- Test: `tests/unit/tenant/test_db_context.py`

**Interfaces:**
- Consumes: `agent.agent_config.AgentConfig` (đã có), `tenant.context.TenantContext` (đã có).
- Produces:
  - `context_from_config(tenant_id: str, cfg: AgentConfig, *, skeleton_dir: Path) -> TenantContext`.
  - `set_db_context(tenant_id, ctx)` / `get_db_context(tenant_id) -> TenantContext | None` (cache module-level cho provider-source).
  - `default_db_context(tenant_id, *, skeleton_dir) -> TenantContext` (data_source="pg_kb", enabled_tools=()).

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/tenant/test_db_context.py
from pathlib import Path
from noble_agent.agent.agent_config import parse_config
from noble_agent.tenant.db_context import (
    context_from_config, set_db_context, get_db_context, default_db_context)

SK = Path("/tmp/skeleton")

def test_context_from_config_maps_fields():
    cfg = parse_config({"tools": {"enabled": ["recommend_units", "booking"], "feng_shui": True,
                                  "media_channel": "noblex_app"},
                        "identity": {"brand": "An Phú"}, "data_source": "pg_kb"})
    ctx = context_from_config("org_1_t", cfg, skeleton_dir=SK)
    assert ctx.tenant_id == "org_1_t"
    assert ctx.data_source == "pg_kb"
    assert "recommend_units" in ctx.enabled_tools and "escalate" in ctx.enabled_tools
    assert ctx.rankers == frozenset({"feng_shui"})
    assert ctx.media_channel == "noblex_app"
    assert ctx.brand == {"company": "An Phú", "app_name": "An Phú"}
    assert ctx.persona_dir == SK

def test_feng_shui_off_no_ranker():
    cfg = parse_config({"tools": {"enabled": ["booking"], "feng_shui": True}})
    ctx = context_from_config("t", cfg, skeleton_dir=SK)
    assert ctx.rankers == frozenset()  # recommend_units off → feng_shui dropped by parse_config

def test_db_context_cache_roundtrip():
    ctx = default_db_context("t9", skeleton_dir=SK)
    assert ctx.data_source == "pg_kb" and ctx.enabled_tools == ()
    set_db_context("t9", ctx)
    assert get_db_context("t9") is ctx
```

- [ ] **Step 2: Chạy fail** → module chưa có.

- [ ] **Step 3: Viết module**

```python
# src/noble_agent/tenant/db_context.py
"""Dựng TenantContext từ published config (db-mode) — thay manifest.toml MinIO.

Cache per-tenant để provider-factory (_active_source) đọc data_source ở request-time
mà không cần MinIO. brand map từ config.identity.brand → {company, app_name}
(build_schemas/load_agent_def dùng shape này)."""
from __future__ import annotations

from pathlib import Path

from noble_agent.agent.agent_config import AgentConfig
from noble_agent.tenant.context import TenantContext

_db_ctx: dict[str, TenantContext] = {}


def context_from_config(tenant_id: str, cfg: AgentConfig, *, skeleton_dir: Path) -> TenantContext:
    brand = {"company": cfg.identity.brand, "app_name": cfg.identity.brand}
    rankers = frozenset({"feng_shui"}) if cfg.feng_shui else frozenset()
    return TenantContext(
        tenant_id=tenant_id,
        data_source=cfg.data_source or "pg_kb",
        persona_dir=skeleton_dir,
        enabled_tools=cfg.enabled_tools,
        rankers=rankers,
        media_channel=cfg.media_channel,
        brand=brand,
    )


def default_db_context(tenant_id: str, *, skeleton_dir: Path) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, data_source="pg_kb",
                         persona_dir=skeleton_dir, enabled_tools=())


def set_db_context(tenant_id: str, ctx: TenantContext) -> None:
    _db_ctx[tenant_id] = ctx


def get_db_context(tenant_id: str) -> TenantContext | None:
    return _db_ctx.get(tenant_id)


def reset_db_context_for_tests() -> None:
    _db_ctx.clear()
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/tenant/test_db_context.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/db_context.py tests/unit/tenant/test_db_context.py
git commit -m "feat(tenant): context_from_config + db-context cache (replaces MinIO manifest in db-mode)"
```

### Task B2: `get_tenant_context` + `_active_source` an toàn ở db-mode

**Files:**
- Modify: `src/noble_agent/tenant/loader.py:132-147` (`get_tenant_context`)
- Test: `tests/unit/tenant/test_get_tenant_context_db.py`

**Interfaces:**
- Consumes: `db_context.get_db_context`, `default_db_context` (B1), `settings.agent_config_source`.
- Produces: `get_tenant_context()` db-mode → cached db-context (nếu có) hoặc `default_db_context` (không đụng MinIO/manifest). `_active_source` (providers) không đổi — nó gọi `get_tenant_context().data_source`, nay trả "pg_kb" ở db-mode.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/tenant/test_get_tenant_context_db.py
import pytest
from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests
from noble_agent.tenant.db_context import reset_db_context_for_tests, set_db_context, default_db_context
from noble_agent.tenant.current import use_tenant
from pathlib import Path

@pytest.fixture(autouse=True)
def _clean():
    reset_tenant_context_for_tests(); reset_db_context_for_tests(); yield
    reset_tenant_context_for_tests(); reset_db_context_for_tests()

def test_db_mode_no_minio_default(monkeypatch):
    from noble_agent import config
    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    # Không set_db_context → default pg_kb, KHÔNG gọi manifest/MinIO
    monkeypatch.setattr("noble_agent.tenant.loader._build_store",
                        lambda s: (_ for _ in ()).throw(AssertionError("MinIO touched")))
    with use_tenant("org_1_t"):
        ctx = get_tenant_context()
    assert ctx.data_source == "pg_kb"

def test_db_mode_returns_cached(monkeypatch):
    from noble_agent import config
    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    cached = default_db_context("org_1_t", skeleton_dir=Path("/tmp/sk"))
    set_db_context("org_1_t", cached)
    with use_tenant("org_1_t"):
        assert get_tenant_context() is cached
```

- [ ] **Step 2: Chạy fail** → hiện get_tenant_context đọc manifest → AssertionError/khác.

- [ ] **Step 3: Sửa `get_tenant_context`**

```python
# loader.py get_tenant_context() — thêm nhánh db TRƯỚC nhánh manifest:
def get_tenant_context() -> TenantContext:
    from noble_agent.config import get_settings
    from noble_agent.tenant.current import current_tenant

    tid = current_tenant()
    settings = get_settings()
    if getattr(settings, "agent_config_source", "legacy") == "db":
        from noble_agent.agent.facade import _skeleton_dir
        from noble_agent.tenant.db_context import default_db_context, get_db_context
        return get_db_context(tid) or default_db_context(tid, skeleton_dir=_skeleton_dir())

    ctx = _ctx_by_tenant.get(tid)
    if ctx is None:
        ctx = load_tenant(tid, get_settings())
        _ctx_by_tenant[tid] = ctx
    return ctx
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/tenant/test_get_tenant_context_db.py tests/unit/unified/providers/test_source_switch.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/loader.py tests/unit/tenant/test_get_tenant_context_db.py
git commit -m "feat(tenant): get_tenant_context db-mode reads db-context (no MinIO manifest)"
```

### Task B3: `_resolve_current_version` async + nhánh db (version từ VIEW)

**Files:**
- Modify: `src/noble_agent/agent/facade.py:317-348` (`_resolve_current_version`), `:505` (`create` await)
- Test: `tests/unit/unified/test_facade_version_db.py`

**Interfaces:**
- Consumes: `storage.agent_config_store.read_published_config` (đã có), `settings.agent_config_source`.
- Produces: `async _resolve_current_version(tenant_id) -> int` — db-mode: version của published config (0 nếu None). Legacy: giữ logic MinIO cũ y nguyên. `create()` await nó.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/unified/test_facade_version_db.py
import pytest
from noble_agent.agent import facade

async def test_resolve_version_db_mode(monkeypatch):
    from noble_agent import config
    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    async def _fake(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig
        return PublishedConfig(version=7, config={})
    monkeypatch.setattr(facade, "read_published_config", _fake)
    assert await facade._resolve_current_version("org_1_t") == 7

async def test_resolve_version_db_none_returns_0(monkeypatch):
    from noble_agent import config
    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    async def _none(tid, **kw): return None
    monkeypatch.setattr(facade, "read_published_config", _none)
    assert await facade._resolve_current_version("org_1_t") == 0
```

- [ ] **Step 2: Chạy fail** → hiện sync, không có nhánh db.

- [ ] **Step 3: Sửa**

```python
# facade.py — _resolve_current_version thành async, thêm nhánh db ở đầu:
async def _resolve_current_version(tenant_id: str) -> int:
    settings = get_settings()
    if settings.agent_config_source == "db":
        pc = await read_published_config(tenant_id)
        return pc.version if pc is not None else 0
    if not getattr(settings, "tenant_store_enabled", False):
        return 0
    # ... (giữ nguyên khối MinIO cũ: _build_store/read_pointer/current_published_version)
```
```python
# create(): version = await _resolve_current_version(tid)
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/unified/test_facade_version_db.py -v`; regression `pytest tests/unit/unified -k facade -q`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/facade.py tests/unit/unified/test_facade_version_db.py
git commit -m "feat(facade): resolve version from published config in db-mode (async)"
```

### Task B4: `_build_runner_for_version` nhánh db (ctx từ config, không MinIO)

**Files:**
- Modify: `src/noble_agent/agent/facade.py:351-361` (`_build_runner_for_version`)
- Test: `tests/unit/unified/test_facade_build_db.py`

**Interfaces:**
- Consumes: `read_published_config` (đã có), `agent_config.parse_config`, `db_context.context_from_config`/`set_db_context`, `_skeleton_dir` (đã có), `_build_runner_from_ctx` (đã có, nhánh db dùng `_agent_def_from_db`).
- Produces: `async _build_runner_for_version(tenant_id, version)` — db-mode: đọc config → dựng ctx qua `context_from_config` → `set_db_context` (để provider-source) → `_build_runner_from_ctx(ctx)`; KHÔNG gọi `context_for_version`/`_build_store` MinIO.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/unified/test_facade_build_db.py
import pytest
from noble_agent.agent import facade
from noble_agent.tenant.db_context import get_db_context, reset_db_context_for_tests

async def test_build_for_version_db_sets_context_no_minio(monkeypatch):
    from noble_agent import config
    reset_db_context_for_tests()
    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    async def _pc(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig
        return PublishedConfig(version=3, config={"data_source": "pg_kb",
                               "tools": {"enabled": ["booking"]}})
    monkeypatch.setattr(facade, "read_published_config", _pc)
    monkeypatch.setattr("noble_agent.tenant.loader._build_store",
                        lambda s: (_ for _ in ()).throw(AssertionError("MinIO touched")))
    sentinel = object()
    async def _from_ctx(ctx):
        assert ctx.tenant_id == "org_1_t" and ctx.data_source == "pg_kb"
        return sentinel
    monkeypatch.setattr(facade, "_build_runner_from_ctx", _from_ctx)
    runner = await facade._build_runner_for_version("org_1_t", 3)
    assert runner is sentinel
    assert get_db_context("org_1_t") is not None  # cached for provider-source
```

- [ ] **Step 2: Chạy fail** → hiện gọi MinIO `_build_store` → AssertionError.

- [ ] **Step 3: Sửa**

```python
# facade.py _build_runner_for_version — thêm nhánh db ở đầu:
async def _build_runner_for_version(tenant_id: str, version: int) -> TurnRunner:
    settings = get_settings()
    from noble_agent.tenant.current import use_tenant

    if settings.agent_config_source == "db":
        from noble_agent.agent.agent_config import parse_config
        from noble_agent.tenant.db_context import context_from_config, set_db_context

        pc = await read_published_config(tenant_id)
        if pc is None:
            raise RuntimeError(f"no published config for tenant {tenant_id!r}")
        ctx = context_from_config(tenant_id, parse_config(pc.config), skeleton_dir=_skeleton_dir())
        set_db_context(tenant_id, ctx)
        with use_tenant(tenant_id):
            return await _build_runner_from_ctx(ctx)

    from noble_agent.tenant.loader import _build_store
    from noble_agent.tenant.version_resolver import context_for_version
    store = _build_store(settings)
    ctx = context_for_version(store, settings, tenant_id, version)
    with use_tenant(tenant_id):
        return await _build_runner_from_ctx(ctx)
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/unified/test_facade_build_db.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/facade.py tests/unit/unified/test_facade_build_db.py
git commit -m "feat(facade): build runner from published config in db-mode (no MinIO ctx)"
```

---

## SLICE C — Heartbeat từ Postgres

### Task C1: `ActiveTenantTracker` + hook trong `NobleAgent.create`

**Files:**
- Create: `src/noble_agent/tenant/pg_heartbeat.py` (phần tracker)
- Modify: `src/noble_agent/agent/facade.py` (`create` gọi `mark_active`)
- Test: `tests/unit/tenant/test_active_tenant_tracker.py`

**Interfaces:**
- Produces: `ActiveTenantTracker(ttl_sec, *, clock)` với `mark(tenant_id)` + `active() -> list[str]` (lọc theo TTL). Module singleton `TRACKER` + `mark_active(tenant_id)`.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/tenant/test_active_tenant_tracker.py
from noble_agent.tenant.pg_heartbeat import ActiveTenantTracker

def test_mark_and_active_within_ttl():
    t = [100.0]
    tr = ActiveTenantTracker(60, clock=lambda: t[0])
    tr.mark("a"); tr.mark("b")
    assert set(tr.active()) == {"a", "b"}

def test_expires_after_ttl():
    t = [100.0]
    tr = ActiveTenantTracker(60, clock=lambda: t[0])
    tr.mark("a")
    t[0] = 161.0
    tr.mark("b")
    assert tr.active() == ["b"]
```

- [ ] **Step 2: Chạy fail** → module chưa có.

- [ ] **Step 3: Viết tracker (đầu file pg_heartbeat.py)**

```python
# src/noble_agent/tenant/pg_heartbeat.py
"""Heartbeat ghi control.agent_heartbeats (db-mode). Beat theo tenant đang có
kết nối (ActiveTenantTracker) vì role agent không enumerate control.tenants.
deployment_id tra agent_api.deployments theo kind của process. Contract:
docs/handoff/agent-postgres-read-contract.md §1.4/§2."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

logger = logging.getLogger("noble_agent.tenant.pg_heartbeat")


class ActiveTenantTracker:
    def __init__(self, ttl_sec: float, *, clock=time.monotonic):
        self._ttl = ttl_sec
        self._clock = clock
        self._seen: dict[str, float] = {}

    def mark(self, tenant_id: str) -> None:
        self._seen[tenant_id] = self._clock()

    def active(self) -> list[str]:
        now = self._clock()
        return [t for t, ts in self._seen.items() if (now - ts) < self._ttl]


TRACKER = ActiveTenantTracker(120.0)


def mark_active(tenant_id: str) -> None:
    TRACKER.mark(tenant_id)
```
```python
# facade.py create(): sau khi tid resolved, ở db-mode mark active:
        if get_settings().agent_config_source == "db":
            from noble_agent.tenant.pg_heartbeat import mark_active
            mark_active(tid)
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/tenant/test_active_tenant_tracker.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/pg_heartbeat.py src/noble_agent/agent/facade.py tests/unit/tenant/test_active_tenant_tracker.py
git commit -m "feat(heartbeat): ActiveTenantTracker + mark active tenants on conversation create"
```

### Task C2: `PgHeartbeatWriter` (upsert `control.agent_heartbeats`)

**Files:**
- Modify: `src/noble_agent/tenant/pg_heartbeat.py` (thêm writer)
- Test: `tests/unit/tenant/test_pg_heartbeat_writer.py`

**Interfaces:**
- Consumes: `agent_control_store.read_deployment_id` (A1), `read_published_config` (version), `tenant_conn`.
- Produces: `async PgHeartbeatWriter(kind, agent_version).beat(tenant_id) -> bool` — tra deployment_id theo kind; None → bỏ qua (False); else upsert heartbeat với `running_version`=published version. Lỗi → log, False.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/tenant/test_pg_heartbeat_writer.py
import pytest
from noble_agent.tenant.pg_heartbeat import PgHeartbeatWriter

class _Conn:
    def __init__(self): self.upserts = []
    def transaction(self):
        c = self
        class _T:
            async def __aenter__(self): return c
            async def __aexit__(self, *a): return False
        return _T()
    async def execute(self, sql, *a):
        if "agent_heartbeats" in sql: self.upserts.append(a)

class _Pool:
    def __init__(self, c): self._c = c
    def acquire(self):
        c = self._c
        class _A:
            async def __aenter__(self): return c
            async def __aexit__(self, *a): return False
        return _A()

async def test_beat_upserts_with_deployment_and_version(monkeypatch):
    conn = _Conn()
    async def _dep(tid, kind, **kw): return 42
    async def _pc(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig
        return PublishedConfig(version=5, config={})
    w = PgHeartbeatWriter("chat", "1.0", pool=_Pool(conn), read_deployment_id=_dep, read_published=_pc)
    assert await w.beat("t1") is True
    assert conn.upserts and conn.upserts[0][:3] == ("t1", 42, 5)

async def test_beat_skips_when_no_deployment(monkeypatch):
    conn = _Conn()
    async def _dep(tid, kind, **kw): return None
    async def _pc(tid, **kw): return None
    w = PgHeartbeatWriter("voice", "1.0", pool=_Pool(conn), read_deployment_id=_dep, read_published=_pc)
    assert await w.beat("t1") is False
    assert conn.upserts == []
```

- [ ] **Step 2: Chạy fail** → writer chưa có.

- [ ] **Step 3: Viết writer**

```python
# pg_heartbeat.py — thêm:
_UPSERT = """
INSERT INTO control.agent_heartbeats
  (tenant_id, deployment_id, running_version, bundle_sha, agent_version, last_error, last_seen_at)
VALUES ($1,$2,$3,$4,$5,$6, now())
ON CONFLICT (tenant_id, deployment_id) DO UPDATE
SET running_version=EXCLUDED.running_version, bundle_sha=EXCLUDED.bundle_sha,
    agent_version=EXCLUDED.agent_version, last_error=EXCLUDED.last_error, last_seen_at=now()
"""


class PgHeartbeatWriter:
    def __init__(self, kind: str, agent_version: str, *, pool=None,
                 read_deployment_id=None, read_published=None):
        self._kind = kind
        self._agent_version = agent_version
        self._pool = pool
        if read_deployment_id is None:
            from noble_agent.storage.agent_control_store import read_deployment_id
        if read_published is None:
            from noble_agent.storage.agent_config_store import read_published_config as read_published
        self._read_dep = read_deployment_id
        self._read_pub = read_published

    async def _pool_(self):
        if self._pool is not None:
            return self._pool
        from noble_agent.storage.postgres_client import get_pool
        return await get_pool()

    async def beat(self, tenant_id: str) -> bool:
        try:
            pool = await self._pool_()
            dep = await self._read_dep(tenant_id, self._kind, pool=pool)
            if dep is None:
                logger.debug("heartbeat: no %s deployment for %s — skip", self._kind, tenant_id)
                return False
            pc = await self._read_pub(tenant_id, pool=pool)
            running = pc.version if pc is not None else None
            from noble_agent.storage.postgres_client import tenant_conn
            async with tenant_conn(pool, tenant_id) as conn:
                await conn.execute(_UPSERT, tenant_id, dep, running, "", self._agent_version, "")
            return True
        except Exception:
            logger.warning("heartbeat: pg beat failed for %s", tenant_id, exc_info=True)
            return False
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/tenant/test_pg_heartbeat_writer.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/pg_heartbeat.py tests/unit/tenant/test_pg_heartbeat_writer.py
git commit -m "feat(heartbeat): PgHeartbeatWriter upserts control.agent_heartbeats"
```

### Task C3: `PgHeartbeatSupervisor` + `should_emit` db-mode

**Files:**
- Modify: `src/noble_agent/tenant/pg_heartbeat.py` (supervisor), `src/noble_agent/tenant/heartbeat.py:37-45` (`should_emit`)
- Test: `tests/unit/tenant/test_pg_heartbeat_supervisor.py`, cập nhật `tests/unit/tenant/test_heartbeat.py` (should_emit db-mode)

**Interfaces:**
- Consumes: `PgHeartbeatWriter` (C2), `ActiveTenantTracker.TRACKER` (C1).
- Produces: `async PgHeartbeatSupervisor(kind, agent_version, interval, *, tracker=TRACKER, writer=None).run(stop_event)` — mỗi chu kỳ beat mọi tenant trong `tracker.active()`. `should_emit(settings)` trả True ở db-mode khi `heartbeat_enabled` (không cần `tenant_store_enabled`).

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/tenant/test_pg_heartbeat_supervisor.py
import asyncio, pytest
from noble_agent.tenant.pg_heartbeat import PgHeartbeatSupervisor, ActiveTenantTracker

async def test_supervisor_beats_active_tenants():
    tr = ActiveTenantTracker(60, clock=lambda: 0.0)
    tr.mark("a"); tr.mark("b")
    beaten = []
    class _W:
        async def beat(self, tid): beaten.append(tid); return True
    sup = PgHeartbeatSupervisor("chat", "1.0", interval=0.01, tracker=tr, writer=_W())
    stop = asyncio.Event()
    task = asyncio.create_task(sup.run(stop))
    await asyncio.sleep(0.03); stop.set(); await task
    assert set(beaten) >= {"a", "b"}
```
```python
# test_heartbeat.py — thêm:
def test_should_emit_db_mode_without_store():
    from types import SimpleNamespace
    from noble_agent.tenant.heartbeat import should_emit
    s = SimpleNamespace(agent_config_source="db", tenant_store_enabled=False, heartbeat_enabled=True)
    assert should_emit(s) is True
```

- [ ] **Step 2: Chạy fail**.

- [ ] **Step 3: Viết supervisor + sửa should_emit**

```python
# pg_heartbeat.py — thêm:
class PgHeartbeatSupervisor:
    def __init__(self, kind: str, agent_version: str, interval: float,
                 *, tracker: ActiveTenantTracker = TRACKER, writer=None):
        self._interval = interval
        self._tracker = tracker
        self._writer = writer or PgHeartbeatWriter(kind, agent_version)

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("pg-heartbeat supervisor: started interval=%.0fs", self._interval)
        try:
            while not stop_event.is_set():
                for tid in self._tracker.active():
                    with contextlib.suppress(Exception):
                        await self._writer.beat(tid)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
        finally:
            logger.info("pg-heartbeat supervisor: stopped")
```
```python
# heartbeat.py should_emit — cho db-mode bỏ điều kiện store:
def should_emit(settings) -> bool:
    if getattr(settings, "agent_config_source", "legacy") == "db":
        return bool(getattr(settings, "heartbeat_enabled", True))
    return bool(getattr(settings, "tenant_store_enabled", False)) and bool(
        getattr(settings, "heartbeat_enabled", True))
```

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/tenant/test_pg_heartbeat_supervisor.py tests/unit/tenant/test_heartbeat.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/pg_heartbeat.py src/noble_agent/tenant/heartbeat.py tests/unit/tenant/test_pg_heartbeat_supervisor.py tests/unit/tenant/test_heartbeat.py
git commit -m "feat(heartbeat): PgHeartbeatSupervisor + should_emit for db-mode"
```

### Task C4: Wire 2 transport chọn supervisor Postgres ở db-mode

**Files:**
- Modify: `src/noble_agent/server/http.py:1025-1035` (kind=`chat`), `src/noble_agent/transport/livekit/worker.py:279-298` (kind=`voice`)
- Test: `tests/unit/tenant/test_heartbeat_wireup.py`

**Interfaces:**
- Consumes: `PgHeartbeatSupervisor` (C3), `MinIO HeartbeatSupervisor` (đã có).
- Produces: `build_heartbeat_supervisor(settings, kind) -> supervisor` — hàm thuần (đặt trong `tenant/heartbeat.py`) trả PG supervisor ở db-mode, else MinIO supervisor. Cả 2 wire-up dùng nó.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/tenant/test_heartbeat_wireup.py
from types import SimpleNamespace
from noble_agent.tenant.heartbeat import build_heartbeat_supervisor
from noble_agent.tenant.pg_heartbeat import PgHeartbeatSupervisor

def test_build_supervisor_db_mode():
    s = SimpleNamespace(agent_config_source="db", heartbeat_sec=20.0, agent_version="1.0")
    sup = build_heartbeat_supervisor(s, "chat")
    assert isinstance(sup, PgHeartbeatSupervisor)

def test_build_supervisor_legacy(monkeypatch):
    monkeypatch.setattr("noble_agent.tenant.loader._build_store", lambda s: object())
    from noble_agent.tenant.heartbeat import HeartbeatSupervisor
    s = SimpleNamespace(agent_config_source="legacy", heartbeat_sec=20.0,
                        tenant_store_enabled=True)
    assert isinstance(build_heartbeat_supervisor(s, "chat"), HeartbeatSupervisor)
```

- [ ] **Step 2: Chạy fail** → hàm chưa có.

- [ ] **Step 3: Viết `build_heartbeat_supervisor` + wire 2 chỗ**

```python
# heartbeat.py — thêm:
def build_heartbeat_supervisor(settings, kind: str):
    if getattr(settings, "agent_config_source", "legacy") == "db":
        from noble_agent.tenant.pg_heartbeat import PgHeartbeatSupervisor
        return PgHeartbeatSupervisor(kind, getattr(settings, "agent_version", ""),
                                     float(getattr(settings, "heartbeat_sec", 20.0)))
    from noble_agent.tenant.loader import _build_store
    return HeartbeatSupervisor(_build_store(settings), settings)
```
```python
# server/http.py — thay dòng dựng supervisor:
            from noble_agent.tenant.heartbeat import build_heartbeat_supervisor
            hb_stop = asyncio.Event()
            supervisor = build_heartbeat_supervisor(settings, "chat")
            heartbeat_task = asyncio.create_task(supervisor.run(hb_stop))
```
```python
# transport/livekit/worker.py _start_heartbeat._run._main:
            from noble_agent.tenant.heartbeat import build_heartbeat_supervisor
            supervisor = build_heartbeat_supervisor(settings, "voice")
            await supervisor.run(_asyncio.Event())
```
> Nếu `settings.agent_version` chưa có, dùng `getattr(..., "", )` (mặc định `""`) — không thêm setting mới ở task này.

- [ ] **Step 4: Chạy pass** → `pytest tests/unit/tenant/test_heartbeat_wireup.py -v`; `pytest tests/unit/tenant -q` 0 new fail.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/heartbeat.py src/noble_agent/server/http.py src/noble_agent/transport/livekit/worker.py tests/unit/tenant/test_heartbeat_wireup.py
git commit -m "feat(heartbeat): wire PG supervisor (chat/voice) in db-mode; MinIO in legacy"
```

---

## SLICE D — Dọn MinIO khỏi serving + docs

### Task D1: Guard — db-mode không bao giờ dựng MinIO store + xác nhận toàn suite

**Files:**
- Modify: `src/noble_agent/tenant/loader.py:24-28` (`_build_store` docstring deprecate) + `src/noble_agent/agent/facade.py:317` (nhánh legacy MinIO của `_resolve_current_version` đã sau nhánh db — xác nhận)
- Test: `tests/unit/tenant/test_no_minio_in_db_mode.py`

**Interfaces:**
- Produces: bảo chứng — trong db-mode, không call-site nào dựng `MinioTenantStore`.

- [ ] **Step 1: Viết test bảo chứng (fail nếu rò)**

```python
# tests/unit/tenant/test_no_minio_in_db_mode.py
import pytest
from noble_agent.agent import facade
from noble_agent.tenant import db_context

async def test_full_db_path_never_builds_minio(monkeypatch):
    from noble_agent import config
    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    db_context.reset_db_context_for_tests()
    monkeypatch.setattr("noble_agent.tenant.loader._build_store",
                        lambda s: (_ for _ in ()).throw(AssertionError("MinIO built in db-mode")))
    async def _pc(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig
        return PublishedConfig(version=1, config={"tools": {"enabled": []}})
    monkeypatch.setattr(facade, "read_published_config", _pc)
    async def _from_ctx(ctx): return object()
    monkeypatch.setattr(facade, "_build_runner_from_ctx", _from_ctx)
    v = await facade._resolve_current_version("org_1_t")
    assert v == 1
    await facade._build_runner_for_version("org_1_t", v)  # no AssertionError
```

- [ ] **Step 2: Chạy fail** (nếu còn rò MinIO ở nhánh db) → sửa cho hết; nếu pass ngay thì các slice trên đã kín.

- [ ] **Step 3: Deprecate docstring `_build_store`**

```python
# loader.py _build_store — thêm docstring:
def _build_store(settings):
    """Build the MinIO tenant store (LEGACY path only — agent_config_source != 'db').

    Retired from the serving path in the Postgres control-plane migration
    (2026-08-04); reachable only for legacy MinIO bundles. Deletion is a
    follow-up. See docs/superpowers/plans/2026-08-04-retire-minio-postgres-control-plane.md.
    """
    from noble_agent.tenant.store import MinioTenantStore
    return MinioTenantStore.from_settings(settings)
```

- [ ] **Step 4: Chạy toàn suite gate**

Run: `source .venv/bin/activate && make test-unit 2>&1 | tail -20`
Expected: PASS trừ baseline red đã ghi trong CLAUDE.md (2 USD-normalize, test_tool_ack flaky, vieneu_vllm, 2 qdrant_adapter, qdrant_store, prompt_builder, send_media, project_financial_mongo). **0 new fail.**
Run: `ruff check src/noble_agent/{gateway,tenant,storage,agent} 2>&1 | tail` → sạch trên file đụng.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/loader.py tests/unit/tenant/test_no_minio_in_db_mode.py
git commit -m "test(retire-minio): assert db-mode never builds MinIO store; deprecate _build_store"
```

### Task D2: CLAUDE.md + Change Log (self-maintenance)

**Files:**
- Modify: `CLAUDE.md` (mục `tenant/` layout + Key configuration `AGENT_CONFIG_SOURCE` + Change Log)

**Interfaces:** N/A (docs).

- [ ] **Step 1: Cập nhật mô tả**

Trong CLAUDE.md:
- Mục `tenant/` + Architecture "one shared agent": ghi rõ **db-mode giờ đọc control-plane từ Postgres** (gateway creds `agent_api.tenant_status`/`tenant_keys`; version từ `agent_published_config.version`; ctx từ published config qua `context_from_config`; heartbeat → `control.agent_heartbeats` beat-theo-kết-nối), **MinIO chỉ còn cho legacy**.
- Bảng Key configuration: dòng `AGENT_CONFIG_SOURCE` bổ sung "db ⇒ toàn bộ control-plane (creds/version/ctx/heartbeat) đọc Postgres, không MinIO".
- Trỏ tới contract `docs/handoff/agent-postgres-read-contract.md`.

- [ ] **Step 2: Thêm 1 dòng Change Log** (đầu bảng Change Log, ngày 2026-08-04) tóm tắt: retire MinIO khỏi luồng config/serving trong db-mode; 4 bề mặt Postgres; credential sha256-plain; heartbeat beat-per-connection; MinIO/CLI giữ cho legacy (xoá = follow-up); branch `feat/share-agent`, chưa push; **live cutover chờ Portal ship `agent_api.*` contract**.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): retire-MinIO Postgres control-plane in db-mode + Change Log"
```

---

## Live smoke (thủ công, sau khi land — KHÔNG chặn unit gate)

Mô phỏng Portal + verify end-to-end (chi tiết trong design spec §6). **Không tạo `control.*`/`agent_api.*` "thật" đè migration Portal trên DB chung** — dùng PG docker cục bộ, hoặc schema tạm gỡ sạch sau test:
1. Dựng sim: `agent_api.tenant_status/tenant_keys/deployments` + `control.agent_heartbeats` + hàm `portal.current_tenant()` (đọc `app.tenant_id`) + `agent_published_config` (đã có). Seed 1 tenant + 1 key (`key_sha256=sha256(token)`) + 1 deployment kind=chat, publish v1.
2. `AGENT_CONFIG_SOURCE=db`, `POSTGRES_DSN` trỏ sim (tunnel `-L 5433:127.0.0.1:5433 thebc-server` nếu dùng DB server).
3. Gateway auth: gọi qua `scratchpad/gateway_chat_client.py` với `Bearer <token>` + Host subdomain → chat trả lời. Sai token → 4001 `bad_credential`; tenant suspended → `tenant_inactive`.
4. Verify **KHÔNG** có object MinIO nào cho tenant đó (tắt `TENANT_STORE_ENABLED` / không tạo bucket key).
5. Heartbeat: kiểm `control.agent_heartbeats` có dòng `(tenant, deployment_id)` cập nhật mỗi ~20s.
6. Chạy `src/noble_agent/SMOKE.md`.

---

## Self-Review (đã chạy khi viết plan)

- **Spec coverage:** D1 (Task A4/B2/B3/C3 gate theo agent_config_source), D2 (A1-A4), D3 (B1-B4), D4 (B3), D5 (C1-C4), D6 (không đổi — không cần task). GUC (F1). Cleanup (D1-D2). Reverse-contract → `docs/handoff/agent-postgres-read-contract.md` (đã commit). ✔
- **Placeholder scan:** không có TBD/TODO; mọi step có code/test/lệnh thật. ✔
- **Type consistency:** `verify_bearer(tenant, plaintext)->str|None` dùng nhất quán A2/A3/A4; `context_from_config(tenant_id, cfg, *, skeleton_dir)` B1↔B4; `read_deployment_id(tenant_id, kind, *, pool)` A1↔C2; `PublishedConfig(version, config)` (đã có) dùng B3/B4/C2. ✔
- **Rủi ro đã ghi:** db-mode đọc config 2 lần/build (version + agent_def) — chấp nhận nhờ version bất biến + last-good cache. `agent_version` dùng `getattr(...,"")` nếu setting chưa có.
