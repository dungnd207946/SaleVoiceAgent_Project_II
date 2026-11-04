# Gateway Runtime-Credentials Auth + PG Per-Tenant Role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay đường auth gateway subdomain+control.* bằng gọi Portal runtime-credentials API (single domain), forward PG role/password sang worker để worker nối Postgres bằng pool per-tenant.

**Architecture:** Gateway POST API key → `GATEWAY_CREDENTIALS_API_URL`, cache theo `expires_at`, fail-closed. Credential (tenant_id + postgres_role/password) forward qua header WS nội bộ (đã có X-Gateway-Secret). Worker đăng ký credential vào registry in-process; `pool_for_tenant()` dựng pool từ `POSTGRES_SERVER_DSN` + role/password, fallback shared `POSTGRES_DSN` khi không có credential (dev/REPL/voice/heartbeat). `tenant_conn` giữ nguyên set_config (defense-in-depth).

**Tech Stack:** Python 3.11+, httpx (đã có trong deps), asyncpg, websockets, pytest (`asyncio_mode=auto`).

**Spec:** `docs/superpowers/specs/2026-08-10-gateway-runtime-credentials-design.md`

## Global Constraints

- Branch: `feat/share-agent` — KHÔNG merge/push/tạo branch mới. Commit local từng task.
- Working tree đang có sửa đổi dở của user ở 13 file khác — `git add` ĐÍCH DANH từng file của task, không bao giờ `git add -A`/`git add .`.
- Ruff: line-length 120, target py311. Chạy `make lint` trước mỗi commit.
- Pytest `asyncio_mode=auto` — test async không cần decorator.
- Close-code contract gateway giữ nguyên: 4001 + reason auth fail, 4004 unknown_route, 4008 handshake_timeout.
- Reason mới: `bad_credential` (API trả 401/403), `auth_api_unavailable` (timeout/5xx/thiếu URL/response thiếu trường). `no_bearer` giữ nguyên.
- Pool per-tenant dựng fail (password sai…) → lỗi nổi lên, KHÔNG fallback shared. Riêng "không có credential" hoặc "POSTGRES_SERVER_DSN chưa cấu hình" → fallback shared (transitional, log warning).
- Voice (`_bridge_voice`) đợt này KHÔNG nhận PG credential — chỉ chat proxy forward.

---

### Task 1: `gateway/credentials.py` — client gọi runtime-credentials API + cache

**Files:**
- Create: `src/noble_agent/gateway/credentials.py`
- Modify: `src/noble_agent/config.py` (thêm 1 field cạnh nhóm gateway, quanh dòng 110)
- Test: `tests/unit/gateway/test_runtime_credentials.py` (tên tránh đụng `test_credentials.py` có sẵn)

**Interfaces:**
- Consumes: `settings.gateway_cred_cache_ttl_sec` (đã có).
- Produces:
  - `RuntimeCredentials` frozen dataclass: `tenant_id: str`, `deployment_id: int | None`, `kind: str`, `postgres_role: str`, `postgres_password: str`, `storage: dict`, `kb: dict`, `live_url: str`, `expires_at: datetime | None`.
  - `CredentialsError(Exception)` với thuộc tính `.reason`.
  - Hằng `REASON_BAD_CREDENTIAL = "bad_credential"`, `REASON_UNAVAILABLE = "auth_api_unavailable"`.
  - `parse_credentials(data: dict) -> RuntimeCredentials` (raise `CredentialsError(REASON_UNAVAILABLE)` khi thiếu `tenant_id`/`expires_at`).
  - `CredentialsClient(url, cache_ttl_sec, *, transport=None, clock=time.monotonic, now_utc=None)` với `async authorize(api_key) -> RuntimeCredentials` và `async aclose()`.

- [ ] **Step 1: Thêm field config**

Trong `src/noble_agent/config.py`, ngay dưới `gateway_worker_secret` (dòng ~114):

```python
    # URL đầy đủ của Portal runtime-credentials API (POST, Bearer = API key của provider).
    # Rỗng ⇒ gateway fail-closed: từ chối MỌI kết nối với reason auth_api_unavailable.
    gateway_credentials_api_url: str = Field("", alias="GATEWAY_CREDENTIALS_API_URL")
```

- [ ] **Step 2: Viết test fail trước**

Tạo `tests/unit/gateway/test_runtime_credentials.py`:

```python
"""CredentialsClient: gọi runtime-credentials API, cache theo expires_at, fail-closed."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from noble_agent.gateway.credentials import (
    REASON_BAD_CREDENTIAL,
    REASON_UNAVAILABLE,
    CredentialsClient,
    CredentialsError,
    parse_credentials,
)

URL = "http://portal.test/api/v1/agent/runtime-credentials"


def _payload(**over):
    base = {
        "tenant_id": "anphu",
        "deployment_id": 12,
        "kind": "chat",
        "postgres_role": "agent_anphu",
        "postgres_password": "s3cret",
        "storage": {"endpoint": "http://minio", "bucket": "b"},
        "kb": {"url": "http://qdrant", "collection": "kb_anphu"},
        "live_url": "tenants/anphu/LIVE",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    base.update(over)
    return base


def _client(handler, ttl=30.0, url=URL, clock=None):
    transport = httpx.MockTransport(handler)
    kwargs = {"transport": transport}
    if clock is not None:
        kwargs["clock"] = clock
    return CredentialsClient(url, ttl, **kwargs)


def test_parse_credentials_full():
    c = parse_credentials(_payload())
    assert c.tenant_id == "anphu"
    assert c.deployment_id == 12
    assert c.kind == "chat"
    assert c.postgres_role == "agent_anphu"
    assert c.postgres_password == "s3cret"
    assert c.kb["collection"] == "kb_anphu"
    assert c.expires_at is not None and c.expires_at.tzinfo is not None


def test_parse_credentials_z_suffix():
    c = parse_credentials(_payload(expires_at="2026-08-10T09:00:00Z"))
    assert c.expires_at == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("missing", ["tenant_id", "expires_at"])
def test_parse_credentials_missing_required(missing):
    data = _payload()
    data[missing] = ""
    with pytest.raises(CredentialsError) as e:
        parse_credentials(data)
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_ok_and_bearer_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_payload())

    c = _client(handler)
    creds = await c.authorize("key_abc")
    assert creds.tenant_id == "anphu"
    assert seen["auth"] == "Bearer key_abc"


async def test_authorize_caches_within_ttl():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_payload())

    c = _client(handler)
    await c.authorize("key_abc")
    await c.authorize("key_abc")
    assert calls["n"] == 1  # cache hit, không gọi lại API


async def test_authorize_cache_expires_by_clock():
    calls = {"n": 0}
    t = {"now": 100.0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_payload())

    c = _client(handler, ttl=30.0, clock=lambda: t["now"])
    await c.authorize("key_abc")
    t["now"] += 31.0
    await c.authorize("key_abc")
    assert calls["n"] == 2


async def test_authorize_cache_capped_by_expires_at():
    """expires_at gần hơn TTL cap → hết expires_at là gọi lại API."""
    calls = {"n": 0}
    t = {"now": 100.0}

    def handler(request):
        calls["n"] += 1
        # expires sau 10s (wall clock thật) — ngắn hơn ttl=3600
        return httpx.Response(200, json=_payload(
            expires_at=(datetime.now(UTC) + timedelta(seconds=10)).isoformat()))

    c = _client(handler, ttl=3600.0, clock=lambda: t["now"])
    await c.authorize("key_abc")
    t["now"] += 11.0
    await c.authorize("key_abc")
    assert calls["n"] == 2


async def test_authorize_401_bad_credential_not_cached():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"detail": "invalid"})

    c = _client(handler)
    for _ in range(2):
        with pytest.raises(CredentialsError) as e:
            await c.authorize("key_bad")
        assert e.value.reason == REASON_BAD_CREDENTIAL
    assert calls["n"] == 2  # không negative-cache


async def test_authorize_5xx_unavailable():
    c = _client(lambda request: httpx.Response(503))
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_network_error_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    c = _client(handler)
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_missing_url_unavailable():
    c = _client(lambda request: httpx.Response(200), url="")
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_bad_json_unavailable():
    c = _client(lambda request: httpx.Response(200, content=b"not-json"))
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `pytest tests/unit/gateway/test_runtime_credentials.py -x -q`
Expected: FAIL — `ModuleNotFoundError: noble_agent.gateway.credentials`

- [ ] **Step 4: Implement `src/noble_agent/gateway/credentials.py`**

```python
"""Runtime-credentials client — gateway auth qua Portal API (kiến trúc single-domain).

Thay hẳn đường subdomain + đọc control.*: gateway POST API key lên
GATEWAY_CREDENTIALS_API_URL, nhận credential per-tenant (tenant_id, PG role/password,
storage/kb, expires_at). Cache in-RAM keyed sha256(api_key), sống tới
min(expires_at, now + GATEWAY_CRED_CACHE_TTL_SEC) — cache hit vẫn phục vụ khi auth
API down; cache miss + API lỗi → fail-closed (`CredentialsError.reason` đi thẳng vào
close frame 4001, phân biệt "khoá sai" với "không hỏi được" như gateway/errors.py cũ)."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("gateway.credentials")

REASON_BAD_CREDENTIAL = "bad_credential"
REASON_UNAVAILABLE = "auth_api_unavailable"

_TIMEOUT_SEC = 5.0


class CredentialsError(Exception):
    """Auth API từ chối hoặc không trả lời được. `reason` đi vào close frame."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RuntimeCredentials:
    tenant_id: str
    deployment_id: int | None
    kind: str
    postgres_role: str
    postgres_password: str
    storage: dict = field(default_factory=dict)
    kb: dict = field(default_factory=dict)
    live_url: str = ""
    expires_at: datetime | None = None


