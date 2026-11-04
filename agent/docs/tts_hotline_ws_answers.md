# Trả lời Inquiry — Tích hợp TTS WebSocket vào Noble Voice Agent

**Endpoint:** `ws://10.50.12.62:8066/tts/ws` · Server: `serve/tts_api.py` (aiohttp).
**Đã khóa server-side:** adapter `sts_luna_v3` + giọng `luna`.
**Audio ra:** PCM 16-bit LE, **24000 Hz, mono**, raw (không WAV header).

> Ghi chú: hợp đồng WS đã được chỉnh để phục vụ đúng mô hình clause-streaming + barge-in.
> Điểm mới quan trọng: **1 event kết thúc duy nhất `end`**, có **`id`** đối chiếu, và **hàng đợi synth FIFO** (prefetch được, không tự hủy nhầm).

---

## 🔴 NHÓM 1 — Bắt buộc

### 1.1. Tín hiệu KẾT THÚC một lần synth
**(a) — có control frame kết thúc, và LUÔN là `event:"end"`.** Sau khi gửi hết binary PCM, server gửi **đúng một** message TEXT:

```json
{"event":"end","id":"<id-bạn-gửi>","reason":"complete"}                 // đọc hết bình thường
{"event":"end","id":"<id>","reason":"stopped"}                          // bị stop cắt
{"event":"end","id":"<id>","reason":"error","error":"<mô tả>"}          // lỗi
```

- Client chỉ cần chờ `event == "end"` → biết lượt đã xong (đọc `reason` để biết vì sao).
- WebSocket **KHÔNG đóng** sau `end` — dùng tiếp cho câu sau.
- `id` = đúng giá trị bạn gửi trong `synth` (xem 1.2) → ghép request↔response an toàn khi pipeline.

→ Pipeline prefetch của bạn chờ `end` là chuẩn, không bị treo.

### 1.2. Mô hình kết nối
**1 WebSocket dùng suốt cuộc gọi** (khuyến nghị) — không cần mở lại mỗi câu.

- Sau khi 1 câu xong (`end`), WS còn mở → gửi `synth` tiếp.
- Gửi **nhiều `synth` liên tiếp** (kể cả khi câu trước chưa đọc xong) → server **xếp hàng FIFO**, đọc lần lượt. KHÔNG tự hủy câu trước. → **prefetch thoải mái**.
- Mỗi `synth` nên kèm `id` để đối chiếu:
  ```json
  {"cmd":"synth","id":"clause-7","text":"..."}
  ```
  `id` là chuỗi bất kỳ do bạn đặt (mặc định `null` nếu không gửi).

→ Giữ 1 WS suốt cuộc gọi, tiết kiệm handshake mỗi câu như bạn mong muốn.

### 1.3. Barge-in — `{"cmd":"stop"}`
Hành vi hiện tại khi nhận `stop`:

1. **Cắt câu đang đọc NGAY**: server ngừng gửi binary còn lại (bỏ, không phát nốt) trong ~1 vòng event-loop. Câu đang đọc kết thúc bằng `{"event":"end","reason":"stopped"}`.
2. **Xóa toàn bộ câu đang chờ trong hàng đợi** (các `synth` đã prefetch nhưng chưa bắt đầu). Lưu ý: các câu này **chưa từng gửi `start`** nên cũng **không có `end`** — coi như hủy im lặng. Client nên xem `stop` = huỷ tất cả outstanding.
3. **WS vẫn mở** — gửi `synth` mới tiếp tục bình thường.
4. **Nếu client đóng thẳng WS** (không gửi `stop`): server phát hiện, tự set cờ dừng, xóa hàng đợi, dừng thread sinh và giải phóng tài nguyên đúng cách.

> ⚠️ **Về mục tiêu cắt <50ms — đọc kỹ:** TTS sinh **nhanh hơn realtime nhiều** (RTF ~0.15). Khi bạn nhận được audio, phần lớn/toàn bộ câu **đã nằm trong buffer phía client**. `stop` chỉ chặn phần server CHƯA gửi.
> **Tiếng bot mà khách nghe = do client đang phát buffer.** Để cắt <50ms thật sự, **client PHẢI: (1) dừng playback + xóa buffer audio cục bộ ngay khi VAD fire, (2) gửi `stop` cho server (để dừng sinh phần còn lại + xóa queue).** Chỉ dựa vào server-stop sẽ KHÔNG cắt được tiếng đang phát.
> Nếu muốn server chủ động hơn (phát PCM theo đúng nhịp realtime để `stop` server cắt ăn ngay), chúng tôi có thể bật **chế độ throttle** — hiện chưa bật. Báo nếu cần.

