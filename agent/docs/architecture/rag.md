# RAG Stack — chi tiết từng backend

Chi tiết pipeline từng RAG backend + media search. CLAUDE.md chỉ giữ bảng dispatch + gotcha.

Ngược lại: [`../../CLAUDE.md`](../../CLAUDE.md)

### KB Qdrant backend (opt-in: `NOBLE_RAG_BACKEND=kb_service`)

**In-process retrieval over per-tenant Qdrant collections — no retrieval-service
hop.** Replaced the `query_rag:8016` HTTP client on 2026-08-05 when that service was
retired; the backend NAME is unchanged so `noble_kb`'s dispatch and the `kb_search`
tool schema are untouched. `send_media` runs the same pipeline shape over the media
collection (below), which is why both share one pair of clients.

Pipeline (`agent/rag/kb_service_adapter.py`):

1. `collection = f"{current_tenant()}_documents"` — **tenant isolation is the
   collection NAME**, not a filter, so a bug cannot leak another tenant's chunks.
2. missing collection → `""` **before** embedding (fail-closed; an unprovisioned
   tenant costs no embed round-trip and is never an error).
3. embed the query **dense + BM25-sparse in parallel**, both `side="query"`. Neither
   leg needs the embed service, so `kb_search` works with `EMBED_SERVICE_URL` unset.
4. ONE Qdrant hybrid query: dense (`dense`) + sparse (`bm25`) prefetch → server-side
   RRF → `kb_search_top_k`, filtered by `project_id` (always unioned with the
   `__ALL__` sentinel so tenant-wide docs stay visible).
5. `_format_kb_hits` → the same context string every other backend returns.

Shared clients (both config-free; caller passes endpoints/token/timeouts):

- `data/embed_client.py` — **the single embedding seam** for both tools.
  `embed_dense` dispatches on `EMBED_BACKEND` (`gemini` \| `service` \| `hf`); callers
  pass only `side`, so switching backend touches no call site. **`embed_sparse` follows
  the same switch** (2026-08-06): `service` → `kind=sparse` over HTTP (response key
  `sparse`, not `embeddings`); anything else → **in-process**
  `fastembed.SparseTextEmbedding(EMBED_SPARSE_MODEL)` (default `Qdrant/bm25`, cached per
  name). The two are interchangeable — the service runs the same model and returns
  **bit-identical indices AND values** (measured live), so ingest's term ids match either
  way. **`EMBED_BACKEND=service` therefore means NO model is loaded in-process at all**;
  the service path has **no fallback to local on error** on purpose, since falling back
  would load the very model the flag forbids. `side` is validated but unweighted,
  matching what ingest did. `embed_visual_text` (SigLIP2 image space) is
  `EMBED_SERVICE_URL`-only regardless of the switch.
  **Both models must match what ingest indexed with**: a different dense model is a
  different vector space, so Qdrant returns noise with no error (measured: E5 query on
  an E5-indexed collection scores ~0.82, a Gemini query on the same collection ~0.03);
  a different sparse model is a different term vocabulary, so that branch silently
  contributes nothing.
  Unrelated to `flat_store._Embedder` / `EMBED_REMOTE_*`, which serves the legacy
  flat_store/qdrant/hipporag backends over an older wire contract — and that contract is
  **dead**: its `{"texts":…,"is_query":…}` body gets **HTTP 422 `Field required: side`**
  from the live service (measured 2026-08-06), so `EMBED_REMOTE_URL` cannot be pointed at
  it. That seam does NOT read `EMBED_BACKEND`, so with no `EMBED_REMOTE_URL` it loads
  e5-large locally. Only reachable on the parked backends (on `kb_service` nothing imports
  it), so it is left alone; unifying the two seams is a separate job.
- `data/qdrant_search.py` — `collection_name`, `build_scope_filter`,
  `collection_exists`, `search_hybrid` (N prefetch branches → RRF; `limit` and
  `score_threshold` applied AFTER the fuse). Keeps a module-level client cache keyed
  `(url, api_key)` — `AsyncQdrantClient` holds a persistent channel and rebuilding
  it per turn would cost real latency on the voice path.

**`score_threshold` / `min_score` are on the RRF scale** (`Σ 1/(2 + rank)`: rank0 =
0.5, rank1 = 0.333…), NOT cosine, and not comparable across queries — a threshold
here both filters AND implicitly caps how many hits survive.

