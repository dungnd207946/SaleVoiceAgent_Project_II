# User Memory — short-term + long-term per-caller memory

Date: 2026-07-13
Branch: feat/refactor2
Status: design (approved in brainstorming, pending spec review)

## Goal

Give Luna per-user memory keyed by phone number:

- **Short-term memory** — at the start of a new conversation, inject the caller's
  latest call summary + last K raw turns into the system prompt
  (`CUSTOMER_PROFILE` block).
- **Long-term memory** — an on-demand tool the agent calls to semantically search
  the caller's own past conversations for something not present in short-term.

## Guiding principles

- **No new MongoDB collection.** The memory store is ONE Qdrant collection
  (`user_memory`) plus reads of the existing Mongo collections. Decided YAGNI in
  brainstorming.
- **No raw-data duplication.** `agent_messages` + `hotline_call_summaries` remain
  the single source of truth for raw transcript + narrative. Qdrant holds only
  vectors + payload for semantic search.
- **Phone is the identity key.** All memory reads/writes are scoped to
  `customer.phone`. No real phone → memory is skipped entirely (no read, no write).
- **Phone is code-supplied, never an LLM parameter.** The `recall_memory` tool
  exposes only `query` to the LLM; the executor injects `phone` from `customer`.
  The Qdrant search pre-filters on that phone BEFORE semantic ranking. This
  guarantees a caller can never (via prompt injection or model error) read another
  caller's memory.
- **Off by default.** Gated behind `NOBLE_USER_MEMORY_ENABLED` (default `false`)
  so rollout does not change current behavior until explicitly enabled.

## Architecture

All consumers depend ONLY on the `MemoryBackend` interface, resolved once via
`get_memory_backend(settings)`. The diagram shows the default v1 (`qa_vector`) impl.

```
WRITE (end of call, fire-and-forget)
  base_session.stop() summary block
    ├─ generate_call_summary + save_call_summary   (existing)
    └─ memory.write_call(phone, session_id, history, ended_at)  (NEW, if enabled + phone)
          [qa_vector impl]
          build QA pairs from history
          for each pair: embed → dedup (find_similar vs this phone's points)
              ≥ threshold → reuse existing point id (refresh)  else → new id
          → vector_store.upsert_points(...)   → Qdrant `user_memory`

SHORT-TERM READ (first turn bootstrap)
  orchestrator.handle_turn first-turn block (_profile_loaded guard)
    if enabled + real phone:
      memory.build_short_term_context(phone, current_session_id)
        [qa_vector impl]
        ├─ load_last_summary_by_phone(phone)                 (existing DAO)
        └─ latest prior session_id (from call_summaries)
              → agent_messages.get_session_messages(sid) tail K
      → render "Bối cảnh lần gọi trước" block, frozen into CUSTOMER_PROFILE

LONG-TERM READ (agent-invoked tool)
  LLM calls recall_memory(query)
    dispatcher injects phone = customer.phone
    → memory.recall(phone, query, top_k)
        [qa_vector impl] encode_query → vector_store.search (phone pre-filter + dense)
    → formatted QA pairs returned to the model
```

## Component 0 — Memory backend abstraction (versioning)

The whole feature lives in a new subpackage `agent/memory/` behind an interface, so
a future, more sophisticated version (e.g. LLM-extracted **graph memory**) can be
swapped in by adding one impl file + one enum value — with NO change to the
consumers (`base_session`, `orchestrator`, the `recall_memory` tool).

```
agent/memory/
  base.py         # MemoryBackend Protocol + MemoryHit dataclass
  qa_vector.py    # v1: QAVectorMemory (this spec)
  vector_store.py # low-level Qdrant `user_memory` ops (reuses qdrant_store._get_client)
  __init__.py     # get_memory_backend(settings) → selects by USER_MEMORY_BACKEND
```

`MemoryBackend` (minimal interface — all consumers depend only on this):

- `async write_call(phone, session_id, history, ended_at) -> None` — distill + persist
  memory from a finished call.
- `async build_short_term_context(phone, current_session_id) -> str` — the short-term
  block injected at bootstrap (empty string when nothing to show).
- `async recall(phone, query, top_k) -> list[MemoryHit]` — long-term retrieval.

`get_memory_backend(settings)` reads `USER_MEMORY_BACKEND` (default `qa_vector`) and
returns a cached singleton. Unknown value → log + fall back to `qa_vector`. When
`NOBLE_USER_MEMORY_ENABLED=false`, consumers skip the backend entirely (no import
cost, no calls). Short-term is routed through the backend too, so a future version
can build it differently (e.g. a summarized subgraph).

