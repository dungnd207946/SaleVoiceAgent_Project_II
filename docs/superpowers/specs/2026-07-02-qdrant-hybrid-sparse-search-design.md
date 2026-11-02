# Qdrant Hybrid Sparse Search — Design Spec

**Date:** 2026-07-02
**Branch:** `feat/seperate-service`
**Scope:** `NOBLE_RAG_BACKEND=qdrant` path only. The `flat_store` (default, local) backend is unchanged.

---

## 1. Motivation

Today the `qdrant` RAG backend owns **only the dense signal** (e5-large 1024d) on a remote Qdrant.
BM25 (sparse) runs **locally in the worker** from a gitignored on-disk index, and RRF fusion happens
locally in `agent/rag/qdrant_adapter.py`. Two problems:

1. **Data divergence.** The corpus lives in two places (Qdrant dense + local BM25 files). When the
   remote Qdrant is updated by another team, the local BM25 index goes stale — dense and sparse no
   longer describe the same corpus.
2. **Stale over-fetch hack.** Local BM25 is *post-filtered* by project (`over_k = k*5` in
   `_bm25_topk`). With 15 projects the `×5` factor is a weak heuristic — a target project's chunks
   can fall out of the global top-`k*5`, hurting recall. This is a symptom of post-filtering; a
   server-side pre-filter removes it entirely.

**Goal:** move BM25 (sparse) scoring **and** fusion onto Qdrant so the corpus has a single source of
truth, while keeping Vietnamese tokenization quality (pyvi) and a resilience fallback.

---

## 2. Key decisions (agreed)

| # | Decision |
|---|---|
| D1 | **Hướng A — sparse vectors on Qdrant.** Store a BM25 sparse vector per point alongside dense; query sends a sparse query vector; Qdrant does sparse scoring + RRF fusion **server-side** in one request. |
| D2 | **App-owned clone collection.** The other team writes dense into a **root** collection (read-only for us). App **clones** root into its **own** collection, adds the sparse vector config, and runs all searches on the clone. Both collection names come from `.env`. |
| D3 | **One-shot build at server-agent startup**, independent of LiveKit workers. Runs once in the single aiortc `run_server` process (no lock needed). Also packaged as a standalone command for livekit-only / manual runs. |
| D4 | **Recreate-before-traffic.** On each server-agent start, rebuild the clone from root fully (recreate → bulk upsert) *before* the server accepts traffic. Deterministic, no orphan/stale points. Corpus is small (~285 points → ms-scale). |
| D5 | **Keep a local BM25 fallback, rebuilt from root at the same startup.** The local BM25 index is built from the *same root snapshot* as the Qdrant sparse (so they are consistent by construction, not a stale older build) and **written to disk** so LiveKit worker processes (which never run the build) can lazy-load it for fallback. |
| D6 | **IDF is computed by Qdrant** (`Modifier.IDF`); doc-side sparse encoding uses a **fixed avgdl** so each chunk's sparse vector is a pure function of its own text (stateless, never stale). |
| D7 | **Payload contract = the other team's schema** (`project_id`, `text`, `content_hash`, `chunk_index`, `project_name`). No `chunk_id`/`project`/`is_faq`/`tokens`/`chunk_order`. |

---

## 3. Payload contract

The root collection (other team) stores this payload per point:

```json
{
  "project_id": "NCTH",
  "project_name": "Noble Crystal Tây Hồ",
  "chunk_index": 0,
  "text": "Dự án Noble Crystal Tây Hồ > Hỏi đáp ...",
  "content_hash": "99dbb938862fff95f978d2d0a53a077ec2f6ef18"
}
```

Mapping vs the legacy `build_qdrant.py` schema:

| Concept | Legacy (current code) | **New contract (use this)** |
|---|---|---|
| Project code (filter key) | `project` | **`project_id`** |
| Chunk text | `text` | `text` |
| Chunk identity | `chunk_id` | **Qdrant `point.id`** (copied verbatim from root); `content_hash` available but not used as key |
| Project display name | — | `project_name` |
| Content fingerprint | — | `content_hash` (reserved for a future change-guard; not in core scope) |
| Dropped | `is_faq`, `tokens`, `chunk_order` | n/a |

**Rules:**
- All code touching payload (`qdrant_store`, `qdrant_adapter`, the new reconcile module) uses these
  keys consistently.
- `project_id` holds the canonical Noble code (e.g. `NCTH`), so it aligns with `catalog.normalize()`
  output — no extra mapping needed.
- Chunk identity for the local BM25 fallback keys on the Qdrant `point.id` (unique, copied verbatim),
  storing `text` + `project_id` for formatting. `content_hash` is not the key (guards against two
  chunks with identical text colliding).
- `build_qdrant.py` (legacy `project`/`chunk_id` self-ingest) is NOT on this path and is left
  untouched.

---

## 4. Architecture