**`QDRANT_URL` is now the app's ONE Qdrant endpoint** (consolidated 2026-08-06 — the
separate `SEARCH_QDRANT_*` block is gone). The legacy `qdrant`/`hipporag` backends read
the same URL but look for their own clone collection (`QDRANT_COLLECTION`, default
`noble_kb_hybrid`), which does **not** exist on the per-tenant deployment — so those
backends now degrade to empty/BM25-fallback unless someone rebuilds a clone there.
Their code is untouched and still runnable, but their config (`QDRANT_COLLECTION_ROOT`,
`EMBED_REMOTE_*`) is no longer set, so treat them as parked, not live.

Live infra: the Qdrant behind `QDRANT_URL` is a Portal-owned container on a
private-subnet EC2 (`10.110.43.147`, VPC `10.110.0.0/16`) with **no published host port
and no inbound `6333` SG rule**. The intended shape is the agent running **inside that
VPC** — then it is a plain in-VPC HTTP call with no tunnel and no AWS credentials at
runtime (same host → `http://odyssey-portal-backend-qdrant-1:6333` via docker DNS; a
different host → `http://10.110.43.147:6333`, which first needs the port published and
an SG rule). From outside the VPC the only way in is an SSM port-forward, and
`session-manager-plugin` binds `127.0.0.1` only (measured) — so any
`127.0.0.1`/`172.17.0.1` value is local to the host that reads it and must never be
copied between machines. Full setup + prerequisites: `docs/handoff/qdrant-access.md`.

### Media search (`send_media`)

Same shape as the KB backend, different collection and branches — `data/media_data.py`
took over the retired `query_media:8015` service on 2026-08-05:

- collection `f"{current_tenant()}_media"`; missing → `[]` (fail-closed).
- embeds the phrase as dense text (1024d) and — **only when `with_visual`** — also
  through the SigLIP2 **text tower** (768d, `kind="visual_text"`, query-side only by
  contract), both in parallel. `support_ops` passes `with_visual=bool(EMBED_SERVICE_URL)`
  (2026-08-06): the visual leg is the ONE thing here that still needs the embed
  service, so without one media degrades to text-only rather than failing.
- ONE Qdrant query: `text` (+ `visual` when on) branches → RRF → `MEDIA_SEARCH_TOP_K`,
  filtered by `project_id` (unioned with `__ALL__`) AND `category` (exact match, optional)
  AND `content_type` (exact match, optional — `image`|`video`).
- `category` và `content_type` đều optional ở schema nhưng **không được rỗng cả hai**
  (`support_ops` trả retry `missing_filter`). `content_type=video` nới cap video từ 1
  lên `MAX_VIDEOS_WHEN_REQUESTED=3`.
- hits → `_hit_to_item`/`_map_items`: ≤6 image items + ≤1 YouTube video (hoặc ≤`MAX_VIDEOS_WHEN_REQUESTED`=3 video khi `content_type=video`);
  S3 mp4 / PDF are dropped as unrenderable.
- an image item carries `thumb` (the ingest-written `thumb_url`) **only when
  `MEDIA_SEND_THUMB=true`** — default off, because that URL currently points at a
  private-subnet MinIO no client can reach, and both web clients + the app fall back to
  `url` when `thumb` is absent, so dropping it server-side turns a broken image into a
  heavier one. Flip it back on once `thumb_url` is publicly resolvable.
- **in-process result cache**, TTL `MEDIA_SEARCH_CACHE_TTL` (default 300s), keyed
  collection+query+top_k+threshold+project_code+category+content_type+with_visual+include_thumb
  (both flags are in the key because they change the mapped items). **Not invalidated by
  an ingest** — freshly uploaded media appears after at most the TTL. Tests MUST call
  `media_data.reset_result_cache_for_tests()` between cases (autouse fixture in
  `test_send_media.py`) or results leak across tests.
- `MEDIA_SEARCH_THRESHOLD` is RRF-scaled AND shifts with the number of branches fused
  (text-only ranks an item lower than text+visual), so a fixed cutoff caps image count
  differently depending on whether visual is on. **Default is `0.0` = no filter**; cap
  with `MEDIA_SEARCH_TOP_K` instead.
- unconfigured `QDRANT_URL` → `send_media` returns its degraded `no_media` payload
  without dialling anything. This is the only "off switch": unlike `kb_search` there is
  no backend flag, so **do not deploy to a tenant relying on media until Qdrant is
  reachable**.

### Qdrant hybrid backend (opt-in: `NOBLE_RAG_BACKEND=qdrant`)

