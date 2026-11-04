from noble_agent.config import UnifiedSettings


def test_qdrant_hybrid_settings_defaults(monkeypatch):
    for var in (
        "QDRANT_COLLECTION",
        "QDRANT_COLLECTION_ROOT",
        "QDRANT_DENSE_VECTOR_NAME",
        "QDRANT_SPARSE_VECTOR_NAME",
        "QDRANT_FALLBACK_DIR",
    ):
        monkeypatch.delenv(var, raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.qdrant_collection_root == ""
    assert s.qdrant_collection == "noble_kb_hybrid"
    assert s.qdrant_dense_vector_name == "dense"
    assert s.qdrant_sparse_vector_name == "bm25"
    assert s.qdrant_fallback_dir.endswith("bm25_qdrant_fallback")
