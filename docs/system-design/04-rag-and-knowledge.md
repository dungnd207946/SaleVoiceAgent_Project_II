# 04 — RAG & Project Knowledge

> How the agent answers "căn 2 phòng ngủ Lakeside còn không?". The retrieval stack moved from Qdrant to in-process FlatStore in rev 3 (post-migration). Three knowledge sources feed the LLM: foreground hybrid search (FlatStore), per-turn FAQ semantic injection, and background prefetch (SlowThinker). All three converge on a single source of truth for project codes (`project_catalog`).

Read [`02-llm-and-agents.md`](02-llm-and-agents.md) first — RAG hooks are wired into `stream_response`.

---

## 1. The single source of truth — `project_catalog`

File: `src/noble_agent/agent/project_catalog.py`. Pure-stdlib. Knows 5 Noble projects:

| Code | Name | Aliases (longest-first) |
|---|---|---|
| `NCLB` | Noble Crystal Long Biên | `Long Biên`, `Crystal LB`, `NCLB` |
| `NCTH` | Noble Crystal Tây Hồ | `Tây Hồ`, `Crystal Tây Hồ`, `NCTH` |
| `NPLB` | Noble Palace Long Biên | `Palace Long Biên`, `NPLB` |
| `NTTL` | Noble Tower Tây Hồ Lake | `Tower Tây Hồ`, `NTTL` |
| `SSLC` | Noble … (NƠHTTL building) | `NƠHTTL`, `SSLC`, … |

```python
from noble_agent.agent.project_catalog import catalog
catalog.normalize("Em quan tâm đến Lakeside Long Biên")  # → ('NCLB', confidence=0.95)
catalog.normalize("nhà ở thuộc TLT")                      # → (None, ambiguous_reject=True)
```

Rules:

- **Longest-first matching.** "Crystal Tây Hồ" matches before "Tây Hồ" alone.
- **Ambiguous reject** is explicit. If two codes are equally good, returns `None` rather than guessing.
- **Redis only ever stores canonical 4-char codes.** Anything that reads `customer.project_interest` from Redis must already be normalized.

This is **not optional**. Every consumer that touches project state goes through `catalog.normalize()`. If you find raw user strings in Redis, that's a bug.

---

## 2. Foreground retrieval — FlatStore hybrid

File: `src/noble_agent/agent/rag/flat_store.py`. The replacement for the Qdrant + sentence-transformers path. Loads from `data/flat_store/`:

```
data/flat_store/
  embeddings_intfloat__multilingual-e5-large.npy        ~15 MB  dense vectors
  embeddings_intfloat__multilingual-e5-large_nofaq.npy  ~15 MB  same, but FAQ chunks excluded
  bm25_index/                                           ~3.5 MB sparse BM25S
  bm25_index_nofaq/
  meta_e5large.json                                      chunk metadata
  meta_e5large_nofaq.json
```

Both `_nofaq` and full variants exist because FAQ has its own injection channel (V5 / V10) — the foreground RAG shouldn't double-cover what the FAQ already does.

### 2.1 Search algorithm

```
query (Vietnamese) ─┬─► e5-large query encode (1024-dim)
                    │           │
                    │           ▼
                    │    cosine top-K dense (default K=20)
                    │           │
                    └─► BM25S sparse top-K
                                │
                                ▼
                    Reciprocal Rank Fusion (RRF, k=60)
                                │
                                ▼
                    Optional project_filter mask
                                │
                                ▼
                    Top-N hits → text block for the LLM
```

Performance (warm, no network):

| Stage | p50 | p95 |
|---|---:|---:|
| Encode query | 8 ms | 15 ms |
| Dense top-K | 12 ms | 25 ms |
| BM25 top-K | 5 ms | 12 ms |
| RRF + filter | 1 ms | 3 ms |
| **Total** | **~30 ms** | **~55 ms** |

p95 covers cold cache reload. p99 spikes happen when the e5 model swaps to disk; mitigated by keeping the agent process resident.

### 2.2 Tool entry point

The LLM calls `noble_search(query, project_filter)`. `agent/tools/__init__.py:execute_tool` routes:

```python
backend = settings.noble_rag_backend  # "flat_store" (default) | "memory_router" | "empty"
if backend == "flat_store":
    return query_flat_store_for_noble_kb(query, project_filter)
elif backend == "memory_router":
    return MemoryRouter.query_context(...)  # cache-aware FastTalker shim
else:  # "empty"
    return ""  # degraded mode for missing artifacts
```

Setting `NOBLE_RAG_BACKEND=empty` is what you set in CI when you don't want to ship the 30 MB artifacts — the agent still runs, just without retrieved knowledge.

---

