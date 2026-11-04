# HippoRAG triple embedding trên Qdrant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép đọc triple embedding của HippoRAG từ Qdrant (flag-gated) thay vì chỉ numpy sidecar local, với chuỗi fallback `qdrant → local → hybrid`.

**Architecture:** Thêm setting `HIPPORAG_TRIPLE_STORE`. `noble-rag-sync` build CẢ npz local (giữ nguyên) LẪN một collection Qdrant riêng (`recreate + fill`). Query-time `adapter._sparse_seed` branch theo flag: Qdrant → nếu lỗi thì local npz → nếu cả hai rỗng thì sparse-seed no-op (pipeline chạy tiếp). Ngữ nghĩa cosine/top_m/seed giữ hệt.

**Tech Stack:** Python 3.11+, pydantic-settings, `qdrant-client` (AsyncQdrantClient, import lazy), numpy, pytest (asyncio_mode=auto).

## Global Constraints

- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`.
- Default `hipporag_triple_store="local"` → **zero behaviour change** khi chưa set env.
- `qdrant-client` import **lazy** (bên trong hàm) — `make test-unit` phải collect được không cần extra `rag-qdrant`.
- Không đụng: `graph.json`, `expander.load()`, `HippoGraph`, PPR, `TripleIndex`, `triple_index.py`, đường `store=local`.
- Best-effort ở build-side: lỗi build Qdrant-triple chỉ log, không raise, không wedge `noble-rag-sync`.
- Collection triple là collection RIÊNG, tách khỏi clone `qdrant_collection`.
- Branch: `feat/refactor2`. Commit local trên branch này (không đụng `develop`, không push/PR).

---

### Task 1: Config — 2 setting mới

**Files:**
- Modify: `src/noble_agent/config.py` (khối HippoRAG, sau dòng `hipporag_openie_model` ~493)
- Test: `tests/unit/unified/test_config_triple_store.py` (create)

**Interfaces:**
- Produces: `settings.hipporag_triple_store: str` (`"local"|"qdrant"`, default `"local"`); `settings.qdrant_triple_collection: str` (default `"noble_kb_hipporag_triples"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_config_triple_store.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_config_triple_store.py -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'hipporag_triple_store'`.

- [ ] **Step 3: Add the settings**

Trong `src/noble_agent/config.py`, ngay sau `hipporag_openie_model: str = ""` (dòng ~493):

```python
    # Triple embedding store for the sparse triple-seed. "local" (default) = the
    # numpy sidecar <graph>.triple_emb.npz; "qdrant" = a dedicated Qdrant collection
    # (built alongside the npz by noble-rag-sync). Query cascade when "qdrant":
    # Qdrant → local npz → sparse-seed no-op. Toggle needs no rebuild (both built).
    hipporag_triple_store: str = "local"          # env HIPPORAG_TRIPLE_STORE
    qdrant_triple_collection: str = "noble_kb_hipporag_triples"  # env QDRANT_TRIPLE_COLLECTION
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_config_triple_store.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/config.py tests/unit/unified/test_config_triple_store.py
git commit -m "feat(hipporag): add HIPPORAG_TRIPLE_STORE + QDRANT_TRIPLE_COLLECTION settings"
```

---

### Task 2: Qdrant store — 3 hàm triple collection

**Files:**
- Modify: `src/noble_agent/agent/rag/qdrant_store.py` (thêm cuối file, trước `close`)
- Test: `tests/unit/unified/rag/test_qdrant_store.py` (thêm cases)

**Interfaces:**
- Consumes: `settings.qdrant_triple_collection` (Task 1); `_get_client()` (đã có).
- Produces:
  - `async recreate_triple_collection(dim: int) -> None`
  - `async upsert_triples(points: list) -> None`
  - `async search_triples(query_vec, top_m: int) -> list[tuple[str, str, float]]` — trả `[(s, o, score)]`, ném exception khi Qdrant lỗi/thiếu collection.

- [ ] **Step 1: Write the failing tests**

Thêm vào cuối `tests/unit/unified/rag/test_qdrant_store.py` (tái dùng `_FakePoint`/`_FakeResp` sẵn có):

```python
class _FakeTripleClient:
    def __init__(self):
        self.last = None

    async def query_points(self, **kwargs):
        self.last = kwargs
        return _FakeResp(
            [
                _FakePoint(0, {"s": "A", "o": "B", "text": "A r B"}, 0.9),
                _FakePoint(1, {"s": "C", "o": "D", "text": "C r D"}, 0.4),
            ]
        )


