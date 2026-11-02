from noble_agent.agent.rag import noble_kb


async def test_dispatch_routes_to_kb_service(monkeypatch):
    called: dict = {}

    async def fake_query(query, project_filter, top_k=5, dinh_kem=None, du_an=None, numbers=None):
        called["args"] = (query, project_filter, top_k)
        called["dinh_kem"] = dinh_kem
        called["du_an"] = du_an
        return "CTX"

    # noble_kb imports the adapter lazily inside _query_via_kb_service; patch the
    # module attribute the branch calls.
    import noble_agent.agent.rag.kb_service_adapter as ad

    monkeypatch.setattr(ad, "query_kb_service_for_noble_kb", fake_query)
    monkeypatch.setattr(noble_kb.settings, "noble_rag_backend", "kb_service")
    monkeypatch.setattr(noble_kb.settings, "kb_search_top_k", 9)

    out = await noble_kb.query_noble_kb("tiện ích", "NCLB")
    assert out == "CTX"
    assert called["args"] == ("tiện ích", "NCLB", 9)


async def test_dispatch_kb_service_degrades_on_error(monkeypatch):
    async def boom(query, project_filter, top_k=5):
        raise RuntimeError("service down")

    import noble_agent.agent.rag.kb_service_adapter as ad

    monkeypatch.setattr(ad, "query_kb_service_for_noble_kb", boom)
    monkeypatch.setattr(noble_kb.settings, "noble_rag_backend", "kb_service")

    out = await noble_kb.query_noble_kb("tiện ích", "NCLB")
    assert out == ""
