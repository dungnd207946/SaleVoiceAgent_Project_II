# Shared-process heartbeat multi-tenant + app_session per-request tenant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a shared process serving N tenants, emit an SP-D heartbeat for every active tenant (not just `settings.tenant_id`), and let `/api/v1/app/session` resolve the tenant per-request and carry it into the LiveKit participant metadata.

**Architecture:** Add a `HeartbeatSupervisor` that owns one `HeartbeatEmitter` per active tenant (enumerated from the store each cycle, materialize-only build) and wire it into both transports. Make `provision_session` read `tenant_id` from the request body, scope the body with `use_tenant(...)`, and add `tenant_id` to the participant metadata in `_mint_livekit_token`. All additive with a `settings.tenant_id` fallback so single-tenant/direct paths stay byte-identical; the whole heartbeat feature is inert when the tenant store is disabled.

**Tech Stack:** Python 3.11+, asyncio, `livekit.api` (hard dep), pydantic-settings (`UnifiedSettings`), pytest (`asyncio_mode=auto`).

## Global Constraints

- **Tenant resolved per-tenant / per-request, never `settings.tenant_id` at process scope** for the two paths in scope.
- **Single-tenant / direct paths byte-identical:** heartbeat store disabled → `should_emit` false → supervisor never starts; app_session with no body `tenant_id` → falls back to `settings.tenant_id`; the participant metadata `tenant_id` still resolves to the same tenant the worker used before.
- **Heartbeat build is materialize-only for every tenant** (`build_materialize_fn`) — no full LLM runner. This replaces the aiortc process's prior `ensure_version_built` full-runner warm.
- **Keep `HeartbeatEmitter`, `build_materialize_fn`, `should_emit`, `build_heartbeat` unchanged** — the supervisor composes them.
- **Surgical / additive.** No changes to RAG / `send_media` / `kb_search`, the turn loop, the gateway, or the Redis key shape. ruff `E,F,W,I,UP,B,SIM`, line-length 120. Tests offline (no live MinIO / LiveKit / network).
- Work on the current branch `feat/share-agent`. Commit LOCALLY only — no push/merge/rebase/PR. Append this trailer as the last line of every commit body:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Spec of record: `docs/superpowers/specs/2026-08-03-shared-process-heartbeat-appsession-tenant-design.md`.

---

### Task 1: `HeartbeatSupervisor` — one emitter per active tenant

**Files:**
- Modify: `src/noble_agent/tenant/heartbeat.py` (add `HeartbeatSupervisor` at end of file; keep everything else as-is)
- Test: `tests/unit/tenant/test_heartbeat.py` (append the supervisor tests)

**Interfaces:**
- Consumes: `HeartbeatEmitter`, `build_materialize_fn`, `_utc_iso` (same module); `store.list_ids()`, `store.read_meta(tid).status`, `store.read_pointer`, `store.write_heartbeat` (the store Protocol).
- Produces: `HeartbeatSupervisor(store, settings, *, build_fn_factory=None, now_iso=_utc_iso)` with `async run(stop_event: asyncio.Event) -> None` and, for tests, `async _cycle() -> None` + `_active_tenants() -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/tenant/test_heartbeat.py` (the helpers `_versioned_store`, `_add_version`, `_pub_bundle`, `_S`, `_ok_build`, `ISO`, `FakeTenantStore` already exist at the top of that file):

