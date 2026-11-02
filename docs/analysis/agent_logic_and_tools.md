# Tài Liệu Phân Tích Logic Hệ Thống Voice Agent NobleX

Tài liệu này cung cấp cái nhìn chi tiết về cách thức các Agent trong hệ thống NobleX vận hành, từ các định nghĩa lý thuyết (`definitions`) đến các chỉ dẫn thực thi cụ thể trong prompts (`src/agent/prompts`).

---

## 1. Kiến Trúc Tổng Quan (Multi-Agent System)

Hệ thống NobleX được xây dựng trên mô hình Multi-Agent, nơi mỗi Agent đảm nhận một vai trò chuyên biệt. Việc chuyển đổi giữa các Agent được thực hiện thông qua tool `switch_agent`.

### 1.1. Luồng Di Chuyển Chính
1. **Khách hàng** gọi đến -> **Router** (Tiếp đón).
2. **Router** đánh giá nhu cầu -> `switch_agent` sang:
   - **Advisor**: Tư vấn mua mới, dự án, giá.
   - **Booking**: Đặt lịch xem nhà mẫu.
   - **Support**: Hỗ trợ khách đã mua (hợp đồng, thanh toán).
   - **Transfer**: Leo thang chuyển chuyên viên thật.

---

## 2. Chi Tiết Từng Agent & Logic Xử Lý

### 2.1. Router (Tuyến đầu tiếp đón)
**Logic**: Xác định nhu cầu nhanh nhất, KHÔNG tự tư vấn, chuyển luồng ngay lập tức khi phát hiện intent.

**Các Case & Nhóm Intent**:
- **Chào hỏi**: "Dạ em là Luna, Chuyên viên tư vấn Noble ạ. Quý Khách muốn tìm hiểu dự án hay đặt lịch tham quan ạ?"
- **Đã xác định nhu cầu**: Gọi `switch_agent` ngay (không nói "em sẽ chuyển").
- **Chưa rõ nhu cầu (Clarify)**: Hỏi tối đa 2 lần theo mẫu menu:
  1. Tìm hiểu dự án mới.
  2. Xem giá, chính sách.
  3. Đặt lịch xem nhà.
  4. Hỗ trợ hợp đồng đã mua.
- **Off-topic**: Trả lời lịch sự mình là chuyên viên BĐS Noble và đề nghị quay lại chủ đề chính.

**Tools & Ví dụ**:
- `switch_agent(agent_id="advisor", query="anh muốn mua căn 2 ngủ ở Long Biên")`
- `update_customer(name="Cường", gender="M", project_interest="NCLB")`

---

### 2.2. Advisor (Chuyên viên tư vấn dự án)
**Logic**: Nhiệt tình (T1) khi nói về tiện ích, Tự tin (T2) khi nói về giá/pháp lý. Tuyệt đối không nói "em không biết" mà phải dùng `noble_search`.

**Nhóm Case & Tool Xử Lý**:
- **Thông tin dự án (Vị trí, Tiện ích, Pháp lý)**:
  - Tool: `noble_search(query="vị trí dự án Noble Crystal Long Biên", project_filter="NCLB")`
- **Giá & Tài chính**:
  - Tool: `get_project_financial(project_code="NCLB", info_type="pricing")`
- **Tìm căn hộ phù hợp**:
  - Tool: `search_units(project_code="NCLB", unit_type="2PN")`
- **So sánh dự án**: Tra cứu cả 2 và đưa ra bảng so sánh.

**Ví dụ dữ liệu chuẩn**:
- **NCLB (Noble Crystal Long Biên)**: Sky villa 17 tầng, 413 căn duplex, bể bơi riêng.
- **NCTH (Noble Crystal Tây Hồ)**: 5 toà 40 tầng, WorldHotels quản lý.

---

### 2.3. Booking (Chuyên viên đặt lịch)
**Logic**: Chuyên nghiệp (T3). Chờ khách xác nhận "OK" mới thực thi đặt lịch. Nếu khách hỏi giá/thông tin sâu thì chuyển ngược lại `advisor`.

**Workflow đặt lịch (5 thông tin bắt buộc)**:
1. Tên
2. SĐT (Validate qua `validate_phone`)
3. Dự án (Mã dự án chuẩn)
4. Ngày
5. Giờ
- **Hành động**: `check_availability` -> Xác nhận khách -> `schedule_viewing(confirmed=true)`.

