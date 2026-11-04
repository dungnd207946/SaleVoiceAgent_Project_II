from noble_agent.config import UnifiedSettings


def test_triple_store_defaults():
    s = UnifiedSettings(_env_file=None)
    assert s.hipporag_triple_store == "local"
    assert s.qdrant_triple_collection == "noble_kb_hipporag_triples"


def test_triple_store_env_override(monkeypatch):
    monkeypatch.setenv("HIPPORAG_TRIPLE_STORE", "qdrant")
    monkeypatch.setenv("QDRANT_TRIPLE_COLLECTION", "custom_triples")
    s = UnifiedSettings(_env_file=None)
    assert s.hipporag_triple_store == "qdrant"
    assert s.qdrant_triple_collection == "custom_triples"