def parse_credentials(data: dict) -> RuntimeCredentials:
    """Parse response 200. Thiếu tenant_id/expires_at hoặc expires_at hỏng →
    CredentialsError(auth_api_unavailable): không tin dữ liệu nửa vời."""
    tenant_id = str(data.get("tenant_id") or "").strip()
    raw_exp = str(data.get("expires_at") or "").strip()
    if not tenant_id or not raw_exp:
        raise CredentialsError(REASON_UNAVAILABLE)
    try:
        expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CredentialsError(REASON_UNAVAILABLE) from exc
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    dep = data.get("deployment_id")
    return RuntimeCredentials(
        tenant_id=tenant_id,
        deployment_id=int(dep) if dep is not None else None,
        kind=str(data.get("kind") or ""),
        postgres_role=str(data.get("postgres_role") or ""),
        postgres_password=str(data.get("postgres_password") or ""),
        storage=data.get("storage") or {},
        kb=data.get("kb") or {},
        live_url=str(data.get("live_url") or ""),
        expires_at=expires_at,
    )


class CredentialsClient:
    """`transport`/`clock`/`now_utc` inject được cho unit test (httpx.MockTransport)."""

    def __init__(self, url: str, cache_ttl_sec: float, *, transport=None, clock=time.monotonic, now_utc=None):
        self._url = url
        self._ttl = cache_ttl_sec
        self._transport = transport
        self._clock = clock
        self._now_utc = now_utc or (lambda: datetime.now(UTC))
        self._cache: dict[str, tuple[float, RuntimeCredentials]] = {}
        self._client = None

    def _http(self):
        import httpx  # lazy: giữ import gateway nhẹ

        if self._client is None:
            kwargs: dict = {"timeout": _TIMEOUT_SEC}
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def authorize(self, api_key: str) -> RuntimeCredentials:
        cache_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        now = self._clock()
        hit = self._cache.get(cache_key)
        if hit is not None and now < hit[0]:
            return hit[1]
        creds = await self._fetch(api_key)
        wall_left = _TIMEOUT_SEC  # placeholder ghi đè ngay dưới
        wall_left = max(0.0, (creds.expires_at - self._now_utc()).total_seconds()) if creds.expires_at else 0.0
        self._cache[cache_key] = (now + min(self._ttl, wall_left), creds)
        return creds

    async def _fetch(self, api_key: str) -> RuntimeCredentials:
        if not self._url:
            logger.error("gateway: GATEWAY_CREDENTIALS_API_URL chưa cấu hình — từ chối kết nối (fail-closed)")
            raise CredentialsError(REASON_UNAVAILABLE)
        try:
            resp = await self._http().post(self._url, headers={"Authorization": f"Bearer {api_key}"})
        except CredentialsError:
            raise
        except Exception as exc:  # noqa: BLE001 — mọi lỗi mạng/timeout đều là "không hỏi được"
            logger.warning("gateway: auth API không phản hồi: %s", exc)
            raise CredentialsError(REASON_UNAVAILABLE) from exc
        if resp.status_code in (401, 403):
            raise CredentialsError(REASON_BAD_CREDENTIAL)
        if resp.status_code != 200:
            logger.warning("gateway: auth API trả %s", resp.status_code)
            raise CredentialsError(REASON_UNAVAILABLE)
        try:
            data = resp.json()
        except ValueError as exc:
            raise CredentialsError(REASON_UNAVAILABLE) from exc
        return parse_credentials(data if isinstance(data, dict) else {})

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
```

Lưu ý khi code thật: bỏ dòng `wall_left = _TIMEOUT_SEC  # placeholder…` — viết thẳng một dòng tính `wall_left` như dòng dưới nó.

- [ ] **Step 5: Chạy test pass**

Run: `pytest tests/unit/gateway/test_runtime_credentials.py -x -q`
Expected: PASS toàn bộ.

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add src/noble_agent/gateway/credentials.py src/noble_agent/config.py tests/unit/gateway/test_runtime_credentials.py
git commit -m "feat(gateway): CredentialsClient gọi runtime-credentials API, cache theo expires_at, fail-closed"
```

---

### Task 2: Viết lại `gateway/auth.py` — authorize qua CredentialsClient

**Files:**
- Modify: `src/noble_agent/gateway/auth.py` (viết lại toàn bộ)
- Test: `tests/unit/gateway/test_auth.py` (viết lại toàn bộ)

**Interfaces:**
- Consumes: `CredentialsClient.authorize(api_key)`, `CredentialsError`, `RuntimeCredentials` (Task 1).
- Produces: `AuthResult(ok, tenant_id="", key_id="", reason="", credentials=None)`; `async authorize(authorization: str, *, credentials) -> AuthResult`. KHÔNG còn `tenant_from_host`, không còn tham số `host`/`base_domain`/`registry`.

- [ ] **Step 1: Viết lại test trước** — thay toàn bộ nội dung `tests/unit/gateway/test_auth.py`:

```python
"""Gateway authorization: Bearer key → runtime-credentials API (không còn Host subdomain)."""

