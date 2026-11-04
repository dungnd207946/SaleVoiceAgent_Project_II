# Plan 2 — Option C RLS Pooling (§6, O3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Depends on Plan 1** (`tenant/current.py` → `current_tenant()`). Do not start until Plan 1 Task 6 is merged.

**Goal:** Serve all tenants' Postgres reads/writes from **one shared app-role pool**, isolating them per-transaction with `set_config('app.current_tenant', <tenant>, true)` + an RLS policy on `current_setting` — so connection count stays flat at 200 tenants (O4) and a reused pooled connection can never leak one tenant's rows to the next (fail-closed).

**Architecture:** Add a **second** PERMISSIVE RLS policy `agent_runtime` (`current_setting('app.current_tenant', true)`) on each of the 3 tables, **keeping** the existing `tenant_isolation` policy (`current_user`) for Portal/admin per-tenant login roles (O5). Multiple PERMISSIVE policies OR together, and the two clauses route cleanly: the app role never matches `current_user` (its name ≠ any tenant_id) so only `current_setting` applies to it; Portal roles never set `app.current_tenant` (NULL) so only `current_user` applies to them. Runtime connects as one non-owner, non-superuser, **non-BYPASSRLS** app role; a `tenant_conn(pool, tenant_id)` helper opens a transaction, calls `set_config(..., true)` (txn-scoped, dies with the txn), and every DAO runs inside it. Tenant comes from `current_tenant()` (Plan 1), not `settings.tenant_id`.

**Tech Stack:** Postgres 16, asyncpg, RLS (`ENABLE`+`FORCE`), pytest (`needs_postgres` marker + live admin DSN).

## Global Constraints