## 3. Per-turn FAQ injection (V5 + V10)

Two layers of FAQ defense.

### 3.1 V5 — static FAQ MD inject (build time)

`agent/registry.py:_load_project_faq` reads `data/faq/<CODE>.md` for the current `customer.project_interest` and **prepends** it to the system prompt before any LLM call. Coarse-grained: covers all FAQ topics for that project, regardless of the user's specific question.

Toggle: `FAQ_INJECT_IN_PROMPT=true` (default).

### 3.2 V10 — dynamic semantic FAQ inject (per turn)

`agent/rag/faq_searcher.py` runs per turn:

1. Encode user utterance with e5-large.
2. Cosine search over `data/faq/<CODE>_faq.json` (per-project FAQ embeddings, hash-keyed cache in `data/faq_cache/`).
3. Take top-K above threshold.
4. **Append** matched FAQ items to the system prompt tail (so the LLM sees: SOUL → SKILL → V5 FAQ MD → conversation history → V10 FAQ matches).

Toggle + tune:

```bash
FAQ_SEMANTIC_INJECT_ENABLED=true
FAQ_SEMANTIC_THRESHOLD=0.45     # e5 cosine; tune higher for fewer / more relevant matches
FAQ_SEMANTIC_TOP_K=5
```

V5 and V10 run together by design — V5 covers everything coarsely, V10 catches paraphrased queries the LLM might miss. They don't duplicate work because V5's static MD is one block, V10 adds individual Q&A pairs at the end.

### 3.3 Cache invalidation

V10's per-project FAQ npz cache is keyed by SHA1 of the JSON content:

```
data/faq_cache/NCLB_e5large_a1b2c3d4....npz
```

When `data/faq/NCLB_faq.json` changes, the SHA1 changes, the old npz is stale and a new one is built lazily on next request. No manual rebuild needed.

---

## 4. Background prefetch — SlowThinker (paper Table 6)

File: `src/noble_agent/agent/rag/slow_thinker.py` (driver) + `agent/rag/semantic_cache.py` (FAISS L2 hot layer) + `agent/rag/conversation_stream.py` (event bus) + `agent/rag/fast_talker.py` (cache-aware reader).

### 4.1 Why

Foreground RAG is fast (~30 ms warm) but still adds to TTFT. If the LLM frequently asks about predictable adjacent topics (after asking about price → asking about payment terms), we can prefetch those answers while the user is still talking.

### 4.2 Flow

```
USER_UTTERANCE event (published by VoiceAgent on every STT final)
              │
              ▼
ConversationStream broadcasts to subscribers
              │
              ▼
SlowThinker (gpt-4o-mini, ~$0.0003/turn, async — does NOT block TTFT)
   │ predicts up to 5 next likely topics:
   │   ["thanh toán Lakeside", "phòng 3PN", "khu tiện ích trẻ em", ...]
   ▼
For each topic:
   e5-large encode → FlatStore dense top-K → SemanticCache.put(TTL=300s)
              │
              ▼
Next turn's FastTalker.get_context(query):
   SemanticCache.get(query, similarity_threshold=0.4) → hit?
       ├── yes → ~5 ms total (skip FlatStore)
       └── no  → fall back to FlatStore (~30-50 ms)
```

Paper (LangGraph multi-stream RAG paper) reports **75-79% warm hit rate** in production-like traffic. Each hit saves 40-200 ms. The cost is **one LLM call per user utterance** ($0.0003 amortized).

### 4.3 Configuration

Defaults match the paper:

```bash
SLOW_THINKER_ENABLED=true
SLOW_THINKER_MODEL=gpt-4o-mini
SLOW_THINKER_MAX_PREDICTIONS=5
SLOW_THINKER_PREDICTION_TIMEOUT_S=2.0
SEMANTIC_CACHE_TTL_S=300
SEMANTIC_CACHE_SIMILARITY_THRESHOLD=0.40
```

Disable for benchmarking determinism; enable in production. The cache lives in-process (FAISS L2) — when the agent process restarts, the cache is empty until SlowThinker warms it again.

---

## 5. Streaming integration order

`agent/llm/streaming.py:stream_response` runs RAG hooks in this strict order:

1. **V6 pre-turn project sniff** (`catalog.normalize(user_text)`) — if the user named a project, update `customer.project_interest` *before* prompt build, so the very first LLM call sees the right FAQ.
2. **`_maybe_fast_route`** — router intent classifier (cheap), may pre-switch agent.
3. **V10 FAQ semantic inject** — `inject_faq_searched(user_text, project_interest)` appends matches to the system prompt tail.
4. **Tool loop** — `noble_search` (FlatStore) + `update_customer` + `switch_agent` rebuild prompts inline.
5. **V9 post-turn rebuild** — if a mid-turn tool changed `project_interest` (V7 auto-set), `refresh_system_prompt()` for the next turn.

