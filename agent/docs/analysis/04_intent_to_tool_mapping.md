# Luna Chat DeepAgent — Intent → Tool Mapping (Toàn Bộ Luồng)

## Bảng Tổng Hợp Nhanh

| Intent | Agent xử lý | Tools gọi | Thứ tự |
|--------|------------|-----------|--------|
| Chào hỏi / off-topic / cảm ơn | Luna | None | — |
| Hỏi dự án Noble (pre-sale) | Luna → `set_project` → Consultant | `set_project` | Luna trước |
| Tổng quan dự án | Consultant (info) | `search_documents` + `get_project_info` | Parallel |
| Vị trí & kết nối | Consultant (info) | `search_documents` + `get_project_info` | Parallel |
| Tiện ích nội/ngoại khu | Consultant (info) | `search_documents` | Single |
| Pháp lý dự án | Consultant (info) | `get_project_info` + `search_documents` ×3 | Parallel |
| Tiến độ xây dựng | Consultant (info) | `search_documents` ×2 | Parallel |
| Chủ đầu tư | Consultant (info) | `search_documents` ×2 | Parallel |
| So sánh dự án | Consultant (info) | `get_project_info` + `search_documents` per project | Mixed |
| Loại căn / sản phẩm | Consultant (info) | `search_units` + `search_documents` | Parallel |
| Bảng giá | Consultant (pricing) | `get_project_pricing` | Single |
| Chính sách thanh toán | Consultant (pricing) | `get_payment_plans` | Single |
| Ưu đãi / chiết khấu | Consultant (pricing) | `get_promotions` | Single |
| Vay ngân hàng | Consultant (pricing) | `get_loan_policies` | Single |
| Tiềm năng đầu tư | Consultant (pricing) | `get_project_pricing` + `search_documents` | Parallel |
| Tổng chi phí (VAT, bảo trì) | Consultant (pricing) | `get_project_pricing` + `get_project_fees` | Parallel |
| So sánh giá dự án | Consultant (pricing) | `get_project_pricing` ×N | Parallel |
| Căn cụ thể (tầng, mã căn) | Consultant (pricing/info) | `search_units` | Single |
| Gợi ý dự án theo nhu cầu | Consultant (advisor) | `match_projects` + `get_project_pricing` | Sequential |
| Giới thiệu khu vực | Consultant (advisor) | `get_region_overview` | Single |
| Đặt lịch tham quan | Consultant (booking) | `get_booking_state` + `get_available_dates` + `update_booking_info` | Parallel (first turn) |
| Xem khung giờ | Consultant (booking) | `get_available_slots` | Single |
| Xác nhận & lưu booking | Consultant (booking) | `save_booking` | Single (sau confirm) |
| Gặp người / không muốn bot | Support (escalation) | `get_transfer_state` + `get_transfer_message` | Parallel |
| Gọi lại / callback | Support (escalation) | `get_transfer_state` + `get_transfer_message` | Parallel |
| Bảng hàng real-time | Support (escalation) | `generate_summary` + `get_transfer_message` | Parallel |
| Tính giá chi tiết / cam kết giá | Support (escalation) | `generate_summary` + `get_transfer_message` | Parallel |
| KH khiếu nại bot | Support (escalation) | Xác nhận trước → Branch 2 | Sequential |
| KH đã mua — hợp đồng | Support (CRM) | `lookup` → `verify` → `get_contract_info` + `get_payment_schedule` | Sequential |
| KH đã mua — thanh toán | Support (CRM) | `lookup` → `verify` → `get_payment_schedule` | Sequential |
| Bàn giao / nhận nhà | Support (CRM) | `lookup` → `get_contract_info` | Sequential |
| Khiếu nại / phàn nàn | Support (CRM) | `lookup` → `get_ticket_history` → `create_ticket` | Sequential |
| Bảo trì / sửa chữa | Support (CRM) | `lookup` → `get_contract_info` → `create_ticket(MAINTENANCE)` | Sequential |
| Sổ hồng / sang tên | Support (CRM) | `lookup` → `get_certificate_status` | Sequential |
| Thủ tục sau mua | Support (CRM) | `lookup` → `get_certificate_status` + `search_documents` | Parallel |
| Sự cố khẩn cấp | Support (CRM) | `lookup` → `create_ticket(urgent)` | Sequential |
| Email escalation | Support (escalation) | `get_department_contact` → `generate_escalation_email` | Sequential |

---

