# User Memory Redesign — Per-User Snapshot (drop long-term RAG)

**Date:** 2026-07-13
**Branch:** `feat/refactor2`
**Supersedes the runtime behavior of:** `docs/superpowers/specs/2026-07-13-user-memory-design.md`
(short-term + summary + long-term qa_vector). This redesign keeps short-term,
**replaces** the "latest call summary" with a single evolving per-user snapshot,
and **removes** long-term RAG entirely.

## Problem

The current per-caller memory has three layers:

- **short-term** — at first-turn bootstrap, inject the *latest call summary* +
  the last K turns of the most recent prior session, folded into `customer_block`.
- **summary** — a per-session `hotline_call_summaries` document.
- **long-term** — the `recall_memory` tool over a phone-filtered Qdrant
  `user_memory` collection of QA-pair vectors.

Two issues with this shape:

1. The "summary" the caller's next call sees is only the **single latest
   session's** summary — facts from older sessions are invisible unless the LLM
   happens to `recall_memory` them. There is no cumulative, always-present view
   of the caller across all their calls.
2. Long-term RAG (`recall_memory`) is an extra tool the model must decide to
   call, an extra Qdrant collection to maintain, and in practice a weak fit for
   "who is this caller" — that is better served by a cumulative summary than by
   semantic QA-pair retrieval.

## Goals

- **Short-term:** keep as-is (last K turns of the most recent prior session).
- **Summary → snapshot:** one free-text narrative per caller (keyed by phone),
  **updated across all sessions**. Merged after each call from (existing snapshot
  + full current-call history). Loaded at the start of the next call **in place
  of** the latest-call summary.
- **Long-term:** removed entirely.
- **Always on** for real-phone callers (no enable flag).

## Non-Goals

- **Do NOT touch `hotline_call_summaries` / `generate_call_summary` /
  `save_call_summary`.** The CMS dashboard (handoff inbox, "Cuộc gọi" tab,
  `record_handoff`, `mark_followed_up`, `list_recent_summaries`) depends on the
  per-session summary. It stays exactly as it is; the snapshot is a **parallel,
  additional** write at call-end, unrelated to the dashboard.
- No structured key-facts in the snapshot. Facts already live in the customer
  profile (`customer_block` via `bootstrap_customer_profile`); the snapshot is a
  narrative complement, not a duplicate fact store.

## Design decisions (confirmed with user)

| Decision | Choice |
|---|---|
| Snapshot content | **Free-text narrative** only (facts already in customer profile). |
| Merge prompt requirement | Rewrite must **preserve distinct old facts** (never drop/blur them) and **update matching facts** to be up-to-date. |
| Enable flag | **Removed** — snapshot memory is always on when a real phone is present. |
| Merge timing | **Fire-and-forget** on `stop()` (background), **not** blocking. |
| Cross-session guard | The **next** call/chat from the same phone must not bootstrap until the in-flight merge for that phone finishes — enforced by a **Redis lock keyed by phone**. |
| Guard timeout behavior | Bootstrap waits up to `snapshot_lock_wait_sec` (default **10s**); on timeout it proceeds with the **old snapshot** and logs a warning (never blocks indefinitely). |
| Collection name | **`hotline_user_snapshots`** — the `hotline_` prefix per the shared-DB convention (DB `noble_agent` is shared with the chat-agent; a bare `snapshot` risks collision). Confirmed with user. |

## Chosen approach

**Two independent LLM writes at call-end.** `generate_call_summary` (dashboard,
blocking, unchanged) runs as today; a **new** snapshot-merge LLM call runs
fire-and-forget under a Redis lock. The two have different lifecycles (dashboard
summary must complete for the record; snapshot is background) and different
inputs (snapshot needs the *old snapshot* as input; the dashboard summary does
not), so keeping them separate is cleanest.

*Rejected — a single combined LLM call producing both:* couples two concerns
with different lifecycles and inputs, complicates the prompt/parse, and mixes a
blocking write with a background one. Marginal token saving not worth it.

## Components

### 1. Storage — `storage/user_snapshots.py` (new)

Collection **`hotline_user_snapshots`**, one document per caller:

```
{
  phone:           str,        # unique index — 1 doc / user
  snapshot:        str,        # free-text narrative (the merged content)
  updated_at:      datetime,
  last_session_id: str,        # session that produced the latest merge
  created_at:      datetime,
}
```

DAO (mirrors `call_summaries.py` style — lazy `get_db()`, log-and-continue):

