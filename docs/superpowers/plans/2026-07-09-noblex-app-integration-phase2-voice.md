# NobleX App Integration — Phase 2 (Voice/LiveKit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/v1/app/session` với `channel="voice"` trả về LiveKit token (room = session_id, có agent dispatch nhúng sẵn) để app Flutter join room và nói chuyện với Luna; agent tự load identity đã seed.

**Architecture:** Mở rộng `provision_session` (Phase 1) rẽ theo `channel`: `voice` → seed Customer (y hệt chat) + mint LiveKit access token với `RoomAgentDispatch(agent_name)` nhúng qua `with_room_config` (phương án A — mảnh còn thiếu để LiveKit dispatch agent vào room client). Helper mint token dùng chung cho endpoint `/livekit/token`, endpoint này nay gate sau `LIVEKIT_TOKEN_PUBLIC`. Worker KHÔNG sửa (invariant `room = session_id` + greet-by-session đã đủ).

**Tech Stack:** Python 3.11+, `livekit.api` (`AccessToken`/`VideoGrants`/`RoomConfiguration`/`RoomAgentDispatch`), pydantic-settings, `websockets` http11, pytest (asyncio_mode=auto) + fakeredis + PyJWT (có sẵn qua livekit-api).

## Global Constraints

- Chỉ đụng `server/app_session.py`, `server/http.py`, `config.py` + tests + docs + `.env.example`. **KHÔNG** đụng `transport/livekit/worker.py` / `room_session.py` / `base_session.py` / agent core / audio pipeline / Luna prompt.
- **Invariant:** provisioning voice PHẢI đặt `room = session_id` (`_derive_session_id(noble_user_id)`), nếu không worker load nhầm identity.
- `identity` participant = `f"user-{session_id}"` (chốt brainstorm).
- Phương án A: dispatch nhúng vào token qua `AccessToken.with_room_config(RoomConfiguration(agents=[RoomAgentDispatch(agent_name=settings.livekit_agent_name)]))`.
- Seed Customer khi voice giống hệt chat (cùng `_derive_session_id`, cùng merge truthy) — không tách logic seed.
- `_mint_livekit_token` **import `livekit.api` function-local** (giữ `make test-unit` collect được, mirror `http.py`).
- `/livekit/token` gate sau `settings.livekit_token_public` (default `false`); dùng CHUNG helper (nên cũng mint dispatch → fix luôn "browser tester không có agent").
- JWT claim shape (đã spike): `claims["sub"]`=identity, `claims["video"]["room"]`, `claims["video"]["roomJoin"]`, `claims["roomConfig"]["agents"][0]["agentName"]`. Decode test: `jwt.decode(tok, secret, algorithms=["HS256"], options={"verify_aud": False})`.
- Ruff line-length 120, rules E,F,W,I,UP,B,SIM. Commit conventional, **NO attribution trailer**. Format CHỈ file đã đụng (`ruff format <files>`), KHÔNG `make format`.
- Tests: `.venv/bin/python -m pytest` (system python thiếu deps). asyncio_mode=auto (không cần `@pytest.mark.asyncio`).

## File Structure

- **Modify** `src/noble_agent/config.py` — +`livekit_token_public: bool = False` (cạnh khối livekit settings ~line 560-567).
- **Modify** `src/noble_agent/server/app_session.py` — +`_mint_livekit_token()` helper; `provision_session` rẽ nhánh `channel="voice"`.
- **Modify** `src/noble_agent/server/http.py` — `/livekit/token` (~844-875): gate + dùng chung helper.
- **Modify** `.env.example`, `CLAUDE.md`, `docs/system-design/08-api-contracts-websocket-http.md`.
- **Modify** `tests/unit/unified/test_app_session.py` (voice provision) ; **Create** `tests/unit/unified/test_livekit_token_endpoint.py`.

---

### Task 1: Config `livekit_token_public`

**Files:**
- Modify: `src/noble_agent/config.py` (khối livekit, sau `livekit_worker_port: int = 8081`)
- Modify: `.env.example`
- Test: `tests/unit/unified/test_config.py`

