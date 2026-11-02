"""Heartbeat ghi control.agent_heartbeats (db-mode). Beat theo tenant đang có
kết nối (ActiveTenantTracker) vì role agent không enumerate control.tenants.

KHOÁ THEO `tenant_id` từ Portal `0941` — `control.deployments` đã bị DROP và cột
`agent_heartbeats.deployment_id` đã bỏ. Hệ quả: hai pod (chat/voice) của cùng một
tenant nay ĐÈ lên nhau thay vì nằm hai hàng. Portal vốn đã đọc hàng `last_seen_at`
mới nhất nên màn hình không đổi.

⚠️ NHỊP TIM CHẾT SUỐT `0919`→`0941`, và không test nào bắt được. Bản cũ chỉ dùng pool
tenant khi `cred.kind == self._kind`, mà `kind` biến mất khỏi response
`/runtime-credentials` ở `0919` ⇒ `cred.kind` luôn `''` ⇒ luôn rơi xuống nhánh
`SELECT control.deployments` bằng role `agent_<tenant>` — role không có SELECT ở đó.
Mọi bài test đều TIÊM `read_deployment_id` giả nên đường thật chưa từng chạy. Contract:
docs/handoff/agent-postgres-read-contract.md §1.4/§2."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

logger = logging.getLogger(__name__)

__all__ = [
    "ActiveTenantTracker",
    "mark_active",
    "TRACKER",
    "PgHeartbeatWriter",
    "PgHeartbeatSupervisor",
    "run_job_heartbeat",
]


class ActiveTenantTracker:
    """Track tenants with live conversations, filtered by TTL.

    Used to decide which tenants the agent should emit heartbeats for,
    since the agent role cannot enumerate all provisioned tenants.

    Process model: this tracker is a module-global, so ``mark_active`` and a
    ``PgHeartbeatSupervisor`` only see each other's updates when they run in the
    SAME process. That holds for **chat** (aiortc, single-process): both
    ``NobleAgent.create`` (which calls ``mark_active``) and the supervisor run
    in the one server process, so the supervisor beats every tenant with a live
    chat.

    **Voice/LiveKit does NOT use this tracker.** LiveKit forks a subprocess per
    job, so ``mark_active`` (job subprocess) and a main-process supervisor would
    live in different processes with different module-global ``TRACKER``
    instances. Instead the voice path runs a fork-safe **per-job** heartbeat
    (:func:`run_job_heartbeat`) INSIDE the job subprocess/entrypoint, beating
    that call's tenant for its lifetime — so no cross-process tracking is
    needed. See ``transport/livekit/worker.py::_start_job_heartbeat``. The
    legacy MinIO heartbeat (``tenant/heartbeat.py``'s supervisor) is
    process-independent (it enumerates ``store.list_ids()``) and unaffected.
    """

    def __init__(self, ttl_sec: float, *, clock=time.monotonic):
        self._ttl = ttl_sec
        self._clock = clock
        self._seen: dict[str, float] = {}

    def mark(self, tenant_id: str) -> None:
        """Mark a tenant as having an active conversation."""
        self._seen[tenant_id] = self._clock()

    def active(self) -> list[str]:
        """Return list of tenants with active conversations within TTL.

        Also purges expired entries from ``_seen`` so it doesn't grow
        unbounded over the process lifetime.
        """
        now = self._clock()
        expired = [t for t, ts in self._seen.items() if (now - ts) >= self._ttl]
        for t in expired:
            del self._seen[t]
        return list(self._seen.keys())


TRACKER = ActiveTenantTracker(120.0)


def mark_active(tenant_id: str) -> None:
    """Mark a tenant as active (called by NobleAgent.create in db-mode).

    Writes to the module-global ``TRACKER`` in THIS process only. This feeds the
    **chat** (aiortc, single-process) ``PgHeartbeatSupervisor``, where caller and
    supervisor share a process. The **voice/LiveKit** path does not rely on this
    (fork-per-job) — it uses :func:`run_job_heartbeat` inside the job subprocess
    instead. See the process-model note on ``ActiveTenantTracker``.
    """
    TRACKER.mark(tenant_id)


_UPSERT = """
INSERT INTO control.agent_heartbeats
  (tenant_id, running_version, bundle_sha, agent_version, last_error, last_seen_at)
VALUES ($1,$2,$3,$4,$5, now())
ON CONFLICT (tenant_id) DO UPDATE
SET running_version=EXCLUDED.running_version, bundle_sha=EXCLUDED.bundle_sha,
    agent_version=EXCLUDED.agent_version, last_error=EXCLUDED.last_error, last_seen_at=now()
"""


class PgHeartbeatWriter:
    """Upsert heartbeat row to control.agent_heartbeats."""

    def __init__(
        self,
        kind: str,
        agent_version: str,
        *,
        pool=None,
        read_published=None,
    ):
        self._kind = kind
        self._agent_version = agent_version
        self._pool = pool
        if read_published is None:
            from noble_agent.storage.agent_config_store import read_published_config as _read_published

            read_published = _read_published
        self._read_pub = read_published

    async def _pool_(self):
        if self._pool is not None:
            return self._pool
        from noble_agent.storage.postgres_client import get_pool

        return await get_pool()

    async def beat(self, tenant_id: str) -> bool:
        """Emit heartbeat for tenant. False if skipped or error.

        Pool chọn theo credential per-tenant (worker đã nhận từ gateway): có credential
        ⇒ `pool_for_tenant` (role `agent_<tenant>`, đã được GRANT INSERT trên
        `control.agent_heartbeats` + SELECT `tenant_data.agent_config` — verify live
        2026-08-10). Không có ⇒ pool dùng chung.

        ĐIỀU KIỆN `cred.kind == self._kind` ĐÃ BỎ (`0941`): `kind` không còn trong
        response `/runtime-credentials` từ `0919`, nên nó luôn rỗng và phép so đó không
        bao giờ đúng — đó chính là thứ giữ nhịp tim chết. Không còn nhánh dự phòng nào:
        `tenant_id` là thứ duy nhất cần, và caller luôn có nó.
        """
        try:
            from noble_agent.storage import tenant_credentials

            if tenant_credentials.get(tenant_id) is not None:
                from noble_agent.storage.postgres_client import pool_for_tenant

                pool = await pool_for_tenant(tenant_id)
            else:
                pool = await self._pool_()
            pc = await self._read_pub(tenant_id, pool=pool)
            running = pc.version if pc is not None else None
            from noble_agent.storage.postgres_client import tenant_conn

            async with tenant_conn(pool, tenant_id) as conn:
                await conn.execute(_UPSERT, tenant_id, running, "", self._agent_version, "")
            return True
        except Exception:
            logger.warning("heartbeat: pg beat failed for %s", tenant_id, exc_info=True)
            return False


class PgHeartbeatSupervisor:
    """Beats every tenant in ``ActiveTenantTracker.active()`` every ``interval``.

    Unlike the MinIO ``HeartbeatSupervisor`` (which enumerates all provisioned
    tenants from the store), the agent role has no way to enumerate
    ``control.tenants`` — so this beats whichever tenants have a live
    conversation (tracked via ``mark_active``) instead.

    Used by the **chat** transport only (aiortc, single-process), where caller
    and supervisor share the process so the module-global tracker works. The
    **voice** transport uses :func:`run_job_heartbeat` per-job instead (LiveKit
    fork-per-job breaks the shared-process assumption).
    """

    def __init__(
        self,
        kind: str,
        agent_version: str,
        interval: float,
        *,
        tracker: ActiveTenantTracker = TRACKER,
        writer=None,
    ):
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


async def run_job_heartbeat(
    tenant_id: str,
    kind: str,
    agent_version: str,
    interval: float,
    stop_event: asyncio.Event,
    *,
    writer=None,
) -> None:
    """Beat a single tenant for the lifetime of one connection (fork-safe).

    Runs INSIDE the process that owns the connection — for voice that is the
    LiveKit job subprocess (``entrypoint``), the only place that knows the
    call's tenant and where ``get_pool()`` binds to the session loop. Beats
    ``tenant_id`` immediately (so even a short call records ≥1 heartbeat), then
    every ``interval`` seconds until ``stop_event`` is set (the entrypoint sets
    it when the call ends). Best-effort: a failed beat is logged and the loop
    continues; stopping is the honest "disconnected" signal (a stale
    ``last_seen_at`` → Dashboard infers E02 after the freshness window).
    """
    w = writer or PgHeartbeatWriter(kind, agent_version)
    logger.info("pg-heartbeat (per-job): started tenant=%s kind=%s interval=%.0fs", tenant_id, kind, interval)
    try:
        # Beat-first (do-while): guarantees ≥1 heartbeat even for a call that
        # ends before the first interval elapses.
        while True:
            with contextlib.suppress(Exception):
                await w.beat(tenant_id)
            if stop_event.is_set():
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            if stop_event.is_set():
                break
    finally:
        logger.info("pg-heartbeat (per-job): stopped tenant=%s", tenant_id)
