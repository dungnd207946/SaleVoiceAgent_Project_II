"""Regression: the asyncpg pool must not be reused across event loops.

LiveKit reuses a job subprocess but runs each job on its OWN event loop. A pool
created on a prior job's (now-closed) loop is unusable — ``pool.acquire()`` on a
closed loop raises ``RuntimeError: Event loop is closed``. ``get_pool`` must
detect the loop change and rebuild on the current loop (chat/aiortc is a single
long-lived loop, so it is unaffected either way).
"""

from __future__ import annotations

import asyncio
import sys
import types


def _fake_asyncpg(created: list, terminated: list):
    class _FakePool:
        def __init__(self, n):
            self.n = n

        def terminate(self):  # asyncpg's sync force-close
            terminated.append(self.n)

    async def create_pool(dsn, **kw):
        created.append(dsn)
        return _FakePool(len(created))

    mod = types.ModuleType("asyncpg")
    mod.create_pool = create_pool
    return mod


def test_get_pool_rebuilds_across_event_loops(monkeypatch):
    from noble_agent.storage import postgres_client as pc

    pc.set_pool_for_tests(None)  # reset all module globals
    created: list = []
    terminated: list = []
    monkeypatch.setitem(sys.modules, "asyncpg", _fake_asyncpg(created, terminated))

    async def _one():
        return await pc.get_pool("postgresql://fake")

    p1 = asyncio.run(_one())  # loop 1 — creates the pool, then loop closes
    assert created == ["postgresql://fake"]

    p2 = asyncio.run(_one())  # loop 2 — must NOT reuse the loop-1 pool

    assert len(created) == 2, "pool was not rebuilt on the new loop"
    assert terminated == [1], "stale pool was not force-closed"
    assert p2 is not p1

    pc.set_pool_for_tests(None)


def test_get_pool_reuses_within_one_loop(monkeypatch):
    from noble_agent.storage import postgres_client as pc

    pc.set_pool_for_tests(None)
    created: list = []
    terminated: list = []
    monkeypatch.setitem(sys.modules, "asyncpg", _fake_asyncpg(created, terminated))

    async def _twice():
        a = await pc.get_pool("postgresql://fake")
        b = await pc.get_pool("postgresql://fake")
        return a, b

    a, b = asyncio.run(_twice())
    assert a is b
    assert len(created) == 1, "pool rebuilt within the same loop"
    assert terminated == []

    pc.set_pool_for_tests(None)