class _FakeAdminClient:
    def __init__(self, exists=True):
        self._exists = exists
        self.created = None
        self.deleted = None
        self.upserted = None

    async def collection_exists(self, name):
        return self._exists

    async def delete_collection(self, name):
        self.deleted = name

    async def create_collection(self, **kwargs):
        self.created = kwargs

    async def upsert(self, **kwargs):
        self.upserted = kwargs


async def test_search_triples_maps_payload(monkeypatch):
    c = _FakeTripleClient()
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    monkeypatch.setattr(qs.settings, "qdrant_triple_collection", "triples")
    out = await qs.search_triples([0.1, 0.2], top_m=2)
    assert out == [("A", "B", 0.9), ("C", "D", 0.4)]
    assert c.last["collection_name"] == "triples"
    assert c.last["limit"] == 2


async def test_recreate_triple_collection_drops_then_creates(monkeypatch):
    from qdrant_client import models

    c = _FakeAdminClient(exists=True)
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    monkeypatch.setattr(qs.settings, "qdrant_triple_collection", "triples")
    await qs.recreate_triple_collection(4)
    assert c.deleted == "triples"
    assert c.created["collection_name"] == "triples"
    vc = c.created["vectors_config"]
    assert vc.size == 4
    assert vc.distance == models.Distance.COSINE


