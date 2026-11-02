# Spec — TTS WebSocket Endpoint (bắt buộc) cho NobleX SaaS Gateway

**Đối tượng:** đội triển khai model TTS.
**Phiên bản:** 1.0 — 2026-09-21. **Nguồn chân lý:** code gateway NobleX SaaS (phía gọi). Mọi tên field, kiểu frame, sample rate phải khớp **chính xác từng byte** — phía NobleX chỉ đổi một biến môi trường (`TTS_WS_URL`) để trỏ sang endpoint mới, **không sửa code**.

Endpoint này phục vụ **3 kiểu client** từ gateway, cùng một URL:
1. **WS streaming** — khách hàng synthesize real-time (playground console, API `/v1/tts` WS).
2. **HTTP unary** — gateway mở **một WS mới cho mỗi request**, gửi đúng 1 `synthesize`, gom PCM tới `end`, đóng.
3. **Encode reference** — gateway mở **một WS mới cho mỗi lần** nhân bản giọng (voice clone), chạy chu trình `encode_reference`.

## 0. Tóm tắt 1 phút

| Hạng mục | Giá trị |
|---|---|
| Transport | WebSocket; tối thiểu 1 chu trình lệnh/kết nối, **khuyến nghị** phục vụ nhiều lệnh tuần tự trên cùng WS |
| Client gửi | text JSON: `synthesize` / `encode_reference` / `encode_end`; binary = WAV bytes (chỉ trong phiên encode) |
| Server trả | binary = PCM **int16 LE, 24000 Hz, mono, raw**; text JSON: `end` / `ref_codes` / `error` |
| Auth | `Authorization: Bearer <token tĩnh>` khi handshake; sai ⇒ close `1008` |
| Ngôn ngữ | tiếng Việt (bắt buộc) |
| Voice cloning | **zero-shot bắt buộc** — nhận `ref_codes`+`ref_text` trong `synthesize`, và cung cấp bước `encode_reference` |

Giao cho NobleX: **một URL WS đầy đủ** + **token tĩnh dùng chung với STT** (gateway chỉ có một biến `ODYSSEY_MODELS_TOKEN`).

## 1. Quy ước chung

- Text frame = một JSON object UTF-8, khóa phân loại là `"type"`.
- Server phải nhận frame tới **≥ 10 MB** (gateway gửi WAV encode theo chunk 1 MB).
- **QUAN TRỌNG:** mỗi binary frame server gửi về phải **≤ 1 MB** (gateway nhận với `max_size` mặc định 1 MiB — frame to hơn làm đứt kết nối). Khuyến nghị chunk PCM 8–64 KB, phát ngay khi có (streaming, không chờ synth xong cả câu).
- Client bật `ping_interval=20s` — giữ pong mặc định của thư viện WS.
- Bỏ qua an toàn field lạ trong frame đã biết. Frame `type` lạ ⇒ bỏ qua im lặng.
- **Không có `start` frame.** Client giả định cứng PCM out = 24000 Hz mono int16. Đổi sample rate = breaking change, phải thống nhất trước.

### 1.1. Auth
Giống STT: token cấu hình rỗng ⇒ tắt auth (dev only); có giá trị ⇒ so khớp chính xác, sai/thiếu ⇒ close `1008` ngay handshake.

## 2. Lệnh `synthesize`

```
Client → {"type":"synthesize","text":"Dạ em chào anh.","voice":"luna"}
Server → <binary PCM 24k>          (nhiều chunk, mỗi chunk ≤ 1MB)
Server → <binary PCM 24k> ...
Server → {"type":"end"}
```

| Field | Kiểu | Bắt buộc | Ý nghĩa |
|---|---|---|---|
| `text` | string | có | Nội dung cần đọc. Qua đường HTTP gateway đã chặn ≤ 5000 ký tự; đường WS không chặn — server tự đặt trần và trả `error` nếu vượt |
| `voice` | string | không | Tên giọng preset. **Vắng mặt hoặc không nhận ra ⇒ dùng giọng mặc định, KHÔNG lỗi.** Danh sách preset do đội công bố khi bàn giao |
| `ref_codes` | list[int] | không | Zero-shot voice clone — xem §4. Chỉ gateway inject, luôn đi cùng `ref_text` |
| `ref_text` | string | không | Transcript đúng của audio mẫu đã encode (không phải văn bản cần đọc) |

