# NobleX App Integration — Phase 1 (Chat) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép NobleX backend provision một phiên agent (seed danh tính user vào Redis + mint connect-token) rồi để Flutter app nối thẳng WS `/chat` — với auth server-authoritative.

**Architecture:** Mô hình 2-chân. Chân control: `POST /api/v1/app/session` (server-to-server, header `X-Noble-App-Key`) derive `session_id` ổn định từ `noble_user_id`, seed `Customer` qua `StateRepo` trực tiếp (không dựng LLM runner), mint connect-token vào Redis, trả `{session_id, ws_url, connect_token}`. Chân stream: app mở WS `/chat?session=&token=` thẳng tới agent; handler verify token trước khi chạy. Logic provisioning nằm ở module mới `server/app_session.py` (giữ `http.py` mỏng, mirror `outbound_endpoints.py`).

**Tech Stack:** Python 3.11+, `websockets` (http11 Request/Response + asyncio server), pydantic-settings, redis.asyncio (StateRepo 3-key), pytest (asyncio_mode=auto), fakeredis.

## Global Constraints

- KHÔNG đụng agent core / RAG / LLM / audio pipeline / tool catalog / Luna prompt — chỉ server + storage model + config.
- Immutability: seed bằng cách tạo `Customer` mới rồi `save_all`, không mutate object cũ (theo `set_customer_fields` hiện có).
- Identity là server-authoritative — WS client KHÔNG được set danh tính; provisioning là nguồn duy nhất.
- `session_id` phải resumable: cùng `noble_user_id` → cùng `session_id` (deterministic).
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Format bằng `make format`.
- Commit conventional (`feat:`/`test:`/`docs:`), KHÔNG attribution trailer (rule global của user). Branch: `feat/app-integration` (đã tạo). KHÔNG push.
- Test async không cần `@pytest.mark.asyncio` (asyncio_mode=auto).
- fakeredis: `fakeredis.aioredis.FakeRedis()` (bytes mode) + `noble_agent.storage.redis_client.set_redis_for_tests(client)`; nhớ `close_redis()` teardown.

## File Structure

- **Create** `src/noble_agent/server/app_session.py` — toàn bộ logic provisioning: helper thuần (`_normalize_gender`, `_derive_session_id`, `_compose_noble_info`, `_token_key`), core async (`provision_session`, `verify_connect_token`), HTTP wrapper (`handle_app_session`). Một trách nhiệm: provisioning phiên app.
- **Modify** `src/noble_agent/config.py:569-570` — thêm 4 settings vào khối Sales API/thêm khối App API.
- **Modify** `src/noble_agent/storage/models.py:22-34` — `Customer` +`noble_user_id`.
- **Modify** `src/noble_agent/server/http.py:880` — route `POST /api/v1/app/session` trong `process_request`.
- **Modify** `src/noble_agent/server/ws_handler.py:89-91` — token gate cho `/chat`.
- **Modify** `.env.example`, `CLAUDE.md`, `docs/system-design/08-api-contracts-websocket-http.md` — docs + change log.
- **Create** `tests/unit/unified/test_app_session.py`, `tests/unit/unified/test_chat_ws_auth.py`.

---

### Task 1: Config settings cho App API

**Files:**
- Modify: `src/noble_agent/config.py:569-570` (khối `# ── Sales API ──`)
- Modify: `.env.example`
- Test: `tests/unit/unified/test_config.py`