## Luồng Chi Tiết Từng Intent

### LUNA ROUTING FLOWS

#### Flow 1: Chào hỏi lần đầu (chưa biết tên)

```
KH: "Xin chào" / "Hello" / (bắt đầu chat)
  ↓
Luna phân tích → intent: GREETING (no name)
  ↓
Luna trả lời trực tiếp (KHÔNG route):
  "Kính chào Anh/Chị, cảm ơn Anh/Chị đã quan tâm đến sản phẩm Bất động
   sản hàng hiệu của NobleX ạ. Em là Luna — Chuyên viên tư vấn, có thể
   giúp gì cho Anh/Chị ạ? Anh/Chị vui lòng cho em xin tên để tiện xưng hô ạ?"
```

#### Flow 2: Hỏi về dự án Noble (biết dự án)

```
KH: "Cho tôi hỏi về Noble Crystal Tây Hồ?"
  ↓
Luna phân tích → intent: PRE_SALE, project: NCTH
  ↓
Luna: 1 câu acknowledge ngắn + gọi tools song song:
  CALL set_project(["NCTH"])
  CALL route_to_consultant(task=...)
  ↓
[FAQInjectionMiddleware inject FAQ NCTH vào Consultant system prompt]
  ↓
Consultant nhận task + context
```

#### Flow 3: Hỏi về dự án Noble (chưa biết dự án nào)

```
KH: "NobleX có những dự án nào?"
  ↓
Luna phân tích → intent: PRE_SALE, project: unknown
  ↓
Luna hỏi làm rõ:
  "{xưng hô} muốn tìm hiểu dự án nào ạ? NobleX hiện có 5 dự án:
   Noble Crystal Tây Hồ, Noble Crystal Long Biên, Noble Palace Long Biên,
   Noble Palace Tây Thăng Long và Sunshine Legend City ạ."
```

#### Flow 4: KH muốn gọi lại / gặp chuyên viên

```
KH: "gọi lại cho tôi" / "muốn nói chuyện với người thật"
  ↓
Luna phân tích → intent: CALLBACK / EXPLICIT_REQUEST
  ↓
Luna: 1 câu acknowledge + route_to_support
```

#### Flow 5: KH off-topic

```
KH: "Bitcoin hôm nay giá bao nhiêu?"
  ↓
Luna phân tích → intent: OFF_TOPIC
  ↓
Luna trả lời trực tiếp:
  "Dạ, em chuyên tư vấn về các dự án bất động sản hàng hiệu của NobleX ạ.
   Nếu Anh/Chị đang tìm hiểu về bất động sản, em rất sẵn lòng hỗ trợ
   thông tin các dự án Noble. Anh/Chị có quan tâm đến khu vực nào không ạ?"
```

---

### CONSULTANT FLOWS

#### Flow 6: INQ_PROJECT_OVERVIEW — Tổng quan dự án

```
KH: "Kể về Noble Palace Long Biên?"
  ↓
Consultant đọc consultant-info/SKILL.md
  ↓
Gọi parallel:
  search_documents(query="Noble Palace Long Biên tổng quan", source="NPLB.md")
  get_project_info(project="NPLB")
  ↓
Tổng hợp kết quả, cite [xxxx] ngay sau từng fact từ RAG
  ↓
Kết thúc bằng Bridge Response: "Anh/Chị muốn tìm hiểu thêm về giá hay tiện ích ạ?"
```

#### Flow 7: INQ_AMENITIES — Tiện ích

```
KH: "Noble Crystal Tây Hồ có tiện ích gì?"
  ↓
Consultant đọc consultant-info/SKILL.md
  ↓
Gọi: search_documents(query="Noble Crystal Tây Hồ tiện ích nội khu ngoại khu")
  ↓
Trả lời từ context (cite [xxxx])
  ↓
Bridge Response: "Anh/Chị muốn biết thêm về giá hoặc đặt lịch tham quan ạ?"
```

#### Flow 8: PRC_PRICE_LIST — Bảng giá

```
KH: "Giá căn 2PN ở Noble Palace Long Biên bao nhiêu?"
  ↓
Consultant đọc consultant-pricing/SKILL.md
  ↓
Gọi: get_project_pricing(project="NPLB", unit_type="2PN")
  ↓
Trả lời với số liệu thực từ DB (KHÔNG bịa)
  ↓
Bridge Response: "Anh/Chị muốn biết thêm về phương thức thanh toán hay ưu đãi ạ?"
```

