from noble_agent.agent.rag import sparse_reconcile as sr


async def test_reconcile_builds_clone_and_fallback(monkeypatch, tmp_path):
    recreated = {}
    upserted = []
    built = {}

    async def fake_params():
        return 1024, "Cosine"

    async def fake_recreate(dim, distance):
        recreated["dim"] = dim
        recreated["distance"] = distance

    async def fake_iter(batch=256):
        yield "p1", [0.0] * 1024, {"project_id": "NCTH", "text": "căn hộ Tây Hồ view hồ"}
        yield "p2", [0.1] * 1024, {"project_id": "SGR", "text": "Sunshine Grand City bể bơi"}

    async def fake_upsert(points):
        upserted.extend(points)

    def fake_build(chunks, out_dir):
        built["n"] = len(chunks)
        built["dir"] = out_dir

    monkeypatch.setattr(sr.qdrant_store, "get_root_dense_params", fake_params)
    monkeypatch.setattr(sr.qdrant_store, "recreate_clone", fake_recreate)
    monkeypatch.setattr(sr.qdrant_store, "iter_root_points", fake_iter)
    monkeypatch.setattr(sr.qdrant_store, "upsert_clone_points", fake_upsert)
    monkeypatch.setattr(sr.bm25_fallback, "build", fake_build)
    monkeypatch.setattr(sr.settings, "qdrant_collection_root", "root")
    monkeypatch.setattr(sr.settings, "qdrant_fallback_dir", str(tmp_path / "fb"))

    n = await sr.reconcile()

    assert n == 2
    assert recreated["dim"] == 1024
    assert recreated["distance"] == "Cosine"
    assert len(upserted) == 2
    assert built["n"] == 2


async def test_reconcile_noop_when_root_unset(monkeypatch):
    monkeypatch.setattr(sr.settings, "qdrant_collection_root", "")
    assert await sr.reconcile() == 0