```python
# ── HeartbeatSupervisor (multi-tenant) ──────────────────────────────────────
def _multi_store(*tids):
    s = FakeTenantStore()
    for tid in tids:
        _add_version(s, tid, 1, "one")
        s.write_pointer(tid, 1)
    return s


def _supervisor(store, **kw):
    VR.reset_for_tests()
    kw.setdefault("build_fn_factory", lambda tid: _ok_build)
    kw.setdefault("now_iso", lambda: ISO)
    return HB.HeartbeatSupervisor(store, _S(), **kw)


async def test_supervisor_emits_one_heartbeat_per_active_tenant():
    s = _multi_store("t1", "t2", "t3")
    sup = _supervisor(s)
    await sup._cycle()
    assert set(s._heartbeats) == {"t1", "t2", "t3"}
    assert s._heartbeats["t2"]["status_hint"] == "serving"


async def test_supervisor_skips_non_active_tenants():
    s = _multi_store("t1", "t2")
    s.write_status("t2", "disabled")
    sup = _supervisor(s)
    await sup._cycle()
    assert set(s._heartbeats) == {"t1"}  # disabled tenant gets no beat


async def test_supervisor_reconcile_drops_tenant_when_deactivated():
    s = _multi_store("t1", "t2")
    sup = _supervisor(s)
    await sup._cycle()
    assert set(sup._emitters) == {"t1", "t2"}
    s.write_status("t2", "disabled")
    await sup._cycle()
    assert set(sup._emitters) == {"t1"}  # emitter for t2 dropped


async def test_supervisor_store_error_keeps_current_set(monkeypatch):
    s = _multi_store("t1")
    sup = _supervisor(s)
    await sup._cycle()  # establishes {"t1"}
    monkeypatch.setattr(s, "list_ids", lambda: (_ for _ in ()).throw(RuntimeError("store down")))
    await sup._cycle()  # must not crash; keeps t1 and still beats it
    assert set(sup._emitters) == {"t1"}


async def test_supervisor_emitters_keep_independent_state():
    s = _multi_store("t1", "t2")
    sup = _supervisor(s)
    await sup._cycle()
    assert sup._emitters["t1"] is not sup._emitters["t2"]
    assert sup._emitters["t1"]._tenant == "t1"
    assert sup._emitters["t2"]._tenant == "t2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/tenant/test_heartbeat.py -k supervisor -v`
Expected: FAIL (`HB.HeartbeatSupervisor` does not exist).

- [ ] **Step 3: Implement `HeartbeatSupervisor`**

Append to `src/noble_agent/tenant/heartbeat.py` (after `HeartbeatEmitter`):

```python
class HeartbeatSupervisor:
    """Runs one :class:`HeartbeatEmitter` per ACTIVE tenant in the store, so a
    single shared process emits ``<tenant>/_heartbeat.json`` for every tenant it
    serves (not just ``settings.tenant_id``).

    Each cycle: refresh the active-tenant set from the store, reconcile the
    per-tenant emitters (add new, drop deactivated), then beat them all
    concurrently. A store-read error on the refresh keeps the current set — an
    emitter that can no longer read its own version already reports ``degraded`` /
    skips, and a stale ``ts`` is the honest "disconnected" signal. Emitters use a
    materialize-only ``build_fn`` (no full LLM runner) so serving N tenants never
    builds N runners.
    """

    def __init__(self, store, settings, *, build_fn_factory=None, now_iso=_utc_iso):
        self._store = store
        self._settings = settings
        self._now_iso = now_iso
        self._interval = float(getattr(settings, "heartbeat_sec", 20.0))
        # tenant_id -> async ``version -> None`` warmer; default = materialize-only.
        self._build_fn_factory = build_fn_factory or (
            lambda tid: build_materialize_fn(store, settings, tid)
        )
        self._emitters: dict[str, HeartbeatEmitter] = {}

    def _active_tenants(self) -> list[str]:
        out: list[str] = []
        for tid in self._store.list_ids():
            meta = self._store.read_meta(tid)
            if meta is not None and meta.status == "active":
                out.append(tid)
        return out

    def _reconcile(self, active: list[str]) -> None:
        active_set = set(active)
        for tid in active:
            if tid not in self._emitters:
                self._emitters[tid] = HeartbeatEmitter(
                    self._store,
                    self._settings,
                    tid,
                    build_fn=self._build_fn_factory(tid),
                    now_iso=self._now_iso,
                )
        for tid in list(self._emitters):
            if tid not in active_set:
                del self._emitters[tid]

    async def _cycle(self) -> None:
        try:
            active = await asyncio.to_thread(self._active_tenants)
        except Exception:
            logger.warning("heartbeat: active-tenant refresh failed — keeping current set", exc_info=True)
            active = list(self._emitters)
        self._reconcile(active)
        if self._emitters:
            await asyncio.gather(
                *(em.beat() for em in self._emitters.values()), return_exceptions=True
            )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Beat every active tenant every ``heartbeat_sec`` until ``stop_event``."""
        logger.info("heartbeat supervisor: started interval=%.0fs", self._interval)
        try:
            while not stop_event.is_set():
                try:
                    await self._cycle()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("heartbeat supervisor: cycle raised (continuing)")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
        finally:
            logger.info("heartbeat supervisor: stopped (%d tenants)", len(self._emitters))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_heartbeat.py -v`
