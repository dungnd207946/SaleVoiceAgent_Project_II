# SP-C2 — Version-Pinned Config Load (Read Side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent resolves the published config version at each conversation start, pins it for that conversation's lifetime (BR05), refreshes within ~20s (YC03), checksums the version (E04), and falls back to the last-good local copy when the store is unreachable (E01).

**Architecture:** A new `tenant/version_resolver.py` provides a TTL-cached `current_published_version()` and a per-version `context_for_version()` (materialize `versions/<n>/` → checksum → build `TenantContext`). The facade replaces its single `_runner_singleton` with a **version-keyed runner registry**; `NobleAgent.create()` resolves the current version and hands the version's runner to the instance — because both transports create one `NobleAgent` per conversation and hold it for the whole conversation, the instance IS the per-conversation pin (no session→version map needed). When `TENANT_STORE_ENABLED=false` the legacy single-runner path is kept unchanged.

**Tech Stack:** Python 3.11+, stdlib `json`/`hashlib`/`pathlib`, pytest (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-sp-c2-version-pinned-load-design.md`. Contract C2: `docs/api/odyssey-agent-interface-contract.md`. Depends on SP-C1 store API: `read_pointer(t)->int|None`, `read_version_bundle(t,n)->Bundle|None`, `list_versions(t)->[int]`, `read_meta(t).published_version`.
- BR05: a conversation keeps the version it started with, end to end. Never swap a live `NobleAgent`'s runner.
- YC03: a newly published version is picked up by NEW conversations within ~`NOBLE_CONFIG_POLL_SEC` (default 20) — via a TTL cache on the pointer read, NOT a per-conversation store round-trip on the hot path.
- E04: after reading a version, verify `bundle_hash(manifest, files) == stored hash`; mismatch → do NOT build that version, keep last-good, record the error.
- E01: store unreachable when resolving → serve the highest locally-materialized version; none present → fail loud.
- Back-compat: `TENANT_STORE_ENABLED=false` (package mode) keeps the exact current single-runner behavior. `NobleAgent.create()` / `stream_response` / transports' call sites UNCHANGED in signature.
- Do NOT modify SP-C1 store/provisioning code. ruff clean on touched files; no new failures in `tests/unit/tenant` or `tests/unit/unified`.
- Branch `feat/agent`; local commits only.
- **Test-output caveat:** an "rtk" shell hook can mangle piped pytest/grep/git output. Redirect to a file and Read it (or use `.venv/bin/python -m pytest … > out 2>&1`) for ground truth; confirm via the file + exit code, not the inline summary.

---

### Task 1: Factor `loader._context_from_dir` (no behavior change)

**Files:**
- Modify: `src/noble_agent/tenant/loader.py`
- Test: `tests/unit/tenant/test_loader.py` (add one)

**Interfaces:**
- Produces: `_context_from_dir(tenant_id:str, tenant_dir:Path, *, is_materialized:bool) -> TenantContext` — the manifest-parse + tool-import + `TenantContext` build currently inlined in `load_tenant`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/tenant/test_loader.py (add)
from pathlib import Path
from noble_agent.tenant.loader import _context_from_dir
import noble_agent

def test_context_from_dir_builds_context():
    d = Path(noble_agent.__file__).resolve().parent / "tenants" / "noble"
    ctx = _context_from_dir("noble", d, is_materialized=False)
    assert ctx.tenant_id == "noble"
    assert "escalate" in ctx.enabled_tools
    assert ctx.persona_dir == (d / "persona").resolve()
```

- [ ] **Step 2: Run → fail** (`ImportError: _context_from_dir`).

- [ ] **Step 3: Implement** — extract the body of `load_tenant` after `_resolve_tenant_dir` (manifest read/parse, required-key check, brand, tool import, `TenantContext(...)`) into `_context_from_dir(tenant_id, tenant_dir, *, is_materialized)`. Rewrite `load_tenant` to call `_resolve_tenant_dir` then `return _context_from_dir(tenant_id, tenant_dir, is_materialized=is_materialized)`. No logic change.

- [ ] **Step 4: Run → pass**, plus `pytest tests/unit/tenant -q` green (no regression).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/loader.py tests/unit/tenant/test_loader.py
git commit -m "refactor(tenant): extract loader._context_from_dir (SP-C2 t1)"
```

---

### Task 2: `NOBLE_CONFIG_POLL_SEC` setting

**Files:**
- Modify: `src/noble_agent/config.py`
- Test: `tests/unit/unified/test_config_poll_sec.py` (new, tiny)

**Interfaces:** Produces `settings.noble_config_poll_sec: float` (default `20.0`), env `NOBLE_CONFIG_POLL_SEC`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_config_poll_sec.py
from noble_agent.config import UnifiedSettings
def test_default_poll_sec():
    assert UnifiedSettings(_env_file=None).noble_config_poll_sec == 20.0
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — add the field next to the other tenant settings in `config.py` (match the existing pydantic-settings field style + env alias). Document one line in `.env.example`.
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/config.py tests/unit/unified/test_config_poll_sec.py .env.example
git commit -m "feat(config): NOBLE_CONFIG_POLL_SEC for version poll TTL (SP-C2 t2)"
```

---

### Task 3: `version_resolver.context_for_version` (materialize + checksum E04 + build)

**Files:**
- Create: `src/noble_agent/tenant/version_resolver.py`
- Test: `tests/unit/tenant/test_version_resolver.py` (new)

**Interfaces:**
- Consumes: store `read_version_bundle`, `bundle_hash`, `loader._context_from_dir`.
- Produces:
  - `class ChecksumError(Exception)`
  - `materialize_version(store, tenant_id, version:int, dest_root) -> Path` — writes `dest_root/<tenant>/versions/<n>/` atomically (temp+rename); returns the dir. Raises `ChecksumError` if `bundle_hash(bundle.manifest_text, bundle.files) != bundle.meta.bundle_hash` (E04). Raises `FileNotFoundError` if the version is absent.
  - `context_for_version(store, settings, tenant_id, version:int) -> TenantContext` — `materialize_version(...)` then `loader._context_from_dir(tenant_id, dir, is_materialized=True)`; caches by `version` in a module dict.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/tenant/test_version_resolver.py
import pytest
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, VersionInfo, bundle_hash
from noble_agent.tenant import version_resolver as VR

def _pub_bundle(tid, soul):
    mtext = (f'tenant_id="{tid}"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n')
    files = {"persona/SOUL.md": soul, "persona/RULES.md": "escalate", "persona/PROMPT_TEMPLATE.md": "x",
             "persona/CUSTOMER_PROFILE.md": "x", "persona/config.json": "{}"}
    bh = bundle_hash(mtext, files)
    return mtext, files, bh

def _store_with_v1(tid="tt", soul="one"):
    s = FakeTenantStore()
    mtext, files, bh = _pub_bundle(tid, soul)
    meta = TenantMeta(tid, "active", 1, bh, published_version=1, latest_version=1)
    s.write_version_bundle(tid, 1, Bundle(tid, mtext, files, meta), VersionInfo(tid, 1, bh))
    s.write_pointer(tid, 1)
    return s

def test_materialize_and_build_context(tmp_path):
    VR._context_cache.clear()
    s = _store_with_v1()
    class _S:  # minimal settings
        tenant_materialize_dir = str(tmp_path)
    ctx = VR.context_for_version(s, _S(), "tt", 1)
    assert ctx.tenant_id == "tt" and "escalate" in ctx.enabled_tools
    assert (tmp_path / "tt" / "versions" / "1" / "persona" / "SOUL.md").read_text() == "one"

def test_checksum_mismatch_raises(tmp_path, monkeypatch):
    s = _store_with_v1()
    # corrupt: return a bundle whose stored hash != content
    good = s.read_version_bundle("tt", 1)
    bad_meta = good.meta.__class__(**{**good.meta.__dict__, "bundle_hash": "sha256:WRONG"})
    monkeypatch.setattr(s, "read_version_bundle", lambda t, n: Bundle("tt", good.manifest_text, good.files, bad_meta))
    class _S: tenant_materialize_dir = str(tmp_path)
    with pytest.raises(VR.ChecksumError):
        VR.materialize_version(s, "tt", 1, str(tmp_path))
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** `version_resolver.py`:

```python
from __future__ import annotations
import os, shutil
from pathlib import Path
from uuid import uuid4
from noble_agent.tenant.store import bundle_hash

class ChecksumError(Exception): ...

_MARKER = ".bundle_hash"
_context_cache: dict[tuple[str, int], object] = {}

def materialize_version(store, tenant_id, version, dest_root):
    bundle = store.read_version_bundle(tenant_id, version)
    if bundle is None:
        raise FileNotFoundError(f"version {version} not in store for {tenant_id!r}")
    computed = bundle_hash(bundle.manifest_text, bundle.files)
    if computed != bundle.meta.bundle_hash:
        raise ChecksumError(f"{tenant_id} v{version}: {computed} != {bundle.meta.bundle_hash}")
    dest = Path(dest_root) / tenant_id / "versions" / str(version)
    marker = dest / _MARKER
    if dest.is_dir() and marker.is_file() and marker.read_text().strip() == bundle.meta.bundle_hash:
        return dest
    tmp = Path(dest_root) / f".{tenant_id}.v{version}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        (tmp).mkdir(parents=True)
        (tmp / "manifest.toml").write_text(bundle.manifest_text, encoding="utf-8")
        for rel, content in bundle.files.items():
            p = tmp / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
        (tmp / _MARKER).write_text(bundle.meta.bundle_hash, encoding="utf-8")
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True); raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists(): shutil.rmtree(dest)
    os.replace(tmp, dest)
    return dest

def context_for_version(store, settings, tenant_id, version):
    key = (tenant_id, version)
    if key in _context_cache:
        return _context_cache[key]
    from noble_agent.tenant.loader import _context_from_dir
    d = materialize_version(store, tenant_id, version, settings.tenant_materialize_dir)
    ctx = _context_from_dir(tenant_id, d, is_materialized=True)
    _context_cache[key] = ctx
    return ctx
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/version_resolver.py tests/unit/tenant/test_version_resolver.py
git commit -m "feat(tenant): version_resolver.context_for_version + E04 checksum (SP-C2 t3)"
```

---

### Task 4: `version_resolver.current_published_version` (TTL cache + E01 fallback)

**Files:**
- Modify: `src/noble_agent/tenant/version_resolver.py`
- Test: `tests/unit/tenant/test_version_resolver.py`

**Interfaces:**
- Produces: `current_published_version(store, settings, tenant_id, *, clock=time.monotonic) -> int`
  - TTL cache (`settings.noble_config_poll_sec`) on the resolved int per tenant.
  - Reads `store.read_pointer(tenant_id)`; `None` → treat as legacy v1 (`store.read_meta` present) else `FileNotFoundError`.
  - Store raises → serve `_last_good[tenant_id]` if set (E01); else re-raise.
  - On success, set `_last_good[tenant_id] = v`.
- Also `reset_for_tests()` clearing `_context_cache` + `_ttl` + `_last_good`.

- [ ] **Step 1: Write the failing test**

```python
def test_current_version_ttl_and_refresh():
    VR.reset_for_tests()
    s = _store_with_v1()
    class _S: noble_config_poll_sec = 100.0; tenant_materialize_dir = "/x"
    t = [0.0]; clk = lambda: t[0]
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1
    s.write_pointer("tt", 2)               # publish v2
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1  # cached (TTL not elapsed)
    t[0] = 200.0
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 2  # refreshed

def test_current_version_store_down_uses_last_good():
    VR.reset_for_tests()
    s = _store_with_v1()
    class _S: noble_config_poll_sec = 0.0; tenant_materialize_dir = "/x"
    clk = lambda: 0.0
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1  # primes last_good
    def boom(t): raise RuntimeError("minio down")
    s.read_pointer = boom
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1  # E01: last_good
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement**

```python
import time
_ttl: dict[str, tuple[float, int]] = {}
_last_good: dict[str, int] = {}

def current_published_version(store, settings, tenant_id, *, clock=time.monotonic):
    now = clock(); hit = _ttl.get(tenant_id)
    if hit is not None and (now - hit[0]) < settings.noble_config_poll_sec:
        return hit[1]
    try:
        ptr = store.read_pointer(tenant_id)
        if ptr is None:
            if store.read_meta(tenant_id) is None:
                raise FileNotFoundError(f"tenant not in store: {tenant_id!r}")
            ptr = 1  # legacy in-place = v1
    except Exception:
        if tenant_id in _last_good:
            return _last_good[tenant_id]  # E01
        raise
    _ttl[tenant_id] = (now, ptr); _last_good[tenant_id] = ptr
    return ptr

def reset_for_tests():
    _context_cache.clear(); _ttl.clear(); _last_good.clear()
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/version_resolver.py tests/unit/tenant/test_version_resolver.py
git commit -m "feat(tenant): current_published_version TTL cache + E01 fallback (SP-C2 t4)"
```

---

### Task 5: Facade — version-keyed runner registry + resolve-and-pin at `create()`

**Files:**
- Modify: `src/noble_agent/agent/facade.py`
- Test: `tests/unit/unified/test_facade_version_pinning.py` (new)

**Interfaces:**
- `_build_runner_for_version(version:int) -> TurnRunner` — like `_build_runner` but builds `agent_def` from `context_for_version(store, settings, TENANT_ID, version)` instead of `get_tenant_context()`.
- `_get_runner_for_version(version:int) -> TurnRunner` — get-or-build into a capped `OrderedDict` `_runners` (maxlen 4; evicting a build-cache entry is safe — live conversations hold their own ref).
- `NobleAgent.create(session_id, customer=None)`:
  - store enabled AND tenant in store → `v = current_published_version(...)`; `runner = _get_runner_for_version(v)`; `NobleAgent(session_id, runner, version=v)`.
  - else (package mode / store disabled / tenant absent) → legacy `_get_runner()` path, `version=0`.
- `NobleAgent.__init__(..., version:int=0)` stores `self.pinned_version` (read by SP-D later). The instance holding `self._runner` for its lifetime IS the BR05 pin.

- [ ] **Step 1: Write the failing test** (BR05 pin + version-keyed build)

```python
# tests/unit/unified/test_facade_version_pinning.py
import asyncio, pytest
from noble_agent.agent import facade

class _FakeRunner:
    def __init__(self, v): self.v = v

@pytest.mark.asyncio
async def test_create_pins_version_and_reuses_runner(monkeypatch):
    facade._runners.clear()
    built = []
    async def fake_build(version): built.append(version); return _FakeRunner(version)
    monkeypatch.setattr(facade, "_build_runner_for_version", fake_build)
    monkeypatch.setattr(facade, "_resolve_current_version", lambda: 5)   # helper the facade uses
    a = await facade.NobleAgent.create("sess-A")
    assert a.pinned_version == 5 and a._runner.v == 5
    # a SECOND conversation at the same version reuses the cached runner (no rebuild)
    b = await facade.NobleAgent.create("sess-B")
    assert b._runner is a._runner and built == [5]
    # publish -> version 6; a NEW conversation gets v6, but 'a' keeps v5 (BR05)
    monkeypatch.setattr(facade, "_resolve_current_version", lambda: 6)
    c = await facade.NobleAgent.create("sess-C")
    assert c.pinned_version == 6 and a.pinned_version == 5 and a._runner.v == 5
```

(`_resolve_current_version()` = a thin facade helper wrapping `current_published_version(store, settings, TENANT_ID)` or returning `0` in legacy mode — patch point for the test.)

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — introduce `_runners: "OrderedDict[int, TurnRunner]"`, `_runner_locks: dict[int, asyncio.Lock]`, `_resolve_current_version()` (store-enabled → `current_published_version(...)`, else `0`), `_build_runner_for_version(v)` (copy `_build_runner` but swap the `get_tenant_context()` line for `context_for_version(...)`; keep everything else identical), `_get_runner_for_version(v)` (locked get-or-build + evict oldest when > 4). Rewrite `NobleAgent.create` + `__init__(version=0)` + set `self.pinned_version`. Keep the legacy `_get_runner`/`_build_runner`/`_runner_singleton` for the `version==0` path so store-disabled behavior is byte-identical. Keep `stream_response`, `reset`, etc. unchanged.

- [ ] **Step 4: Run → pass**, plus `pytest tests/unit/unified -q` for no facade regression.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/facade.py tests/unit/unified/test_facade_version_pinning.py
git commit -m "feat(agent): facade version-keyed runner registry + per-conversation pin (SP-C2 t5)"
```

---

### Task 6: Regression + back-compat + live re-smoke (verification)

**Files:** `src/noble_agent/SMOKE.md` (doc); fix-forward if red.

- [ ] **Step 1: Offline gate** — `pytest tests/unit/tenant tests/unit/unified tests/unit/gateway` → 0 failures (redirect to file, confirm). `ruff check src/noble_agent/tenant/ src/noble_agent/agent/facade.py` → clean.
- [ ] **Step 2: Store-disabled back-compat** — a test (or reasoned check) that with `tenant_store_enabled=False`, `NobleAgent.create` takes the legacy `_get_runner()` path (`pinned_version==0`, single runner) — behavior byte-identical to today.
- [ ] **Step 3: Live re-smoke** (services up per SMOKE.md; store enabled):
  - `python scripts/smoke_gateway_chat.py <tnt_...>` → PASS (loader/resolver serve published version).
  - Publish a v2 for `noble` (via a throwaway edit + `noble-tenant save-draft noble <dir> && noble-tenant publish noble`), then open a NEW chat session → confirm it reflects v2 within ~20s; a session opened before the publish keeps v1 (BR05 — observe via a persona marker or logged `pinned_version`).
  - `noble-tenant rollback noble 1` → new sessions revert.
- [ ] **Step 4: Update SMOKE.md** with an "SP-C2 version-pinned load" subsection.
- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/SMOKE.md tests/unit/
git commit -m "test(agent): SP-C2 regression + back-compat + smoke recipe (SP-C2 t6)"
```

---

## Self-Review

- **Spec coverage:** resolve-at-conversation-start + pin (Task 5, via instance lifetime) · TTL refresh YC03 (Task 4) · checksum E04 (Task 3) · disk-cache/last-good E01 (Task 3/4) · store-disabled back-compat (Task 5/6) · `NOBLE_CONFIG_POLL_SEC` (Task 2) · `_context_from_dir` reuse (Task 1). Spec §4.2's `_session_pin` map is intentionally replaced by instance-lifetime pinning (both transports create one `NobleAgent` per conversation — verified in facade/text_chat/voice_agent); the background poller is replaced by a TTL cache (simpler, same ≤20s guarantee) — noted as a refinement.
- **Placeholder scan:** none — every step has real test + impl code.
- **Type consistency:** `current_published_version → int`, `context_for_version → TenantContext`, `_get_runner_for_version(int) → TurnRunner`, `pinned_version:int` used consistently across Tasks 3–5. `materialize_version` raises `ChecksumError`/`FileNotFoundError` as used by tests.
- **Eviction safety:** `_runners` is a *build cache*; evicting an entry only forces a rebuild for a future conversation on that (old) version, which won't happen (new conversations use current) — live conversations hold their own runner ref, so BR05 is never violated by eviction.
- **Deferred (SP-D):** emitting `pinned_version` as a heartbeat — C2 only stores/exposes it.