#### Flow 9: PRC_TOTAL_COST — Tổng chi phí

```
KH: "Tổng tôi phải trả bao nhiêu cho căn 2PN NPLB?"
  ↓
Consultant đọc consultant-pricing/SKILL.md + COST_CALC.md
  ↓
Gọi parallel:
  get_project_pricing(project="NPLB", unit_type="2PN")
  get_project_fees(project="NPLB")
  ↓
Tính toán:
  Giá bán = price_vnd (từ pricing)
  VAT = Giá bán × vat_percent / 100
  Phí bảo trì = area_m2 × maintenance_fee_per_m2
  Phí booking = booking_fee_vnd
  TỔNG = Giá + VAT + Bảo trì + Booking
  ↓
Trình bày chi tiết từng khoản
```

#### Flow 10: PRC_LOAN — Vay ngân hàng

```
KH: "Vay được ngân hàng nào cho dự án NPLB?"
  ↓
Gọi: get_loan_policies(project="NPLB")
  ↓
Trình bày bảng ngân hàng, lãi suất ưu đãi, LTV, thời hạn
  ↓
Guard: "Lãi suất có thể thay đổi, Anh/Chị nên liên hệ trực tiếp ngân hàng để xác nhận ạ"
```

#### Flow 11: Gợi ý dự án (Advisor)

```
KH: "Tôi có khoảng 3 tỷ muốn mua ở Long Biên, nên mua dự án nào?"
  ↓
Consultant đọc consultant-advisor/SKILL.md
  ↓
Entities collected: budget=3 tỷ, region=Long Biên (2/4 entities → gợi ý sơ bộ)
  ↓
Gọi: match_projects(budget_max=3.0, region="Long Biên", bedrooms=0, purpose="unknown")
  ↓
Nhận top 3 dự án
  ↓
Gọi parallel: get_project_pricing(project=X) cho mỗi dự án đề xuất
  ↓
Trình bày so sánh, highlight phù hợp ngân sách
  ↓
Hỏi thêm: "Anh/Chị dự định để ở hay đầu tư ạ? Và muốn mấy phòng ngủ ạ?"
```

#### Flow 12: BKG_VISIT_SCHEDULE — Đặt lịch tham quan (first turn)

```
KH: "Tôi muốn đặt lịch xem nhà mẫu NPLB"
  ↓
Consultant đọc consultant-booking/SKILL.md
  ↓
Mandatory first-turn parallel calls:
  get_booking_state()                           → status: collecting, missing: all 5
  get_available_dates(project="NPLB")           → ["2026-04-14", "2026-04-15", ...]
  update_booking_info(project="NPLB")           → saved project from context
  ↓
Trả lời:
  "Dạ, em sẽ hỗ trợ Anh/Chị đặt lịch tham quan Noble Palace Long Biên ạ.
   Anh/Chị vui lòng cho em xin họ tên ạ?"
```

#### Flow 13: BKG — Thu thập thông tin booking (multi-turn)

```
Turn 1: KH cung cấp tên → update_booking_info(name="Nguyễn Văn A")
Turn 2: KH cung cấp SĐT → update_booking_info(phone="0987654321")
Turn 3: KH chọn ngày → get_available_slots(project="NPLB", date="2026-04-14")
                     → update_booking_info(preferred_date="2026-04-14")
Turn 4: KH chọn giờ → update_booking_info(preferred_slot="10:00-11:00")
Turn 5: get_booking_state() → ready_to_book: true
  ↓
Confirm template:
  "Dạ, em xác nhận lại thông tin đặt lịch:
   - Họ tên: Nguyễn Văn A
   - Số điện thoại: 0987654321
   - Dự án: Noble Palace Long Biên
   - Ngày: 14/04/2026
   - Khung giờ: 10:00 - 11:00
   Anh xác nhận thông tin trên đúng chưa ạ?"
  ↓
KH xác nhận → save_booking(...)
  ↓
Trả về: booking_id: "BK-20260414-001"
```

---

### SUPPORT FLOWS

#### Flow 14: Explicit Request — Gặp chuyên viên (Branch 3)

