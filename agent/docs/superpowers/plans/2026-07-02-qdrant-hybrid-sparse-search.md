# Qdrant Hybrid Sparse Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move BM25 (sparse) scoring and RRF fusion onto Qdrant via an app-owned *clone* collection, keeping a disk-persisted local BM25 fallback rebuilt from the same source.

**Architecture:** At server-agent startup a one-shot reconcile clones the other team's read-only root collection into an app-owned collection, attaching a pyvi/fixed-avgdl BM25 **sparse vector** (IDF computed by Qdrant) to each point and persisting a local `bm25s` fallback index built from the same snapshot. Queries run one Qdrant Query-API request (dense + sparse prefetch → server-side RRF, pre-filtered by `project_id`); on Qdrant error they fall back to the on-disk BM25 index.

**Tech Stack:** Python 3.11–3.13, `qdrant-client>=1.10` (async, Query API), `bm25s`, `pyvi`, existing remote e5-large embed service, pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Scope is the `NOBLE_RAG_BACKEND=qdrant` path ONLY. The `flat_store` default backend is untouched — verbatim from spec §1/§10.
- Payload contract keys (verbatim from spec §3): `project_id` (canonical code, filter key), `text`, `content_hash`, `chunk_index`, `project_name`. Legacy keys `project`/`chunk_id`/`is_faq`/`tokens`/`chunk_order` MUST NOT be assumed on the live collection.
- Chunk identity = Qdrant `point.id` copied verbatim from root. `content_hash` is NOT used as an identity key.
- IDF is computed by Qdrant (`models.Modifier.IDF`); doc-side sparse weights use a **fixed** `AVGDL`/`K1`/`B` so a chunk's sparse vector is a pure function of its own text.
- Sparse term ids MUST use a process-stable hash (`hashlib`, never builtin `hash()`).
- The reconcile runs ONLY in the aiortc `run_server` process (single process, no lock), NOT in `transport/livekit/worker.py`.
- Branch: `feat/seperate-service`. Local commits only; do not touch `develop`, do not push/PR without explicit instruction (CLAUDE.md).
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Pytest `asyncio_mode=auto`.
- `qdrant-client` is the `rag-qdrant` optional extra — import it lazily inside functions so `make test-unit` collects without it. `bm25s`/`pyvi` are core deps (always present).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/noble_agent/config.py` (modify ~L400) | New settings: root/clone collection names, dense/sparse vector names, fallback dir. |
| `src/noble_agent/agent/rag/sparse_encoder.py` (new) | pyvi + fixed-avgdl BM25 sparse encoder for docs and queries. Stateless. |
| `src/noble_agent/agent/rag/bm25_fallback.py` (new) | Disk-persisted `bm25s` local fallback: build + load + search. |
| `src/noble_agent/agent/rag/qdrant_store.py` (rewrite) | Async Qdrant client: collection (re)create + hybrid Query-API search on the clone. |
| `src/noble_agent/agent/rag/sparse_reconcile.py` (new) | One-shot: read root → upsert dense+sparse into clone → build local fallback. Standalone `main()`. |
| `src/noble_agent/agent/rag/qdrant_adapter.py` (rewrite) | Entry `query_qdrant_for_noble_kb`: hybrid on clone, fallback to `bm25_fallback` on error. |
| `src/noble_agent/server/http.py` (modify ~L980) | Await reconcile after prewarm, gated on backend==qdrant. |
| `pyproject.toml` (modify L53-57) | `noble-rag-sync` console script. |
| `tests/unit/unified/rag/…` (new) | Unit tests per module (fake Qdrant client). |

Reused verbatim (import, do not duplicate): `Chunk`, `SearchHit`, `_tokenize_vi` from `noble_agent.agent.rag.flat_store`; `_format_hits` from `noble_agent.agent.rag.flat_store_adapter`.

---

## Task 1: Config fields

**Files:**
- Modify: `src/noble_agent/config.py` (the Qdrant block, ~L400-404)
- Test: `tests/unit/unified/rag/test_qdrant_config.py`

**Interfaces:**
- Produces: `settings.qdrant_collection_root: str`, `settings.qdrant_collection: str` (now the *clone*), `settings.qdrant_dense_vector_name: str = "dense"`, `settings.qdrant_sparse_vector_name: str = "bm25"`, `settings.qdrant_fallback_dir: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_qdrant_config.py
from noble_agent.config import UnifiedSettings


