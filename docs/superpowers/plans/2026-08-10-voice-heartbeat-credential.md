# Voice + Heartbeat Per-Tenant Credential — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Voice (LiveKit qua gateway) và heartbeat dùng PG credential per-tenant: gateway stash credential (mã hoá Fernet) vào Redis nội bộ, voice worker ingest lúc vào job; heartbeat lấy `deployment_id` từ credential thay vì SELECT `control.deployments` (role tenant bị chặn quyền).

**Architecture:** Module mới `storage/credential_stash.py` (Fernet key dẫn xuất từ `GATEWAY_WORKER_SECRET`, stash/fetch Redis với TTL = expires_at, `fetch_and_register` đăng ký vào registry). `TenantPgCredential` thêm `deployment_id`/`kind`; chat forward thêm 2 header; heartbeat chọn nguồn theo credential.

**Tech Stack:** Python 3.11+, cryptography (Fernet), redis.asyncio (client sẵn có `storage/redis_client.get_redis`), pytest asyncio_mode=auto.

**Spec:** `docs/superpowers/specs/2026-08-10-voice-heartbeat-credential-design.md`

## Global Constraints

- Branch `feat/share-agent` — không branch mới/merge/push. Commit local từng task, message kết thúc bằng `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- KHÔNG BAO GIỜ chạy `git stash` / `git checkout --` / `git reset` / `git add -A|-u|.` — working tree có WIP của user; stage đích danh từng file.
- KHÔNG sửa `.env` (config live của user). `.env.example` sửa được khi task yêu cầu.
- Ruff line-length 120; chỉ file mình đụng phải sạch (`ruff check <files>`). Baseline repo có ~198 lỗi pre-existing ở file khác — bỏ qua.
- Pytest: dùng `.venv/bin/pytest`; asyncio_mode=auto (async test không cần decorator). Full-suite baseline có ~29-31 fail env-dependent/flaky pre-existing — CHỈ cấm fail MỚI.
- Fail-safe hướng an toàn: mọi lỗi stash/fetch/decrypt → rơi về shared DSN, KHÔNG làm rớt cuộc gọi/kết nối. Secret rỗng → không stash, không ingest.
- Key Redis: `noble:pgcred:<tenant_id>`. TTL = `max(1, int(giây tới expires_at))`.
- Header mới: `X-PG-Deployment` (int dạng str), `X-PG-Kind` (str) — OPTIONAL: hỏng/thiếu không từ chối kết nối, chỉ mất tính năng heartbeat-từ-credential.

---

### Task 1: `TenantPgCredential` thêm `deployment_id` + `kind`

**Files:**
- Modify: `src/noble_agent/storage/tenant_credentials.py`
- Test: `tests/unit/storage/test_tenant_credentials.py` (thêm test, giữ 4 test cũ)

**Interfaces:**
- Consumes: registry hiện tại (`register(tenant_id, *, role, password, expires_at)`, `get`, `clear_for_tests`).
- Produces: `TenantPgCredential(role, password, expires_at, deployment_id: int | None = None, kind: str = "")`; `register(tenant_id, *, role, password, expires_at, deployment_id=None, kind="")`. Call cũ (không truyền 2 kwarg mới) phải chạy nguyên trạng.

- [ ] **Step 1: Thêm test fail** — append vào `tests/unit/storage/test_tenant_credentials.py`:

```python
def test_register_with_deployment_and_kind():
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp(),
                deployment_id=6, kind="chat")
    cred = tc.get("anphu")
    assert cred.deployment_id == 6 and cred.kind == "chat"


def test_register_defaults_deployment_none_kind_empty():
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    cred = tc.get("anphu")
    assert cred.deployment_id is None and cred.kind == ""
```

- [ ] **Step 2: Chạy fail**

Run: `.venv/bin/pytest tests/unit/storage/test_tenant_credentials.py -q`
Expected: 2 test mới FAIL (`unexpected keyword argument 'deployment_id'`).

- [ ] **Step 3: Implement** — trong `tenant_credentials.py`:

```python
@dataclass(frozen=True)
class TenantPgCredential:
    role: str
    password: str
    expires_at: datetime
    deployment_id: int | None = None
    kind: str = ""
```

```python
def register(
    tenant_id: str, *, role: str, password: str, expires_at: datetime,
    deployment_id: int | None = None, kind: str = "",
) -> None:
    _creds[tenant_id] = TenantPgCredential(
        role=role, password=password, expires_at=expires_at,
        deployment_id=deployment_id, kind=kind,
    )
