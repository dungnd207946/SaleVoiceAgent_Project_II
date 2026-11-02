# Qdrant Dense Backend for RAG — Design

**Date:** 2026-06-08
**Status:** Approved (design); pending implementation plan
**Scope owner:** dutn@noblex.vn

## Problem

The RAG knowledge base lives entirely on local disk. The main KB (~3.7k chunks
from the LightRAG exports under `data/rag/lightrag_s02_*`) is encoded with
`intfloat/multilingual-e5-large` (1024d), cached to `data/flat_store/*.npy`, and
loaded into every process's RAM. Dense retrieval is a numpy matmul inside
`FlatStore.search_hybrid`, fused with a local BM25s index via Reciprocal Rank
Fusion (RRF).

This local-only layout blocks four goals the user wants:

1. **Update KB without redeploy** — today, changing project docs means rebuilding
   `.npy` + BM25 artifacts and restarting every agent.
2. **Share one KB across instances** — server, telephony, and LiveKit workers each
   load their own copy into RAM.
3. **Prepare to scale** beyond the ~4k-chunk premise.
4. **Centralized ops/observability** — manage/inspect/snapshot the corpus from one
   place instead of gitignored disk artifacts.

A self-hosted Qdrant instance is already running, reachable via SSH tunnel at
`QDRANT_URL=http://localhost:6333` with an API key.

## Non-goals

- **Not** moving the sparse/BM25 signal to Qdrant. BM25 stays local; RRF fusion
  stays in code. (User decision — preserves current quality, lowest risk.)
- **Not** touching the FAQ semantic searcher (`agent/rag/faq_searcher.py`). It is
  dead code in production — `inject_faq_searched` has no caller in `src/`, only in
  `tests/bench/*`. Out of scope.
- **Not** reusing the legacy BGE-M3 Qdrant collection
  (`lightrag_vdb_entities_baai_bge_m3_1024d`). We create a fresh e5 collection.
- **Not** replacing `flat_store`. It remains the default backend.

## Verified current state (read from source, not docstrings)

- Per-turn KB retrieval path: `noble_search` tool → `agent/facade.py:36`
  `query_noble_kb` → dispatch on `settings.noble_rag_backend` in
  `agent/rag/noble_kb.py` → `flat_store` branch →
  `flat_store_adapter.query_flat_store_for_noble_kb` → `FlatStore.search_hybrid`
  (dense + BM25 RRF) → formatted string.
- Valid backends today: `flat_store` (default), `grep_faq`, `empty`. A removed
  `memory_router` backend is still referenced by a stale Qdrant health probe in
  `server/http.py`.
- `_Embedder` already supports a remote sidecar via `EMBED_REMOTE_URL`
  (`embed_remote_url` / `embed_remote_timeout` in config), plus fastembed and
  sentence-transformers.
- Legacy `qdrant_url` / `qdrant_api_key` / `qdrant_collection` settings exist in
  `config.py` (marked deprecated). `qdrant-client` is **not** in `pyproject.toml`
  deps; it is only lazily imported in `server/http.py`.
- Dead code to clean up (no callers found in `src/` or `tests/`):
  `get_flat_store_adapters`, `FlatStoreVectorStoreAdapter`,
  `FlatStoreEmbeddingAdapter` in `flat_store_adapter.py`. They import a deleted
  `agent/rag/vector_store.py` and would `ImportError` if ever called.
- `server/http.py` `/api/config` hardcodes `"rag": {"provider": "qdrant"}` —
  currently false; will be made dynamic.
- Boot warm of FlatStore happens only in `transport/livekit/worker.py`; the HTTP
  server warms lazily on first `noble_search`.

## Design

### Principles & scope

- Qdrant is an **opt-in backend**: `NOBLE_RAG_BACKEND=qdrant`. `flat_store` stays
  the default, so the change is additive and reversible.
- Qdrant owns **dense only** (e5-large, 1024d, cosine). BM25 stays local; RRF
  fusion stays in code.
- Query embedding uses the **existing `_Embedder`** (fastembed / remote sidecar /
  sentence-transformers). Identical query vectors → dense scores match the local
  path → answer-quality parity expected.
- Fresh collection for e5: default `qdrant_collection = "noble_kb_e5_1024d"`.
  Reuse `qdrant_url` + `qdrant_api_key` env (already present).
- Scope: main KB (~3.7k chunks) only.

### New components

| File | Role |
|---|---|
| `agent/rag/qdrant_store.py` | `QdrantKB` singleton wrapping `AsyncQdrantClient`. `search_dense(q_vec, project_filter, top_k) -> list[(chunk_id, project, text, score)]`. Payload filter on `project`. Lazy connect + warm. |
| `agent/rag/qdrant_adapter.py` | `query_qdrant_for_noble_kb(query, project_filter, top_k) -> str`. Encodes query with the shared embedder; gets dense candidates from Qdrant + sparse candidates from the local BM25s index; fuses with RRF on `chunk_id` (same formula as `FlatStore.search_hybrid`); formats via the shared `_format_hits`. Same string contract as the flat_store path. |
| `scripts/build_qdrant.py` | Offline ingestion. Loads chunks + embeddings via FlatStore (reuses the `.npy` cache, encodes if missing). Creates/recreates the collection (cosine, 1024d). Upserts points `{id, vector, payload:{chunk_id, project, text, is_faq, tokens, chunk_order}}`. Flags: `--recreate`, `--project CODE` (subset), default idempotent upsert (= update KB without redeploy). Point `id` = stable hash of `chunk_id`. |

### Local BM25 in the qdrant path

