# Turn Lifecycle — một lượt hội thoại end-to-end

Seam này mô tả cách hệ thống xử lý **một lượt hội thoại** (một câu người dùng → một câu trả lời của Luna), từ lúc transport đưa text vào cho tới khi phát token ra, chạy tool, lưu state và bắn sự kiện `on_done`.

**Ai gọi nó?** Mọi transport (browser WebRTC `server/session.py`, text chat `server/text_chat.py`, telephony, LiveKit) đều hội tụ về một điểm vào duy nhất: `NobleAgent.stream_response`. Facade là lớp mỏng bọc quanh một singleton `TurnRunner`; `TurnRunner.handle_turn` điều phối cả lượt; `run_turn` chạy vòng lặp LLM + tool. Prompt do `build_system_prompt` dựng bằng jinja2. Summary + semcache chạy nền, không nằm trên đường tới hạn (critical path) của câu trả lời.

## Sơ đồ luồng (bám code thật)

```
transport (text_chat / voice / telephony / livekit)
  │  user_text, on_token, on_tool_start, on_tool_done, interrupt_check
  ▼
NobleAgent.stream_response                       facade.py:343
  ├─ tạo ThinkStripper (ẩn <think> khỏi UI/TTS trừ khi show_thinking)   facade.py:357
  ├─ bọc callbacks trong _Callbacks                                     facade.py:358
  └─ await runner.handle_turn(...)  →  finally: cb.flush()              facade.py:366
  ▼
TurnRunner.handle_turn                            orchestrator.py:87
  ├─ semcache.cancel_refresh (huỷ prefetch cũ)    orchestrator.py:91
  ├─ huỷ warm-task còn chạy từ lượt trước          orchestrator.py:99
  ├─ repo.load(sid) → (meta, customer, state)      orchestrator.py:121
  ├─ history_anchor = len(state.history)           orchestrator.py:122
  ├─ append ThreadMessage(user, user_text)         orchestrator.py:123
  ├─ thử semcache full-hit → _replay_cache_hit     orchestrator.py:125
  └─ nếu không hit → _run_live                     orchestrator.py:146
        ▼
     run_turn (LLM + tool loop)                    runner.py:17
        ├─ build_system_prompt(agent, customer, summary)   runner.py:35
        ├─ messages = [system] + history[summary.covers_turns:]   runner.py:38
        └─ for _ in range(MAX_TOOL_ITERATIONS=7):    runner.py:46
             ├─ interrupt_check() trước LLM → return  runner.py:47
             ├─ content, tool_calls = llm.stream_completion(...)   runner.py:51
             ├─ drop tool_call id/name rỗng           runner.py:65
             ├─ append assistant msg                  runner.py:72
             ├─ nếu không có tool_calls → return       runner.py:76
             ├─ interrupt_check() → inject {"interrupted": true}   runner.py:79
             ├─ for tc: dispatcher.dispatch → append tool msg   runner.py:94
             └─ nếu consume_customer_dirty → dựng lại system prompt   runner.py:105
  ▼  (quay lại handle_turn)
  ├─ meta.last_active = now                         orchestrator.py:155
  ├─ tính delta transcript + save_all               orchestrator.py:162
  ├─ fire_and_forget agent_messages (nếu saved)     orchestrator.py:181
  ├─ nếu pending_user_turns > K → task summary+warm  orchestrator.py:193
  ├─ transcript_writer.write_session_async          orchestrator.py:208
  ├─ on_done (fire-once, luôn chạy)                 orchestrator.py:214
  └─ semcache.schedule_refresh (đoán lượt kế)        orchestrator.py:219
```

## Giải thích từng bước

