"""Async Postgres pool for the SP-E Odyssey data plane (Option C — shared app-role pooling).

The runtime connects as ONE shared app role (``POSTGRES_DSN``), not a per-tenant
role. Per-tenant isolation is enforced per-transaction: ``tenant_conn`` issues
``set_config('app.current_tenant', <tenant_id>, true)`` on the connection, and the
``agent_runtime`` RLS policy on ``tenant_data.*`` matches rows against
``current_setting('app.current_tenant', true)`` — fail-closed, so an unset GUC
(e.g. bypassing ``tenant_conn``) yields zero rows rather than another tenant's.
``asyncpg`` is imported lazily so unit collection stays offline when
``POSTGRES_ENABLED`` is false.

Provisioning (schema apply + CREATE ROLE) uses a separate admin DSN and its own
short-lived connection — see ``tenant/pg_provisioning.py`` — never this pool.

When a worker has received a per-tenant runtime credential from the gateway
(``storage/tenant_credentials.py``), ``pool_for_tenant`` builds a SEPARATE pool
logged in as that tenant's own role instead of the shared app role — isolation
then rests on the DB login identity itself, not only on ``tenant_conn``'s
``set_config`` + RLS. The shared ``get_pool()`` pool remains the fallback for
sessions without a credential (dev/REPL/voice/heartbeat) and stays otherwise
unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

logger = logging.getLogger("noble_agent.storage.postgres")

_pool: Any = None
# The event loop ``_pool`` was created on. A pool (and asyncio primitives) bound
# to one loop cannot be used from another. Chat/aiortc runs a single long-lived
# loop, but LiveKit reuses a job subprocess and runs each job on its OWN loop, so
# a pool cached from a prior job is bound to a now-closed loop → ``get_pool``
# must rebuild when the running loop differs. ``None`` = externally injected
# (``set_pool_for_tests``) → trusted, never rebuilt.
_pool_loop: asyncio.AbstractEventLoop | None = None
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_lock(running: asyncio.AbstractEventLoop) -> asyncio.Lock:
    """Return an ``asyncio.Lock`` bound to the CURRENT loop.

    A module-global ``asyncio.Lock`` binds to the first loop it's awaited on and
    raises "bound to a different event loop" if reused from another — fatal on
    the LiveKit per-job-loop path. Recreate it whenever the loop changes. This
    helper is fully synchronous (no ``await``), so within one loop it can't be
    interleaved between the loop-check and the reassignment.
    """
    global _lock, _lock_loop
    if _lock is None or _lock_loop is not running:
        _lock = asyncio.Lock()
        _lock_loop = running
    return _lock


async def get_pool(dsn: str | None = None) -> Any:
    """Return a singleton asyncpg pool on the shared runtime app-role DSN.

    Tenant isolation is NOT tied to this DSN/connection identity — it is enforced
    per-transaction by ``tenant_conn`` (see below) via ``set_config`` + RLS.

    Loop-aware: a pool bound to a different (or closed) event loop is force-closed
    and rebuilt on the current loop, so the LiveKit voice path (which reuses a job
    subprocess across per-job loops) never serves a pool bound to a closed loop.

    Raises ``RuntimeError`` if no DSN is configured (fail loud — Postgres is
    required for the Odyssey data plane).
    """
    global _pool, _pool_loop
    running = asyncio.get_running_loop()

    # Fast path: reuse a pool that is externally injected (``_pool_loop is None``)
    # or was built on THIS still-open loop.
    if _pool is not None and (_pool_loop is None or (_pool_loop is running and not running.is_closed())):
        return _pool

    async with _get_lock(running):
        if _pool is not None and (_pool_loop is None or (_pool_loop is running and not running.is_closed())):
            return _pool
        if _pool is not None:
            # Stale pool bound to a different/closed loop. ``terminate()`` is
            # synchronous, so it force-closes without awaiting the dead loop.
            with contextlib.suppress(Exception):
                _pool.terminate()
            _pool = None
            _pool_loop = None
        import asyncpg  # lazy: keep unit collection offline

        from noble_agent.config import get_settings

        dsn = dsn or get_settings().postgres_dsn
        if not dsn:
            raise RuntimeError("POSTGRES_DSN not set — Odyssey data plane requires Postgres")
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
        _pool_loop = running
        logger.info("postgres: runtime pool connected")
    return _pool


@asynccontextmanager
async def tenant_conn(pool, tenant_id: str):
    """Yield a pooled connection scoped to ``tenant_id`` for one transaction.

    Sets BOTH ``app.current_tenant`` (agent-owned data-plane RLS) and
    ``app.tenant_id`` (Portal-owned control-plane RLS) with ``is_local=true``
    so RLS policies bind this txn to the tenant; the settings are reset when
    the txn ends, so a reused pooled connection never leaks the prior tenant's scope.
    """
    async with pool.acquire() as conn:  # noqa: SIM117 — nested acquire/txn is intentional
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            yield conn


async def healthcheck(dsn: str | None = None) -> bool:
    """True if a ``SELECT 1`` succeeds on the runtime pool (E05 probe)."""
    try:
        pool = await get_pool(dsn)
        async with pool.acquire() as conn:
            return (await conn.fetchval("SELECT 1")) == 1
    except Exception:
        logger.warning("postgres: healthcheck failed", exc_info=True)
        return False


async def close_pool() -> None:
    global _pool, _pool_loop
    if _pool is not None:
        await _pool.close()
        _pool = None
        _pool_loop = None


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


async def  pool_for_tenant(tenant_id: str) -> Any:
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


def set_pool_for_tests(pool: Any) -> None:
    global _pool, _pool_loop
    _pool = pool
    # ``None`` loop marks the pool as externally injected → ``get_pool`` trusts
    # it and never rebuilds (also resets state between tests when pool is None).
    _pool_loop = None
