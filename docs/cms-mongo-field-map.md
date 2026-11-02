# CMS ↔ MongoDB Field Map (cầu nối giao diện CMS ↔ dữ liệu agent ghi)

**Mục đích.** Khi phát triển tính năng cho agent "cập nhật thông tin lên CMS", bạn chỉ cần
nhìn **nhãn trên giao diện CMS** (`agent-cms.noble.vn`) rồi tra bảng dưới để biết:
(1) field đó nằm ở **collection.field** nào trong MongoDB, (2) **kiểu dữ liệu** CMS bắt buộc,
(3) **code phía agent** nào ghi field đó — **không cần vào Mongo dò tay**.

> Cập nhật spec này mỗi khi thêm/sửa field mà CMS đọc, hoặc khi CMS đổi schema.

---

## 0. Kiến trúc tích hợp (đọc trước)

- **Một MongoDB dùng chung** (`noble_agent` DB trên `10.50.12.70` / `thebc-server.local`).
  Agent hotline là **NGƯỜI GHI DUY NHẤT**; CMS **chỉ đọc** (trừ vài field CMS tự "flip" —
  xem §6). CMS backend là FastAPI query Mongo trực tiếp qua Pydantic models
  (`santa-agent-cms/backend/app/schemas/hotline/*.py`).
- **CMS validate bằng Pydantic** → **sai KIỂU dữ liệu = HTTP 500** (trang detail kẹt
  "Đang tải…"). **Thiếu field = OK** (models có `extra="ignore"` + default). ⇒ Ưu tiên
  ghi **đúng tên + đúng kiểu**; field dư bị bỏ qua vô hại.
- **Không có collection nào tên `customers` được CMS đọc.** Màn "Khách hàng" được
  **suy ra (derived)** bằng cách gộp `bookings_flat` + `call_summaries` theo `phone`
  (xem §4). ⇒ Muốn 1 khách xuất hiện trong CMS, phải ghi **booking** hoặc **summary**
  có `phone` (+ `customer_name`). Ghi vào collection `customers` (qua
  `save_customer_persistent`) **KHÔNG** hiển thị trên CMS.

### Collection ↔ ai ghi (phía agent)

| Mongo collection | CMS đọc? | Code agent ghi |
|---|---|---|
| `call_summaries` | ✅ (Cuộc gọi) | `agent/summary/generator.py::generate_call_summary` (shape) → `storage/call_summaries.py::save_call_summary`; escalate → `record_handoff` |
| `agent_messages` | ✅ (transcript trong Cuộc gọi) | `storage/agent_messages.py::insert_messages` (gọi từ `agent/orchestrator.py` mỗi lượt) |
| `bookings_flat` | ✅ (Lịch hẹn + derive Khách hàng) | `agent/tools/schedule_viewing.py` → `storage/bookings_flat.py::upsert_booking` |
| `outbound_briefs` | ✅ (hàng đợi gọi ra) | `storage/outbound_briefs.py` (outbound worker) |
| `outbound_calls` | ✅ (lịch sử gọi ra) | `storage/outbound_calls.py` |
| `customers` | ❌ **không** | `storage/session_store.py::save_customer_persistent` — chỉ dùng nội bộ (không lên CMS) |
| `call_events` | ❌ (không có endpoint hotline đọc) | `storage/call_events.py::log_event` — audit nội bộ |

### Endpoint CMS (base `…/api/v1/hotline`)

| Màn hình | Method + path | Response model | Nguồn Mongo |
|---|---|---|---|
| Cuộc gọi (list) | `GET /summaries?phone=&project_code=&…` | `SummaryListOut` | `call_summaries` |
| Cuộc gọi (detail) | `GET /summaries/{id}` | `SummaryDetail` | `call_summaries` + `agent_messages` |
| Cuộc gọi (sửa) | `PATCH /summaries/{id}` | — | CMS ghi (summary/project_code) |
| Đánh dấu đã xử lý | `POST /summaries/{id}/mark_followed_up` | — | CMS ghi (follow-up) |
| Lịch hẹn (list) | `GET /bookings?project=&phone=&status=&contacted=` | `BookingListOut` | `bookings_flat` |
| Lịch hẹn (detail) | `GET /bookings/{appointment_id}` | `BookingOut` | `bookings_flat` |
| Đánh dấu đã liên hệ | `POST /bookings/{appointment_id}/mark_contacted` | — | CMS ghi (contacted) |
| Khách hàng (search) | `GET /customers/search?q=` | `CustomerSearchOut` | derive: `bookings_flat` + `call_summaries` |
| Khách hàng (360) | `GET /customers?phone=` | `Customer360Out` | derive |
| Khách hàng (lịch sử) | `GET /customers/{phone}/history` | dict | derive |
| Thống kê | `GET /stats/today`, `/stats/range` | `StatsTodayOut/RangeOut` | aggregate `bookings_flat`+`call_summaries` |
| Gọi ra (queue) | `GET /outbound/queue` | `QueueListOut` | `outbound_briefs` |
| Gọi ra (lịch sử) | `GET /outbound/calls` | `list[OutboundCallOut]` | `outbound_calls` |

