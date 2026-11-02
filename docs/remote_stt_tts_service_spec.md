# Spec — Chuẩn endpoint WebSocket cho STT / TTS Service (`remote`)

**Đối tượng:** đội vận hành hạ tầng STT/TTS.
**Mục tiêu:** refactor server STT & TTS của đội về đúng hợp đồng WebSocket mà backend
`remote` của Noble Voice Agent (worker) đang dùng, để chỉ cần đổi URL trong `.env` là
worker kết nối được, không sửa code worker.

Spec này là **hợp đồng bắt buộc** (source of truth = code client trong worker). Mọi field
tên, kiểu frame, sample rate, tín hiệu kết thúc phải khớp **chính xác**. Nếu muốn thêm
field mới (auth, error code…) thì bổ sung theo mục "Mở rộng tương thích" — không đổi cái đang có.

> ⚠️ **Đây KHÔNG phải protocol `{"event":"start"}` / `{"cmd":"synth"}`** trong
> `tts_hotline_ws_answers.md`. Chuẩn `remote` dùng khóa `"type"`, không có `start`
> frame, không có `id`, không có lệnh `stop` (barge-in = đóng WS). Đọc kỹ khác biệt ở
> mục 6.

---

## 0. Tóm tắt 1 phút

| | STT | TTS |
|---|---|---|
| Vai trò | worker **gửi** audio, nhận transcript | worker **gửi** text, nhận audio |
| Endpoint mặc định | `ws://<host>:8770/stt` | `ws://<host>:8771/tts` |
| Mô hình kết nối | **1 WS/phiên gọi** (dài) | **1 WS / mỗi lần synth (mỗi clause)** |
| Binary frame | client→server: PCM in | server→client: PCM out |
| PCM in/out | int16 LE, **16000 Hz**, mono | int16 LE, **24000 Hz**, mono |
| Text control | server→client: `partial`/`final` | client→server: `synthesize`; server→client: `end` |
| Kết thúc | client gửi `{"type":"eos"}` rồi đóng | server gửi `{"type":"end"}` |
| Barge-in / hủy | client đóng WS | client **đóng WS** (không có `stop`) |
| Auth | `Authorization: Bearer <token>` (tùy chọn) | như STT |

---

## 1. Quy ước chung (áp dụng cho cả 2 service)

- **Transport:** WebSocket (RFC 6455). Server nên chấp nhận `ping/pong` ở tầng protocol —
  client mở với `ping_interval=20s`.
- **Hai loại frame:**
  - **Binary frame** = PCM thô, `int16 little-endian, mono`, **không có WAV header**.
  - **Text frame** = một JSON object UTF-8, dùng làm control.
- **Khóa phân loại control luôn là `"type"`** (không phải `event`/`cmd`).
- **`max_size` khung:** ≥ 10 MB (client đặt `max_size=10*1024*1024`).
- **Kích thước chunk PCM:** tùy ý, thay đổi được. Bên nhận phải nối byte liên tục, **không**
  giả định chunk cố định.

### 1.1. Xác thực (tùy chọn, giống nhau cho cả 2)

- Nếu bật auth: client gửi HTTP header khi handshake:
  `Authorization: Bearer <token>`.
- Quy tắc server:
  - Token cấu hình rỗng ⇒ **tắt auth**, chấp nhận mọi kết nối (kể cả không có header).
  - Token cấu hình có giá trị ⇒ so khớp chính xác phần sau `Bearer `.
    - Khớp ⇒ chấp nhận.
    - Thiếu / sai ⇒ **đóng WS với close code `1008` ("unauthorized")** ngay khi handshake.
- Token là **cùng một giá trị** cho cả STT và TTS (`VOICE_SERVICE_AUTH_TOKEN` phía worker).

---

## 2. STT Service

### 2.1. Endpoint
- Đường dẫn mặc định: `ws://<host>:8770/stt` (worker cấu hình qua `STT_SERVICE_URL`,
  nhận URL đầy đủ — host/port/đường dẫn do đội đặt, chỉ cần báo lại để worker trỏ đúng).