The order matters: V6 updates state → V10 reads state → tool loop may mutate state → V9 cleans up. Skipping V6 means the first LLM call sees stale FAQ for the wrong project.

---

## 6. Building / regenerating artifacts

The artifacts live under `data/` and are gitignored. Regenerate after data changes:

```bash
# FlatStore — rebuild from raw chunks (data/rag/lightrag_s02_*/)
python -c "from noble_agent.agent.rag.flat_store import FlatStore; \
           s=FlatStore(); s.load(); s.build_bm25()"

# Repeat for the _nofaq variant
NOBLE_FLATSTORE_SKIP_FAQ=1 python -c "from noble_agent.agent.rag.flat_store import FlatStore; \
                                       s=FlatStore(); s.load(); s.build_bm25()"

# FAQ per-project npz — auto on first query, but force-rebuild via:
rm -rf data/faq_cache
```

Time: FlatStore rebuild ~3 min on a CPU laptop, ~30 s on GPU. The npy + bm25 outputs land in `data/flat_store/`.

---

## 7. Configuration cheat sheet

| Setting | Default | Purpose |
|---|---|---|
| `NOBLE_RAG_BACKEND` | `flat_store` | Foreground retrieval backend |
| `FLAT_STORE_SKIP_FAQ` | `True` | Use `_nofaq` artifact (FAQ has its own channel) |
| `FAQ_INJECT_IN_PROMPT` | `True` | V5 static MD inject toggle |
| `FAQ_SEMANTIC_INJECT_ENABLED` | `True` | V10 per-turn semantic inject toggle |
| `FAQ_SEMANTIC_THRESHOLD` | `0.45` | e5 cosine; higher = stricter |
| `FAQ_SEMANTIC_TOP_K` | `5` | Max FAQ items per turn |
| `SLOW_THINKER_ENABLED` | `True` | Background prefetch toggle |
| `SLOW_THINKER_MODEL` | `gpt-4o-mini` | Prediction model — keep cheap |
| `SLOW_THINKER_MAX_PREDICTIONS` | `5` | Topics per turn |
| `SEMANTIC_CACHE_TTL_S` | `300` | Cache lifetime |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | Single embedding model — both query and chunks must use it |

Changing the embedding model requires re-encoding all artifacts. Don't toggle casually.

---

## 8. Deprecated stubs (Step 13b cleanup)

Keep an eye out for these — they're no-ops kept for one sprint:

- `agent/rag/embeddings.py:preload_bge_model()` — old BGE-m3 path; superseded by e5-large. Delete in next sprint.
- `agent/rag/faq_lookup.py:preload_all_faqs()` — old static FAQ loader; replaced by V10 lazy.
- `agent/rag/vector_store.py` — only `SearchResult` dataclass remains; rest is unused.
- Settings `embedding_model`, `qdrant_*`, `tei_url` — kept for fallback wheel reproducibility.
- `pyproject.toml`: `qdrant-client`, `sentence-transformers` — keep one sprint then drop.

When deleting, run `tests/bench_rag/` to confirm nothing real depends on them.

---

## 9. Common debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| `noble_search` returns `""` always | `NOBLE_RAG_BACKEND=empty` or artifacts missing | Check `data/flat_store/embeddings_*.npy` exists; rebuild |
| Wrong project info in answer | `project_interest` stale; V9 didn't rebuild | Check V7 auto-set fired (`grep "project_interest" logs`) |
| FAQ inject silent | V10 threshold too high or wrong project_interest | Lower `FAQ_SEMANTIC_THRESHOLD` to 0.35 to confirm |
| SlowThinker eats budget | Predictions too aggressive | Drop `SLOW_THINKER_MAX_PREDICTIONS` to 3, raise threshold |
| BM25 returns junk for short queries | Default BM25S settings too lenient on length | Tunes in `flat_store.py:_tokenize_vi`; consider min query length filter |
| Agent says "tôi không biết dự án Lakeside" but Lakeside = NCLB | Alias missing in `project_catalog._ALIASES` | Add the alias, run unit tests, redeploy |

---

## 10. References

- Multilingual E5 large: https://huggingface.co/intfloat/multilingual-e5-large
- BM25S Python: https://github.com/xhluca/bm25s
- Reciprocal Rank Fusion (Cormack et al. 2009): https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- LangGraph multi-stream RAG paper (SlowThinker basis) — internal `Ref/papers/`

Continue → [`05-benchmarking-and-testing.md`](05-benchmarking-and-testing.md) for how RAG quality is measured.
