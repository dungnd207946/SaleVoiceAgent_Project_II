# santa-hotline-agent — Post-migration architecture (rev 3)

> Generated 2026-04-20 after merging 13/13 RAG migration steps on `feat/optimize-llm`.
> Source-of-truth document for the **current** state of the agent. Supersedes the
> per-step rationale in `voiceagentrag/docs/analysis/livekit_pipeline_comparison.md` §16-§40
> for sh-specific code; that file remains the migration history reference.

---

## 1. Branch state

```
feat/optimize-llm  (13 commits ahead of develop)
└─ 3fc4330  chore(deploy): remove TEI sidecar, mount fastembed cache (step 13/13)
└─ 615c871  feat(streaming): V10 per-turn FAQ semantic inject (step 12/13)
└─ 86ae714  feat(tools): V7 tool-result auto-set project_interest (step 11/13)
└─ adf828e  feat(streaming): V6 pre-turn sniff + V9 post-turn rebuild (step 10/13)
└─ 4ed6ca2  refactor(rag): shrink bge-m3/Qdrant orphans to deprecation stubs (step 9/13)
└─ 9559522  feat(rag): remove LightRAG from noble_kb (step 8/13, BIG BANG)
└─ 7c95a54  refactor(rag): rewire FastTalker/SlowThinker/MemoryRouter (step 7/13)
└─ 906a768  feat(rag): port FaqSearcher per-turn semantic FAQ search (step 6/13)
└─ ad89b8b  feat(rag): port FlatStore + adapter from voiceagentrag (step 5/13)
└─ 350a18b  chore(deps): add FlatStore stack deps + ignore artifacts (steps 3+4/13)
└─ 63a7023  refactor(catalog): wire 4 consumers to project_catalog (step 2/13)
└─ 8ecd5c2  feat(catalog): add project_catalog as single source of truth (step 1/13)
   develop@8b149e2
```

**Test status**: 239 passed, 1 skipped (FAQ-parallel test obsolete after step 7), 3 pre-existing tool_ack failures (baseline before any rev 3 work).

**Net code delta**: ~+1100 lines (FlatStore + adapter + corpus loader + FaqSearcher + project_catalog), ~-650 lines (LightRAG path + Qdrant client + bge-m3 OpenAIEmbedding + FAQ bge-m3 lookup deleted/stubbed). Total RAG package: 1970 LOC across 13 files (`agent/rag/`).

---

## 2. RAG architecture — single diagram

