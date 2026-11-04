# Shared-worker routing (gateway ↔ agent) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make gateway↔agent routing work for ONE shared process serving N tenants — remove the per-tenant `agent-<tenant>` assumption from LiveKit dispatch + chat DNS; carry the tenant in the request (voice: participant metadata; chat: `X-Tenant-Id` header) and enforce the `X-Gateway-Secret` hop.

**Architecture:** A single shared LiveKit agent-dispatch name (`settings.livekit_agent_name`) that one worker pool registers under; the gateway injects `tenant_id` into voice participant metadata (the worker already resolves tenant from metadata via `_job_tenant`). The chat proxy targets a shared worker URL and passes tenant via `X-Tenant-Id`; the worker's `/chat` reads it into `handle_text_session(tenant_id=)` and enforces `X-Gateway-Secret` when configured.

**Tech Stack:** Python 3.11+, `livekit.api` (hard dep), `websockets`, pydantic-settings (`UnifiedSettings`), pytest (`asyncio_mode=auto`).

## Global Constraints

- **Shared dispatch name = `settings.livekit_agent_name`** (default `"noble-hotline-agent"`), used by ALL THREE mint/register sites (gateway `build_dispatch_token`, `server/app_session.py` mint, `transport/livekit/worker.py` registration). No name derived from `tenant_id` anymore.
- **Voice: `tenant_id` MUST be in the participant metadata JSON** (merged into `identity_json` by `build_dispatch_token`) — this is how the shared worker resolves the tenant now that the dispatch name doesn't carry it.
- **Chat: tenant via `X-Tenant-Id` header**; the worker chat URL template has NO `{tenant_id}` placeholder.
- **Enforce `X-Gateway-Secret` ONLY when `settings.gateway_worker_secret` is non-empty** (empty → skip, dev/trust-network unchanged); mismatch/missing → `ws.close(4403, "gateway_secret_mismatch")`; compare with `hmac.compare_digest`.
- **Single-tenant / direct paths unchanged (byte-identical):** a `/chat` connection with no `X-Tenant-Id` → `tenant_id=None` → `handle_text_session` falls back to `settings.tenant_id`; a voice job with no `tenant_id` in metadata → `_job_tenant` falls back to `settings.tenant_id`; `gateway_worker_secret` empty → no enforcement.
- **Surgical / additive:** do NOT touch RAG backends, `send_media`, `kb_search`, or unrelated code. ruff line-length 120, rules `E,F,W,I,UP,B,SIM`. Tests offline (no live LiveKit / MinIO / network).
- Spec of record: `docs/superpowers/specs/2026-08-03-shared-worker-routing-design.md`.

---

### Task 1: Gateway voice — shared `agent_name` param + tenant in metadata

**Files:**
- Modify: `src/noble_agent/gateway/livekit_bridge.py` (rewrite `build_dispatch_token`, drop `agent_dispatch_name` import)
- Modify: `src/noble_agent/gateway/server.py:122-129` (`_bridge_voice` passes `agent_name=settings.livekit_agent_name`)
- Test: `tests/unit/gateway/test_livekit_bridge.py`

**Interfaces:**
- Consumes: `settings.livekit_agent_name`.
- Produces: `build_dispatch_token(tenant_id, identity_json, *, api_key, api_secret, url, agent_name, call_id="call", minter=None) -> (jwt, url, room)` — RoomAgentDispatch uses `agent_name`; participant metadata = `identity_json` merged with `{"tenant_id": tenant_id}`.

- [ ] **Step 1: Update the failing test**

Replace `test_build_dispatch_token_uses_tenant_agent_and_metadata` in `tests/unit/gateway/test_livekit_bridge.py` with the two below (keep `test_room_name_scoped_and_unique` and the `FakeToken` class as-is):

```python
def test_build_dispatch_token_shared_agent_and_tenant_metadata():
    """Dispatch uses the shared agent_name; metadata carries tenant_id merged into identity."""
    import json

    tok = FakeToken()
    jwt, url, room = b.build_dispatch_token(
        "t1",
        '{"name":"An"}',
        api_key="k",
        api_secret="s",
        url="wss://lk",
        agent_name="noble-hotline-agent",
        minter=lambda *a, **k: tok,
    )
    assert jwt == "JWT" and url == "wss://lk" and room.startswith("t1-")
    kinds = dict(tok.calls)
    meta = json.loads(kinds["metadata"])
    assert meta["tenant_id"] == "t1"
    assert meta["name"] == "An"
    assert kinds["room_config"].agents[0].agent_name == "noble-hotline-agent"


def test_build_dispatch_token_empty_identity_still_carries_tenant():
    import json

    tok = FakeToken()
    b.build_dispatch_token(
        "t2", "", api_key="k", api_secret="s", url="u", agent_name="A", minter=lambda *a, **k: tok
    )
    assert json.loads(dict(tok.calls)["metadata"]) == {"tenant_id": "t2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_livekit_bridge.py -v`
