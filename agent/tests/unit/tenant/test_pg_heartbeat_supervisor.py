import asyncio

from noble_agent.tenant.pg_heartbeat import TRACKER, ActiveTenantTracker, PgHeartbeatSupervisor, mark_active


async def test_supervisor_beats_active_tenants():
    tr = ActiveTenantTracker(60, clock=lambda: 0.0)
    tr.mark("a")
    tr.mark("b")
    beaten = []

    class _W:
        async def beat(self, tid):
            beaten.append(tid)
            return True

    sup = PgHeartbeatSupervisor("chat", "1.0", interval=0.01, tracker=tr, writer=_W())
    stop = asyncio.Event()
    task = asyncio.create_task(sup.run(stop))
    await asyncio.sleep(0.03)
    stop.set()
    await task
    assert set(beaten) >= {"a", "b"}


async def test_supervisor_uses_default_module_global_tracker_same_process():
    """Pins the same-process contract: mark_active() and a supervisor built with

    no injected tracker (the default ``TRACKER`` module-global) must see each
    other's updates. This is the invariant the voice/LiveKit fork-per-job path
    violates (see the "KNOWN GAP" note on ``ActiveTenantTracker``) — this test
    documents what's supposed to happen when caller and supervisor DO share a
    process, which is the case for chat (aiortc, single-process).
    """
    TRACKER._seen.clear()
    try:
        mark_active("same-process-tenant")
        beaten = []

        class _W:
            async def beat(self, tid):
                beaten.append(tid)
                return True

        sup = PgHeartbeatSupervisor("chat", "1.0", interval=0.01, writer=_W())  # default tracker=TRACKER
        stop = asyncio.Event()
        task = asyncio.create_task(sup.run(stop))
        await asyncio.sleep(0.03)
        stop.set()
        await task
        assert "same-process-tenant" in beaten
    finally:
        TRACKER._seen.clear()
