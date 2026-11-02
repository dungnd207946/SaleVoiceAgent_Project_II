# Storage — Redis 3-key, MongoDB, summary WATCH

Lớp `storage` giữ trạng thái hội thoại của Luna. **Redis là source-of-truth nóng** (3 key per session, TTL ~24h) cho một turn đang chạy; **MongoDB là sink phân tích / dashboard CSKH** (conversation transcript, bookings, call summaries, call events, customer profile cross-session, project collections). Mỗi turn: orchestrator `load` 3 key Redis → chạy LLM/tool → `save_all` 3 key → fire-and-forget các write Mongo (không chặn TTFT/TTFA). Cập nhật summary chạy nền, ghi riêng key `state` bằng WATCH để không đè history của turn live.

Có hai lớp code song song:
- **`StateRepo` (mới, unified)** — `repo.py` + `models.py`, dùng pydantic model chặt chẽ. Đây là đường đi chính của agent Luna.
- **`session_store.py` (legacy, dict thô)** — vẫn còn cho dashboard/telephony đọc-ghi meta/customer/bookings; đọc cùng key Redis nhưng qua JSON dict, không qua pydantic.

## Sơ đồ

```
                         ┌─────────────────────────── REDIS (TTL = session_ttl_seconds) ──────────────────────────┐
   một session (sid)     │  session:{sid}:meta       → Meta      (session_id, started_at, last_active, phone)     │
                         │  session:{sid}:customer   → Customer  (name, gender, phone, project_interest, ...)     │
                         │  session:{sid}:state      → State     (history[] + summary? + scratchpad{})            │
                         └────────────────────────────────────────────────────────────────────────────────────────┘

   MỘT TURN (orchestrator.handle_turn)
     repo.load(sid) ──mget 3 key──▶ (meta, customer, state)      [repo.py load]
        history.append(user_text)
        run_live / cache replay  → history += assistant/tool msgs
        meta.last_active = now
        delta = history[persisted_cursor:]                        (tính transcript delta)
     repo.save_all(sid, meta, customer, state) ──pipeline SET×3 ex=TTL──▶ Redis
        └─(nếu saved) fire_and_forget:
              agent_messages.insert_messages(delta)  ──▶ Mongo  agent_messages
        └─(nếu pending_user_turns > K) summarize_and_persist
              └─ repo.update_summary(sid, summary) ──WATCH state──▶ Redis

                         ┌──────────────────────────────── MONGODB (motor, best-effort) ─────────────────────────┐
                         │  conversations   messages[] per session (legacy; unified KHÔNG ghi)      TTL 30d       │
                         │  agent_messages  1 doc / message (transcript CSKH: user|agent)            (không TTL)   │
                         │  bookings        embedded array per session                               TTL 30d       │
                         │  bookings_flat   1 doc / lịch hẹn (index phone/project/date)              TTL cấu hình  │
                         │  customers       profile cross-session, key = phone (unique)              không TTL     │
                         │  call_summaries  key (phone, ended_at); unique session_id                 TTL 90d       │
                         │  call_events     audit log lifecycle (dual-write field)                   TTL 30d       │
                         │  noble_profiles / outbound_briefs / outbound_calls                        TTL riêng     │
                         │  project_du_an / project_can_ho  (project + inventory — đọc bởi RAG/tools)             │
                         └────────────────────────────────────────────────────────────────────────────────────────┘
```

## Các model dữ liệu

Định nghĩa trong [models.py](src/noble_agent/storage/models.py). Đây là schema pydantic dùng cho `StateRepo`; `session_store.py` legacy dùng dict thô nhưng cố ý ghi cùng shape để parse được qua các model này.

