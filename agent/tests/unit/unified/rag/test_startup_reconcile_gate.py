from noble_agent.server import http as srv


async def test_reconcile_runs_only_for_qdrant_backend(monkeypatch):
    calls = {"n": 0}

    async def fake_reconcile():
        calls["n"] += 1
        return 5

    monkeypatch.setattr("noble_agent.agent.rag.sparse_reconcile.reconcile", fake_reconcile)

    monkeypatch.setattr(srv.settings, "noble_rag_backend", "flat_store")
    await srv._maybe_reconcile_qdrant()
    assert calls["n"] == 0

    monkeypatch.setattr(srv.settings, "noble_rag_backend", "qdrant")
    await srv._maybe_reconcile_qdrant()
    assert calls["n"] == 1


async def test_reconcile_error_does_not_raise(monkeypatch):
    async def boom():
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr("noble_agent.agent.rag.sparse_reconcile.reconcile", boom)
    monkeypatch.setattr(srv.settings, "noble_rag_backend", "qdrant")
    await srv._maybe_reconcile_qdrant()  # must not raise


async def test_reconcile_timeout_does_not_wedge(monkeypatch):
    async def hang():
        import asyncio

        await asyncio.sleep(10)

    monkeypatch.setattr("noble_agent.agent.rag.sparse_reconcile.reconcile", hang)
    monkeypatch.setattr(srv.settings, "noble_rag_backend", "qdrant")
    monkeypatch.setattr(srv.settings, "qdrant_reconcile_timeout_sec", 0.01)
    await srv._maybe_reconcile_qdrant()  # must return promptly, not raise, not hang