Expected: FAIL (`build_dispatch_token` has no `agent_name` kwarg; metadata is the raw identity string without `tenant_id`).

- [ ] **Step 3: Rewrite `build_dispatch_token`**

Replace the body of `src/noble_agent/gateway/livekit_bridge.py` (remove `from noble_agent.tenant.naming import agent_dispatch_name`; keep `room_name` + `_ROOM_EMPTY_TIMEOUT_S`):

```python
def build_dispatch_token(
    tenant_id: str,
    identity_json: str,
    *,
    api_key: str,
    api_secret: str,
    url: str,
    agent_name: str,
    call_id: str = "call",
    minter=None,
) -> tuple[str, str, str]:
    """Mint a LiveKit room-join token that dispatches the SHARED worker
    (`agent_name`, tenant-independent) and carries the caller identity PLUS
    `tenant_id` as participant metadata — the worker resolves its per-job tenant
    from that metadata. Returns (jwt, url, room)."""
    import json

    from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

    minter = minter or AccessToken
    room = room_name(tenant_id, call_id)
    identity = f"caller-{room}"
    try:
        meta = json.loads(identity_json) if identity_json else {}
        if not isinstance(meta, dict):
            meta = {}
    except (ValueError, TypeError):
        meta = {}
    meta["tenant_id"] = tenant_id
    metadata_json = json.dumps(meta, ensure_ascii=False)
    token = (
        minter(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_metadata(metadata_json)
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(
            RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=agent_name)],
                empty_timeout=_ROOM_EMPTY_TIMEOUT_S,
            )
        )
        .to_jwt()
    )
    return token, url, room
```

- [ ] **Step 4: Pass `agent_name` from the gateway voice bridge**

In `src/noble_agent/gateway/server.py` `_bridge_voice`, add `agent_name=settings.livekit_agent_name` to the `build_dispatch_token(...)` call (lines 122-129):

```python
    jwt, url, room = build_dispatch_token(
        tenant_id,
        identity_json,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        url=settings.livekit_url,
        agent_name=settings.livekit_agent_name,
        call_id=call_id,
    )
```

- [ ] **Step 5: Run test + lint**

Run: `pytest tests/unit/gateway/test_livekit_bridge.py -v` → PASS (3 tests).
Run: `ruff check src/noble_agent/gateway/livekit_bridge.py src/noble_agent/gateway/server.py tests/unit/gateway/test_livekit_bridge.py` → clean.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/gateway/livekit_bridge.py src/noble_agent/gateway/server.py tests/unit/gateway/test_livekit_bridge.py
git commit -m "feat(gateway): voice dispatch uses shared agent_name + tenant in metadata"
```

---

### Task 2: Worker + app_session use the shared dispatch name; delete `agent_dispatch_name`

**Files:**
- Modify: `src/noble_agent/transport/livekit/worker.py:19,322`
- Modify: `src/noble_agent/server/app_session.py:24,241`
- Delete: `src/noble_agent/tenant/naming.py`, `tests/unit/tenant/test_naming.py`
- Modify: `src/noble_agent/config.py:707-710` (comment), `src/noble_agent/SMOKE.md:73`
- Test: `tests/unit/unified/test_app_session.py`, `tests/unit/unified/test_livekit_token_endpoint.py`

**Interfaces:**
- Consumes: `settings.livekit_agent_name` (Task 1 constraint). After this task `noble_agent.tenant.naming` no longer exists.
- Produces: worker registers `agent_name=settings.livekit_agent_name`; app_session mint uses `RoomAgentDispatch(agent_name=settings.livekit_agent_name)`.

- [ ] **Step 1: Update the failing tests**

In `tests/unit/unified/test_app_session.py`: remove the `from noble_agent.tenant.naming import agent_dispatch_name` import (line 9). Replace every `agent_dispatch_name("noble")` / `agent_dispatch_name("acme-corp")` occurrence (lines ~177, 222, 255) with `A.settings.livekit_agent_name`. Rewrite the docstring/comment at 174-176 and rename `test_mint_livekit_token_dispatch_name_matches_agent_dispatch_name` → `test_mint_livekit_token_uses_shared_dispatch_name` with body asserting the shared name regardless of tenant:

```python
def test_mint_livekit_token_uses_shared_dispatch_name(monkeypatch):
    """All three sites (worker registration, this app mint, gateway build_dispatch_token)
    use the SHARED settings.livekit_agent_name — NOT a tenant-derived name — so one
    worker pool serves every tenant. Setting a different tenant_id must NOT change it."""
    _lk_settings(monkeypatch)
    monkeypatch.setattr(A.settings, "tenant_id", "acme-corp")
    tok = _FakeToken()
    monkeypatch.setattr("livekit.api.AccessToken", lambda *a, **k: tok)
    A._mint_livekit_token("app-x", "user-app-x", "user-app-x")
    room_config = dict(tok.calls)["room_config"]
    assert room_config.agents[0].agent_name == A.settings.livekit_agent_name