```

Docstring module: thêm 1 câu — "`deployment_id`/`kind` (từ runtime-credentials API) phục vụ heartbeat: beat không cần SELECT control.deployments (role tenant bị chặn quyền)."

- [ ] **Step 4: Chạy pass**

Run: `.venv/bin/pytest tests/unit/storage/test_tenant_credentials.py -q`
Expected: 6/6 PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/storage/tenant_credentials.py tests/unit/storage/test_tenant_credentials.py
git add src/noble_agent/storage/tenant_credentials.py tests/unit/storage/test_tenant_credentials.py
git commit -m "feat(storage): TenantPgCredential mang deployment_id/kind từ credential API"
```

---

### Task 2: `storage/credential_stash.py` — Fernet + Redis stash/fetch/register

**Files:**
- Create: `src/noble_agent/storage/credential_stash.py`
- Modify: `pyproject.toml` (khai báo `"cryptography>=42",` vào `dependencies` — hiện chỉ có transitively qua livekit; cạnh dòng `"httpx>=0.27",`)
- Test: `tests/unit/storage/test_credential_stash.py`

**Interfaces:**
- Consumes: `tenant_credentials.register(tenant_id, *, role, password, expires_at, deployment_id, kind)` (Task 1).
- Produces:
  - `derive_key(secret: str) -> bytes`
  - `encrypt_credential(secret: str, payload: dict) -> str`
  - `decrypt_credential(secret: str, token: str) -> dict | None` (mọi lỗi → None)
  - `stash_key(tenant_id: str) -> str` = `f"noble:pgcred:{tenant_id}"`
  - `async stash(redis, secret, tenant_id, *, role, password, deployment_id, kind, expires_at) -> bool`
  - `async fetch(redis, secret, tenant_id) -> dict | None`
  - `async fetch_and_register(redis, secret, tenant_id) -> bool`
  - `ttl_seconds(expires_at: datetime, *, now=None) -> int` (max(1, int còn lại))

- [ ] **Step 1: Viết test fail** — tạo `tests/unit/storage/test_credential_stash.py`:

```python
"""Fernet stash Redis: cầu nối credential gateway → LiveKit voice worker."""

from datetime import UTC, datetime, timedelta

from noble_agent.storage import credential_stash as cs
from noble_agent.storage import tenant_credentials as tc

SECRET = "motchuoibatky"


def setup_function():
    tc.clear_for_tests()


def _exp(sec=3600):
    return datetime.now(UTC) + timedelta(seconds=sec)


class _FakeRedis:
    """Chỉ mô phỏng set(name, value, ex=...) + get(name) mà stash/fetch dùng."""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def set(self, name, value, ex=None):
        self.store[name] = value
        self.ttls[name] = ex

    async def get(self, name):
        return self.store.get(name)


def test_encrypt_decrypt_roundtrip():
    payload = {"role": "agent_a", "password": "p@ss", "deployment_id": 6, "kind": "voice"}
    token = cs.encrypt_credential(SECRET, payload)
    assert token != str(payload)  # không phải plaintext
    assert cs.decrypt_credential(SECRET, token) == payload


def test_decrypt_wrong_secret_returns_none():
    token = cs.encrypt_credential(SECRET, {"role": "a"})
    assert cs.decrypt_credential("secret-khac", token) is None


def test_decrypt_garbage_returns_none():
    assert cs.decrypt_credential(SECRET, "not-a-fernet-token") is None
    assert cs.decrypt_credential(SECRET, "") is None


def test_ttl_seconds_clamps_to_one():
    assert cs.ttl_seconds(_exp(120)) in (119, 120)
    assert cs.ttl_seconds(_exp(-50)) == 1


async def test_stash_and_fetch_roundtrip():
    r = _FakeRedis()
    ok = await cs.stash(r, SECRET, "eco_green", role="agent_eco_green", password="pw",
                        deployment_id=7, kind="voice", expires_at=_exp())
    assert ok is True
    assert list(r.store) == ["noble:pgcred:eco_green"]
    assert r.ttls["noble:pgcred:eco_green"] >= 3599 - 1
    got = await cs.fetch(r, SECRET, "eco_green")
    assert got["role"] == "agent_eco_green" and got["deployment_id"] == 7


async def test_fetch_missing_key_returns_none():
    assert await cs.fetch(_FakeRedis(), SECRET, "nope") is None


async def test_fetch_and_register_registers():
    r = _FakeRedis()
    await cs.stash(r, SECRET, "eco_green", role="agent_eco_green", password="pw",
                   deployment_id=7, kind="voice", expires_at=_exp())
    assert await cs.fetch_and_register(r, SECRET, "eco_green") is True
    cred = tc.get("eco_green")
    assert cred is not None
    assert cred.role == "agent_eco_green" and cred.deployment_id == 7 and cred.kind == "voice"


async def test_fetch_and_register_no_key_false():
    assert await cs.fetch_and_register(_FakeRedis(), SECRET, "eco_green") is False
    assert tc.get("eco_green") is None


async def test_fetch_and_register_empty_secret_skips_redis():
    r = _FakeRedis()

    async def boom(name):  # secret rỗng thì không được đụng Redis
        raise AssertionError("must not touch redis")

    r.get = boom
    assert await cs.fetch_and_register(r, "", "eco_green") is False


async def test_fetch_and_register_bad_expires_false():
    r = _FakeRedis()
    token = cs.encrypt_credential(SECRET, {"role": "a", "password": "p",
                                           "deployment_id": 1, "kind": "voice",
                                           "expires_at": "hôm-qua"})
    await r.set(cs.stash_key("eco_green"), token)
    assert await cs.fetch_and_register(r, SECRET, "eco_green") is False
```