**Interfaces:**
- Produces: `settings.noble_app_api_key: str`, `settings.chat_ws_require_token: bool`, `settings.app_connect_token_ttl_seconds: int`, `settings.app_ws_public_base: str`.

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/unit/unified/test_config.py`:

```python
def test_app_api_settings_defaults():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings()
    assert s.noble_app_api_key == ""
    assert s.chat_ws_require_token is False
    assert s.app_connect_token_ttl_seconds == 120
    assert s.app_ws_public_base == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_config.py::test_app_api_settings_defaults -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'noble_app_api_key'`

- [ ] **Step 3: Add the settings**

Trong `src/noble_agent/config.py`, ngay sau dòng `noble_sales_api_key: str = ""` (line 570) thêm khối:

```python

    # ── NobleX App integration (bubble chat/voice) ─────────────────────────────
    # Server-to-server key the NobleX backend uses to provision agent sessions.
    noble_app_api_key: str = ""
    # When true, WS /chat requires a valid connect-token (prod). False keeps the
    # local /chat tester (static/chat.html) working without provisioning.
    chat_ws_require_token: bool = False
    # TTL (seconds) of the short-lived connect-token minted at provisioning.
    app_connect_token_ttl_seconds: int = 120
    # Public wss base (e.g. wss://hotline-agent.noble.vn). Empty → ws_url is a
    # bare path and the backend composes the host.
    app_ws_public_base: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_config.py::test_app_api_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Document env vars**

Trong `.env.example`, thêm (gần khối `NOBLE_SALES_API_KEY` / `WS_PORT`):

```bash
# ── NobleX app integration (bubble chat/voice) ──────────────────────────────
# Server-to-server key backend NobleX dùng để provision phiên agent.
NOBLE_APP_API_KEY=
# Prod set true để WS /chat bắt buộc connect-token. Dev để trống/false cho chat tester.
CHAT_WS_REQUIRE_TOKEN=false
APP_CONNECT_TOKEN_TTL_SECONDS=120
# Public wss base, vd wss://hotline-agent.noble.vn (trống = trả path, backend tự ghép host).
APP_WS_PUBLIC_BASE=
```

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py .env.example tests/unit/unified/test_config.py
git commit -m "feat(config): add NobleX app-integration settings (app key, chat ws token gate)"
```

---

### Task 2: `Customer.noble_user_id`

**Files:**
- Modify: `src/noble_agent/storage/models.py:22-34`
- Test: `tests/unit/unified/test_state_models.py`

**Interfaces:**
- Produces: `Customer(noble_user_id: str | None = None)` — khóa định danh Noble ổn định.

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/unit/unified/test_state_models.py`:

```python
def test_customer_has_noble_user_id():
    from noble_agent.storage.models import Customer

    c = Customer(noble_user_id="6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb", name="Nga")
    assert c.noble_user_id == "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    # round-trips through JSON (StateRepo persists via model_dump_json)
    assert Customer.model_validate_json(c.model_dump_json()).noble_user_id == c.noble_user_id
    # default stays None (back-compat with existing persisted blobs)
    assert Customer().noble_user_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_state_models.py::test_customer_has_noble_user_id -v`
Expected: FAIL — `TypeError`/`ValidationError` (unexpected `noble_user_id`)

- [ ] **Step 3: Add the field**

Trong `src/noble_agent/storage/models.py`, class `Customer`, thêm dòng đầu tiên sau `class Customer(BaseModel):` docstring/fields — đặt ngay dưới dòng `name: str | None = None` (line 23):

```python
    noble_user_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_state_models.py::test_customer_has_noble_user_id -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/storage/models.py tests/unit/unified/test_state_models.py
git commit -m "feat(models): add Customer.noble_user_id (stable Noble identity key)"
```

---

### Task 3: `app_session.py` — helper thuần

**Files:**
- Create: `src/noble_agent/server/app_session.py`
- Test: `tests/unit/unified/test_app_session.py`

**Interfaces:**
- Produces:
  - `_normalize_gender(raw: object) -> str | None` — "Female"/"Nữ"/"F"→"F"; "Male"/"Nam"/"M"→"M"; else None.
  - `_derive_session_id(noble_user_id: str) -> str` — `"app-" + <12 hex đầu, bỏ '-', lower>`.
  - `_compose_noble_info(identity: dict) -> str | None` — gộp `noble_info`/`email`/`birthday`, `None` nếu rỗng.
  - `_token_key(session_id: str) -> str` — `f"session:{session_id}:connect_token"`.

- [ ] **Step 1: Write the failing test**

Tạo `tests/unit/unified/test_app_session.py`:

```python
from noble_agent.server import app_session as A


def test_normalize_gender():
    assert A._normalize_gender("Female") == "F"
    assert A._normalize_gender("Nữ") == "F"
    assert A._normalize_gender(" male ") == "M"
    assert A._normalize_gender("Nam") == "M"
    assert A._normalize_gender("") is None
    assert A._normalize_gender(None) is None
    assert A._normalize_gender("other") is None


def test_derive_session_id_stable_and_shaped():
    uid = "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    sid = A._derive_session_id(uid)
    assert sid == "app-6cb7cc1dd5d0"
    # deterministic → resumable
    assert A._derive_session_id(uid) == sid


def test_compose_noble_info():
    assert A._compose_noble_info({}) is None
    assert A._compose_noble_info({"noble_info": "VIP"}) == "VIP"
    out = A._compose_noble_info({"noble_info": "VIP", "email": "a@b.vn", "birthday": "25/02/1997"})
    assert "VIP" in out and "a@b.vn" in out and "25/02/1997" in out


def test_token_key():
    assert A._token_key("app-x") == "session:app-x:connect_token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_app_session.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.server.app_session`

- [ ] **Step 3: Create the module with helpers**

Tạo `src/noble_agent/server/app_session.py`:

```python
"""Provisioning cho phiên agent của NobleX app (Phase 1: chat).

Server-to-server: backend NobleX (sau khi xác thực user) POST danh tính user
vào đây. Ta derive một session_id ổn định, seed Customer state trong Redis (để
Luna biết đang nói với ai TRƯỚC lượt đầu), mint connect-token ngắn hạn, và trả
thứ app cần để mở WS /chat thẳng. Identity là server-authoritative — WS client
không tự set.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets

from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from noble_agent.config import settings
from noble_agent.storage.redis_client import get_redis
from noble_agent.storage.repo import StateRepo

logger = logging.getLogger("server")

_GENDER_MAP = {
    "m": "M", "male": "M", "nam": "M",
    "f": "F", "female": "F", "nữ": "F", "nu": "F",
}


def _normalize_gender(raw: object) -> str | None:
    if not raw:
        return None
    return _GENDER_MAP.get(str(raw).strip().lower())


def _derive_session_id(noble_user_id: str) -> str:
    """Stable, resumable session id — 12 hex, khớp shape session-id hiện có."""
    compact = noble_user_id.replace("-", "").lower()
    return "app-" + compact[:12]


def _compose_noble_info(identity: dict) -> str | None:
    """Gộp các field profile phụ Luna dùng được vào một chuỗi. None nếu rỗng."""
    parts: list[str] = []
    if identity.get("noble_info"):
        parts.append(str(identity["noble_info"]))
    if identity.get("email"):
        parts.append(f"email: {identity['email']}")
    if identity.get("birthday"):
        parts.append(f"sinh nhật: {identity['birthday']}")
    return " | ".join(parts) if parts else None


def _token_key(session_id: str) -> str:
    return f"session:{session_id}:connect_token"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_app_session.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py
git commit -m "feat(app-session): pure helpers (gender/session-id/noble-info/token-key)"
```

---

### Task 4: `provision_session` + `verify_connect_token`

**Files:**
- Modify: `src/noble_agent/server/app_session.py` (append)
- Test: `tests/unit/unified/test_app_session.py` (append)

**Interfaces:**
- Consumes: helpers từ Task 3; `StateRepo` (`load`/`save_all`); `Customer` (+`noble_user_id` từ Task 2); `settings.session_ttl_seconds`, `settings.app_connect_token_ttl_seconds`, `settings.app_ws_public_base`.
- Produces:
  - `async provision_session(body: dict) -> tuple[dict, int]` — `(payload, status)`. 400 nếu thiếu `noble_user_id`; 200 kèm `{session_id, channel, ws_url, connect_token, expires_in}`. Seed Customer vào Redis + mint token. Idempotent theo `noble_user_id` (merge, chỉ ghi field truthy).
  - `async verify_connect_token(session_id: str, token: str | None) -> bool` — so token với Redis (constant-time); False nếu thiếu/không khớp/redis lỗi.