```

In `tests/unit/unified/test_livekit_token_endpoint.py`: remove the `agent_dispatch_name` import (line 6), add `from noble_agent.config import settings`, and change line 42 assertion to `== settings.livekit_agent_name`.

Delete `tests/unit/tenant/test_naming.py` (`git rm`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_app_session.py tests/unit/unified/test_livekit_token_endpoint.py -v`
Expected: FAIL (source still emits `agent-<tenant>` via `agent_dispatch_name`).

- [ ] **Step 3: Point the source at the shared name + delete the helper**

- `src/noble_agent/transport/livekit/worker.py`: delete the import line 19 (`from noble_agent.tenant.naming import agent_dispatch_name`); change line 322 to `agent_name=settings.livekit_agent_name,`.
- `src/noble_agent/server/app_session.py`: delete the import line 24; change line 241 to `agents=[RoomAgentDispatch(agent_name=settings.livekit_agent_name)],`.
- `git rm src/noble_agent/tenant/naming.py`.
- `src/noble_agent/config.py`: update the comment block above `livekit_agent_name` (lines ~707-709) to:

```python
    # Single SHARED LiveKit agent-dispatch name. One worker pool registers under
    # this name and serves EVERY tenant; the per-job tenant is resolved from the
    # caller's participant metadata (gateway-injected), NOT from the dispatch name.
    # Used identically by worker registration, app_session mint, and the gateway.
    livekit_agent_name: str = "noble-hotline-agent"
```

- `src/noble_agent/SMOKE.md` line 73: change `# - Agent dispatched as agent-t1 (agent_dispatch_name)` to `# - Agent dispatched via the shared livekit_agent_name; tenant carried in participant metadata`.

- [ ] **Step 4: Run tests + confirm no stale references**

Run: `pytest tests/unit/unified/test_app_session.py tests/unit/unified/test_livekit_token_endpoint.py -v` → PASS.
Run: `grep -rn "agent_dispatch_name\|tenant.naming\|tenant import naming" src/noble_agent tests` → **no matches** (helper fully removed).
Run: `ruff check src/noble_agent/transport/livekit/worker.py src/noble_agent/server/app_session.py src/noble_agent/config.py tests/unit/unified/test_app_session.py tests/unit/unified/test_livekit_token_endpoint.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(voice): worker + app_session register the shared dispatch name; drop agent_dispatch_name"
```

---

### Task 3: Chat proxy → shared worker URL + `X-Tenant-Id` header

**Files:**
- Modify: `src/noble_agent/gateway/chat_proxy.py` (`worker_chat_url` returns fixed URL; new `proxy_headers`; `proxy_chat` sends `X-Tenant-Id`)
- Modify: `src/noble_agent/config.py:109-111` (`worker_chat_internal_url_template` default → no placeholder)
- Test: `tests/unit/gateway/test_chat_proxy.py`

**Interfaces:**
- Consumes: `settings.worker_chat_internal_url_template`, `settings.gateway_worker_secret`.
- Produces: `worker_chat_url(tenant_id, settings) -> str` (returns the template verbatim); `proxy_headers(settings, tenant_id) -> dict` (always includes `X-Tenant-Id`, plus `X-Gateway-Secret` when the secret is set).

