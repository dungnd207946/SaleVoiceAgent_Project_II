from noble_agent.agent.rag import noble_kb


async def test_backend_qdrant_routes_to_qdrant_adapter(monkeypatch):
    monkeypatch.setattr(noble_kb.settings, "noble_rag_backend", "qdrant")
    called = {}

    async def _fake(query, project_filter, top_k=5):
        called["args"] = (query, project_filter)
        return "QDRANT_RESULT"

    monkeypatch.setattr(
        "noble_agent.agent.rag.qdrant_adapter.query_qdrant_for_noble_kb",
        _fake,
    )
    out = await noble_kb.query_noble_kb("giá căn hộ", "NCLB")
    assert out == "QDRANT_RESULT"
    assert called["args"][0] == "giá căn hộ"
    assert called["args"][1] == "NCLB"


async def test_backend_hipporag_routes_to_hipporag_adapter(monkeypatch):
    monkeypatch.setattr(noble_kb.settings, "noble_rag_backend", "hipporag")
    called = {}

    async def _fake(query, project_filter, top_k=5):
        called["args"] = (query, project_filter)
        return "HIPPORAG_RESULT"

    monkeypatch.setattr(
        "noble_agent.agent.rag.hipporag.adapter.query_hipporag_for_noble_kb",
        _fake,
    )
    out = await noble_kb.query_noble_kb("bể bơi tây hồ", "NCTH")
    assert out == "HIPPORAG_RESULT"
    assert called["args"] == ("bể bơi tây hồ", "NCTH")
