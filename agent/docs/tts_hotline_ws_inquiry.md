# Inquiry Spec — Tích hợp TTS WebSocket API vào Noble Voice Agent

**Endpoint đang xét:** `ws://10.50.12.62:8066/tts/ws`

**Bối cảnh:** client là voice agent realtime, stream từng *clause* (mệnh đề) một, cần
barge-in (cắt khi khách nói). Mỗi clause là 1 yêu cầu synth riêng, phát ngay khi có
audio. Adapter/voice đã khóa sẵn server-side: `sts_luna_v3` + giọng `luna`.

> Các câu **🔴 NHÓM 1** là quan trọng nhất — thiếu là không tích hợp đúng được.

---

## 🔴 NHÓM 1 — Bắt buộc

### 1.1. Tín hiệu KẾT THÚC một lần synth là gì?
Spec chỉ mô tả `{"event":"start", ...}` ở đầu, nhưng **không thấy event báo hết**.
Client cần biết chính xác khi nào một câu đã đọc xong để chuyển sang câu kế. Sau khi
gửi hết binary PCM, server sẽ:
- (a) Gửi một control frame kết thúc? Nếu có, **chính xác JSON đó là gì?**
  (vd `{"event":"end"}`, `{"event":"eos"}`, `{"event":"done"}`…), hay
- (b) Tự **đóng WebSocket** (close frame, mã bao nhiêu)? hay
- (c) Không có gì cả (client tự đoán qua timeout)?

> Đây là câu quan trọng nhất. Nếu không có tín hiệu end rõ ràng, pipeline prefetch
> của chúng tôi sẽ bị treo giữa các câu.

### 1.2. Mô hình kết nối: 1 WS cho mỗi câu, hay 1 WS dùng suốt cuộc gọi?
- Sau khi `synth` xong, WS **còn mở** để gửi `synth` tiếp theo, hay phải mở WS mới mỗi câu?
- Nếu dùng lại được: gửi `{"cmd":"synth"}` mới khi câu cũ **đã xong** có được không, hay
  chỉ được gửi khi đang đọc dở (để auto-hủy)?

> Ảnh hưởng lớn tới latency: giữ 1 WS suốt cuộc gọi tiết kiệm ~1 handshake mỗi câu.

### 1.3. Barge-in — hành vi của `{"cmd":"stop"}`
- Sau khi client gửi `{"cmd":"stop"}`, server có gửi thêm binary/event nào nữa không,
  hay dừng ngay lập tức?
- Sau `stop`, **WS còn dùng được** để gửi `synth` kế tiếp không, hay bị đóng?
- Nếu client **đóng thẳng WS** (không gửi `stop`) thì server có tự dừng synth và giải
  phóng tài nguyên đúng cách không?

> Chúng tôi cần cắt audio trong <50ms khi khách bắt đầu nói.

---

## 🟠 NHÓM 2 — Định dạng & giao thức

### 2.1. Audio frames
- Binary PCM là `pcm_s16le, 24000 Hz, mono` cố định (như `event:start` báo) hay có thể
  đổi theo request?
- Kích thước mỗi binary chunk cố định hay thay đổi?
- Có bao giờ 24000 đổi sang giá trị khác không? (client đang giả định 24 kHz).

### 2.2. Toàn bộ danh mục message Server → Client
Ngoài `start`, liệt kê **tất cả** các event JSON có thể gửi (end, error, warning,
metrics…) kèm schema từng loại.

### 2.3. Toàn bộ message Client → Server
Xác nhận đúng danh sách: `synth`, `stop`. Có `ping` / `keepalive` / `flush` nào không?

---

## 🟡 NHÓM 3 — Auth, giới hạn, độ bền

### 3.1. Xác thực
WS này có cần header auth (Bearer token / API key / query param) không, hay chỉ chặn
theo LAN? (client hiện hỗ trợ gửi `Authorization: Bearer <token>`).

### 3.2. Đồng thời (concurrency)
Server chịu được bao nhiêu cuộc gọi đồng thời? Có giới hạn số WS / số synth song song
không? Vượt ngưỡng thì báo lỗi thế nào?

### 3.3. Timeout & keepalive
- Server đóng WS sau bao lâu không hoạt động (idle timeout)?
- Có yêu cầu ping-interval từ client không? (client mặc định ping mỗi 20s).

### 3.4. Xử lý lỗi
Khi text lỗi / rỗng / quá dài, hoặc synth thất bại — server gửi gì? (event error có
`code` / `message`?) và có đóng WS không?

### 3.5. Độ dài text
Giới hạn ký tự mỗi `synth` là bao nhiêu? (chúng tôi gửi từng mệnh đề ngắn
~30–160 ký tự).

---

## 🟢 NHÓM 4 — Xử lý text (chất lượng đọc)

### 4.1. Chuẩn hóa text
Server tự xử lý số / ngày / đơn vị / ký hiệu (vd "24000" → "hai mươi bốn nghìn", "m2",
"%") hay client phải chuẩn hóa trước?

### 4.2. Markdown / emoji
Nếu text lọt ký tự markdown (`**`, `#`), emoji, hay tag `[warmly]`… server có tự lọc
không, hay client phải làm sạch trước khi gửi?

### 4.3. Tham số tùy chọn
`voice`, `adapter`, `temperature`, `top_p`, `max_new`, `rep_penalty` — giá trị mặc định
server đang khóa (`sts_luna_v3` + `luna`) là gì, và **có nên để client bỏ qua hoàn toàn**
các field này không? (spec nói voice/adapter đã khóa server-side).

---

## Ví dụ 1 lượt trao đổi mong muốn (nhờ team xác nhận / sửa cho đúng thực tế)

```
Client → {"cmd":"synth","text":"Xin chào anh."}
Server → {"event":"start","sr":24000,"format":"pcm_s16le","channels":1,"adapter":"sts_luna_v3","voice":"luna"}
Server → <binary PCM chunk>
Server → <binary PCM chunk>
...
Server → ???              ← (1.1) frame kết thúc là gì? hay đóng WS?

--- barge-in giữa chừng ---
Client → {"cmd":"stop"}
Server → ???              ← (1.3) còn gửi gì nữa không? WS còn sống không?
```

---

**Ưu tiên trả lời:** 1.1 → 1.2 → 1.3 trước, phần còn lại giúp tối ưu latency & độ bền.
