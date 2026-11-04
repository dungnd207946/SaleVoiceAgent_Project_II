# Qdrant Dense Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `qdrant` RAG backend that serves dense (e5-large, 1024d, cosine) retrieval from a remote Qdrant, fused with the existing local BM25 via RRF, while keeping `flat_store` as the default.

**Architecture:** Qdrant owns dense only; BM25 stays local; RRF fusion stays in code keyed on `chunk_id`. Query embedding reuses the existing FlatStore `_Embedder`, so vectors match the offline-ingested ones (answer-quality parity). A new dispatch branch in `noble_kb.py` routes `NOBLE_RAG_BACKEND=qdrant` to the new adapter. An offline script ingests the same chunks FlatStore loads. Stale Qdrant remnants are cleaned up in the same change.

**Tech Stack:** Python 3.11+, `qdrant-client>=1.10` (new optional extra `rag-qdrant`, lazy-imported), numpy, bm25s, pytest (`asyncio_mode=auto`).

**Spec:** `docs/superpowers/specs/2026-06-08-qdrant-dense-backend-design.md`

**Pre-req for integration/eval tasks:** the dev Qdrant is remote (EC2). Open the SSH tunnel first:
```
ssh -i "seoul-ai-dev.pem" -L 6333:localhost:6333 -L 6334:localhost:6334 \
  -L 6379:localhost:6379 -L 27017:localhost:27017 \
  ubuntu@ec2-3-37-136-28.ap-northeast-2.compute.amazonaws.com -N
```

---

### Task 1: Config + packaging for the qdrant backend

**Files:**
- Modify: `src/noble_agent/config.py:249-253`
- Modify: `pyproject.toml` (optional-dependencies + markers)
- Test: `tests/unit/unified/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/unified/test_config.py`:

```python
def test_qdrant_collection_default_is_e5():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings()
    assert s.qdrant_collection == "noble_kb_e5_1024d"
    assert s.qdrant_url == "http://localhost:6333"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_config.py::test_qdrant_collection_default_is_e5 -v`
Expected: FAIL — `assert 'lightrag_vdb_entities_baai_bge_m3_1024d' == 'noble_kb_e5_1024d'`

- [ ] **Step 3: Edit the config block**

In `src/noble_agent/config.py`, replace the legacy block (lines ~249-253):

```python
    # ── RAG: Qdrant dense backend (opt-in via NOBLE_RAG_BACKEND=qdrant) ────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "noble_kb_e5_1024d"
    rag_top_k: int = 3
    embedding_model: str = "BAAI/bge-m3"
```