```
                  ┌─────────────────── PER TURN (foreground, blocks TTFA) ─────────────────┐
                  │                                                                          │
  STT final ──▶ VoiceAgent.handle_utterance(text)                                            │
                  │                                                                          │
                  ▼                                                                          │
  StreamingLLM.stream_response(user_text):                                                   │
    1. V6 pre-turn sniff   ─ catalog.normalize(user_text)                                    │
                            └─ if changed: save_customer + refresh_system_prompt (~50ms)     │
    2. _maybe_fast_route   ─ intent classifier (router agents only)                          │
                            └─ may pre-switch agent + rebuild prompt                         │
    3. V10 FAQ semantic    ─ faq_searcher.inject_faq_searched(text, project_interest)        │
       inject              └─ append top-K FAQ block to system prompt tail (~30ms)           │
    4. Push user msg, run tool loop:                                                         │
       ┌──────────────────────────────────────────────────────────────────────────┐          │
       │ For each LLM streaming round:                                            │          │
       │   ┌─ tool_calls? ─┐                                                      │          │
       │   ▼               │                                                      │          │
       │  execute_tool(name, args, session_id):                                   │          │
       │   ┌─ V7 tool-result auto-set                                             │          │
       │   │  - extract project_code/project_filter per TIER_1_AUTO_SET_TOOLS     │          │
       │   │  - catalog.normalize → save_customer if delta                        │          │
       │   └─ Dispatch:                                                           │          │
       │     - noble_search ───▶ query_noble_kb(query, project_filter)            │          │
       │       └─▶ flat_store_adapter.query_flat_store_for_noble_kb               │          │
       │            └─▶ FlatStore.search_hybrid (BM25+dense RRF, <50ms warm)      │          │
       │     - update_customer ─▶ catalog.normalize project_interest, save        │          │
       │     - switch_agent ───▶ snapshot via catalog.normalize, rebuild prompt   │          │
       │     - get_project_overview/financial/search_units/check_availability/    │          │
       │       schedule_viewing/match_projects/crm_lookup/                        │          │
       │       get_certificate_status ─▶ V7 captures project_code arg             │          │
       │     - escalate / verify_identity / support_ticket / list_* / etc.        │          │
       │   if had_update_customer: rebuild prompt inline                          │          │
       │   if switch_agent: rebuild prompt + re-fetch tool hints                  │          │
       └──────────────────────────────────────────────────────────────────────────┘          │
    5. V9 post-turn rebuild trigger                                                          │
       └─ if project_interest changed AFTER V6 (i.e. V7 fired mid-turn):                     │
          await refresh_system_prompt() so NEXT turn's first LLM call has fresh FAQ          │
                                                                                             │
                  ▼                                                                          │
  Tokens stream → SentenceBuffer → TTS → audio out                                           │
                                                                                             │
                  └────────────────── BACKGROUND (parallel, no TTFA impact) ─────────────────┤
                                                                                             │
  Step 4 above also publishes USER_UTTERANCE → ConversationStream                            │
  → SlowThinker subscribed handler:                                                          │
       1. predict 5 next topics via gpt-4o-mini (~1-2s, fire-and-forget)                     │
       2. for each: encode (e5-large) + FlatStore dense search + cache.put                   │
       3. NEXT turn FastTalker.cache.get hits the prefetch (~5ms vs ~30-50ms cold)           │
                                                                                             │
                                                                       Paper hit rate 75-79% │
                                                                                             │
                  └─────────── FAQ STATIC (V5, prompt-build time) ────────────────────────────┤
                                                                                             │
  registry.build_agent_prompt(agent_id, session_id):                                         │
    └─ if customer.project_interest set AND faq_inject_in_prompt:                            │
       └─ _load_project_faq(code) reads data/faq/{CODE}.md, lru_cache(8)                     │
          └─ Inject "═══ FAQ DỰ ÁN — PRIORITY SOURCE ═══" header + full MD                   │
             (capped 32000 chars by faq_inject_max_chars setting)                            │
                                                                                             │
                  ──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. File inventory — `src/noble_agent/agent/rag/`

| File | LOC | Role | State |
|---|---:|---|---|
| `__init__.py` | 12 | Package marker | unchanged |
| `flat_store.py` | 509 | **PRIMARY**: chunks loader, e5-large embedder, BM25S hybrid search, query LRU cache | added step 5 |
| `flat_store_adapter.py` | 191 | `query_flat_store_for_noble_kb` + `FlatStoreEmbeddingAdapter` + `FlatStoreVectorStoreAdapter` | added step 5+7 |
| `faq_searcher.py` | 231 | V10 per-turn FAQ semantic search (e5-large cosine, disk cache .npz) | added step 6 |
| `noble_kb.py` | 101 | Tool entry point for `noble_search`, backend dispatch | rewritten step 8 |
| `memory_router.py` | 207 | Singleton holder for FastTalker + SlowThinker + cache | rewired step 7 |
| `fast_talker.py` | 113 | Cache-aware retrieval (no FAQ branch after step 7) | rewired step 7 |
| `slow_thinker.py` | 230 | Background prefetch via gpt-4o-mini predictor | unchanged behavior, type hints widened step 9 |
| `semantic_cache.py` | 177 | FAISS IP in-memory L2 cache | unchanged |
| `conversation_stream.py` | 85 | Pub/sub event bus for SlowThinker subscribe | unchanged |
| `embeddings.py` | 41 | **STUB** — `preload_bge_model` + `get_embedding_model` no-ops (delete next sprint) | shrunk step 9 |
| `faq_lookup.py` | 37 | **STUB** — `preload_all_faqs` + `get_project_faq` no-ops (delete next sprint) | shrunk step 9 |
| `vector_store.py` | 36 | **STUB** — only `SearchResult` dataclass + `_PROJECT_TO_WORKSPACE` (delete next sprint) | shrunk step 9 |

**Total**: 1970 LOC (from ~2200 pre-migration after stub-shrinks).

---

## 4. Project catalog — single source of truth

`src/noble_agent/agent/project_catalog.py` (127 lines, pure stdlib).

```python
Project(id, code, name_vi, region, aliases)
  1 NCLB Noble Crystal Long Biên   Long Biên       (5 aliases)
  2 NCTH Noble Crystal Tây Hồ      Tây Hồ          (7 aliases incl. unique "tay ho")
  3 NPLB Noble Palace Long Biên    Long Biên       (5 aliases)
  4 NTTL Noble Palace Tây Thăng Long  Tây Thăng Long  (8 aliases incl. unique "thang long")
  5 SSLC Sunshine Legend City      Hà Nội          (5 aliases incl. unique "sunshine"/"legend")