- [ ] **Step 2: Chạy fail**

Run: `.venv/bin/pytest tests/unit/storage/test_credential_stash.py -q`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Khai báo dependency** — trong `pyproject.toml`, thêm vào list `dependencies` (cạnh `"httpx>=0.27",`):

```toml
    "cryptography>=42",
```

(Không cần pip install — venv đã có 48.0.0 qua livekit; khai báo để tường minh.)

- [ ] **Step 4: Implement `src/noble_agent/storage/credential_stash.py`:**

```python
"""Stash credential PG per-tenant qua Redis nội bộ — cầu nối gateway → LiveKit voice worker.

Voice không có hop trực tiếp gateway→worker (dispatch đi qua LiveKit Cloud, không
nhét secret vào metadata được). Gateway ghi credential đã MÃ HOÁ Fernet vào Redis
(key ``noble:pgcred:<tenant>``, TTL = giây còn lại tới expires_at — Redis tự xoá);
worker job fetch + giải mã + đăng ký vào ``tenant_credentials`` lúc vào cuộc.

Khoá Fernet dẫn xuất từ ``GATEWAY_WORKER_SECRET`` (SHA-256 → urlsafe-b64) — hai
process vốn đã bắt buộc chung secret này cho chat forwarding, không thêm env mới.
Secret rỗng ⇒ không stash, không fetch (nhất quán hardening chat: hop không xác
thực thì không tin credential). Mọi lỗi (lệch secret, token rác, JSON hỏng,
expires_at hỏng) → None/False — caller rơi về shared DSN, không bao giờ raise
trên đường cuộc gọi."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger("noble_agent.storage.credential_stash")

_KEY_PREFIX = "noble:pgcred:"


def stash_key(tenant_id: str) -> str:
    return f"{_KEY_PREFIX}{tenant_id}"


def derive_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def _fernet(secret: str):
    from cryptography.fernet import Fernet  # lazy: giữ import storage nhẹ

    return Fernet(derive_key(secret))


def encrypt_credential(secret: str, payload: dict) -> str:
    return _fernet(secret).encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")


def decrypt_credential(secret: str, token: str) -> dict | None:
    """Lệch secret / token rác / JSON hỏng → None. Không raise."""
    if not token:
        return None
    try:
        raw = _fernet(secret).decrypt(token.encode("ascii") if isinstance(token, str) else bytes(token))
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 — mọi lỗi giải mã đều là "không có credential"
        return None
    return data if isinstance(data, dict) else None


def ttl_seconds(expires_at: datetime, *, now: datetime | None = None) -> int:
    left = (expires_at - (now or datetime.now(UTC))).total_seconds()
    return max(1, int(left))


async def stash(
    redis, secret: str, tenant_id: str, *,
    role: str, password: str, deployment_id: int | None, kind: str, expires_at: datetime,
) -> bool:
    """Gateway gọi trước khi dispatch voice. Best-effort: False khi thiếu điều kiện."""
    if not secret or not role or not password:
        return False
    payload = {
        "role": role, "password": password, "deployment_id": deployment_id,
        "kind": kind, "expires_at": expires_at.isoformat(),
    }
    await redis.set(stash_key(tenant_id), encrypt_credential(secret, payload), ex=ttl_seconds(expires_at))
    return True


async def fetch(redis, secret: str, tenant_id: str) -> dict | None:
    if not secret:
        return None
    token = await redis.get(stash_key(tenant_id))
    if token is None:
        return None
    if isinstance(token, (bytes, bytearray)):
        token = token.decode("ascii", errors="replace")
    data = decrypt_credential(secret, token)
    if data is None:
        # Có key mà không mở được = hai process lệch GATEWAY_WORKER_SECRET — đáng báo.
        logger.warning("credential_stash: giải mã fail cho tenant %s (lệch secret giữa gateway và worker?)", tenant_id)
    return data


async def fetch_and_register(redis, secret: str, tenant_id: str) -> bool:
    """Voice worker gọi lúc vào job. True = đã đăng ký credential per-tenant."""
    data = await fetch(redis, secret, tenant_id)
    if data is None:
        return False
    role = str(data.get("role") or "")
    password = str(data.get("password") or "")
    raw_exp = str(data.get("expires_at") or "")
    if not role or not password or not raw_exp:
        return False
    try:
        expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    dep = data.get("deployment_id")
    from noble_agent.storage import tenant_credentials

    tenant_credentials.register(
        tenant_id, role=role, password=password, expires_at=expires_at,
        deployment_id=int(dep) if dep is not None else None, kind=str(data.get("kind") or ""),
    )
    logger.info("credential_stash: đã đăng ký credential per-tenant cho %s (role=%s)", tenant_id, role)
    return True
```