- `async load_snapshot(phone) -> dict | None` — the caller's snapshot doc, or None.
- `async save_snapshot(phone, snapshot_text, session_id) -> str | None` — upsert
  on `phone`; `$set` snapshot/updated_at/last_session_id, `$setOnInsert` created_at.

Unique index on `phone` created in `storage/connection.py::initialize()`.

### 2. Redis lock — `storage/snapshot_lock.py` (new)

Cross-process (aiortc / livekit / telephony are separate processes), so the lock
lives in Redis (already the session-state backend). Key `snapshot:lock:{phone}`.

- `async acquire_snapshot_lock(phone, ttl_sec)` — `SET key 1 EX ttl NX`-style;
  TTL self-heals if a merge crashes without releasing.
- `async release_snapshot_lock(phone)` — `DEL key`.
- `async wait_snapshot_lock_clear(phone, max_wait_sec, poll_sec=0.5) -> bool` —
  poll until the key is absent or `max_wait_sec` elapses; returns True if cleared,
  False on timeout. All ops log-and-continue (Redis down → treat as unlocked so
  the call is never blocked by a memory concern).

### 3. Snapshot logic — `agent/memory/snapshot.py` (new)

- `async merge_snapshot(old_snapshot: str, history: list[dict]) -> str` — build
  the merge prompt (old snapshot + flattened full history), call the **shared
  summary provider chain** (reuse `generator._call_llm` or an equivalent
  `StreamingClient.complete_once` with `provider_model_map` + `NOBLE_AGENT_MODEL`
  primary pin + per-provider timeout), return the new narrative (`""` on failure
  → caller skips the save, old snapshot preserved). Pure prompt construction is a
  separate testable helper.
- `async build_short_term_context(phone, current_session_id) -> str` — replaces
  `qa_vector.build_short_term_context`. Loads the snapshot narrative (via DAO) +
  the last K turns of the most recent prior session (**existing logic kept**:
  find prior session via `call_summaries.list_summaries`, load turns via
  `agent_messages.get_session_messages`). Renders the same `## Bối cảnh khách
  hàng` block shape used today.

**Merge prompt** (careful, per user requirement):

```
Bạn đang duy trì một hồ sơ ghi nhớ (snapshot) tích lũy về một khách hàng qua
NHIỀU cuộc gọi. Dưới đây là snapshot HIỆN TẠI và hội thoại của cuộc gọi VỪA XONG.

Viết lại snapshot MỚI (tiếng Việt, 3-6 câu, plain text) theo quy tắc:
- GIỮ NGUYÊN mọi thông tin/fact cũ vẫn còn đúng — KHÔNG được bỏ sót hoặc làm mờ.
- Nếu cuộc gọi mới có fact MÂU THUẪN với snapshot cũ (vd đổi ngân sách, đổi dự án
  quan tâm) → cập nhật theo thông tin MỚI NHẤT.
- Nếu có fact MỚI khác biệt → bổ sung, không ghi đè fact cũ khác chủ đề.
- Ghi việc còn dang dở / cần follow-up nếu có.
- KHÔNG bịa thông tin không có trong dữ liệu.

SNAPSHOT HIỆN TẠI:
{old_snapshot}

HỘI THOẠI CUỘC GỌI VỪA XONG:
{history}

SNAPSHOT MỚI:
```

### 4. Entry helpers — `agent/memory/__init__.py` (rework)

Keep the guarded, log-and-continue seam; rename/repoint:

- `async update_snapshot_after_call(settings, *, phone, session_id, history)` —
  replaces `record_call_memory`. No-op without a phone. Acquires the Redis lock
  (`snapshot_lock_ttl_sec`), merges, saves, **always** releases in `finally`.
  Swallows all errors.
- `async short_term_block(settings, *, phone, session_id) -> str` — kept.
  Now: `await wait_snapshot_lock_clear(phone, snapshot_lock_wait_sec)` first, then
  delegate to `snapshot.build_short_term_context`. Returns `""` on any error.

Drop the `MemoryBackend` Protocol / `get_memory_backend` factory (single
implementation now; the pluggable-backend indirection was for the removed
long-term layer).

### 5. Call-end wiring (3 paths)

Replace `record_call_memory(...)` fire-and-forget with
`update_snapshot_after_call(...)` in:

- `server/base_session.py` (browser + livekit) — already fires `record_call_memory`.
- `server/text_chat.py` — already fires `record_call_memory`.
- `telephony/session.py` — currently does **not** write user memory; add the
  fire-and-forget snapshot update here too (PSTN is a real-phone path and should
  build snapshots). Placed alongside the existing `save_call_summary` call.

### 6. Bootstrap wiring (2 paths)

`short_term_block` is already called from both bootstrap sites; only the gate
changes (flag removed):

- `agent/orchestrator.py` first-turn bootstrap — call unconditionally when
  `customer.phone` is present (drop `settings.user_memory_enabled`).
- `agent/facade.py` `set_customer` path — same.

### 7. Removals (long-term)

- Delete `agent/tools/recall_memory.py`; remove the dispatcher branch
  (`dispatcher.py`) and schema entry (`schemas.py`).
- Remove `recall_memory` from `agent/definitions/config.json` `tools`
  (11 → **10** tools) and its row in `agent/definitions/RULES.md`.
- Delete `agent/memory/qa_vector.py`, `agent/memory/vector_store.py`,
  `agent/memory/base.py`.
- No Qdrant `user_memory` collection is used anymore (leave any existing data;
  code no longer references it).

### 8. Config — `config.py`

Remove: `user_memory_enabled`, `user_memory_backend`,
`user_memory_qdrant_collection`, `user_memory_recall_top_k`,
`user_memory_dedup_enabled`, `user_memory_dedup_threshold`.

Keep: `user_memory_short_term_turns` (K), `user_memory_since_days`.

Add: `snapshot_lock_wait_sec` (default `10`), `snapshot_lock_ttl_sec`
(default `60`). Document in `.env.example` (remove the deleted vars there too).

## Data flow

```
── Call N ends (stop) ──────────────────────────────────────────────
  generate_call_summary → save_call_summary   (hotline_call_summaries, dashboard — UNCHANGED, blocking)
  fire_and_forget(update_snapshot_after_call):
    acquire_snapshot_lock(phone, ttl=60s)
    old = load_snapshot(phone)                  ("" if first ever)
    new = merge_snapshot(old, full_history)     (LLM, careful merge prompt)
    if new: save_snapshot(phone, new, sid)      (hotline_user_snapshots)
    finally: release_snapshot_lock(phone)

── Call N+1 starts (same phone, first turn bootstrap) ──────────────
  wait_snapshot_lock_clear(phone, max=10s)      (cleared → fresh snapshot; timeout → old snapshot + warn)
  snapshot = load_snapshot(phone).snapshot
  turns    = last K turns of most recent prior session   (UNCHANGED)
  customer_block += "## Bối cảnh khách hàng\n" + snapshot + turns
```

## Error handling / invariants

- Memory must **never** break a call: every entry helper and DAO/lock op is
  log-and-continue.
- The Redis lock is **always** released in `finally`; TTL is the crash backstop.
- `merge_snapshot` returning `""` (LLM failure) **skips the save** — the previous
  snapshot is preserved, never clobbered with empty.
- No phone (chat tester without a real phone / simulate) → no snapshot read/write.
- Bootstrap never blocks longer than `snapshot_lock_wait_sec`.

## Testing

- `test_user_snapshots.py` — DAO upsert/load with an in-memory fake db.
- `test_snapshot_lock.py` — acquire/release/wait-cleared/wait-timeout (fake redis).
- `test_snapshot_merge.py` — merge prompt builder (pure); `merge_snapshot` returns
  old-preserving output on a stubbed LLM; `""` on LLM failure → no save.
- `test_snapshot_short_term.py` — `build_short_term_context` renders snapshot +
  K turns; empty when neither present.
- `test_snapshot_entry_helpers.py` — `update_snapshot_after_call` lock lifecycle
  (acquire → save → release; release even on merge error); `short_term_block`
  waits on the lock then loads.
- Update `test_agent_def.py` (11 → 10 tools; `recall_memory` absent).
- Delete `test_memory_{factory,vector_store,qa_vector}.py`,
  `test_recall_memory.py`, `test_memory_entry_helpers.py` (replaced), and the
  `user_memory` config test.
- CLAUDE.md architecture table (`agent/memory/`) + tool count + Change Log row.

## Open risk (accepted)

Fire-and-forget merge + a 10s bootstrap wait means a caller who hangs up and
redials within ~10s while the merge is slow gets the **old** snapshot for that
one call (logged). Acceptable — the alternative (block the redial indefinitely)
is worse, and the missed update lands on the call after.