- Server bind `0.0.0.0:8770` để máy khác kết nối được (port do đội chọn, báo lại là được).

### 2.2. Luồng
1. Worker mở WS (kèm header auth nếu có). **1 kết nối tồn tại suốt cả phiên/cuộc gọi.**
2. Worker **stream nhiều binary frame**: PCM `int16 LE, 16000 Hz, mono`.
3. Server chạy STT streaming, đẩy transcript về **bằng text frame** (mục 2.3).
4. Kết thúc phiên: worker gửi text frame `{"type":"eos"}` rồi đóng WS.
   Server nhận `eos` (hoặc thấy WS đóng) ⇒ dừng phiên, giải phóng tài nguyên.

> Server **chỉ gửi text frame**. Client bỏ qua mọi binary frame server gửi (đừng gửi binary về client).

### 2.3. Server → Client (text frames)

```json
{"type": "partial", "text": "<transcript tạm>"}   // giả thuyết trung gian, gửi nhiều lần
{"type": "final",   "text": "<transcript chốt>"}   // đoạn đã chốt (endpoint fired)
```

- `partial`: kết quả tạm, có thể thay đổi; gửi bao nhiêu lần tùy ý trong khi khách nói.
- `final`: một đoạn đã hoàn tất (VD sau khi phát hiện endpoint/khoảng lặng). Một phiên có
  thể có **nhiều `final`** (streaming liên tục, không phải một lần cuối cùng).
- **Không gửi `text` rỗng** cho tín hiệu điều khiển — client **bỏ qua frame có `text` rỗng**.
  Muốn báo hiệu gì khác phải dùng `type` khác (thỏa thuận thêm ở mục 7).

### 2.4. Client → Server

| Frame | Ý nghĩa |
|---|---|
| Binary (PCM 16k) | audio mic, gửi liên tục |
| `{"type":"eos"}` | hết audio phiên này; server dừng, sau đó client đóng WS |

Không có lệnh nào khác từ client trong luồng STT.

---

## 3. TTS Service

### 3.1. Endpoint
- Đường dẫn mặc định: `ws://<host>:8771/tts` (worker cấu hình qua `TTS_SERVICE_URL`).
- Server bind `0.0.0.0:8771`.

### 3.2. Luồng — **mỗi lần synth mở một WS mới**

> Điểm khác biệt lớn nhất so với protocol cũ của đội: **worker mở một WS riêng cho MỖI
> clause** (mệnh đề ngắn), gửi đúng **một** yêu cầu `synthesize`, nhận audio, rồi đóng.
> KHÔNG có mô hình "1 WS suốt cuộc gọi + hàng đợi FIFO + `id`". Không cần `id`, không cần queue.

1. Worker mở WS (kèm auth nếu có).
2. Worker gửi **một** text frame:
   ```json
   {"type": "synthesize", "text": "<clause cần đọc>", "voice": "<optional>"}
   ```
   - `text`: nội dung đọc (mệnh đề ngắn, ~30–160 ký tự).
   - `voice`: **tùy chọn**. Nếu có ⇒ server chọn giọng đó cho lần synth này. Worker gửi
     `VIENEU_VOICE_ID` nếu được cấu hình, ngược lại **bỏ hẳn field** ⇒ server dùng giọng mặc định.
3. Server **stream binary PCM** `int16 LE, 24000 Hz, mono` theo từng chunk, phát ngay khi có
   (streaming — không chờ synth xong cả câu).
4. Server gửi text frame kết thúc:
   ```json
   {"type": "end"}
   ```
   Client thấy `end` ⇒ dừng đọc, đóng WS.
5. **`text` rỗng:** server gửi ngay `{"type":"end"}` (không phát audio).