from noble_agent.gateway.auth import AuthResult, authorize
from noble_agent.gateway.credentials import (
    REASON_BAD_CREDENTIAL,
    REASON_UNAVAILABLE,
    CredentialsError,
    RuntimeCredentials,
)

_CREDS = RuntimeCredentials(
    tenant_id="anphu", deployment_id=12, kind="chat",
    postgres_role="agent_anphu", postgres_password="pw",
)


class _Client:
    """Fake CredentialsClient: trả creds cho key 'good', raise cho phần còn lại."""

    def __init__(self, error: CredentialsError | None = None):
        self._error = error

    async def authorize(self, api_key: str) -> RuntimeCredentials:
        if self._error is not None:
            raise self._error
        if api_key == "good":
            return _CREDS
        raise CredentialsError(REASON_BAD_CREDENTIAL)


async def test_authorize_happy():
    r = await authorize("Bearer good", credentials=_Client())
    assert r.ok
    assert r.tenant_id == "anphu"
    assert r.credentials is _CREDS
    assert r.key_id  # sha256 prefix, chỉ cần khác rỗng
    assert r.reason == ""


async def test_authorize_no_bearer():
    for bad in ("", "Basic abc", "bearer good"):
        r = await authorize(bad, credentials=_Client())
        assert not r.ok and r.reason == "no_bearer"


async def test_authorize_bad_credential():
    r = await authorize("Bearer wrong", credentials=_Client())
    assert not r.ok and r.reason == REASON_BAD_CREDENTIAL
    assert r.credentials is None


async def test_authorize_api_unavailable():
    r = await authorize("Bearer good", credentials=_Client(error=CredentialsError(REASON_UNAVAILABLE)))
    assert not r.ok and r.reason == REASON_UNAVAILABLE


async def test_authorize_unexpected_error_fail_closed():
    class _Boom:
        async def authorize(self, api_key):
            raise RuntimeError("bug")

    r = await authorize("Bearer good", credentials=_Boom())
    assert not r.ok and r.reason == REASON_UNAVAILABLE


