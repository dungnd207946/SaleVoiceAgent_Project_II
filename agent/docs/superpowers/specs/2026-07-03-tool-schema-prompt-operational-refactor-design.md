# Tool schema + prompt refactor theo Operational Protocol

**Ngày:** 2026-07-03
**Branch:** feat/connect-db
**Phạm vi:** `agent/tools/schemas.py`, `agent/tools/booking.py`, `agent/tools/schedule_viewing.py`, `agent/tools/booking_state.py` (xoá), `agent/tools/dispatcher.py`, `agent/definitions/RULES.md`. KHÔNG đụng logic RAG / transport / storage / LLM.

## Vấn đề

Sau khi bỏ mock data và một số thay đổi kiến trúc, tool schema và prompt lệch nhau:

1. **Description lủng củng, mô tả theo lịch sử refactor thay vì hành vi.** VD `booking.description` = "Quản lý lịch tham quan dự án (gộp 6 tool booking cũ)"; docstring `schemas.py` nói "mirror legacy SFT". Model yếu (gemini-flash, qwen3-flash) không cần biết lịch sử — cần biết KHI NÀO gọi và tool LÀM GÌ.
2. **Description nhồi cả rule vận hành**, trùng lặp và có nguy cơ xung đột với RULES.md (nguồn sự thật của operational protocol). VD `booking.description` mô tả cả state-machine.
3. **Booking bắt buộc tên + số điện thoại** (hiện đang mock). Yêu cầu mới: khi khách xin đặt lịch, chỉ cần cung cấp ngày/giờ còn trống và hỏi khách chọn — không cần tên/SĐT.

## Mục tiêu

- Viết lại description của 10 tool được offer theo hướng **operational protocol**: rõ phạm vi qua câu khẳng định + 1 ví dụ câu khách nói cụ thể; đủ rõ cho model yếu, không dài dòng tốn context; không cross-reference tool khác; không lặp rule vận hành (rule thuộc RULES.md).
- Booking bỏ hoàn toàn tên + số điện thoại; rút state-machine 6 action → 4 action.
- Schema không xung đột với system prompt.

## Nguyên tắc viết description (áp dụng cho toàn bộ)

Mỗi description trả lời đúng 2 điều: **KHI NÀO gọi** + **tool LÀM GÌ**, kèm 1 ví dụ câu khách nói. Loại bỏ:

- Lịch sử refactor / ghi chú kỹ thuật nội bộ ("gộp 6 tool cũ", "mirror legacy SFT", "pull từ Customer state").
- Narration state-machine và quy tắc vận hành → thuộc RULES.md, không lặp trong schema.
- Liệt kê cứng danh sách vùng miền trong description (từng gây hallucination "Long Biên, Tây Hồ...").
- Dòng phân biệt kiểu "KHÁC tool X" — làm rối; thay bằng câu mô tả phạm vi rõ ràng.

## Description mới — 10 tool offered

- **update_customer**: "Ghi nhớ thông tin cá nhân của khách vào hồ sơ: tên, giới tính, dự án đang quan tâm, mục đích ở hay đầu tư, ngân sách, khu vực muốn mua, số phòng ngủ. Gọi ngay khi khách vừa cung cấp bất kỳ thông tin nào trong số này. Ví dụ khách nói 'anh tên Hùng, tầm 3 tỷ' thì gọi update_customer(name='Hùng', budget='3 tỷ')."

- **list_projects**: "Liệt kê danh sách các dự án Noble đang mở bán, có thể lọc theo khu vực. Dùng khi khách muốn biết Noble có những dự án nào, hoặc có dự án nào ở một khu vực. Ví dụ 'bên em có dự án nào', 'ở Long Biên có dự án gì'."

- **get_project_overview**: "Lấy thông tin tổng quan của một dự án: vị trí, loại hình, quy mô, các điểm nổi bật chính. Dùng khi khách hỏi giới thiệu chung về một dự án cụ thể. Ví dụ 'dự án Noble Crystal thế nào', 'giới thiệu cho em dự án đó'."

- **noble_search**: "Tra cứu thông tin chi tiết về dự án trong tài liệu: tiện ích, mô tả vị trí, thiết kế, vật liệu, pháp lý, hoặc so sánh giữa các dự án. Dùng cho câu hỏi nội dung cụ thể cần dữ liệu thật. Ví dụ 'dự án đó có bể bơi không', 'pháp lý dự án thế nào'."

- **get_project_financial**: "Lấy thông tin tài chính của một dự án: bảng giá, chính sách thanh toán, chính sách vay ngân hàng, ưu đãi, hoặc các loại phí. Dùng khi khách hỏi về giá hoặc điều khoản tài chính. Ví dụ 'dự án đó giá bao nhiêu', 'trả góp thế nào'."

- **search_units**: "Tìm các căn hộ cụ thể còn trong một dự án theo tiêu chí: loại căn, mức giá tối đa, hướng, tầng, diện tích, mã căn, tình trạng còn hay đã bán. Dùng khi khách hỏi về căn cụ thể. Ví dụ 'còn căn 3 phòng ngủ dưới 5 tỷ không', 'có căn nào hướng Đông Nam'."

- **match_projects**: "Gợi ý những dự án phù hợp với nhu cầu của khách khi khách chưa biết chọn dự án nào, dựa trên ngân sách, khu vực, số phòng ngủ và mục đích. Dùng khi khách muốn được tư vấn nên xem dự án nào. Ví dụ 'tầm 4 tỷ ở Tây Hồ thì nên xem dự án nào'."

- **booking**: "Đặt lịch cho khách tới tham quan dự án. action='check_availability' để xem những ngày và khung giờ còn trống, gọi trước để báo khách chọn; action='schedule' để chốt lịch sau khi khách đã chọn ngày và giờ, đặt confirmed=true; action='list' để xem các lịch đã đặt; action='modify' để đổi ngày hoặc giờ của một lịch đã đặt. Chỉ cần dự án, ngày và giờ; không cần tên hay số điện thoại."

