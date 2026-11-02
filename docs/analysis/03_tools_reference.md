# Luna Chat DeepAgent — Chi Tiết Tất Cả Tools (20 Tools)

## Nhóm 1: Project Tool (1 tool)

### `set_project`

**File:** `src/agents/tools/project_tools.py`  
**Agent sử dụng:** Luna (main)  
**Khi gọi:** LUÔN gọi trước khi route sang Consultant cho câu hỏi liên quan dự án cụ thể

**Parameters:**
```python
projects: list[str]  # 1-2 items, max 2
# Valid codes: NCTH, NCLB, NPLB, NTTL, SSLC
```

**Returns:**
```json
{
  "status": "ok",
  "projects": ["NCTH"],
  "invalid": [],
  "faq_available": true
}
```

**Vai trò:** Set `project_code` trong `NobleContext` → FAQInjectionMiddleware dùng để inject FAQ vào system prompt của subagent.

---

## Nhóm 2: RAG Tools (3 tools)

**File:** `src/agents/tools/rag_tools.py`

### `search_documents`

**Agent sử dụng:** Consultant, Support  
**Khi gọi:** KH hỏi tiện ích, vị trí, thiết kế, tiến độ, chủ đầu tư, pháp lý mô tả chi tiết  
**KHÔNG dùng cho:** bảng giá, phí VAT, ngân hàng, căn cụ thể

**Parameters:**
```python
query: str   # Bao gồm tên đầy đủ dự án trong query
source: str  # Optional — filter theo file, e.g., "NCTH.md"
```

**Returns:**
```json
{
  "found": true,
  "context": "Dự án gồm 2 tòa cao 17 tầng[a3x9]...",
  "sources": ["NCTH.md"],
  "top_score": 0.87
}
```

**Score threshold:** 0.5 — dưới ngưỡng này coi là not found  
**Citation format:** Mỗi chunk có mã [xxxx] (4 ký tự), phải cite ngay sau thông tin sử dụng

---

### `match_projects`

**Agent sử dụng:** Consultant (advisor)  
**Khi gọi:** KH muốn tư vấn/gợi ý dự án phù hợp với nhu cầu

**Parameters:**
```python
budget_max: float   # Ngân sách tối đa (tỷ VNĐ)
region: str         # Khu vực mong muốn
bedrooms: int       # Số phòng ngủ
purpose: str        # "ở thực" | "đầu tư" | "cả hai"
```

**Returns:**
```json
[
  {
    "code": "NPLB",
    "name": "Noble Palace Long Biên",
    "region": "Long Biên",
    "type": "cao tầng",
    "score": 0.85,
    "reasons": ["Phù hợp ngân sách", "Đúng khu vực"],
    "highlights": ["Tiện ích đầy đủ", "Pháp lý hoàn chỉnh"],
    "min_price": 2800000000,
    "max_price": 15000000000
  }
]
```

**Scoring logic:**
- Base: 0.5
- +0.2 nếu giá ≤ 85% ngân sách
- +0.1 nếu giá ≤ ngân sách
- +0.1 nếu nằm trong `projects_interested` của KH
- Trả về tối đa 3 dự án

---

### `get_region_overview`

**Agent sử dụng:** Consultant (advisor, info)  
**Khi gọi:** KH hỏi "có những dự án nào?", "khu vực nào?"

**Parameters:** None

**Returns:**
```json
{
  "Tây Hồ": ["Noble Crystal Tây Hồ (NCTH)"],
  "Long Biên": ["Noble Crystal Long Biên (NCLB)", "Noble Palace Long Biên (NPLB)"],
  "Tây Thăng Long": ["Noble Palace Tây Thăng Long (NTTL)"],
  "Legend City": ["Sunshine Legend City (SSLC)"]
}
```

---

## Nhóm 3: Structured Data Tools (7 tools — PostgreSQL)

**File:** `src/agents/tools/structured_data_tools.py`

### `get_project_pricing`