def test_authresult_defaults():
    r = AuthResult(False)
    assert r.tenant_id == "" and r.key_id == "" and r.credentials is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/gateway/test_auth.py -x -q`
Expected: FAIL — `ImportError` (authorize signature cũ / AuthResult thiếu credentials).

- [ ] **Step 3: Viết lại `src/noble_agent/gateway/auth.py`** (thay toàn bộ file):

```python
"""Gateway request authorization: Bearer API key → Portal runtime-credentials API.

Kiến trúc single-domain (noble-saas.<domain>): tenant KHÔNG còn nằm trong Host —
mọi thông tin (tenant_id, PG role/password, expires_at) đến từ credential API.
Fail-closed: mọi lỗi hỏi API đều là ok=False với reason phân loại rõ (bad_credential
vs auth_api_unavailable) để người debug không xoay nhầm khoá khi lỗi là hạ tầng."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from noble_agent.gateway.credentials import REASON_UNAVAILABLE, CredentialsError, RuntimeCredentials

logger = logging.getLogger("gateway.auth")

_BEARER = "Bearer "


@dataclass(frozen=True)
class AuthResult:
    """Result of gateway authorization attempt."""

    ok: bool
    tenant_id: str = ""
    key_id: str = ""
    reason: str = ""
    credentials: RuntimeCredentials | None = None


async def authorize(authorization: str, *, credentials) -> AuthResult:
    """Authorize một request gateway bằng Bearer API key.

    `credentials`: đối tượng có `async authorize(api_key) -> RuntimeCredentials`
    (CredentialsClient thật, hoặc fake trong test). Reasons: "no_bearer",
    "bad_credential" (API trả 401/403 — khoá sai/revoked), "auth_api_unavailable"
    (API down/5xx/thiếu config/response hỏng — KHÔNG phải lỗi của khoá)."""
    if not authorization or not authorization.startswith(_BEARER):
        return AuthResult(False, reason="no_bearer")
    api_key = authorization[len(_BEARER) :]
    try:
        creds = await credentials.authorize(api_key)
    except CredentialsError as exc:
        return AuthResult(False, reason=exc.reason)
    except Exception:
        logger.exception("gateway: lỗi bất ngờ khi hỏi credentials API")
        return AuthResult(False, reason=REASON_UNAVAILABLE)
    key_id = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
    return AuthResult(True, tenant_id=creds.tenant_id, key_id=key_id, credentials=creds)
```

- [ ] **Step 4: Chạy test pass**

Run: `pytest tests/unit/gateway/test_auth.py -x -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/gateway/auth.py tests/unit/gateway/test_auth.py
git commit -m "feat(gateway): authorize qua runtime-credentials API — bỏ tenant-from-Host"
```

(Lint sẽ báo import thừa ở `server.py`/`pg_registry.py` nếu có — các file đó chưa đụng, để Task 3.)

---

### Task 3: Wiring `server.py` + xoá sạch đường auth cũ

**Files:**
- Modify: `src/noble_agent/gateway/server.py` (bỏ `build_registry`, dùng CredentialsClient, kind-vs-route warning)
- Delete: `src/noble_agent/gateway/pg_registry.py`, `src/noble_agent/gateway/registry.py`, `src/noble_agent/gateway/errors.py`
- Modify: `src/noble_agent/storage/agent_control_store.py` (xoá `read_tenant_active`, `read_tenant_key_hashes`, `_SQL_STATUS`, `_SQL_KEYS`; GIỮ `read_deployment_id` + `_pool` — heartbeat dùng)
- Modify: `src/noble_agent/config.py` (xoá field `gateway_base_domain` dòng ~110)
- Delete tests: `tests/unit/gateway/test_pg_registry.py`, `tests/unit/gateway/test_registry.py`, `tests/unit/gateway/test_registry_selection.py`, `tests/unit/gateway/test_registry_unavailable.py`
- Modify: `tests/unit/storage/test_agent_control_store.py` (bỏ test của 2 hàm xoá, giữ test `read_deployment_id`)
- Modify: `scripts/smoke_gateway_chat.py`, `scripts/smoke_gateway_voice.py`, `scripts/e2e_dbmode/verify_portal_reads.py` (cập nhật tham chiếu GATEWAY_BASE_DOMAIN / reader đã xoá — xem Step 4)

**Interfaces:**
- Consumes: `authorize(authz, credentials=...)` (Task 2), `CredentialsClient` (Task 1).
- Produces: `_handle(ws, settings, credentials_client)`; `run_gateway()` dựng `CredentialsClient(settings.gateway_credentials_api_url, settings.gateway_cred_cache_ttl_sec)`. `proxy_chat`/`_bridge_voice` call sites nhận thêm `result.credentials` (chat dùng ở Task 7 — đợt này truyền xuống `proxy_chat` qua param mới `credentials=None` để Task 7 chỉ sửa `chat_proxy.py`).

- [ ] **Step 1: Sửa test routing hiện có nếu cần** — đọc `tests/unit/gateway/test_server_routing.py` (chỉ test `route()` — giữ nguyên). Xoá 4 file test của registry cũ:

```bash
git rm tests/unit/gateway/test_pg_registry.py tests/unit/gateway/test_registry.py \
       tests/unit/gateway/test_registry_selection.py tests/unit/gateway/test_registry_unavailable.py
```

- [ ] **Step 2: Sửa `server.py`**

Trong `src/noble_agent/gateway/server.py`:

1. Xoá hàm `build_registry` (dòng 26–39) và docstring module nhắc "store-backed cache" — sửa docstring đầu file thành: auth qua Portal runtime-credentials API, single domain.
2. `run_gateway()`:

```python
def run_gateway() -> None:  # pragma: no cover — integration entry
    import asyncio

    from noble_agent.config import get_settings
    from noble_agent.gateway.credentials import CredentialsClient

    settings = get_settings()
    credentials_client = CredentialsClient(
        settings.gateway_credentials_api_url, settings.gateway_cred_cache_ttl_sec
    )
    asyncio.run(_serve(settings, credentials_client))
```

3. `_serve(settings, credentials_client)` — đổi tên tham số `registry` → `credentials_client`, truyền xuống `_handle`.
4. `_handle`:

```python
async def _handle(ws, settings, credentials_client) -> None:  # pragma: no cover
    import asyncio

    from noble_agent.gateway.auth import authorize

    path, _host, authz = _extract_request(ws)
    mode = route(path)
    if mode is None:
        await ws.close(code=4004, reason="unknown_route")
        return
    result = await authorize(authz, credentials=credentials_client)
    if not result.ok:
        await ws.close(code=4001, reason=result.reason)
        return
    kind = result.credentials.kind if result.credentials else ""
    if kind and kind != mode:
        # Contract voice-key chưa chốt — cảnh báo, không chặn.
        logger.warning("gateway: credential kind=%s nhưng route=%s (tenant=%s)", kind, mode, result.tenant_id)
    try:
        first = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT_SEC)
    except TimeoutError:
        await ws.close(code=4008, reason="handshake_timeout")
        return
    hs = parse_handshake(first if isinstance(first, str) else "")
    identity_json = json.dumps(hs.get("identity") or {}, ensure_ascii=False)
    call_id = str(hs.get("call_id") or "call")
    if mode == "voice":
        await _bridge_voice(ws, settings, result.tenant_id, identity_json, call_id)
    else:
        from noble_agent.gateway.chat_proxy import proxy_chat

        await proxy_chat(ws, settings, result.tenant_id, hs.get("identity") or {}, credentials=result.credentials)
```

`_extract_request` GIỮ NGUYÊN (vẫn đọc Host để trả tuple — đổi chỗ dùng thành `_host` bỏ qua; hoặc thu gọn `_extract_request` trả `(path, authz)` và cập nhật test `test_server_routing.py` nếu file đó test hàm này — kiểm tra trước, chọn phương án ít đụng test nhất).

5. `chat_proxy.proxy_chat` thêm param `credentials=None` (chưa dùng — Task 7 mới forward header; thêm ngay để chữ ký ổn định):

```python
async def proxy_chat(client_ws, settings, tenant_id: str, identity: dict, credentials=None) -> None:
```

- [ ] **Step 3: Xoá file cũ + prune `agent_control_store`**

```bash
git rm src/noble_agent/gateway/pg_registry.py src/noble_agent/gateway/registry.py src/noble_agent/gateway/errors.py
```

Trong `src/noble_agent/storage/agent_control_store.py`: xoá `_SQL_STATUS`, `_SQL_KEYS`, `read_tenant_active`, `read_tenant_key_hashes`; sửa docstring đầu file (giờ chỉ còn phục vụ heartbeat: `read_deployment_id`). Trong `tests/unit/storage/test_agent_control_store.py`: xoá các test gọi 2 hàm đã bỏ, giữ test `read_deployment_id`.

Kiểm tra không còn ai import đồ đã xoá:

```bash
grep -rn "pg_registry\|gateway.registry\|gateway.errors\|RegistryUnavailable\|read_tenant_active\|read_tenant_key_hashes\|build_registry\|tenant_from_host" src tests scripts --include="*.py" | grep -v __pycache__
```

Expected: chỉ còn hit trong `scripts/` (sửa ở Step 4) — nếu còn hit trong `src/`/`tests/`, sửa nốt. Lưu ý `noble_agent.tenant.store` (MinioTenantStore) vẫn dùng cho legacy config bundle — KHÔNG xoá; chỉ gateway thôi không dùng nó.

- [ ] **Step 4: Cập nhật scripts**

- `scripts/smoke_gateway_chat.py` + `scripts/smoke_gateway_voice.py`: đổi dòng hướng dẫn env `GATEWAY_BASE_DOMAIN=localhost` → `GATEWAY_CREDENTIALS_API_URL=http://<portal>/api/v1/agent/runtime-credentials`; nếu script dựng URL dạng `t1.localhost` thì đổi thành host bất kỳ (host không còn ý nghĩa).
- `scripts/e2e_dbmode/verify_portal_reads.py`: nếu gọi `read_tenant_active`/`read_tenant_key_hashes` thì xoá phần đó (hoặc cả script nếu chỉ để verify 2 reader này — đọc file rồi quyết, ghi chú lại trong commit message).

- [ ] **Step 5: Xoá `gateway_base_domain` khỏi `config.py`** (dòng ~110) và grep xác nhận:

```bash
grep -rn "gateway_base_domain\|GATEWAY_BASE_DOMAIN" src tests scripts .env.example --include="*.py" 2>/dev/null; grep -n "GATEWAY_BASE_DOMAIN" .env.example
```

Expected: 0 hit trong src/tests; `.env.example` nếu có dòng này thì thay bằng `GATEWAY_CREDENTIALS_API_URL=`.

- [ ] **Step 6: Chạy toàn bộ gateway tests + lint**

Run: `pytest tests/unit/gateway/ tests/unit/storage/ -q && make lint`
Expected: PASS, lint sạch.

- [ ] **Step 7: Commit**

```bash
git add -u src/noble_agent/gateway/ src/noble_agent/storage/agent_control_store.py src/noble_agent/config.py \
    tests/unit/gateway/ tests/unit/storage/test_agent_control_store.py \
    scripts/smoke_gateway_chat.py scripts/smoke_gateway_voice.py scripts/e2e_dbmode/verify_portal_reads.py .env.example
git commit -m "feat(gateway): single-domain auth qua credentials API — xoá subdomain + registry control.*"
```

---

### Task 4: `storage/tenant_credentials.py` — registry credential PG in-process

**Files:**
- Create: `src/noble_agent/storage/tenant_credentials.py`
- Test: `tests/unit/storage/test_tenant_credentials.py`

**Interfaces:**
- Produces: `TenantPgCredential(role: str, password: str, expires_at: datetime)` (frozen dataclass); `register(tenant_id, *, role, password, expires_at) -> None`; `get(tenant_id, *, now=None) -> TenantPgCredential | None` (hết hạn → xoá entry + trả None); `clear_for_tests()`.

- [ ] **Step 1: Viết test fail trước** — `tests/unit/storage/test_tenant_credentials.py`:

```python
"""Registry in-process credential PG per-tenant (worker nhận từ gateway)."""

from datetime import UTC, datetime, timedelta

from noble_agent.storage import tenant_credentials as tc


def setup_function():
    tc.clear_for_tests()


def _exp(sec=3600):
    return datetime.now(UTC) + timedelta(seconds=sec)


def test_register_and_get():
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    got = tc.get("anphu")
    assert got is not None
    assert got.role == "agent_anphu" and got.password == "pw"


def test_get_unknown_tenant():
    assert tc.get("nope") is None


def test_expired_credential_dropped():
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp(-1))
    assert tc.get("anphu") is None
    assert tc.get("anphu") is None  # idempotent sau khi drop


def test_register_overwrites():
    tc.register("anphu", role="agent_anphu", password="old", expires_at=_exp())
    tc.register("anphu", role="agent_anphu", password="new", expires_at=_exp())
    assert tc.get("anphu").password == "new"
```

- [ ] **Step 2: Chạy fail**

Run: `pytest tests/unit/storage/test_tenant_credentials.py -x -q`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement `src/noble_agent/storage/tenant_credentials.py`**

```python
"""Credential Postgres per-tenant do gateway forward (X-PG-Role/-Password/-Expires).