- [ ] **Step 5: Chạy pass**

Run: `.venv/bin/pytest tests/unit/storage/test_credential_stash.py tests/unit/storage/test_tenant_credentials.py -q`
Expected: PASS toàn bộ.

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/storage/credential_stash.py tests/unit/storage/test_credential_stash.py
git add src/noble_agent/storage/credential_stash.py tests/unit/storage/test_credential_stash.py pyproject.toml
git commit -m "feat(storage): credential_stash — Fernet stash Redis cầu nối gateway→voice worker"
```

---

### Task 3: Chat forward thêm `X-PG-Deployment` / `X-PG-Kind`

**Files:**
- Modify: `src/noble_agent/gateway/chat_proxy.py` (hàm `proxy_headers`)
- Modify: `src/noble_agent/server/ws_handler.py` (hàm `_register_pg_credentials` — chữ ký hiện tại: `_register_pg_credentials(headers, tenant_id, configured_secret: str) -> bool`)
- Test: `tests/unit/gateway/test_chat_proxy.py`, `tests/unit/unified/test_ws_pg_credentials.py` (đọc cả hai TRƯỚC — thêm test, khớp helper/fixture sẵn có; test cũ giữ nguyên pass)

**Interfaces:**
- Consumes: `RuntimeCredentials` có `deployment_id: int | None` + `kind: str` (sẵn có từ đợt 1); `register(..., deployment_id=, kind=)` (Task 1).
- Produces: header `X-PG-Deployment` = `str(credentials.deployment_id)` (chỉ khi không None) và `X-PG-Kind` = `credentials.kind` (chỉ khi non-empty), nằm TRONG khối `if credentials ... postgres_role and postgres_password` hiện có. Worker parse: deployment hỏng (không phải int) → `None`; kind là str tự do; cả hai OPTIONAL — thiếu vẫn register như cũ.

- [ ] **Step 1: Thêm test fail.** Vào `tests/unit/gateway/test_chat_proxy.py` (khớp pattern fake-settings sẵn có của file):

```python
def test_proxy_headers_include_deployment_and_kind():
    creds = _creds()  # helper sẵn có của file — nếu thiếu deployment_id/kind thì bổ sung vào helper
    h = proxy_headers(_settings_with_secret(), "anphu", credentials=creds)
    assert h["X-PG-Deployment"] == str(creds.deployment_id)
    assert h["X-PG-Kind"] == creds.kind