**Agent sử dụng:** Consultant (pricing)  
**Khi gọi:** KH hỏi giá, bảng giá, loại căn, diện tích, so sánh giá  
**KHÔNG dùng khi:** KH hỏi căn cụ thể (tầng, mã căn) → dùng `search_units`

**Parameters:**
```python
project: str      # Required — mã dự án
unit_type: str    # Optional — loại căn
max_price: int    # Optional — giá tối đa (VNĐ)
direction: str    # Optional — hướng căn
```

**Returns:**
```json
{
  "project": "NPLB",
  "results_count": 5,
  "results": [
    {
      "type": "2PN",
      "category": "cao tầng",
      "area_min_m2": 65.5,
      "area_max_m2": 75.2,
      "price_from_vnd": 3200000000,
      "price_to_vnd": 4500000000,
      "price_per_m2_vnd": 48000000,
      "total_units": 120,
      "available_units": 45
    }
  ]
}
```

---

### `get_payment_plans`

**Agent sử dụng:** Consultant (pricing)  
**Khi gọi:** KH hỏi thanh toán, đóng mấy đợt, chiết khấu thanh toán sớm

**Parameters:**
```python
project: str  # Mã dự án
```

**Returns:**
```json
{
  "project": "NPLB",
  "plans": [
    {
      "name": "Thanh toán tiêu chuẩn",
      "plan_type": "STANDARD",
      "discount_percent": 0,
      "installments": [
        {"order_index": 1, "milestone_desc": "Ký HĐMB", "percent": 30},
        {"order_index": 2, "milestone_desc": "Bàn giao", "percent": 70}
      ]
    },
    {
      "name": "Thanh toán sớm 95%",
      "plan_type": "EARLY_PAYMENT",
      "discount_percent": 3.5,
      "installments": [...]
    }
  ]
}
```

**plan_type values:** `STANDARD` | `EARLY_PAYMENT` | `INSTALLMENT`

---

### `get_loan_policies`

**Agent sử dụng:** Consultant (pricing)  
**Khi gọi:** KH hỏi vay, lãi suất, ngân hàng liên kết

**Parameters:**
```python
project: str  # Mã dự án
```

**Returns:**
```json
{
  "project": "NPLB",
  "banks": [
    {
      "bank_name": "Vietcombank",
      "interest_rate_year": 8.5,
      "standard_rate_year": 10.5,
      "preferential_months": 24,
      "max_ltv_percent": 70,
      "max_term_years": 25
    }
  ]
}
```

---

### `get_promotions`

**Agent sử dụng:** Consultant (pricing)  
**Khi gọi:** KH hỏi ưu đãi, chiết khấu, quà tặng, khuyến mãi  
**Lưu ý:** Auto-filters expired promotions (chỉ trả về còn hiệu lực)

**Parameters:**
```python
project: str  # Mã dự án
```

**Returns:**
```json
{
  "project": "NPLB",
  "active_count": 2,
  "promotions": [
    {
      "name": "Chiết khấu thanh toán sớm",
      "promotion_type": "DISCOUNT_PERCENT",
      "discount_value_percent": 3.5,
      "valid_until": "2026-06-30"
    },
    {
      "name": "Gói nội thất bếp",
      "promotion_type": "GIFT",
      "discount_value_percent": null,
      "valid_until": "2026-03-31"
    }
  ]
}
```

**promotion_type values:** `DISCOUNT_PERCENT` | `GIFT` | `CASHBACK`

---

### `get_project_fees`

**Agent sử dụng:** Consultant (pricing)  
**Khi gọi:** KH hỏi phí booking, VAT, phí bảo trì, phí dịch vụ, tổng chi phí  
**LUÔN dùng thay vì `search_documents`** cho câu hỏi về phí

**Parameters:**
```python
project: str  # Mã dự án
```