---

## 1. Màn "Cuộc gọi" — LIST (`call_summaries` → `SummaryOut`)

Cột bảng: `# | KHÁCH HÀNG | SỐ ĐIỆN THOẠI | DỰ ÁN | TÓM TẮT | THỜI GIAN`.

| Nhãn CMS | API field | Mongo `call_summaries` field | Kiểu (bắt buộc) | Agent ghi |
|---|---|---|---|---|
| KHÁCH HÀNG | `customer_name` | `customer_name` (**top-level**) | `str\|None` | generator `_base_doc` ← `customer.full_name or name`; "" → CMS hiện "(chưa rõ tên)" |
| SỐ ĐIỆN THOẠI | `phone` | `phone` | `str` (**bắt buộc**) | `save_call_summary(phone,…)` |
| DỰ ÁN | `project_code` | `project_code` (**top-level**) | `str\|None` | generator ← `customer.project_interest` (mã canonical: NCLB…) |
| TÓM TẮT | `summary` | `summary` | `str` | generator (LLM narrative) |
| THỜI GIAN | `ended_at` | `ended_at` | `datetime\|None` | generator/close-path |
| (badge Chuyển sales) | `transferred_to_sales` | `transferred_to_sales` | `bool` | mặc định `False`; `record_handoff` set `True` |
| (đã xử lý) | `sales_followed_up` | `sales_followed_up` | `bool` | mặc định `False`; **CMS** flip (mark_followed_up) |
| — | `priority` | `priority` | `str` | mặc định `"normal"`; `record_handoff` set (urgent…) |
| — | `id` | `_id` | `str` | Mongo (service stringify) |
| — | `session_id` | `session_id` | `str\|None` | khoá liên kết transcript |
| — | `duration_seconds` | `duration_seconds` | `int\|None` | generator |
| — | `started_at`,`created_at` | idem | `datetime\|None` | generator |

## 2. Màn "Cuộc gọi" — DETAIL drawer (`SummaryDetail` = `SummaryOut` + dưới đây)

Drawer "Chi tiết cuộc gọi": khối **"Thông tin chính"** (key_facts), **"Hành động cần làm"**
(open_actions), **"Nội dung cuộc gọi"** (messages/transcript).

| Nhãn CMS | API field | Mongo field | Kiểu (bắt buộc) | Agent ghi / ⚠️ bẫy |
|---|---|---|---|---|
| Thông tin chính | `key_facts` | `key_facts` | `dict` | generator: `{budget, bedrooms, purpose, loan_needed}` — **`bedrooms`** (KHÔNG phải `bedroom_count`); `customer_name`/`project` **KHÔNG** nằm trong đây |
| Hành động cần làm | `open_actions` | `open_actions` | **`list[dict]`** ⚠️ | generator ghi `[{"action": "<text>"}]` — **PHẢI là dict**, list[str] → **500** |
| Nội dung cuộc gọi | `messages` | (join `agent_messages` theo `session_id`) | `list[CallTurn]` | xem §3 — role **phải** `agent`/`caller` |
| — | `agent_path` | `agent_path` | `list[str]` | mặc định `[]` |
| — | `reason` | `reason` | `str\|None` | `record_handoff` |
| Ghi chú xử lý | `follow_up_notes` | `follow_up_notes` | `str\|None` | **CMS** ghi (mark_followed_up) |
| — | `followed_up_by`,`followed_up_at` | idem | `str\|None`,`datetime\|None` | **CMS** ghi |
| — | `conversation_id` | (không dùng) | `str\|None` | bỏ trống |

## 3. Transcript hội thoại (`agent_messages` → `CallTurn`) — ⚠️ hay lỗi nhất

Join: `call_summaries.session_id` → `agent_messages.session_id` (sort `created_at` asc).
Drawer render "Khách:" cho phía caller.

| Nhãn CMS | Mongo `agent_messages` field | Kiểu (bắt buộc) | Agent ghi |
|---|---|---|---|
| (một lượt) `role` | `role` | **`Literal["agent","caller"]`** ⚠️ | `insert_messages` `_ROLE_MAP`: `assistant→"agent"`, `user→"caller"` — ghi `"user"` → **500 detail** |
| nội dung | `content` | `str` | verbatim (bỏ system/tool + rỗng) |
| — | `created_at` | `datetime\|None` | thời điểm ghi |
| liên kết | `session_id` | (khoá) | = `call_summaries.session_id` |

## 4. Màn "Khách hàng" — DERIVED (không có collection `customers`)

CMS suy ra từ `bookings_flat` (chính, có `customer_name`) + `call_summaries` theo `phone`.
⇒ Muốn khách hiện lên: **ghi booking hoặc summary có `phone`** (+ `customer_name`).

