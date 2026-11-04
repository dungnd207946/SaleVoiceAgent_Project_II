"""The noble-rag-sync CLI parses --renew-graph and forwards it to the KG build."""

from __future__ import annotations

import sys

from noble_agent.agent.rag import sparse_reconcile


def test_main_default_is_incremental(monkeypatch):
    seen = {}

    async def fake_sync(*, renew_graph):
        seen["renew"] = renew_graph

    monkeypatch.setattr(sparse_reconcile, "_sync_and_build_graph", fake_sync)
    monkeypatch.setattr(sys, "argv", ["noble-rag-sync"])
    sparse_reconcile.main()
    assert seen["renew"] is False


def test_main_renew_graph_flag(monkeypatch):
    seen = {}

    async def fake_sync(*, renew_graph):
        seen["renew"] = renew_graph

    monkeypatch.setattr(sparse_reconcile, "_sync_and_build_graph", fake_sync)
    monkeypatch.setattr(sys, "argv", ["noble-rag-sync", "--renew-graph"])
    sparse_reconcile.main()
    assert seen["renew"] is True


async def test_sync_builds_graph_after_reconcile(monkeypatch):
    order = []

    async def fake_reconcile():
        order.append("reconcile")
        return 5

    async def fake_run_sync(*, renew):
        order.append(f"build:{renew}")
        return 3

    monkeypatch.setattr(sparse_reconcile, "reconcile", fake_reconcile)
    from noble_agent.agent.rag.hipporag import builder

    monkeypatch.setattr(builder, "run_sync", fake_run_sync)

    await sparse_reconcile._sync_and_build_graph(renew_graph=True)
    assert order == ["reconcile", "build:True"]