**Returns:**
```json
{
  "booking_fee_vnd": 50000000,
  "hold_duration_hours": 48,
  "vat_percent": 10,
  "maintenance_fee_per_m2": 1200000,
  "service_fee_per_m2_year": 25000
}
```

---

### `get_project_info`

**Agent sử dụng:** Consultant (info, pricing)  
**Khi gọi:** KH hỏi tổng quan dự án, pháp lý tóm tắt, trạng thái bán, khu vực

**Parameters:**
```python
project: str  # Mã dự án
```

**Returns:**
```json
{
  "project": "NPLB",
  "info": {
    "code": "NPLB",
    "name": "Noble Palace Long Biên",
    "region": "Long Biên",
    "status": "selling",
    "legal_status": "COMPLETE",
    "booking_fee_vnd": 50000000
  }
}
```

**status values:** `selling` | `coming_soon` | `sold_out`  
**legal_status values:** `COMPLETE` | `PARTIAL`

---

### `search_units`

**Agent sử dụng:** Consultant (info, pricing)  
**Khi gọi:** KH hỏi căn cụ thể (tầng, hướng, mã căn)  
**KHÔNG dùng khi:** KH chỉ hỏi bảng giá chung → dùng `get_project_pricing`

**Parameters:**
```python
project: str      # Mã dự án
unit_type: str    # Loại căn
max_price: int    # Giá tối đa
direction: str    # Hướng
floor: int        # Tầng
tower: str        # Tòa
unit_code: str    # Mã căn cụ thể
status: str       # Default: "available"
min_area: int     # Diện tích tối thiểu
```

**Unit types:**
- Cao tầng: `Studio`, `1PN`, `2PN`, `3PN`, `4PN`, `Duplex`, `Penthouse`, `Sky Villa`
- Thấp tầng: `Liền kề`, `Biệt thự đơn lập`, `Biệt thự song lập`, `Shophouse`

**Returns (cao tầng):**
```json
{
  "unit_code": "A-1205",
  "wall_area_m2": 72.5,
  "clear_area_m2": 68.2,
  "bedroom_count": 2,
  "room_details": {"living_room": 1, "bathroom": 2, "balcony": 1},
  "direction": "Đông Nam",
  "floor": 12,
  "tower": "A",
  "price_vnd": 3800000000,
  "status": "available"
}
```

**Returns (thấp tầng):**
```json
{
  "unit_code": "LK-05",
  "land_area_m2": 120,
  "frontage_m": 6,
  "floor_count": 4,
  "floor_details": {"basement": 1, "floors": 3, "rooftop": 0},
  "direction": "Đông",
  "price_vnd": 8500000000,
  "status": "available"
}
```

---

## Nhóm 4: Booking Tools (5 tools — Factory Pattern)

**File:** `src/agents/tools/booking_tools.py`  
**Lưu ý:** Tất cả tools được tạo theo factory pattern, nhận request context khi khởi tạo

### `get_booking_state`

**Khi gọi:** BẮT BUỘC gọi ĐẦU TIÊN khi KH muốn đặt lịch, xem nhà mẫu, hoặc giữ chỗ

**Parameters:** None (EmptyInput)

**Returns:**
```json
{
  "collected": ["customer_name", "phone_number"],
  "missing": ["project_interest", "preferred_date", "preferred_slot"],
  "status": "collecting",
  "all_data": {
    "customer_name": "Nguyễn Văn A",
    "phone_number": "0987654321",
    "project_interest": null,
    "preferred_date": null,
    "preferred_slot": null
  }
}
```

**status values:** `collecting` | `confirming` | `confirmed`

---

### `update_booking_info`

**Khi gọi:** Ngay khi KH cung cấp bất kỳ thông tin nào trong context booking

**Parameters:**
```python
name: str            # Tên khách
phone: str           # Số điện thoại (validated)
project: str         # Dự án quan tâm (fuzzy match)
preferred_date: str  # YYYY-MM-DD format
preferred_slot: str  # HH:MM-HH:MM format
```