**Dense AND BM25 sparse both live on Qdrant; RRF fusion is server-side.** The app
does NOT own the source data: another team writes dense into a read-only **root**
collection (`QDRANT_COLLECTION_ROOT`). At server-agent startup the app **clones**
root into its own **clone** collection (`QDRANT_COLLECTION`), attaching a BM25
**sparse vector** per point (IDF computed by Qdrant via `Modifier.IDF`) and a
`project_id` payload index. All searches run on the clone. Payload contract is the
team's schema: `project_id` (canonical code, filter key), `text`, `content_hash`,
`chunk_index`, `project_name` — **not** the legacy `project`/`chunk_id`; chunk identity
is the Qdrant `point.id` (copied verbatim from root). See design spec
`docs/superpowers/specs/2026-07-02-qdrant-hybrid-sparse-search-design.md`.

- `agent/rag/sparse_encoder.py` — stateless pyvi BM25 sparse encoder. `encode_document`
  uses a FIXED `AVGDL/K1/B` (so a chunk's vector is a pure function of its own text,
  never stale); `encode_query` = 1.0 per unique term (IDF applied by Qdrant). Term ids
  are a process-stable `blake2b` hash (never builtin `hash()`).
- `agent/rag/qdrant_store.py` — `AsyncQdrantClient` singleton. `search_hybrid(...)` =
  one `query_points` with dense + sparse `Prefetch` → `FusionQuery(RRF)`, pre-filtered
  by `project_id`. Plus clone (re)build helpers: `get_root_dense_params`,
  `recreate_clone`, `iter_root_points`, `upsert_clone_points`.
- `agent/rag/sparse_reconcile.py` — one-shot `reconcile()`: read root → upsert
  dense+sparse into the clone (batched) → build the local BM25 fallback from the same
  snapshot. Runs ONLY in the aiortc `run_server` process (single process, no lock),
  timeout-bounded (`QDRANT_RECONCILE_TIMEOUT_SEC`) + exception-swallowed so it never
  wedges boot; NOT wired into the LiveKit worker. Also a standalone console command
  **`noble-rag-sync`** (for livekit-only / manual runs).
- `agent/rag/qdrant_adapter.py` — `query_qdrant_for_noble_kb`: embed query (remote
  `_Embedder`) + sparse-encode (pyvi), one hybrid Qdrant call; on ANY error → local
  disk BM25 fallback (sparse-only, no dense). Formats via `flat_store_adapter._format_hits`.
- `agent/rag/bm25_fallback.py` — disk-persisted `bm25s` index + `chunks.json`, built by
  the reconcile from the same root snapshot (so it mirrors the clone). Read cross-process
  (server + LiveKit workers lazy-load it). `QDRANT_FALLBACK_DIR`.
- Install via `pip install -e ".[rag-qdrant]"` (`qdrant-client` is import-lazy so
  `make test-unit` collects without it). `scripts/build_qdrant.py` (legacy self-ingest
  with the old `project`/`chunk_id` schema) is NOT on this path.
- **Degraded window (accepted):** `recreate_clone` drops-then-fills, so a reconcile that
  fails mid-flight leaves the clone empty until the next restart (the disk BM25 fallback
  covers the prior snapshot). Future-proof variant = build-temp + alias-swap.

### HippoRAG 2 graph backend (opt-in: `NOBLE_RAG_BACKEND=hipporag`)

A HippoRAG-2-style knowledge graph layered **on top of** the qdrant hybrid — an
option beside it, not a replacement. Package `agent/rag/hipporag/`. Design doc
`docs/hipporag2-explainer.html` (animated) + plan
`docs/superpowers/plans/2026-07-28-hipporag2-graph-rag-backend.md`.

- **KG shape:** `phrase` nodes (entities) + `passage` nodes (one per KB chunk,
  keyed by Qdrant `point.id`); undirected weighted edges (passage──phrase
  "contains", phrase──phrase relations). `graph.py::HippoGraph` — pure numpy, NO
  graph lib. `content_hash` is the incremental-skip key.
- **OFFLINE build (LLM OpenIE):** `builder.run_sync(renew)` reads the Qdrant
  **clone** (`qdrant_store.iter_clone_points`), runs `openie.extract` (LLM triples
  via the configured provider chain, thinking off, temp 0) on the NEW chunks
  only, merges into `graph.py::HippoGraph`, persists to `HIPPORAG_GRAPH_PATH`
  (JSON). Wired into **`noble-rag-sync`** AFTER `reconcile()`: default =
  incremental (only new `content_hash` → LLM); `--renew-graph` = rebuild all. The
  **in-process startup reconcile (`http.py`) does NOT build the KG** — only the
  console command does, so a boot never pays the OpenIE cost.