### Bước 1 — Transport gọi facade, dựng callbacks
Transport gọi [`NobleAgent.stream_response`](src/noble_agent/agent/facade.py#L343) với `user_text` và các callback đồng bộ (`on_token`, `on_tool_start`, `on_tool_done`, `interrupt_check`). Facade tạo một `sink` list để gom token trả về chuỗi cuối, và một [`ThinkStripper`](src/noble_agent/agent/facade.py#L357) để ẩn `<think>...</think>` khỏi kênh hiển thị (UI/TTS) trừ khi `show_thinking=True`. Các callback được bọc trong [`_Callbacks`](src/noble_agent/agent/facade.py#L358) — lớp này chuẩn hoá callback sync/async qua `_maybe_await` và không bao giờ để callback lỗi làm sập lượt. Sau đó gọi [`handle_turn` trong `try/finally`](src/noble_agent/agent/facade.py#L366); `finally` luôn gọi `cb.flush()` để xả phần đuôi còn kẹt trong stripper.

### Bước 2 — Dọn công việc nền của lượt trước
Vào [`handle_turn`](src/noble_agent/agent/orchestrator.py#L87), việc đầu tiên là [huỷ semcache refresh](src/noble_agent/agent/orchestrator.py#L91) đang chạy dở từ lượt trước (predictor/ghost run tranh băng thông LLM và kết quả nay đã cũ), rồi [huỷ warm-task](src/noble_agent/agent/orchestrator.py#L99) prompt-cache còn sót lại. Đây là lý do vì sao mỗi lượt phải dọn trước khi chạy: công việc nền chỉ có giá trị khi chưa có input mới.

### Bước 3 — Load state, ghim anchor, append câu người dùng
[`repo.load(sid)`](src/noble_agent/agent/orchestrator.py#L121) đọc 3 key Redis → `(meta, customer, state)`. Ngay sau đó ghim [`history_anchor = len(state.history)`](src/noble_agent/agent/orchestrator.py#L122) — mốc để có thể cắt history về trạng thái nhất quán nếu lượt crash giữa chừng. Rồi [append `ThreadMessage(role="user", ...)`](src/noble_agent/agent/orchestrator.py#L123) vào history.

### Bước 4 — Thử semcache (mặc định tắt), else chạy live
Gọi [`_try_cache_hit`](src/noble_agent/agent/orchestrator.py#L125). Chỉ entry `mode="full"` mới được replay ([partial thì bỏ qua, chạy live](src/noble_agent/agent/orchestrator.py#L386)). Nếu có hit, [`_replay_cache_hit`](src/noble_agent/agent/orchestrator.py#L394) phát lại chuỗi token/tool_start/tool_done đã lưu thay vì gọi LLM; nếu replay lỗi thì [cắt history về anchor + re-append câu user](src/noble_agent/agent/orchestrator.py#L141) rồi rơi xuống live. Đường live gọi [`_run_live`](src/noble_agent/agent/orchestrator.py#L146).

### Bước 5 — `_run_live` dựng dispatcher và gọi `run_turn`
[`_run_live`](src/noble_agent/agent/orchestrator.py#L248) tạo [`ToolDispatcher`](src/noble_agent/agent/orchestrator.py#L258) (giữ tham chiếu `state`/`customer`/`rag`/`callbacks`), lấy `interrupt_check` từ callbacks, rồi [gọi `run_turn`](src/noble_agent/agent/orchestrator.py#L268) với model map + primary provider đã tính sẵn ở `__init__`. Toàn bộ được bọc trong `try/except BaseException` để giữ invariant history khi crash (xem phần Invariant).

### Bước 6 — Dựng system prompt
Trong [`run_turn`](src/noble_agent/agent/runner.py#L17), [`build_system_prompt`](src/noble_agent/agent/runner.py#L35) được gọi. Hàm [`build_system_prompt`](src/noble_agent/agent/prompts/builder.py#L39) render jinja2 template với `soul`, `rules`, bảng dự án động [`_project_table()`](src/noble_agent/agent/prompts/builder.py#L28) (mỗi dòng `CODE — tên — khu vực — loại hình`, lấy từ cache registry DB-warmed nên không I/O), block khách hàng, summary (truyền `text` thô, không phải `model_dump()`) và ngày VN. Messages gửi LLM = `[system]` + [`history[summary.covers_turns:]`](src/noble_agent/agent/runner.py#L38) — chỉ gửi phần history sau ranh giới đã được summary bao phủ.

### Bước 7 — Vòng lặp LLM + tool (tối đa 7 vòng)
Vòng [`for _ in range(MAX_TOOL_ITERATIONS)`](src/noble_agent/agent/runner.py#L46) (=7, [định nghĩa ở đây](src/noble_agent/agent/runner.py#L14)). Mỗi vòng: kiểm tra [interrupt trước khi gọi LLM](src/noble_agent/agent/runner.py#L47); gọi [`llm.stream_completion`](src/noble_agent/agent/runner.py#L51) trả về `(content, tool_calls)`, stream token qua `callbacks.on_token`. Nếu không có `tool_calls` thì [return](src/noble_agent/agent/runner.py#L76) — kết thúc lượt. Nếu có tool, [dispatch từng tool và append tool message](src/noble_agent/agent/runner.py#L94). Sau khi chạy tool, nếu [`dispatcher.consume_customer_dirty()`](src/noble_agent/agent/runner.py#L105) trả True (một tool đã đổi `Customer`, ví dụ set `project_interest`) thì [dựng lại system prompt](src/noble_agent/agent/runner.py#L106) trước vòng LLM kế để prompt phản ánh state mới.

### Bước 8 — Cập nhật meta, tính delta transcript, lưu state
Quay lại `handle_turn`: [`meta.last_active = now`](src/noble_agent/agent/orchestrator.py#L155). Tính [delta các message mới](src/noble_agent/agent/orchestrator.py#L162) so với cursor `_persisted_msg_count` trong scratchpad, rồi [`save_all`](src/noble_agent/agent/orchestrator.py#L168). Chỉ khi [`saved` thành công](src/noble_agent/agent/orchestrator.py#L181) mới `fire_and_forget` insert `agent_messages` (tránh double-insert nếu save_all fail rồi lượt sau tính lại delta cũ).

### Bước 9 — Kích hoạt summary nền (theo ngưỡng user-turn)
Đếm [`pending_user_turns`](src/noble_agent/agent/orchestrator.py#L192) (số message `role=user` sau ranh giới `covers_turns`). Nếu [vượt `summary_threshold_K`](src/noble_agent/agent/orchestrator.py#L193) thì spawn [`asyncio.create_task(_run_summary_then_warm)`](src/noble_agent/agent/orchestrator.py#L197) với bản copy history/customer (chống bị lượt sau mutate). [`_run_summary_then_warm`](src/noble_agent/agent/orchestrator.py#L294) chạy `summarize_and_persist` tới cùng (không huỷ được), rồi nếu có summary mới và bật `summary_warm_cache` thì [lên lịch warm](src/noble_agent/agent/orchestrator.py#L320). [`_warm`](src/noble_agent/agent/orchestrator.py#L338) phát lại **đúng shape request của lượt kế** (max_tokens nhỏ, kết quả vứt bỏ) để làm nóng prompt-cache của provider — provider-agnostic vì đi cùng đường `stream_completion`.

### Bước 10 — Transcript, on_done, schedule semcache
Nếu bật, [`transcript_writer.write_session_async`](src/noble_agent/agent/orchestrator.py#L208) ghi transcript. Sau đó [`_fire_done_once()`](src/noble_agent/agent/orchestrator.py#L214) bắn `on_done`. Cuối cùng [`semcache.schedule_refresh`](src/noble_agent/agent/orchestrator.py#L219) đoán lượt kế — đặt SAU khi lượt xong để predictor thấy history vừa chốt (gồm cả câu trả lời của assistant).

## Invariant PHẢI giữ

1. **Mỗi `assistant(tool_calls=[...])` phải có đủ tool message đi kèm trước khi persist.** Nếu không, request kế sẽ bị provider trả 400 (orphan `tool_call_id`). Vòng dispatch [append tool message cho từng tool_call](src/noble_agent/agent/runner.py#L94). Hàm phát hiện vi phạm: [`_last_assistant_has_unresolved_tool_calls`](src/noble_agent/agent/orchestrator.py#L41).

2. **Crash giữa tool-loop → cắt history về `history_anchor`.** `_run_live` bọc `run_turn` trong `except BaseException`; nếu còn tool_calls chưa resolve thì [`del state.history[history_anchor:]`](src/noble_agent/agent/orchestrator.py#L289) để lượt sau load được prompt nhất quán, rồi re-raise.

3. **Drop tool_call có `id` hoặc `name` rỗng** (provider cắt giữa stream). Lọc ở [`valid_tcs`](src/noble_agent/agent/runner.py#L66): chỉ giữ tool_call có cả `id` và `function.name`; phần còn lại bị bỏ để không persist orphan.

4. **Interrupt giữa tool-loop → inject `{"interrupted": true}`.** Khi `interrupt_check()` True sau khi đã có tool_calls, [append tool message placeholder](src/noble_agent/agent/runner.py#L82) cho từng tool_call để giữ invariant #1 rồi return.

5. **`on_done` LUÔN fire** — dù thành công, exception hay `CancelledError` (voice barge-in). Cơ chế fire-once [`_fire_done_once`](src/noble_agent/agent/orchestrator.py#L110); gọi ở [nhánh CancelledError](src/noble_agent/agent/orchestrator.py#L233), [nhánh Exception](src/noble_agent/agent/orchestrator.py#L237), và [`finally` last-resort](src/noble_agent/agent/orchestrator.py#L242) cho cả BaseException như SystemExit.

6. **Task nền phải giữ strong-ref** — asyncio chỉ giữ weakref trong registry nên nếu không giữ ref, CPython có thể GC task trước khi xong (rơi summary âm thầm). Set giữ ref: [`self._bg_tasks`](src/noble_agent/agent/orchestrator.py#L81); mỗi task được [`add` vào set + `add_done_callback(discard)`](src/noble_agent/agent/orchestrator.py#L205).