- [ ] **Step 1: Write the failing test**

Append vào `tests/unit/unified/test_app_session.py`:

```python
import fakeredis.aioredis
import pytest

from noble_agent.storage.redis_client import close_redis, set_redis_for_tests


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis()
    set_redis_for_tests(client)
    yield client
    await close_redis()


async def test_provision_missing_user_id_returns_400(fake_redis):
    payload, status = await A.provision_session({"identity": {"full_name": "Nga"}})
    assert status == 400
    assert "noble_user_id" in payload["error"]


async def test_provision_seeds_customer_and_mints_token(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "app_connect_token_ttl_seconds", 120)
    monkeypatch.setattr(A.settings, "app_ws_public_base", "wss://agent.noble.vn")

    body = {
        "noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb",
        "channel": "chat",
        "identity": {
            "full_name": "Lê Viết Thúy Nga",
            "phone": "0378764303",
            "gender": "Female",
            "is_noble_customer": False,
            "noble_info": "VIP",
            "email": "ngalvt@noblex.vn",
        },
    }
    payload, status = await A.provision_session(body)
    assert status == 200
    assert payload["session_id"] == "app-6cb7cc1dd5d0"
    assert payload["connect_token"]
    assert payload["expires_in"] == 120
    assert payload["ws_url"] == (
        f"wss://agent.noble.vn/chat?session=app-6cb7cc1dd5d0&token={payload['connect_token']}"
    )

    # Customer seeded in Redis (same key the runner loads)
    from noble_agent.storage.repo import StateRepo

    repo = StateRepo(redis_client=fake_redis, ttl_seconds=86400)
    _meta, cust, _state = await repo.load("app-6cb7cc1dd5d0")
    assert cust.noble_user_id == "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    assert cust.full_name == "Lê Viết Thúy Nga"
    assert cust.name == "Lê Viết Thúy Nga"
    assert cust.phone == "0378764303"
    assert cust.gender == "F"
    assert cust.is_noble_customer is False
    assert "VIP" in cust.noble_info and "ngalvt@noblex.vn" in cust.noble_info

    # token stored, and verify accepts it / rejects a wrong one
    assert await A.verify_connect_token("app-6cb7cc1dd5d0", payload["connect_token"]) is True
    assert await A.verify_connect_token("app-6cb7cc1dd5d0", "nope") is False
    assert await A.verify_connect_token("app-6cb7cc1dd5d0", None) is False
    assert await A.verify_connect_token("unknown-sid", payload["connect_token"]) is False


async def test_provision_ws_url_is_path_when_no_base(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "app_ws_public_base", "")
    payload, status = await A.provision_session({"noble_user_id": "abc123def4567890"})
    assert status == 200
    assert payload["ws_url"].startswith("/chat?session=app-abc123def456&token=")


async def test_provision_idempotent_merges(fake_redis):
    uid = "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    await A.provision_session({"noble_user_id": uid, "identity": {"full_name": "Nga", "phone": "0378764303"}})
    # second call without phone must not blank the earlier phone
    await A.provision_session({"noble_user_id": uid, "identity": {"full_name": "Nga 2"}})

    from noble_agent.storage.repo import StateRepo

    repo = StateRepo(redis_client=fake_redis, ttl_seconds=86400)
    _m, cust, _s = await repo.load(A._derive_session_id(uid))
    assert cust.full_name == "Nga 2"
    assert cust.phone == "0378764303"  # preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_app_session.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'provision_session'`

- [ ] **Step 3: Append core logic**

Append vào `src/noble_agent/server/app_session.py`:

```python
async def provision_session(body: dict) -> tuple[dict, int]:
    """Core provisioning (transport-agnostic, testable). Returns (payload, status)."""
    noble_user_id = str(body.get("noble_user_id") or "").strip()
    if not noble_user_id:
        return {"error": "noble_user_id required"}, 400

    channel = body.get("channel") or "chat"
    identity = body.get("identity") or {}
    session_id = _derive_session_id(noble_user_id)

    # Build the seed field set (only truthy values overwrite).
    fields: dict = {"noble_user_id": noble_user_id}
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

    # Seed via StateRepo directly (no LLM runner needed) — same 3 keys the turn
    # loop reads. Merge onto existing customer so re-provision doesn't blank
    # fields (mirrors facade.set_customer_fields semantics).
    from noble_agent.storage.models import Customer

    redis = await get_redis()
    repo = StateRepo(redis_client=redis, ttl_seconds=settings.session_ttl_seconds)
    meta, customer, state = await repo.load(session_id)
    merged = customer.model_dump()
    for key, value in fields.items():
        if isinstance(value, bool) or value:
            merged[key] = value
    new_customer = Customer.model_validate(merged)
    await repo.save_all(session_id, meta, new_customer, state)

    # Mint a short-lived connect-token for the direct WS handshake.
    token = secrets.token_urlsafe(24)
    ttl = settings.app_connect_token_ttl_seconds
    await redis.set(_token_key(session_id), token, ex=ttl)

    base = (settings.app_ws_public_base or "").rstrip("/")
    ws_path = f"/chat?session={session_id}&token={token}"
    ws_url = f"{base}{ws_path}" if base else ws_path

    return (
        {
            "session_id": session_id,
            "channel": channel,
            "ws_url": ws_url,
            "connect_token": token,
            "expires_in": ttl,
        },
        200,
    )


async def verify_connect_token(session_id: str, token: str | None) -> bool:
    """True iff `token` matches the stored connect-token for `session_id`."""
    if not token:
        return False
    try:
        redis = await get_redis()
        stored = await redis.get(_token_key(session_id))
    except Exception:
        logger.warning("verify_connect_token: redis error", exc_info=True)
        return False
    if not stored:
        return False
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8")
    return hmac.compare_digest(stored, token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_app_session.py -v`
Expected: PASS (toàn bộ, gồm 4 helper + 4 provisioning)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py
git commit -m "feat(app-session): provision_session (seed Customer + mint token) + verify_connect_token"
```

---

### Task 5: HTTP wrapper `handle_app_session` + route

**Files:**
- Modify: `src/noble_agent/server/app_session.py` (append `_json`, `handle_app_session`)
- Modify: `src/noble_agent/server/http.py:880` (route trong `process_request`)
- Test: `tests/unit/unified/test_app_session.py` (append)

**Interfaces:**
- Consumes: `provision_session` (Task 4); `settings.noble_app_api_key`; `websockets.http11.Request`/`Response`.
- Produces: `async handle_app_session(request: Request) -> Response` — 405 (không phải POST), 503 (chưa cấu hình key), 401 (sai key), rồi delegate `provision_session`. Route: `POST /api/v1/app/session`.

- [ ] **Step 1: Write the failing test**

Append vào `tests/unit/unified/test_app_session.py`:

```python
import json as _json_mod


class _FakeReq:
    def __init__(self, method="POST", headers=None, body=b""):
        self.method = method
        self.headers = headers or {}
        self.body = body


async def test_handle_app_session_disabled_when_no_key(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "")
    resp = await A.handle_app_session(_FakeReq(headers={"X-Noble-App-Key": "x"}))
    assert resp.status_code == 503


async def test_handle_app_session_rejects_bad_key(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "secret")
    resp = await A.handle_app_session(_FakeReq(headers={"X-Noble-App-Key": "wrong"}))
    assert resp.status_code == 401


async def test_handle_app_session_rejects_non_post(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "secret")
    resp = await A.handle_app_session(_FakeReq(method="GET", headers={"X-Noble-App-Key": "secret"}))
    assert resp.status_code == 405


