# Tools & DB — dispatcher, 10 tool của Luna, kết nối xuống MongoDB

Seam này mô tả cách agent Luna gọi công cụ (tool) và cách các tool đó chạm xuống dữ liệu thật. Trong kiến trúc single-agent, `runner.run_turn` chạy vòng lặp LLM ↔ tool: LLM trả về `tool_calls`, runner đưa từng call cho `ToolDispatcher.dispatch`, dispatcher match tên tool → gọi executor tương ứng trong `agent/tools/<name>.py`, executor trả về một **string** (thường là JSON) rồi được nối lại vào history như một `tool` message để LLM đọc ở vòng kế tiếp. Một số executor chỉ đọc/ghi Redis SessionState, số khác truy vấn MongoDB qua data-layer async ở `data/structured_data.py`, và `noble_search` đi xuống RAG.

`config.json` quyết định **10 tool được offer** cho Luna; `schemas.py` giữ schema OpenAI của TẤT CẢ tool (kể cả 3 tool post-sale không offer). Sửa prompt/tool là sửa markdown + JSON, không đụng code logic.

## Sơ đồ luồng

```
LLM stream_completion → tool_calls
        │
        ▼
runner.run_turn  ──for tc in tool_calls──▶  ToolDispatcher.dispatch(tc)
   (agent/runner.py:94)                        (agent/tools/dispatcher.py:51)
                                                    │  match name
                                                    ▼
                                          _exec(name, args)   (dispatcher.py:85)
                                                    │
        ┌───────────────────────────┬───────────────┴───────────────┬─────────────────────────┐
        ▼                           ▼                                ▼                         ▼
  noble_search.run            projects_info / project_financial   booking / schedule_viewing   support_ops
   → RAG (rag.search)          → data/structured_data (Mongo)      → Redis state.scratchpad     → crm_data (mock)
                               → project_du_an / project_can_ho    + best-effort bookings_flat  → escalate / send_media
        │                           │                                │                         │
        └───────────────────────────┴───────────────┬───────────────┴─────────────────────────┘
                                                     ▼
                                     string (JSON) trả về  → ThreadMessage(role="tool")
                                                     ▼
                          runner nối vào history + messages  (runner.py:96-103)
                                                     ▼
                          consume_customer_dirty() → rebuild system prompt (runner.py:105)
```

## Bảng 10 tool