Components 1–4 below describe the **v1 `qa_vector`** implementation.

## Component 1 — Qdrant `user_memory` store (`agent/memory/vector_store.py`)

Low-level store used by `qa_vector`. Reuses the `qdrant_store._get_client()`
`AsyncQdrantClient` singleton and the `_Embedder` (e5-large, 1024d, remote-capable).

- **Collection**: dense-only, e5-large 1024d, cosine. (Hybrid/BM25 deferred —
  per-user corpus is small, semantic recall over QA pairs is sufficient. Can add a
  sparse vector later without a schema break, mirroring the noble_kb clone.)
- **Point** = one question/answer exchange. Embedded text uses a fixed template:
  ```
  Khách hỏi: {query}
  Sale trả lời: {answer}
  ```
- **Payload**: `phone` (keyword, payload-indexed — the pre-filter key), `session_id`,
  `ended_at` (epoch int), `query`, `answer`, `project_code` (optional).
- **Point id**: within a single call, `blake2b(f"{session_id}:{turn_index}")` hex
  (idempotent re-write of the same call). Cross-call semantic duplicates are
  collapsed by the dedup step (Component 2), which reuses the matched point's id.
- **Functions**:
  - `ensure_collection()` — create the collection + `phone` payload index if absent
    (called lazily on first write, and/or at boot when enabled).
  - `upsert_points(points)` — upsert prepared PointStructs (id, vector, payload).
  - `find_similar(phone, vector, top_k=1)` — search BY VECTOR (dedup path), phone
    pre-filtered → returns `[(point_id, score)]`.
  - `search(phone, query, top_k)` — `encode_query` → `query_points` with
    `query_filter = Filter(must=[FieldCondition(key="phone", match=MatchValue(phone))])`
    → returns `[(query, answer, score, ended_at)]`.
  - All functions no-op / return `[]` and log (never raise) on Qdrant error, so
    memory failures never break a call.

## Component 2 — Write path (end of call)

In `server/base_session.py` stop() summary block (next to `save_call_summary`,
~L364), add a guarded, fire-and-forget call when
`settings.user_memory_enabled and phone`:

- `await get_memory_backend(settings).write_call(phone, session_id, history, ended_at)`
  — one call through the interface; `base_session` stays thin and version-agnostic.
- Wrapped in try/except + a timeout, log-and-continue. Runs after the summary so it
  never delays it.

The v1 `QAVectorMemory.write_call`:

1. `build_qa_pairs(history)` — walk `history` (already loaded as
   `load_history_from_state`), pairing each `user` message with the next `assistant`
   message's text. Skip `system`/`tool` and empty content. `turn_index` = pair ordinal.
2. Embed all pair texts (`_Embedder.encode_batch`, is_query=False, one batch).
3. **Dedup (per pair)** when `USER_MEMORY_DEDUP_ENABLED`:
   `find_similar(phone, vec, top_k=1)`; if top score ≥ `USER_MEMORY_DEDUP_THRESHOLD`
   → reuse the matched existing point id (refresh: overwrite `answer` + `ended_at` +
   `session_id` → "latest occurrence wins", one canonical point per semantic cluster);
   else → new `blake2b(session_id:turn_index)` id. Dedup runs sequentially so pairs
   later in the same batch also dedup against just-upserted ones.
4. `vector_store.upsert_points(points)`.

`build_qa_pairs` is a pure function, independently unit-testable.

## Component 3 — Short-term read (bootstrap)

In `agent/orchestrator.py` first-turn bootstrap block (`_profile_loaded` guard,
~L129-142), when `settings.user_memory_enabled` and `customer.phone` is a real
phone, call `block = await get_memory_backend(settings).build_short_term_context(
phone, sid)` and store it in `state.scratchpad` alongside `customer_block`, frozen
for the whole call. The prompt builder injects it into `CUSTOMER_PROFILE`. Empty
string → prompt unchanged from today.

The v1 `QAVectorMemory.build_short_term_context`:

- `summary = await load_last_summary_by_phone(phone, since_days)` — existing DAO.
- Resolve the most recent prior `session_id` for the phone from
  `hotline_call_summaries` (already sorted by `ended_at`; skip the current session),
  then `turns = await agent_messages.get_session_messages(prior_sid)` and take the
  last K messages.
- Render a compact "Bối cảnh lần gọi trước" block (summary text + open_actions +
  last K turns). No prior calls → return `""`.
- No schema change to `agent_messages` (2-hop join via call_summaries avoids adding
  a `phone` field).