- **RUNTIME (query, NO LLM):** `adapter.query_hipporag_for_noble_kb` → qdrant
  `search_hybrid` seed rows → `expander.expand` (load KG singleton → seed PPR at
  the hit passages → numpy power-iteration PPR spreads through shared phrases to
  co-entity passages) → `_rrf_fuse` PPR ranking with the hybrid ranking →
  `_format_hits` (same output shape). **Degrades to the plain qdrant result** when
  the graph artifact is missing / any step errors — enabling it can never do
  worse than `qdrant`.
- **Project scoping:** when `kb_search` passes a non-empty `project_filter`, the
  output is scoped to that project — `expander.expand`/`graph.top_passages` filter
  by `project` BEFORE the top_k cut and `adapter._rrf_fuse` output is guarded, so a
  project-pinned query never surfaces another project's passage. PPR still spreads
  through cross-project shared phrases (that's the recall win); only the OUTPUT is
  scoped. Empty `project_filter` = no scoping (search all).
- **OpenIE model:** build-time triple extraction is pinned by `HIPPORAG_OPENIE_MODEL`
  (must equal one of the `<P>_MODEL` values, same scheme as `NOBLE_AGENT_MODEL`);
  empty → falls back to the `NOBLE_AGENT_MODEL` pin. `builder._openie_primary`
  resolves it; thinking off, temp 0.
- **Sparse triple-seed (opt-in `HIPPORAG_SPARSE_SEED_ENABLED`):** HippoRAG 2 dual
  seeding kept LLM-free, **triple-based** (not bare-entity). The graph stores the
  full extracted triples (`HippoGraph.triples` = `{s,o,rel,text,passage}`; the
  relation is kept here, edges stay weight-only). Build-time
  (`builder._build_triple_index_from_embedder` → `triple_index.save_triple_index`)
  embeds each triple's `text` ("subject relation object") with the FlatStore
  embedder into a `.triple_emb.npz` sidecar aligned to the two entity keys — on
  every `noble-rag-sync` regardless of the flag (toggle without rebuild).
  Query-time (`adapter._sparse_seed`) embeds the query, cosine-matches it against
  the triple embeddings, and seeds PPR at **both** entity nodes of the top-M
  triples — so relational queries ("dự án nào ở Hải Phòng") match the triple, not
  just a surface entity string. Runs **in parallel** with the hybrid search via
  `asyncio.gather` (own embed; overlaps → ~no extra wall-clock). `expander.expand`
  mixes the restart `(1-W)·dense + W·sparse` (each group normalised;
  `W=HIPPORAG_SPARSE_SEED_WEIGHT`, `HIPPORAG_SPARSE_SEED_TOP_M` = number of triples,
  each seeding ≤2 entities). Sidecar missing / embedder unavailable / older graph
  without triples → silently no-ops (passage-only). Default OFF. **Older graphs
  have no triples → run `noble-rag-sync --renew-graph` once to (re-)extract them.**
  Build-time (`noble-rag-sync`) now ALSO (re)builds a dedicated Qdrant triple
  collection (`QDRANT_TRIPLE_COLLECTION`) alongside the `.triple_emb.npz` sidecar —
  both are written every sync regardless of which store is active, so switching
  `HIPPORAG_TRIPLE_STORE` never needs a rebuild. Query-time reads per
  `HIPPORAG_TRIPLE_STORE` (`local` default | `qdrant`) with cascade fallback
  `qdrant → local npz → sparse-seed off` — a Qdrant error degrades to the local
  npz, and a missing/empty npz degrades to no sparse seed (passage-only), never
  a hard failure. `graph.json` (the KG itself) stays local either way.
- **Seed thresholds:** `HIPPORAG_PASSAGE_SEED_THRESHOLD` / `HIPPORAG_PHRASE_SEED_THRESHOLD`
  drop low-similarity seeds — applied in `expander.expand` AFTER top-K, BEFORE the
  dense/sparse mix (passage = qdrant hybrid score, phrase = triple cosine; `0.0` =
  keep all). Filtering out every passage seed and every phrase seed → `expand`
  returns `[]` and the adapter degrades to the plain hybrid result.
- **Latency:** query-time adds only a graph load (cached) + PPR (~ms on this
  corpus). No new dependency (numpy only).