- **escalate**: "Chuyển cuộc gọi sang chuyên viên là người thật. Dùng khi khách đã mua nhà hỏi về hợp đồng, thanh toán, sổ hồng, bảo hành hoặc thủ tục; khi khách hỏi giá nội bộ; khi khách yêu cầu gặp người thật; hoặc khi một tool khác trả về đúng câu 'Thông tin đã được chuyển đến chuyên viên tư vấn'. Đây là cách duy nhất để đưa cuộc gọi ra khỏi luồng tự động."

- **send_via_app**: "Gửi tài liệu cho khách qua ứng dụng NobleX hoặc SMS: hình ảnh, bản đồ, mặt bằng, brochure — những nội dung khó diễn đạt bằng lời nói. Bắt buộc nói một câu filler ('Dạ em gửi qua app cho anh/chị nha, chờ em một chút ạ') cùng lúc khi gọi tool."

3 schema post-sale (`crm_lookup` / `verify_identity` / `support_ticket`) **giữ nguyên** — vẫn defined-but-unoffered, không đụng.

## Booking — rút 6 action → 4 action, bỏ tên + SĐT

### Xoá
- 2 action `get_state`, `update_info` khỏi enum + router (`booking.py`).
- File `agent/tools/booking_state.py` (chỉ tồn tại để gom dần tên/SĐT — không còn lý do).
- Trong `schema.booking`: bỏ param `preferred_slot` (chỉ dùng cho `update_info` cũ). Chuẩn hoá về `preferred_time` cho cả check/schedule.

### Giữ 4 action
| action | vai trò | tham số dùng |
|---|---|---|
| `check_availability` | trả ngày + khung giờ còn trống | `project_code` (optional), `preferred_date` (optional) |
| `schedule` | chốt lịch | `preferred_date`, `preferred_time`, `project_code` (optional), `confirmed`, `notes` |
| `list` | xem lịch đã đặt trong session | — |
| `modify` | đổi ngày/giờ lịch đã đặt | `booking_id`, `new_preferred_date`, `new_preferred_time` |

### `schedule_viewing.py` sửa
- `_normalize_and_validate`: **bỏ check name + phone** (bỏ `_PHONE_REGEX`, bỏ điều kiện `len(name) < 2`). Chỉ validate **project hợp lệ (`catalog.normalize`)** + **ngày đúng định dạng & không quá khứ**. Đổi chữ ký thành `(project, preferred_date) -> (norm_project, errors)`.
- `schedule_viewing()`: bỏ đọc/ghi `name` + `phone`. Booking record bỏ 2 field `customer_name`, `phone`. Không còn `customer.full_name = ...` / `customer.phone = ...`. **Giữ** `customer.project_interest = norm_project` (giữ dirty-signal cho runner).
- Dedup key giữ nguyên (project + date + time). Mongo `bookings_flat` ghi record đã bỏ name/phone.
- `list_bookings` / `modify_booking`: giữ nguyên logic; record chỉ khác ở việc không có name/phone.

### `booking.py` router
- Bỏ 2 nhánh `get_state` / `update_info` + import `booking_state`.
- `schedule` forward: `preferred_date`, `preferred_time`, `notes`, `confirmed`, `project` (từ `project_code`). Không forward name/phone.
- `schedule_viewing` tự pull project từ `customer.project_interest` nếu `project_code` rỗng; nếu vẫn rỗng → trả lỗi "cần dự án" để Luna hỏi khách.

### `dispatcher.py`
- `_BOOKING_DIRTYING_ACTIONS = {"schedule"}` **giữ nguyên** (schedule vẫn set `project_interest`).

## RULES.md

- **Rule 6** viết lại theo 4-action flow, bỏ mọi câu về thu thập tên/SĐT:
  > 6. Đặt lịch tham quan: gọi `booking(action="check_availability")` để lấy ngày/giờ còn trống rồi báo khách chọn; khi khách đã chọn ngày và giờ, gọi `booking(action="schedule", confirmed=true)` để chốt. Đổi/xem lịch dùng `modify`/`list`. Chỉ cần dự án + ngày + giờ, không hỏi tên hay số điện thoại. Dự án lấy từ hồ sơ khách; nếu chưa rõ thì hỏi khách muốn tham quan dự án nào.
- **Tool catalog**: dòng booking đổi mô tả cho khớp ("Đặt/đổi/xem lịch tham quan → booking(action=...)").
- Các rule/style/guardrail khác giữ nguyên.

## Không đụng

- `config.json` tools list (vẫn đúng 10 tool).
- Logic `escalate` / `send_via_app` (chỉ đổi description).
- `availability.py` (stub trả ngày/giờ — đã đúng nhu cầu).
- 3 schema post-sale + branch dispatcher của chúng + `support_ops`.
- Model / temperature / RAG backend / transport / storage schema.

## Tác động test

- Test booking tham chiếu `get_state` / `update_info` / name-phone-required → cập nhật theo 4-action flow mới.
- Test đặt lịch thành công không cần name/phone (case mới).
- `tests/unit/unified/test_agent_def.py` (10 tool) vẫn pass — số tool không đổi.
- Test nào assert nguyên văn description cũ → cập nhật sang v3.
- Chạy `make test-unit` + `make lint`.

## Rủi ro

- Booking record cũ trong Mongo/Redis vẫn còn field name/phone — code đọc phải chịu được record thiếu 2 field (dùng `.get`). `list_bookings` trả nguyên record nên record cũ vẫn hiển thị được.
- Không có migration cần thiết (scratchpad theo session, TTL).