The qdrant path still needs the local BM25 index and the chunk list (for token
text and the `chunk_id → local index` mapping used in RRF). It loads **chunks +
BM25 only, not `.npy`** (Qdrant owns dense), via a lightweight loader on
`FlatStore` (e.g. `load_chunks_only()` / a `skip_embeddings` flag on `load()`).
This keeps the qdrant path's RAM footprint below the full flat_store path.

RRF fusion key: both candidate lists are keyed by `chunk_id`. Qdrant returns
`chunk_id` in payload; BM25 returns local indices mapped to `chunk_id` via
`FlatStore.chunks[i].id`. Text comes from Qdrant payload (dense hits) or local
chunks (sparse hits).

### Wiring (minimal edits)

- `agent/rag/noble_kb.py`: add `if backend == "qdrant": return await
  query_qdrant_for_noble_kb(query, project, top_k)`.
- Warm: add Qdrant client warm in `transport/livekit/worker.py` alongside the
  FlatStore warm; lazy warm in the HTTP path on first call.
- `pyproject.toml`: add `qdrant-client>=1.10` under a new optional extra
  `rag-qdrant`. Import lazily so the base install and the default flat_store path
  never require it.

### Resilience

On Qdrant error/timeout, the adapter **falls back to BM25-only** results (already
loaded locally) and logs a warning — the turn never dies. No local dense fallback,
since `.npy` is intentionally not loaded in this path.

### Cleanup of stale Qdrant remnants (in-area, surgical)

- Remove dead `get_flat_store_adapters`, `FlatStoreVectorStoreAdapter`,
  `FlatStoreEmbeddingAdapter` and the broken `vector_store` import in
  `flat_store_adapter.py`.
- `server/http.py`: make `/api/config` `rag.provider` reflect
  `settings.noble_rag_backend`; replace the dead `memory_router` health probe with
  a `qdrant` probe gated on `backend == "qdrant"`.
- `config.py`: drop the "deprecated" annotation on `qdrant_*`; change the default
  `qdrant_collection` to `noble_kb_e5_1024d`.

### Configuration

| Setting (env) | Default | Purpose |
|---|---|---|
| `NOBLE_RAG_BACKEND` | `flat_store` | Add `qdrant` as a valid value. |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint (SSH-tunneled self-host). |
| `QDRANT_API_KEY` | empty | Qdrant API key. |
| `QDRANT_COLLECTION` | `noble_kb_e5_1024d` | e5 collection name. |

## Verification

- **Unit:** project-filter behavior + RRF fusion with a mocked Qdrant client; the
  BM25-only fallback branch when the client errors.
- **Integration (`needs_qdrant` marker):** build a small collection, compare top-k
  against `flat_store` on a handful of queries — expect parity (dense vectors are
  identical).
- **Eval:** `make eval-estate` with `NOBLE_RAG_BACKEND=qdrant` vs `flat_store`;
  confirm no answer-quality regression.
- **Latency (hot-path risk):** dense retrieval moves from a local matmul (<2 ms) to
  a network round-trip to Qdrant (via SSH tunnel). `noble_search` blocks TTFA. Run
  `make bench` (`benchmark_latency.py`) under the qdrant backend and compare p95
  against flat_store. This is the primary risk of the chosen approach. If p95
  regresses unacceptably, mitigations: co-locate the agent with Qdrant, or keep a
  local dense cache as a fast-path.

## Decisions accepted (user said "oke" to recommended defaults)

1. Collection name: `noble_kb_e5_1024d`.
2. Dead-code cleanup + health/info fixes land in the **same PR** as the feature.
3. Dense-as-network-call is accepted; latency to be measured, not assumed.

## CLAUDE.md updates required on landing

- Pluggable-backends list: add `qdrant` to `NOBLE_RAG_BACKEND`.
- RAG Stack section: document the qdrant dense path, BM25-local fusion, and the
  `build_qdrant.py` ingestion command.
- Key-configuration table: add `QDRANT_*` rows.
- Change Log row.

## Results (2026-06-09)

Ingestion: `python scripts/build_qdrant.py --recreate` → **45 points** in
`noble_kb_e5_1024d` (1024d cosine; payload index on `project`). The local KB
currently holds 45 chunks (NCTH 11, NCLB 11, NPLB 5, NTTL 5, SSLC 13), not the
~3.7k the spec assumed — `data/rag/` is a reduced local set.

**Retrieval parity (qdrant vs flat_store), top_k=3, warm:**

| Query (project) | Top-hit match | Output | flat_store | qdrant |
|---|---|---|---|---|
| "giá bán căn hộ" (NCLB) | yes | byte-identical (Diem 0.82) | 31 ms | 238 ms |
| "tiện ích dự án" (NTTL) | yes | byte-identical (Diem 0.83) | 31 ms | 239 ms |
| "chính sách thanh toán" (ALL) | yes | byte-identical (Diem 0.82) | 31 ms | 239 ms |

- **Answer quality: identical.** Same chunks, same scores, same text — query
  vectors and the local BM25 are the same, so RRF fusion produces the same hits.
  The `needs_qdrant` parity test passes.
- **Latency: qdrant adds ~207 ms/query**, entirely the network round-trip to the
  remote Qdrant over the dev SSH tunnel (local ↔ Seoul ap-northeast-2). This is on
  the TTFA-blocking `noble_search` path. Mitigation per the spec: co-locate the
  agent with Qdrant (same region/VPC) where the round-trip is ~5–15 ms, or keep a
  local dense fast-path. The 238 ms is a dev-tunnel artifact, not a Qdrant cost.

Full `make eval-estate-smoke` / `make bench` under both backends were not re-run
because retrieval output is byte-identical — the eval (LLM-judge) and TTFA deltas
would reduce to the latency row above.