| Nhãn CMS | API field (`CustomerSearchHit`/`Customer360Out`) | Suy ra từ | Agent ghi (gián tiếp) |
|---|---|---|---|
| SĐT | `phone` | `bookings_flat.phone` / `call_summaries.phone` | booking/summary |
| Tên | `full_name` | `bookings_flat.customer_name` (last) | `schedule_viewing` (từ Customer) |
| Lần cuối | `last_seen_at` | `max(bookings_flat.updated_at)` / `call_summaries.ended_at` | tự động |
| Số cuộc gọi | `total_summaries` | count `call_summaries` theo phone | tự động |
| Số lịch hẹn | `total_bookings` | count `bookings_flat` theo phone | tự động |
| Dự án quan tâm | `project_interest` | (360) | derive |

## 5. Màn "Lịch hẹn" (`bookings_flat` → `BookingOut`)

| Nhãn CMS | API field | Mongo `bookings_flat` field | Kiểu | Agent ghi / bẫy |
|---|---|---|---|---|
| Khách | `customer_name` | `customer_name` | `str` ("") | `upsert_booking` ← Customer (mặc định "No Name") |
| SĐT | `phone` | `phone` | `str` ("") | ← phone phiên (không bắt buộc) |
| Dự án | `project` | `project` | `str` | mã dự án; repo `.upper()` khi filter |
| Ngày/Giờ | `preferred_date`,`preferred_time` | idem | `str` | tool booking |
| (sort ngày) | `preferred_date_dt` | `preferred_date_dt` | `datetime\|None` | **`upsert_booking` tự tính** — nếu ghi thẳng bỏ field này thì mất sort |
| Trạng thái | `status` | `status` | `str` | `"confirmed"`… |
| Ghi chú | `notes` | `notes` | `str` | tool booking |
| Đánh dấu đã liên hệ | `contacted_by_sales` | idem | `bool` | mặc định `False`; **CMS** flip |
| — | `contacted_at/by`,`contact_outcome`,`follow_up_notes` | idem | (nullable) | **CMS** ghi (mark_contacted) |
| khoá | `id`/`appointment_id` | `_id`/`appointment_id` | `str` | `appointment_id` = khoá gọi detail |

## 6. Field do **CMS** sở hữu (agent KHÔNG được ghi đè)

Agent chỉ **default khi insert** các field này (dùng `$setOnInsert`, đã làm trong
`save_call_summary`) để thao tác của sale/CSKH trên CMS không bị summary cuối phiên xoá:

- `call_summaries`: `sales_followed_up`, `followed_up_by`, `followed_up_at`, `follow_up_notes`
  (CMS `mark_followed_up`); và `transferred_to_sales`/`reason`/`priority`/`project_code`
  do `record_handoff` (escalate) sở hữu — summary chỉ default-on-insert.
- `bookings_flat`: `contacted_by_sales`, `contacted_at`, `contacted_by`, `contact_outcome`,
  `follow_up_notes` (CMS `mark_contacted`).
- `outbound_briefs`: `sales_instructions`, `called*` (CMS/worker).

Cũng có field CMS **ghi đè trực tiếp** qua PATCH (sale sửa tay): `call_summaries.summary`,
`call_summaries.project_code` (`SummaryUpdateIn`).

## 7. Quy trình khi làm tính năng "agent cập nhật CMS"

1. **Nhìn nhãn trên CMS** cần cập nhật → tra §1–§6 ra `collection.field` + **kiểu** + **code agent**.
2. **Field đã có trong schema CMS?**
   - Có → chỉ cần agent **ghi đúng tên + đúng kiểu** vào collection tương ứng (sửa
     `generator._base_doc` / `upsert_booking` / …). Field không có trong schema → CMS bỏ qua.
   - Chưa có trong schema CMS → **không thể hiển thị** (CMS cố định, không sửa được từ đây).
3. **Ưu tiên kiểu dữ liệu** — sai kiểu = 500. Nhớ 3 bẫy: `agent_messages.role ∈ {agent,caller}`;
   `open_actions` là `list[dict]`; `customer_name`/`project_code` **top-level** ở `call_summaries`.
4. **Field CMS sở hữu (§6)** → chỉ `$setOnInsert`, không `$set` đè.
5. **Test nhanh không cần Mongo**: gọi hàm sinh doc (vd `generate_call_summary`) và so field/kiểu
   với bảng trên. Muốn kiểm live: `docker exec santa-infra-mongodb-1 mongosh` (auth) trên
   `thebc-server.local`.
6. **Restart agent server** (`--no-reload`) để nạp thay đổi cho phiên mới; dữ liệu cũ cần
   **migration** riêng (vd đổi role `user→caller`).

## 8. Nguồn tham chiếu (đọc-only, KHÔNG sửa CMS)

- CMS schemas: `santa-agent-cms/backend/app/schemas/hotline/{summary,booking,customer,outbound,stats}.py`
- CMS services/repos: `…/services/hotline/*.py`, `…/repositories/hotline/*.py`
- CMS frontend: `…/frontend/src/components/sales/SummaryDrawer.tsx`, `…/api/queries/sales/*`
- Agent writers: `src/noble_agent/agent/summary/generator.py`, `storage/{call_summaries,agent_messages,bookings_flat,session_store,call_events,outbound_briefs,outbound_calls}.py`, `agent/tools/schedule_viewing.py`, `agent/orchestrator.py`