(Only the comment and `qdrant_collection` default change; `rag_top_k` and
`embedding_model` are untouched.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_config.py::test_qdrant_collection_default_is_e5 -v`
Expected: PASS

- [ ] **Step 5: Add packaging — optional extra + pytest marker**

In `pyproject.toml`, under `[project.optional-dependencies]` add:

```toml
rag-qdrant = ["qdrant-client>=1.10"]
```

Under `[tool.pytest.ini_options]` `markers = [...]` add:

```toml
    "needs_qdrant: integration test requires a reachable Qdrant (QDRANT_URL)",
```

- [ ] **Step 6: Install the extra into the venv**

Run: `pip install -e ".[rag-qdrant]"`
Expected: installs `qdrant-client`.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/config.py pyproject.toml tests/unit/unified/test_config.py
git commit -m "feat(rag): config + packaging for qdrant dense backend"
```

---

### Task 2: `FlatStore.load_chunks_only()` — chunks + BM25 mapping without dense `.npy`

**Files:**
- Modify: `src/noble_agent/agent/rag/flat_store.py` (add method near `load`, ~line 396)
- Test: `tests/unit/unified/test_flat_store_chunks_only.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_flat_store_chunks_only.py`:

```python
from noble_agent.agent.rag.flat_store import FlatStore


def test_load_chunks_only_loads_chunks_and_project_idx_without_embeddings():
    s = FlatStore()
    s.load_chunks_only()
    assert len(s.chunks) > 0
    assert s.embeddings is None
    # project_idx covers every canonical code present in the corpus
    assert set(s.project_idx) == {"NCLB", "NCTH", "NPLB", "NTTL", "SSLC"}
    # indices map back to chunks of that project
    for code, idx in s.project_idx.items():
        if len(idx):
            assert s.chunks[int(idx[0])].project == code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_flat_store_chunks_only.py -v`
Expected: FAIL — `AttributeError: 'FlatStore' object has no attribute 'load_chunks_only'`

- [ ] **Step 3: Add the method**

In `src/noble_agent/agent/rag/flat_store.py`, add after `load()` (before `# — Public search —`):

```python
    def load_chunks_only(self) -> None:
        """Load chunks + project_idx WITHOUT dense embeddings.

        For the qdrant backend, where Qdrant owns the dense signal and only
        BM25 + chunk metadata (text, project, chunk_id) stay local for RRF
        fusion. Leaves ``self.embeddings`` as None.
        """
        self.chunks = self._load_chunks_from_disk()
        if not self.chunks:
            raise RuntimeError(f"No chunks loaded from {self.data_dir}")
        arr = np.array([c.project for c in self.chunks])
        for p in set(PROJECT_MAP.values()):
            self.project_idx[p] = np.where(arr == p)[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_flat_store_chunks_only.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/flat_store.py tests/unit/unified/test_flat_store_chunks_only.py
git commit -m "feat(rag): FlatStore.load_chunks_only for qdrant BM25-local path"
```

---

### Task 3: `qdrant_store.py` — dense search wrapper

**Files:**
- Create: `src/noble_agent/agent/rag/qdrant_store.py`
- Test: `tests/unit/unified/test_qdrant_store.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_qdrant_store.py`:

```python
import numpy as np
import pytest

from noble_agent.agent.rag import qdrant_store as qs


@pytest.fixture(autouse=True)
def _reset_client():
    qs._client = None
    yield
    qs._client = None


async def test_search_dense_maps_points_to_tuples(monkeypatch):
    class _Pt:
        def __init__(self, pid, payload, score):
            self.id, self.payload, self.score = pid, payload, score

    class _Resp:
        points = [
            _Pt("u1", {"chunk_id": "a", "project": "NCLB", "text": "alpha"}, 0.91),
            _Pt("u2", {"chunk_id": "b", "project": "NCLB", "text": "beta"}, 0.80),
        ]

    class _FakeClient:
        async def query_points(self, **kwargs):
            # project filter must be passed through when project_filter given
            assert kwargs["query_filter"] is not None
            return _Resp()

    monkeypatch.setattr(qs, "_get_client", lambda: _FakeClient())
    out = await qs.search_dense(np.zeros(4, dtype=np.float32), "NCLB", top_k=5)
    assert out == [
        ("a", "NCLB", "alpha", 0.91),
        ("b", "NCLB", "beta", 0.80),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_qdrant_store.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.agent.rag.qdrant_store`

- [ ] **Step 3: Write the module**

Create `src/noble_agent/agent/rag/qdrant_store.py`:

```python
"""Qdrant-backed dense retrieval for the noble_search KB.

Owns ONLY the dense signal (e5-large, 1024d, cosine). BM25 stays local; RRF
fusion happens in qdrant_adapter. Query embedding uses the shared FlatStore
_Embedder so query vectors match the offline-ingested ones exactly.

qdrant-client is imported lazily (optional extra `rag-qdrant`) so the default
flat_store path never requires it.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("rag.qdrant_store")

_client = None  # AsyncQdrantClient singleton


def _get_client():
    global _client
    if _client is not None:
        return _client
    from qdrant_client import AsyncQdrantClient

    from noble_agent.config import settings

    _client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    logger.info("[qdrant_store] client → %s (collection=%s)", settings.qdrant_url, settings.qdrant_collection)
    return _client


async def search_dense(q_vec: np.ndarray, project_filter: str, top_k: int) -> list[tuple[str, str, str, float]]:
    """Return ``[(chunk_id, project, text, score)]`` sorted by score desc."""
    from qdrant_client import models

    from noble_agent.config import settings

    client = _get_client()
    query_filter = None
    if project_filter:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="project", match=models.MatchValue(value=project_filter))]
        )
    resp = await client.query_points(
        collection_name=settings.qdrant_collection,
        query=q_vec.tolist(),
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )
    out: list[tuple[str, str, str, float]] = []
    for p in resp.points:
        pl = p.payload or {}
        out.append(
            (
                pl.get("chunk_id", str(p.id)),
                pl.get("project", "?"),
                pl.get("text", ""),
                float(p.score),
            )
        )
    return out


async def close() -> None:
    global _client
    if _client is not None:
        try:
            await _client.close()
        except Exception:
            pass
        _client = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_qdrant_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/qdrant_store.py tests/unit/unified/test_qdrant_store.py
git commit -m "feat(rag): qdrant_store dense search wrapper"
```

---

### Task 4: `qdrant_adapter.py` — dense + local BM25 → RRF → formatted string

**Files:**
- Create: `src/noble_agent/agent/rag/qdrant_adapter.py`
- Test: `tests/unit/unified/test_qdrant_adapter.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/unified/test_qdrant_adapter.py`:

```python
import numpy as np
import pytest

from noble_agent.agent.rag import qdrant_adapter as qa
from noble_agent.agent.rag.flat_store import Chunk


class _FakeEmbedder:
    def encode_query(self, q):
        return np.zeros(4, dtype=np.float32)


class _FakeStore:
    def __init__(self, chunks, sparse):
        self.chunks = chunks
        self.bm25_retriever = object()  # truthy → BM25 considered available
        self.embedder = _FakeEmbedder()
        self._sparse = sparse  # list[(local_index, score)]

    def _bm25_topk(self, query, project_filter, k):
        return self._sparse


@pytest.fixture(autouse=True)
def _reset():
    qa._store = None
    qa._warmed = False
    yield
    qa._store = None
    qa._warmed = False


async def test_rrf_fuses_dense_and_sparse(monkeypatch):
    chunks = [
        Chunk(id="a", project="NCLB", text="alpha"),
        Chunk(id="b", project="NCLB", text="beta"),
        Chunk(id="c", project="NCLB", text="gamma"),
    ]
    # sparse ranks c, then a (local indices 2, 0)
    store = _FakeStore(chunks, sparse=[(2, 5.0), (0, 1.0)])

    async def _ensure():
        return store

    monkeypatch.setattr(qa, "_ensure_local", _ensure)

    async def _dense(q_vec, pf, k):
        return [("a", "NCLB", "alpha", 0.9), ("b", "NCLB", "beta", 0.8)]

    monkeypatch.setattr("noble_agent.agent.rag.qdrant_store.search_dense", _dense)

    out = await qa.query_qdrant_for_noble_kb("q", "NCLB", top_k=3)
    # 'a' appears in BOTH lists → highest RRF → ranked first
    assert out.startswith("[Nguon 1 | Du an: NCLB")
    assert "alpha" in out
    assert "gamma" in out  # 'c' from sparse-only is fused in


async def test_fallback_to_bm25_only_on_qdrant_error(monkeypatch):
    chunks = [Chunk(id="a", project="NCLB", text="alpha")]
    store = _FakeStore(chunks, sparse=[(0, 3.0)])

    async def _ensure():
        return store

    monkeypatch.setattr(qa, "_ensure_local", _ensure)

    async def _boom(q_vec, pf, k):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("noble_agent.agent.rag.qdrant_store.search_dense", _boom)

    out = await qa.query_qdrant_for_noble_kb("q", "NCLB", top_k=3)
    assert "alpha" in out  # BM25-only still returns a result


async def test_empty_query_returns_empty(monkeypatch):
    out = await qa.query_qdrant_for_noble_kb("   ", "NCLB", top_k=3)
    assert out == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_qdrant_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.agent.rag.qdrant_adapter`

- [ ] **Step 3: Write the module**

Create `src/noble_agent/agent/rag/qdrant_adapter.py`:

```python
"""Qdrant dense + local BM25 → RRF → noble_kb formatted string.

Mirrors FlatStore.search_hybrid (candidates=20, rrf_k=60) but takes the dense
candidates from Qdrant instead of a local matmul. RRF fuses on chunk_id. Text
and project for each hit resolve from the local chunk list (sparse side) or the
Qdrant payload (dense-only side). Output uses flat_store_adapter._format_hits so
the tool-result shape is identical across backends.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("rag.qdrant_adapter")

_CANDIDATES = 20
_RRF_K = 60

_store = None  # FlatStore loaded chunks + BM25 only (no .npy)
_warmed = False


async def _ensure_local():
    """Load FlatStore chunks + BM25 (NOT dense embeddings) once. Warm encoder."""
    global _store, _warmed
    if _store is not None:
        if not _warmed:
            _store.embedder.encode_query("warmup")
            _warmed = True
        return _store
    from noble_agent.agent.rag.flat_store import FlatStore

    s = FlatStore()
    s.load_chunks_only()
    try:
        s.load_bm25(build_if_missing=False)
        logger.info("[qdrant_adapter] BM25 index loaded")
    except Exception as exc:
        logger.warning("[qdrant_adapter] BM25 not available: %s -- dense-only", exc)
    s.embedder.encode_query("warmup")
    _store = s
    _warmed = True
    return s


async def query_qdrant_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str:
    """Called by noble_kb.query_noble_kb when backend == 'qdrant'."""
    from noble_agent.agent.rag import qdrant_store
    from noble_agent.agent.rag.flat_store import Chunk, SearchHit
    from noble_agent.agent.rag.flat_store_adapter import _format_hits

    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return ""

    s = await _ensure_local()
    loop = asyncio.get_event_loop()
    q_vec = await loop.run_in_executor(None, s.embedder.encode_query, query)

    # Dense from Qdrant (graceful: empty list on failure → BM25-only).
    try:
        dense = await qdrant_store.search_dense(q_vec, project_filter, _CANDIDATES)
    except Exception as exc:
        logger.warning("[qdrant_adapter] dense search failed: %s -- BM25-only fallback", exc)
        dense = []

    # Sparse from local BM25 → list[(local_index, score)].
    def _bm25():
        if getattr(s, "bm25_retriever", None) is None:
            return []
        try:
            return s._bm25_topk(query, project_filter, _CANDIDATES)
        except Exception as exc:
            logger.warning("[qdrant_adapter] bm25 failed: %s", exc)
            return []

    sparse = await loop.run_in_executor(None, _bm25)

    by_id = {c.id: c for c in s.chunks}

    rrf: dict[str, float] = {}
    dense_score: dict[str, float] = {}
    for rank, (cid, _proj, _text, score) in enumerate(dense):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
        dense_score[cid] = score
    for rank, (lidx, _s) in enumerate(sparse):
        cid = s.chunks[lidx].id
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (_RRF_K + rank)

    if not rrf:
        return ""

    fused = sorted(rrf.items(), key=lambda x: -x[1])[:top_k]

    hits: list[SearchHit] = []
    for cid, _r in fused:
        ch = by_id.get(cid)
        if ch is None:
            d = next((x for x in dense if x[0] == cid), None)
            if d is None:
                continue
            ch = Chunk(id=cid, project=d[1], text=d[2])
        hits.append(SearchHit(chunk=ch, score=dense_score.get(cid, 0.0)))

    return _format_hits(hits)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_qdrant_adapter.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/qdrant_adapter.py tests/unit/unified/test_qdrant_adapter.py
git commit -m "feat(rag): qdrant_adapter — dense+BM25 RRF fusion with graceful fallback"
```

---

### Task 5: Wire the `qdrant` backend into `noble_kb.query_noble_kb`

**Files:**
- Modify: `src/noble_agent/agent/rag/noble_kb.py` (dispatch in `query_noble_kb`, ~lines 70-85)
- Test: `tests/unit/unified/test_noble_kb_dispatch.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_noble_kb_dispatch.py`:

```python
import pytest

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_noble_kb_dispatch.py -v`
Expected: FAIL — routes to flat_store, returns "" or flat_store output, not "QDRANT_RESULT".

- [ ] **Step 3: Add the dispatch branch + helper**

In `src/noble_agent/agent/rag/noble_kb.py`, inside `query_noble_kb`, add a
branch before the flat_store default (after the `grep_faq` branch):

```python
    if backend == "qdrant":
        return await _query_via_qdrant(query, project)
```

And add the helper near `_query_via_flat_store`:

```python
async def _query_via_qdrant(query: str, project_filter: str) -> str:
    """Qdrant dense + local BM25 RRF. Falls back to BM25-only on Qdrant error."""
    try:
        from noble_agent.agent.rag.qdrant_adapter import query_qdrant_for_noble_kb

        result = await query_qdrant_for_noble_kb(
            query,
            project_filter,
            top_k=settings.rag_top_k if settings.rag_top_k > 0 else 5,
        )
        if result:
            logger.info("[noble_kb] qdrant returned %d chars (project=%s)", len(result), project_filter or "ALL")
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] qdrant error: %s — returning empty", exc)
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_noble_kb_dispatch.py -v`
Expected: PASS

- [ ] **Step 5: Run the full unified RAG unit set**

Run: `pytest tests/unit/unified/test_noble_kb_dispatch.py tests/unit/unified/test_qdrant_adapter.py tests/unit/unified/test_qdrant_store.py tests/unit/unified/test_flat_store_chunks_only.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/rag/noble_kb.py tests/unit/unified/test_noble_kb_dispatch.py
git commit -m "feat(rag): route NOBLE_RAG_BACKEND=qdrant to qdrant_adapter"
```

---

### Task 6: Offline ingestion script `scripts/build_qdrant.py`

**Files:**
- Create: `scripts/build_qdrant.py`

No unit test (it talks to a live Qdrant); verified manually in Task 8. It reuses the
exact `FlatStore()` the runtime flat_store path builds, so uploaded vectors match.

- [ ] **Step 1: Write the script**

Create `scripts/build_qdrant.py`:

```python
"""Ingest the FlatStore KB into Qdrant (dense e5-large, cosine).

Reuses the exact FlatStore the runtime flat_store path builds (same chunks,
same .npy-cached embeddings), so the vectors in Qdrant match the local matmul
path → answer-quality parity.

Open the SSH tunnel to the remote Qdrant first (see the plan header), then:
    python scripts/build_qdrant.py             # idempotent upsert
    python scripts/build_qdrant.py --recreate  # drop + recreate collection
    python scripts/build_qdrant.py --project NCLB
"""

from __future__ import annotations

import argparse
import logging
import uuid

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("build_qdrant")

# Stable namespace so re-runs upsert (not duplicate) the same chunk.
_NS = uuid.UUID("00000000-0000-0000-0000-0000000000ab")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recreate", action="store_true", help="drop + recreate the collection")
    ap.add_argument("--project", default="", help="only ingest this canonical code (e.g. NCLB)")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()

    from qdrant_client import QdrantClient, models

    from noble_agent.agent.rag.flat_store import FlatStore
    from noble_agent.config import settings

    store = FlatStore()
    store.load()  # chunks + embeddings (uses .npy cache, encodes if missing)
    assert store.embeddings is not None
    dim = int(store.embeddings.shape[1])

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    coll = settings.qdrant_collection

    exists = client.collection_exists(coll)
    if args.recreate and exists:
        client.delete_collection(coll)
        exists = False
        log.info("dropped existing collection %s", coll)
    if not exists:
        client.create_collection(
            coll,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        client.create_payload_index(coll, field_name="project", field_schema=models.PayloadSchemaType.KEYWORD)
        log.info("created collection %s (%dd cosine)", coll, dim)

    points: list = []
    total = 0
    for i, ch in enumerate(store.chunks):
        if args.project and ch.project != args.project:
            continue
        points.append(
            models.PointStruct(
                id=str(uuid.uuid5(_NS, ch.id)),
                vector=store.embeddings[i].tolist(),
                payload={
                    "chunk_id": ch.id,
                    "project": ch.project,
                    "text": ch.text,
                    "is_faq": ch.is_faq,
                    "tokens": ch.tokens,
                    "chunk_order": ch.chunk_order,
                },
            )
        )
        if len(points) >= args.batch:
            client.upsert(coll, points=points)
            total += len(points)
            points = []
            log.info("upserted %d", total)
    if points:
        client.upsert(coll, points=points)
        total += len(points)
    log.info("done: %d points in %s", total, coll)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Lint the script**

Run: `ruff check scripts/build_qdrant.py`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_qdrant.py
git commit -m "feat(rag): scripts/build_qdrant.py — ingest FlatStore KB into Qdrant"
```

---

### Task 7: Boot warm + health/info + dead-code cleanup

**Files:**
- Modify: `src/noble_agent/transport/livekit/worker.py:110-125`
- Modify: `src/noble_agent/server/http.py:744-753` and `:822`
- Modify: `src/noble_agent/agent/rag/flat_store_adapter.py:104-196` (remove dead adapters)

- [ ] **Step 1: Remove dead adapters in flat_store_adapter.py**

In `src/noble_agent/agent/rag/flat_store_adapter.py`, delete everything from
the `# ─── Adapters for MemoryRouter ...` comment block (line ~104) to end of file:
`FlatStoreEmbeddingAdapter`, `FlatStoreVectorStoreAdapter`, and
`get_flat_store_adapters`. (They have no callers and import the deleted
`agent/rag/vector_store.py`.) Keep `_ensure_flat_store`, `_format_hits`, and
`query_flat_store_for_noble_kb`.

- [ ] **Step 2: Verify nothing imported them**

Run: `grep -rn "get_flat_store_adapters\|FlatStoreVectorStoreAdapter\|FlatStoreEmbeddingAdapter" src/ tests/ scripts/`
Expected: no matches.

- [ ] **Step 3: Fix `/api/config` provider + health probe in http.py**

In `src/noble_agent/server/http.py`, change line ~822:

```python
            "rag": {"provider": settings.noble_rag_backend},
```

And replace the `memory_router` Qdrant health probe (lines ~744-753) with a
backend-gated probe:

```python
        if (settings.noble_rag_backend or "").lower() == "qdrant":
            try:
                from qdrant_client import AsyncQdrantClient

                qc = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
                await qc.get_collections()
                services["qdrant"] = "ok"
                await qc.close()
            except Exception as e:
                services["qdrant"] = f"error: {e}"
```

- [ ] **Step 4: Warm the qdrant path in the LiveKit worker**

In `src/noble_agent/transport/livekit/worker.py`, where it warms the
flat_store (`_ensure_flat_store`), add backend-aware warm. Replace the warm block
(~lines 110-114) with:

```python
        from noble_agent.config import settings as _settings

        if (_settings.noble_rag_backend or "").lower() == "qdrant":
            from noble_agent.agent.rag.qdrant_adapter import _ensure_local

            _asyncio.run(_ensure_local())
        else:
            from noble_agent.agent.rag.flat_store_adapter import _ensure_flat_store

            _asyncio.run(_ensure_flat_store())
```

- [ ] **Step 5: Run the unified unit suite + lint**

Run: `pytest tests/unit/unified/ -q && make lint`
Expected: tests PASS, lint clean.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/rag/flat_store_adapter.py src/noble_agent/server/http.py src/noble_agent/transport/livekit/worker.py
git commit -m "chore(rag): qdrant warm + health/info, remove dead flat_store adapters"
```

---

### Task 8: Integration parity test (opt-in, `needs_qdrant`)

**Files:**
- Create: `tests/integration/unified/test_qdrant_parity.py`

- [ ] **Step 1: Open the tunnel and build the collection**

Run (in a separate shell, keep it open):
```
ssh -i "seoul-ai-dev.pem" -L 6333:localhost:6333 -L 6334:localhost:6334 \
  -L 6379:localhost:6379 -L 27017:localhost:27017 \
  ubuntu@ec2-3-37-136-28.ap-northeast-2.compute.amazonaws.com -N
```
Then: `python scripts/build_qdrant.py --recreate`
Expected: `done: <N> points in noble_kb_e5_1024d` where N == number of FlatStore chunks.

- [ ] **Step 2: Write the parity test**

Create `tests/integration/unified/test_qdrant_parity.py`:

```python
import os

import pytest

pytestmark = pytest.mark.needs_qdrant

_QUERIES = [
    ("giá bán căn hộ", "NCLB"),
    ("tiện ích dự án", "NTTL"),
    ("chính sách thanh toán", ""),
]


@pytest.mark.skipif(not os.getenv("QDRANT_URL"), reason="QDRANT_URL not set")
async def test_qdrant_topk_overlaps_flat_store():
    from noble_agent.agent.rag.flat_store_adapter import query_flat_store_for_noble_kb
    from noble_agent.agent.rag.qdrant_adapter import query_qdrant_for_noble_kb

    for query, proj in _QUERIES:
        flat = await query_flat_store_for_noble_kb(query, proj, top_k=5)
        qdr = await query_qdrant_for_noble_kb(query, proj, top_k=5)
        # Both return non-empty formatted blocks of the same shape.
        assert flat and qdr
        assert qdr.startswith("[Nguon 1 | Du an:")
        # Dense vectors are identical, BM25 identical → top hit should match.
        flat_top = flat.splitlines()[0]
        qdr_top = qdr.splitlines()[0]
        assert flat_top.split("]")[0] == qdr_top.split("]")[0] or flat[:80] == qdr[:80]
```

- [ ] **Step 3: Run the parity test**

Run: `QDRANT_URL=http://localhost:6333 pytest tests/integration/unified/test_qdrant_parity.py -m needs_qdrant -v`
Expected: PASS. If the top-hit assert is too strict in practice, relax to "top hit
of one appears within the other's top-5"; document the observed overlap in the commit
message.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/unified/test_qdrant_parity.py
git commit -m "test(rag): qdrant↔flat_store retrieval parity (needs_qdrant)"
```

---

### Task 9: Eval + latency verification (evidence, no new code)

**Files:** none (run + record).

- [ ] **Step 1: Answer-quality eval — flat_store baseline**

Run: `make eval-estate-smoke`
Record the score (section A, 5 cases).

- [ ] **Step 2: Answer-quality eval — qdrant backend**

Run: `NOBLE_RAG_BACKEND=qdrant QDRANT_URL=http://localhost:6333 make eval-estate-smoke`
Expected: score within noise of Step 1 (dense parity). If it regresses, STOP and
investigate ingestion (collection populated? right dim? right collection name?).

- [ ] **Step 3: Latency benchmark — both backends**

Run: `make bench` then `NOBLE_RAG_BACKEND=qdrant QDRANT_URL=http://localhost:6333 make bench`
Compare p95 TTFA. Record both numbers. Per the spec, the network round-trip is the
known risk; if p95 regresses materially, note it and surface the mitigation options
(co-locate agent with Qdrant / local dense fast-path) rather than silently shipping.

- [ ] **Step 4: Record results in the spec**

Append a short "## Results" section to
`docs/superpowers/specs/2026-06-08-qdrant-dense-backend-design.md` with the eval
scores and p95 numbers from Steps 1-3. Commit:

```bash
git add docs/superpowers/specs/2026-06-08-qdrant-dense-backend-design.md
git commit -m "docs(spec): record qdrant eval + latency results"
```

---

### Task 10: Update CLAUDE.md + final smoke

**Files:**
- Modify: `CLAUDE.md` (pluggable-backends list, RAG Stack, key-config table, Change Log)
- Reference: `src/noble_agent/SMOKE.md`

- [ ] **Step 1: Update CLAUDE.md**

- In **RAG retrieval** backends line, change to:
  `NOBLE_RAG_BACKEND={flat_store, qdrant, grep_faq, empty}` (default `flat_store`).
- In the **RAG Stack** section, add a subsection describing the qdrant dense path:
  Qdrant owns dense (e5-large 1024d, cosine); BM25 stays local; RRF fused in
  `qdrant_adapter`; ingest via `python scripts/build_qdrant.py`.
- In the **Key configuration** table add rows for `QDRANT_URL`, `QDRANT_API_KEY`,
  `QDRANT_COLLECTION` (default `noble_kb_e5_1024d`).
- Append a Change Log row:
  `| 2026-06-08 | Added opt-in qdrant RAG backend (dense via Qdrant + local BM25 RRF); scripts/build_qdrant.py ingestion; removed dead flat_store adapters; fixed /api/config rag.provider + health probe. | User wanted the vector store centralized (shared across instances, updatable without redeploy). |`

- [ ] **Step 2: Run the smoke checklist**

Follow `src/noble_agent/SMOKE.md` for the turn-loop / prompt path (text chat
at `/chat`), once with default `flat_store` and once with `NOBLE_RAG_BACKEND=qdrant`
(tunnel up). Confirm `noble_search` returns context and the agent answers.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — qdrant RAG backend + config"
```

---

## Self-Review

**Spec coverage:**
- Opt-in `qdrant` backend, flat_store default → Tasks 1, 5. ✓
- Dense-only via Qdrant, query uses shared `_Embedder` → Tasks 3, 4. ✓
- BM25 local + RRF in code → Task 4 (`_ensure_local` loads BM25; RRF on chunk_id). ✓
- Fresh e5 collection, reuse env → Task 1. ✓
- `qdrant_store.py`, `qdrant_adapter.py`, `build_qdrant.py` → Tasks 3, 4, 6. ✓
- `load_chunks_only` (BM25 without .npy) → Task 2. ✓
- Resilience (BM25-only fallback) → Task 4 + 5. ✓
- Cleanup (dead adapters, /api/config, health probe) → Task 7. ✓
- `qdrant-client` optional extra, lazy import → Tasks 1, 3. ✓
- Verification: unit/integration/eval/latency → Tasks 4, 8, 9. ✓
- CLAUDE.md updates → Task 10. ✓

**Placeholder scan:** No TBD/TODO; every code step has full code. ✓

**Type consistency:** `search_dense → list[(chunk_id, project, text, score)]` used
identically in qdrant_store (Task 3) and qdrant_adapter (Task 4). `_bm25_topk`
returns `[(local_index, score)]` (existing FlatStore signature) consumed in Task 4.
`load_chunks_only()` defined in Task 2, called in Task 4. `query_qdrant_for_noble_kb`
signature consistent across Tasks 4, 5, 8, 9. `_format_hits` reused from
flat_store_adapter (kept in Task 7). ✓