def test_qdrant_hybrid_settings_defaults():
    s = UnifiedSettings()
    assert s.qdrant_collection_root == ""
    assert s.qdrant_collection == "noble_kb_hybrid"
    assert s.qdrant_dense_vector_name == "dense"
    assert s.qdrant_sparse_vector_name == "bm25"
    assert s.qdrant_fallback_dir.endswith("bm25_qdrant_fallback")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_qdrant_config.py -v`
Expected: FAIL (`AttributeError: ... qdrant_collection_root` or default mismatch).

- [ ] **Step 3: Edit the Qdrant block in config.py**

Replace the existing lines:
```python
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "noble_kb_e5_1024d"
```
with:
```python
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    # Root = other team's read-only source collection; clone = app-owned collection
    # we (re)build with dense + BM25 sparse and run all searches against.
    qdrant_collection_root: str = ""
    qdrant_collection: str = "noble_kb_hybrid"
    qdrant_dense_vector_name: str = "dense"
    qdrant_sparse_vector_name: str = "bm25"
    # On-disk BM25 fallback (built by sparse_reconcile from the same root snapshot).
    qdrant_fallback_dir: str = str(
        Path(__file__).resolve().parent.parent.parent / "data" / "flat_store" / "bm25_qdrant_fallback"
    )
```

Ensure `from pathlib import Path` is imported at the top of `config.py` (it already imports `os`; add `Path` if absent).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_qdrant_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/config.py tests/unit/unified/rag/test_qdrant_config.py
git commit -m "feat(rag): qdrant hybrid config (root+clone collections, sparse vector names, fallback dir)"
```

---

## Task 2: Sparse encoder

**Files:**
- Create: `src/noble_agent/agent/rag/sparse_encoder.py`
- Test: `tests/unit/unified/rag/test_sparse_encoder.py`

**Interfaces:**
- Consumes: `_tokenize_vi` from `noble_agent.agent.rag.flat_store`.
- Produces:
  - `encode_document(text: str) -> tuple[list[int], list[float]]` — (indices, values) BM25 doc weights, fixed avgdl.
  - `encode_query(text: str) -> tuple[list[int], list[float]]` — (indices, values) query weights (1.0 per unique term).
  - Module constants `AVGDL = 256.0`, `K1 = 1.5`, `B = 0.75`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_sparse_encoder.py
from noble_agent.agent.rag import sparse_encoder as se


def test_encode_document_is_deterministic():
    a = se.encode_document("căn hộ Noble Crystal Tây Hồ giá bao nhiêu")
    b = se.encode_document("căn hộ Noble Crystal Tây Hồ giá bao nhiêu")
    assert a == b
    idx, val = a
    assert len(idx) == len(val) > 0
    assert all(isinstance(i, int) and i >= 0 for i in idx)
    assert all(v > 0 for v in val)


def test_query_encoding_is_unit_weighted():
    idx, val = se.encode_query("giá căn hộ giá")
    assert all(v == 1.0 for v in val)
    # duplicate token collapses to one index
    assert len(idx) == len(set(idx))


def test_repeated_term_saturates_below_linear():
    once, _ = None, None
    idx1, val1 = se.encode_document("giá")
    idx3, val3 = se.encode_document("giá giá giá")
    w1 = dict(zip(idx1, val1))
    w3 = dict(zip(idx3, val3))
    term = idx1[0]
    # tf=3 weight is higher than tf=1 but less than 3x (BM25 saturation)
    assert w3[term] > w1[term]
    assert w3[term] < 3 * w1[term]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_sparse_encoder.py -v`
Expected: FAIL (`ModuleNotFoundError: ... sparse_encoder`).

- [ ] **Step 3: Implement `sparse_encoder.py`**

```python
# src/noble_agent/agent/rag/sparse_encoder.py
"""Stateless BM25 sparse-vector encoder for Qdrant (pyvi tokenization).

Document weights use a FIXED avgdl so a chunk's sparse vector depends only on
its own text (never stale vs the corpus). IDF is applied by Qdrant at query
time via SparseVectorParams(modifier=Modifier.IDF) — NOT here.

Term ids are a process-stable blake2b hash of the token (never builtin hash()).
"""

from __future__ import annotations

import hashlib
from collections import Counter

from noble_agent.agent.rag.flat_store import _tokenize_vi

AVGDL = 256.0
K1 = 1.5
B = 0.75


def _term_id(token: str) -> int:
    """Stable uint32 id for a token (deterministic across processes/runs)."""
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(), "big")


def encode_document(text: str) -> tuple[list[int], list[float]]:
    """BM25 document-side sparse weights with fixed avgdl. Returns (indices, values)."""
    tokens = _tokenize_vi(text or "")
    if not tokens:
        return [], []
    dl = len(tokens)
    tf: Counter[int] = Counter(_term_id(t) for t in tokens)
    norm = K1 * (1.0 - B + B * dl / AVGDL)
    indices: list[int] = []
    values: list[float] = []
    for tid, f in tf.items():
        indices.append(tid)
        values.append(f * (K1 + 1.0) / (f + norm))
    return indices, values