- Branch `feat/agent`. **NO commit/push/PR** without explicit instruction. **Never `develop`.** (memo §10)
- **KEEP the `tenant_isolation` (`current_user`) policy unchanged** — Portal/admin still use per-tenant LOGIN roles (O5). Only ADD the `agent_runtime` policy. RLS stays **ENABLE + FORCE**. (memo §6, O5)
- **App role name MUST differ from every `tenant_id`** — else the `current_user` clause matches it by accident. Enforce + document in provisioning. (memo §6 "Bẫy phải tránh")
- **`set_config` must be `is_local = true`** (transaction-scoped). Never `SET ROLE`. Never string-interpolate the tenant into `SET` — use `SELECT set_config('app.current_tenant', $1, true)`. (memo §6.3)
- **Fail-closed:** app role with `app.current_tenant` unset → `current_setting('app.current_tenant', true)` = NULL → `tenant_id = NULL` → **0 rows**. (memo §6.1)
- **Keep `tenant_id` explicit in every query** as defense-in-depth (WITH CHECK catches a param vs `current_setting` mismatch). (memo §6.6)
- **Wrappers keep best-effort/E05 semantics** (PG down → no-op, don't fabricate). (memo §10)
- DDL is idempotent (`CREATE POLICY IF NOT EXISTS` isn't valid SQL → use `DROP POLICY IF EXISTS` then `CREATE`, in the existing `DO` loop). RLS policy change = **storage-schema change** → CLAUDE.md self-maintenance (Storage/Postgres section + Change Log, same commit). (memo §10)
- `make test-unit` baseline, 0 new; live gate via `SPE_PG_ADMIN_DSN`. (memo §9)

---

## File Structure

**Modified files:**
- `src/noble_agent/storage/sql/odyssey_data_plane.sql` — add the `agent_runtime` policy inside the existing `DO $$ ... LOOP` (lines 83-94).
- `src/noble_agent/tenant/pg_provisioning.py` — add `ensure_app_role(admin_dsn)` (one-time app role: non-login? no — app role LOGINs via the DSN, so LOGIN + password, non-owner/non-superuser/non-BYPASSRLS + CRUD grants), guard app-role name ≠ tenant.
- `src/noble_agent/storage/postgres_client.py` — add `tenant_conn(pool, tenant_id)` async context manager.
- `src/noble_agent/storage/pg_data_plane.py` — `_tenant_id()` → `current_tenant()`; every best-effort wrapper runs its DAO inside `tenant_conn`.
- `src/noble_agent/config.py` — add `POSTGRES_APP_ROLE` (default `odyssey_agent`) for provisioning/validation.
- `tests/integration/tenant/test_pg_rls_live.py` — add app-role SET LOCAL isolation, leak-on-reuse, fail-closed, and Portal-still-works cases.
- `tests/unit/storage/test_tenant_conn.py` (create) — unit test the helper's SQL/txn shape with a fake connection.

---

## Design contract

```python
# storage/postgres_client.py
@asynccontextmanager
async def tenant_conn(pool, tenant_id: str):
    """Acquire a pooled conn, open a txn, scope it to tenant_id via
    set_config('app.current_tenant', $1, true), yield the conn. The setting
    dies with the txn — no leak across connection reuse."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
            yield conn

# tenant/pg_provisioning.py
async def ensure_app_role(admin_dsn: str, *, role: str, password: str) -> None: ...
def assert_app_role_distinct(role: str, tenant_ids: Iterable[str]) -> None: ...

# storage/pg_data_plane.py
def _tenant_id() -> str:   # now returns current_tenant()
```

---

### Task 1: Add the `agent_runtime` RLS policy (DDL)

**Files:**
- Modify: `src/noble_agent/storage/sql/odyssey_data_plane.sql:83-94` (the `DO $$` RLS loop)
- Test: covered live in Task 6 (DDL has no unit surface).

- [ ] **Step 1: Edit the DDL loop**

Inside the existing `DO $$ ... FOREACH ... LOOP` over `ARRAY['conversations','appointments','contacts']`, keep the ENABLE/FORCE + `tenant_isolation` statements and ADD, after the `tenant_isolation` CREATE POLICY:

```sql
        DROP POLICY IF EXISTS agent_runtime ON tenant_data.%I;
        CREATE POLICY agent_runtime ON tenant_data.%I
            USING       (tenant_id = current_setting('app.current_tenant', true))
            WITH CHECK  (tenant_id = current_setting('app.current_tenant', true));
```

(Use the same `format(..., t, t)` / `%I` placeholder style already in the loop — one `%I` per table reference. Both policies are PERMISSIVE by default → they OR. `current_setting('app.current_tenant', true)` with `missing_ok=true` returns NULL when unset → fail-closed.)

- [ ] **Step 2: Sanity-check idempotency locally (if a PG is available)**

Run (against a scratch DB): apply the DDL twice; expect no error and exactly two policies per table.

```bash
psql "$SPE_PG_ADMIN_DSN" -f src/noble_agent/storage/sql/odyssey_data_plane.sql
psql "$SPE_PG_ADMIN_DSN" -f src/noble_agent/storage/sql/odyssey_data_plane.sql   # idempotent
psql "$SPE_PG_ADMIN_DSN" -c "SELECT tablename, policyname FROM pg_policies WHERE schemaname='tenant_data' ORDER BY 1,2;"
```
Expected: each of the 3 tables lists both `agent_runtime` and `tenant_isolation`.

- [ ] **Step 3: Commit**

```bash
git add src/noble_agent/storage/sql/odyssey_data_plane.sql
git commit -m "feat(rls): add agent_runtime policy (current_setting) alongside tenant_isolation (current_user)"
```

---

### Task 2: App-role provisioning (`tenant/pg_provisioning.py`)

**Files:**
- Modify: `src/noble_agent/tenant/pg_provisioning.py` — add `ensure_app_role`, `assert_app_role_distinct`; keep per-tenant `provision`/`deprovision` untouched (O5).
- Modify: `src/noble_agent/config.py` — add `postgres_app_role: str = Field("odyssey_agent", alias="POSTGRES_APP_ROLE")`.
- Test: `tests/unit/tenant/test_pg_provisioning.py` (extend — name-distinctness guard is unit-testable offline).

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/tenant/test_pg_provisioning.py  (add)
import pytest
from noble_agent.tenant import pg_provisioning as pp


def test_assert_app_role_distinct_rejects_collision():
    with pytest.raises(ValueError):
        pp.assert_app_role_distinct("acme", ["noble", "acme"])   # role == a tenant_id


def test_assert_app_role_distinct_ok():
    pp.assert_app_role_distinct("odyssey_agent", ["noble", "acme"])   # no raise


def test_app_role_name_validated_as_slug():
    with pytest.raises(ValueError):
        pp.assert_app_role_distinct("bad name!", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_pg_provisioning.py -k app_role -v`
Expected: FAIL — helpers don't exist.

- [ ] **Step 3: Implement**

Add to `pg_provisioning.py` (reuse the existing `_ROLE_RE` and `_pw_literal`):

```python
def assert_app_role_distinct(role: str, tenant_ids) -> None:
    """The shared runtime app role must be a valid slug AND differ from every
    tenant_id — else the current_user clause of tenant_isolation matches it by
    accident (memo §6 trap)."""
    if not _ROLE_RE.match(role):
        raise ValueError(f"invalid app role name: {role!r}")
    collisions = {t for t in tenant_ids if t == role}
    if collisions:
        raise ValueError(f"app role {role!r} collides with tenant id(s): {sorted(collisions)}")


async def ensure_app_role(admin_dsn: str, *, role: str, password: str) -> None:
    """Create (idempotently) the ONE shared runtime app role: LOGIN, non-owner,
    non-superuser, NOT BYPASSRLS (so RLS FORCE still binds it), with CRUD on the
    3 tables. Called once at bootstrap, NOT per tenant."""
    import asyncpg

    if not _ROLE_RE.match(role):
        raise ValueError(f"invalid app role name: {role!r}")
    pw = _pw_literal(password)
    conn = await asyncpg.connect(admin_dsn)
    try:
        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            if not exists:
                await conn.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD {pw} NOBYPASSRLS')
            await conn.execute(f'GRANT USAGE ON SCHEMA tenant_data TO "{role}"')
            await conn.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE '
                f'ON ALL TABLES IN SCHEMA tenant_data TO "{role}"'
            )
    finally:
        await conn.close()
```

Wire a CLI subcommand (mirror the existing `pg-provision` style) `noble-tenant pg-ensure-app-role` that reads `settings.postgres_app_role` + a `--password`, calls `assert_app_role_distinct(role, <existing tenant roles>)` then `ensure_app_role`. Add `postgres_app_role` to `config.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/tenant/test_pg_provisioning.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenant/pg_provisioning.py src/noble_agent/config.py tests/unit/tenant/test_pg_provisioning.py
git commit -m "feat(rls): provision one shared app role (non-BYPASSRLS, CRUD) + name-collision guard"
```

---

### Task 3: `tenant_conn` transaction helper (`storage/postgres_client.py`)

**Files:**
- Modify: `src/noble_agent/storage/postgres_client.py` — add `tenant_conn`.
- Test: `tests/unit/storage/test_tenant_conn.py` (create).

**Interfaces:**
- Produces: `tenant_conn(pool, tenant_id)` async context manager (see Design contract).

- [ ] **Step 1: Write the failing test (fake pool/conn, offline)**

```python
# tests/unit/storage/test_tenant_conn.py
import pytest


class _FakeTxn:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): self.conn.calls.append("BEGIN"); return self
    async def __aexit__(self, *a): self.conn.calls.append("COMMIT"); return False


class _FakeConn:
    def __init__(self): self.calls = []
    def transaction(self): return _FakeTxn(self)
    async def execute(self, sql, *args): self.calls.append((sql, args))


class _FakePool:
    def __init__(self, conn): self._conn = conn
    def acquire(self):
        conn = self._conn
        class _Acq:
            async def __aenter__(s): return conn
            async def __aexit__(s, *a): conn.calls.append("RELEASE"); return False
        return _Acq()


@pytest.mark.asyncio
async def test_tenant_conn_sets_config_in_txn():
    from noble_agent.storage.postgres_client import tenant_conn
    conn = _FakeConn()
    pool = _FakePool(conn)
    async with tenant_conn(pool, "acme") as c:
        assert c is conn
        c.calls.append("DAO")
    assert conn.calls[0] == "BEGIN"
    assert conn.calls[1] == ("SELECT set_config('app.current_tenant', $1, true)", ("acme",))
    assert "DAO" in conn.calls
    assert conn.calls[-2:] == ["COMMIT", "RELEASE"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/storage/test_tenant_conn.py -v`
Expected: FAIL — `tenant_conn` doesn't exist.

- [ ] **Step 3: Implement**

Add to `postgres_client.py` (top: `from contextlib import asynccontextmanager`):

```python
@asynccontextmanager
async def tenant_conn(pool, tenant_id: str):
    """Yield a pooled connection scoped to ``tenant_id`` for one transaction.

    Sets ``app.current_tenant`` with ``is_local=true`` so the RLS agent_runtime
    policy binds this txn to the tenant; the setting is reset when the txn ends,
    so a reused pooled connection never leaks the prior tenant's scope.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
            yield conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/storage/test_tenant_conn.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/storage/postgres_client.py tests/unit/storage/test_tenant_conn.py
git commit -m "feat(pg): tenant_conn helper — per-txn set_config('app.current_tenant', …, true)"
```

---

### Task 4: Route every DAO wrapper through `tenant_conn`; tenant from `current_tenant()`

**Files:**
- Modify: `src/noble_agent/storage/pg_data_plane.py:221-224` (`_tenant_id`), and each best-effort wrapper (`:227` `persist_contact` … `:385` `list_conversation_hints`).
- Test: `tests/unit/storage/test_pg_wrappers_use_tenant_conn.py` (create) — assert a wrapper runs its DAO on a `tenant_conn` connection with the current tenant.

**Interfaces:**
- Consumes: `tenant_conn` (Task 3), `current_tenant` (Plan 1).
- Note: the **core DAOs** (`upsert_contact`, `record_conversation`, `upsert_appointment`, …) already take `db` and execute on it — pass the `tenant_conn` connection as `db`. No DAO body change; `tenant_id` stays an explicit `$1` column (defense-in-depth).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/storage/test_pg_wrappers_use_tenant_conn.py
import pytest
from noble_agent.storage import pg_data_plane as dp


@pytest.mark.asyncio
async def test_read_contact_snapshot_scopes_to_current_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()

    seen = {}

    class _Conn:
        async def execute(self, sql, *a): pass
        async def fetchrow(self, sql, *a):
            seen["args"] = a
            return {"snapshot": "hi"}

    class _CM:
        def __init__(self, tid): seen["tenant"] = tid
        async def __aenter__(self): return _Conn()
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(dp, "_pool_or_none", lambda: object())
    monkeypatch.setattr(dp, "tenant_conn", lambda pool, tid: _CM(tid))

    with use_tenant("acme"):
        out = await dp.read_contact_snapshot("0900000000")
    assert out == "hi"
    assert seen["tenant"] == "acme"          # scoped to the request tenant, not settings
    assert seen["args"][0] == "acme"         # tenant_id still an explicit query arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/storage/test_pg_wrappers_use_tenant_conn.py -v`
Expected: FAIL — wrapper still runs the DAO directly on the pool with `settings.tenant_id`.

- [ ] **Step 3: Implement**

`_tenant_id()` (221-224):

```python
def _tenant_id() -> str:
    from noble_agent.tenant.current import current_tenant

    return current_tenant()
```

Import `tenant_conn` at module top: `from noble_agent.storage.postgres_client import tenant_conn` (keep it a module attribute so tests can monkeypatch `dp.tenant_conn`). Then in **each** best-effort wrapper, replace the "run DAO directly on `pool`" call with a `tenant_conn` block. Pattern (apply to all 8 wrappers — `persist_contact`, `read_contact_snapshot`, `persist_customer_profile`, `read_customer_profile`, `persist_appointment`, `read_latest_booking_hint`, `persist_conversation`, `list_conversation_hints`):

Before:
```python
    pool = _pool_or_none()
    if pool is None:
        return DEFAULT
    tid = _tenant_id()
    try:
        return await some_dao(pool, tenant_id=tid, ...)
    except Exception:
        logger.warning(..., exc_info=True)
        return DEFAULT
```

After:
```python
    pool = _pool_or_none()
    if pool is None:
        return DEFAULT
    tid = _tenant_id()
    try:
        async with tenant_conn(pool, tid) as conn:
            return await some_dao(conn, tenant_id=tid, ...)
    except Exception:
        logger.warning(..., exc_info=True)
        return DEFAULT
```

(Keep every wrapper's existing no-op default and field mapping — e.g. `persist_appointment`'s `booking["project"]→project_code`, `read_latest_booking_hint`'s `project_code→project`. Only the execution seam changes: DAO now runs on `conn` inside the tenant-scoped txn instead of on the bare `pool`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/storage/test_pg_wrappers_use_tenant_conn.py tests/unit/ -k "pg or contact or booking or conversation or snapshot" -v`
Expected: PASS — existing pg wrapper unit tests (they use fake pools) still green; the new tenant-scoping test passes.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/storage/pg_data_plane.py tests/unit/storage/test_pg_wrappers_use_tenant_conn.py
git commit -m "feat(pg): run DAO wrappers inside tenant_conn; tenant from current_tenant()"
```

---

### Task 5: Point the runtime DSN at the app role (config + docs)

**Files:**
- Modify: `.env.example` — document `POSTGRES_DSN` now = the **shared app role** (not a per-tenant role); `POSTGRES_ADMIN_DSN` = provisioning superuser; new `POSTGRES_APP_ROLE`.
- Modify: `src/noble_agent/config.py` — confirm `postgres_app_role` present (Task 2) and comment the `POSTGRES_DSN` field to say "shared app role, RLS-scoped per txn".
- Test: none (documentation/config; behavior covered live in Task 6).

- [ ] **Step 1: Edit `.env.example` + config comment**

Add/adjust:
```
# Runtime PG connection — the SHARED app role (non-owner, non-superuser,
# NOT BYPASSRLS). RLS agent_runtime policy scopes each txn via set_config.
POSTGRES_DSN=postgresql://odyssey_agent:...@host:5432/odyssey
# Provisioning superuser (off the turn path) — apply schema, create roles.
POSTGRES_ADMIN_DSN=postgresql://postgres:...@host:5432/odyssey
# Shared app role name — MUST differ from every tenant_id.
POSTGRES_APP_ROLE=odyssey_agent
```

- [ ] **Step 2: Commit**

```bash
git add .env.example src/noble_agent/config.py
git commit -m "docs(pg): POSTGRES_DSN = shared app role; document POSTGRES_APP_ROLE"
```

---

### Task 6: Live RLS gate — isolation, leak-on-reuse, fail-closed, Portal-still-works (§9)

**Files:**
- Modify: `tests/integration/tenant/test_pg_rls_live.py` — add app-role cases (guarded by `SPE_PG_ADMIN_DSN`, `needs_postgres`).

**Interfaces:**
- Consumes: `ensure_app_role` (Task 2), `tenant_conn` (Task 3), the DDL (Task 1), `apply_schema`/`provision`/`deprovision` (existing).

- [ ] **Step 1: Write the live tests**

Extend the existing file (reuse its `provisioned` fixture, `_tenant_dsn`, `TA`/`TB`). Add:

```python
# tests/integration/tenant/test_pg_rls_live.py  (add)
import asyncpg
import pytest
from noble_agent.tenant.pg_provisioning import ensure_app_role
from noble_agent.storage.postgres_client import tenant_conn

APP_ROLE = "spe_app_role"      # distinct from spe_probe_a / spe_probe_b
APP_PW = "app_pw"


def _app_dsn(admin, role, pw):
    # same swap helper shape as _tenant_dsn
    head, tail = admin.split("://", 1)
    _cred, hostpart = tail.split("@", 1)
    return f"{head}://{role}:{pw}@{hostpart}"


@pytest.mark.needs_postgres
@pytest.mark.asyncio
async def test_app_role_set_local_isolation_and_leak(provisioned):
    await ensure_app_role(ADMIN, role=APP_ROLE, password=APP_PW)
    pool = await asyncpg.create_pool(_app_dsn(ADMIN, APP_ROLE, APP_PW), min_size=1, max_size=1)  # size 1 forces reuse
    try:
        # A writes its own row
        async with tenant_conn(pool, TA) as c:
            await c.execute(
                "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1,$2)", TA, "s-a"
            )
        # WITH CHECK: A cannot write a row tagged B
        with pytest.raises(asyncpg.PostgresError):
            async with tenant_conn(pool, TA) as c:
                await c.execute(
                    "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1,$2)", TB, "s-x"
                )
        # LEAK-ON-REUSE (the critical one): same pooled conn, now scoped to B,
        # sees ZERO of A's rows.
        async with tenant_conn(pool, TB) as c:
            n = await c.fetchval("SELECT count(*) FROM tenant_data.conversations")
            assert n == 0
        # A re-scoped sees exactly its own row
        async with tenant_conn(pool, TA) as c:
            n = await c.fetchval("SELECT count(*) FROM tenant_data.conversations")
            assert n == 1
    finally:
        await pool.close()


@pytest.mark.needs_postgres
@pytest.mark.asyncio
async def test_app_role_fail_closed_when_unset(provisioned):
    await ensure_app_role(ADMIN, role=APP_ROLE, password=APP_PW)
    conn = await asyncpg.connect(_app_dsn(ADMIN, APP_ROLE, APP_PW))
    try:
        # No set_config → app.current_tenant NULL → 0 rows (fail-closed)
        n = await conn.fetchval("SELECT count(*) FROM tenant_data.conversations")
        assert n == 0
    finally:
        await conn.close()


# Portal path (per-tenant login role via current_user) MUST still work — the
# existing test_rls_cross_tenant_isolation covers this; keep it green.
```

(If `ensure_app_role` GRANTs need re-running after `provision` creates tables, call `apply_schema`/`ensure_app_role` order so `GRANT ON ALL TABLES` sees the tables. The `provisioned` fixture already `apply_schema`s first.)

- [ ] **Step 2: Run the live suite**

Run: `SPE_PG_ADMIN_DSN=postgresql://postgres:...@localhost:5432/odyssey pytest tests/integration/tenant/test_pg_rls_live.py -v -m needs_postgres`
Expected: PASS — new app-role isolation/leak/fail-closed cases + the existing `test_rls_cross_tenant_isolation` (Portal `current_user` path) all green.

- [ ] **Step 3: Full unit gate + lint**

Run: `make test-unit && make lint`
Expected: baseline pass, 0 new; ruff clean on touched files.

- [ ] **Step 4: Update CLAUDE.md (self-maintenance — storage-schema change)**

Edit the **Storage → Postgres** section: RLS now has TWO policies per table (`tenant_isolation` on `current_user` for Portal/admin per-tenant roles; `agent_runtime` on `current_setting('app.current_tenant', true)` for the shared runtime app role), runtime connects as one app role and scopes each txn via `tenant_conn`/`set_config`, and `_tenant_id()` reads `current_tenant()`. Append a Change Log row (same commit).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/tenant/test_pg_rls_live.py CLAUDE.md
git commit -m "test(rls): live app-role SET LOCAL isolation + leak-on-reuse + fail-closed; CLAUDE.md sync"
```

---

## Self-Review

**Spec coverage (memo §6):**
- Second PERMISSIVE `agent_runtime` policy, keep `tenant_isolation` (O5): Task 1. ✅
- App role: non-owner/non-superuser/NOT BYPASSRLS + CRUD, one-time not per-tenant, name ≠ tenant: Task 2. ✅
- `set_config(..., $1, true)` per txn, no `SET` interpolation: Tasks 3. ✅
- `tenant_conn` helper wrapping every DAO: Tasks 3, 4. ✅
- `_tenant_id()` → contextvar: Task 4. ✅
- `tenant_id` explicit in queries (defense-in-depth): kept — DAO bodies unchanged (Task 4 note). ✅
- Per-tenant Portal role kept (O5): Task 2 leaves `provision`/`deprovision` untouched; Task 6 asserts it still works. ✅
- §9 gates — isolation, **leak-on-reuse**, fail-closed, Portal-still-works: Task 6. ✅

**Placeholder scan:** real SQL + real asyncpg code throughout. ✅

**Type consistency:** `tenant_conn(pool, tenant_id)`, `ensure_app_role(admin_dsn, *, role, password)`, `assert_app_role_distinct(role, tenant_ids)`, `_tenant_id() -> str` consistent across Tasks 2/3/4/6. ✅

**Latency note (memo §6):** +1 `set_config` per txn on the 2 critical-path spots (bootstrap reads + booking persist) — sub-ms to a few ms, negligible; the real risk being closed is isolation correctness, verified by the leak-on-reuse test.