Registry in-process {tenant_id → TenantPgCredential}: ws_handler đăng ký khi mở
session chat qua gateway; `postgres_client.pool_for_tenant` đọc để dựng pool riêng.
Không có entry (dev local, REPL, voice, heartbeat) nghĩa là "dùng shared DSN" —
không phải lỗi. Hết `expires_at` → coi như chưa đăng ký (drop + None)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class TenantPgCredential:
    role: str
    password: str
    expires_at: datetime


_creds: dict[str, TenantPgCredential] = {}


def register(tenant_id: str, *, role: str, password: str, expires_at: datetime) -> None:
    _creds[tenant_id] = TenantPgCredential(role=role, password=password, expires_at=expires_at)


def get(tenant_id: str, *, now: datetime | None = None) -> TenantPgCredential | None:
    cred = _creds.get(tenant_id)
    if cred is None:
        return None
    if (now or datetime.now(UTC)) >= cred.expires_at:
        _creds.pop(tenant_id, None)
        return None
    return cred


def clear_for_tests() -> None:
    _creds.clear()
```

- [ ] **Step 4: Chạy pass**

Run: `pytest tests/unit/storage/test_tenant_credentials.py -x -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/storage/tenant_credentials.py tests/unit/storage/test_tenant_credentials.py
git commit -m "feat(storage): registry credential PG per-tenant (nhận từ gateway)"
```

---

### Task 5: `postgres_client.pool_for_tenant` + `POSTGRES_SERVER_DSN`

**Files:**
- Modify: `src/noble_agent/storage/postgres_client.py`
- Modify: `src/noble_agent/config.py` (thêm field cạnh `postgres_dsn`, dòng ~455)
- Test: `tests/unit/storage/test_pool_for_tenant.py`

**Interfaces:**
- Consumes: `tenant_credentials.get(tenant_id)` (Task 4), `settings.postgres_server_dsn`.
- Produces: `build_tenant_dsn(server_dsn: str, role: str, password: str) -> str`; `async pool_for_tenant(tenant_id: str) -> pool`; `close_tenant_pools_for_tests()`. `get_pool`/`tenant_conn`/`set_pool_for_tests` GIỮ NGUYÊN.

- [ ] **Step 1: Thêm field config** — trong `config.py` ngay dưới `POSTGRES_DSN` (dòng ~455):

```python
    # DSN KHÔNG chứa user/password (vd postgresql://10.50.13.220:5433/odyssey).
    # Worker lắp role+password per-tenant (từ runtime-credentials) vào để dựng pool
    # riêng. Rỗng ⇒ pool_for_tenant luôn fallback shared POSTGRES_DSN.
    postgres_server_dsn: str = Field("", alias="POSTGRES_SERVER_DSN")
```

- [ ] **Step 2: Viết test fail trước** — `tests/unit/storage/test_pool_for_tenant.py`:

```python
"""pool_for_tenant: pool per-tenant từ credential, fallback shared khi không có."""

from datetime import UTC, datetime, timedelta

import pytest

from noble_agent.storage import postgres_client as pc
from noble_agent.storage import tenant_credentials as tc


def setup_function():
    tc.clear_for_tests()
    pc.set_pool_for_tests(None)
    pc.close_tenant_pools_for_tests()


def _exp():
    return datetime.now(UTC) + timedelta(hours=1)


def test_build_tenant_dsn_basic():
    dsn = pc.build_tenant_dsn("postgresql://10.50.13.220:5433/odyssey", "agent_anphu", "s3cret")
    assert dsn == "postgresql://agent_anphu:s3cret@10.50.13.220:5433/odyssey"


def test_build_tenant_dsn_quotes_special_chars():
    dsn = pc.build_tenant_dsn("postgresql://h:5432/db", "agent_a", "p@ss:w/ord")
    assert dsn == "postgresql://agent_a:p%40ss%3Aw%2Ford@h:5432/db"


def test_build_tenant_dsn_strips_existing_userinfo():
    dsn = pc.build_tenant_dsn("postgresql://old:cred@h:5432/db", "agent_a", "pw")
    assert dsn == "postgresql://agent_a:pw@h:5432/db"


async def test_no_credential_falls_back_to_shared(monkeypatch):
    shared = object()
    pc.set_pool_for_tests(shared)
    assert await pc.pool_for_tenant("anphu") is shared


async def test_credential_builds_tenant_pool(monkeypatch):
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": "postgresql://h:5432/db"})(),
    )
    created = {}

    async def fake_create_pool(dsn, **kw):
        created["dsn"] = dsn
        return object()

    monkeypatch.setattr(pc, "_create_tenant_pool", fake_create_pool)
    pool = await pc.pool_for_tenant("anphu")
    assert created["dsn"] == "postgresql://agent_anphu:pw@h:5432/db"
    # Gọi lần 2 cùng credential → cache, không dựng lại
    created.clear()
    assert await pc.pool_for_tenant("anphu") is pool
    assert created == {}


async def test_password_change_rebuilds_pool(monkeypatch):
    tc.register("anphu", role="agent_anphu", password="pw1", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": "postgresql://h:5432/db"})(),
    )

    class _FakePool:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    pools = []

    async def fake_create_pool(dsn, **kw):
        p = _FakePool()
        pools.append(p)
        return p

    monkeypatch.setattr(pc, "_create_tenant_pool", fake_create_pool)
    p1 = await pc.pool_for_tenant("anphu")
    tc.register("anphu", role="agent_anphu", password="pw2", expires_at=_exp())
    p2 = await pc.pool_for_tenant("anphu")
    assert p2 is not p1
    assert pools[0].terminated  # pool cũ bị đóng khi fingerprint đổi


async def test_credential_but_no_server_dsn_falls_back_shared(monkeypatch):
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": ""})(),
    )
    shared = object()
    pc.set_pool_for_tests(shared)
    assert await pc.pool_for_tenant("anphu") is shared


async def test_expired_credential_falls_back_shared():
    tc.register("anphu", role="agent_anphu", password="pw",
                expires_at=datetime.now(UTC) - timedelta(seconds=1))
    shared = object()
    pc.set_pool_for_tests(shared)
    assert await pc.pool_for_tenant("anphu") is shared


async def test_pool_build_failure_raises_no_fallback(monkeypatch):
    """Password sai / PG từ chối → lỗi nổi lên, KHÔNG rơi về shared (mở rộng quyền = sai hướng)."""
    tc.register("anphu", role="agent_anphu", password="bad", expires_at=_exp())
    monkeypatch.setattr(
        "noble_agent.config.get_settings",
        lambda: type("S", (), {"postgres_server_dsn": "postgresql://h:5432/db"})(),
    )

    async def boom(dsn, **kw):
        raise RuntimeError("auth failed")

    monkeypatch.setattr(pc, "_create_tenant_pool", boom)
    pc.set_pool_for_tests(object())
    with pytest.raises(RuntimeError):
        await pc.pool_for_tenant("anphu")
