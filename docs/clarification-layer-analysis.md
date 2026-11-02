# Phân tích toàn diện: Agent Scenarios vs Voice Agent hiện tại

Nguồn: `NobleX_AI_Agent_Scenarios.xlsx` (8 sheets)
So sánh với: Voice Agent (`voice-agent-sandbox-fix`) + Subagent (`NMC-Utils/Subagent`)
Phạm vi: Kênh Voice (bỏ qua nội dung chỉ chat-only)

---

## Mục lục

1. [Tổng quan hệ thống Scenarios](#1-tổng-quan)
2. [Gap Analysis: Voice Agent vs Scenarios](#2-gap-analysis)
3. [Gap Analysis: Subagent Skills vs Scenarios](#3-subagent-gaps)
4. [Chi tiết thay đổi cần thiết](#4-chi-tiết-thay-đổi)
5. [Flow tổng thể sau khi áp dụng](#5-flow-tổng-thể)

---

## 1. Tổng quan

### Scenarios định nghĩa 30 intents chia 5 nhóm

```
Nhóm 1 — THÔNG TIN DỰ ÁN (Tone T1: Nhiệt tình)      8 intents (INQ_*)
Nhóm 2 — GIÁ & CHÍNH SÁCH (Tone T2: Tự tin)           7 intents (PRC_*)
Nhóm 3 — BOOKING (Tone T3: Chuyên nghiệp)              4 intents (BKG_*)
Nhóm 4 — SAU MUA (Tone T4: Đồng cảm)                   5 intents (AFT_*)
Nhóm 5 — HỆ THỐNG (Tone T5: Nhẹ nhàng)                 6 intents (SYS_*)
+ Clarification Layer (6 pain points)
+ Escalation Rules (10 rules)
+ Tone Guidelines (10 mandatory rules + 5 tone codes)
```

### Voice Agent hiện tại bao phủ gì

Voice agent dùng 1 system prompt cho 1 agent (Luna). Không phân intent riêng — LLM tự quyết dựa vào prompt sections: GREETING, LUỒNG TƯ VẤN, TOOL ROUTING, ĐẶT LỊCH, CHUYỂN CHUYÊN VIÊN, OFF-TOPIC, XỬ LÝ ĐẶC BIỆT.

### Subagent bao phủ gì

4 agents chuyên biệt:
- **advisor** (noble-advisor skill) → Nhóm 1 + Nhóm 2
- **booking** (visit-scheduling skill) → Nhóm 3 (chỉ BKG_VISIT)
- **transfer** (human-transfer skill) → escalation
- **luna** (luna-general skill) → Nhóm 5

---

## 2. Gap Analysis: Voice Agent vs Scenarios

### Nhóm 1 — THÔNG TIN DỰ ÁN (8 intents)

| Intent | Mô tả | Voice Agent | GAP |
|--------|--------|------------|-----|
| INQ_PROJECT_OVERVIEW | Tổng quan DA | ✅ `get_project_overview` tool | — |
| INQ_LOCATION | Vị trí & kết nối | ✅ `noble_search` | — |
| INQ_AMENITIES | Tiện ích DA | ✅ `noble_search` | — |
| INQ_LEGAL | Pháp lý DA | ✅ `noble_search` (đã fix: search trước transfer) | — |
| INQ_PROGRESS | Tiến độ xây dựng | ✅ `noble_search` | — |
| INQ_DEVELOPER | Chủ đầu tư | ✅ `noble_search` | — |
| INQ_COMPARE | So sánh DA | ⚠️ Prompt có nhắc so sánh, nhưng **thiếu hướng dẫn luôn kết thúc bằng recommendation** | Cần thêm |
| INQ_PRODUCT_TYPE | Loại căn/sản phẩm | ✅ `noble_search` | — |

**GAP cụ thể:**

**INQ_COMPARE — thiếu rule "luôn kết thúc bằng gợi ý"**

Scenarios yêu cầu: *"Luôn kết thúc bằng recommendation dựa trên nhu cầu KH"*. Voice prompt chỉ nói search + trả lời tự nhiên, không enforce recommendation cuối.

**Đề xuất thêm vào LUỒNG TƯ VẤN:**
```
Khi KH so sánh dự án:
  → Tìm kiếm thông tin cả 2+ dự án.
  → Trả lời khách quan, nêu ưu/nhược mỗi bên.
  → LUÔN kết thúc bằng gợi ý: "Dựa trên nhu cầu [mục đích] của Quý Khách,
     em gợi ý [DA phù hợp hơn] ạ."
```

**INQ_LEGAL — Tone T2 thay vì T1**

Scenarios chỉ định pháp lý dùng **T2 (Tự tin, rõ ràng, tạo yên tâm)** thay vì T1 (Nhiệt tình). Và rule: **KHÔNG BAO GIỜ cung cấp thông tin pháp lý chưa xác thực**.

Voice prompt đã có "KHÔNG bịa đặt thông tin" — nhưng chưa nhấn mạnh riêng cho pháp lý.

**Đề xuất thêm vào prompt sau noble_search topics:**
```
Khi trả lời về pháp lý, hợp đồng:
  → Trả lời tự tin, rõ ràng, tạo yên tâm.
  → CHỈ cung cấp thông tin từ kết quả search, KHÔNG suy luận hay bổ sung.
  → Nếu KH hỏi chi tiết vượt ngoài FAQ → đề xuất chuyển chuyên viên pháp lý.
```

### Nhóm 2 — GIÁ & CHÍNH SÁCH (7 intents)

| Intent | Mô tả | Voice Agent | GAP |
|--------|--------|------------|-----|
| PRC_PRICE_LIST | Bảng giá | ⚠️ Prompt nói "bảng hàng realtime → transfer" nhưng FAQ có giá cơ bản | Cần phân biệt giá tham khảo vs giá realtime |
| PRC_PAYMENT | Chính sách thanh toán | ✅ `noble_search` + FAQ | — |
| PRC_PROMOTION | Ưu đãi/khuyến mãi | ⚠️ Không có trong prompt hay FAQ | **THIẾU** — cần data source |
| PRC_LOAN | Hỗ trợ vay | ✅ FAQ có (MB Bank) | — |
| PRC_INVESTMENT | Tiềm năng đầu tư | ⚠️ Prompt không có rule "KHÔNG cam kết lợi nhuận" | **THIẾU rule** |
| PRC_TOTAL_COST | Chi phí tổng | ✅ FAQ nplb_032 rất chi tiết | — |
| PRC_COMPARE_PRICE | So sánh giá | ⚠️ Tương tự INQ_COMPARE | Cần rule recommendation |

**GAP cụ thể:**

**PRC_PRICE_LIST — phân biệt "giá tham khảo" vs "giá realtime"**

Scenarios: *"Không bao giờ cam kết giá cụ thể nếu không có bảng giá chính thức"*. Hiện tại voice agent transfer NGAY cho "bảng hàng realtime" — đúng cho giá chính xác. Nhưng FAQ có giá tham khảo/m2 mà agent có thể chia sẻ.

**Đề xuất thêm:**
```
Khi KH hỏi giá:
  → Search trước — nếu FAQ có giá tham khảo → chia sẻ kèm disclaimer:
    "Dạ, giá tham khảo khoảng [X] ạ. Để có bảng giá chính xác và cập nhật nhất,
     em có thể chuyển Quý Khách tới chuyên viên ạ."
  → Nếu KH hỏi giá CỤ THỂ từng căn → transfer (realtime data).
```

**PRC_INVESTMENT — thiếu rule "không cam kết lợi nhuận"**

Scenarios: *"KHÔNG BAO GIỜ cam kết lợi nhuận — chỉ tham khảo dữ liệu"*. Voice prompt không có rule này.

**Đề xuất thêm vào prompt:**
```
Khi KH hỏi về đầu tư, lợi nhuận, tăng giá:
  → Trả lời dựa trên dữ liệu nếu có (vị trí, quy hoạch, tiện ích).
  → KHÔNG BAO GIỜ cam kết lợi nhuận hay tỷ suất sinh lời cụ thể.
  → "Dạ, em chỉ có thể chia sẻ thông tin tham khảo ạ.
     Quyết định đầu tư cần Quý Khách cân nhắc thêm ạ."
```

**PRC_PROMOTION — không có data**

Scenarios define intent PRC_PROMOTION (ưu đãi, khuyến mãi, quà tặng). Voice agent + FAQ không có data này. Đây là data thay đổi theo thời điểm.

**Đề xuất:** Thêm vào transfer rules:
```
Khi KH hỏi ưu đãi, khuyến mãi, quà tặng hiện tại:
  → Search trước (có thể FAQ có chính sách chung).
  → Nếu không có data cụ thể → "Dạ, chính sách ưu đãi thay đổi theo thời điểm ạ.
     Em chuyển Quý Khách tới chuyên viên để cập nhật mới nhất ạ."
```

### Nhóm 3 — BOOKING (4 intents)

| Intent | Mô tả | Voice Agent | GAP |
|--------|--------|------------|-----|
| BKG_VISIT | Đặt lịch xem nhà | ✅ `schedule_viewing` tool, 5 fields | — |
| BKG_BOOKING | Booking giữ chỗ | ❌ KHÔNG CÓ | **LỚN** — cần CCCD, mã căn, thanh toán |
| BKG_DEPOSIT | Đặt cọc/ký HĐ | ❌ KHÔNG CÓ | **LỚN** — quy trình phức tạp |
| BKG_CONSULT_REQUEST | Yêu cầu tư vấn trực tiếp | ⚠️ Bị gộp vào transfer | Cần tách riêng |

**GAP cụ thể:**

**BKG_BOOKING + BKG_DEPOSIT — quá phức tạp cho voice agent**

Scenarios liệt kê BKG_BOOKING cần: CCCD, mã căn, thông tin thanh toán, trạng thái căn realtime, document upload. BKG_DEPOSIT còn phức tạp hơn: thông tin vợ/chồng, giấy tờ pháp lý, biên lai.

Voice agent **KHÔNG THỂ** xử lý (không có CRM, không verify CCCD, không nhận document). Đây thuộc **transfer + ghi nhận**.

**Đề xuất:** Nhận diện intent nhưng transfer ngay:
```
Khi KH muốn booking giữ chỗ hoặc đặt cọc (không phải đặt lịch xem nhà):
  → "Dạ, để booking giữ chỗ/đặt cọc em cần chuyển Quý Khách tới chuyên viên
     vì cần xác thực giấy tờ và kiểm tra căn hộ ạ."
  → Thu thập: tên, SĐT, dự án, căn quan tâm (nếu biết)
  → Transfer to human
```

**BKG_CONSULT_REQUEST — cần tách khỏi transfer chung**

Scenarios: KH muốn tư vấn trực tiếp = thu thập nhu cầu chi tiết (mục đích mua, loại căn, ngân sách, mức độ quan tâm) rồi forward cho CVTV. Khác với transfer phàn nàn.

**Đề xuất thêm vào prompt:**
```
Khi KH yêu cầu tư vấn trực tiếp / gọi lại:
  → Thu thập thông tin trước khi chuyển:
    1. Tên + SĐT (bắt buộc)
    2. Dự án quan tâm (nếu có)
    3. Mục đích: ở hay đầu tư
    4. Ngân sách dự kiến
    5. Thời gian thuận tiện để gọi lại
  → "Dạ, em đã ghi nhận ạ. Chuyên viên sẽ liên hệ lại
     vào [thời gian] để tư vấn chi tiết cho Quý Khách ạ."
```

### Nhóm 4 — SAU MUA (5 intents)

| Intent | Mô tả | Voice Agent | GAP |
|--------|--------|------------|-----|
| AFT_DELIVERY | Tiến độ bàn giao | ⚠️ noble_search có thể tìm, nhưng cần mã căn để chính xác | Cần clarify |
| AFT_COMPLAINT | Khiếu nại | ✅ Transfer rule 2 (phàn nàn) + XIN LỖI section | — |
| AFT_MAINTENANCE | Bảo trì/sửa chữa | ❌ KHÔNG CÓ | **THIẾU** — voice nên nhận diện + transfer |
| AFT_PROCEDURE | Thủ tục sau mua | ⚠️ FAQ có 1 số thông tin | Cần nhận diện |
| AFT_CONTRACT_INFO | Tra cứu hợp đồng | ✅ Transfer rule 6 (cần CCCD + mã căn) | — |

**GAP cụ thể:**

**AFT_MAINTENANCE — thiếu hoàn toàn**

Scenarios: *"Sự cố khẩn cấp (ngập, cháy) → escalate NGAY + gọi hotline kỹ thuật song song"*. Voice agent không nhận diện intent này.

**Đề xuất thêm vào CHUYỂN CHUYÊN VIÊN:**
```
Transfer NGAY — sự cố khẩn cấp:
  Khi KH báo ngập nước, cháy, mất điện toàn tòa, sự cố an ninh:
    → Transfer NGAY + báo hotline kỹ thuật.
    → "Dạ, em ghi nhận sự cố ạ. Em chuyển Quý Khách tới bộ phận kỹ thuật ngay ạ."

Transfer + ghi nhận — bảo trì thông thường:
  Khi KH yêu cầu sửa chữa, bảo trì trong thời hạn bảo hành:
    → Thu thập: mã căn, mô tả sự cố, mức độ khẩn cấp.
    → "Dạ, em đã ghi nhận yêu cầu bảo trì ạ. Bộ phận kỹ thuật sẽ liên hệ
       trong vòng [X] ngày ạ."
```

### Nhóm 5 — HỆ THỐNG (6 intents)

| Intent | Mô tả | Voice Agent | GAP |
|--------|--------|------------|-----|
| SYS_GREETING | Chào hỏi | ✅ GREETING section + auto-greet | — |
| SYS_UNCLEAR_NEED | KH không rõ nhu cầu | ⚠️ XỬ LÝ ĐẶC BIỆT có nhưng thiếu gợi ý 4 nhóm | Cần sửa |
| SYS_OUT_OF_SCOPE | Ngoài phạm vi | ⚠️ OFF-TOPIC xử lý chung, không phân biệt BĐS khác vs hoàn toàn off-topic | Cần tách |
| SYS_NO_RESPONSE | KH không phản hồi | ❌ KHÔNG CÓ | **THIẾU** — cần timeout logic |
| SYS_REQUEST_HUMAN | Yêu cầu người thật | ✅ Transfer rule 1 | — |
| SYS_END_CHAT | Kết thúc chat | ✅ FAREWELL section | — |

**GAP cụ thể:**

**SYS_NO_RESPONSE — thiếu timeout xử lý**

Scenarios: *"30 phút: nhắc nhẹ. 60 phút: kết thúc + thông tin liên hệ (App NobleX, hotline 18006298, email)"*. Voice agent không có timeout logic.

Với **voice**: timeout ngắn hơn chat (KH không nói 30s-1 phút = có thể đã disconnect). Không cần 30/60 phút như chat.

**Đề xuất cho voice:**
```
Nếu KH im lặng sau khi agent trả lời (>30s không có STT transcript):
  → Nhắc nhẹ 1 lần: "Dạ, Quý Khách vẫn còn ở đây không ạ?"
  → Im lặng thêm 30s → "Dạ, em cảm ơn Quý Khách đã liên hệ Noble ạ.
     Khi cần hỗ trợ, Quý Khách gọi lại bất cứ lúc nào ạ."
```
(Cần thêm code: silence timer trong session.py)

**SYS_OUT_OF_SCOPE — phân biệt BĐS khác vs hoàn toàn off-topic**

Đã phân tích ở phần trước. Scenarios phân biệt rõ:
- BĐS ngoài Noble → gợi ý DA Noble tương tự (proactive)
- Hoàn toàn off-topic → từ chối nhẹ

### Escalation Rules — 10 rules

| Rule | Mô tả | Voice Agent | GAP |
|------|--------|------------|-----|
| 1. Clarify 2 lần không rõ | Transfer | ⚠️ Prompt thiếu rule này | Cần thêm |
| 2. KH yêu cầu người thật | Transfer ngay | ✅ Rule 1 | — |
| 3. Pháp lý phức tạp | Transfer phòng pháp lý | ✅ Đã fix: search trước, transfer nếu không có | — |
| 4. Khiếu nại | Transfer CSKH | ✅ Rule 2 + XIN LỖI | — |
| 5. Sự cố khẩn cấp | Transfer KỸ THUẬT + hotline | ❌ THIẾU | **Cần thêm** |
| 6. Yêu cầu cam kết bằng văn bản | Transfer quản lý | ❌ THIẾU | Cần thêm |
| 7. Điều chỉnh hợp đồng/phí | Transfer HĐ/kế toán | ✅ Rule 7 | — |
| 8. Đe dọa kiện/truyền thông | Transfer NGAY quản lý + pháp lý | ❌ THIẾU | **Cần thêm** |
| 9. Booking căn đã bán | Gợi ý căn khác hoặc transfer | ❌ THIẾU | Cần nhận diện |
| 10. Ngoài giờ làm việc | Ghi nhận + hẹn gọi lại | ❌ THIẾU | Cần xử lý |

**GAP đáng chú ý:**

**Rule 5: Sự cố khẩn cấp** — đã phân tích ở AFT_MAINTENANCE.

**Rule 6: Yêu cầu cam kết bằng văn bản**

Scenarios: *"KH yêu cầu CĐT cam kết bằng văn bản (giá, tiến độ, chất lượng) → transfer quản lý kinh doanh"*. Voice agent không nhận diện.

**Đề xuất thêm:**
```
Khi KH yêu cầu cam kết bằng văn bản hoặc xác nhận chính thức:
  → "Dạ, yêu cầu này em cần chuyển tới chuyên viên có thẩm quyền ạ."
  → Transfer
```

**Rule 8: Đe dọa kiện/truyền thông**

Scenarios: *"Transfer NGAY tới quản lý + pháp lý. KHÔNG tranh luận."*

**Đề xuất thêm vào "Transfer NGAY":**
```
  3. Khách đe dọa kiện tụng hoặc phản ánh truyền thông:
     "kiện", "báo chí", "lên mạng", "tòa án"
     → Xin lỗi, KHÔNG tranh luận, transfer NGAY.
```

**Rule 10: Ngoài giờ làm việc**

Voice agent chạy 24/7 nhưng chuyên viên chỉ trực giờ hành chính. Khi cần transfer ngoài giờ → không có ai.

**Đề xuất thêm:**
```
Khi cần transfer nhưng ngoài giờ làm việc (trước 8h hoặc sau 18h):
  → "Dạ, hiện đã ngoài giờ làm việc ạ. Em ghi nhận yêu cầu của Quý Khách.
     Chuyên viên sẽ liên hệ lại vào giờ hành chính ngày tiếp theo ạ."
  → Thu thập: tên, SĐT, nhu cầu tóm tắt, thời gian thuận tiện.
```
(Cần config giờ làm việc trong settings hoặc hardcode)

### Tone Guidelines — 5 Tone codes

| Tone | Khi nào | Voice Agent hiện tại | GAP |
|------|---------|---------------------|-----|
| T1 Nhiệt tình | Thông tin DA, KH mới | ✅ "giọng ấm áp" trong PERSONA | Chưa enforce chủ động gợi ý |
| T2 Tự tin | Giá, chính sách, pháp lý | ⚠️ Không phân biệt tone theo topic | Thiếu |
| T3 Chuyên nghiệp | Booking, thu thập info | ✅ ĐẶT LỊCH section chuẩn | — |
| T4 Đồng cảm | Khiếu nại, sự cố | ✅ XIN LỖI & ĐỒNG CẢM section | — |
| T5 Nhẹ nhàng | Greeting, farewell, mơ hồ | ✅ GREETING + FAREWELL | — |

**GAP:** Voice agent dùng **1 tone duy nhất** cho tất cả. Scenarios yêu cầu **chuyển tone theo context** (T1→T2 khi chuyển từ info sang giá). Với single-prompt agent, đây khó enforce — LLM cần instruction cụ thể.

**Đề xuất thêm vào PERSONA:**
```
- TONE: Điều chỉnh giọng điệu theo nội dung:
  + Thông tin dự án → nhiệt tình, chủ động gợi ý thêm.
  + Giá, chính sách, pháp lý → tự tin, dùng con số cụ thể, tạo yên tâm.
  + Booking, thu thập info → chuyên nghiệp, dẫn dắt từng bước.
  + Khiếu nại, sự cố → đồng cảm, xin lỗi TRƯỚC rồi hỏi chi tiết.
  + Chào hỏi, kết thúc → nhẹ nhàng, không gây áp lực.
```

---

## 3. Subagent Skills vs Scenarios

### Mapping Skills ↔ Nhóm

| Nhóm Scenarios | Subagent Skill | Coverage |
|----------------|---------------|----------|
| Nhóm 1 (DA info) | noble-advisor | ✅ 8/8 intents |
| Nhóm 2 (Giá & CS) | noble-advisor | ✅ 7/7 intents |
| Nhóm 3 Booking | visit-scheduling | ⚠️ 1/4 (chỉ BKG_VISIT) |
| Nhóm 3 (BKG_BOOKING, DEPOSIT) | human-transfer | Đúng (quá phức tạp cho bot) |
| Nhóm 3 (BKG_CONSULT_REQUEST) | ❌ Không có skill riêng | GAP |
| Nhóm 4 Sau mua | human-transfer (phần lớn) | ⚠️ Thiếu nhận diện AFT_MAINTENANCE |
| Nhóm 5 Hệ thống | luna-general | ✅ 5/6 (thiếu SYS_NO_RESPONSE) |

### Subagent thiếu gì

1. **BKG_CONSULT_REQUEST** — không có skill riêng, bị gộp vào transfer. Nên có flow thu thập nhu cầu chi tiết trước khi chuyển.

2. **AFT_MAINTENANCE** — human-transfer skill nhắc "bảo trì" nhưng không phân biệt **khẩn cấp** (ngập, cháy) vs **thường** (rò nước, hỏng khóa).

3. **SYS_NO_RESPONSE timeout** — luna-general không có logic timeout. Cần ở orchestrator level.

4. **Tone switching** — Subagent skill files có tone guidance trong SKILL.md nhưng mỗi agent chỉ dùng 1 tone. Khi advisor trả lời pháp lý (T2) vs thông tin (T1), tone không thay đổi.

---

## 4. Chi tiết thay đổi cần thiết

### A. Thay đổi trong `prompts/system_prompt.txt`

#### A1. GREETING — thêm gợi ý nhu cầu

```
HIỆN TẠI:
  "Dạ, em là Luna, Chuyên viên tư vấn Noble ạ.
   Em có thể giúp gì cho Quý Khách ạ?"

ĐỔI THÀNH:
  "Dạ, em là Luna, Chuyên viên tư vấn Noble ạ.
   Quý Khách muốn tìm hiểu dự án, xem giá, hay đặt lịch tham quan ạ?"
```

#### A2. LUỒNG TƯ VẤN — thêm gợi ý sau chốt DA + rule so sánh

```
THÊM sau Bước 1:
  Sau khi chốt project_filter, nếu KH chưa hỏi cụ thể:
    → "Dạ, Quý Khách muốn em giới thiệu tổng quan, tìm hiểu bảng giá,
       hay đặt lịch tham quan ạ?"

THÊM sau Bước 3 (so sánh):
  Khi KH so sánh dự án:
    → Trả lời khách quan, nêu ưu/nhược.
    → LUÔN kết thúc bằng gợi ý dựa trên nhu cầu KH đã nêu.

THÊM rule đầu tư:
  Khi KH hỏi về đầu tư, lợi nhuận:
    → KHÔNG BAO GIỜ cam kết lợi nhuận hay tỷ suất cụ thể.
    → Chỉ chia sẻ dữ liệu tham khảo.
```

#### A3. CHUYỂN CHUYÊN VIÊN — thêm 4 rules

```
THÊM vào "Transfer NGAY":
  3. Khách đe dọa kiện/truyền thông → KHÔNG tranh luận, transfer NGAY.

THÊM vào "Transfer + ghi nhận":
  9. Sự cố khẩn cấp (ngập, cháy, mất điện): transfer bộ phận kỹ thuật NGAY.
  10. Yêu cầu cam kết bằng văn bản: transfer quản lý kinh doanh.
  11. Booking giữ chỗ / đặt cọc (cần CCCD, mã căn): transfer chuyên viên.
  12. Clarify 2 lần KH vẫn mơ hồ: transfer kèm context.
  13. Ngoài giờ làm việc: ghi nhận + hẹn liên hệ giờ hành chính.
```

#### A4. OFF-TOPIC — tách BĐS ngoài Noble vs hoàn toàn off-topic

```
THÊM section mới:
  ═══ KH HỎI SẢN PHẨM NGOÀI NOBLE ═══
  Khi KH hỏi BĐS khác CĐT (Vinhomes, Ecopark, đất nền...):
    → KHÔNG nói "em không nắm rõ" (đây vẫn là BĐS).
    → "Dạ, hiện NobleX chưa có [SP] ạ. Tuy nhiên bên em có dự án
       tương tự. Quý Khách có muốn tìm hiểu không ạ?"
    → KH đồng ý → chuyển flow DA gợi ý.
    → KH từ chối → kết thúc lịch sự.

OFF-TOPIC chỉ cho: thời tiết, crypto, bóng đá, chính trị, v.v.
```

#### A5. XỬ LÝ ĐẶC BIỆT — sửa/thêm 4 rules

```
SỬA "nhiều câu hỏi":
  → "Dạ, em ghi nhận Quý Khách có [N] câu hỏi ạ.
     Em xin phép hỗ trợ lần lượt ạ."
  → Xử lý từng vấn đề, thông báo khi chuyển.

THÊM "ngôn ngữ":
  → Nếu KH nói ngoại ngữ: nhắc tiếng Việt.
  → Tiếp tục ngoại ngữ → transfer.

THÊM "tư vấn trực tiếp":
  → KH yêu cầu gọi lại / tư vấn riêng:
    Thu thập: tên, SĐT, DA, mục đích, ngân sách, thời gian thuận tiện.
    → Ghi nhận + chuyển CVTV.

THÊM "giá tham khảo vs giá chính xác":
  → FAQ có giá tham khảo → chia sẻ kèm disclaimer.
  → Giá cụ thể từng căn → transfer.
```

#### A6. PERSONA — thêm tone guidance + rule pháp lý

```
THÊM:
  - TONE: Điều chỉnh giọng theo nội dung:
    + Thông tin DA → nhiệt tình, chủ động gợi ý.
    + Giá, pháp lý → tự tin, số liệu cụ thể.
    + Booking → chuyên nghiệp, dẫn dắt.
    + Khiếu nại → đồng cảm, xin lỗi trước.
    + Greeting/farewell → nhẹ nhàng.

  - Pháp lý: CHỈ cung cấp từ kết quả search. KHÔNG suy luận thêm.
  - Đầu tư: KHÔNG cam kết lợi nhuận.
  - LUÔN trả lời bằng tiếng Việt.
```

### B. Thay đổi trong code (future — không cần ngay)

| Thay đổi | File | Mô tả |
|----------|------|-------|
| Silence timeout | `src/server/session.py` | Timer 30s sau agent response, nhắc 1 lần, 30s nữa → farewell |
| Working hours check | `src/server/ws_handler.py` | Check giờ trước khi transfer, nếu ngoài giờ → ghi nhận |
| Greeting gợi ý | `src/agent/voice.py` | Sửa `build_greeting()` thêm gợi ý nhu cầu |

### C. Thay đổi trong Subagent Skills (nếu adopt)

| Skill | Thay đổi |
|-------|----------|
| noble-advisor | Thêm: rule so sánh luôn kết bằng gợi ý, rule không cam kết lợi nhuận, tone switching T1↔T2 |
| visit-scheduling | Thêm: nhận diện BKG_BOOKING/DEPOSIT → redirect transfer thay vì xử lý |
| human-transfer | Thêm: phân biệt sự cố khẩn cấp vs thường, rule đe dọa kiện, cam kết văn bản, ngoài giờ |
| luna-general | Thêm: tách BĐS ngoài Noble vs off-topic, timeout logic, ngôn ngữ |

---

## 5. Flow tổng thể sau khi áp dụng

```
KH kết nối
  ↓
Auto-greeting:
  Có info → "Dạ em chào anh Hùng ạ, em là Luna... Em có thể giúp gì cho anh ạ?"
  Không info → "Dạ, em là Luna... Quý Khách muốn tìm hiểu dự án,
                xem giá, hay đặt lịch tham quan ạ?"
  ↓
KH phản hồi
  │
  ├─ [MƠ HỒ] "Ừ", "ok", "tìm hiểu"
  │   → Clarify 1: Hỏi khu vực/DA
  │   → Clarify 2: Hỏi nhu cầu cụ thể (tổng quan / giá / đặt lịch)
  │   → Vẫn mơ hồ → Transfer kèm context
  │
  ├─ [THÔNG TIN DA] "Crystal Long Biên có gì?"
  │   → noble_search → trả lời (Tone T1: nhiệt tình)
  │   → Gợi ý tiếp: "Quý Khách muốn tìm hiểu thêm gì ạ?"
  │
  ├─ [GIÁ] "Giá bao nhiêu?"
  │   → noble_search → giá tham khảo + disclaimer (Tone T2: tự tin)
  │   → Giá cụ thể căn → transfer
  │
  ├─ [PHÁP LÝ] "Người nước ngoài mua được không?"
  │   → noble_search → FAQ có → trả lời (Tone T2)
  │   → FAQ không có → transfer pháp lý
  │
  ├─ [ĐẦU TƯ] "Có nên mua đầu tư không?"
  │   → Tư vấn từ data, KHÔNG cam kết lợi nhuận
  │
  ├─ [SO SÁNH] "Crystal vs Palace Long Biên?"
  │   → Search cả 2 → so sánh khách quan → KẾT THÚC bằng gợi ý
  │
  ├─ [BOOKING XEM NHÀ] "Đặt lịch tham quan"
  │   → Thu thập 5 field → xác nhận → schedule_viewing (Tone T3)
  │
  ├─ [BOOKING GIỮ CHỖ / ĐẶT CỌC] "Booking căn A1201"
  │   → "Dạ, booking giữ chỗ cần xác thực giấy tờ ạ.
  │      Em chuyển Quý Khách tới chuyên viên ạ."
  │   → Transfer
  │
  ├─ [TƯ VẤN RIÊNG] "Gọi lại cho tôi"
  │   → Thu thập: tên, SĐT, DA, mục đích, ngân sách, thời gian
  │   → "Chuyên viên sẽ liên hệ lại vào [giờ] ạ."
  │
  ├─ [BĐS NGOÀI NOBLE] "Dự án Vinhomes Grand Park?"
  │   → "Dạ, NobleX chưa có SP đó ạ. Bên em có DA tương tự..."
  │   → Gợi ý DA Noble
  │
  ├─ [KHIẾU NẠI] "Bàn giao muộn quá!"
  │   → Xin lỗi TRƯỚC (Tone T4) → hỏi chi tiết → transfer CSKH
  │
  ├─ [SỰ CỐ KHẨN CẤP] "Nhà tôi bị ngập!"
  │   → Transfer KỸ THUẬT NGAY
  │
  ├─ [ĐE DỌA] "Tôi sẽ kiện!"
  │   → Xin lỗi, KHÔNG tranh luận, transfer NGAY quản lý
  │
  ├─ [NGOẠI NGỮ] "I want to buy a house"
  │   → "Dạ, em hỗ trợ bằng tiếng Việt ạ..."
  │   → Tiếp tục ngoại ngữ → transfer
  │
  ├─ [NHIỀU CÂU HỎI] "Giá DA X, rồi đặt lịch, rồi hỏi pháp lý"
  │   → "Dạ, em ghi nhận 3 câu hỏi ạ. Em hỗ trợ lần lượt ạ."
  │
  ├─ [OFF-TOPIC] "Thời tiết hôm nay thế nào?"
  │   → Từ chối nhẹ + gợi ý Noble
  │
  ├─ [IM LẶNG 30s]
  │   → "Dạ, Quý Khách vẫn ở đây không ạ?"
  │   → Im thêm 30s → Farewell
  │
  └─ [KẾT THÚC] "Cảm ơn, không cần nữa"
      → "Dạ, cảm ơn Quý Khách đã liên hệ Noble ạ.
         Chúc Quý Khách một ngày tốt lành ạ!" (Tone T5)
```