Expected: PASS (existing emitter tests + 5 new supervisor tests).

- [ ] **Step 5: Lint**

Run: `ruff check src/noble_agent/tenant/heartbeat.py tests/unit/tenant/test_heartbeat.py` → clean.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/tenant/heartbeat.py tests/unit/tenant/test_heartbeat.py
git commit -m "feat(heartbeat): HeartbeatSupervisor emits one beat per active tenant"
```

---

### Task 2: Wire the supervisor into both transports

**Files:**
- Modify: `src/noble_agent/server/http.py` (heartbeat block ~L1024-1034; the shutdown block ~L1057-1060 is unchanged)
- Modify: `src/noble_agent/transport/livekit/worker.py` (`_start_heartbeat` ~L263-304)
- Test: `tests/unit/unified/test_worker_heartbeat.py` (existing gate tests stay green — no new test needed)

**Interfaces:**
- Consumes: `HeartbeatSupervisor` (Task 1). After this task neither transport constructs a bare `HeartbeatEmitter`.
- Produces: both transports run a `HeartbeatSupervisor`.

- [ ] **Step 1: Point aiortc at the supervisor**

In `src/noble_agent/server/http.py`, inside the `if should_emit(settings):` block, replace the `HeartbeatEmitter` import + construction with the supervisor (the surrounding `heartbeat_task`/`hb_stop`/try-except/shutdown-cancel stay exactly as they are):

```python
        try:
            from noble_agent.tenant.heartbeat import HeartbeatSupervisor
            from noble_agent.tenant.loader import _build_store

            hb_stop = asyncio.Event()
            supervisor = HeartbeatSupervisor(_build_store(settings), settings)
            heartbeat_task = asyncio.create_task(supervisor.run(hb_stop))
            log.info("Heartbeat supervisor started (every %.0fs, active tenants)", settings.heartbeat_sec)
        except Exception as exc:  # noqa: BLE001 — heartbeat must never abort boot
            log.error("Heartbeat supervisor failed to start (continuing): %s", exc)
```

- [ ] **Step 2: Point the LiveKit worker at the supervisor**

In `src/noble_agent/transport/livekit/worker.py`, rewrite `_start_heartbeat`'s import + `_run` inner so it constructs a `HeartbeatSupervisor` (drop the per-`settings.tenant_id` `HeartbeatEmitter` + `build_materialize_fn` construction — the supervisor defaults to materialize-only; the daemon-thread + own-loop + gate + log pattern is unchanged):

```python
    from noble_agent.tenant.heartbeat import HeartbeatSupervisor, should_emit

    if not should_emit(settings):
        return

    def _run() -> None:
        import asyncio as _asyncio

        from noble_agent.tenant.loader import _build_store

        async def _main() -> None:
            supervisor = HeartbeatSupervisor(_build_store(settings), settings)
            await supervisor.run(_asyncio.Event())  # never set → runs for the worker's life

        try:
            _asyncio.run(_main())
        except Exception:  # noqa: BLE001 — heartbeat must never take down the worker
            logger.warning("heartbeat: LiveKit thread crashed", exc_info=True)

    threading.Thread(target=_run, name="sp-d-heartbeat", daemon=True).start()
    logger.info("heartbeat: LiveKit supervisor daemon thread started")