def encode_query(text: str) -> tuple[list[int], list[float]]:
    """Query-side sparse weights: 1.0 per unique term (IDF applied by Qdrant)."""
    tokens = _tokenize_vi(text or "")
    if not tokens:
        return [], []
    uniq = list(dict.fromkeys(_term_id(t) for t in tokens))
    return uniq, [1.0] * len(uniq)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_sparse_encoder.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/sparse_encoder.py tests/unit/unified/rag/test_sparse_encoder.py
git commit -m "feat(rag): pyvi/fixed-avgdl BM25 sparse encoder for Qdrant"
```

---

## Task 3: Local BM25 fallback store

**Files:**
- Create: `src/noble_agent/agent/rag/bm25_fallback.py`
- Test: `tests/unit/unified/rag/test_bm25_fallback.py`

**Interfaces:**
- Consumes: `Chunk`, `SearchHit`, `_tokenize_vi` from `flat_store`.
- Produces:
  - `build(chunks: list[Chunk], out_dir: str) -> None` — write bm25s index + `chunks.json` ({id, project, text}).
  - `search(query: str, project_filter: str, top_k: int, out_dir: str) -> list[SearchHit]` — lazy-load (process-cached) + BM25-only, post-filtered by project.
  - `reset_cache() -> None` — test helper to drop the in-process cache.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_bm25_fallback.py
import pytest

from noble_agent.agent.rag import bm25_fallback as fb
from noble_agent.agent.rag.flat_store import Chunk


@pytest.fixture(autouse=True)
def _clear():
    fb.reset_cache()
    yield
    fb.reset_cache()


def _chunks():
    return [
        Chunk(id="p1", project="NCTH", text="Noble Crystal Tây Hồ căn hộ ba phòng ngủ view hồ"),
        Chunk(id="p2", project="SGR", text="Sunshine Grand City tiện ích bể bơi giá gốc"),
        Chunk(id="p3", project="NCTH", text="Noble Crystal Tây Hồ pháp lý sổ hồng lâu dài"),
    ]


def test_build_then_search_returns_hits(tmp_path):
    d = str(tmp_path / "fb")
    fb.build(_chunks(), d)
    hits = fb.search("căn hộ Tây Hồ", project_filter="", top_k=2, out_dir=d)
    assert hits
    assert all(h.chunk.project for h in hits)


def test_project_filter_restricts_results(tmp_path):
    d = str(tmp_path / "fb")
    fb.build(_chunks(), d)
    hits = fb.search("Noble Crystal", project_filter="NCTH", top_k=5, out_dir=d)
    assert hits
    assert {h.chunk.project for h in hits} == {"NCTH"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_bm25_fallback.py -v`
Expected: FAIL (`ModuleNotFoundError: ... bm25_fallback`).

- [ ] **Step 3: Implement `bm25_fallback.py`**