def test_proxy_headers_no_deployment_header_when_none():
    creds = _creds_without_deployment()  # RuntimeCredentials(deployment_id=None, kind="")
    h = proxy_headers(_settings_with_secret(), "anphu", credentials=creds)
    assert "X-PG-Deployment" not in h and "X-PG-Kind" not in h
```

Vào `tests/unit/unified/test_ws_pg_credentials.py` (file dùng `setup_function` + `_headers(**over)` + secret; khớp chữ ký 3 tham số hiện tại):

```python
def test_register_stores_deployment_and_kind():
    h = _headers(**{"X-PG-Deployment": "6", "X-PG-Kind": "chat"})
    assert _register_pg_credentials(h, "anphu", "secret") is True
    cred = tc.get("anphu")
    assert cred.deployment_id == 6 and cred.kind == "chat"


def test_register_bad_deployment_still_registers_with_none():
    h = _headers(**{"X-PG-Deployment": "abc", "X-PG-Kind": "chat"})
    assert _register_pg_credentials(h, "anphu", "secret") is True
    cred = tc.get("anphu")
    assert cred.deployment_id is None and cred.kind == "chat"


def test_register_without_new_headers_defaults():
    assert _register_pg_credentials(_headers(), "anphu", "secret") is True
    cred = tc.get("anphu")
    assert cred.deployment_id is None and cred.kind == ""
```

(Lưu ý: file test hiện gọi `_register_pg_credentials` với secret — đọc file để lấy đúng giá trị secret các test cũ dùng.)

- [ ] **Step 2: Chạy fail**

Run: `.venv/bin/pytest tests/unit/gateway/test_chat_proxy.py tests/unit/unified/test_ws_pg_credentials.py -q`
Expected: test mới FAIL (thiếu header / thiếu kwarg).

- [ ] **Step 3: Implement.** `chat_proxy.py::proxy_headers` — trong khối `if credentials is not None and ...` hiện có, sau `X-PG-Expires`:

```python
        if credentials.deployment_id is not None:
            headers["X-PG-Deployment"] = str(credentials.deployment_id)
        if credentials.kind:
            headers["X-PG-Kind"] = credentials.kind
```

`ws_handler.py::_register_pg_credentials` — trước dòng `tenant_credentials.register(...)`:

```python
    raw_dep = str(headers.get("X-PG-Deployment") or "").strip()
    try:
        deployment_id = int(raw_dep) if raw_dep else None
    except ValueError:
        deployment_id = None
    kind = str(headers.get("X-PG-Kind") or "").strip()
```

và đổi call:

```python
    tenant_credentials.register(
        tenant_id, role=role, password=password, expires_at=expires_at,
        deployment_id=deployment_id, kind=kind,
    )
```

Docstring hàm: thêm 1 câu "X-PG-Deployment/X-PG-Kind optional — phục vụ heartbeat, hỏng thì để None/rỗng chứ không từ chối."

- [ ] **Step 4: Chạy pass + regression**

Run: `.venv/bin/pytest tests/unit/gateway/ tests/unit/unified/test_ws_pg_credentials.py tests/unit/unified/test_chat_ws_auth.py -q`
Expected: PASS toàn bộ.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/gateway/chat_proxy.py src/noble_agent/server/ws_handler.py tests/unit/gateway/test_chat_proxy.py tests/unit/unified/test_ws_pg_credentials.py
git add src/noble_agent/gateway/chat_proxy.py src/noble_agent/server/ws_handler.py tests/unit/gateway/test_chat_proxy.py tests/unit/unified/test_ws_pg_credentials.py
git commit -m "feat: chat forward X-PG-Deployment/X-PG-Kind cho heartbeat per-tenant"
```

---

### Task 4: Wiring — gateway stash voice + worker ingest

**Files:**
- Modify: `src/noble_agent/gateway/server.py` (nhánh voice trong `_handle`, dòng ~162)
- Modify: `src/noble_agent/transport/livekit/worker.py` (trong `entrypoint`, ngay sau `set_current_tenant(job_tenant)` dòng ~242)
- Test: không có test mới bắt buộc — cả hai chỗ là wiring quanh `stash`/`fetch_and_register` đã test kỹ ở Task 2; hai hàm bao (`_stash_voice_credentials`) phải là try/except best-effort thuần wiring. Regression chạy suite gateway + một lần import worker module.

