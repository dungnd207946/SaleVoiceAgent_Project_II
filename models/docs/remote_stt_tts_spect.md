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
   - `ref_codes` / `ref_text`: **tùy chọn, đi CÙNG nhau** — zero-shot voice cloning (xem
     §3.6). Có cả hai ⇒ server dùng ref đó thay preset (`voice` bị bỏ qua nếu có). Có
     **đúng một trong hai** ⇒ lỗi, xem §3.6. Không có field nào ⇒ hành vi y hệt hôm nay
     (voice preset).
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

### 3.6. Zero-shot voice cloning — `encode_reference` (mở rộng, cộng thêm)

> **2026-10-06: hiện KHÔNG service nào cài mục này.** Hai bản cài duy nhất — `tts` (v2) và
> `tts-vieneu-v3` — đã gỡ khỏi `odyssey-models`; `tts-omnivoice` chỉ có `enroll_voice`
> (xem `docs/voice_cloning.md`). Giữ lại làm hợp đồng cho lần cài sau.

> **Cộng thêm, không phá cái cũ.** Client không dùng tính năng này thì không gửi các frame
> dưới đây và mọi hành vi `synthesize` giữ nguyên 100% như §3.2–§3.5.

Client mã hoá một mẫu audio (giọng cần nhân bản) thành `ref_codes` trên **cùng WS** trước khi
`synthesize`, hoặc trên một WS riêng rồi mang `ref_codes` sang lần `synthesize` khác (client tự
quản lý vòng đời — server không cache theo phiên nào cả, mỗi lần `encode_reference` độc lập).

**Luồng encode:**
```
Client → {"type": "encode_reference"}
Client → <binary WAV bytes>            (một hoặc nhiều chunk, tuỳ ý, tổng ≤ 25MB, ≤ 4096 chunk)
Client → <binary WAV bytes> ...
Client → {"type": "encode_end"}
Server → {"type": "ref_codes", "codes": [int, ...]}            # thành công
         hoặc
         {"type": "error", "code": "...", "message": "..."}   # thất bại (xem lý do bên dưới)
```

- **`error` frame có field `code` máy-đọc-được** (mới — trước bản này TTS không có `error`
  frame nào cả, xem mục 7). Giá trị `code` hiện có:

  | `code` | Khi nào | `message` an toàn để hiển thị? |
  |---|---|---|
  | `invalid_audio` | không phải WAV, audio <1s, hoặc phiên encode vượt 25MB/4096 chunk | Có — mô tả rõ vấn đề đầu vào |
  | `encode_failed` | lỗi nội bộ (encoder chưa load được, OOM, lỗi mạng HF, ...) | Không — message là câu chung chung cố định, lỗi thật chỉ log phía server (có thể chứa đường dẫn cache/CUDA) |
  | `encode_session_replaced` | nhận `encode_reference` thứ hai trong khi phiên trước chưa `encode_end` — phiên cũ bị huỷ, phiên mới bắt đầu | Có |
  | `no_encode_session` | nhận `encode_end` mà chưa có `encode_reference` nào mở phiên | Có |
  | `ref_mismatch` | `synthesize` có đúng một trong `ref_codes`/`ref_text` | Có |
  | `invalid_ref` | `ref_codes` không parse được / rỗng / vượt `REF_CODES_MAX` | Có |

- **Chỉ nhận WAV** (RIFF/WAVE). Image server không cài ffmpeg → mp3/định dạng nén khác bị
  từ chối ngay (`code: invalid_audio`) với message rõ ràng thay vì lỗi mù mờ sâu trong
  librosa. Muốn hỗ trợ mp3 phải thêm ffmpeg vào image trước.
- **Giới hạn dung lượng VÀ số chunk:** tổng byte binary trong một phiên encode vượt 25MB,
  **hoặc** số chunk binary vượt 4096 (`ENCODE_MAX_CHUNKS`) ⇒ server huỷ phiên (`encode_buf`
  reset) và trả `{"type":"error","code":"invalid_audio",...}` ngay tại chunk vượt ngưỡng.
  Cap theo byte kiểm tra bằng một bộ đếm chạy (O(1) mỗi frame) — **không** tính lại tổng mỗi
  lần nhận frame, để một client gửi audio thành rất nhiều frame nhỏ (VD `MediaRecorder`
  timeslice ngắn) không thể khiến server tốn CPU trên event loop và làm timeout các phiên
  synth khác đang chạy song song.