**Validation:**
- Phone regex: `^(0[35789])\d{8}$`
- Normalized project name → project code
- Reject past dates

**Returns:**
```json
{
  "saved": {"customer_name": "Nguyễn Văn A", "phone_number": "0987654321"},
  "errors": {},
  "current_state": "collecting",
  "still_missing": ["project_interest", "preferred_date", "preferred_slot"],
  "ready_to_book": false
}
```

---

### `get_available_dates`

**Khi gọi:** Đồng thời với `get_booking_state` khi bắt đầu booking flow

**Parameters:**
```python
project: str  # Mã dự án
```

**Returns:**
```json
["2026-04-14", "2026-04-15", "2026-04-17", "2026-04-18", "2026-04-19", "2026-04-21"]
```

**Logic:** 14 ngày tới, thứ 2 - thứ 7 (không Chủ nhật)

---

### `get_available_slots`

**Khi gọi:** Khi KH đã chọn ngày và cần xem khung giờ

**Parameters:**
```python
project: str  # Mã dự án
date: str     # YYYY-MM-DD
```

**Returns:**
```json
["09:00 - 10:00", "10:00 - 11:00", "14:00 - 15:00", "15:00 - 16:00"]
```

---

### `save_booking`

**Khi gọi:** CHỈ sau khi KH đã xác nhận đầy đủ cả 5 trường  
**Lưu ý:** Kiểm tra conflict thời gian trước khi lưu

**Parameters:**
```python
customer_name: str      # Tên KH
phone_number: str       # SĐT
project_interest: str   # Dự án
preferred_date: str     # YYYY-MM-DD
preferred_slot: str     # HH:MM - HH:MM
```

**Returns (success):**
```json
{
  "success": true,
  "booking_id": "BK-20260414-001"
}
```

**Returns (failure):**
```json
{
  "success": false,
  "error": "Khung giờ 10:00-11:00 ngày 14/04 đã đầy, vui lòng chọn khung giờ khác"
}
```

---

## Nhóm 5: Transfer/Escalation Tools (5 tools — Factory Pattern)

**File:** `src/agents/tools/transfer_tools.py`

### `get_transfer_state`

**Khi gọi:** Đầu tiên trong Branch 3 (explicit/confirmed transfer)

**Parameters:** None

**Returns:**
```json
{
  "contact": {
    "customer_name": "Nguyễn Văn A",
    "phone_number": "0987654321"
  }
}
```

**Lưu ý:** Merge với `user_profile` nếu đã có trong context

---

### `generate_summary`

**Khi gọi:** Trước khi transfer để tạo handoff note cho chuyên viên  
**Cơ chế:** Gọi LLM để sinh tóm tắt 5-8 dòng plain text

**Parameters:**
```python
conversation_history: str  # Toàn bộ lịch sử hội thoại
```

**Summary prompt (verbatim):**
```
Tóm tắt cuộc hội thoại sau để chuyên viên CSKH NobleX tiếp nhận nhanh
mà không cần đọc lại toàn bộ.

Viết 3-5 dòng text thuần (KHÔNG markdown, KHÔNG bullet phức tạp):
- Dòng 1: KH là ai (tên, SĐT nếu đã cung cấp), quan tâm dự án/khu vực nào
- Dòng 2-3: Nhu cầu chính của KH (cụ thể, không xã giao)
- Dòng 4: AI đã hỗ trợ gì, hoặc "AI chưa xử lý, đã chuyển chuyên viên ngay"
- Dòng 5: Lý do chuyển chuyên viên
```

**Returns:** Plain text summary string (5-8 dòng)

---

### `get_transfer_message`

**Khi gọi:** Song song với `get_transfer_state` trong Branch 3

**Parameters:** None

**Returns (trong giờ làm việc 8:00-21:00 VN):**
```
"Dạ, để Quý Khách được tư vấn chi tiết nhất về dự án, em xin phép chuyển
thông tin đến chuyên viên tư vấn NobleX. Quý Khách vui lòng đợi trong giây lát,
chuyên viên sẽ liên hệ hỗ trợ Quý Khách sớm nhất ạ. Nếu được, Quý Khách vui
lòng cho em xin số điện thoại để tiện liên hệ ạ."
```