async def test_handle_app_session_happy_path(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "noble_app_api_key", "secret")
    body = _json_mod.dumps({"noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"}).encode()
    resp = await A.handle_app_session(_FakeReq(headers={"X-Noble-App-Key": "secret"}, body=body))
    assert resp.status_code == 200
    data = _json_mod.loads(resp.body)
    assert data["session_id"] == "app-6cb7cc1dd5d0"
    assert data["connect_token"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_app_session.py -k handle_app_session -v`
Expected: FAIL — `AttributeError: ... 'handle_app_session'`

- [ ] **Step 3: Append the HTTP wrapper**

Append vào `src/noble_agent/server/app_session.py`:

```python
def _json(data: dict, status: int) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return Response(status, "OK" if status < 400 else "Error", headers, body)


async def handle_app_session(request: Request) -> Response:
    """POST /api/v1/app/session — server-to-server, header X-Noble-App-Key."""
    method = getattr(request, "method", "GET").upper()
    if method != "POST":
        return _json({"error": "method_not_allowed"}, 405)
    if not settings.noble_app_api_key:
        return _json({"error": "app_api_disabled", "message": "Set NOBLE_APP_API_KEY to enable."}, 503)
    auth = request.headers.get("X-Noble-App-Key") or request.headers.get("x-noble-app-key", "")
    if not auth or not hmac.compare_digest(auth, settings.noble_app_api_key):
        return _json({"error": "unauthorized"}, 401)

    raw = getattr(request, "body", None) or b""
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    try:
        body = json.loads(raw) if raw else {}
    except Exception:
        body = {}

    payload, status = await provision_session(body)
    return _json(payload, status)
```

- [ ] **Step 4: Wire the route in http.py**

Trong `src/noble_agent/server/http.py`, trong `process_request`, ngay TRƯỚC khối `if path.startswith("/api/v1/sales/"):` (line ~880) thêm:

```python
    # ── API: NobleX app session provisioning (server-to-server) ──────────
    # POST /api/v1/app/session — backend seeds identity + gets a connect-token.
    if path == "/api/v1/app/session":
        from noble_agent.server.app_session import handle_app_session

        return await handle_app_session(request)

```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/unit/unified/test_app_session.py -v`
Expected: PASS (toàn bộ file)

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/server/app_session.py src/noble_agent/server/http.py tests/unit/unified/test_app_session.py
git commit -m "feat(server): POST /api/v1/app/session provisioning endpoint (X-Noble-App-Key)"
```

---

### Task 6: Token gate cho WS `/chat`

**Files:**
- Modify: `src/noble_agent/server/ws_handler.py:87-91`
- Test: `tests/unit/unified/test_chat_ws_auth.py`

**Interfaces:**
- Consumes: `verify_connect_token` (Task 4); `settings.chat_ws_require_token`.
- Produces: khi `chat_ws_require_token=True`, WS `/chat` không có token hợp lệ → `ws.close(4401, "unauthorized")` và KHÔNG chạy `handle_text_session`.

- [ ] **Step 1: Write the failing test**

Tạo `tests/unit/unified/test_chat_ws_auth.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from noble_agent.server import ws_handler
from noble_agent.storage.redis_client import close_redis, set_redis_for_tests


class _FakeWS:
    """Minimal ServerConnection double for _handle_session."""

    def __init__(self, path):
        self.request = MagicMock()
        self.request.path = path
        self.remote_address = ("127.0.0.1", 1234)
        self.close = AsyncMock()
        self.send = AsyncMock()

    def __aiter__(self):
        async def _gen():
            return
            yield  # pragma: no cover

        return _gen()


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis()
    set_redis_for_tests(client)
    yield client
    await close_redis()


async def test_chat_ws_closed_when_token_required_and_missing(fake_redis, monkeypatch):
    monkeypatch.setattr(ws_handler.settings, "chat_ws_require_token", True)
    called = False

    async def _fake_handle(ws, sid):
        nonlocal called
        called = True

    from noble_agent.server import text_chat

    monkeypatch.setattr(text_chat, "handle_text_session", _fake_handle)

    ws = _FakeWS("/chat?session=app-xyz")  # no token
    await ws_handler._handle_session(ws, "127.0.0.1")

    ws.close.assert_awaited_once()
    assert ws.close.call_args.args[0] == 4401
    assert called is False


async def test_chat_ws_allows_valid_token(fake_redis, monkeypatch):
    monkeypatch.setattr(ws_handler.settings, "chat_ws_require_token", True)
    await fake_redis.set("session:app-xyz:connect_token", "good")
    seen = {}

    async def _fake_handle(ws, sid):
        seen["sid"] = sid

    from noble_agent.server import text_chat

    monkeypatch.setattr(text_chat, "handle_text_session", _fake_handle)

    ws = _FakeWS("/chat?session=app-xyz&token=good")
    await ws_handler._handle_session(ws, "127.0.0.1")

    ws.close.assert_not_awaited()
    assert seen["sid"] == "app-xyz"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_chat_ws_auth.py -v`
Expected: FAIL — `test_...missing` fails (close not called; `handle_text_session` runs) vì chưa có gate.

- [ ] **Step 3: Add the gate**

Trong `src/noble_agent/server/ws_handler.py`, thay khối (lines 89-91):

```python
    if text_chat.is_chat_path(raw_path):
        await text_chat.handle_text_session(ws, session_id)
        return
```

bằng:

```python
    if text_chat.is_chat_path(raw_path):
        if settings.chat_ws_require_token:
            from noble_agent.server.app_session import verify_connect_token

            token = qs.get("token", [None])[0]
            if not await verify_connect_token(session_id, token):
                logger.warning("[CHAT] unauthorized connect rejected (session=%s ip=%s)", session_id, client_ip)
                await ws.close(4401, "unauthorized")
                return
        await text_chat.handle_text_session(ws, session_id)
        return
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/unified/test_chat_ws_auth.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/ws_handler.py tests/unit/unified/test_chat_ws_auth.py
git commit -m "feat(server): gate WS /chat on connect-token when CHAT_WS_REQUIRE_TOKEN"
```

---

### Task 7: Docs, CLAUDE.md, smoke

**Files:**
- Modify: `CLAUDE.md` (Change Log + Layout/route note)
- Modify: `docs/system-design/08-api-contracts-websocket-http.md` (thêm endpoint + WS token)
- Verify: `src/noble_agent/SMOKE.md` (chạy checklist)

**Interfaces:** none (docs only).

- [ ] **Step 1: Full test suite + lint**

Run:
```bash
make test-unit
make lint
```
Expected: green (các test mới pass; ruff sạch). Nếu ruff báo import/format → `make format` rồi chạy lại.

- [ ] **Step 2: Document the endpoint contract**

Trong `docs/system-design/08-api-contracts-websocket-http.md`, mục "HTTP REST", thêm section:

```markdown
### 2.x Routes — NobleX app session (server-to-server)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/app/session` | `X-Noble-App-Key` | Backend NobleX provision phiên: seed identity + mint connect-token |

Body:
​```json
{"noble_user_id":"<uuid>","channel":"chat","identity":{"full_name":"...","phone":"...","gender":"Female","is_noble_customer":false,"noble_info":"...","email":"...","birthday":"..."}}
​```
Response: `{"session_id","channel","ws_url","connect_token","expires_in"}`.

WS `/chat` chỉ chấp nhận `?token=<connect_token>` khi `CHAT_WS_REQUIRE_TOKEN=true` (prod); sai/thiếu → close `4401`. Identity là server-authoritative (client không gửi `set_customer`).
```

- [ ] **Step 3: Update CLAUDE.md**

Thêm dòng vào bảng Change Log (đầu bảng, dưới header) trong `CLAUDE.md`:

```markdown
| 2026-07-09 | **NobleX app integration Phase 1 (chat): provisioning endpoint + WS token gate.** New `server/app_session.py` (`provision_session`/`verify_connect_token`/`handle_app_session`): `POST /api/v1/app/session` (auth `X-Noble-App-Key`) derive `session_id` ổn định từ `noble_user_id`, seed `Customer` (+`noble_user_id`) qua StateRepo trực tiếp, mint connect-token Redis (`session:{sid}:connect_token`, TTL `APP_CONNECT_TOKEN_TTL_SECONDS=120`), trả `{session_id, ws_url, connect_token, expires_in}`. WS `/chat` gate token khi `CHAT_WS_REQUIRE_TOKEN=true` (default false → chat tester dev không đổi). Model `Customer` +`noble_user_id`. New settings `NOBLE_APP_API_KEY`/`CHAT_WS_REQUIRE_TOKEN`/`APP_CONNECT_TOKEN_TTL_SECONDS`/`APP_WS_PUBLIC_BASE`. Identity server-authoritative (client không set). Spec `docs/superpowers/specs/2026-07-09-noblex-app-agent-integration-design.md`. Branch `feat/app-integration`. | Nhúng Luna vào NobleX mobile app (bubble chat/voice), mô hình 2-chân: backend provision + seed, app nối WS thẳng. |
```

Và trong bảng Layout (`server/` row) hoặc mục backends, thêm ghi chú ngắn: `server/app_session.py` — provisioning phiên cho NobleX app (chat).

- [ ] **Step 4: Run smoke checklist**

Đọc `src/noble_agent/SMOKE.md` và chạy các mục chạm transport boundary / WS `/chat`. Với `CHAT_WS_REQUIRE_TOKEN=false` (mặc định), chat tester `/chat` phải hoạt động y như trước (regression). Thử `POST /api/v1/app/session` với `NOBLE_APP_API_KEY` set → nhận `{session_id, ws_url, connect_token}`; mở WS `/chat?session=&token=` với `CHAT_WS_REQUIRE_TOKEN=true` → chat được; token sai → đóng 4401.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/system-design/08-api-contracts-websocket-http.md
git commit -m "docs: document app-session endpoint + WS token gate; CLAUDE.md change log"
```

---

## Phase 2 (Voice, LiveKit) — KHÔNG trong plan này

Ghi lại để không quên (sẽ là plan riêng): `provision_session(channel="voice")` mint thêm LiveKit token (`room = session_id`) → worker tự load Customer đã seed (không sửa worker). Khoá `GET /livekit/token` public. Hạ tầng: `LIVEKIT_PUBLIC_URL` + TURN. Flutter `livekit_client` join room. Phụ thuộc Phase 1 (endpoint + model + settings) đã có.

## Client-side (ngoài repo) — hợp đồng để backend + Flutter team làm

- **Backend NobleX:** khi user bấm bubble → xác thực user → gọi `POST {agent}/api/v1/app/session` với `X-Noble-App-Key` + `{noble_user_id, channel:"chat", identity:{...}}` (identity lấy từ `GetProfileInfo`, gender để nguyên "Female"/"Male"/"Nữ"/"Nam" — agent tự map) → trả `ws_url`(+token) cho app.
- **Flutter:** mở WS `ws_url`, gửi `{"type":"user_text","text":...,"tts":false}`, render stream `token`/`tool_start`/`tool_done`/`done`; `reset` để làm mới. KHÔNG gửi `set_customer` (identity đã seed server-side).

## Self-Review

- **Spec coverage:** provisioning endpoint (T5) · seed identity + gender map + noble_info fold (T3/T4) · `noble_user_id` model (T2) · WS auth gate (T6) · settings (T1) · session_id resumable deterministic (T3/T4) · idempotent re-provision (T4) · docs/CLAUDE.md/API contract (T7). Escalate/handoff = không đổi (spec ghi rõ). Phase 2 + client-side = out-of-scope, đã liệt kê. ✔ mọi requirement Phase 1 có task.
- **Placeholder scan:** không có TBD/"handle errors"/pseudo — mọi step có code/lệnh + expected.
- **Type consistency:** `_derive_session_id`→`"app-6cb7cc1dd5d0"` dùng đồng nhất ở T3/T4/T6 test; `provision_session`→`(dict,int)` khớp ở T4/T5; `verify_connect_token(session_id, token)` khớp T4/T6; `_token_key`→`session:{sid}:connect_token` đồng nhất T3/T4/T6; settings names đồng nhất T1↔T3/T4/T6.