**Interfaces:**
- Produces: `settings.livekit_token_public: bool` (default False).

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/unit/unified/test_config.py`:

```python
def test_livekit_token_public_default_false(monkeypatch):
    monkeypatch.delenv("LIVEKIT_TOKEN_PUBLIC", raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.livekit_token_public is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_config.py::test_livekit_token_public_default_false -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'livekit_token_public'`

- [ ] **Step 3: Add the setting**

Trong `src/noble_agent/config.py`, ngay sau `livekit_worker_port: int = 8081` thêm:

```python
    # When true, GET /livekit/token is publicly reachable (dev browser tester).
    # Prod keeps it false — the app path mints LiveKit tokens via
    # POST /api/v1/app/session (channel="voice") instead.
    livekit_token_public: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_config.py::test_livekit_token_public_default_false -v`
Expected: PASS

- [ ] **Step 5: Document env var**

Trong `.env.example`, trong khối LiveKit (gần `LIVEKIT_AGENT_NAME`), thêm:

```bash
# Public GET /livekit/token (dev browser tester). Prod=false → app dùng
# POST /api/v1/app/session channel=voice để mint token.
LIVEKIT_TOKEN_PUBLIC=false
```

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py .env.example tests/unit/unified/test_config.py
git commit -m "feat(config): add LIVEKIT_TOKEN_PUBLIC gate for /livekit/token"
```

---

### Task 2: `_mint_livekit_token` helper

**Files:**
- Modify: `src/noble_agent/server/app_session.py` (append helper)
- Test: `tests/unit/unified/test_app_session.py` (append)

**Interfaces:**
- Consumes: `settings.livekit_api_key`, `settings.livekit_api_secret`, `settings.livekit_agent_name`, `settings.livekit_public_url`, `settings.livekit_url`.
- Produces: `_mint_livekit_token(session_id: str, identity: str, name: str) -> tuple[str, str, str]` returning `(jwt, url, room)`; `room == session_id`; token grants `room_join` on `session_id` + embeds `RoomAgentDispatch(agent_name=settings.livekit_agent_name)`. Caller must ensure livekit key/secret are set.

- [ ] **Step 1: Write the failing tests**

Append vào `tests/unit/unified/test_app_session.py`:

```python
import jwt as _jwt

_LK_SECRET = "devsecret_change_me_for_prod_1234567890abcdef"


def _lk_settings(monkeypatch, public_url="wss://lk.noble.vn"):
    monkeypatch.setattr(A.settings, "livekit_api_key", "devkey")
    monkeypatch.setattr(A.settings, "livekit_api_secret", _LK_SECRET)
    monkeypatch.setattr(A.settings, "livekit_agent_name", "noble-hotline-agent")
    monkeypatch.setattr(A.settings, "livekit_public_url", public_url)
    monkeypatch.setattr(A.settings, "livekit_url", "ws://localhost:7880")


def test_mint_livekit_token_embeds_room_grants_and_dispatch(monkeypatch):
    _lk_settings(monkeypatch)
    tok, url, room = A._mint_livekit_token("app-6cb7cc1dd5d0", "user-app-6cb7cc1dd5d0", "Nga")
    assert url == "wss://lk.noble.vn"
    assert room == "app-6cb7cc1dd5d0"
    claims = _jwt.decode(tok, _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["sub"] == "user-app-6cb7cc1dd5d0"
    assert claims["video"]["room"] == "app-6cb7cc1dd5d0"
    assert claims["video"]["roomJoin"] is True
    assert claims["roomConfig"]["agents"][0]["agentName"] == "noble-hotline-agent"


def test_mint_livekit_token_url_falls_back_to_internal(monkeypatch):
    _lk_settings(monkeypatch, public_url="")
    _tok, url, _room = A._mint_livekit_token("app-x", "user-app-x", "user-app-x")
    assert url == "ws://localhost:7880"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_app_session.py -k mint_livekit -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_mint_livekit_token'`

- [ ] **Step 3: Append the helper**

Append vào `src/noble_agent/server/app_session.py`:

```python
def _mint_livekit_token(session_id: str, identity: str, name: str) -> tuple[str, str, str]:
    """Mint a LiveKit access token for `identity` to join room `session_id`,
    with the hotline agent embedded as a dispatched agent so LiveKit brings the
    agent into the room when the participant joins. Returns (jwt, url, room).
    Caller must ensure settings.livekit_api_key/secret are set.
    """
    from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

    token = (
        AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name or identity)
        .with_grants(
            VideoGrants(
                room_join=True,
                room=session_id,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(RoomConfiguration(agents=[RoomAgentDispatch(agent_name=settings.livekit_agent_name)]))
        .to_jwt()
    )
    url = settings.livekit_public_url or settings.livekit_url
    return token, url, session_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_app_session.py -k mint_livekit -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py
git add src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py
git commit -m "feat(app-session): _mint_livekit_token with embedded agent dispatch"
```
Expected: ruff clean.

---

### Task 3: `provision_session` voice branch

**Files:**
- Modify: `src/noble_agent/server/app_session.py` (`provision_session`)
- Test: `tests/unit/unified/test_app_session.py` (append)

**Interfaces:**
- Consumes: `_mint_livekit_token` (Task 2); existing seed logic; `settings.livekit_api_key/secret`.
- Produces: `provision_session(body)` with `body["channel"]=="voice"` → seeds Customer (same as chat) then returns `({session_id, channel:"voice", livekit_url, livekit_token, room}, 200)`; `503 {"error":"livekit_not_configured"}` if livekit key/secret unset. `channel` absent/"chat"/other → unchanged chat behavior (connect-token + ws_url).

- [ ] **Step 1: Write the failing tests**

Append vào `tests/unit/unified/test_app_session.py`:

```python
async def test_provision_voice_returns_livekit_token_and_seeds(fake_redis, monkeypatch):
    _lk_settings(monkeypatch)
    body = {
        "noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb",
        "channel": "voice",
        "identity": {"full_name": "Lê Viết Thúy Nga", "phone": "0378764303", "gender": "Female"},
    }
    payload, status = await A.provision_session(body)
    assert status == 200
    assert payload["channel"] == "voice"
    assert payload["session_id"] == "app-6cb7cc1dd5d0"
    assert payload["room"] == "app-6cb7cc1dd5d0"
    assert payload["livekit_url"] == "wss://lk.noble.vn"
    assert "livekit_token" in payload
    # no chat-only fields on the voice payload
    assert "ws_url" not in payload and "connect_token" not in payload
    # token carries room + dispatch
    claims = _jwt.decode(payload["livekit_token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["sub"] == "user-app-6cb7cc1dd5d0"
    assert claims["video"]["room"] == "app-6cb7cc1dd5d0"
    assert claims["roomConfig"]["agents"][0]["agentName"] == "noble-hotline-agent"
    # Customer seeded identically to chat
    from noble_agent.storage.repo import StateRepo

    repo = StateRepo(redis_client=fake_redis, ttl_seconds=86400)
    _m, cust, _s = await repo.load("app-6cb7cc1dd5d0")
    assert cust.noble_user_id == "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    assert cust.full_name == "Lê Viết Thúy Nga"
    assert cust.phone == "0378764303"
    assert cust.gender == "F"


async def test_provision_voice_503_when_livekit_unconfigured(fake_redis, monkeypatch):
    monkeypatch.setattr(A.settings, "livekit_api_key", "")
    monkeypatch.setattr(A.settings, "livekit_api_secret", "")
    payload, status = await A.provision_session(
        {"noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb", "channel": "voice"}
    )
    assert status == 503
    assert payload["error"] == "livekit_not_configured"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_app_session.py -k provision_voice -v`
Expected: FAIL — voice returns the chat payload (has `ws_url`) / no 503 branch yet.

- [ ] **Step 3: Add the voice branch**

Trong `src/noble_agent/server/app_session.py`, trong `provision_session`, ngay SAU dòng `await repo.save_all(session_id, meta, new_customer, state)` và TRƯỚC comment `# Mint a short-lived connect-token`, chèn:

```python
    if channel == "voice":
        if not (settings.livekit_api_key and settings.livekit_api_secret):
            return {"error": "livekit_not_configured"}, 503
        identity = f"user-{session_id}"
        lk_token, lk_url, room = _mint_livekit_token(session_id, identity, fields.get("full_name") or identity)
        return (
            {
                "session_id": session_id,
                "channel": "voice",
                "livekit_url": lk_url,
                "livekit_token": lk_token,
                "room": room,
            },
            200,
        )

```

(The existing chat tail — connect-token + `ws_url` — stays unchanged and now only runs for the non-voice path. `channel` is already read near the top of the function.)

- [ ] **Step 4: Run tests to verify they pass (+ no chat regression)**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_app_session.py -v`
Expected: PASS — voice tests green AND all Phase-1 chat tests (provision chat, idempotent, handle_app_session) still pass.

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py
git add src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py
git commit -m "feat(app-session): provision channel=voice → LiveKit token (room=session_id + dispatch)"
```
Expected: ruff clean.

---

### Task 4: Gate + rewire `GET /livekit/token`

**Files:**
- Modify: `src/noble_agent/server/http.py` (`/livekit/token` branch ~844-875)
- Test: `tests/unit/unified/test_livekit_token_endpoint.py` (create)

**Interfaces:**
- Consumes: `_mint_livekit_token` (Task 2); `settings.livekit_token_public` (Task 1).
- Produces: `GET /livekit/token` → `503 {"error":"livekit_token_disabled"}` when `livekit_token_public` false; `503` when livekit key/secret unset; else `200 {token,url,room,identity}` with the token now carrying agent dispatch. Grant room = the `?room=` query value.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/unified/test_livekit_token_endpoint.py`:

```python
import json

import jwt as _jwt

from noble_agent.server import http as H

_LK_SECRET = "devsecret_change_me_for_prod_1234567890abcdef"


class _FakeReqHTTP:
    """Minimal stand-in for websockets.http11.Request for process_request."""

    def __init__(self, path, method="GET"):
        self.path = path
        self.method = method
        self.headers = {}  # .get("Upgrade","") → "" (not a websocket upgrade)


async def test_livekit_token_disabled_by_default(monkeypatch):
    monkeypatch.setattr(H.settings, "livekit_token_public", False)
    resp = await H.process_request(None, _FakeReqHTTP("/livekit/token?room=r1"))
    assert resp.status_code == 503
    assert json.loads(resp.body)["error"] == "livekit_token_disabled"


async def test_livekit_token_enabled_mints_with_dispatch(monkeypatch):
    monkeypatch.setattr(H.settings, "livekit_token_public", True)
    monkeypatch.setattr(H.settings, "livekit_api_key", "devkey")
    monkeypatch.setattr(H.settings, "livekit_api_secret", _LK_SECRET)
    monkeypatch.setattr(H.settings, "livekit_agent_name", "noble-hotline-agent")
    monkeypatch.setattr(H.settings, "livekit_public_url", "wss://lk.noble.vn")
    resp = await H.process_request(None, _FakeReqHTTP("/livekit/token?room=r1&identity=i1"))
    assert resp.status_code == 200
    data = json.loads(resp.body)
    assert data["room"] == "r1" and data["identity"] == "i1" and data["url"] == "wss://lk.noble.vn"
    claims = _jwt.decode(data["token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["video"]["room"] == "r1"
    assert claims["roomConfig"]["agents"][0]["agentName"] == "noble-hotline-agent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_livekit_token_endpoint.py -v`
Expected: FAIL — no gate yet (disabled test gets 200 not 503) / token lacks `roomConfig` dispatch.

- [ ] **Step 3: Rewire the endpoint**

Trong `src/noble_agent/server/http.py`, thay TOÀN BỘ khối `if path == "/livekit/token":` (hiện ~844-875, gồm phần import livekit + dựng AccessToken inline) bằng:

```python
    # ── API: LiveKit access token (dev browser tester) ────────────────────
    # GET /livekit/token?room=<name>&identity=<name>. Gated: prod mints via
    # POST /api/v1/app/session (channel=voice). Uses the shared minter so the
    # token carries agent dispatch (RoomAgentDispatch) — without it a WebRTC
    # client joins an agent-less room.
    if path == "/livekit/token":
        if not settings.livekit_token_public:
            return _json_response({"error": "livekit_token_disabled"}, 503)
        if not settings.livekit_api_key or not settings.livekit_api_secret:
            return _json_response({"error": "LiveKit not configured"}, 503)
        from urllib.parse import parse_qs, urlparse

        from noble_agent.server.app_session import _mint_livekit_token

        qs = parse_qs(urlparse(request.path).query)
        room = qs.get("room", [f"hotline-{int(time.time())}"])[0]
        identity = qs.get("identity", [f"user-{int(time.time() * 1000)}"])[0]
        token, url, room = _mint_livekit_token(room, identity, identity)
        return _json_response({"token": token, "url": url, "room": room, "identity": identity})
```

(`time` is already imported at the top of `http.py`. This removes the inline `from livekit.api import AccessToken, VideoGrants` + hand-built grants — the shared helper replaces them.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/unified/test_livekit_token_endpoint.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/server/http.py tests/unit/unified/test_livekit_token_endpoint.py
git add src/noble_agent/server/http.py tests/unit/unified/test_livekit_token_endpoint.py
git commit -m "feat(server): gate /livekit/token behind LIVEKIT_TOKEN_PUBLIC + embed agent dispatch"
```
Expected: ruff clean (endpoint block clean; a pre-existing SIM108 elsewhere in http.py is NOT from this change — leave it).

---

### Task 5: Docs + verify

**Files:**
- Modify: `CLAUDE.md` (Change Log + config table note)
- Modify: `docs/system-design/08-api-contracts-websocket-http.md` (§2.6 voice + /livekit/token gate)

**Interfaces:** none (docs only).

- [ ] **Step 1: Verify the feature (scoped — repo has pre-existing red unrelated to this branch)**

Run:
```bash
.venv/bin/python -m pytest tests/unit/unified/test_app_session.py tests/unit/unified/test_livekit_token_endpoint.py tests/unit/unified/test_config.py -q
ruff check src/noble_agent/server/app_session.py src/noble_agent/server/http.py src/noble_agent/config.py
```
Expected: all feature tests pass; ruff shows only the pre-existing SIM108 in http.py (not from this branch) — app_session.py + config.py clean. Record output verbatim in the report.
Do NOT run `make test-unit`/`make lint` as a pass/fail gate — the repo has pre-existing failures (SIM108 http.py, SIM105 ws_handler.py, and red tests in test_build_faq_flatstore/test_tool_schemas/test_qdrant*). Do NOT fix those.

- [ ] **Step 2: Update the API contract doc**

Trong `docs/system-design/08-api-contracts-websocket-http.md`, trong §2.6 (app-session), thêm dưới phần response/errors đã có:

```markdown
**Voice channel** (`channel: "voice"`): response thay chat fields bằng `{"session_id","channel":"voice","livekit_url","livekit_token","room"}` (`room == session_id`). App dùng `livekit_client.connect(livekit_url, livekit_token)`; token nhúng `RoomAgentDispatch(agent_name)` nên LiveKit tự đưa agent vào room, và Customer đã seed theo `session_id` → agent chào đích danh. `503 livekit_not_configured` nếu LiveKit key/secret trống. `GET /livekit/token` chỉ bật khi `LIVEKIT_TOKEN_PUBLIC=true` (dev tester), prod dùng đường provisioning này.
```

- [ ] **Step 3: Update CLAUDE.md**

Thêm một dòng ở đầu bảng Change Log (dưới header separator) trong `CLAUDE.md` (TODAY = 2026-07-09):

```markdown
| 2026-07-09 | **NobleX app Phase 2 (voice): provisioning mints LiveKit token w/ embedded agent dispatch; `/livekit/token` gated.** `provision_session(channel="voice")` seeds Customer (như chat) + `_mint_livekit_token()` (new, `server/app_session.py`) → LiveKit `AccessToken` với `room=session_id` + `RoomConfiguration(agents=[RoomAgentDispatch(agent_name=livekit_agent_name)])` (phương án A — mảnh còn thiếu để client WebRTC được dispatch agent; SIP telephony vẫn dùng trunk dispatch rule). Response `{session_id, channel:"voice", livekit_url, livekit_token, room}`; `503 livekit_not_configured` nếu chưa cấu hình LiveKit. `GET /livekit/token` nay dùng chung `_mint_livekit_token` (nên cũng mint dispatch) và gate sau `LIVEKIT_TOKEN_PUBLIC` (default false; dev=true cho browser tester). Worker KHÔNG sửa (invariant `room=session_id` + greet-by-session). New setting `LIVEKIT_TOKEN_PUBLIC`. Infra prerequisite (public wss + TURN) là runbook ops, e2e mobile hoãn tới khi expose. Spec `docs/superpowers/specs/2026-07-09-noblex-voice-livekit-phase2-design.md`. Branch `feat/app-integration`. | Kênh voice cho bubble NobleX app: cùng endpoint provisioning trả LiveKit token, agent join room qua dispatch nhúng, identity đã seed. |
```

Và trong Key configuration table (hoặc mục backends nơi liệt kê env), thêm dòng: `LIVEKIT_TOKEN_PUBLIC | false | Public GET /livekit/token (dev tester); prod mints via POST /api/v1/app/session channel=voice.`

- [ ] **Step 4: Manual smoke (document, do NOT run live — needs public infra)**

Trong report, liệt kê smoke ops chạy khi infra public: (1) `curl -X POST .../api/v1/app/session -H "X-Noble-App-Key: …" -d '{"noble_user_id":"…","channel":"voice","identity":{…}}'` → nhận `{livekit_url, livekit_token, room}`; (2) Flutter `livekit_client.connect` → agent join room, nghe greeting đích danh; (3) `LIVEKIT_TOKEN_PUBLIC=false` → `GET /livekit/token` trả 503; set true → browser tester `static/livekit.html` có agent.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/system-design/08-api-contracts-websocket-http.md
git commit -m "docs: document app-session voice channel + /livekit/token gate (Phase 2)"
```

---

## Out of scope (per spec)
Flutter client (livekit_client + bubble UI); infra deployment (expose public + TURN — runbook only); greeting prompt personalization tuning; end-to-end mobile verification (deferred until public).

## Self-Review

- **Spec coverage:** provision voice branch + LiveKit token (T3) · embedded dispatch via `_mint_livekit_token` (T2) · `/livekit/token` gate + shared helper (T4) · `LIVEKIT_TOKEN_PUBLIC` setting (T1) · docs + runbook note (T5) · `room=session_id` invariant + `identity=user-{session_id}` (T2/T3) · worker not touched (design, no task needed) · infra runbook (spec §6, documented in T5 report as ops). ✔ all Phase-2 spec requirements have a task or are explicitly out-of-scope.
- **Placeholder scan:** none — every code/doc step has literal content + exact commands/expected output.
- **Type consistency:** `_mint_livekit_token(session_id, identity, name) -> (jwt, url, room)` identical in T2 def, T3 call, T4 call; JWT claim keys (`sub`/`video.room`/`video.roomJoin`/`roomConfig.agents[0].agentName`) identical across T2/T3/T4 tests (matches the spike); `provision_session(body)->(dict,int)` unchanged from Phase 1; `settings.livekit_token_public` name identical T1↔T4.