async def test_upsert_triples_targets_triple_collection(monkeypatch):
    c = _FakeAdminClient()
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    monkeypatch.setattr(qs.settings, "qdrant_triple_collection", "triples")
    await qs.upsert_triples([{"id": 0}])
    assert c.upserted["collection_name"] == "triples"
    assert c.upserted["points"] == [{"id": 0}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/rag/test_qdrant_store.py -k "triple" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'search_triples'`.

- [ ] **Step 3: Implement the 3 functions**

Thêm vào `src/noble_agent/agent/rag/qdrant_store.py` ngay trước `async def close()`:

```python
async def recreate_triple_collection(dim: int) -> None:
    """Drop + create the HippoRAG triple collection: one unnamed dense vector,
    Cosine distance (≡ the normalised dot-product TripleIndex uses). Dense-only,
    no sparse, no payload index."""
    from qdrant_client import models

    client = _get_client()
    coll = settings.qdrant_triple_collection
    if await client.collection_exists(coll):
        await client.delete_collection(coll)
    await client.create_collection(
        collection_name=coll,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    logger.info("[qdrant_store] recreated triple collection %s (dim=%d)", coll, dim)


async def upsert_triples(points: list) -> None:
    """Upsert prepared PointStructs into the triple collection."""
    client = _get_client()
    await client.upsert(collection_name=settings.qdrant_triple_collection, points=points)


async def search_triples(query_vec, top_m: int) -> list[tuple[str, str, float]]:
    """Dense search on the triple collection. Returns [(s_key, o_key, score)].
    Raises on Qdrant error / missing collection so the caller can fall back to the
    local npz index."""
    client = _get_client()
    resp = await client.query_points(
        collection_name=settings.qdrant_triple_collection,
        query=query_vec,
        limit=top_m,
        with_payload=True,
    )
    out: list[tuple[str, str, float]] = []
    for p in resp.points:
        pl = p.payload or {}
        out.append((str(pl.get("s", "")), str(pl.get("o", "")), float(p.score)))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/rag/test_qdrant_store.py -k "triple" -v`
Expected: PASS (3 passed). (Cần extra `rag-qdrant` cài để import `qdrant_client.models` — đã có trong môi trường dev; nếu chưa: `pip install -e ".[rag-qdrant]"`.)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/qdrant_store.py tests/unit/unified/rag/test_qdrant_store.py
git commit -m "feat(hipporag): qdrant_store triple collection recreate/upsert/search"
```

---

### Task 3: Builder — build Qdrant triple collection mỗi sync

**Files:**
- Modify: `src/noble_agent/agent/rag/hipporag/builder.py` (thêm `_build_triple_qdrant`, gọi trong `run_sync`)
- Test: `tests/unit/unified/rag/test_hipporag_builder.py` (thêm cases)

**Interfaces:**
- Consumes: `qdrant_store.recreate_triple_collection` / `upsert_triples` (Task 2); `flat_store._Embedder`; `graph.triples` (list of dict với keys `s`/`o`/`text`).
- Produces: `async _build_triple_qdrant(graph: HippoGraph) -> None` (best-effort, không raise). Wired vào `run_sync` sau `_build_triple_index_from_embedder`.

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/unit/unified/rag/test_hipporag_builder.py` (đã import `builder`, `HippoGraph`):

```python
async def test_build_triple_qdrant_upserts(monkeypatch):
    import numpy as np

    from noble_agent.agent.rag import flat_store, qdrant_store

    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", [("A", "r", "B"), ("C", "r2", "D")])

    class FakeEmb:
        def encode_batch(self, texts, show_progress=False):
            return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr(flat_store, "_Embedder", lambda: FakeEmb())

    calls = {}

    async def fake_recreate(dim):
        calls["dim"] = dim

    async def fake_upsert(points):
        calls["points"] = points

    monkeypatch.setattr(qdrant_store, "recreate_triple_collection", fake_recreate)
    monkeypatch.setattr(qdrant_store, "upsert_triples", fake_upsert)

    await builder._build_triple_qdrant(g)
    assert calls["dim"] == 4
    assert len(calls["points"]) == 2  # 2 triples


async def test_build_triple_qdrant_noop_on_empty(monkeypatch):
    from noble_agent.agent.rag import qdrant_store

    called = {"recreate": False}

    async def fake_recreate(dim):
        called["recreate"] = True

    monkeypatch.setattr(qdrant_store, "recreate_triple_collection", fake_recreate)
    await builder._build_triple_qdrant(HippoGraph())  # no passages → no triples
    assert called["recreate"] is False


async def test_build_triple_qdrant_swallows_embedder_error(monkeypatch):
    from noble_agent.agent.rag import flat_store

    def boom():
        raise RuntimeError("embedder down")

    monkeypatch.setattr(flat_store, "_Embedder", boom)
    g = HippoGraph()
    g.add_passage("p1", "t", "NCTH", "h1", [("A", "r", "B")])
    # must not raise
    await builder._build_triple_qdrant(g)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/rag/test_hipporag_builder.py -k "triple_qdrant" -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_build_triple_qdrant'`.

- [ ] **Step 3: Implement `_build_triple_qdrant` + wire into `run_sync`**

Thêm hàm vào `src/noble_agent/agent/rag/hipporag/builder.py` (sau `_build_triple_index_from_embedder`):

```python
async def _build_triple_qdrant(graph: HippoGraph) -> None:
    """Embed triples and (re)build the Qdrant triple collection — the backup source
    for the local npz. Built on every sync so HIPPORAG_TRIPLE_STORE can be toggled
    without a rebuild. Best-effort: any failure just logs (runtime cascade
    qdrant→local→hybrid covers it)."""
    triples = graph.triples
    if not triples:
        return
    try:
        from qdrant_client import models

        from noble_agent.agent.rag import qdrant_store
        from noble_agent.agent.rag.flat_store import _Embedder

        embedder = _Embedder()
        emb = np.asarray(
            embedder.encode_batch([t.get("text", "") for t in triples], show_progress=False),
            dtype=np.float32,
        )
        dim = int(emb.shape[1])
        await qdrant_store.recreate_triple_collection(dim)
        points = [
            models.PointStruct(
                id=i,
                vector=emb[i].tolist(),
                payload={"s": t.get("s", ""), "o": t.get("o", ""), "text": t.get("text", "")},
            )
            for i, t in enumerate(triples)
        ]
        await qdrant_store.upsert_triples(points)
        logger.info("[hipporag.builder] qdrant triple collection built (%d triples)", len(triples))
    except Exception as exc:  # noqa: BLE001
        logger.error("[hipporag.builder] qdrant triple build skipped: %s", exc)
```

Trong `run_sync`, ngay sau dòng `_build_triple_index_from_embedder(graph, path)` (~176):

```python
        _build_triple_index_from_embedder(graph, path)
        await _build_triple_qdrant(graph)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/rag/test_hipporag_builder.py -k "triple_qdrant" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/hipporag/builder.py tests/unit/unified/rag/test_hipporag_builder.py
git commit -m "feat(hipporag): build qdrant triple collection alongside npz in run_sync"
```

---

### Task 4: Adapter — `_sparse_seed` cascade qdrant → local → hybrid

**Files:**
- Modify: `src/noble_agent/agent/rag/hipporag/adapter.py` (`_sparse_seed`, dòng ~70-91)
- Test: `tests/unit/unified/rag/test_hipporag_adapter.py` (thêm cases)

**Interfaces:**
- Consumes: `settings.hipporag_triple_store` (Task 1); `qdrant_store.search_triples` (Task 2); `expander.load_triple_index` (đã có); `qdrant_adapter._embed_query` (đã có).
- Produces: `_sparse_seed(query, top_m)` giữ nguyên chữ ký + trả `dict[str, float]`.

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/unit/unified/rag/test_hipporag_adapter.py` (đã import `adapter`, `expander`):

```python
async def test_sparse_seed_qdrant_source(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "qdrant")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1, 0.2])

    async def fake_search(vec, top_m):
        return [("A", "B", 0.9), ("C", "", 0.5)]

    monkeypatch.setattr(qdrant_store, "search_triples", fake_search)
    seeds = await adapter._sparse_seed("q", 5)
    assert seeds == {"A": 0.9, "B": 0.9, "C": 0.5}  # empty o_key skipped