```python
# src/noble_agent/agent/rag/bm25_fallback.py
"""Disk-persisted local BM25 fallback for the Qdrant hybrid path.

Built by sparse_reconcile from the SAME root snapshot pushed to Qdrant, so the
fallback describes the same corpus. Used only when the Qdrant query errors.
"""

from __future__ import annotations

import json
import logging
import os

import bm25s

from noble_agent.agent.rag.flat_store import Chunk, SearchHit, _tokenize_vi

logger = logging.getLogger("rag.bm25_fallback")

_CHUNKS_FILE = "chunks.json"

# process-level cache: out_dir -> (retriever, chunks)
_cache: dict[str, tuple[object, list[Chunk]]] = {}


def reset_cache() -> None:
    _cache.clear()


def build(chunks: list[Chunk], out_dir: str) -> None:
    """Index chunks with bm25s and persist index + chunk metadata to out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    tokenized = [_tokenize_vi(c.text) for c in chunks]
    retriever = bm25s.BM25(method="lucene")
    retriever.index(tokenized)
    retriever.save(os.path.join(out_dir, "index"))
    with open(os.path.join(out_dir, _CHUNKS_FILE), "w", encoding="utf-8") as fh:
        json.dump([{"id": c.id, "project": c.project, "text": c.text} for c in chunks], fh, ensure_ascii=False)
    _cache.pop(out_dir, None)
    logger.info("[bm25_fallback] built %d chunks → %s", len(chunks), out_dir)


def _load(out_dir: str) -> tuple[object, list[Chunk]]:
    cached = _cache.get(out_dir)
    if cached is not None:
        return cached
    retriever = bm25s.BM25.load(os.path.join(out_dir, "index"))
    with open(os.path.join(out_dir, _CHUNKS_FILE), encoding="utf-8") as fh:
        rows = json.load(fh)
    chunks = [Chunk(id=r["id"], project=r["project"], text=r["text"]) for r in rows]
    _cache[out_dir] = (retriever, chunks)
    logger.info("[bm25_fallback] loaded %d chunks from %s", len(chunks), out_dir)
    return retriever, chunks


def search(query: str, project_filter: str, top_k: int, out_dir: str) -> list[SearchHit]:
    """BM25-only search, post-filtered by project. Returns [] if artifact missing."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        retriever, chunks = _load(out_dir)
    except Exception as exc:
        logger.warning("[bm25_fallback] load failed (%s) — no fallback available", exc)
        return []
    over_k = min(top_k * 10 if project_filter else top_k, len(chunks))
    if over_k <= 0:
        return []
    q_tokens = _tokenize_vi(query)
    ids_arr, scores_arr = retriever.retrieve([q_tokens], k=over_k)
    ids = ids_arr[0].tolist()
    scores = scores_arr[0].tolist()
    hits: list[SearchHit] = []
    for i, s in zip(ids, scores):
        ch = chunks[int(i)]
        if project_filter and ch.project != project_filter:
            continue
        hits.append(SearchHit(chunk=ch, score=float(s)))
        if len(hits) >= top_k:
            break
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_bm25_fallback.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/bm25_fallback.py tests/unit/unified/rag/test_bm25_fallback.py
git commit -m "feat(rag): disk-persisted local BM25 fallback store for qdrant path"
```

---

## Task 4: Qdrant store — collection setup + hybrid query

**Files:**
- Rewrite: `src/noble_agent/agent/rag/qdrant_store.py`
- Test: `tests/unit/unified/rag/test_qdrant_store.py`

**Interfaces:**
- Consumes: `settings.qdrant_*`; `sparse_encoder.encode_query`.
- Produces:
  - `async search_hybrid(dense_vec: list[float], sparse_idx: list[int], sparse_val: list[float], project_filter: str, top_k: int) -> list[tuple[str, str, str, float]]` — returns `[(point_id, project_id, text, score)]`.
  - `async recreate_clone(dim: int, distance) -> None` — drop+create clone with named dense + IDF sparse + `project_id` index.
  - `async get_root_dense_params() -> tuple[int, object]` — `(dim, distance)` read from root collection config.
  - `async iter_root_points(batch: int = 256)` — async generator yielding `(point_id, dense_list, payload)` from root.
  - `async upsert_clone_points(points: list) -> None`.
  - `async close() -> None`.
  - `_get_client()` singleton (AsyncQdrantClient).

- [ ] **Step 1: Write the failing test** (fake async client — no live Qdrant)

```python
# tests/unit/unified/rag/test_qdrant_store.py
import pytest

from noble_agent.agent.rag import qdrant_store as qs


class _FakePoint:
    def __init__(self, id, payload, score=0.0):
        self.id = id
        self.payload = payload
        self.score = score


class _FakeResp:
    def __init__(self, points):
        self.points = points


class _FakeClient:
    def __init__(self):
        self.last_kwargs = None

    async def query_points(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp([
            _FakePoint("p1", {"project_id": "NCTH", "text": "Noble Crystal Tây Hồ"}, 0.9),
            _FakePoint("p2", {"project_id": "NCTH", "text": "view hồ"}, 0.7),
        ])


@pytest.fixture
def fake(monkeypatch):
    c = _FakeClient()
    monkeypatch.setattr(qs, "_get_client", lambda: c)
    return c


async def test_search_hybrid_builds_prefetch_and_maps_payload(fake, monkeypatch):
    monkeypatch.setattr(qs.settings, "qdrant_collection", "clone")
    monkeypatch.setattr(qs.settings, "qdrant_dense_vector_name", "dense")
    monkeypatch.setattr(qs.settings, "qdrant_sparse_vector_name", "bm25")
    out = await qs.search_hybrid([0.1, 0.2], [10, 20], [1.0, 1.0], project_filter="NCTH", top_k=2)
    assert out == [("p1", "NCTH", "Noble Crystal Tây Hồ", 0.9), ("p2", "NCTH", "view hồ", 0.7)]
    kw = fake.last_kwargs
    assert kw["collection_name"] == "clone"
    assert len(kw["prefetch"]) == 2  # dense + sparse
    assert kw["query_filter"] is not None  # project_id filter applied


async def test_search_hybrid_no_filter_omits_query_filter(fake, monkeypatch):
    monkeypatch.setattr(qs.settings, "qdrant_collection", "clone")
    await qs.search_hybrid([0.1], [1], [1.0], project_filter="", top_k=3)
    assert fake.last_kwargs["query_filter"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_qdrant_store.py -v`