```
KH: "Tôi muốn nói chuyện với người thật, không muốn chat bot"
  ↓
Support đọc support-escalation/SKILL.md
  ↓
Trigger: explicit_request → Branch 3
  ↓
Gọi parallel:
  get_transfer_state()       → {contact: {name: null, phone: null}}
  get_transfer_message()     → working hours message
  ↓
Trả lời với transfer message, xin tên + SĐT:
  "Dạ, em hiểu ạ. [transfer_message]
   Anh/Chị vui lòng cho em xin họ tên và số điện thoại để chuyên viên
   liên hệ lại ạ?"
  ↓
KH cung cấp info → generate_summary(conversation_history)
  ↓
Xác nhận và hoàn tất transfer
```

#### Flow 15: Callback Request (Branch 3)

```
KH: "Gọi lại cho tôi số 0987654321 nhé"
  ↓
Support → trigger: callback_request → Branch 3
  ↓
get_transfer_state() → merge phone từ message
get_transfer_message()
  ↓
generate_summary(...)
  ↓
"Dạ em đã ghi nhận yêu cầu gọi lại cho Anh/Chị. Chuyên viên NobleX
 sẽ liên hệ Anh/Chị tại số 0987654321 sớm nhất ạ."
```

#### Flow 16: Realtime Data — Bảng hàng (Branch 2)

```
KH: "Cho tôi xem bảng hàng còn lại của NCTH?"
  ↓
Support → trigger: realtime_data → Branch 2
  ↓
Sinh confirmation message:
  "Dạ, thông tin về bảng hàng và giá bán được cập nhật liên tục, em muốn
   kết nối Quý Khách với chuyên viên tư vấn NobleX để được tư vấn chính
   xác nhất. Quý Khách đồng ý không ạ?"
  ↓
KH đồng ý → confirmed_transfer → Branch 3
  generate_summary + get_transfer_message
  ↓
KH từ chối → tiếp tục chat, offer search_documents (limited info)
```

#### Flow 17: AFT_CONTRACT_INFO — Tra cứu hợp đồng

```
KH: "Hợp đồng của tôi còn phải đóng bao nhiêu nữa?"
  ↓
Support đọc support-crm/SKILL.md
  ↓
Trigger keyword: "hợp đồng", "còn phải đóng"
  ↓
STEP 1: lookup_customer_tool(phone=KH_phone)
  → {customer_id: 12345, name: "Nguyễn Văn A", has_cccd: true, contracts: [...]}
  ↓
STEP 2: Yêu cầu CCCD (thông tin bảo mật):
  "Dạ, để bảo mật thông tin hợp đồng, Anh vui lòng cung cấp số CMND/CCCD ạ"
  ↓
KH cung cấp CCCD
  ↓
STEP 3: verify_customer_identity_tool(customer_id=12345, cccd_input="...")
  → {verified: true, contracts: [...]}
  ↓
verify=false → "Thông tin CCCD không khớp, vui lòng liên hệ hotline 18006298 ạ"
  (max 2 lần fail → escalate)
  ↓
STEP 4 (parallel):
  get_contract_info_tool(contract_code="HD-NCTH-001")
  get_payment_schedule_tool(contract_code="HD-NCTH-001")
  ↓
Trả lời chi tiết: số tiền đã đóng, còn lại, các đợt sắp tới
```

#### Flow 18: AFT_COMPLAINT — Khiếu nại

```
KH: "Tôi không hài lòng về dịch vụ bảo trì của NobleX"
  ↓
Support đọc support-crm/SKILL.md
  ↓
Trigger: "khiếu nại" / "không hài lòng"
  ↓
EMPATHIZE FIRST:
  "Dạ, em rất xin lỗi Anh/Chị về trải nghiệm này. Em hiểu đây là điều
   không mong muốn và em sẽ hỗ trợ Anh/Chị ngay ạ."
  ↓
STEP 1: lookup_customer_tool(phone=...)
  ↓
STEP 2: get_ticket_history_tool(phone=...) → kiểm tra complaint trước
  ↓
Thu thập chi tiết khiếu nại
  ↓
STEP 3: create_support_ticket_tool(
  ticket_type="COMPLAINT",
  customer_id=12345,
  contract_code="HD-NCTH-001",
  details="KH phàn nàn về dịch vụ bảo trì...",
  severity="high",
  department="CSKH",
  customer_request="..."
)
  ↓
Returns: {ticket_code: "TK-20260411-0023", email_sent: true, sla_hours: 24}
  ↓
"Dạ em đã tạo phiếu hỗ trợ cho Anh mã TK-20260411-0023 ạ. Bộ phận CSKH
 sẽ liên hệ Anh trong vòng 24 giờ ạ."
```

#### Flow 19: AFT_MAINTENANCE — Báo hỏng / sự cố