```

Also update `_start_heartbeat`'s docstring first sentence from "one HeartbeatEmitter for settings.tenant_id" wording to note it now runs a `HeartbeatSupervisor` over all active tenants (keep the rest of the docstring — daemon-thread rationale + split-deploy note — intact).

- [ ] **Step 3: Run the wiring gate tests + a broad heartbeat/worker slice**

Run: `pytest tests/unit/unified/test_worker_heartbeat.py tests/unit/tenant/test_heartbeat.py -v`
Expected: PASS. The two worker gate tests still pass unchanged (they spy on `threading.Thread` via the `should_emit` gate; the supervisor is constructed inside the thread's `_run`, not at `_start_heartbeat` time).

- [ ] **Step 4: Confirm no bare emitter remains in the transports + lint**

Run: `grep -n "HeartbeatEmitter(" src/noble_agent/server/http.py src/noble_agent/transport/livekit/worker.py` → **no matches** (both now build the supervisor).
Run: `ruff check src/noble_agent/server/http.py src/noble_agent/transport/livekit/worker.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/http.py src/noble_agent/transport/livekit/worker.py
git commit -m "feat(heartbeat): both transports run HeartbeatSupervisor over active tenants"
```

---

### Task 3: `app_session` resolves tenant per-request + carries it in metadata

**Files:**
- Modify: `src/noble_agent/server/app_session.py` (`provision_session` ~L92-163; `_mint_livekit_token` ~L212-247; add a `use_tenant` import)
- Test: `tests/unit/unified/test_app_session.py` (extend `_FakeToken`; add mint + provision tenant tests)
- Then: full gate (`make test-unit`)

**Interfaces:**
- Consumes: `use_tenant` from `noble_agent.tenant.current`; `settings.tenant_id`.
- Produces: `_mint_livekit_token(session_id, identity, name, *, tenant_id=None, empty_timeout=_ROOM_EMPTY_TIMEOUT_S)` — participant metadata JSON `{"tenant_id": tenant_id or settings.tenant_id}`; `provision_session` reads `body["tenant_id"]`, scopes the body with `use_tenant`, and passes `tenant_id=` into the voice mint.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/unified/test_app_session.py`, add a `with_metadata` recorder to the existing `_FakeToken` class (so the real function's new `.with_metadata(...)` call is captured and does not break the existing `_FakeToken`-based dispatch test):

```python
    def with_metadata(self, v):
        self.calls.append(("metadata", v))
        return self
```

Then add these tests (the file already imports `json as _json_mod`, `jwt as _jwt`, `A`, and defines `_lk_settings`, `_LK_SECRET`, `_FakeToken`, `fake_redis`):

```python
def test_mint_livekit_token_embeds_tenant_metadata(monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    tok = _FakeToken()
    monkeypatch.setattr("livekit.api.AccessToken", lambda *a, **k: tok)
    A._mint_livekit_token("app-x", "user-app-x", "user-app-x", tenant_id="acme")
    meta = _json_mod.loads(dict(tok.calls)["metadata"])
    assert meta == {"tenant_id": "acme"}


def test_mint_livekit_token_metadata_falls_back_to_settings_tenant(monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    tok = _FakeToken()
    monkeypatch.setattr("livekit.api.AccessToken", lambda *a, **k: tok)
    A._mint_livekit_token("app-x", "user-app-x", "user-app-x")  # no tenant_id
    meta = _json_mod.loads(dict(tok.calls)["metadata"])
    assert meta == {"tenant_id": "noble"}


async def test_provision_voice_uses_body_tenant_in_metadata(fake_redis, monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    body = {"noble_user_id": "u1", "channel": "voice", "tenant_id": "acme", "identity": {}}
    payload, status = await A.provision_session(body)
    assert status == 200
    claims = _jwt.decode(
        payload["livekit_token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )
    assert _json_mod.loads(claims["metadata"]) == {"tenant_id": "acme"}


async def test_provision_voice_tenant_falls_back_to_settings(fake_redis, monkeypatch):
    _lk_settings(monkeypatch)  # settings.tenant_id = "noble"
    body = {"noble_user_id": "u1", "channel": "voice", "identity": {}}  # no tenant_id
    payload, status = await A.provision_session(body)
    assert status == 200
    claims = _jwt.decode(
        payload["livekit_token"], _LK_SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )
    assert _json_mod.loads(claims["metadata"]) == {"tenant_id": "noble"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_app_session.py -k "tenant_metadata or body_tenant or tenant_falls_back or metadata_falls_back" -v`
Expected: FAIL (`_mint_livekit_token` has no `tenant_id` kwarg and emits no metadata; `provision_session` ignores `body["tenant_id"]`).

- [ ] **Step 3: Add `tenant_id` metadata to `_mint_livekit_token`**

In `src/noble_agent/server/app_session.py`, change `_mint_livekit_token`'s signature and add the metadata call (everything else — grants, room config, url resolution, return — unchanged):

```python
def _mint_livekit_token(
    session_id: str,
    identity: str,
    name: str,
    *,
    tenant_id: str | None = None,
    empty_timeout: int = _ROOM_EMPTY_TIMEOUT_S,
) -> tuple[str, str, str]:
    """Mint a LiveKit access token for `identity` to join room `session_id`,
    with the hotline agent embedded as a dispatched agent so LiveKit brings the
    agent into the room when the participant joins, and the resolved `tenant_id`
    carried as participant metadata so the shared worker's `_job_tenant` resolves
    the caller's tenant (falls back to `settings.tenant_id`). Returns (jwt, url, room).
    Caller must ensure settings.livekit_api_key/secret are set.

    `empty_timeout` is applied to the room LiveKit auto-creates from this token
    (honored only at creation) so the room is released quickly once empty.
    """
    import json

    from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

    tid = tenant_id or settings.tenant_id
    token = (
        AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name or identity)
        .with_metadata(json.dumps({"tenant_id": tid}, ensure_ascii=False))
        .with_grants(
            VideoGrants(
                room_join=True,
                room=session_id,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(
            RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=settings.livekit_agent_name)],
                empty_timeout=empty_timeout,
            )
        )
        .to_jwt()
    )
    url = settings.livekit_public_url or settings.livekit_url
    return token, url, session_id
```

- [ ] **Step 4: Resolve the tenant in `provision_session` + pass it to the mint**

In `src/noble_agent/server/app_session.py`, add the import near the other `noble_agent` imports at the top of the file:

```python
from noble_agent.tenant.current import use_tenant
```

Then change the top of `provision_session` to resolve the tenant and wrap the whole body in `use_tenant`, and pass `tenant_id=` into the voice mint. The full function becomes:

```python
async def provision_session(body: dict) -> tuple[dict, int]:
    """Core provisioning (transport-agnostic, testable). Returns (payload, status)."""
    noble_user_id = str(body.get("noble_user_id") or "").strip()
    if not noble_user_id:
        return {"error": "noble_user_id required"}, 400

    tenant_id = str(body.get("tenant_id") or "").strip() or settings.tenant_id
    with use_tenant(tenant_id):
        channel = body.get("channel") or "chat"
        identity = body.get("identity") or {}
        session_id = _derive_session_id(noble_user_id)
        if channel == "voice":
            session_id = f"{session_id}-{int(time.time() * 1000)}-{secrets.token_hex(2)}"

        fields: dict = {"noble_user_id": noble_user_id, **identity_to_fields(identity)}

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

        if channel == "voice":
            if not (settings.livekit_api_key and settings.livekit_api_secret):
                return {"error": "livekit_not_configured"}, 503
            identity = f"user-{session_id}"
            lk_token, lk_url, room = _mint_livekit_token(
                session_id, identity, fields.get("full_name") or identity, tenant_id=tenant_id
            )
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
```

- [ ] **Step 5: Run the app_session tests to verify they pass**

Run: `pytest tests/unit/unified/test_app_session.py -v`
Expected: PASS — the 4 new tests plus every pre-existing app_session test (incl. `test_mint_livekit_token_uses_shared_dispatch_name`, which now exercises the extended `_FakeToken.with_metadata`, and the JWT-decode voice tests, which are unaffected by the added `metadata` claim).

- [ ] **Step 6: Full gate + lint**

Run: `make test-unit`
Expected: the documented baseline failures only (~9-11 pre-existing: 2 USD-normalize, `test_tool_ack` flaky, vieneu_vllm, prompt 'Tên:', qdrant_adapter×2, qdrant_store, send_media local-.env; `project_financial_mongo`/`snapshot_short_term` vary) + **ZERO new failures**.
Run: `ruff check src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py` → clean.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/server/app_session.py tests/unit/unified/test_app_session.py
git commit -m "feat(app_session): resolve tenant per-request + carry it in LiveKit metadata"
```

---

## Notes for the implementer

- `asyncio_mode=auto`: async tests are plain `async def test_...` (no decorator). Sync tests (token minting, pure supervisor reconcile) are plain `def`.
- `use_tenant` is a **sync** `@contextmanager` (`noble_agent/tenant/current.py`); using `with use_tenant(tid):` around `await` calls is correct — the ContextVar stays set for the duration within the same task.
- Task 2 has no new test file by design: the emitter/supervisor loop is unit-tested in Task 1, and the existing `test_worker_heartbeat.py` gate tests already cover the daemon-thread start/no-start. Verify Task 2 via those tests + the `grep` gate + ruff.
- Do not change room name, grants, `empty_timeout`, the dispatch `agent_name` (already `settings.livekit_agent_name`), the shutdown-cancel block in `http.py`, or the `should_emit` gate.
- Task ordering: Task 1 defines `HeartbeatSupervisor` that Task 2 wires in; Task 3 is independent of 1-2. Run the full `make test-unit` gate only at the end of Task 3.
```