async def test_sparse_seed_qdrant_falls_back_to_local(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "qdrant")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1])

    async def boom(vec, top_m):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(qdrant_store, "search_triples", boom)

    class FakeIdx:
        def search(self, vec, top_m):
            return [("X", "Y", 0.7)]

    monkeypatch.setattr(expander, "load_triple_index", lambda: FakeIdx())
    seeds = await adapter._sparse_seed("q", 5)
    assert seeds == {"X": 0.7, "Y": 0.7}  # served from local npz backup


async def test_sparse_seed_qdrant_and_local_empty(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "qdrant")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1])

    async def boom(vec, top_m):
        raise RuntimeError("down")

    monkeypatch.setattr(qdrant_store, "search_triples", boom)
    monkeypatch.setattr(expander, "load_triple_index", lambda: None)
    assert await adapter._sparse_seed("q", 5) == {}  # → sparse-seed no-op (hybrid)


async def test_sparse_seed_local_store_skips_qdrant(monkeypatch):
    from noble_agent.agent.rag import qdrant_adapter, qdrant_store

    monkeypatch.setattr(adapter.settings, "hipporag_triple_store", "local")
    monkeypatch.setattr(qdrant_adapter, "_embed_query", lambda q: [0.1])
    called = {"q": False}

    async def spy(vec, top_m):
        called["q"] = True
        return []

    monkeypatch.setattr(qdrant_store, "search_triples", spy)

    class FakeIdx:
        def search(self, vec, top_m):
            return [("X", "Y", 0.6)]

    monkeypatch.setattr(expander, "load_triple_index", lambda: FakeIdx())
    seeds = await adapter._sparse_seed("q", 5)
    assert called["q"] is False  # local store never calls Qdrant
    assert seeds == {"X": 0.6, "Y": 0.6}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/rag/test_hipporag_adapter.py -k "sparse_seed_qdrant or sparse_seed_local" -v`
Expected: FAIL — hiện `_sparse_seed` chưa branch theo `hipporag_triple_store`; `test_sparse_seed_local_store_skips_qdrant` chưa chắc fail nhưng `test_sparse_seed_qdrant_source` fail (không gọi `search_triples`).

- [ ] **Step 3: Rewrite `_sparse_seed`**

Thay thân `_sparse_seed` trong `src/noble_agent/agent/rag/hipporag/adapter.py` (dòng ~70-91) bằng:

```python
async def _sparse_seed(query: str, top_m: int) -> dict[str, float]:
    """The SPARSE triple-seed (HippoRAG 2): embed the query and cosine-match against
    the stored TRIPLE embeddings ("subject relation object"); the top triples seed
    PPR at BOTH their phrase nodes → {phrase_key: score}. Runs concurrently with the
    hybrid search (own embed; the two overlap so wall-clock is unaffected).

    Source cascade when HIPPORAG_TRIPLE_STORE="qdrant": Qdrant triple collection →
    (on error) local npz index → (both empty) {} so sparse-seed simply no-ops.
    Default "local" reads only the npz index (unchanged)."""
    from noble_agent.agent.rag.qdrant_adapter import _embed_query

    loop = asyncio.get_running_loop()
    dense = await loop.run_in_executor(None, _embed_query, query)

    triples: list[tuple[str, str, float]] = []
    if settings.hipporag_triple_store == "qdrant":
        from noble_agent.agent.rag import qdrant_store

        try:
            triples = await qdrant_store.search_triples(dense, top_m)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hipporag.adapter] qdrant triple search failed (%s) — local fallback", exc)
            idx = expander.load_triple_index()
            if idx is not None:
                triples = await loop.run_in_executor(None, idx.search, dense, top_m)
    else:
        idx = expander.load_triple_index()
        if idx is not None:
            triples = await loop.run_in_executor(None, idx.search, dense, top_m)

    seeds: dict[str, float] = {}
    for s_key, o_key, score in triples:
        if score <= 0:
            continue
        for key in (s_key, o_key):
            if key:
                seeds[key] = max(seeds.get(key, 0.0), score)
    return seeds
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/rag/test_hipporag_adapter.py -k "sparse_seed" -v`
Expected: PASS (4 mới + các case sparse-seed cũ vẫn xanh).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/hipporag/adapter.py tests/unit/unified/rag/test_hipporag_adapter.py
git commit -m "feat(hipporag): _sparse_seed cascade qdrant → local → hybrid"
```