---

## 🟠 NHÓM 2 — Định dạng & giao thức

### 2.1. Audio frames
- **Cố định** `pcm_s16le, 24000 Hz, mono` cho mọi request. Không đổi theo request.
- Kích thước mỗi binary chunk **thay đổi**: mỗi chunk ≈ 1 cửa sổ `WINDOW≈20` token (vài trăm ms); chunk cuối của mỗi câu có thể ngắn hơn. Client KHÔNG nên giả định chunk size cố định — cứ nối byte liên tục.
- 24000 Hz **hiện cố định** (do model/codec). Chỉ đổi nếu ta đổi model — sẽ báo trước và `event:start` luôn khai báo `sr` để client đọc động thay vì hardcode.

### 2.2. Danh mục message Server → Client (đầy đủ)
| Loại | Schema | Ghi chú |
|---|---|---|
| TEXT `start` | `{"event":"start","id",​"sr":24000,"format":"pcm_s16le","channels":1,"adapter","voice"}` | 1 lần, mở đầu mỗi lượt synth |
| BINARY | raw PCM16 LE 24k mono | nhiều frame, audio |
| TEXT `end` | `{"event":"end","id","reason":"complete"|"stopped"|"error"[,"error":"..."]}` | **đúng 1 lần**, kết thúc lượt |
| TEXT `error` | `{"event":"error","error":"..."}` | **lỗi mức giao thức** (JSON sai / cmd lạ), KHÔNG gắn với lượt synth, WS vẫn mở |

Không có event metrics/warning. (Cần thì bổ sung được.)

### 2.3. Message Client → Server (đầy đủ)
Chỉ **2** lệnh: `synth`, `stop`. Không có `ping`/`keepalive`/`flush` ở tầng ứng dụng — keepalive do WebSocket lo (xem 3.3).

---

## 🟡 NHÓM 3 — Auth, giới hạn, độ bền

### 3.1. Xác thực
**Hiện KHÔNG có auth** — chỉ chặn theo LAN. Chưa đọc header `Authorization`. Nếu team cần Bearer token / API-key (query param hoặc header), báo — thêm nhanh (khuyến nghị nên có nếu ra ngoài LAN tin cậy).

### 3.2. Đồng thời (concurrency) — ⚠️ QUAN TRỌNG
- **Chỉ 1 GPU + khóa tuần tự (`_gpu_lock`)** → mọi lượt synth chạy **tuần tự trên toàn server**, kể cả từ nhiều WS/cuộc gọi khác nhau. **KHÔNG synth song song thật.**
- Không giới hạn cứng số WS kết nối, nhưng nếu N cuộc gọi cùng xin synth → chúng **xếp hàng**, độ trễ cộng dồn.
- **Hệ quả cho hotline nhiều line:** đây là nút cổ chai. 1 máy GPU này phù hợp cho **ít cuộc gọi đồng thời**. Muốn nhiều line song song cần: nhiều GPU / nhiều instance + load-balancer, hoặc batching. Cần bàn nếu tải cao.
- Vượt tải hiện KHÔNG trả lỗi riêng — chỉ chậm dần (xếp hàng).

### 3.3. Timeout & keepalive
- Server bật WebSocket **heartbeat 20s** (tự ping/pong ở tầng protocol) → giữ kết nối sống; không có idle-timeout chủ động ngoài việc phát hiện kết nối chết qua heartbeat.
- Client ping mỗi 20s **không sao** (trùng khớp). Không bắt buộc client phải ping.

### 3.4. Xử lý lỗi
- Lỗi trong 1 lượt synth (text rỗng, adapter lạ, synth fail) → `{"event":"end","reason":"error","error":"<mô tả>"}` cho lượt đó; **WS vẫn mở**.
- Lỗi giao thức (JSON sai, cmd lạ) → `{"event":"error","error":"<mô tả>"}`; **WS vẫn mở**.
- Hiện **chưa có field `code`** (chỉ `error` dạng text). Cần mã lỗi máy-đọc-được thì báo, thêm `code`.