```

- [ ] **Step 3: Chạy fail**

Run: `pytest tests/unit/storage/test_pool_for_tenant.py -x -q`
Expected: FAIL — `build_tenant_dsn`/`pool_for_tenant` chưa tồn tại.

- [ ] **Step 4: Implement trong `postgres_client.py`** — thêm vào cuối file (trước `set_pool_for_tests`), và cập nhật docstring module (thêm đoạn: khi worker có credential per-tenant từ gateway, `pool_for_tenant` dựng pool bằng chính role đó — isolation phía DB theo danh tính đăng nhập; shared DSN là fallback):

```python
from urllib.parse import quote, urlsplit, urlunsplit  # đặt ở đầu file cùng các import khác

# tenant_id → (fingerprint sha256(role:password), pool, loop tạo pool)
_tenant_pools: dict[str, tuple[str, Any, asyncio.AbstractEventLoop]] = {}


def build_tenant_dsn(server_dsn: str, role: str, password: str) -> str:
    """Lắp role+password vào DSN server (không credential). Userinfo có sẵn bị thay."""
    parts = urlsplit(server_dsn)
    hostpart = parts.netloc.rsplit("@", 1)[-1]
    userinfo = f"{quote(role, safe='')}:{quote(password, safe='')}"
    return urlunsplit((parts.scheme, f"{userinfo}@{hostpart}", parts.path, parts.query, parts.fragment))


async def _create_tenant_pool(dsn: str):
    """Seam cho test. Pool per-tenant nhỏ hơn shared (nhiều tenant cùng process)."""
    import asyncpg  # lazy như get_pool

    return await asyncpg.create_pool(dsn, min_size=1, max_size=5)


async def pool_for_tenant(tenant_id: str) -> Any:
    """Pool cho MỘT tenant: per-tenant role khi worker đã nhận credential từ gateway,
    ngược lại shared ``get_pool()``.

    - Không có credential (dev/REPL/voice/heartbeat) → shared. Không phải lỗi.
    - Có credential nhưng POSTGRES_SERVER_DSN chưa cấu hình → shared + warning
      (transitional; shared vẫn được tenant_conn set_config scope như cũ).
    - Dựng pool per-tenant FAIL (password sai, PG từ chối) → raise, KHÔNG fallback
      shared: rơi về shared lúc lỗi là mở rộng quyền — sai hướng an toàn.
    - Fingerprint (role, password) đổi → đóng pool cũ, dựng lại. Loop-aware như
      ``get_pool`` (LiveKit per-job loop).
    """
    import hashlib

    from noble_agent.storage import tenant_credentials

    cred = tenant_credentials.get(tenant_id)
    if cred is None:
        return await get_pool()
    from noble_agent.config import get_settings

    server_dsn = get_settings().postgres_server_dsn
    if not server_dsn:
        logger.warning(
            "postgres: tenant %s có credential nhưng POSTGRES_SERVER_DSN chưa cấu hình — dùng shared pool",
            tenant_id,
        )
        return await get_pool()
    fp = hashlib.sha256(f"{cred.role}:{cred.password}".encode()).hexdigest()
    running = asyncio.get_running_loop()
    entry = _tenant_pools.get(tenant_id)
    if entry is not None and entry[0] == fp and entry[2] is running and not running.is_closed():
        return entry[1]
    async with _get_lock(running):
        entry = _tenant_pools.get(tenant_id)
        if entry is not None and entry[0] == fp and entry[2] is running and not running.is_closed():
            return entry[1]
        if entry is not None:
            with contextlib.suppress(Exception):
                entry[1].terminate()
            _tenant_pools.pop(tenant_id, None)
        pool = await _create_tenant_pool(build_tenant_dsn(server_dsn, cred.role, cred.password))
        _tenant_pools[tenant_id] = (fp, pool, running)
        logger.info("postgres: pool per-tenant connected (tenant=%s role=%s)", tenant_id, cred.role)
    return pool


def close_tenant_pools_for_tests() -> None:
    for _fp, pool, _loop in _tenant_pools.values():
        with contextlib.suppress(Exception):
            pool.terminate()
    _tenant_pools.clear()
```

- [ ] **Step 5: Chạy pass + regression storage**

Run: `pytest tests/unit/storage/ -q`
Expected: PASS toàn bộ.

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add src/noble_agent/storage/postgres_client.py src/noble_agent/config.py tests/unit/storage/test_pool_for_tenant.py
git commit -m "feat(storage): pool_for_tenant — pool PG per-tenant từ credential, POSTGRES_SERVER_DSN"
```

---

### Task 6: Chuyển call sites sang `pool_for_tenant`

**Files:**
- Modify: `src/noble_agent/storage/pg_data_plane.py` (`_pool_or_none` nhận tenant, ~10 wrapper đảo thứ tự lấy tid)
- Modify: `src/noble_agent/storage/agent_config_store.py:43-46`
- Modify: `src/noble_agent/data/providers/postgres_kb.py:73-81`
- Test: sửa `tests/unit/storage/test_pg_wrappers_use_tenant_conn.py` nếu nó monkeypatch `get_pool`/`_pool_or_none` (đọc file trước khi sửa); thêm test mới vào file đó.

**Interfaces:**
- Consumes: `pool_for_tenant(tenant_id)` (Task 5).
- Produces: `pg_data_plane._pool_or_none(tenant_id: str)` (đổi chữ ký — thêm tham số bắt buộc). KHÔNG đổi chữ ký hàm public nào khác.
- KHÔNG đụng: `agent_control_store._pool` + `pg_heartbeat` (heartbeat giữ shared pool — ghi schema `control`), `tenant/pg_provisioning.py` (admin DSN).

- [ ] **Step 1: Viết test fail trước** — thêm vào `tests/unit/storage/test_pg_wrappers_use_tenant_conn.py` (đọc file trước để khớp fixture có sẵn; nếu file monkeypatch `_pool_or_none` không tham số thì cập nhật các chỗ đó thành nhận 1 tham số):

```python
async def test_pool_or_none_uses_pool_for_tenant(monkeypatch):
    """Wrapper best-effort phải xin pool THEO TENANT (per-tenant role khi có creds)."""
    from noble_agent.storage import pg_data_plane

    seen = {}

    async def fake_pool_for_tenant(tid):
        seen["tid"] = tid
        return None  # đủ để wrapper no-op

    monkeypatch.setattr("noble_agent.storage.postgres_client.pool_for_tenant", fake_pool_for_tenant)
    assert await pg_data_plane._pool_or_none("anphu") is None
    assert seen["tid"] == "anphu"
```

- [ ] **Step 2: Chạy fail**

Run: `pytest tests/unit/storage/test_pg_wrappers_use_tenant_conn.py -x -q`
Expected: test mới FAIL (`_pool_or_none` chưa nhận tham số).

- [ ] **Step 3: Sửa `pg_data_plane.py`**

```python
async def _pool_or_none(tenant_id: str):
    """Pool theo tenant (per-tenant role khi có credential), hoặc None khi Postgres
    chưa cấu hình/unreachable — wrapper best-effort no-op thay vì nổ trên hot path.
    Lưu ý: pool per-tenant dựng FAIL (password sai) cũng rơi vào None ở đây — wrapper
    là best-effort; đường đọc bắt buộc (config) thì KHÔNG nuốt kiểu này."""
    try:
        from noble_agent.storage.postgres_client import pool_for_tenant

        return await pool_for_tenant(tenant_id)
    except Exception:
        return None
```

