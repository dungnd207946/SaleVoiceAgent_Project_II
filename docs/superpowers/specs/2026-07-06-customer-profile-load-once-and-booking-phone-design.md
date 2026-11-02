# Customer profile load-once + booking phone flow — Design

**Date:** 2026-07-06
**Branch:** `feat/refactor2`
**Status:** Approved (design)

## Problem

Ngày nay hồ sơ khách được **giả định agent thu thập qua cuộc gọi** và block
`CUSTOMER_PROFILE.md` được **render động** — `runner.py` rebuild `messages[0]`
mỗi khi `update_customer` / `booking(action="schedule")` set cờ
`consume_customer_dirty()`. Nghiệp vụ mới đổi:

- Khi khách gọi đến, hệ thống đã biết **số điện thoại** (caller-ID với
  telephony; app-client cung cấp số). Cần **tra hồ sơ theo SĐT một lần** lúc bắt
  đầu cuộc gọi từ Mongo `customers` + `bookings_flat`. Không tìm thấy → chỉ có
  phone.
- Không còn phụ thuộc "hệ sinh thái Noble Profile app". Bỏ hẳn.
- Block hồ sơ trong prompt phải **đóng băng snapshot đầu cuộc**, không rebuild
  động theo `update_customer`.
- Agent **chủ động hỏi tên** khi khách đặt lịch / cần tư vấn. Khi đặt lịch phải
  **hỏi có dùng số đang gọi không**; đồng ý → dùng luôn; không → hỏi số khác để
  booking. Số booking khác **chỉ ghi trên booking row**, không đổi danh tính.
- `update_customer` tiếp tục persist khách lên Mongo (feed lần gọi sau + CMS).

## Kiến trúc tích hợp CMS (không đổi — xác nhận từ `docs/cms-mongo-field-map.md`)

Agent là **người ghi Mongo duy nhất**; CMS **chỉ đọc** Mongo (FastAPI query
trực tiếp). **Không có HTTP POST tới `agent-cms.noble.vn`.** "Update lên CMS
/customers, /summaries, /bookings" nghĩa là ghi đúng field vào 3 collection:

- **`call_summaries`** ← `agent/summary/generator.py` + `storage/call_summaries.py`.
- **`bookings_flat`** ← `agent/tools/schedule_viewing.py` → `storage/bookings_flat.py::upsert_booking`.
- **`customers`** ← `storage/session_store.py::save_customer_persistent`
  (dùng nội bộ + feed lookup lần sau; CMS **không** đọc trực tiếp — màn "Khách
  hàng" là *derived* từ `bookings_flat`+`call_summaries` theo `phone`). ⇒ Tên
  khách agent thu thập tự lên CMS qua summary/booking `customer_name`.

Lớp persist (`storage/persist.py::fire_and_forget`, `storage/agent_messages.py`,
`save_call_summary`, `upsert_booking`, `save_customer_persistent`) đã có sẵn trên
branch. Thiết kế này **chồng lên**, không dựng lại.

## Thay đổi

### 1. Bootstrap hồ sơ 1 lần theo SĐT (thay render động)

**Vị trí:** guard chạy **đúng một lần ở turn đầu** trong
`TurnRunner.handle_turn` (`agent/orchestrator.py`), ngay sau `repo.load(sid)` và
trước `_run_live`. Gác bằng cờ `state.scratchpad["_profile_loaded"]`. Đây là
điểm hợp nhất mọi transport — tới turn đầu, phone đã chắc chắn có (telephony
seed caller-ID vào Redis trước `agent.start`; browser/text có simulate hoặc
`set_customer`). Chạy trước `_run_live` nên response đầu (kể cả câu chào) thấy
hồ sơ đã bootstrap.

**Lookup + merge** (`customer.phone` rỗng → bỏ qua toàn bộ, chỉ giữ phone rỗng):
1. `session_store.load_customer_by_phone(phone)` → Mongo `customers` (nguồn
   chính, giàu field).
2. Helper MỚI `session_store.load_latest_booking_hint_by_phone(phone)` → đọc
   `bookings_flat` doc mới nhất theo phone (sort `updated_at`/`created_at` desc),
   trả `{customer_name, project}` làm **fallback** cho `name`/`project_interest`
   khi `customers` thiếu.
3. Merge vào object `Customer`: **DB thắng** — field DB có giá trị thì ghi vào
   snapshot (override giá trị đẩy sẵn qua `set_customer` nếu có); field DB rỗng
   thì giữ nguyên. `project_interest` normalize qua `catalog.normalize()`.
   Danh sách field merge = whitelist trong `Customer` model (name, full_name,
   gender, project_interest, purpose, budget, preferred_area, bedroom_count,
   is_noble_customer, noble_info). Không đụng các field Noble-ecosystem
   (`email`/`noble_user_id`/`source`/`enriched_at`) — chúng bị loại khỏi luồng.

**Đóng băng block:** sau merge, render block hồ sơ **một lần** (dùng
`agent.sections["customer_format"]` + jinja như hiện tại) và lưu **chuỗi** vào
`state.scratchpad["customer_block"]`. Set `_profile_loaded=true`. Object
`Customer` (đã merge) vẫn persist qua `repo.save_all` cuối turn như thường.

**Dùng block đóng băng:** `build_system_prompt` (`agent/prompts/builder.py`)
đổi chữ ký để nhận **block đã render sẵn** thay vì tự render từ `Customer`:

```
build_system_prompt(agent, customer_block: str, prior_summary) -> str
```

`runner.run_turn` đọc `state.scratchpad["customer_block"]` và truyền vào. Nếu
chuỗi rỗng (guard chưa chạy — không xảy ra ở luồng bình thường vì bootstrap
đứng trước) → fallback render live từ `customer` để an toàn.

**Bỏ render động:** xoá nhánh `consume_customer_dirty()` rebuild `messages[0]`
trong `runner.py` (line ~105–108). `update_customer` / `booking(schedule)` vẫn
mutate `Customer` (summary/booking/persist đọc giá trị mới) nhưng **không** đổi
block hiển thị. Cờ dirty trong `dispatcher.py` trở nên vô dụng cho mục đích
prompt; giữ tối giản (không xoá API để tránh vỡ test khác) hoặc dọn nhẹ nếu
không consumer nào còn dùng — quyết trong plan.

### 2. Luồng tên + SĐT khi đặt lịch

**Tool schema (`agent/tools/schemas.py`):** thêm param `phone` (string, optional)
vào tool `booking` cho action `schedule`:

```
"phone": {"type": "string", "description":
  "SĐT liên hệ cho lịch hẹn. Bỏ trống nếu khách dùng số đang gọi (mặc định)."}
```

Sửa description tool `booking`: bỏ câu "không cần tên hay số điện thoại"; nêu rõ
`schedule` cần **tên khách trong hồ sơ** + **xác nhận số điện thoại**.

**Executor (`agent/tools/schedule_viewing.py`):** `schedule_viewing` dùng
`booking_phone = (args.get("phone") or customer.phone or "").strip()`, validate
sơ bộ (10 số, đầu 03/05/07/08/09 — tái dùng regex như `update_customer`; sai →
báo lỗi để agent hỏi lại). Ghi `booking["phone"] = booking_phone`. **Không**
`setattr(customer, "phone", ...)` — `customer.phone` giữ nguyên caller-ID. Tên
lấy từ `customer.full_name or customer.name` (đã do `update_customer` set).

**Prompt (`agent/definitions/RULES.md` rule 6 + Tool catalog):** viết lại luồng
đặt lịch:
- Chưa có tên trong hồ sơ → hỏi tên, `update_customer(name=...)` trước khi chốt.
- Trước khi chốt, hỏi: *"Anh/chị dùng số [số đang gọi] này để đặt lịch không ạ?"*
  (đọc số từ block hồ sơ). Đồng ý → `booking(action="schedule", confirmed=true)`
  **không truyền `phone`** (mặc định = số đang gọi). Khách cho số khác →
  `booking(action="schedule", confirmed=true, phone="<số mới>")`.
- Đảo ngược dòng hiện tại "KHÔNG hỏi SĐT — hệ thống đã biết số gọi".

`update_customer` tiếp tục là chỗ persist tên → Mongo `customers`
(fire-and-forget khi `customer.phone` có; phone giờ luôn có nên luôn ghi).
Không đổi logic tool này ngoài việc RULES nhấn mạnh gọi khi thu được tên.

### 3. Dọn Noble Profile ecosystem (đã duyệt)

`telephony/session.py`:
- **Xoá** block seed lookup `load_customer_by_phone` + copy whitelist
  (dòng ~174–210) — việc tra DB dồn về bootstrap chung ở orchestrator.
- **Giữ** seed caller-ID: chỉ `save_customer(session_id, {"phone": caller_number})`
  để phone có mặt trong Redis trước turn đầu (bootstrap orchestrator sẽ tra DB).
- **Xoá** block Noble Profile API enrichment (dòng ~231+, gated
  `settings.noble_profile_enabled`).
- **Giữ nguyên** logic outbound callback intent (không liên quan).

Các setting/service Noble Profile (`noble_profile_service`, `noble_profile_*`
config) trở thành dead — dọn tuỳ phạm vi trong plan (ưu tiên tối giản, không
mở rộng blast radius ngoài telephony trừ khi cần).

## Data flow (một cuộc gọi)

```
Kết nối → phone biết (caller-ID / set_customer / simulate)
  ↓ turn đầu: handle_turn → repo.load
  ↓ [GUARD !_profile_loaded]
      load_customer_by_phone(phone) + load_latest_booking_hint_by_phone(phone)
      → merge vào Customer (DB thắng) → render block 1 lần
      → scratchpad["customer_block"], _profile_loaded=true
  ↓ mọi turn: build_system_prompt(agent, scratchpad["customer_block"], summary)
      (block ĐÓNG BĂNG — không rebuild động)
  ↓ khách nói tên → update_customer(name) → mutate Customer + fire-and-forget
      save_customer_persistent(phone, ...) → Mongo customers
  ↓ đặt lịch: hỏi tên (nếu thiếu) + xác nhận số
      booking(schedule, confirmed, [phone]) → upsert_booking → bookings_flat
  ↓ kết thúc: generate_call_summary (customer_name/phone/project) → call_summaries
      → CMS đọc: /summaries, /bookings, /customers(derived)
```

## File đụng tới

| File | Thay đổi |
|---|---|
| `agent/orchestrator.py` | Guard bootstrap turn-đầu (lookup + merge + freeze block) |
| `storage/session_store.py` | Helper mới `load_latest_booking_hint_by_phone` |
| `agent/prompts/builder.py` | `build_system_prompt` nhận `customer_block` render-sẵn |
| `agent/runner.py` | Truyền block đóng băng; **xoá** rebuild `consume_customer_dirty` |
| `agent/tools/schemas.py` | Thêm param `phone` + sửa description `booking` |
| `agent/tools/schedule_viewing.py` | Đọc `phone` param cho booking row; không đè `customer.phone` |
| `agent/definitions/RULES.md` | Rule 6 + Tool catalog: hỏi tên + xác nhận SĐT khi đặt lịch |
| `agent/definitions/CUSTOMER_PROFILE.md` | (tuỳ) chỉnh câu hướng dẫn cho khớp luồng |
| `telephony/session.py` | Xoá lookup trùng + Noble enrichment; chỉ seed caller-ID |
| `dispatcher.py` | (tuỳ) dọn cờ dirty nếu không còn consumer |

## Testing

- **Bootstrap:** unit test orchestrator guard — (a) phone có doc `customers` →
  merge đúng, block chứa tên; (b) chỉ có `bookings_flat` → fallback name/project;
  (c) không có gì → block chỉ phone; (d) chạy đúng 1 lần (`_profile_loaded`).
- **Freeze:** sau `update_customer(name)` giữa cuộc, block turn sau **không đổi**;
  nhưng `Customer` (và summary/booking) thấy tên mới.
- **Booking phone:** `schedule` không có `phone` → row dùng `customer.phone`;
  có `phone` khác → row dùng số mới, `customer.phone` **không đổi**; số sai
  định dạng → lỗi.
- **Prompt:** `test_prompt_builder` cập nhật chữ ký `build_system_prompt`.
- **Telephony:** không còn gọi `load_customer_by_phone`/noble_profile trong
  `session.run`; vẫn seed phone.
- Chạy `make test-unit` + `SMOKE.md` (chạm turn loop + prompt).

## Rủi ro / lưu ý

- **Ordering phone:** bootstrap phụ thuộc phone có mặt ở turn đầu. Với
  browser/app-client, nếu `set_customer` tới **sau** turn đầu, bootstrap chạy
  với phone rỗng/simulate → không lookup. Chấp nhận (trọng tâm nghiệp vụ là
  telephony có caller-ID chắc chắn); ghi log khi phone rỗng.
- **Block đóng băng vs Customer sống lệch nhau:** cố ý. Agent thấy thông tin
  mới qua lịch sử hội thoại, không cần block đổi.
- **`bookings_flat.phone` ≠ `customers.phone`:** một khách có thể xuất hiện
  dưới 2 số trên màn "Khách hàng" (derived theo phone) nếu đặt lịch bằng số
  khác. Đúng theo yêu cầu (số booking chỉ là số liên hệ cho lịch hẹn).