**Returns (ngoài giờ):**
```
"Dạ, em rất tiếc hiện tại đang ngoài giờ làm việc của NobleX (8:00 - 21:00).
Quý Khách vui lòng để lại số điện thoại, em sẽ chuyển thông tin để chuyên viên
NobleX liên hệ hỗ trợ Quý Khách trong giờ làm việc ngày hôm sau ạ."
```

---

### `get_department_contact`

**Khi gọi:** Khi cần biết email của bộ phận để tạo ticket hoặc escalation email

**Parameters:**
```python
department: str  # Tên bộ phận
```

**Department → Email mapping:**
| Department | Email |
|------------|-------|
| CVTV trực chat | sales@noblex.vn |
| Quản lý kinh doanh | sales.manager@noblex.vn |
| Bộ phận CSKH | cskh@noblex.vn |
| Bộ phận pháp lý | legal@noblex.vn |
| Kỹ thuật + Ban QLDA | tech@noblex.vn |
| Quản lý + Pháp lý | management@noblex.vn |
| Kế toán / Bộ phận HĐ | accounting@noblex.vn |
| Bộ phận bàn giao | handover@noblex.vn |
| Bộ phận thủ tục | admin@noblex.vn |

**Returns:**
```json
{"email": "cskh@noblex.vn"}
```

---

### `generate_escalation_email`

**Khi gọi:** Khi cần tạo email chuyển tiếp yêu cầu cho bộ phận liên quan

**Parameters:**
```python
request_type: str      # "transaction_check" | "contract_schedule" | "payment_extension" | "legal_document"
customer_info: str     # JSON string của thông tin KH
details: str           # Chi tiết yêu cầu
```

**Department routing theo request_type:**
| request_type | To | CC |
|---|---|---|
| `transaction_check` | Phòng Thủ tục, Phòng Kế toán | - |
| `legal_document` | Phòng Pháp chế | - |
| `payment_extension` | Phòng Kinh doanh | Ban Lãnh đạo |
| `contract_schedule` | Phòng Kinh doanh | - |

**Returns:**
```json
{
  "subject": "Yêu cầu kiểm tra giao dịch - KH Nguyễn Văn A - 0987654321",
  "body": "Kính gửi Phòng Thủ tục...",
  "to": "accounting@noblex.vn",
  "cc": ""
}
```

---

## Nhóm 6: CRM Tools (7 tools)

**File:** `src/agents/tools/crm_tools.py`

### `lookup_customer_tool`

**Khi gọi:** ĐẦU TIÊN khi KH đã mua liên hệ (trigger keywords xem Skill 6)

**Parameters:**
```python
phone: str  # Số điện thoại KH
```

**Returns:**
```json
{
  "customer_id": 12345,
  "name": "Nguyễn Văn A",
  "has_cccd": true,
  "contracts": [
    {"contract_code": "HD-NCTH-001", "project": "NCTH", "unit": "A-1205"}
  ]
}
```

**Lưu ý:** KHÔNG trả về CCCD — chỉ trả về `has_cccd: bool`

---

### `verify_customer_identity_tool`

**Khi gọi:** BẮT BUỘC trước khi cung cấp thông tin tài chính hợp đồng  
**Lưu ý:** Agent KHÔNG so sánh CCCD — tool so sánh nội bộ với DB

**Parameters:**
```python
customer_id: int   # ID từ lookup_customer_tool
cccd_input: str    # CCCD KH cung cấp
```

**Returns:**
```json
{
  "verified": true,
  "contracts": [
    {"contract_code": "HD-NCTH-001", "project": "NCTH"}
  ]
}
```

---

### `get_contract_info_tool`