- **Giới hạn thời lượng:** audio dài hơn 15s bị **cắt còn 15s đầu** trước khi encode (không
  phải lỗi) — ref dài làm mọi lần synth sau đó chậm hơn vì nó nằm trong prompt. Audio ngắn
  hơn 1s ⇒ lỗi (`code: invalid_audio`, `"audio mẫu quá ngắn (<1s)"`).
- **Binary frame ngoài phiên encode** (không có `encode_reference` trước đó, hoặc phiên đã
  kết thúc) tiếp tục bị **bỏ qua** như hành vi cũ — không có tác dụng phụ.
- **`encode_reference` nhận hai lần liên tiếp** (phiên trước chưa `encode_end`) ⇒ phiên cũ bị
  huỷ (không corrupt gì, buffer là connection-local), server trả
  `{"type":"error","code":"encode_session_replaced",...}` rồi **vẫn mở phiên mới** ngay sau đó
  (không cần client gửi lại `encode_reference`).
- **`encode_end` khi chưa có phiên nào mở** ⇒ `{"type":"error","code":"no_encode_session",...}`,
  không có `end` frame đi kèm (đây không phải luồng `synthesize`).
- `codes` là danh sách int — chính là `ref_codes` dùng lại ở `synthesize` bên dưới.

**Dùng `ref_codes` để synth (zero-shot):**
```
Client → {"type": "synthesize", "text": "...", "ref_codes": [int, ...], "ref_text": "<transcript của mẫu audio>"}
Server → <binary PCM 24k> ...
Server → {"type": "end"}
```
- `ref_text` là **transcript đúng** của mẫu audio đã encode (bắt buộc đi kèm `ref_codes`,
  dùng để dựng prompt zero-shot — không phải văn bản cần đọc).
- Có **đúng một** trong hai field (`ref_codes` hoặc `ref_text`) ⇒ server trả
  `{"type":"error","code":"ref_mismatch","message":"ref_codes và ref_text phải đi cùng nhau"}`
  **rồi** `{"type":"end"}` — **không silent-fallback** về giọng mặc định, để caller biết chắc
  là lỗi chứ không phải đã synth bằng giọng khác ý muốn.
- `ref_codes` có nhưng không parse được thành list số nguyên, **hoặc là list rỗng**, **hoặc
  dài hơn `REF_CODES_MAX`** (900 phần tử — ~15s audio ở ~50 code/s, cùng giới hạn thời lượng
  của `encode_reference`, cộng ~20% dư; caller có thể gửi thẳng `ref_codes` mà không qua
  `encode_reference`, nên giới hạn 15s phải được áp lại ở đây, không chỉ ở bước encode) ⇒
  `{"type":"error","code":"invalid_ref","message":"..."}` rồi `{"type":"end"}`.
- Không có field `ref_codes`/`ref_text` nào ⇒ y hệt hành vi cũ (`voice` preset hoặc mặc định).

**Env mới (phía server, không ảnh hưởng worker):** `TTS_ENCODER_REPO` (mặc định
`neuphonic/neucodec`), `TTS_ENCODER_DEVICE` (mặc định `cpu`) — encoder full torch NeuCodec,
nạp lazy ở lần `encode_reference` đầu tiên (tách khỏi codec ONNX int8 dùng cho decode, vì
codec đó không hỗ trợ encode).

> **Yêu cầu bắt buộc cho phía console/frontend:** `MediaRecorder` trong trình duyệt ghi ra
> webm/ogg, KHÔNG phải WAV — vì service chỉ nhận WAV (xem lý do ở trên), console phải tự
> chuyển sang WAV (client-side hoặc qua backend) trước khi gửi binary frame cho
> `encode_reference`. Gửi thẳng webm/ogg sẽ bị từ chối với `code: invalid_audio`.

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