---

### Task 5: Gate hồi quy + docs

**Files:**
- Modify: `CLAUDE.md` (khối HippoRAG trong bảng layout + config table + Change Log)
- Modify: `.env.example` (thêm 2 var + ghi chú)

- [ ] **Step 1: Chạy full RAG unit gate**

Run: `pytest tests/unit/unified/rag -q`
Expected: PASS ngoại trừ baseline đã biết (qdrant_adapter×2, qdrant_store — theo Change Log). **ZERO** failure mới ngoài baseline đó. Nếu có failure mới → dừng, fix.

- [ ] **Step 2: Chạy toàn bộ unit unified + ruff**

Run: `pytest tests/unit/unified -q` rồi `ruff check src/noble_agent/agent/rag/hipporag/ src/noble_agent/agent/rag/qdrant_store.py src/noble_agent/config.py`
Expected: chỉ còn 7 baseline failures đã biết (project_financial USD, prompt 'Tên:', qdrant_adapter×2, qdrant_store, send_media local-.env, snapshot_short_term); ruff clean trên file đã đụng.

- [ ] **Step 3: Cập nhật `.env.example`**

Thêm dưới khối HippoRAG:

```bash
# HippoRAG triple embedding store: "local" (numpy sidecar, default) | "qdrant"
# (dedicated collection built by noble-rag-sync alongside the npz). Query cascade
# when "qdrant": Qdrant → local npz → sparse-seed off. Rollback = set back to local.
HIPPORAG_TRIPLE_STORE=local
QDRANT_TRIPLE_COLLECTION=noble_kb_hipporag_triples
```

- [ ] **Step 4: Cập nhật `CLAUDE.md`**

- Trong khối HippoRAG "Sparse triple-seed": ghi chú build-time nay cũng (re)build một Qdrant triple collection `QDRANT_TRIPLE_COLLECTION`, và query đọc theo `HIPPORAG_TRIPLE_STORE` với cascade `qdrant → local → hybrid`.
- Config table: thêm 2 hàng `HIPPORAG_TRIPLE_STORE` (default `local`) + `QDRANT_TRIPLE_COLLECTION` (default `noble_kb_hipporag_triples`).
- Append 1 hàng Change Log (ngày 2026-07-29) mô tả thay đổi + lý do (chuyển triple embedding lên Qdrant, flag-gated, build cả hai, cascade fallback) + note "graph.json vẫn local".

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .env.example
git commit -m "docs(hipporag): document HIPPORAG_TRIPLE_STORE + qdrant triple collection"
```

---

## Self-Review

**Spec coverage:**
- Config 2 setting → Task 1. ✅
- `recreate_triple_collection`/`upsert_triples`/`search_triples` → Task 2. ✅
- `_build_triple_qdrant` + wire `run_sync`, build cả hai → Task 3. ✅
- `_sparse_seed` cascade qdrant→local→hybrid, embed 1 lần → Task 4. ✅
- Payload `{s, o, text}` → Task 2 (search đọc `s`/`o`) + Task 3 (upsert ghi cả 3). ✅
- Không đổi đường local / bất biến → Task 4 case `local_store_skips_qdrant` + default `local`. ✅
- Vận hành (bật/rollback/`--renew-graph`) → Task 5 `.env.example` + CLAUDE.md. ✅

**Placeholder scan:** không có TBD/TODO; mọi step code là code thật.

**Type consistency:** `search_triples`/`idx.search` cùng trả `list[tuple[str,str,float]]`; seed-building dùng chung. `_build_triple_qdrant` đọc `t.get("s"/"o"/"text")` khớp shape `graph.triples` (dùng bởi `build_and_save_triple_index` hiện tại). `recreate_triple_collection(dim:int)` khớp caller Task 3. ✅

## Notes
- `run_sync` (Task 3 wiring) không unit-test trực tiếp (cần Qdrant + LLM live); `_build_triple_qdrant` được test đơn vị, wiring xác nhận qua live `noble-rag-sync`.
- Trước khi bật `HIPPORAG_TRIPLE_STORE=qdrant` trên deploy: chạy `noble-rag-sync` (graph cũ chưa có triple → `noble-rag-sync --renew-graph` một lần) để populate collection triple; đồng thời npz local được refresh làm backup.
- Live smoke `/chat` với `NOBLE_RAG_BACKEND=hipporag` + `HIPPORAG_SPARSE_SEED_ENABLED=true` + `HIPPORAG_TRIPLE_STORE=qdrant` sau khi merge (theo `SMOKE.md`).