**Khi gọi:** Sau khi verify thành công, song song với `get_payment_schedule_tool`

**Parameters:**
```python
contract_code: str  # e.g., "HD-NCTH-001"
```

**Returns:**
```json
{
  "contract_code": "HD-NCTH-001",
  "project": "NCTH",
  "unit": "A-1205",
  "contract_value": 4200000000,
  "sign_date": "2025-06-15",
  "payments_summary": {
    "total_paid": 1260000000,
    "total_remaining": 2940000000,
    "paid_percent": 30
  },
  "warranty": {"duration_months": 24, "expiry": "2028-01-01"},
  "handover_schedule": {"expected_date": "2026-12-31", "actual_date": null}
}
```

---

### `get_payment_schedule_tool`

**Khi gọi:** Sau verify, song song với `get_contract_info_tool`

**Parameters:**
```python
contract_code: str  # Mã hợp đồng
```

**Returns:**
```json
{
  "installments": [
    {
      "order": 1,
      "milestone": "Ký HĐMB",
      "percent": 30,
      "amount": 1260000000,
      "due_date": "2025-06-15",
      "paid_date": "2025-06-14",
      "status": "paid"
    },
    {
      "order": 2,
      "milestone": "Bàn giao",
      "percent": 70,
      "amount": 2940000000,
      "due_date": "2026-12-31",
      "paid_date": null,
      "status": "pending"
    }
  ],
  "total_paid": 1260000000,
  "total_remaining": 2940000000
}
```

---

### `create_support_ticket_tool`

**Khi gọi:** Khi KH cần tạo yêu cầu hỗ trợ chính thức  
**Side effect:** Tự động gửi email notification đến bộ phận tương ứng

**Parameters:**
```python
ticket_type: str        # "COMPLAINT" | "MAINTENANCE" | "PROCEDURE" | "DELIVERY" | "CONTRACT_INQUIRY"
customer_id: int        # ID KH
contract_code: str      # Mã HĐ
details: str            # Mô tả chi tiết yêu cầu
severity: str           # "normal" | "high" | "urgent"
department: str         # Bộ phận tiếp nhận
customer_request: str   # Yêu cầu cụ thể của KH
maintenance_info: str   # JSON (cho MAINTENANCE type)
```

**Returns:**
```json
{
  "ticket_code": "TK-20260411-0023",
  "email_sent": true,
  "sla_hours": 24
}
```

**SLA by severity:**
- `normal` → 48h
- `high` → 24h
- `urgent` → 4h

---

### `get_ticket_history_tool`

**Khi gọi:** TRƯỚC khi tạo complaint ticket (kiểm tra KH đã phàn nàn trước chưa)

**Parameters:**
```python
phone: str  # Số điện thoại KH
```

**Returns:**
```json
{
  "tickets": [
    {
      "ticket_code": "TK-20260101-0005",
      "type": "COMPLAINT",
      "created_at": "2026-01-01",
      "status": "resolved",
      "details": "Rò rỉ nước tại tầng 12"
    }
  ],
  "total_tickets": 1
}
```

---

### `get_certificate_status_tool`

**Khi gọi:** KH hỏi "bao giờ có sổ hồng", "thủ tục sang tên"  
**Phạm vi:** Chỉ bao gồm sổ hồng + sang tên; thuế/hộ khẩu → dùng `search_documents`

**Parameters:**
```python
contract_code: str  # Mã hợp đồng
```

**Returns:**
```json
{
  "certificates": [
    {
      "type_display": "Sổ hồng (Giấy chứng nhận quyền sử dụng đất)",
      "status_display": "Đang xử lý — dự kiến Q3/2026",
      "issued_date": null,
      "notes": "Hồ sơ đã nộp Sở TN&MT ngày 2026-03-01"
    },
    {
      "type_display": "Thủ tục sang tên",
      "status_display": "Chưa thực hiện — chờ có sổ hồng",
      "issued_date": null,
      "notes": null
    }
  ]
}
```