normalize(raw) → canonical code or "" (longest-first, ambiguous-reject)
by_code(code) → Project | None
by_id(n) → Project | None
all_projects() → tuple
VALID_CODES: frozenset
```

**Ambiguous tokens** (deliberately NOT in any alias list):
- `crystal` → NCLB+NCTH (returns "")
- `long biên` → NCLB+NPLB (returns "")
- `palace` → NPLB+NTTL (returns "")
- `noble` → all 4 Noble projects (returns "")
- `noble palace` → NPLB+NTTL (returns "")

When normalize returns `""`, the agent's `data/agent/definitions/shared/PROJECTS.md` knowledge guides the LLM to ask a clarifying question.

### 9 consumer points (W1-W5 + R1-R4)

| # | File:line | Purpose |
|---|---|---|
| W1 | `tools/__init__.py:101-115` | `update_customer` normalises project_interest, drops invalid/ambiguous |
| W1b | `tools/__init__.py:168-180` | `switch_agent` snapshot normalises project_interest |
| W2 | `tools/booking.py:10-30` | `_normalize_and_validate` returns canonical code, validates |
| W3 | `streaming.py:V6 sniff block` | Pre-turn user_text normalize |
| W4 | `streaming.py:V9 trigger block` | Post-turn delta detection |
| W5 | `tools/__init__.py:V7 helper` | Tool-result auto-set for 10 TIER_1 tools |
| R1 | `registry.py:_load_project_faq` | FAQ MD lookup gated on canonical code |
| R2 | `faq_searcher.py:search` | Per-turn semantic search with project_filter normalize |
| R3 | `registry.py:build_agent_prompt fallback infer` | When pi empty, infer from switch_query |
| R4 | `storage/session_store.py:format_customer_context` | Display `name_vi` not raw code |

---

## 5. Configuration matrix

`src/noble_agent/config.py` — RAG-relevant settings (post-migration defaults).

### Active

| Setting | Default | Env | Effect |
|---|---|---|---|
| `noble_rag_backend` | `flat_store` | `NOBLE_RAG_BACKEND` | `flat_store` (primary) \| `memory_router` (cache+FlatStore dense) \| `empty` (degraded) |
| `flat_store_skip_faq` | `True` | `FLAT_STORE_SKIP_FAQ` | Use `_nofaq` artifact (FAQ has its own channel) |
| `faq_inject_in_prompt` | `True` | `FAQ_INJECT_IN_PROMPT` | V5 static FAQ MD inject |
| `faq_inject_max_chars` | `32000` | `FAQ_INJECT_MAX_CHARS` | V5 max content size |
| `faq_semantic_inject_enabled` | `True` | `FAQ_SEMANTIC_INJECT_ENABLED` | V10 per-turn FAQ inject |
| `faq_semantic_threshold` | `0.45` | `FAQ_SEMANTIC_THRESHOLD` | V10 e5-large cosine threshold |
| `faq_semantic_top_k` | `5` | `FAQ_SEMANTIC_TOP_K` | V10 max FAQ items per turn |
| `faq_match_threshold` | `0.75` | (legacy bge-m3 threshold, unused after step 9) |
| `cache_similarity_threshold` | `0.35` | `CACHE_SIMILARITY_THRESHOLD` | SemanticCache FAISS hit threshold |
| `cache_max_size` | `2000` | | LRU cap |
| `cache_ttl_seconds` | `300.0` | | SlowThinker prefetch TTL |
| `slow_thinker_llm_model` | `gpt-4o-mini` | `SLOW_THINKER_LLM_MODEL` | Predictor model (paper default) |
| `slow_thinker_max_predictions` | `5` | | Topics per USER_UTTERANCE |
| `slow_thinker_prefetch_top_k` | `10` | | Chunks cached per prediction |
| `slow_thinker_rate_limit` | `0.5` | | Min seconds between predictions |
| `embedding_dimension` | `1024` | | e5-large + bge-m3 both 1024d (FAISS cache stays valid) |

### Required env (no default)

- `OPENAI_API_KEY` or `GEMINI_API_KEY` (LLM provider chain)
- `FASTEMBED_CACHE_PATH` (production: mount volume to persist e5-large ONNX)

### Deprecated (Step 13b will remove)

- `embedding_model` (was `BAAI/bge-m3`, e5-large hardcoded in FlatStore)
- `qdrant_url` / `qdrant_api_key` / `qdrant_collection` — kept 1 sprint as `memory_router` fallback target
- `tei_url` — sidecar removed in step 13

---

## 6. Disk layout

| Path | Tracked? | Size | Built by | Purpose |
|---|---|---|---|---|
| `data/faq/{CODE}.md` (5 files) | git | ~50KB | manual | V5 static FAQ inject source |
| `data/faq/{code}_faq.json` (5 files) | git | ~150KB | manual | V10 FAQ Q-A items source (94+89+39+47+78=347 items) |
| `data/rag/lightrag_s02_*/` | git (symlinks) | 0B link | symlink to santa-chat-agent checkout | LightRAG workspace dirs (only `kv_store_text_chunks.json` is read by FlatStore loader) |
| `data/flat_store/embeddings_*.npy` (2 files) | gitignored | ~30MB | `FlatStore.load()` | e5-large encoded chunks (with/without FAQ) |
| `data/flat_store/bm25_index{,_nofaq}/` | gitignored | ~7MB | `FlatStore.build_bm25()` | BM25S sparse matrix + vocab |
| `data/flat_store/meta_*.json` | gitignored | <1KB | `FlatStore.load()` | Cache invalidation hash (chunk count + ids sample + model name) |
| `data/faq_cache/{CODE}_e5large_{hash}.npz` (5 files) | gitignored | ~600KB total | `FaqSearcher.ensure_indexed()` | Per-project FAQ embeddings (hash = sha256 prefix of item ids+questions) |

**Total disk** for ~3741 chunks across 5 projects: ~38MB extra vs pre-migration.

---

## 7. Conflicts & open items

### Resolved

| # | Conflict | Resolution |
|---|---|---|
| 1 | bge-m3 dup load §4.2 (LightRAG + embeddings.py instantiated `SentenceTransformer("BAAI/bge-m3")` independently → 7s freeze + Soniox 408) | Both paths gone; FlatStore is single embedder, e5-large via fastembed ONNX INT8 |
| 2 | TEI sidecar 2.3GB Docker image overhead | Removed step 13; FastEmbed loads ~500MB INT8 ONNX in-process per worker |
| 3 | `_PROJECT_FAQ_MAP` substring matching mis-resolved "long biên" → first dict order | All consumers route through `catalog.normalize` (longest-first ambiguous-reject) |
| 4 | Triple FAQ retrieval (registry static + FastTalker FAQ branch + faq_searcher) | FastTalker FAQ branch removed step 7; only V5 static + V10 dynamic remain |
| 5 | tool_ack 3 pre-existing test failures (baseline before any rev 3 work) | Verified at step 2 stash baseline; not regressions |

### Pending (Step 13b, next sprint after A/B)

| # | Item | Risk | Action |
|---|---|---|---|
| 6 | `qdrant` Docker service still running | low | Remove after A/B confirms `noble_rag_backend=flat_store` stable on prod for 1 week |
| 7 | `pyproject.toml` deps: `qdrant-client`, `sentence-transformers` | low | Drop after #6 — saves ~80MB wheel |
| 8 | Settings `embedding_model`, `qdrant_url`, `qdrant_api_key`, `qdrant_collection`, `tei_url` | low | Remove from `Settings` class after deprecated stubs deleted |
| 9 | Stub files `embeddings.py` (41 LOC), `faq_lookup.py` (37 LOC), `vector_store.py` (36 LOC) | low | Delete entirely + grep for any remaining external import (none expected) |
| 10 | `data/rag/lightrag_s02_*` symlinks point to `NobleX/santa-chat-agent` (not `Official/...`) | low | Repath symlinks after sh+chat-agent merge or copy chunks JSON in-tree |

### Known limitations

| # | Limitation | Mitigation |
|---|---|---|
| 11 | fastembed 0.7.4 uses mean-pooling for e5-large (vag prebuilt embeddings may have used CLS) | Recall on 36-scenario benchmark stays >0.85 in smoke tests; rebuild via `FlatStore.load(force_reencode=True)` if production recall drops |
| 12 | Multi-hop graph queries ("so sánh long biên với palace") have lower recall than LightRAG graph mode had | <10% of production queries — agent's PROJECTS.md prompts LLM to ask clarifying question for cross-project comparisons |
| 13 | First worker cold-start ~5-15s (FastEmbed ONNX load + FlatStore + FAQ pre-embed) | Mitigated by `fastembed_cache` Docker volume + `data/faq_cache/` persisted disk + `LiveKit num_idle_processes=1` keeps a hot spare |
| 14 | SlowThinker prediction LLM cost ~$0.0003/turn on gpt-4o-mini | Worth it: 75% warm hit rate × 40-200ms saved per hit. Auto-disable if `slow_thinker_hit_rate < 0.3` over 100 conv (TODO: metric not yet wired) |

---

## 8. Validation evidence

### Smoke tests (run during migration)

| Step | Test | Result |
|---|---|---|
| 1 | `pytest tests/unit/test_catalog.py` | 15/15 passed |
| 2 | `pytest tests/unit/{test_catalog,test_booking_tools,test_customer_context,test_tool_execution}.py` | 33/33 passed |
| 5 | `FlatStore().load(); search_hybrid("chính sách bàn giao", "NCLB")` | 1st cold 4.5s (ONNX load), 2nd warm 20ms; 3 hits scored 0.835-0.849 |
| 6 | `inject_faq_searched("đặt cọc bao nhiêu tiền", "NCLB")` | 30ms warm, matched "Số tiền đặt cọc...300.000.000VNĐ" |
| 7 | `MemoryRouter.start() + query_context()` | start 12ms, 1st query 34ms, 2nd cached 30ms |
| 8 | `query_noble_kb("chính sách thanh toán", "NCLB")` 3 backend modes | flat_store 23ms warm, memory_router 293ms, empty 0 chars |
| 9 | All imports + stubs verify | All modules load OK |
| 10 | `catalog.normalize` on 4 ambiguous/unique inputs | 4/4 correct (V6 logic verified) |
| 11 | `_v7_auto_set_project_interest` on 5 tool calls | NCLB/NCTH/NTTL all captured, ambiguous skipped, list_projects skipped |
| 12 | `inject_faq_searched` 3 vag bench replay queries | 674/863/555 chars, top match exact |
| 13 | `docker-compose.yml` parse | services list clean, no TEI |

### Test suite trend

| Phase | passed | skipped | failed | notes |
|---|---|---|---|---|
| Pre-rev3 baseline | 244 | 0 | 3 | 3 tool_ack failures (unrelated) |
| After step 2 | 245 | 0 | 3 | +1 catalog test |
| After step 7 | 240 | 1 | 3 | -5 (vector_store wrapper tests) +1 (skipped FAQ-parallel) |
| After step 9 | 239 | 1 | 3 | -1 (test_rag_optimizations cleanup) |
| **Final (step 13)** | **239** | **1** | **3** | **stable** |

---

## 9. Operational runbook

### Initial deploy

```bash
# 1. Code
git checkout feat/optimize-llm
pip install -e ".[dev]"

