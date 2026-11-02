# CONCERNS 7.2 — Pre-Load-Test Singleton Audit

> Static audit of shared state that could bleed across concurrent sessions under
> the Phase 6 load test (plan §5 Phase 6, §7 row 7.2).
>
> Done before the real sipp runs so we know *where* to look when the runs
> produce weird cross-session results.
>
> Last updated: 2026-04-20.

## Severity summary

| # | Component | Shared scope | Bleed risk | Action |
|---|-----------|--------------|-----------|--------|
| 1 | `SemanticCache` in `MemoryRouter` | **process-global** | **HIGH** | Fix before 50-conc run — see §1 |
| 2 | `AsyncElevenLabsTTS` | per-session (OK) | none | Verify under 100-conc (voice_id bleed) |
| 3 | `LightRAG` KG instances | per-project (OK) | medium | Monitor mutex contention |
| 4 | `SmartTurn` / Sherpa / VieNeu / Gender | process singletons | low | Monitor lock wait times |
| 5 | `@lru_cache` on registry.py | content-keyed | none | — |

## 1. `SemanticCache` — HIGH: cross-session RAG bleed

**Location:**
- `src/noble_agent/agent/rag/memory_router.py:18` — `_router` module-global.
- `src/noble_agent/agent/rag/memory_router.py:106` — single `SemanticCache`
  instance inside the global router.
- `src/noble_agent/agent/rag/semantic_cache.py:93-132` — `get()` does pure
  FAISS similarity on `query_embedding`. No `project_filter` / `session_id`
  in the key.

**Leak path:**

```
Session A (project_filter=NCTH) asks "bảng giá"
  → FastTalker.get_context → vector_store.async_search(project=NCTH)
  → cache.put(embedding(bảng giá), NCTH chunks)

Session B (project_filter=NCLB) asks "bảng giá"
  → FastTalker.get_context
  → FAQ miss → cache.get(embedding(bảng giá)) HIT → returns NCTH chunks
  → B's caller hears NCTH pricing instead of NCLB.
```

Confirmed in `fast_talker.py:57-64,83-86`: `cache.get()` is called with only
the embedding. `project_filter` is only used for the vector-store fallback
path, not for cache lookup or key scoping.

**Fix (minimal):** add `project_filter` to `SemanticCache.get()` and `.put()`;
filter entries at retrieval by `metadata.get("project")` match when
`project_filter` is set. Keep global-scope cache (legitimate reuse across
callers asking about the same project).

**Do not scope by `session_id`** — we *want* cross-session reuse inside a
project. Scoping by session defeats the cache.

**Regression test to add:** two `FastTalker` calls with different
`project_filter` on the same shared cache must not return each other's
chunks.

## 2. `AsyncElevenLabsTTS` — per-session, verified OK

- Constructed in `VoiceAgent._create_tts()` (voice.py:146) — one per
  `VoiceAgent`, one per session.
- `_warm_ws` is instance-scoped; single-writer per session (pipeline loop).
- `set_voice()` mutates `_voice_id` — safe because caller is the same
  session.

**To verify under 100-conc:** no cross-call voice-id bleed (caller A's
voice overriding caller B's). If the load test shows bleed, fix: snapshot
voice_id into a local before the `websockets.connect()` URL is built.

## 3. `LightRAG` per-project KG — shared across same-project sessions

- `src/noble_agent/agent/rag/noble_kb.py:103-108` — `_kg_instances` dict
  keyed by project code, process-global.
- Two sessions on the same project reuse the same `LightRAG` handle.
- LightRAG uses async internally; its mutex safety under concurrent
  `aquery_llm()` is assumed but not proven.

**Action for load test:** run 10-conc with all callers on the same
project code; watch for LightRAG errors or mixed results.

## 4. Singleton ML models — bottleneck, not bleed

| Singleton | Location | Risk |
|-----------|----------|------|
| `bge-m3` embeddings | `agent/rag/embeddings.py:14-25` | serialized inference, not a bleed risk |
| `GenderDetector` | `voice/gender_detector.py:9-22` | torch inference thread-safe, read-only |
| Sherpa recognizer | `voice/stt/sherpa.py:31-44` | per-session streams, shared model OK |
| SmartTurn ONNX | `voice/turn_detection/smart_turn.py:26` | ONNX serializes on CPU — monitor lock waits |
| VieNeu TTS | `voice/tts/vieneu.py:34-37` | `threading.Lock` inside — serial bottleneck; expected |

**None are correctness bugs.** Under 100-conc, they're throughput
bottlenecks. Load test measures p95 TTS/STT ttfb → if any of these
dominate the tail, pool/replace.

## 5. Benign: content-keyed caches

- `registry.py:31-32` — `@lru_cache(maxsize=8)` on project FAQs; keyed by
  `project_interest`. Read-only. OK.
- `voice/tts/_normalize.py:194`, `elevenlabs.py:39`, `vieneu.py:50` —
  normalize maps, loaded once, read-only. OK.

## 6. Open question — `ToolHintSelector` cache

- `agent/llm/tool_hint.py:296-304` — singleton, but `_prefetch_cache` is
  keyed by `session_id` per inspection. Good.
- **Regression test to add:** two session IDs on the same shared
  `ToolHintSelector` must not see each other's prefetched hints.

---

## Fixes queued for this migration

1. **§1 SemanticCache project scoping** — ship before 50-concurrent run.
2. **§2,§3,§6 regression tests** — add under `tests/load/` alongside the
   sipp harness.
3. **§4 monitoring** — covered by the sipp load-test scraper emitting
   p95 per stage. No code change.

All other findings documented for post-Phase-6 follow-up.