```
                 (other team writes dense)
   ROOT collection  ──read-only──┐
   QDRANT_COLLECTION_ROOT        │
                                 ▼
        ┌──────────────── server agent startup (one-shot) ────────────────┐
        │  scroll(root, with_vectors=True)                                 │
        │    for each point:                                               │
        │      • keep id + dense vector + payload                          │
        │      • sparse = encode_document(payload["text"])   (pyvi, fixed) │
        │      • upsert {dense, sparse} → CLONE collection                 │
        │      • collect Chunk(point_id, project_id, text)                 │
        │  build local BM25 (bm25s + pyvi) from collected chunks           │
        │  write BM25 index + chunk metadata to disk                       │
        └──────────────────────────────────────────────────────────────────┘
                                 │                         │
             CLONE collection ◀──┘                         └──▶ local BM25 artifact (disk)
             QDRANT_COLLECTION                                   (fallback, all processes)
             dense + sparse(IDF)

   QUERY (any process: server agent OR LK worker)
     embed query (remote EMBED_REMOTE_URL)  +  encode_query sparse (local pyvi)
       └─▶ Qdrant Query API on CLONE:
             prefetch[dense] + prefetch[sparse] → FusionQuery(RRF), filter project_id, limit top_k
       └─ on Qdrant error ─▶ lazy-load disk BM25 → BM25-only (sparse signal) → format
```

### Components

- **`agent/rag/sparse_encoder.py` (new).** Shared doc/query sparse encoder.
  - `encode_document(text) -> dict[int, float]`: pyvi tokenize → hash each token to a stable `uint32`
    id → value = BM25 doc weight `tf*(k1+1) / (tf + k1*(1 - b + b*len/AVGDL))` with **fixed `AVGDL`,
    `k1`, `b`** constants. Stateless (no vocab file, no corpus stats).
  - `encode_query(text) -> dict[int, float]`: pyvi tokenize → same hash → value `1.0` per query term.
  - IDF is applied by Qdrant (`Modifier.IDF`), not here.
  - Hashing uses a stable function (e.g. token bytes → `uint32`); collisions negligible for this
    vocab size.

- **`agent/rag/sparse_reconcile.py` (new).** The one-shot build.
  - `reconcile() -> None`: read root config via `get_collection` (mirror dense size/distance/naming);
    recreate the clone with the same dense config **plus** `sparse_vectors_config={<name>:
    SparseVectorParams(modifier=Modifier.IDF)}` and a payload index on `project_id`; scroll root
    (`with_vectors=True`, `with_payload=True`); upsert dense+sparse into the clone; build + persist the
    local BM25 artifact.
  - Idempotent full rebuild. Recreate guarantees the clone == current root + sparse.
  - Exposed as a standalone command (console script / `python -m ...`) for manual / livekit-only runs.

- **`agent/rag/qdrant_store.py` (rewrite).** Add a hybrid query using Qdrant Query API
  (`query_points` with `prefetch` + `FusionQuery(RRF)`), filter on `project_id`, read `text` /
  `project_id` from payload. Keep the async client singleton.

- **`agent/rag/qdrant_adapter.py` (rewrite / simplify).** No more local dense/BM25/RRF for the happy
  path — one Qdrant call returns fused hits. Keep a **fallback branch**: on Qdrant error, lazy-load the
  disk BM25 artifact and run BM25-only, formatting via the shared `_format_hits`.

- **Local BM25 fallback store.** Reuse `bm25s` + pyvi (`_tokenize_vi`). Chunks come from the root
  snapshot at build time (not from `data/rag/*.json`). Persist to a dedicated dir (e.g.
  `data/flat_store/bm25_qdrant_fallback/`) + a chunk metadata file (`point_id`, `project_id`, `text`).

### What is removed from the qdrant path
- Local dense `.npy` load and local dense matmul.
- Local RRF fusion (`qdrant_adapter` fuse loop).
- The `over_k = k*5` post-filter hack (server-side pre-filter replaces it).
- Dependency on `data/rag/lightrag_s02_*/kv_store_text_chunks.json` for the qdrant path.

---

## 5. Build / reconcile flow (D3, D4, D5)

Wired into the aiortc server startup at `server/http.py::_run_server_async`, **after**
`cm.initialize()` (same neighborhood as `prewarm_voice_models()`), and **NOT** into
`transport/livekit/worker.py::_prewarm`.

- Single process → runs exactly once → no lock / no single-flight needed.
- Runs synchronously (blocking) **before** the server accepts traffic, so the clone + local artifact
  are ready when queries start. Guarded by a timeout; on failure it logs and boot continues (queries
  then fall back / degrade rather than wedging boot — mirrors the existing prewarm resilience rule).
- Cross-process contract: **only the server agent builds and writes.** LK workers never build; they
  lazy-load the disk BM25 artifact when they hit the fallback branch.