# 2. Pre-build artifacts (optional but recommended — saves first-call latency)
python -c "
import sys; sys.path.insert(0, 'src')
from noble_agent.agent.rag.flat_store import FlatStore
for skip in (False, True):
    s = FlatStore(skip_faq=skip)
    s.load()  # encodes if cache missing
    s.build_bm25()
"
python -c "
import sys, asyncio; sys.path.insert(0, 'src')
from noble_agent.agent.rag.faq_searcher import get_searcher
async def warm():
    s = await get_searcher()
    await s.ensure_indexed()
asyncio.run(warm())
"

# 3. Docker
docker compose up -d   # agent + redis + mongodb + qdrant (qdrant kept 1 sprint as fallback)

# 4. Verify
curl http://localhost:8766/health/ready
# Should report: redis ok, mongodb ok, llm ok, embeddings ok (fastembed, 3741 chunks, 1024d)
# qdrant ok ONLY if NOBLE_RAG_BACKEND=memory_router
```

### Common diagnostics

| Symptom | Check | Fix |
|---|---|---|
| `noble_search` returns "Không tìm thấy thông tin liên quan." for all queries | `health/ready` shows `embeddings: not warmed` → FlatStore artifact missing | Build artifacts (step above) or set `NOBLE_RAG_BACKEND=empty` for graceful degrade |
| `noble_search` slow (>500ms) | First cold call OK; persistent slowness → check `FASTEMBED_CACHE_PATH` is mounted volume | Mount `fastembed_cache` Docker volume per docker-compose.yml |
| FAQ inject not appearing in prompts | `customer.project_interest` empty → V5 + V10 both gated on it | Verify V6 sniff is firing (grep `[V6] sniffed` in agent logs); check user is naming a project unambiguously |
| Cache hit rate below paper baseline (target 75%) | SlowThinker disabled? rate-limited? | Check `settings.slow_thinker_*`; logs for `[Slow Thinker]` events; verify USER_UTTERANCE events publishing |
| Project_interest set to wrong project | V7 captured ambiguous arg | Check tool args in logs `[V7] tool=X field=Y raw=Z` — confirm `Z` is actually the right project; if catalog.normalize returned wrong code, add to project_catalog._REGISTRY aliases |

### Rollback escalation

1. **First**: `NOBLE_RAG_BACKEND=empty` → noble_search degraded (returns ""), agent still answers everything else from V5 static FAQ + general LLM knowledge.
2. **Second**: `NOBLE_RAG_BACKEND=memory_router` → fall back to SemanticCache + FlatStore dense (no BM25).
3. **Third**: `git revert` step-by-step from 13 backwards. Each commit message has a Rollback section.
4. **Last resort**: `git reset --hard 8b149e2` (back to develop@HEAD pre-rev3). Only after backing up Redis (customer state may have canonical codes that older code expects raw).

---

## 10. Reference documents

- `voiceagentrag/docs/analysis/livekit_pipeline_comparison.md` §16-§40 — full migration history + alternative-considered ladders
- `voiceagentrag/docs/superpowers/specs/2026-04-20-project-interest-capture-design.md` — original spec
- `voiceagentrag/docs/superpowers/plans/2026-04-20-project-interest-capture.md` — TDD plan
- `voiceagentrag/tests/_replay_input.txt` — 8-turn user replay used for end-to-end acceptance

End of post-migration state document.