Expected: FAIL (`AttributeError: ... search_hybrid`).

- [ ] **Step 3: Rewrite `qdrant_store.py`**

```python
# src/noble_agent/agent/rag/qdrant_store.py
"""Qdrant hybrid retrieval on the app-owned CLONE collection.

Clone stores a named dense vector + a named BM25 sparse vector (IDF applied by
Qdrant). Search fuses both server-side via the Query API (RRF), pre-filtered by
project_id. Also exposes the clone (re)build helpers used by sparse_reconcile.

qdrant-client is imported lazily (optional extra `rag-qdrant`).
"""

from __future__ import annotations

import contextlib
import logging

from noble_agent.config import settings

logger = logging.getLogger("rag.qdrant_store")

_client = None  # AsyncQdrantClient singleton


def _get_client():
    global _client
    if _client is not None:
        return _client
    from qdrant_client import AsyncQdrantClient

    _client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    logger.info("[qdrant_store] client → %s", settings.qdrant_url)
    return _client


def _project_filter(project_filter: str):
    from qdrant_client import models

    if not project_filter:
        return None
    return models.Filter(
        must=[models.FieldCondition(key="project_id", match=models.MatchValue(value=project_filter))]
    )


async def search_hybrid(
    dense_vec: list[float],
    sparse_idx: list[int],
    sparse_val: list[float],
    project_filter: str,
    top_k: int,
) -> list[tuple[str, str, str, float]]:
    """Dense + sparse prefetch → server-side RRF fusion. Returns [(id, project_id, text, score)]."""
    from qdrant_client import models

    client = _get_client()
    flt = _project_filter(project_filter)
    candidates = max(top_k * 4, 20)
    resp = await client.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            models.Prefetch(
                query=dense_vec,
                using=settings.qdrant_dense_vector_name,
                limit=candidates,
                filter=flt,
            ),
            models.Prefetch(
                query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                using=settings.qdrant_sparse_vector_name,
                limit=candidates,
                filter=flt,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
        query_filter=flt,
        with_payload=True,
    )
    out: list[tuple[str, str, str, float]] = []
    for p in resp.points:
        pl = p.payload or {}
        out.append((str(p.id), pl.get("project_id", "?"), pl.get("text", ""), float(p.score)))
    return out


async def get_root_dense_params() -> tuple[int, object]:
    """Read (dim, distance) from the root collection's dense vector config."""
    client = _get_client()
    info = await client.get_collection(settings.qdrant_collection_root)
    vectors = info.config.params.vectors
    if isinstance(vectors, dict):
        params = next(iter(vectors.values()))
    else:
        params = vectors
    return int(params.size), params.distance


async def recreate_clone(dim: int, distance) -> None:
    """Drop + create the clone with named dense + IDF sparse + project_id index."""
    from qdrant_client import models

    client = _get_client()
    coll = settings.qdrant_collection
    if await client.collection_exists(coll):
        await client.delete_collection(coll)
    await client.create_collection(
        collection_name=coll,
        vectors_config={settings.qdrant_dense_vector_name: models.VectorParams(size=dim, distance=distance)},
        sparse_vectors_config={
            settings.qdrant_sparse_vector_name: models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    await client.create_payload_index(
        coll, field_name="project_id", field_schema=models.PayloadSchemaType.KEYWORD
    )
    logger.info("[qdrant_store] recreated clone %s (dim=%d)", coll, dim)


async def iter_root_points(batch: int = 256):
    """Yield (point_id, dense_list, payload) from the root collection."""
    client = _get_client()
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=settings.qdrant_collection_root,
            with_vectors=True,
            with_payload=True,
            limit=batch,
            offset=offset,
        )
        for p in points:
            vec = p.vector
            if isinstance(vec, dict):
                vec = next(iter(vec.values()))
            yield p.id, list(vec), (p.payload or {})
        if offset is None:
            break


async def upsert_clone_points(points: list) -> None:
    """Upsert prepared PointStructs into the clone."""
    client = _get_client()
    await client.upsert(collection_name=settings.qdrant_collection, points=points)


async def close() -> None:
    global _client
    if _client is not None:
        with contextlib.suppress(Exception):
            await _client.close()
        _client = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_qdrant_store.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/qdrant_store.py tests/unit/unified/rag/test_qdrant_store.py
git commit -m "feat(rag): qdrant_store hybrid Query-API search + clone (re)build helpers"
```