Prompt wiring: add a `{{ user_memory_block }}` (or extend the customer block) in
`agent/definitions/CUSTOMER_PROFILE.md` / `builder.py`, rendered only when non-empty.

## Component 4 — Long-term retrieval tool `recall_memory`

Tool #11 (offered set grows 10 → 11). Wire all five seams:

1. `agent/tools/recall_memory.py` — executor
   `(args, *, state, customer, callbacks, session_id, rag) -> str`:
   - `phone = customer.phone` (code-supplied). If no real phone → return a short
     "không có dữ liệu lịch sử" string (no search).
   - `query = args["query"]` (the ONLY LLM-supplied field).
   - `hits = await get_memory_backend(settings).recall(phone, query, top_k)`.
   - Format hits into a readable block; empty → "không tìm thấy".
2. `agent/tools/schemas.py` — schema with a single required `query: string`. NO
   `phone` param (guarantees the model cannot supply/forge it).
3. `agent/tools/dispatcher.py` — import + dispatch branch. Does not mutate
   `Customer` (not in `_DIRTIES_CUSTOMER`).
4. `agent/definitions/config.json` — add `"recall_memory"` to `tools`.
5. `agent/definitions/RULES.md` — tool-catalog row: call when the caller references
   something discussed in a PREVIOUS call that is not in the current short-term
   context. Do NOT call for within-current-call recall (history already present).

## Configuration

New settings in `config.py` (`UnifiedSettings`):

| Env | Default | Purpose |
|---|---|---|
| `NOBLE_USER_MEMORY_ENABLED` | `false` | Master flag for the whole feature. |
| `USER_MEMORY_BACKEND` | `qa_vector` | Which `MemoryBackend` impl to use (future: `graph`). |
| `USER_MEMORY_QDRANT_COLLECTION` | `user_memory` | Qdrant collection name. |
| `USER_MEMORY_SHORT_TERM_TURNS` | `6` | K raw messages of the prior call to inject. |
| `USER_MEMORY_RECALL_TOP_K` | `3` | Points returned by `recall_memory`. |
| `USER_MEMORY_SINCE_DAYS` | `30` | Recency window for the short-term summary lookup. |
| `USER_MEMORY_DEDUP_ENABLED` | `true` | Collapse cross-session semantic duplicates at write. |
| `USER_MEMORY_DEDUP_THRESHOLD` | `0.95` | Cosine ≥ this → treat as duplicate (refresh existing point). |

Reuses existing `QDRANT_URL`/`QDRANT_API_KEY` and `EMBED_REMOTE_URL`/`_TOKEN`.

## Identity & edge cases

- **No phone** → feature fully skipped (both read and write).
- **Chat tester (random phone)** → memory accumulates isolated under that random
  phone; harmless, never leaks across users because of the phone pre-filter.
- **Qdrant down / embed down** → all memory ops log-and-continue; the call proceeds
  exactly as today.
- **Cross-user isolation** is enforced structurally by the mandatory `phone`
  pre-filter, and phone is never model-controlled.

## Testing

Follow repo conventions (`pytest asyncio_mode=auto`, markers, fakes):

- `vector_store` unit tests with a fake Qdrant client: upsert shape, `search`/
  `find_similar` build the phone filter, error → `[]`.
- `build_qa_pairs` — pairing, skipping tool/system/empty, turn_index ordinals.
- **Dedup** — near-duplicate pair reuses the existing point id (refresh, no new
  point); below-threshold → new id; dedup off → always new id.
- **Backend factory** — `get_memory_backend` returns `qa_vector` by default, caches
  the singleton, unknown value falls back with a log; consumers skip when flag off.
- Short-term (`build_short_term_context`) — fake Mongo: renders block from summary +
  prior-session turns; empty when no prior calls; skipped when no phone / flag off.
- `recall_memory` dispatch — phone injected from customer (not args); schema exposes
  only `query`; agent loads 11 tools when enabled.
- Latency discipline: assert the write path is off the turn hot path (call-end,
  fire-and-forget) and short-term adds ≤2 Mongo reads once per call at bootstrap.

## Out of scope (YAGNI / deferred)

- Mongo `user_memory` collection (dropped).
- **Graph memory (LLM-extracted)** — the planned v2. Explicitly enabled by the
  `MemoryBackend` abstraction (Component 0): a `graph` impl + a new
  `USER_MEMORY_BACKEND` value, no consumer changes. Not built in this version.
- BM25/hybrid sparse on `user_memory` (dense-only for now).
- Per-turn (incremental) memory writes; within-call recall (Redis short-term
  already covers the current call).
- Telephony-specific handling beyond the shared `base_session`/customer.phone path
  already used by other cross-call features.