Rồi trong TỪNG wrapper (persist_contact, read_contact_snapshot, persist_customer_profile, … — grep `_pool_or_none()` ra đủ ~10 chỗ): đảo thứ tự — lấy `tid = _tenant_id()` TRƯỚC, rồi `pool = await _pool_or_none(tid)`. Ví dụ `persist_contact`:

```python
async def persist_contact(phone: str, snapshot: str) -> None:
    if not phone:
        return
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return
    try:
        async with tenant_conn(pool, tid) as conn:
            await upsert_contact(conn, tenant_id=tid, phone=phone, snapshot=snapshot)
    except Exception:
        logger.warning("pg persist_contact failed", exc_info=True)
```

Cập nhật docstring module (dòng 4-9): shared app role → "per-tenant role khi có credential từ gateway, shared app role là fallback; cả hai đều qua tenant_conn set_config".

- [ ] **Step 4: Sửa `agent_config_store.py`**

```python
async def _read_from_db(tenant_id: str, *, pool=None) -> PublishedConfig | None:
    from noble_agent.storage.postgres_client import pool_for_tenant, tenant_conn

    pool = pool or await pool_for_tenant(tenant_id)
    async with tenant_conn(pool, tenant_id) as conn:
        row = await conn.fetchrow(_SQL, tenant_id)
    ...
```

- [ ] **Step 5: Sửa `postgres_kb.py` `_acquire`**

```python
    def _acquire(self):
        """Async CM yielding a tenant-scoped connection. Overridden in tests."""
        from noble_agent.storage import postgres_client

        async def _ctx():
            tid = current_tenant()
            pool = await postgres_client.pool_for_tenant(tid)
            return postgres_client.tenant_conn(pool, tid)

        return _LazyCtx(_ctx())
```

- [ ] **Step 6: Chạy regression**

Run: `pytest tests/unit/storage/ tests/unit/unified/test_pg_appointment.py tests/unit/unified/test_pg_conversation.py tests/unit/unified/test_pg_customer_profile.py tests/unit/unified/test_pg_conversation_messages.py tests/unit/providers/ -q`
Expected: PASS (các test này inject pool/conn trực tiếp nên không đụng `pool_for_tenant`; nếu có test nào monkeypatch `get_pool` trong pg_data_plane thì đổi sang `pool_for_tenant`).

- [ ] **Step 7: Lint + commit**

```bash
make lint
git add src/noble_agent/storage/pg_data_plane.py src/noble_agent/storage/agent_config_store.py \
    src/noble_agent/data/providers/postgres_kb.py tests/unit/storage/test_pg_wrappers_use_tenant_conn.py
git commit -m "feat(storage): data-plane + config + pg_kb xin pool theo tenant (pool_for_tenant)"
```

---

### Task 7: Forward credential gateway → worker (chat) + worker ingest

**Files:**
- Modify: `src/noble_agent/gateway/chat_proxy.py` (`proxy_headers` + `proxy_chat` dùng param `credentials` đã thêm ở Task 3)
- Modify: `src/noble_agent/server/ws_handler.py` (helper `_register_pg_credentials`, gọi trong nhánh chat sau secret-check)
- Test: `tests/unit/gateway/test_chat_proxy.py` (thêm case), `tests/unit/unified/test_ws_pg_credentials.py` (mới)

**Interfaces:**
- Consumes: `RuntimeCredentials` (Task 1), `tenant_credentials.register` (Task 4).
- Produces: `proxy_headers(settings, tenant_id, credentials=None) -> dict` (thêm `X-PG-Role`/`X-PG-Password`/`X-PG-Expires` khi credentials có role+password); `ws_handler._register_pg_credentials(headers, tenant_id) -> bool`.

- [ ] **Step 1: Viết test fail trước.** Thêm vào `tests/unit/gateway/test_chat_proxy.py` (đọc file trước, khớp helper/fake settings có sẵn):

```python
from datetime import UTC, datetime

from noble_agent.gateway.chat_proxy import proxy_headers
from noble_agent.gateway.credentials import RuntimeCredentials


def _creds(role="agent_anphu", pw="s3cret"):
    return RuntimeCredentials(
        tenant_id="anphu", deployment_id=1, kind="chat",
        postgres_role=role, postgres_password=pw,
        expires_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
    )


def test_proxy_headers_include_pg_credentials(settings_with_secret):
    h = proxy_headers(settings_with_secret, "anphu", credentials=_creds())
    assert h["X-PG-Role"] == "agent_anphu"
    assert h["X-PG-Password"] == "s3cret"
    assert h["X-PG-Expires"] == "2026-08-10T09:00:00+00:00"


def test_proxy_headers_no_credentials_no_pg_headers(settings_with_secret):
    h = proxy_headers(settings_with_secret, "anphu", credentials=None)
    assert "X-PG-Role" not in h and "X-PG-Password" not in h


def test_proxy_headers_empty_role_skipped(settings_with_secret):
    h = proxy_headers(settings_with_secret, "anphu", credentials=_creds(role=""))
    assert "X-PG-Role" not in h
```

(`settings_with_secret`: nếu file test hiện dùng fake settings khác thì tái dùng đúng pattern đó thay vì fixture tên này.)

Tạo `tests/unit/unified/test_ws_pg_credentials.py`:

```python
"""Worker ingest PG credential từ header gateway (chỉ sau khi secret-check pass)."""

from datetime import UTC, datetime, timedelta

from noble_agent.server.ws_handler import _register_pg_credentials
from noble_agent.storage import tenant_credentials as tc


def setup_function():
    tc.clear_for_tests()


def _headers(**over):
    h = {
        "X-PG-Role": "agent_anphu",
        "X-PG-Password": "pw",
        "X-PG-Expires": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    h.update(over)
    return {k: v for k, v in h.items() if v is not None}


def test_register_ok():
    assert _register_pg_credentials(_headers(), "anphu") is True
    cred = tc.get("anphu")
    assert cred is not None and cred.role == "agent_anphu"


def test_missing_any_header_skips():
    for drop in ("X-PG-Role", "X-PG-Password", "X-PG-Expires"):
        tc.clear_for_tests()
        assert _register_pg_credentials(_headers(**{drop: None}), "anphu") is False
        assert tc.get("anphu") is None


def test_bad_expires_skips():
    assert _register_pg_credentials(_headers(**{"X-PG-Expires": "hôm-qua"}), "anphu") is False
    assert tc.get("anphu") is None


def test_no_tenant_skips():
    assert _register_pg_credentials(_headers(), None) is False


def test_z_suffix_expires_ok():
    assert _register_pg_credentials(_headers(**{"X-PG-Expires": "2099-01-01T00:00:00Z"}), "anphu") is True
```

- [ ] **Step 2: Chạy fail**

Run: `pytest tests/unit/gateway/test_chat_proxy.py tests/unit/unified/test_ws_pg_credentials.py -x -q`
Expected: FAIL.

- [ ] **Step 3: Implement `chat_proxy.py`**

```python
def proxy_headers(settings, tenant_id: str, credentials=None) -> dict:
    """Headers the gateway sends to the worker /chat: tenant + shared-secret (nếu có)
    + PG credential per-tenant (X-PG-*) để worker dựng pool bằng chính role tenant."""
    headers = {"X-Tenant-Id": tenant_id}
    if settings.gateway_worker_secret:
        headers["X-Gateway-Secret"] = settings.gateway_worker_secret
    if credentials is not None and credentials.postgres_role and credentials.postgres_password:
        headers["X-PG-Role"] = credentials.postgres_role
        headers["X-PG-Password"] = credentials.postgres_password
        if credentials.expires_at is not None:
            headers["X-PG-Expires"] = credentials.expires_at.isoformat()
    return headers
```