- [ ] **Step 1: Update/add the failing tests**

In `tests/unit/gateway/test_chat_proxy.py`, replace `test_worker_chat_url` and add header tests (keep `first_messages` tests):

```python
from types import SimpleNamespace

from noble_agent.gateway.chat_proxy import first_messages, proxy_headers, worker_chat_url


def test_worker_chat_url_is_fixed_shared_url():
    s = SimpleNamespace(worker_chat_internal_url_template="ws://agent:8766/chat")
    assert worker_chat_url("t1", s) == "ws://agent:8766/chat"
    assert worker_chat_url("t2", s) == "ws://agent:8766/chat"


def test_proxy_headers_include_tenant():
    s = SimpleNamespace(gateway_worker_secret="")
    assert proxy_headers(s, "t1") == {"X-Tenant-Id": "t1"}


def test_proxy_headers_include_secret_when_set():
    s = SimpleNamespace(gateway_worker_secret="shh")
    assert proxy_headers(s, "t1") == {"X-Tenant-Id": "t1", "X-Gateway-Secret": "shh"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/gateway/test_chat_proxy.py -v`
Expected: FAIL (`proxy_headers` does not exist; `worker_chat_url` still `.format`s a `{tenant_id}` template).

- [ ] **Step 3: Implement**

In `src/noble_agent/gateway/chat_proxy.py`:
- Change `worker_chat_url` to return the template verbatim (no `.format`):

```python
def worker_chat_url(tenant_id: str, settings) -> str:
    """The shared worker chat WebSocket URL (tenant travels in the X-Tenant-Id
    header now, not the DNS). `tenant_id` kept for call-site compatibility."""
    return settings.worker_chat_internal_url_template
```

- Add `proxy_headers`:

```python
def proxy_headers(settings, tenant_id: str) -> dict:
    """Headers the gateway sends to the worker /chat: always the tenant, plus the
    shared-secret when configured."""
    headers = {"X-Tenant-Id": tenant_id}
    if settings.gateway_worker_secret:
        headers["X-Gateway-Secret"] = settings.gateway_worker_secret
    return headers
```

- In `proxy_chat`, replace the inline header build (the `headers = {}` / `if settings.gateway_worker_secret:` block) with `headers = proxy_headers(settings, tenant_id)`.

In `src/noble_agent/config.py`, change the `worker_chat_internal_url_template` default (lines 109-111):

```python
    worker_chat_internal_url_template: str = Field(
        "ws://agent:8766/chat", alias="WORKER_CHAT_INTERNAL_URL_TEMPLATE"
    )
```

- [ ] **Step 4: Run test + lint**

Run: `pytest tests/unit/gateway/test_chat_proxy.py -v` → PASS.
Run: `ruff check src/noble_agent/gateway/chat_proxy.py src/noble_agent/config.py tests/unit/gateway/test_chat_proxy.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/gateway/chat_proxy.py src/noble_agent/config.py tests/unit/gateway/test_chat_proxy.py
git commit -m "feat(gateway): chat proxy targets shared worker + sends X-Tenant-Id"
```

---

### Task 4: Worker `/chat` — read `X-Tenant-Id` + enforce `X-Gateway-Secret`

**Files:**
- Modify: `src/noble_agent/server/ws_handler.py` (add `_tenant_from_headers` + `_gateway_secret_ok`; wire into the chat branch at lines 89-99)
- Test: `tests/unit/unified/test_ws_handler_chat_headers.py`
- Then: full gate (`make test-unit`)

**Interfaces:**
- Consumes: `settings.gateway_worker_secret`; `text_chat.handle_text_session(ws, session_id, *, tenant_id=None)`.
- Produces: `_tenant_from_headers(headers) -> str | None`; `_gateway_secret_ok(configured_secret: str, headers) -> bool`. Chat branch closes `4403` on secret mismatch and passes the header tenant into `handle_text_session`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_ws_handler_chat_headers.py
"""Pure header helpers for the /chat gateway hop in ws_handler."""
from noble_agent.server import ws_handler as h


def test_tenant_from_headers_reads_value():
    assert h._tenant_from_headers({"X-Tenant-Id": "acme"}) == "acme"


def test_tenant_from_headers_missing_or_blank_is_none():
    assert h._tenant_from_headers({}) is None
    assert h._tenant_from_headers({"X-Tenant-Id": "  "}) is None
    assert h._tenant_from_headers(None) is None