| Model | Field quan trọng | Định nghĩa |
|---|---|---|
| `Meta` | `session_id`, `started_at`, `last_active`, `phone?` | [models.py:15](src/noble_agent/storage/models.py#L15) |
| `Customer` | `name`, `full_name`, `gender ∈ {M,F}?`, `phone`, `project_interest`, `purpose`, `budget`, `preferred_area`, `bedroom_count`, `is_buyer`, `is_noble_customer`, `noble_info` | [models.py:22](src/noble_agent/storage/models.py#L22) |
| `ThreadMessage` | `role ∈ {user,assistant,tool,system}`, `content`, `tool_calls?`, `tool_call_id?`, `name?` (+ `to_openai()` render) | [models.py:37](src/noble_agent/storage/models.py#L37) |
| `ThreadSummary` | `text`, `covers_turns` (boundary index vào history), `updated_at` | [models.py:58](src/noble_agent/storage/models.py#L58) |
| `State` | `history: list[ThreadMessage]`, `summary: ThreadSummary | None`, `scratchpad: dict` (giữ `_persisted_msg_count`) | [models.py:64](src/noble_agent/storage/models.py#L64) |

## Giải thích từng bước (luồng 1 turn)

1. **Khởi tạo repo với TTL.** Facade dựng singleton `StateRepo(redis_client=..., ttl_seconds=settings.session_ttl_seconds)` — [facade.py:170](src/noble_agent/agent/facade.py#L170); constructor lưu `self._ttl` — [repo.py:36](src/noble_agent/storage/repo.py#L36). Client Redis là singleton async lazy-connect đọc `REDIS_URL` — [redis_client.py:25](src/noble_agent/storage/redis_client.py#L25).

2. **`repo.load(sid)` → (meta, customer, state).** Một lệnh `mget` lấy 3 key cùng lúc rồi validate JSON qua pydantic; nếu blob lệch schema/hỏng thì log cảnh báo và **reset về default** thay vì crash turn — [repo.py:47](src/noble_agent/storage/repo.py#L47). Key được sinh bởi `_keys` (`session:{sid}:meta|customer|state`) — [repo.py:40](src/noble_agent/storage/repo.py#L40).

3. **Append user message vào history.** Orchestrator ghi lại `history_anchor = len(state.history)` (mốc rollback) rồi `history.append(user)` — [orchestrator.py:121](src/noble_agent/agent/orchestrator.py#L121). Sau đó cache-replay hoặc `_run_live` bồi thêm các message assistant/tool.

4. **Cập nhật `meta.last_active` + tính transcript delta.** `last_active` set = now — [orchestrator.py:155](src/noble_agent/agent/orchestrator.py#L155). Delta transcript tính TRƯỚC khi save, dựa trên cursor `_persisted_msg_count` trong scratchpad, và bump cursor in-memory — [orchestrator.py:162](src/noble_agent/agent/orchestrator.py#L162).

5. **`save_all` — pipeline SET 3 key với `ex=TTL`.** Một pipeline ghi cả meta/customer/state, mỗi key kèm `ex=self._ttl` (mọi write đều làm mới TTL) — [repo.py:89](src/noble_agent/storage/repo.py#L89). Orchestrator bọc trong try/except và set cờ `saved` — [orchestrator.py:168](src/noble_agent/agent/orchestrator.py#L168).

6. **Fire-and-forget transcript sang Mongo (gate trên `saved`).** Chỉ khi `save_all` thành công (cursor đã lên Redis) mới insert delta để tránh double-insert khi save fail — [orchestrator.py:181](src/noble_agent/agent/orchestrator.py#L181). Insert chạy nền qua `fire_and_forget` — [persist.py:22](src/noble_agent/storage/persist.py#L22).

7. **Summary update dùng WATCH (chạy nền).** Khi `pending_user_turns > summary_threshold_K`, `summarize_and_persist` sinh summary rồi gọi `repo.update_summary` — [orchestrator.py:308](src/noble_agent/agent/orchestrator.py#L308). `update_summary` là read-modify-write **chỉ trên key `state`**, dùng WATCH: `watch(k_state)` → `get` → sửa `state.summary` → `multi()` → `set(ex=TTL)`; retry 1 lần nếu WATCH conflict, no-op nếu key chưa tồn tại — [repo.py:97](src/noble_agent/storage/repo.py#L97).

## persist.py & agent_messages.py — lớp dual-write / best-effort mới

- **`persist.py::fire_and_forget`** — helper chạy coroutine nền và **giữ strong-ref trong set `_bg_tasks`** cho tới khi xong (asyncio registry chỉ giữ weakref → không có set này CPython có thể GC task đang chạy và mất write). Không có event loop → đóng coro, trả `None`. Mọi Mongo write trên/gần đường turn dùng nó để không chặn TTFT/TTFA — [persist.py:22](src/noble_agent/storage/persist.py#L22).

- **`agent_messages.py`** — transcript per-message cho dashboard CSKH: mỗi turn ghi các message MỚI thành `{session_id, role, content, created_at}`. Role map nội bộ → dashboard: `user→user`, `assistant→agent`, **bỏ qua** `system`/`tool` và message content rỗng; best-effort (lỗi chỉ log). Insert delta: [agent_messages.py:28](src/noble_agent/storage/agent_messages.py#L28). Đọc lại (dashboard/`session_store.list_sessions`+`get_session_detail`): [agent_messages.py:67](src/noble_agent/storage/agent_messages.py#L67). Đây là collection thay thế `conversations` — unified agent KHÔNG còn ghi `conversations` (xem chú thích [session_store.py:445](src/noble_agent/storage/session_store.py#L445)).

- **`call_events.py::log_event` — dual-write field thật.** Mỗi doc mang **hai bộ field trùng giá trị**: `ts/event/data/...` (reader trong repo: `query_events`/`count_today`) VÀ `timestamp/event_type/metadata` (dashboard CSKH) — [call_events.py:44](src/noble_agent/storage/call_events.py#L44). Cũng chạy fire-and-forget, best-effort. (Test ý đồ: `tests/unit/unified/test_call_events_dualwrite.py`.)

- **`call_summaries.py`** — DAO cho tóm tắt cuộc gọi cuối phiên: `save_call_summary` upsert theo `session_id` (unique, chống double-trigger `stop()`) — [call_summaries.py:16](src/noble_agent/storage/call_summaries.py#L16); `record_handoff` ghi bản handoff realtime cho sale.

- **`session_store.py` (legacy)** — API dict thô đọc/ghi cùng key Redis (meta/customer/state/speakers) + Mongo (conversations/bookings/customers cross-session). Cố ý ghi shape hợp lệ để `StateRepo` parse được (ví dụ `save_customer` strip empty-string trước khi ghi vì `Customer.gender` là `Literal` không nhận `""`) — [session_store.py:211](src/noble_agent/storage/session_store.py#L211). TTL của path này = `redis_session_ttl_hours * 3600` — [session_store.py:30](src/noble_agent/storage/session_store.py#L30).

- **`connection.py` / `mongo_client.py`** — `ConnectionManager.initialize()` kết nối Redis+Mongo (idempotent) và tạo toàn bộ TTL/unique index cho các collection Mongo — [connection.py:217](src/noble_agent/storage/connection.py#L217), index block từ [connection.py:88](src/noble_agent/storage/connection.py#L88). `mongo_client.get_db()` là singleton motor riêng, trả `None` nếu thiếu `MONGODB_URI`/motor → mọi DAO tự bỏ qua write một cách an toàn — [mongo_client.py:32](src/noble_agent/storage/mongo_client.py#L32).

(Các test ý đồ persist mới nằm ở `tests/unit/unified/test_*_persist.py` và `test_call_events_dualwrite.py`.)

## Invariant PHẢI giữ

1. **Summary WATCH optimistic concurrency.** Task summary nền và turn live có thể ghi key `state` đồng thời. `update_summary` PHẢI đọc-sửa-ghi trong pipeline WATCH (`watch → get → multi → set`) và chỉ đụng `state.summary`, không được `save_all` toàn bộ state — nếu không sẽ đè history mà turn live vừa append. WATCH conflict → retry 1 lần rồi bỏ (overflow sau retry) — [repo.py:97](src/noble_agent/storage/repo.py#L97).

2. **History consistency + persisted-count cursor.** `history` chỉ được lớn lên trên success path (mốc `history_anchor` để rollback khi crash giữa tool-loop). Cursor `_persisted_msg_count` là index đơn điệu vào `state.history`; transcript delta chỉ được insert khi `save_all` **đã** thành công (cursor đã lên Redis), nếu không sẽ double-insert ở turn sau — [orchestrator.py:181](src/noble_agent/agent/orchestrator.py#L181).

3. **TTL = `session_ttl_seconds`, làm mới mỗi write.** `StateRepo` phải set `ex=self._ttl` trên CẢ `save_all` (3 key) lẫn `update_summary` (key state) để phiên đang hoạt động không bị hết hạn giữa chừng — [repo.py:92](src/noble_agent/storage/repo.py#L92) và [repo.py:116](src/noble_agent/storage/repo.py#L116). Giá trị `session_ttl_seconds` (default 86400 = 24h) khai báo tại [config.py:62](src/noble_agent/config.py#L62) và có ràng buộc min ở validate config [config.py:643](src/noble_agent/config.py#L643).

4. **Mọi write Mongo là best-effort, không được chặn turn.** DAO phải kiểm tra `get_db() is None` và nuốt exception (chỉ log); write trên đường turn phải qua `fire_and_forget` (giữ strong-ref chống GC) — [persist.py:22](src/noble_agent/storage/persist.py#L22), [mongo_client.py:32](src/noble_agent/storage/mongo_client.py#L32).