**Ví dụ**:
- `schedule_viewing(name="Anh Cường", phone="0983828828", project="NCLB", date="2024-04-15", time="09:00", confirmed=true)`

---

### 2.4. Support (Hỗ trợ sau mua)
**Logic**: Đồng cảm (T4). Ưu tiên bảo mật thông tin.

**Quy tắc bảo mật (CRM Security Flow)**:
- Mọi câu hỏi về **Hợp đồng, Thanh toán, Sổ hồng** -> Yêu cầu CCCD.
- Tool: `verify_identity(customer_id="...", cccd="...")`.
- Nếu sai 2 lần -> `switch_agent(agent_id="transfer")`.

**Dịch vụ hỗ trợ**:
- Tra cứu HĐ: `crm_lookup(action="contract", contract_code="...")`.
- Tạo phiếu khiếu nại: `support_ticket(action="create", ticket_type="COMPLAINT", severity="high")`.

---

### 2.5. Transfer (Bộ phận Escalation)
**Logic**: Thấu hiểu, ấm áp (T4). Là chốt chặn cuối cùng khi AI không thể xử lý.

**Trường hợp chuyển người thật**:
- Khách yêu cầu: "Gặp nhân viên", "nói chuyện với người thật".
- Vấn đề nhạy cảm: Pháp lý phức tạp, đe doạ kiện.
- Bot không có dữ liệu sau 2 lần tra cứu.

**Quy trình chuyển (Escalate Tool)**:
1. `escalate(action="check_state")` để xem đủ Tên/SĐT chưa.
2. Thông báo cho khách lý do chuyển (Context-specific).
3. `escalate(action="transfer", department="CVTV", priority="high")` hoặc `transfer_to_human`.

---

## 3. Định Nghĩa Tool & Tham Số Chi Tiết (Data Model)

Lưu ý: Mọi tham số chuỗi phải ưu tiên viết bằng **Chữ số** thay vì số ký hiệu trong Voice (VD: "bảy tỷ" thay vì "7.000.000.000").

| Nhóm Tool | Tool Name | Tham số quan trọng | Ghi chú từ logic |
| :--- | :--- | :--- | :--- |
| **Hệ thống** | `switch_agent` | `agent_id`, `query` | Gọi kèm output text để tránh im lặng. |
| **Dữ liệu** | `noble_search` | `query`, `project_filter` | Query giữ nguyên văn câu khách hỏi. |
| **Thông tin** | `get_project_financial` | `project_code`, `info_type` | `info_type` gồm: pricing, payment_plans, loan... |
| **Bảo mật** | `verify_identity` | `customer_id`, `cccd` | Bắt buộc cho Post-sale. |
| **Hành động** | `update_customer` | `name`, `gender`, `project_interest` | Lưu context ngay khi có data. |

---

## 4. Các Quy Tắc Guardrails & Persona (Văn Hoá NobleX)

Dựa trên `src/agent/prompts/core/tone_guidelines.txt` và `shared/RULES.md`:
- **Xưng hô**: Xưng "em", gọi khách là "Anh/Chị + Tên". Nếu chưa biết tên gọi là "Quý Khách".
- **Từ khoá cấm**: KHÔNG dùng "không" trực diện -> dùng "chưa có", "dạ hiện tại bên em chưa nắm...".
- **Văn nói**: Câu ngắn (2-3 câu), bắt đầu bằng "Dạ", kết thúc bằng "ạ".
- **Voice-friendly**: Không dùng markdown (dấu sao, gạch đầu dòng) khi trả lời khách (vì là voice). Phải viết số bằng chữ.

---

## 5. Dữ Liệu Dự ÁN Chuẩn (Shared Knowledge)

Dự án cần ghi nhớ mã (`project_code`) để truyền vào tham số tool:
- **Noble Crystal Long Biên (NCLB)**: Long Biên, Sky villa cao cấp.
- **Noble Palace Long Biên (NPLB)**: Long Biên, Biệt thự châu Âu.
- **Noble Crystal Tây Hồ (NCTH)**: Tây Hồ, 5 toà 40 tầng.
- **Noble Palace Tây Thăng Long (NTTL)**: 42ha, Tây Thăng Long.
- **Sunshine Legend City (SSLC)**: Dự án hỗn hợp.

---
*Tài liệu được cập nhật tự động dựa trên cấu trúc codebase NobleX Development.*