**Interfaces:**
- Consumes: `credential_stash.stash(redis, secret, tenant_id, *, role, password, deployment_id, kind, expires_at)`, `credential_stash.fetch_and_register(redis, secret, tenant_id)` (Task 2); `storage.redis_client.get_redis()` (sẵn có).
- Produces: không có — task cuối cùng của đường voice.

- [ ] **Step 1: Gateway — thêm helper module-level vào `server.py`** (cạnh `_bridge_voice`):

```python
async def _stash_voice_credentials(settings, tenant_id: str, credentials) -> None:
    """Đặt credential PG (mã hoá Fernet) vào Redis nội bộ TRƯỚC khi dispatch voice —
    worker job fetch lúc vào cuộc (storage/credential_stash.py). Best-effort: Redis
    lỗi / secret rỗng / credential thiếu role+password → bỏ qua, cuộc gọi VẪN chạy
    (worker rơi về shared DSN). Không secret nào đi qua LiveKit Cloud."""
    if credentials is None or not credentials.postgres_role or not credentials.postgres_password:
        return
    if not settings.gateway_worker_secret or credentials.expires_at is None:
        return
    try:
        from noble_agent.storage import credential_stash
        from noble_agent.storage.redis_client import get_redis

        redis = await get_redis()
        await credential_stash.stash(
            redis, settings.gateway_worker_secret, tenant_id,
            role=credentials.postgres_role, password=credentials.postgres_password,
            deployment_id=credentials.deployment_id, kind=credentials.kind,
            expires_at=credentials.expires_at,
        )
    except Exception:  # noqa: BLE001 — stash là best-effort, không được rớt cuộc gọi
        logger.warning("gateway: stash voice credential fail (tenant=%s) — voice dùng shared DSN", tenant_id)
```

Và trong `_handle`, nhánh voice (dòng ~162):

```python
    if mode == "voice":
        await _stash_voice_credentials(settings, result.tenant_id, result.credentials)
        await _bridge_voice(ws, settings, result.tenant_id, identity_json, call_id)
```

- [ ] **Step 2: Worker — trong `entrypoint`** (`transport/livekit/worker.py`), NGAY SAU `set_current_tenant(job_tenant)` (dòng ~242):

```python
    # Per-tenant PG credential: gateway stash vào Redis (mã hoá) trước khi dispatch —
    # ingest ở đây để pool_for_tenant dựng pool bằng chính role tenant. Best-effort:
    # không có stash / secret rỗng / giải mã fail → shared DSN như cũ.
    try:
        from noble_agent.storage.credential_stash import fetch_and_register
        from noble_agent.storage.redis_client import get_redis as _get_redis

        if settings.gateway_worker_secret:
            await fetch_and_register(await _get_redis(), settings.gateway_worker_secret, job_tenant)
    except Exception:  # noqa: BLE001 — credential là tăng cường, không được chặn cuộc gọi
        logger.warning("worker: ingest PG credential fail (tenant=%s) — dùng shared DSN", job_tenant)
```

(`settings` đã là module-level import trong worker.py — xem cách `settings.tenant_id` được dùng ngay dòng 241.)

- [ ] **Step 3: Verify import + regression**

Run: `.venv/bin/python -c "import noble_agent.transport.livekit.worker; import noble_agent.gateway.server; print('import OK')" && .venv/bin/pytest tests/unit/gateway/ tests/unit/storage/ -q`
Expected: import OK + PASS toàn bộ.

- [ ] **Step 4: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/gateway/server.py src/noble_agent/transport/livekit/worker.py
git add src/noble_agent/gateway/server.py src/noble_agent/transport/livekit/worker.py
git commit -m "feat(voice): gateway stash credential vào Redis, LiveKit job ingest lúc vào cuộc"
```

---

### Task 5: Heartbeat dùng credential (deployment_id + pool per-tenant)

**Files:**
- Modify: `src/noble_agent/tenant/pg_heartbeat.py` (`PgHeartbeatWriter.beat`, dòng 128-145)
- Test: `tests/unit/tenant/test_pg_heartbeat_writer.py` (giữ 2 test cũ, thêm 3)

**Interfaces:**
- Consumes: `tenant_credentials.get(tenant_id) -> TenantPgCredential | None` (có `deployment_id`/`kind` — Task 1); `postgres_client.pool_for_tenant(tenant_id)` (sẵn có).
- Produces: hành vi mới của `beat()` — chữ ký KHÔNG đổi.

- [ ] **Step 1: Thêm test fail** — append vào `tests/unit/tenant/test_pg_heartbeat_writer.py` (file có sẵn `_Conn`/`_Pool` fakes — tái dùng):

```python
from datetime import UTC, datetime, timedelta