10 tool offer cho Luna, khai báo tại [config.json:6-17](src/noble_agent/agent/definitions/config.json#L6). Branch dispatch ở [dispatcher.py:85-116](src/noble_agent/agent/tools/dispatcher.py#L85).

| Tool | Vai trò | Executor |
|---|---|---|
| `update_customer` | Ghi field hồ sơ khách vào Customer (normalize project, validate phone) | [update_customer.py:23](src/noble_agent/agent/tools/update_customer.py#L23) |
| `noble_search` | Tra tài liệu RAG (tiện ích/pháp lý/mô tả); auto-set `project_interest` | [noble_search.py:17](src/noble_agent/agent/tools/noble_search.py#L17) |
| `list_projects` | Liệt kê dự án từ `project_du_an`, lọc theo khu vực | [projects_info.py:17](src/noble_agent/agent/tools/projects_info.py#L17) |
| `get_project_overview` | Tổng quan 1 dự án từ `project_du_an` | [projects_info.py:24](src/noble_agent/agent/tools/projects_info.py#L24) |
| `match_projects` | Gợi ý dự án theo tiêu chí khách (dựa trên listing) | [projects_info.py:32](src/noble_agent/agent/tools/projects_info.py#L32) |
| `get_project_financial` | Giá/tồn kho tổng hợp từ `project_can_ho` (chỉ `pricing` có nguồn) | [project_financial.py:16](src/noble_agent/agent/tools/project_financial.py#L16) |
| `search_units` | Lọc căn cụ thể trong inventory `project_can_ho` | [project_financial.py:37](src/noble_agent/agent/tools/project_financial.py#L37) |
| `booking` | Router 4 action: `check_availability`/`schedule`/`list`/`modify` | [booking.py:17](src/noble_agent/agent/tools/booking.py#L17) |
| `escalate` | Off-ramp duy nhất → chuyển người thật (post-sale / giá private / thiếu data) | [support_ops.py:97](src/noble_agent/agent/tools/support_ops.py#L97) |
| `send_media` | Stub gửi thông tin qua app/SMS, ack cho khách | [support_ops.py:150](src/noble_agent/agent/tools/support_ops.py#L150) |

`booking` là router mỏng: `check_availability` → [availability.py:15](src/noble_agent/agent/tools/availability.py#L15); `schedule`/`list`/`modify` → [schedule_viewing.py](src/noble_agent/agent/tools/schedule_viewing.py) (`schedule_viewing` [:70](src/noble_agent/agent/tools/schedule_viewing.py#L70), `list_bookings` [:171](src/noble_agent/agent/tools/schedule_viewing.py#L171), `modify_booking` [:185](src/noble_agent/agent/tools/schedule_viewing.py#L185)).

**3 tool KHÔNG offered** (vẫn còn schema + branch dispatch, để bật lại dễ dàng) — post-sale, hiện chuyển hết sang `escalate`:

| Tool | Schema | Branch dispatch |
|---|---|---|
| `crm_lookup` | [schemas.py:253](src/noble_agent/agent/tools/schemas.py#L253) | [dispatcher.py:105](src/noble_agent/agent/tools/dispatcher.py#L105) |
| `verify_identity` | [schemas.py:282](src/noble_agent/agent/tools/schemas.py#L282) | [dispatcher.py:107](src/noble_agent/agent/tools/dispatcher.py#L107) |
| `support_ticket` | [schemas.py:297](src/noble_agent/agent/tools/schemas.py#L297) | [dispatcher.py:109](src/noble_agent/agent/tools/dispatcher.py#L109) |

Chúng không nằm trong `config.json` nên `schemas_for` không đưa vào catalog Luna thấy — nhưng `_exec` vẫn xử lý được nếu tên xuất hiện.

## Luồng dispatch từng bước

1. Runner lặp tối đa `MAX_TOOL_ITERATIONS = 7` vòng; mỗi vòng gọi `llm.stream_completion` lấy `(content, tool_calls)` — [runner.py:46](src/noble_agent/agent/runner.py#L46), [runner.py:51](src/noble_agent/agent/runner.py#L51).
2. Runner **lọc bỏ** tool_call bị cắt giữa stream (thiếu `id` hoặc `name`) trước khi persist, tránh orphan `tool_call_id` làm 400 turn sau — [runner.py:65-70](src/noble_agent/agent/runner.py#L65).
3. Nếu không còn `tool_calls` → return (turn xong). Nếu bị interrupt giữa chừng, inject placeholder `{"interrupted": true}` cho mỗi call để giữ invariant history — [runner.py:76](src/noble_agent/agent/runner.py#L76), [runner.py:79-92](src/noble_agent/agent/runner.py#L79).
4. Với mỗi `tc`, runner gọi `await dispatcher.dispatch(tc)` — [runner.py:94-95](src/noble_agent/agent/runner.py#L94).
5. `dispatch` đọc `name` + parse `arguments` (bad JSON → emit trace + trả lỗi, không crash) rồi bắn `on_tool_start` — [dispatcher.py:51-64](src/noble_agent/agent/tools/dispatcher.py#L51).
6. `dispatch` gọi `_exec(name, args)` trong try/except; tool crash được bọc thành JSON `{"error": ...}` và set cờ `crashed` — [dispatcher.py:66-71](src/noble_agent/agent/tools/dispatcher.py#L66).
7. `_exec` match tên → gọi executor. Chữ ký executor không đồng nhất (mỗi tool nhận đúng thứ nó cần từ `self`): `noble_search` nhận `(rag, self, args)`, `booking` nhận `(state, customer, args, session_id=...)`, `escalate` nhận `(state, customer, args)`, `update_customer` nhận `(customer, args)` — [dispatcher.py:85-116](src/noble_agent/agent/tools/dispatcher.py#L85). (Các trường `state/customer/rag/callbacks/session_id` được nạp vào dispatcher lúc khởi tạo — [dispatcher.py:36-42](src/noble_agent/agent/tools/dispatcher.py#L36).)
8. Nếu tool chạy thành công VÀ (tên ∈ `_DIRTIES_CUSTOMER` HOẶC là `booking` với `action=schedule`) → set `_customer_dirty = True`. Tool crash KHÔNG đánh dirty (tránh rebuild vô ích + che lỗi) — [dispatcher.py:77-80](src/noble_agent/agent/tools/dispatcher.py#L77), định nghĩa tại [dispatcher.py:31-32](src/noble_agent/agent/tools/dispatcher.py#L31).
9. `dispatch` bắn `on_tool_done` và trả string; runner bọc thành `ThreadMessage(role="tool", ...)` nối vào `state.history` + `messages` — [dispatcher.py:82-83](src/noble_agent/agent/tools/dispatcher.py#L82), [runner.py:96-103](src/noble_agent/agent/runner.py#L96).
10. Sau khi dispatch hết các tool trong vòng, runner gọi `dispatcher.consume_customer_dirty()`; nếu True thì **rebuild system prompt** (messages[0]) bằng `build_system_prompt(agent, customer, state.summary)` để LLM ở vòng kế thấy hồ sơ khách mới — [runner.py:105-109](src/noble_agent/agent/runner.py#L105), `consume` tại [dispatcher.py:47-49](src/noble_agent/agent/tools/dispatcher.py#L47).

## Kết nối tool → MongoDB

Các tool project (`list_projects`/`get_project_overview`/`match_projects`/`get_project_financial`/`search_units`) là lớp mỏng gọi xuống **data-layer async** `data/structured_data.py`. `booking`/`schedule_viewing`/`update_customer` chạm Mongo theo kiểu best-effort (analytics sink), nguồn sự thật hội thoại là Redis.

- **Client Mongo singleton, fail-soft.** `get_db()` connect + ping lần đầu, cache handle; thiếu `MONGODB_URI` / motor / ping timeout → log một lần và trả `None` suốt vòng đời process → mọi caller phải chịu được `None` — [mongo_client.py:32-72](src/noble_agent/storage/mongo_client.py#L32). Config qua env `MONGODB_URI`/`MONGODB_DATABASE` (default db `noble_agent`) — [mongo_client.py:23-29](src/noble_agent/storage/mongo_client.py#L23).

- **Chỉ 2 collection.** `project_du_an` (overview + resolve mã→`_id`) và `project_can_ho` (inventory căn hộ) — nêu rõ ở docstring [structured_data.py:1-20](src/noble_agent/data/structured_data.py#L1). Không collection `project_*` nào khác được đọc → 4 info_type `payment_plans`/`loan_policies`/`promotions`/`fees` luôn trả `None` (hàm stub) — [structured_data.py:160-177](src/noble_agent/data/structured_data.py#L160).

- **Join ObjectId ↔ str.** `project_du_an._id` là **ObjectId**, nhưng FK `project_can_ho.du_an_id` lưu **dạng string** của nó → phải query bằng `str(_id)`. `_resolve_du_an_id` lấy `_id` rồi `str(doc.get("_id"))` — [structured_data.py:68-80](src/noble_agent/data/structured_data.py#L68); `_fetch_units` dùng chuỗi đó để `find({"du_an_id": du_an_id})` — [structured_data.py:83-93](src/noble_agent/data/structured_data.py#L83).

- **Alias mã app → Mongo.** Mã canonical của app khác Mongo ở vài dự án (NCRS→NCR, SSLC→SLC, ASM→ALLUVIA). `catalog.normalize()` chuẩn hoá trước khi khớp `ma_du_an` bằng regex case-insensitive `^<code>$` — trong `_resolve_du_an_id` [structured_data.py:72-76](src/noble_agent/data/structured_data.py#L72) và `_fetch_project_doc` [structured_data.py:289-295](src/noble_agent/data/structured_data.py#L289). Các field số lưu dạng string ('4888308800', '78.3') → parse qua `_to_float`/`_to_int` — [structured_data.py:40-52](src/noble_agent/data/structured_data.py#L40).

- **Sentinel escalate khi thiếu data.** Data-layer trả `None` khi không có dữ liệu (dự án lạ / hết inventory / rỗng sau filter / Mongo down). Tool layer đổi `None` thành hằng `ESCALATE_SIGNAL = "Thông tin đã được chuyển đến chuyên viên tư vấn"` — [structured_data.py:34](src/noble_agent/data/structured_data.py#L34). Nơi trả sentinel: `list_projects`/`get_project_overview`/`match_projects` [projects_info.py:19-20,27-28,34-35](src/noble_agent/agent/tools/projects_info.py#L19); `get_project_financial`/`search_units` [project_financial.py:32-33,49-50](src/noble_agent/agent/tools/project_financial.py#L32). Luna đọc chuỗi này như tín hiệu để gọi `escalate` (RULES.md quy định).

- **`db_project_registry` warm enum lúc startup.** `warm()` nạp `project_du_an` (projection `ma_du_an/ten_thuong_mai/khu_vuc/loai_hinh_sp`) vào cache in-memory keyed theo `ma_du_an` (case verbatim, khớp `project_id` của Qdrant); fail → cache rỗng, dùng fallback 15 mã — [db_project_registry.py:56-83](src/noble_agent/data/db_project_registry.py#L56). Accessor **sync, no-I/O**: `cached_codes()` [:86](src/noble_agent/data/db_project_registry.py#L86), `code_to_name()` [:93](src/noble_agent/data/db_project_registry.py#L93), `registry_rows()` [:100](src/noble_agent/data/db_project_registry.py#L100) (feed `{{ project_table }}` trong prompt builder). Enum `noble_search.project_filter` và `send_media.project_code` được bơm động từ `cached_codes()` tại lúc build schema, không đụng literal `SCHEMAS` — `_with_project_enum` [schemas.py:383-396](src/noble_agent/agent/tools/schemas.py#L383).

## Cách thêm tool mới

1. **Tạo executor** `agent/tools/<name>.py` — hàm async trả về `str` (JSON). Chữ ký nhận đúng thứ cần từ dispatcher (`state`/`customer`/`rag`/`callbacks`/`session_id`), theo mẫu các tool hiện có.
2. **Khai schema** trong `SCHEMAS` của [schemas.py:27](src/noble_agent/agent/tools/schemas.py#L27); nếu tool có field mã dự án cần enum động thì thêm nhánh trong `_with_project_enum` [schemas.py:383](src/noble_agent/agent/tools/schemas.py#L383). `schemas_for` lọc theo tên + skip unknown — [schemas.py:399](src/noble_agent/agent/tools/schemas.py#L399).
3. **Import + thêm branch dispatch** trong `_exec` [dispatcher.py:85](src/noble_agent/agent/tools/dispatcher.py#L85) (và import ở đầu file [dispatcher.py:17-24](src/noble_agent/agent/tools/dispatcher.py#L17)). Nếu tool **mutate Customer**, thêm tên vào `_DIRTIES_CUSTOMER` [dispatcher.py:31](src/noble_agent/agent/tools/dispatcher.py#L31) hoặc gọi `self.mark_customer_dirty()` [dispatcher.py:44](src/noble_agent/agent/tools/dispatcher.py#L44) từ trong executor, để runner rebuild system prompt.
4. **Thêm tên tool** vào mảng `"tools"` của [config.json:6](src/noble_agent/agent/definitions/config.json#L6) để Luna được offer.
5. **Ghi vào RULES.md** (`agent/definitions/RULES.md`, bảng "Tool catalog") để Luna biết KHI NÀO gọi tool.
