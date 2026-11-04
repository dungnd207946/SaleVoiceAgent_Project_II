"""Per-job voice heartbeat (db-mode) — the fork-safe replacement for the
main-process supervisor on the LiveKit path.

``run_job_heartbeat`` runs INSIDE the LiveKit job subprocess (where the call's
tenant is known and ``get_pool()`` binds to the session loop), beating that one
tenant for the call's lifetime. This is the fix for the ActiveTenantTracker
cross-process gap: the subprocess no longer depends on a main-process
supervisor seeing its ``mark_active``.
"""

from __future__ import annotations

import asyncio

from noble_agent.tenant.pg_heartbeat import run_job_heartbeat


class _FakeWriter:
    def __init__(self) -> None:
        self.beats: list[str] = []

    async def beat(self, tenant_id: str) -> bool:
        self.beats.append(tenant_id)
        return True


async def test_run_job_heartbeat_beats_once_immediately_then_stops():
    """A short call (stop set right away) still records at least one beat —
    the loop beats before it first waits on the interval."""
    w = _FakeWriter()
    stop = asyncio.Event()
    stop.set()  # stop before the first interval wait
    await run_job_heartbeat("acme", "voice", "1.0", interval=100.0, stop_event=stop, writer=w)
    assert w.beats == ["acme"]


async def test_run_job_heartbeat_beats_repeatedly_until_stop():
    w = _FakeWriter()
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_job_heartbeat("acme", "voice", "1.0", interval=0.01, stop_event=stop, writer=w)
    )
    await asyncio.sleep(0.035)
    stop.set()
    await task
    assert len(w.beats) >= 2
    assert set(w.beats) == {"acme"}


async def test_run_job_heartbeat_swallows_writer_errors():
    """A beat failure must not kill the per-job loop (best-effort)."""

    class _Boom:
        def __init__(self) -> None:
            self.calls = 0

        async def beat(self, tenant_id: str) -> bool:
            self.calls += 1
            raise RuntimeError("db down")

    w = _Boom()
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_job_heartbeat("acme", "voice", "1.0", interval=0.01, stop_event=stop, writer=w)
    )
    await asyncio.sleep(0.035)
    stop.set()
    await task
    assert w.calls >= 2  # kept looping despite raising every time