Quy tắc:
- `text` rỗng ⇒ trả ngay `{"type":"end"}`, không audio, không lỗi.
- Kết thúc **luôn** bằng `{"type":"end"}` — kể cả sau `error` (trừ lỗi trong phiên encode, §4). Client chỉ thoát vòng chờ khi gặp `end` hoặc WS đóng; **đừng** trông cậy client dừng vì thấy `error`.
- **Không được** gửi `end` với 0 byte PCM cho một `synthesize` hợp lệ có text — gateway đường HTTP coi đó là lỗi upstream (502).
- **Barge-in/hủy:** client đóng WS giữa chừng ⇒ server phải **abort sinh audio ngay**, giải phóng GPU/slot, không sinh nốt.
- Trên một kết nối, sau `end` server **nên** quay lại chờ lệnh kế tiếp (khách playground gửi nhiều `synthesize` tuần tự trên cùng WS). Không hỗ trợ song song trong 1 WS — lệnh đến khi đang synth có thể xếp hàng tuần tự.

## 3. Frame `error`

```json
{"type":"error","code":"<mã máy-đọc-được>","message":"<mô tả>"}
```

Mã lỗi bắt buộc (gateway/console đã map từng mã — đổi tên là vỡ UI):

| `code` | Khi nào | `message` hiển thị cho khách? |
|---|---|---|
| `invalid_audio` | encode: không phải WAV, audio <1s, vượt 25MB/4096 chunk | Có |
| `encode_failed` | encode: lỗi nội bộ (encoder chưa load, OOM…) | Không — message chung chung, chi tiết chỉ ghi log server |
| `encode_session_replaced` | `encode_reference` thứ hai khi phiên trước chưa `encode_end` (phiên cũ hủy, phiên mới mở luôn) | Có |
| `no_encode_session` | `encode_end` khi chưa có phiên encode nào mở | Có |
| `ref_mismatch` | `synthesize` có đúng một trong `ref_codes`/`ref_text` | Có |
| `invalid_ref` | `ref_codes` không phải list số nguyên / rỗng / dài hơn **900** phần tử | Có |

Với lỗi thuộc `synthesize` (`ref_mismatch`, `invalid_ref`, lỗi synth khác): gửi `error` **rồi** `end`. **Không silent-fallback** sang giọng mặc định khi ref lỗi — khách phải biết chắc là lỗi chứ không phải đã synth bằng giọng khác ý.

## 4. Voice cloning zero-shot (bắt buộc)

Kiến trúc phía NobleX: giọng clone lưu ở dạng `ref_codes` (list int, ~50 codes/giây audio) trong DB của NobleX. Endpoint TTS **stateless** — không lưu giọng nào; mỗi `synthesize` mang sẵn ref trong frame.

### 4.1. `encode_reference` — audio mẫu → `ref_codes`

```
Client → {"type":"encode_reference"}
Client → <binary WAV bytes>        (1..n chunk tùy ý, gateway gửi chunk 1MB)
Client → {"type":"encode_end"}
Server → {"type":"ref_codes","codes":[123,456,...]}     # thành công
       | {"type":"error","code":"...","message":"..."}  # thất bại — KHÔNG kèm end
```