```
KH: "Nhà tôi bị rò rỉ nước ở phòng ngủ"
  ↓
Trigger keyword: "rò rỉ" + "nhà tôi" (ownership signal)
  ↓
EMPATHIZE:
  "Dạ, em rất tiếc khi nghe Anh/Chị gặp sự cố này. Em sẽ hỗ trợ Anh/Chị
   ngay ạ."
  ↓
STEP 1: lookup_customer_tool(phone=...)
  ↓
STEP 2: get_contract_info_tool (lấy thông tin căn hộ + bảo hành)
  ↓
STEP 3: create_support_ticket_tool(
  ticket_type="MAINTENANCE",
  severity="normal",  # "urgent" nếu mất điện/ngập/nguy hiểm
  department="Kỹ thuật / Ban QLDA",
  maintenance_info=JSON({"location": "phòng ngủ", "issue": "rò rỉ nước"})
)
  ↓
"Dạ em đã ghi nhận sự cố rò rỉ nước tại phòng ngủ của Anh. Đội kỹ thuật
 sẽ liên hệ Anh trong 48 giờ để lên lịch khắc phục ạ. Mã phiếu: TK-..."
```

#### Flow 20: AFT_PROCEDURE — Sổ hồng

```
KH: "Sổ hồng căn của tôi bao giờ có?"
  ↓
Trigger: "sổ hồng đã" / "bao giờ có sổ"
  ↓
STEP 1: lookup_customer_tool(phone=...)
  → Thông tin công khai → KHÔNG cần verify CCCD
  ↓
STEP 2: get_certificate_status_tool(contract_code="HD-NCTH-001")
  ↓
Returns: status "Đang xử lý — dự kiến Q3/2026"
  ↓
Trả lời + Bridge:
  "Dạ, theo hệ thống, sổ hồng của Anh đang được xử lý, dự kiến Q3/2026 ạ.
   Nếu Anh có thắc mắc về thủ tục sang tên, em có thể hỗ trợ thêm ạ?"
```

---

## Decision Trees

### Luna Decision Tree

```
Nhận tin nhắn
    │
    ├─ Rỗng hoặc >5000 ký tự?
    │   └─ YES → GuardrailMiddleware block
    │
    ├─ Chào hỏi / cảm ơn / tạm biệt / off-topic?
    │   └─ YES → Trả lời trực tiếp
    │
    ├─ Keywords post-sale / support?
    │   ("đã mua", "hợp đồng", "bàn giao", "khiếu nại", ...)
    │   └─ YES → route_to_support
    │
    ├─ "gọi lại" / "callback" / "gặp người" / "chuyên viên gọi"?
    │   └─ YES → route_to_support
    │
    ├─ Hỏi về dự án Noble (pre-sale)?
    │   ├─ Biết dự án cụ thể?
    │   │   └─ YES → set_project([code]) → route_to_consultant
    │   └─ Chưa biết dự án?
    │       └─ Hỏi làm rõ → chờ KH trả lời
    │
    └─ Mơ hồ / không đủ thông tin?
        └─ Hỏi làm rõ
```

### Consultant Decision Tree

```
Nhận task từ Luna
    │
    ├─ Đọc SKILL.md phù hợp nhất
    │
    ├─ Intent thuộc consultant-info?
    │   (INQ_PROJECT_OVERVIEW, INQ_LOCATION, INQ_AMENITIES, ...)
    │   └─ Dùng search_documents / get_project_info / search_units
    │
    ├─ Intent thuộc consultant-pricing?
    │   (PRC_PRICE_LIST, PRC_PAYMENT, PRC_LOAN, PRC_PROMOTION, ...)
    │   └─ Dùng get_project_pricing / get_payment_plans / etc.
    │
    ├─ Intent thuộc consultant-advisor?
    │   └─ Thu thập 4 entities → match_projects → get_project_pricing
    │
    ├─ Intent thuộc consultant-booking?
    │   └─ Mandatory 3 tools parallel → collect 5 fields → save_booking
    │
    └─ Cần escalate?
        (cam kết giá văn bản, bảng hàng real-time, ...)
        └─ route_to_support
```

### Support Decision Tree