> Server **hiện có thể** phục vụ nhiều `synthesize` tuần tự trên cùng một WS (loop nhận
> tiếp sau khi gửi `end`) — điều này **được phép** và vô hại, nhưng **không bắt buộc**, vì
> client thực tế mở WS mới mỗi clause. Yêu cầu tối thiểu: **một** chu trình
> `synthesize → (nhiều binary) → end` cho mỗi kết nối.

### 3.3. Server → Client

| Frame | Ý nghĩa |
|---|---|
| Binary (PCM 24k) | audio, nhiều chunk, kích thước tùy ý |
| `{"type":"end"}` | đã đọc xong lượt synth này |

- **KHÔNG có `start` frame.** Client không đọc `sr`/`format` từ frame mở đầu — nó **giả định
  cứng 24000 Hz mono**. Nếu đội đổi sample rate, **phải báo trước** (đây là thay đổi breaking,
  cần đổi cả worker).
- Client chỉ break vòng lặp khi gặp `{"type":"end"}`. Text frame loại khác sẽ bị **bỏ qua**
  (không làm client dừng) — xem xử lý lỗi ở 3.5.

### 3.4. Barge-in / hủy

- Không có lệnh `stop`. Khi khách nói chen (barge-in), **worker đóng thẳng WS**.
- Server **phải phát hiện WS đóng giữa chừng** (ConnectionClosed) và **abort việc sinh audio
  ngay lập tức**, giải phóng GPU/thread, không sinh nốt tới EOS.

### 3.5. Xử lý lỗi (khuyến nghị)

Client hiện **không** yêu cầu error frame; nó chỉ chờ `end` hoặc chờ WS đóng. Để tránh treo:

- Khi synth lỗi giữa chừng ⇒ server nên **đóng WS** (client bắt `ConnectionClosed`, coi như
  hết audio, log warning) **hoặc** gửi `{"type":"end"}` để kết thúc sạch lượt.
- **Không** dựa vào việc gửi một text frame `{"type":"error"}` để dừng client — client sẽ bỏ
  qua nó và tiếp tục chờ `end`/close. Nếu muốn báo lỗi máy-đọc-được, xem mục 7.

---

## 4. Sample rate & định dạng audio (chốt cứng)

| Hướng | Định dạng |
|---|---|
| STT vào (client→server) | PCM `int16` little-endian, **16000 Hz**, **mono**, raw |
| TTS ra (server→client) | PCM `int16` little-endian, **24000 Hz**, **mono**, raw |

Không WAV header. Không đổi theo request. Việc resample về 8k (telephony) hay 48k (WebRTC)
do worker tự lo — service **không** cần quan tâm.

---

## 5. Ví dụ trao đổi

### 5.1. STT (1 WS suốt phiên)
```
Client → (WS connect, header: Authorization: Bearer <token>)
Client → <binary PCM 16k>            (liên tục)
Client → <binary PCM 16k>
Server → {"type":"partial","text":"xin"}
Server → {"type":"partial","text":"xin chào"}
Server → {"type":"final","text":"xin chào anh"}
Client → <binary PCM 16k> ...          (tiếp tục nói)
Server → {"type":"final","text":"em muốn hỏi giá"}
...
Client → {"type":"eos"}                (hết phiên)
Client → (đóng WS)
```

### 5.2. TTS (1 WS / clause)
```
Client → (WS connect, header auth)
Client → {"type":"synthesize","text":"Dạ em chào anh.","voice":"luna"}
Server → <binary PCM 24k>
Server → <binary PCM 24k> ...
Server → {"type":"end"}
Client → (đóng WS)

--- clause kế tiếp: MỞ WS MỚI ---
Client → (WS connect)
Client → {"type":"synthesize","text":"Căn hộ 85m2 giá 3.5 tỷ."}
Server → <binary PCM 24k> ...
Server → {"type":"end"}

--- barge-in giữa chừng ---
Client → (đóng thẳng WS, KHÔNG gửi stop)
Server → (thấy ConnectionClosed → abort sinh audio ngay, giải phóng GPU)
```