Trong `proxy_chat` (đã có param `credentials=None` từ Task 3): `headers = proxy_headers(settings, tenant_id, credentials=credentials)`.

- [ ] **Step 4: Implement `ws_handler.py`**

Thêm import `from datetime import UTC, datetime` đầu file, helper cạnh `_tenant_from_headers`:

```python
def _register_pg_credentials(headers, tenant_id) -> bool:
    """Đăng ký credential PG per-tenant do gateway forward (X-PG-Role/-Password/-Expires).
    CHỈ gọi sau khi _gateway_secret_ok pass. Thiếu/hỏng header nào → bỏ qua (worker
    fallback shared DSN) — không phải lỗi; voice + dev local không có các header này."""
    if not headers or not tenant_id:
        return False
    role = (headers.get("X-PG-Role") or "").strip()
    password = headers.get("X-PG-Password") or ""
    raw_exp = (headers.get("X-PG-Expires") or "").strip()
    if not role or not password or not raw_exp:
        return False
    try:
        expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    from noble_agent.storage import tenant_credentials

    tenant_credentials.register(tenant_id, role=role, password=password, expires_at=expires_at)
    return True
```

Trong `_handle_session`, nhánh chat, NGAY SAU khối `_gateway_secret_ok` (sau dòng 120 `return`), TRƯỚC `handle_text_session`:

```python
        _register_pg_credentials(hdrs, _tenant_from_headers(hdrs))
        await text_chat.handle_text_session(ws, session_id, tenant_id=_tenant_from_headers(hdrs))
```

- [ ] **Step 5: Chạy pass + regression**

Run: `pytest tests/unit/gateway/ tests/unit/unified/test_ws_pg_credentials.py -q`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add src/noble_agent/gateway/chat_proxy.py src/noble_agent/server/ws_handler.py \
    tests/unit/gateway/test_chat_proxy.py tests/unit/unified/test_ws_pg_credentials.py
git commit -m "feat: forward PG credential gateway→worker qua header nội bộ, worker đăng ký per-tenant"
```

---

### Task 8: E2E script + docs + full regression + live verify

**Files:**
- Modify: `scripts/e2e_dbmode/chat_via_gateway.py`
- Modify: `CLAUDE.md` (mục "Một agent dùng chung cho N tenant" + bảng Change Log), `docs/CHANGELOG-agent.md` (entry mới đầu bảng), `docs/architecture/multi-tenant.md` (đoạn gateway auth nếu có)
- Modify: `.env.example` (thêm `GATEWAY_CREDENTIALS_API_URL=`, `POSTGRES_SERVER_DSN=` nếu chưa làm ở Task 3/5)

**Interfaces:** không có — task tổng hợp + verify.

- [ ] **Step 1: Sửa `scripts/e2e_dbmode/chat_via_gateway.py`**

Docstring: mô tả luồng mới (single domain + credentials API). URL đổi:

```python
    async with websockets.connect(
        "ws://noble-saas.lvh.me:9200/v1/chat",
        additional_headers={"Authorization": "Bearer " + TOKEN},
    ) as ws:
```

(Host giờ vô nghĩa với gateway — giữ `noble-saas.lvh.me` để phản ánh domain chung.)

- [ ] **Step 2: Full test + lint**

Run: `make test-unified && make lint`
Expected: PASS (đối chiếu các fail env-dependent đã biết — xem memory `unit-suite-env-dependent-failures`: fail sẵn trước thay đổi thì không phải do mình; xác nhận bằng cách chỉ soi các test mới fail).

- [ ] **Step 3: Live verify (nếu hạ tầng reachable)**

1. Kiểm tra auth API: `curl -s -X POST http://10.50.13.208/api/v1/agent/runtime-credentials -H "Authorization: Bearer <key thật>"` — cần trả JSON credential.
2. `.env`: set `GATEWAY_CREDENTIALS_API_URL=http://10.50.13.208/api/v1/agent/runtime-credentials`, `POSTGRES_SERVER_DSN=<host:port/db của Odyssey PG>`.
3. Chạy worker (`scripts/run.sh`) + gateway (process gateway), rồi `python scripts/e2e_dbmode/chat_via_gateway.py "dự án nào đang mở bán?"`.
4. Verify: (a) chat trả lời đúng dữ liệu tenant; (b) log worker có `postgres: pool per-tenant connected (tenant=… role=agent_…)`; (c) log gateway không có warning credential; (d) key sai → close 4001 `bad_credential`; (e) tắt auth API (hoặc URL sai) + key chưa cache → 4001 `auth_api_unavailable`.
5. Nếu role per-tenant thấy 0 rows (RLS phía Portal chưa xong): báo user — theo spec đây là trách nhiệm Portal; ghi rõ hiện trạng, KHÔNG tự sửa DDL.
6. Không reachable → ghi rõ trong báo cáo cuối là live verify chưa chạy được và cần gì để chạy.

- [ ] **Step 4: Cập nhật docs**

- `docs/CHANGELOG-agent.md`: entry mới ĐẦU bảng (ngày 2026-08-10): gateway auth chuyển sang runtime-credentials API (single domain, xoá subdomain + đọc control.* ở gateway); PG per-tenant role qua `pool_for_tenant` + `POSTGRES_SERVER_DSN`; voice giữ shared DSN (follow-up).
- `CLAUDE.md`: sửa mục "Một agent dùng chung cho N tenant" (câu "Chat: tenant đi trong header X-Tenant-Id" thêm: auth gateway qua runtime-credentials API, PG per-tenant role khi có credential); thêm entry 1–2 câu vào bảng `## Change Log` (xoá entry thứ 11).
- `docs/architecture/multi-tenant.md`: grep "subdomain\|base_domain\|tenant_from_host" và cập nhật đoạn mô tả gateway auth.
- `.env.example`: xác nhận có `GATEWAY_CREDENTIALS_API_URL=` + `POSTGRES_SERVER_DSN=` kèm comment 1 dòng.

- [ ] **Step 5: Commit cuối**

```bash
git add scripts/e2e_dbmode/chat_via_gateway.py CLAUDE.md docs/CHANGELOG-agent.md docs/architecture/multi-tenant.md .env.example
git commit -m "docs+e2e: gateway single-domain runtime-credentials — cập nhật script e2e, CLAUDE.md, changelog"
```

---

## Self-Review Notes (đã chạy)

- **Spec coverage:** §1 gateway → Tasks 1–3; §2 forward → Task 7 (+ voice giữ nguyên: không task, đúng spec); §3 worker pool → Tasks 4–6; §4 config → gộp vào Tasks 1/3/5; §5 error handling → phủ trong test Tasks 1/2/5; §6 testing/e2e/docs → Task 8. Không gap.
- **Type consistency:** `RuntimeCredentials` (T1) dùng ở T2/T3/T7; `pool_for_tenant(tenant_id)` (T5) dùng ở T6; `_pool_or_none(tenant_id)` đổi chữ ký chỉ trong T6; `proxy_chat(..., credentials=None)` thêm ở T3, dùng ở T7 — nhất quán.
- **Điểm cần linh hoạt khi thực thi:** nội dung thật của `test_chat_proxy.py`, `test_agent_control_store.py`, `test_pg_wrappers_use_tenant_conn.py`, `verify_portal_reads.py`, `_extract_request` test — kế hoạch đã ghi "đọc file trước, khớp pattern có sẵn" tại từng chỗ.