---

## Task 5: Reconcile (build clone + local fallback)

**Files:**
- Create: `src/noble_agent/agent/rag/sparse_reconcile.py`
- Test: `tests/unit/unified/rag/test_sparse_reconcile.py`

**Interfaces:**
- Consumes: `qdrant_store` (recreate/iter/upsert/get_root_dense_params), `sparse_encoder.encode_document`, `bm25_fallback.build`, `Chunk` from `flat_store`, `settings`.
- Produces:
  - `async reconcile() -> int` — returns number of points synced.
  - `main() -> None` — `asyncio.run(reconcile())` for the console script.

- [ ] **Step 1: Write the failing test** (monkeypatch qdrant_store + bm25_fallback)

```python
# tests/unit/unified/rag/test_sparse_reconcile.py
import pytest

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
    assert len(upserted) == 2
    assert built["n"] == 2


async def test_reconcile_noop_when_root_unset(monkeypatch):
    monkeypatch.setattr(sr.settings, "qdrant_collection_root", "")
    assert await sr.reconcile() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_sparse_reconcile.py -v`
Expected: FAIL (`ModuleNotFoundError: ... sparse_reconcile`).

- [ ] **Step 3: Implement `sparse_reconcile.py`**

```python
# src/noble_agent/agent/rag/sparse_reconcile.py
"""One-shot: clone the root Qdrant collection into the app-owned clone with a
BM25 sparse vector per point, and build the local BM25 fallback from the same
snapshot. Runs once at server-agent startup (single process, no lock) and is
also a standalone console command (`noble-rag-sync`).
"""

from __future__ import annotations

import logging

from noble_agent.agent.rag import bm25_fallback, qdrant_store, sparse_encoder
from noble_agent.agent.rag.flat_store import Chunk
from noble_agent.config import settings

logger = logging.getLogger("rag.sparse_reconcile")


async def reconcile() -> int:
    """Rebuild the clone (dense+sparse) and the local fallback from root. Returns point count."""
    if not settings.qdrant_collection_root:
        logger.warning("[reconcile] QDRANT_COLLECTION_ROOT unset — skipping")
        return 0

    from qdrant_client import models

    dim, distance = await qdrant_store.get_root_dense_params()
    await qdrant_store.recreate_clone(dim, distance)

    dense_name = settings.qdrant_dense_vector_name
    sparse_name = settings.qdrant_sparse_vector_name

    batch_points: list = []
    chunks: list[Chunk] = []
    total = 0

    async for point_id, dense_vec, payload in qdrant_store.iter_root_points():
        text = payload.get("text", "") or ""
        project_id = payload.get("project_id", "") or ""
        idx, val = sparse_encoder.encode_document(text)
        batch_points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    dense_name: dense_vec,
                    sparse_name: models.SparseVector(indices=idx, values=val),
                },
                payload=payload,
            )
        )
        chunks.append(Chunk(id=str(point_id), project=project_id, text=text))
        total += 1
        if len(batch_points) >= 256:
            await qdrant_store.upsert_clone_points(batch_points)
            batch_points = []

    if batch_points:
        await qdrant_store.upsert_clone_points(batch_points)

    bm25_fallback.build(chunks, settings.qdrant_fallback_dir)
    logger.info("[reconcile] synced %d points → clone + local fallback", total)
    return total


def main() -> None:
    import asyncio

    from noble_agent.server.logging_config import setup_logging

    setup_logging()
    asyncio.run(reconcile())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_sparse_reconcile.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/sparse_reconcile.py tests/unit/unified/rag/test_sparse_reconcile.py
git commit -m "feat(rag): sparse_reconcile — clone root→app collection + local BM25 fallback"
```

---

## Task 6: Adapter rewrite (hybrid + fallback dispatch)

**Files:**
- Rewrite: `src/noble_agent/agent/rag/qdrant_adapter.py`
- Test: `tests/unit/unified/rag/test_qdrant_adapter.py`

**Interfaces:**
- Consumes: `qdrant_store.search_hybrid`, `sparse_encoder.encode_query`, `bm25_fallback.search`, `_format_hits` from `flat_store_adapter`, the remote embed via `flat_store.FlatStore().embedder` OR a lightweight embedder. See Step 3 note.
- Produces: `async query_qdrant_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str` (unchanged signature — `noble_kb._query_via_qdrant` already calls it).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_qdrant_adapter.py
import numpy as np
import pytest

from noble_agent.agent.rag import qdrant_adapter as qa
from noble_agent.agent.rag.flat_store import Chunk, SearchHit