```
Nhận task từ Luna
    │
    ├─ Đọc SKILL.md phù hợp nhất
    │
    ├─ Intent post-sale (CRM)?
    │   (AFT_CONTRACT_INFO, AFT_DELIVERY, AFT_COMPLAINT, ...)
    │   ├─ lookup_customer_tool TRƯỚC
    │   ├─ Thông tin bảo mật? → verify_customer_identity_tool
    │   └─ Xử lý theo intent cụ thể
    │
    └─ Intent escalation?
        ├─ Xác định trigger reason (1 trong 9)
        ├─ Branch 1 (skip_info)? → transfer ngay
        ├─ Branch 2 (implicit)? → confirm trước
        └─ Branch 3 (explicit/confirmed)? → thu info → summary → transfer
```

---

## Fallback Messages (từ `src/prompts/fallback_prompt.py`)

### Standard Fallbacks

```python
# Trước khi xử lý
PRE_MESSAGE = "Dạ em nhận thông tin, Quý Khách vui lòng chờ trong giây lát để em tìm kiếm thông tin dự án nhé."

# Chào hỏi
GREETING_RESPONSE = "Dạ, em là Luna — Chuyên viên tư vấn NobleX ạ. Em có thể hỗ trợ Anh/Chị tìm hiểu thông tin dự án, giá cả, hoặc đặt lịch tham quan ạ. Anh/Chị cần em hỗ trợ gì ạ?"

# Off-topic
OUT_OF_NOBLE_RESPONSE = "Dạ, em chuyên tư vấn về các dự án bất động sản hàng hiệu của NobleX ạ.\n\nNếu Quý Khách đang tìm hiểu về bất động sản, em rất sẵn lòng hỗ trợ thông tin các dự án Noble. Quý Khách có quan tâm đến khu vực nào không ạ?"

# Không tìm thấy thông tin
NOT_FOUND_RESPONSE = "Dạ, em xin phép kiểm tra thêm thông tin này ạ.\n\nĐể được hỗ trợ nhanh nhất, Quý Khách có thể:\n- Liên hệ tổng đài NobleX: **18006298**\n- Hoặc để lại số điện thoại để chuyên viên liên hệ hỗ trợ Quý Khách ạ."

# Lỗi hệ thống
SYSTEM_ERROR_RESPONSE = "Dạ, em rất xin lỗi Quý Khách, hệ thống đang gặp sự cố kỹ thuật nên em chưa thể hỗ trợ ngay lúc này ạ.\n\nQuý Khách vui lòng:\n- Thử lại sau ít phút\n- Hoặc liên hệ tổng đài NobleX: **18006298** để được hỗ trợ trực tiếp ạ."
```

### Pre-Answer Messages (theo intent type)

```python
PRE_ANSWER_MESSAGES = {
    "information": "Dạ, Quý Khách vui lòng chờ em trong giây lát để em tìm kiếm thông tin ạ",
    "booking": "Dạ, em ghi nhận yêu cầu của Quý Khách ạ. Quý Khách vui lòng chờ em xử lý trong giây lát nhé",
    "need_human_explicit": "Dạ, em đang kết nối Quý Khách với chuyên viên tư vấn NobleX ạ. Quý Khách vui lòng chờ em trong giây lát nhé",
}
```

### Transfer Confirmation Messages (Branch 2 — theo trigger reason)

```python
TRANSFER_CONFIRM_MESSAGES = {
    "realtime_data": "Dạ, thông tin về bảng hàng và giá bán được cập nhật liên tục, em muốn kết nối Quý Khách với chuyên viên tư vấn NobleX để được tư vấn chính xác nhất. Quý Khách đồng ý không ạ?",

    "pricing_calculation": "Dạ, để tính toán chi tiết giá và phương án thanh toán phù hợp cho Quý Khách, em xin phép kết nối với chuyên viên kinh doanh NobleX. Quý Khách đồng ý không ạ?",

    "complaint": "Dạ, em rất xin lỗi vì chưa hỗ trợ tốt cho Quý Khách. Em muốn kết nối Quý Khách với chuyên viên để được hỗ trợ trực tiếp. Quý Khách đồng ý không ạ?",

    "legal_contract": "Dạ, các vấn đề về pháp lý và hợp đồng cần chuyên viên tư vấn trực tiếp để đảm bảo thông tin chính xác nhất. Em xin phép kết nối Quý Khách với chuyên viên NobleX nhé ạ?",

    "repeated_not_found": "Dạ, em rất tiếc vì chưa tìm được thông tin Quý Khách cần trong hệ thống. Em muốn kết nối với chuyên viên để hỗ trợ Quý Khách tốt hơn. Quý Khách đồng ý không ạ?",
}
```