---

## 6. Khác biệt so với protocol `hotline_ws` cũ (để đội đối chiếu khi refactor)

| Khía cạnh | Protocol cũ (`event`/`cmd`) | **Chuẩn `remote` (spec này)** |
|---|---|---|
| Khóa control | `"event"` / `"cmd"` | **`"type"`** |
| Lệnh synth | `{"cmd":"synth",...}` | **`{"type":"synthesize",...}`** |
| Frame mở đầu | `{"event":"start","sr":...}` | **KHÔNG có `start`** (24k giả định cứng) |
| Kết thúc lượt | `{"event":"end","id","reason"}` | **`{"type":"end"}`** (không `id`, không `reason`) |
| Correlation `id` | có | **không** |
| Mô hình WS | 1 WS/cuộc gọi + hàng đợi FIFO | **1 WS / mỗi clause** |
| Barge-in | `{"cmd":"stop"}` | **đóng WS** (không có `stop`) |
| STT transcript | (n/a) | `{"type":"partial"/"final","text"}` |
| Kết thúc STT | (n/a) | client gửi `{"type":"eos"}` |

Nếu đội muốn giữ được cả `id`/`reason`/`start` cho mục đích riêng, có thể **gửi kèm** như field
thừa — nhưng **bắt buộc phải có** đúng các field/tín hiệu ở cột phải để client `remote` hoạt động.

---

## 7. Mở rộng tương thích (nếu đội cần thêm)

Những thứ sau **chưa** nằm trong hợp đồng hiện tại; muốn thêm phải sửa cả client worker →
báo trước để làm đồng bộ:

- **Error code máy-đọc-được** cho TTS/STT (VD `{"type":"error","code":...,"message":...}`).
  Hiện client bỏ qua; cần thì thống nhất rồi wire vào `remote.py`.
- **`id` correlation** để pipeline nhiều synth trên 1 WS (client hiện 1 WS/clause nên không cần).
- **Sample rate động** cho TTS (khai báo `sr` trong một start frame) — hiện client hardcode 24k.
- **Output 8kHz** trực tiếp từ TTS (bỏ resample phía worker).

Mọi thay đổi ở các mục 1–5 là **breaking** với worker; các mục 7 là opt-in, thêm được mà không phá cái cũ.

---

## 8. Checklist nghiệm thu (server đội phải đạt)

**STT**
- [ ] Nhận binary PCM `int16/16k/mono`, không giả định chunk size.
- [ ] Gửi `{"type":"partial","text":...}` khi có kết quả tạm.
- [ ] Gửi `{"type":"final","text":...}` cho mỗi đoạn chốt; hỗ trợ nhiều `final`/phiên.
- [ ] Không gửi frame `text` rỗng.
- [ ] Nhận `{"type":"eos"}` và/hoặc WS đóng ⇒ dừng phiên, giải phóng.
- [ ] Auth Bearer (nếu bật): sai/thiếu ⇒ close `1008`.

**TTS**
- [ ] Nhận `{"type":"synthesize","text":...,"voice"?:...}` trên WS mới mỗi lần.
- [ ] Stream binary PCM `int16/24k/mono`, chunk tùy ý, phát ngay khi có.
- [ ] Gửi đúng **một** `{"type":"end"}` khi xong; `text` rỗng ⇒ `end` ngay.
- [ ] Client đóng WS giữa chừng ⇒ abort sinh audio ngay, giải phóng GPU/thread.
- [ ] Lỗi giữa chừng ⇒ đóng WS hoặc gửi `end` (không để client treo).
- [ ] Auth Bearer (nếu bật): sai/thiếu ⇒ close `1008`.

**Chung**
- [ ] `max_size` khung ≥ 10 MB.
- [ ] Chấp nhận WebSocket ping/pong (client ping mỗi 20s).
- [ ] Báo lại cho team worker: `host`, `port`, đường dẫn (`/stt`, `/tts`), có bật auth token không.
```