@pytest.fixture(autouse=True)
def _stub_embed(monkeypatch):
    # Avoid loading any embed model in unit tests.
    monkeypatch.setattr(qa, "_embed_query", lambda q: [0.1, 0.2, 0.3])


async def test_happy_path_uses_qdrant_hybrid(monkeypatch):
    async def fake_hybrid(dense, sidx, sval, project_filter, top_k):
        return [("p1", "NCTH", "Noble Crystal Tây Hồ", 0.9)]

    monkeypatch.setattr(qa.qdrant_store, "search_hybrid", fake_hybrid)
    out = await qa.query_qdrant_for_noble_kb("căn hộ Tây Hồ", "NCTH", top_k=3)
    assert "Noble Crystal Tây Hồ" in out
    assert "NCTH" in out


async def test_falls_back_to_local_bm25_on_qdrant_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("qdrant down")

    def fake_fb(query, project_filter, top_k, out_dir):
        return [SearchHit(chunk=Chunk(id="p3", project="NCTH", text="pháp lý sổ hồng"), score=1.2)]

    monkeypatch.setattr(qa.qdrant_store, "search_hybrid", boom)
    monkeypatch.setattr(qa.bm25_fallback, "search", fake_fb)
    out = await qa.query_qdrant_for_noble_kb("pháp lý", "NCTH", top_k=3)
    assert "pháp lý sổ hồng" in out


async def test_empty_query_returns_empty():
    assert await qa.query_qdrant_for_noble_kb("  ", "NCTH") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_qdrant_adapter.py -v`
Expected: FAIL (old adapter signature/behavior — `_embed_query` attr missing, hybrid path absent).

- [ ] **Step 3: Rewrite `qdrant_adapter.py`**

Note: dense query embedding reuses the existing FlatStore `_Embedder` (which already honors the remote embed service via `EMBED_REMOTE_URL`). We instantiate a bare embedder (no chunk/BM25 load) so no local corpus is required.

```python
# src/noble_agent/agent/rag/qdrant_adapter.py
"""Qdrant hybrid entrypoint for noble_kb.

Happy path: embed query (remote e5) + sparse-encode query (local pyvi) → one
Qdrant Query-API request (dense+sparse prefetch → server-side RRF), pre-filtered
by project_id. On any Qdrant error → local disk BM25 fallback (sparse-only).
"""

from __future__ import annotations

import asyncio
import logging

from noble_agent.agent.rag import bm25_fallback, qdrant_store, sparse_encoder
from noble_agent.agent.rag.flat_store import Chunk, SearchHit
from noble_agent.agent.rag.flat_store_adapter import _format_hits
from noble_agent.config import settings

logger = logging.getLogger("rag.qdrant_adapter")

_embedder = None


def _embed_query(query: str) -> list[float]:
    """Dense query vector via the shared FlatStore embedder (remote-aware)."""
    global _embedder
    if _embedder is None:
        from noble_agent.agent.rag.flat_store import _Embedder

        _embedder = _Embedder()
    return _embedder.encode_query(query).tolist()


async def query_qdrant_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str:
    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return ""

    loop = asyncio.get_event_loop()
    try:
        dense = await loop.run_in_executor(None, _embed_query, query)
        s_idx, s_val = sparse_encoder.encode_query(query)
        rows = await qdrant_store.search_hybrid(dense, s_idx, s_val, project_filter, top_k)
        hits = [SearchHit(chunk=Chunk(id=pid, project=proj, text=text), score=score) for pid, proj, text, score in rows]
        return _format_hits(hits)
    except Exception as exc:
        logger.warning("[qdrant_adapter] hybrid failed (%s) — local BM25 fallback", exc)
        hits = await loop.run_in_executor(
            None, bm25_fallback.search, query, project_filter, top_k, settings.qdrant_fallback_dir
        )
        return _format_hits(hits)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_qdrant_adapter.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/qdrant_adapter.py tests/unit/unified/rag/test_qdrant_adapter.py
git commit -m "feat(rag): qdrant_adapter server-side hybrid + local BM25 fallback (project_id payload)"
```

---

## Task 7: Wire startup reconcile + console script

**Files:**
- Modify: `src/noble_agent/server/http.py` (~L977-980, after prewarm)
- Modify: `pyproject.toml` (L53-57 scripts block)
- Test: `tests/unit/unified/rag/test_startup_reconcile_gate.py`

**Interfaces:**
- Consumes: `sparse_reconcile.reconcile`, `settings.noble_rag_backend`.
- Produces: `async _maybe_reconcile_qdrant() -> None` in `http.py` (gated + guarded); console script `noble-rag-sync`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_startup_reconcile_gate.py
import pytest

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_startup_reconcile_gate.py -v`
Expected: FAIL (`AttributeError: ... _maybe_reconcile_qdrant`).