from noble_agent.storage import tenant_credentials as tc


def _register_cred(kind="chat", deployment_id=99):
    tc.clear_for_tests()
    tc.register("t1", role="agent_t1", password="pw",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                deployment_id=deployment_id, kind=kind)


async def test_beat_uses_credential_deployment_and_tenant_pool(monkeypatch):
    """Có credential khớp kind → pool_for_tenant + dep từ credential, KHÔNG query control.deployments."""
    _register_cred(kind="chat", deployment_id=99)
    conn = _Conn()

    async def fake_pool_for_tenant(tid):
        assert tid == "t1"
        return _Pool(conn)

    monkeypatch.setattr("noble_agent.storage.postgres_client.pool_for_tenant", fake_pool_for_tenant)

    async def _dep(tid, kind, **kw):
        raise AssertionError("không được SELECT control.deployments khi có credential")

    async def _pc(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig

        return PublishedConfig(version=5, config={})

    w = PgHeartbeatWriter("chat", "1.0", read_deployment_id=_dep, read_published=_pc)
    assert await w.beat("t1") is True
    assert conn.upserts and conn.upserts[0][:3] == ("t1", 99, 5)
    tc.clear_for_tests()


async def test_beat_kind_mismatch_falls_back_to_legacy(monkeypatch):
    """Credential kind=chat nhưng writer kind=voice → đường cũ (read_deployment_id)."""
    _register_cred(kind="chat", deployment_id=99)
    conn = _Conn()
    called = {}

    async def _dep(tid, kind, **kw):
        called["dep"] = kind
        return 42

    async def _pc(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig

        return PublishedConfig(version=5, config={})

    w = PgHeartbeatWriter("voice", "1.0", pool=_Pool(conn), read_deployment_id=_dep, read_published=_pc)
    assert await w.beat("t1") is True
    assert called["dep"] == "voice"
    assert conn.upserts[0][:3] == ("t1", 42, 5)
    tc.clear_for_tests()


async def test_beat_no_credential_legacy_path_unchanged(monkeypatch):
    tc.clear_for_tests()
    conn = _Conn()

    async def _dep(tid, kind, **kw):
        return 42

    async def _pc(tid, **kw):
        return None

    w = PgHeartbeatWriter("chat", "1.0", pool=_Pool(conn), read_deployment_id=_dep, read_published=_pc)
    assert await w.beat("t1") is True
    assert conn.upserts[0][:3] == ("t1", 42, None)
```

- [ ] **Step 2: Chạy fail**

Run: `.venv/bin/pytest tests/unit/tenant/test_pg_heartbeat_writer.py -q`
Expected: `test_beat_uses_credential_deployment_and_tenant_pool` FAIL (beat vẫn gọi `_dep` → AssertionError); 2 test mới còn lại có thể pass sẵn.

- [ ] **Step 3: Implement** — thay thân `PgHeartbeatWriter.beat` (giữ nguyên try/except ngoài cùng):

```python
    async def beat(self, tenant_id: str) -> bool:
        """Emit heartbeat for tenant. False if skipped or error.

        Nguồn deployment_id + pool chọn theo credential per-tenant (nếu worker đã
        nhận từ gateway và kind khớp): dep lấy thẳng từ credential API — role
        agent_<tenant> KHÔNG có quyền SELECT control.deployments (least-privilege
        Portal) nên không query; pool là pool_for_tenant (role tenant, đã được
        GRANT INSERT control.agent_heartbeats + SELECT tenant_data.agent_config —
        verify live 2026-08-10). Không credential / lệch kind → đường shared cũ."""
        try:
            from noble_agent.storage import tenant_credentials

            cred = tenant_credentials.get(tenant_id)
            if cred is not None and cred.deployment_id is not None and cred.kind == self._kind:
                from noble_agent.storage.postgres_client import pool_for_tenant

                pool = await pool_for_tenant(tenant_id)
                dep = cred.deployment_id
            else:
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

Cập nhật docstring module (dòng 1-4): thêm "deployment_id ưu tiên lấy từ credential per-tenant (worker nhận từ gateway) — không cần SELECT control.deployments".

- [ ] **Step 4: Chạy pass + regression heartbeat**

Run: `.venv/bin/pytest tests/unit/tenant/ -q`
Expected: PASS toàn bộ (5 test writer + supervisor/job/wireup cũ).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenant/pg_heartbeat.py tests/unit/tenant/test_pg_heartbeat_writer.py
git add src/noble_agent/tenant/pg_heartbeat.py tests/unit/tenant/test_pg_heartbeat_writer.py
git commit -m "feat(heartbeat): dep từ credential API + pool per-tenant, bỏ SELECT control.deployments khi có credential"
```

---

### Task 6: Docs + full regression + hướng dẫn live verify

**Files:**
- Modify: `docs/CHANGELOG-agent.md` (entry mới ĐẦU bảng, 2026-08-10), `CLAUDE.md` (mục "Một agent dùng chung cho N tenant": sửa câu "voice giữ shared DSN" → voice nhận credential qua Redis stash; bảng Change Log: thêm row mới + xoá row cũ nhất giữ đúng 10), `docs/architecture/multi-tenant.md` (đoạn 2026-08-10: bỏ ghi chú "voice vẫn shared DSN — follow-up", tả cơ chế stash).
- LƯU Ý: `CLAUDE.md`/`docs/CHANGELOG-agent.md` có thể lại mang edit dở của user — nếu `git status` cho thấy dirty thì ghi rõ ride-along trong commit body như đợt trước.

**Interfaces:** không — task tổng hợp.

- [ ] **Step 1: Cập nhật 3 file docs** theo mô tả trên. Nội dung entry changelog (bản đầy đủ): gateway stash credential Fernet-encrypted vào Redis (`noble:pgcred:<tenant>`, TTL=expires_at) trước khi dispatch voice; LiveKit job `fetch_and_register` lúc vào cuộc → voice cũng chạy pool per-tenant; heartbeat lấy `deployment_id`+pool từ credential (role tenant bị chặn SELECT control.deployments), fallback đường shared cũ; chat forward thêm X-PG-Deployment/X-PG-Kind; khoá Fernet dẫn xuất GATEWAY_WORKER_SECRET — không env mới.

- [ ] **Step 2: Full regression**

Run: `.venv/bin/pytest tests/unit -q`
Expected: không fail MỚI so với baseline (~29-31 fail env-dependent pre-existing; đối chiếu TÊN test fail, không chỉ đếm).

- [ ] **Step 3: Ghi hướng dẫn live verify vào cuối message báo cáo** (không cần file): (a) restart gateway + worker (đọc lại code mới); (b) gọi voice qua gateway (smoke_gateway_voice.py hoặc provider thật) với key kind=voice; (c) tìm log job `credential_stash: đã đăng ký credential per-tenant` + `postgres: pool per-tenant connected`; (d) check row: `SELECT tenant_id, deployment_id, last_seen_at FROM control.agent_heartbeats` (qua check-script pattern với role tenant); (e) chat vẫn hoạt động như trước.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/CHANGELOG-agent.md docs/architecture/multi-tenant.md
git commit -m "docs: voice+heartbeat per-tenant credential — changelog + kiến trúc multi-tenant"
```

---

## Self-Review Notes (đã chạy)

- **Spec coverage:** §1 → Task 2; §2 → Task 4 (gateway); §3 → Task 4 (worker); §4 → Tasks 1+3; §5 → Task 5; §6 (không env mới, transports khác không đổi) → không task nào đụng; §7 error handling → phủ trong code Tasks 2/4/5; §8 testing → Tasks 1-5 + live verify Task 6. Không gap.
- **Type consistency:** `register(..., deployment_id: int | None = None, kind: str = "")` (T1) khớp T2 (`fetch_and_register`), T3 (ws_handler), T5 (heartbeat đọc `cred.deployment_id`/`cred.kind`). `stash(redis, secret, tenant_id, *, role, password, deployment_id, kind, expires_at)` (T2) khớp call T4. Chữ ký `_register_pg_credentials(headers, tenant_id, configured_secret)` giữ 3 tham số như hiện trạng.
- **Điểm linh hoạt khi thực thi:** helper/fixture thật của `test_chat_proxy.py` và `test_ws_pg_credentials.py` (T3 ghi "đọc file trước, khớp pattern"); vị trí dòng chính xác trong `worker.py`/`server.py` có thể lệch vài dòng so với plan.