- **Hotwords per-session cho STT** (đã hỗ trợ phía server `odyssey-models`, opt-in):
  client gửi **một** text frame `{"type":"config","hotwords":"NOBLEX :2.0/NOBLE CITY"}`
  **trước binary frame đầu tiên**. Phrase phân cách bằng `/`, hậu tố ` :<score>` (tùy chọn)
  chỉnh mức boost riêng từng phrase. Server tự uppercase (BPE train trên chữ HOA) và dựng
  context graph ngay khi nhận config frame — không đợi audio, nên client VAD-gate gửi config
  lúc mở WS là cây đã sẵn sàng từ trước khi khách nói. Yêu cầu
  server chạy `STT_DECODING_METHOD=modified_beam_search` — nếu không, frame bị bỏ qua
  (log warning), phiên vẫn chạy bình thường. Client cũ không gửi frame này ⇒ không đổi gì.
  **Merge với danh sách nền của server** (`STT_HOTWORDS_FILE`): file là base áp cho mọi
  phiên; phrase client **trùng** phrase trong base (so khớp không phân biệt hoa/thường và
  khoảng trắng thừa) thì score của client **ghi đè** — chỉ có giá trị trong phiên đó,
  base trên server không đổi. Phiên mới (kể cả phiên chạy đồng thời) luôn bắt đầu từ
  base gốc của file.

- **Zero-shot voice cloning cho TTS** (hiện chưa service nào cài — xem ghi chú đầu §3.6) —
  xem §3.6 cho chi tiết đầy đủ. Tóm tắt: `{"type":"encode_reference"}` + binary WAV +
  `{"type":"encode_end"}` → `{"type":"ref_codes","codes":[...]}`; rồi `synthesize` mang
  thêm `ref_codes`/`ref_text` để dùng giọng đó thay preset. Client cũ không gửi các frame
  này ⇒ không đổi gì. Đây cũng là chỗ DUY NHẤT hiện tại mà server chủ động gửi
  `{"type":"error","code":...,"message":...}` cho TTS — bảng `code` đầy đủ ở §3.6. Lỗi
  trong luồng `synthesize` (ví dụ `ref_mismatch`, `invalid_ref`) luôn kèm `{"type":"end"}`
  ngay sau; lỗi trong luồng `encode_reference`/`encode_end` (ví dụ `invalid_audio`,
  `encode_failed`, `encode_session_replaced`, `no_encode_session`) **không** kèm `end` — đó
  không phải một lượt `synthesize`. Không dựa vào client đọc `error` để dừng vòng lặp
  `synthesize → binary → end` nói chung (vẫn đúng như §3.5).

- **Error code máy-đọc-được** cho TTS/STT nói chung (VD `{"type":"error","code":...}`)
  — ngoài các case voice-cloning ở trên (đã có `code`, xem §3.6), phần còn lại của TTS vẫn
  theo §3.5 (đóng WS hoặc `end`, không có `error` frame). Cần mở rộng thêm thì thống nhất
  rồi wire vào `remote.py`.
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
- [ ] (mở rộng, §3.6) `encode_reference` → binary WAV (≤25MB tổng, ≤4096 chunk) →
      `encode_end` ⇒ `{"type":"ref_codes",...}` hoặc `{"type":"error","code":...,...}`;
      audio >15s bị cắt, không lỗi. Byte cap kiểm tra O(1)/frame (không tính lại tổng mỗi
      frame) để nhiều frame nhỏ không làm nghẽn event loop / timeout phiên synth khác.
- [ ] (mở rộng) `synthesize` với đúng một trong `ref_codes`/`ref_text` ⇒
      `{"type":"error","code":"ref_mismatch",...}` + `end` (không silent-fallback);
      `ref_codes` rỗng/không parse được/dài hơn `REF_CODES_MAX` (~15s) ⇒
      `{"type":"error","code":"invalid_ref",...}` + `end`; không có field nào ⇒ hành vi
      preset y hệt cũ.
- [ ] (mở rộng) Binary frame ngoài phiên encode vẫn bị bỏ qua như cũ.
- [ ] (mở rộng) `encode_reference` hai lần liên tiếp ⇒ `error` (`encode_session_replaced`)
      rồi mở phiên mới; `encode_end` không có phiên mở ⇒ `error` (`no_encode_session`),
      không kèm `end`.

**Chung**
- [ ] `max_size` khung ≥ 10 MB.
- [ ] Chấp nhận WebSocket ping/pong (client ping mỗi 20s).
- [ ] Báo lại cho team worker: `host`, `port`, đường dẫn (`/stt`, `/tts`), có bật auth token không.
```