- [ ] **Step 3a: Add the gated helper + call it in `http.py`**

Add this function near the other module-level helpers in `http.py` (top-level, after imports):

```python
async def _maybe_reconcile_qdrant() -> None:
    """Rebuild the Qdrant clone + local BM25 fallback once at server-agent
    startup. Gated on the qdrant backend; failures log and never wedge boot."""
    import logging

    from noble_agent.config import settings

    if (settings.noble_rag_backend or "").lower() != "qdrant":
        return
    log = logging.getLogger("server")
    try:
        from noble_agent.agent.rag.sparse_reconcile import reconcile

        log.info("Reconciling Qdrant hybrid clone (dense+sparse) + local fallback ...")
        n = await reconcile()
        log.info("Qdrant reconcile done: %d points", n)
    except Exception as exc:  # noqa: BLE001 — boot must survive a reconcile failure
        log.error("Qdrant reconcile failed (continuing): %s", exc)
```

Then in `_run_server_async`, immediately after the `prewarm_voice_models()` block (after L980), add:

```python
    await _maybe_reconcile_qdrant()
```

- [ ] **Step 3b: Add the console script in `pyproject.toml`**

In `[project.scripts]`, add the line:
```toml
noble-rag-sync = "noble_agent.agent.rag.sparse_reconcile:main"
```

- [ ] **Step 4: Run test + reinstall entrypoint**

Run: `pytest tests/unit/unified/rag/test_startup_reconcile_gate.py -v`
Expected: PASS (2 tests).
Then: `pip install -e . -q` (registers `noble-rag-sync`).
Verify: `noble-rag-sync --help 2>/dev/null || python -c "from noble_agent.agent.rag.sparse_reconcile import main; print('ok')"`
Expected: prints `ok` (import wiring valid).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/http.py pyproject.toml tests/unit/unified/rag/test_startup_reconcile_gate.py
git commit -m "feat(rag): run qdrant reconcile at server-agent startup + noble-rag-sync command"
```

---

## Task 8: Full-suite verification + eval parity

**Files:** none (verification only).

- [ ] **Step 1: Lint**

Run: `make lint`
Expected: no errors on the new/changed files. Fix any ruff `E,F,W,I,UP,B,SIM` findings inline.

- [ ] **Step 2: Full RAG unit tests**

Run: `pytest tests/unit/unified/rag -v`
Expected: all tasks 1–7 tests PASS.

- [ ] **Step 3: Regression — flat_store path untouched**

Run: `pytest tests/unit/unified -k "rag or noble_kb or flat_store" -v`
Expected: PASS (default backend behavior unchanged).

- [ ] **Step 4: Answer-quality smoke (optional — needs live services)**

Run: `NOBLE_RAG_BACKEND=qdrant make eval-estate-smoke`
Expected: completes; spot-check that answers are non-empty and on-topic vs the `flat_store` baseline. If Qdrant/embed services are unavailable locally, skip and note it.

- [ ] **Step 5: Final commit (only if lint fixes were made)**

```bash
git add -A
git commit -m "chore(rag): lint fixes for qdrant hybrid sparse search"
```

---

## Self-Review notes (author)

- **Spec coverage:** D1 sparse-on-Qdrant → Task 2/4/5; D2 clone collection → Task 4 (`recreate_clone`/`iter_root_points`) + Task 1 config; D3 startup one-shot → Task 7; D4 recreate-before-traffic → Task 5 `reconcile` + Task 7 `await` before `serve`; D5 local fallback from same snapshot → Task 3 + Task 5 `bm25_fallback.build`; D6 IDF modifier + fixed avgdl → Task 4 `SparseVectorParams(modifier=IDF)` + Task 2 constants; D7 payload contract → Task 4/5/6 use `project_id`/`text`, guard asserted in Task 4/6 tests.
- **Payload guard:** `test_search_hybrid_builds_prefetch_and_maps_payload` (Task 4) and Task 6 tests assert `project_id`/`text` reads — the D7 contract test requirement (spec §9) is covered.
- **Type consistency:** `search_hybrid` returns `list[tuple[str,str,str,float]]` in Task 4 and is consumed identically in Task 6; `Chunk(id, project, text)` / `SearchHit(chunk, score)` reused from `flat_store` throughout; `_format_hits` reads `chunk.project`/`chunk.text`/`h.score` (matches how Task 6 builds hits, with `project=project_id`).
- **Fallback dense caveat:** fallback is sparse-only by design (dense lives only in Qdrant) — spec §8. `bm25_fallback.search` never needs a dense vector.
```