### 3.5. Độ dài text
- **Không giới hạn ký tự cứng.** Text dài được **tự tách câu** và đọc nối; mỗi câu trần `max_new≈1200` token (rất dài mới chạm).
- Clause 30–160 ký tự như bạn gửi là **lý tưởng** (TTFB thấp, barge-in mượt). Khuyến nghị cứ gửi theo clause.

---

## 🟢 NHÓM 4 — Xử lý text (chất lượng đọc)

### 4.1. Chuẩn hóa text
**Server tự chuẩn hóa hoàn toàn** (module `core/text` → `datagen/normalize.py`): số → chữ ("24000" → "hai mươi bốn nghìn"), `%`, `m2/m²`, ngày `15/10/2025`, giờ `9h30`, tiền `18.000đ`, SĐT (đọc từng số), thập phân, mã căn/hợp đồng, số La Mã ngữ cảnh…
→ **Client KHÔNG cần chuẩn hóa số/đơn vị.** Cứ gửi text tự nhiên.

### 4.2. Markdown / emoji
Server tự lọc: URL, ảnh/link markdown `![]()`/`[]()`, code block/inline, token template `<|...|>`, field `snake_case`, tag cảm xúc `[warmly]`, và hầu hết ký tự đặc biệt (`* # @ | ~ ^ & [] {} <>` …).
- `**đậm**`, `#` → ký tự markup bị loại, giữ nội dung.
- ⚠️ **Emoji KHÔNG được lọc chắc chắn** → nếu text có thể chứa emoji, **client nên strip emoji trước khi gửi** cho an toàn (tránh phonemize ra âm lạ).

### 4.3. Tham số tùy chọn
- Mặc định đã khóa server: `adapter=sts_luna_v3`, `voice=luna`, `temperature=0.9`, `top_p=0.9`, `max_new=1200`, `rep_penalty=1.3`.
- **Nên để client BỎ QUA hoàn toàn** `voice`/`adapter` (dùng mặc định đã khóa). Chỉ gửi `text` (+ `id`).
- Các tham số sampling (`temperature`…) cũng nên bỏ trừ khi có lý do; mặc định đã tinh chỉnh.

---

## Ví dụ 1 lượt trao đổi (đã xác nhận đúng thực tế)

```
Client → {"cmd":"synth","id":"c1","text":"Xin chào anh."}
Server → {"event":"start","id":"c1","sr":24000,"format":"pcm_s16le","channels":1,"adapter":"sts_luna_v3","voice":"luna"}
Server → <binary PCM chunk>
Server → <binary PCM chunk> ...
Server → {"event":"end","id":"c1","reason":"complete"}      ← kết thúc lượt, WS VẪN MỞ

--- prefetch: gửi tiếp khi chưa cần chờ ---
Client → {"cmd":"synth","id":"c2","text":"Dạ căn hộ 85m2 giá 3.5 tỷ."}   (xếp hàng, đọc sau c1)

--- barge-in giữa chừng (khách nói) ---
Client → (client: DỪNG PLAYBACK + XÓA BUFFER cục bộ NGAY)   ← cắt tiếng khách nghe
Client → {"cmd":"stop"}
Server → {"event":"end","id":"c2","reason":"stopped"}        ← cho câu ĐANG đọc; các câu còn trong queue bị hủy im lặng
         (WS vẫn mở, gửi synth mới tiếp tục được)
```

---

## Tóm tắt hành động đề xuất cho team hotline
1. Mở **1 WS/cuộc gọi**, gắn `id` mỗi `synth`, chờ `event:"end"` để chuyển clause.
2. **Barge-in**: khi VAD fire → **dừng playback + xóa buffer cục bộ trước**, rồi gửi `{"cmd":"stop"}`.
3. **Resample 24k → 8k** phía client nếu telephony cần.
4. **Strip emoji** trước khi gửi (số/đơn vị/markdown thì không cần).
5. Lưu ý **concurrency**: server hiện tuần tự 1 GPU — thống nhất số line đồng thời tối đa, hoặc mở rộng hạ tầng nếu tải cao.

Cần bổ sung (báo là làm): **auth token**, **field `code` cho lỗi**, **chế độ throttle realtime**, **output 8kHz tùy chọn**.