- Đầu vào: **chỉ WAV** (RIFF/WAVE, mọi sample rate/kênh — server tự resample). Định dạng khác ⇒ `invalid_audio`.
- Giới hạn: tổng ≤ **25 MB**, ≤ **4096 chunk**, thời lượng < 1s ⇒ `invalid_audio`; dài hơn **15s ⇒ cắt còn 15s đầu** (không lỗi).
- `codes` trả về ≤ **900** phần tử (đồng bộ trần `invalid_ref` ở §3 — caller có thể gửi thẳng `ref_codes` không qua encode, nên trần phải được áp lại ở `synthesize`).
- **Ngân sách thời gian: toàn bộ chu trình encode phải xong < 90s** (gateway timeout cứng 90s rồi báo lỗi cho khách). Thực tế phải < 10s với mẫu 15s ⇒ **encoder phải được pre-warm lúc deploy**, không được lazy-download model trên request đầu tiên của khách.
- Binary frame ngoài phiên encode ⇒ bỏ qua im lặng. Các case `encode_session_replaced` / `no_encode_session` xử lý như bảng §3.
- Mỗi lần encode độc lập, không cache theo connection.

### 4.2. Synthesize bằng giọng clone

```
Client → {"type":"synthesize","text":"...","ref_codes":[...],"ref_text":"<transcript của mẫu>"}
Server → <PCM 24k> ... → {"type":"end"}
```

`ref_codes` + `ref_text` **luôn đi cùng nhau** (thiếu 1 ⇒ `ref_mismatch`); khi có ref thì bỏ qua `voice`. Giọng ra phải giống mẫu một cách nghe được (không phải giọng preset). Không có ref ⇒ hành vi §2 y nguyên.

## 5. Ràng buộc vận hành (gateway đã cố định)

| Ràng buộc | Giá trị | Ghi chú |
|---|---|---|
| Thời lượng 1 WS | tối đa **900s** | Gateway tự cắt; kết nối HTTP-unary có ngân sách 120s/request |
| Encode timeout | **90s** (cứng) | Xem §4.1 |
| Phiên đồng thời | ≥ **10/workspace**; tham chiếu hiện tại phục vụ 6 synth song song trên 1 GPU 16GB | Khai báo capacity khi bàn giao |
| Billing | Gateway tự đếm ký tự `text`; encode được kiểm soát/duyệt ở tầng NobleX | Server không báo cáo gì |
| SLO khuyến nghị | TTFB (byte PCM đầu) p95 ≤ **500ms** với câu ≤ 160 ký tự; tham chiếu hiện tại ~205ms; TTFB giọng clone không được chậm hơn preset đáng kể | Thống nhất khi nghiệm thu |

## 6. Checklist nghiệm thu (NobleX sẽ chạy đúng các bước này)

1. Token sai ⇒ close `1008`; token đúng ⇒ handshake OK.
2. `synthesize` preset: nhận PCM 24k chunk ≤1MB, kết bằng `end`; audio nghe đúng nội dung tiếng Việt.
3. `text` rỗng ⇒ `end` ngay, 0 audio.
4. `voice` không tồn tại ⇒ giọng mặc định, không lỗi.
5. Encode WAV 5–10s + transcript ⇒ `ref_codes` (~50 codes/s); synth bằng ref đó ⇒ giọng giống mẫu.
6. Negative: gửi mp3 ⇒ `invalid_audio`; `synthesize` chỉ có `ref_codes` ⇒ `ref_mismatch`+`end`; `ref_codes: []` ⇒ `invalid_ref`+`end`; `ref_codes` 901 phần tử ⇒ `invalid_ref`+`end`; `encode_reference` ×2 liên tiếp ⇒ `encode_session_replaced` rồi phiên mới vẫn dùng được; `encode_end` mồ côi ⇒ `no_encode_session`, **không** có `end`.
7. Đóng WS giữa lúc đang synth ⇒ server abort ngay (đo GPU/log), lặp 50 lần không leak.
8. Concurrency: một kết nối đang stream synth, kết nối khác chạy encode ⇒ TTFB của synth không tăng đáng kể.
9. 2 chu trình `synthesize` tuần tự trên cùng 1 WS hoạt động.

Sau nghiệm thu, NobleX chỉ đổi `.env`: `TTS_WS_URL=wss://<endpoint của đội>` (+ token chung với STT) và recreate gateway.