- Staleness model (accepted): root is refreshed into the clone + disk artifact on each server-agent
  start. If the other team updates root without a server-agent restart, the clone and artifact stay on
  the previous snapshot until the next restart. This is the intended operational model (refresh tied
  to server-agent lifecycle).

---

## 6. Query flow (D1, D6)

1. `noble_kb.query_noble_kb` dispatches to the qdrant path (unchanged entrypoint).
2. Embed the query text via the remote embed service (`EMBED_REMOTE_URL`, `is_query=True`) — unchanged.
3. Sparse-encode the query locally via `sparse_encoder.encode_query` (pyvi, no network).
4. One Qdrant `query_points` on the clone:
   - `prefetch=[Prefetch(query=dense_vec, using=<dense>, limit=C),
      Prefetch(query=SparseVector(sparse), using=<sparse-name>, limit=C)]`
   - `query=FusionQuery(fusion=RRF)`, `limit=top_k`
   - `query_filter=Filter(must=[FieldCondition(key="project_id", match=MatchValue(project_filter))])`
     when `project_filter` is set (pre-filter, both branches).
5. Format hits from payload `text` (+ `project_id`) via the existing `_format_hits` shape so the tool
   result is identical across backends.
6. **Fallback:** any Qdrant error → lazy-load disk BM25 → `_bm25_topk`-style search (sparse-only, no
   dense, since dense lives only in Qdrant) → `_format_hits`.

---

## 7. Configuration (`.env`)

| Env | Purpose |
|---|---|
| `QDRANT_COLLECTION_ROOT` | Other team's collection (read-only source for the clone). |
| `QDRANT_COLLECTION` | App-owned clone collection where all searches run (was: single collection name). |
| `QDRANT_SPARSE_VECTOR_NAME` | Name of the named sparse vector on the clone (default e.g. `bm25`). |
| `QDRANT_URL`, `QDRANT_API_KEY` | Unchanged. |
| (BM25 fallback dir) | Dedicated on-disk path for the reconcile-built fallback index + chunk metadata. |

`config.py` (`UnifiedSettings`) gains the new fields. Existing `qdrant_collection` semantics change
from "the single collection" to "the clone we search"; add `qdrant_collection_root`.

---

## 8. Resilience

- **Qdrant down at query time** → fallback to disk BM25 (sparse-only). Matches today's
  "BM25-only on error" behavior, but the local index is now the same snapshot as Qdrant (built from
  root at the last server-agent start), not an independently-maintained stale file.
- **Reconcile fails at boot** → log + continue. Queries fall back to whatever disk artifact exists (or
  degrade to empty if none). Boot never wedges (consistent with `prewarm` resilience).
- **Dense fallback is impossible** when Qdrant is down (dense vectors live only in Qdrant) — accepted;
  the sparse-only BM25 fallback is the degraded mode.

---

## 9. Testing

- **`sparse_encoder`**: unit — determinism (same text → same sparse), pyvi tokenization applied,
  fixed-avgdl weighting formula, query vs document encoding differ as specified, stable hashing.
- **`sparse_reconcile`**: unit with a mocked/fake Qdrant client — mirrors root dense config, adds
  sparse config + `project_id` index, upserts dense+sparse per point, persists the BM25 artifact;
  recreate is idempotent.
- **`qdrant_store` / `qdrant_adapter`**: unit — Query API request shape (prefetch dense+sparse, RRF,
  `project_id` filter), payload read uses new keys, result format parity with `flat_store` via
  `_format_hits`; fallback branch triggers on client error and loads the disk BM25.
- **Payload contract**: a guard test asserting the code reads `project_id`/`text` (not
  `project`/`chunk_id`).
- Markers per repo conventions (`needs_qdrant` where a live client is required; otherwise fake client).
- Run `make eval-estate-smoke` to confirm answer-quality parity on the qdrant path is not regressed.

---

## 10. Out of scope

- Changing the `flat_store` default backend.
- Modifying the other team's root collection or their ingest.
- A `content_hash`-based incremental change-guard (reserved; full recreate is used instead).
- Telephony-specific concerns (RAG path is transport-agnostic).
- Migrating `build_qdrant.py` to the new schema (not on this path).

---

## 11. Open risks

- **Root dense vector naming.** The clone must mirror whether root uses a named or default (unnamed)
  dense vector; the reconcile reads `get_collection` and mirrors it. Query `using=` must match.
- **Root collection recreation by the other team.** If they drop/recreate root, the next server-agent
  start re-clones fresh — fine. But a query against an empty/absent root-derived clone during a root
  outage degrades to the last disk BM25 artifact.
- **pyvi availability.** Fallback + query sparse encoding depend on pyvi; keep imports resilient and
  documented as a required dep for the qdrant path.
- **Horizontal scaling of the server agent.** Design assumes a single server-agent process. Multiple
  concurrent server agents recreating the same clone would race; if that becomes real, switch D4 to
  build-temp + alias-swap (noted as the future-proof variant).