def test_gateway_secret_ok_disabled_when_secret_empty():
    # No configured secret → always OK (dev / trust-network, unchanged behavior).
    assert h._gateway_secret_ok("", {}) is True
    assert h._gateway_secret_ok("", {"X-Gateway-Secret": "whatever"}) is True


def test_gateway_secret_ok_requires_match_when_configured():
    assert h._gateway_secret_ok("shh", {"X-Gateway-Secret": "shh"}) is True
    assert h._gateway_secret_ok("shh", {"X-Gateway-Secret": "nope"}) is False
    assert h._gateway_secret_ok("shh", {}) is False
    assert h._gateway_secret_ok("shh", None) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_ws_handler_chat_headers.py -v`
Expected: FAIL (`_tenant_from_headers` / `_gateway_secret_ok` do not exist).

- [ ] **Step 3: Add the helpers + wire the chat branch**

In `src/noble_agent/server/ws_handler.py`, add `import hmac` at the top (with the other stdlib imports) and these module-level helpers:

```python
def _tenant_from_headers(headers) -> str | None:
    """Tenant the gateway injected via X-Tenant-Id (None when absent/blank)."""
    if not headers:
        return None
    val = (headers.get("X-Tenant-Id") or "").strip()
    return val or None


def _gateway_secret_ok(configured_secret: str, headers) -> bool:
    """When a gateway→worker shared secret is configured, require the incoming
    X-Gateway-Secret to match (constant-time). Empty configured secret → open."""
    if not configured_secret:
        return True
    provided = (headers.get("X-Gateway-Secret") or "") if headers else ""
    return hmac.compare_digest(provided, configured_secret)
```

Then rewrite the chat branch (lines 89-99) so it reads headers, enforces the secret, and passes the tenant:

```python
    if text_chat.is_chat_path(raw_path):
        hdrs = ws.request.headers if hasattr(ws, "request") and ws.request else {}
        if settings.chat_ws_require_token:
            from noble_agent.server.app_session import verify_connect_token

            token = qs.get("token", [None])[0]
            if not await verify_connect_token(session_id, token):
                logger.warning("[CHAT] unauthorized connect rejected (session=%s ip=%s)", session_id, client_ip)
                await ws.close(4401, "unauthorized")
                return
        if not _gateway_secret_ok(settings.gateway_worker_secret, hdrs):
            logger.warning("[CHAT] gateway secret mismatch rejected (session=%s ip=%s)", session_id, client_ip)
            await ws.close(4403, "gateway_secret_mismatch")
            return
        await text_chat.handle_text_session(ws, session_id, tenant_id=_tenant_from_headers(hdrs))
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_ws_handler_chat_headers.py -v` → PASS (4 tests).

- [ ] **Step 5: Full gate + lint**

Run: `make test-unit`
Expected: the documented baseline failures only (~9-10 pre-existing: 2 USD-normalize, `test_tool_ack` flaky, vieneu_vllm, prompt 'Tên:', qdrant_adapter×2, qdrant_store, send_media local-.env; `project_financial_mongo`/`snapshot_short_term` vary) + **ZERO new failures**. Confirm no test still references `agent_dispatch_name`.

Run: `ruff check src/noble_agent/server/ws_handler.py tests/unit/unified/test_ws_handler_chat_headers.py` → clean.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/server/ws_handler.py tests/unit/unified/test_ws_handler_chat_headers.py
git commit -m "feat(chat): worker /chat reads X-Tenant-Id + enforces X-Gateway-Secret"
```

---

## Notes for the implementer

- `asyncio_mode=auto`: async tests are plain `async def test_...` (no decorator). The tests in THIS plan are all sync (pure helpers / token minting) — no async test needed.
- `websockets` `Headers` supports case-insensitive `.get`; tests pass plain dicts (exact-case keys) — both work with the helpers.
- Task ordering matters: Task 1 removes `agent_dispatch_name` from `livekit_bridge`; Task 2 removes it from `worker`/`app_session` and then deletes the helper — after Task 2 there must be zero references left (Step 4 grep gate).
- Do not add try/except beyond what's shown; do not touch other routes/branches in `ws_handler` or other `build_dispatch_token`/`_mint_livekit_token` behavior (room, grants, empty_timeout unchanged).
```
