# Handoff — Frontend Chat qua Gateway (`/v1/chat`)

**Ngày:** 2026-08-10 · **Đối tượng:** team design/dev frontend chat
**Nguồn sự thật:** code trong `src/noble_agent/` (đã inspect, tham chiếu file:line ở §10)
**Reference client chạy được:** [`static/chat.html`](../../static/chat.html) — trang chat 1 file
(HTML+CSS+JS inline) đã nói đúng protocol này ở chế độ gateway; dùng làm mẫu đối chiếu.

---

## 1. Yêu cầu tối thiểu — đúng 2 input

Frontend chỉ cần người dùng nhập:

| Input | Ví dụ | Ý nghĩa |
|---|---|---|
| **Gateway URL** | `wss://noble-saas.example.com/v1/chat` | Một domain DÙNG CHUNG cho mọi tenant |
| **API key** | `ody_ag_vsuUX_t7hWtsyASIeJrz...` | Quyết định tenant, quyền, DB — không cần nhập tenant |

> **Không còn subdomain per-tenant.** Từ 2026-08-10 tenant được suy ra hoàn toàn từ API key
> (gateway gọi runtime-credentials API của Portal). Host trong URL không mang thông tin gì.
> Tài liệu/ảnh chụp cũ ghi `wss://<tenant>.<domain>/v1/chat` là **lỗi thời**.

### Cách gắn API key

```js
// Browser KHÔNG set được header Authorization cho WebSocket → dùng query param.
const ws = new WebSocket(`${gatewayUrl}?key=${encodeURIComponent(apiKey)}`);
ws.binaryType = 'arraybuffer';
```

- Backend/CLI: dùng header `Authorization: Bearer <key>` (ưu tiên hơn query param nếu có cả hai).
- Browser: `?key=<token>` hoặc `?token=<token>` — gateway tự đổi thành `Bearer`.
- Nếu URL đã có sẵn query string thì nối bằng `&`.

---

## 2. Handshake — frame ĐẦU TIÊN bắt buộc

Sau khi WS `open`, client **phải** gửi đúng **một TEXT frame JSON** trong vòng **10 giây**,
trước mọi thứ khác:

```json
{
  "identity": {
    "full_name": "Nguyễn Văn A",
    "phone": "0912010123",
    "gender": "nam",
    "is_noble_customer": true,
    "email": "a@example.com",
    "birthday": "1990-05-01",
    "noble_info": "Khách VIP, đã mua NCLB 2024"
  },
  "call_id": "c-8f21a0"
}
```

- Cả `identity` và `call_id` đều **optional** — gửi `{}` cũng hợp lệ, nhưng **vẫn phải gửi frame này**,
  không gửi → đóng WS code `4008`.
- `identity` (nếu non-empty) được gateway chuyển thành message `set_customer` gửi cho worker →
  agent biết trước tên/SĐT khách, không phải hỏi lại.
- `call_id` hiện **chỉ dùng cho voice** (đặt tên room). Ở chat nó bị bỏ qua — xem §7.

### Các khóa `identity` được worker ĐỌC (khác đi là bỏ qua im lặng)

| Key | Kiểu | Ghi chú |
|---|---|---|
| `full_name` | string | Điền cả `full_name` và `name` |
| `phone` | string | Khóa để lưu hồ sơ + summary cuối phiên |
| `gender` | string | Chuẩn hoá về `M`/`F`; nhận "nam"/"nữ"/"male"/"female"… |
| `is_noble_customer` | **boolean** | Phải là bool thật, gửi `"true"` (string) sẽ bị bỏ |
| `email` · `birthday` · `noble_info` | string | Gộp thành 1 chuỗi `noble_info` cho agent |

> ⚠️ **Không có khóa `name`.** Gửi `{"name": "Anh Duy"}` là mất trắng — phải là `full_name`.

### Close code

| Code | Reason | Nghĩa | UI nên hiện |
|---|---|---|---|
| 4001 | `no_bearer` | Không gửi key | "Chưa nhập API key" |
| 4001 | `bad_credential` | Key sai / bị thu hồi | "API key không hợp lệ" |
| 4001 | `auth_api_unavailable` | Hệ thống auth lỗi (**không phải lỗi key**) | "Hệ thống bận, thử lại" + cho retry |
| 4004 | `unknown_route` | Path không phải `/v1/chat` \| `/v1/voice` | "Sai URL gateway" |
| 4008 | `handshake_timeout` | Không gửi frame handshake trong 10s | lỗi client |
| 4029 | `chat_at_capacity` | Worker đầy tải (cap mặc định 200 phiên) | "Đang quá tải, thử lại sau" |
| 4403 | `gateway_secret_mismatch` | Lỗi cấu hình hạ tầng | báo backend |

`reason` nằm ở `event.reason` của `onclose`; **phân biệt `bad_credential` với `auth_api_unavailable`**
để người dùng không đi đổi key khi lỗi thật là hạ tầng.

---

## 3. Client → Server (TEXT frame, JSON)

Sau handshake, gateway relay nguyên văn mọi frame giữa client và worker. Có đúng 3 message:

```jsonc
// 1) Gửi 1 lượt chat
{ "type": "user_text", "text": "Dự án Noble Crystal giá bao nhiêu em?", "tts": false }

// 2) Xoá sạch hội thoại (Redis) — bắt đầu lại từ đầu, cùng session_id
{ "type": "reset" }

// 3) Cập nhật hồ sơ khách giữa phiên (cùng shape identity ở §2)
{ "type": "set_customer", "identity": { "full_name": "...", "phone": "..." } }
```

- `tts: true` → server sẽ **kèm audio PCM16** cho câu trả lời (§5). Mặc định `false`.
- Không có message "typing", không có message huỷ/ngắt lượt đang chạy. Muốn dừng thì đóng WS.
- Message không đúng JSON hoặc `type` lạ → worker **bỏ qua im lặng**, không báo lỗi.

---

## 4. Server → Client (TEXT frame, JSON) — catalog đầy đủ kênh CHAT

Mọi event là 1 object JSON có khoá `type`. **Bỏ qua `type` lạ**, coi mọi field ngoài `type` là optional.

### 4.1 Lifecycle phiên

```jsonc
{ "type": "session_id", "session_id": "3f9a1c7b2e04" }   // event ĐẦU TIÊN, luôn có
{ "type": "reset_ok" }                                    // trả lời {"type":"reset"}
{ "type": "customer_ok", "customer": { "full_name": "Nguyễn Văn A", "phone": "0912010123", "gender": "M" } }
{ "type": "error", "message": "LLM init failed: ..." }
```

> `session_id` được gửi **trước** khi worker kiểm tra tải và khởi tạo LLM. Nhận `session_id`
> **chưa chắc** đã sẵn sàng — ngay sau đó vẫn có thể là `error` + close `4029`. UI chỉ nên mở
> ô nhập sau `session_id`, nhưng phải xử lý được close ngay sau đó.

### 4.2 Một lượt trả lời (thứ tự đảm bảo)

```jsonc
{ "type": "user_text", "text": "..." }                          // echo lại câu vừa gửi
{ "type": "metrics", "stage": "first_token", "ttft_ms": 412 }   // ngay trước token đầu tiên
{ "type": "token", "text": "Dạ " }                              // stream từng mẩu, PHẢI nối (append)
{ "type": "token", "text": "dự án " }
{ "type": "tool_start", "tool": "kb_search", "args": { "query": "giá noble crystal" } }
{ "type": "tool_done", "tool": "kb_search", "result": "{\"...\":\"...\"}" }
{ "type": "token", "text": "Noble Crystal " }
{ "type": "done", "turn_id": "a1b2c3d4", "ttft_ms": 412, "tokens": 87,
  "gen_ms": 2140, "tokens_per_sec": 40.7, "total_ms": 2552 }
{ "type": "suggestions", "items": [ { "label": "Xem hình ảnh", "text": "Cho mình xem hình dự án" } ] }
```

Quy tắc render:

1. `token` là **mẩu văn bản (chunk)**, không phải từ — nối trực tiếp vào bong bóng đang mở.
2. Một lượt có thể có **nhiều cụm token xen kẽ tool** (agent nói → gọi tool → nói tiếp).
   Gặp `tool_start` thì **chốt bong bóng hiện tại**, hiện chip "đang xử lý…", `token` kế tiếp
   mở bong bóng mới. Tối đa 5 vòng tool/lượt.
3. `done` = kết thúc lượt, mở lại ô nhập. Các field metric đều optional (`ttft_ms` có thể `null`
   nếu lượt không sinh token nào).
4. `suggestions` đến **SAU `done`**, fire-and-forget, có thể **không bao giờ đến** (tắt bằng env,
   hoặc LLM phụ lỗi). Không được chờ nó. `items[].label` ≤ 24 ký tự, tối đa 3 chip;
   bấm chip = gửi `items[].text` như một `user_text` bình thường.
5. `error` giữa lượt: vẫn có `done` sau đó — đừng để UI kẹt ở trạng thái "đang trả lời".

### 4.3 `tool_done.result` — CHỖ DUY NHẤT có dữ liệu card ở kênh chat

> **`result` là một CHUỖI chứa JSON**, không phải object. Phải `JSON.parse` (và bọc try/catch —
> vài tool trả text thuần).

Kênh chat **không** có event `media` riêng (voice thì có, xem §8). Ảnh/video/booking/escalate đều
nằm trong `tool_done.result`.

```js
function handleToolDone(msg){
  let r = null;
  try { r = typeof msg.result === 'string' ? JSON.parse(msg.result) : msg.result; } catch {}
  if (r && Array.isArray(r.items) && r.items.length) return renderMediaCard(r);   // ảnh/video
  if (msg.tool === 'escalate' && r && r.status === 'transfer_completed') return renderEscalationCard(r);
  if (msg.tool === 'booking' && r && r.ok && r.appointment_id) return renderBookingCard(r);
  clearToolChip();
}
```

**a) Media (`send_media`)**

```jsonc
{
  "ok": true,
  "project_name": "Noble Crystal",
  "caption": "Hình ảnh dự án Noble Crystal",
  "count": 4,
  "message": "Dạ em gửi hình ảnh dự án qua app cho anh/chị rồi ạ.",
  "items": [
    { "kind": "image", "url": "https://.../full.jpg", "label": "Phối cảnh tổng thể", "thumb": "https://.../thumb.jpg" },
    { "kind": "video", "video_id": "dQw4w9WgXcQ", "title": "Video giới thiệu dự án" }
  ]
}
```

- `kind: "image"` → `url` (ảnh gốc, **có thể vài MB**), `label` (caption), `thumb` (optional,
  mặc định BẬT ở server). Chiến lược: lưới dùng `thumb`, mở lightbox hiện `thumb` trước rồi
  nâng cấp `url` chạy nền.
- `kind: "video"` → HAI biến thể (2026-08-25): `video_id` = **YouTube id**, nhúng
  `https://www.youtube.com/embed/<id>`, thumbnail rẻ `https://img.youtube.com/vi/<id>/hqdefault.jpg`;
  HOẶC `url` (Google Drive/Vimeo/mp4) kèm `embed_url?` (có thì nhúng iframe) + `thumb?` — không
  `embed_url` thì mở `url` tab mới. `title` là caption. Thiếu cả hai → bỏ.
- Tối đa **6 ảnh + 1 video** (3 video khi khách xin video) trong một lần. **Duyệt hết `items`**,
  đừng lấy phần tử đầu.
- Không có media: `{ "ok": false, "items": [], "count": 0, "note": "no_media", "message": "..." }`
  → **không** hiện card, agent sẽ tự nói bằng lời.
- Lỗi arg: `{ "ok": false, "error": "...", "retry": true, "message": "..." }`.

**b) Escalate (chuyển chuyên viên)**

```jsonc
// action=transfer — dựng card "đang kết nối chuyên viên"
{ "status": "transfer_completed", "department": "CVTV", "priority": "normal",
  "summary": "Khách: ..., SĐT: ..., Dự án: ... Lý do chuyển: ...",
  "working_hours": true,
  "message": "Dạ, em sẽ kết nối chuyên viên ngay ạ." }

// action=check_state — KHÔNG dựng card, chỉ là agent tự kiểm tra
{ "has_name": true, "has_phone": false, "transfer_ready": false, "working_hours": true }
```

`working_hours=false` (ngoài 8h–21h) → đổi nội dung card thành "chuyên viên sẽ liên hệ vào ngày
làm việc tiếp theo".
Lưu ý: `escalate` có thể được hệ thống **tự gọi** khi một tool khác không có dữ liệu — UI sẽ thấy
cặp `tool_start`/`tool_done` cho `escalate` mà agent không hề nhắc tới.

**c) Booking (`booking`, `action=schedule`)**

```jsonc
{ "ok": true, "success": true, "appointment_id": "APT48213",
  "project": "NCR", "preferred_date": "2026-08-15", "preferred_time": "09:00",
  "notes": "", "message": "Đặt lịch thành công." }
```

> ⚠️ **Cảnh báo lệch:** `static/chat.html` hiện kiểm tra `result.action === 'schedule'` và đọc
> `d.project_name` — **cả hai field này KHÔNG tồn tại** trong result. Card đặt lịch trong trang mẫu
> thực tế **không bao giờ hiện**. Bản mới phải bắt theo `ok && appointment_id`, và tên dự án chỉ có
> **mã** (`project`, ví dụ `NCR`) → cần bảng map mã→tên ở FE, hoặc hiển thị mã.

Các action khác của `booking`: `check_availability`, `list` (`{"bookings":[...], "count":n}`),
`modify` — không cần card, để agent diễn giải bằng lời.

**d) Các tool còn lại** (`kb_search`, `find_project`, `discover_projects`,
`get_project_overview`, `get_document`, `search_units`, `check_inventory`, `recommend_units`,
`update_customer`) — result là payload dữ liệu thô/JSON dài **chỉ dành cho model**. FE **không
render**, chỉ dùng để hiện chip "đang xử lý" rồi ẩn đi.

### 4.4 Danh mục tool (để map nhãn chip)

4 tool luôn bật: `update_customer` · `kb_search` · `find_project` · `escalate`
8 tool tuỳ tenant: `discover_projects` · `get_project_overview` · `get_document` ·
`search_units` · `check_inventory` · `recommend_units` · `booking` · `send_media`

> ⚠️ Nhãn trong `static/chat.html` đang dùng **tên cũ đã bị đổi/xoá**: `noble_search` (nay là
> `kb_search`), `list_projects` (nay là `discover_projects`), `get_project_financial` (đã xoá).
> Bản mới phải dùng đúng danh sách trên và **luôn có nhãn fallback** cho tool lạ (tenant có thể
> cài tool riêng).

---

## 5. Audio TTS trong chat (optional)

Bật bằng `{"type":"user_text", "tts": true}`. Khi đó, xen giữa các event JSON sẽ có **BINARY frame**:

```jsonc
{ "type": "tts_begin", "turn_id": "a1b2c3d4", "sample_rate": 24000 }
// ... nhiều BINARY frame: PCM16 mono little-endian, raw, không header ...
{ "type": "tts_end", "turn_id": "a1b2c3d4", "bytes": 384000, "tts_ms": 3120 }
```

- **Phân biệt bằng loại frame WS**: `event.data instanceof ArrayBuffer` → audio; string → JSON.
- **Sample rate lấy từ `tts_begin.sample_rate`** (hiện 24000), đừng hardcode.
- Audio stream **song song** với `token` (bắt đầu sau ~1 câu), và `tts_end` đến **sau `done`**.
- Barge-in: khi user gửi lượt mới, FE tự dừng phát + bỏ audio còn lại (server không gửi tín hiệu huỷ).
- Web Audio: Int16 → Float32 (`/32768`), `createBuffer(1, n, sample_rate)`, lên lịch phát nối
  tiếp bằng `nextStart = max(ctx.currentTime, nextStart)` để không hở tiếng.

---

## 6. Máy trạng thái tối thiểu cho UI

```
[nhập URL+key] → connect
   └ onopen → gửi handshake {identity, call_id} → chờ "session_id"
        ├ close 4001/4004/4008/4029 → hiện lỗi theo bảng §2, cho sửa input & retry
        └ session_id → READY (mở ô nhập)
             └ gửi user_text → BUSY
                  token* / tool_start / tool_done / metrics / error  (xen kẽ, lặp)
                  └ done → READY   (suggestions có thể đến sau, hoặc không)
```

Nguyên tắc phòng thủ:

1. `type` lạ → skip, không crash.
2. Mọi field ngoài `type` là optional.
3. Luôn có timeout phía FE cho trạng thái BUSY (worker có thể chết giữa chừng mà không gửi `done`).
4. `tool_done.result` phải parse trong try/catch.
5. WS đóng đột ngột → hiện trạng thái mất kết nối; **reconnect sẽ tạo phiên MỚI** (xem §7).

---

## 7. Giới hạn đã biết — FE phải thiết kế quanh nó

| Giới hạn | Hệ quả cho UI |
|---|---|
| **Không resume được phiên qua gateway.** `session_id` do worker tự sinh (12 hex ngẫu nhiên); `call_id` trong handshake bị bỏ qua ở chat, không có tham số `?session=`. | Mất mạng / F5 = mất hội thoại. Muốn giữ lịch sử thì FE phải tự lưu local và **hiển thị lại**, nhưng agent sẽ **không nhớ** nội dung cũ. |
| **Không có API lấy lịch sử.** Server không gửi lại history khi kết nối. | Màn hình mở ra luôn trống. |
| **Không có câu chào từ server ở kênh chat.** (Voice có, chat không.) | FE tự hiển thị lời chào client-side như trang mẫu đang làm. |
| **Không có event `media` riêng ở chat.** | Card ảnh/video bắt buộc lấy từ `tool_done.result`. |
| **Không huỷ được lượt đang chạy.** | Nút "dừng" chỉ có thể là đóng WS + kết nối lại. |
| **`suggestions` best-effort.** | Không dựng layout phụ thuộc vào việc chip luôn có. |
| **Một API key = một tenant cố định.** | Đổi tenant = đổi key = phải reconnect (và mất phiên). |

---

## 8. Kênh VOICE (`/v1/voice`) — tóm tắt để đối chiếu

Spec đầy đủ: [`docs/api/gateway-voice-ws-spec.md`](../api/gateway-voice-ws-spec.md). Khác biệt cốt lõi
so với chat:

| | Chat `/v1/chat` | Voice `/v1/voice` |
|---|---|---|
| Auth + handshake | giống nhau (Bearer/`?key=` + frame `{identity, call_id}`) | giống nhau — `call_id` **có dùng** (đặt tên room) |
| Client → server | TEXT JSON (`user_text`/`reset`/`set_customer`) | **BINARY PCM16 mono 16 kHz**; TEXT bị bỏ qua |
| Server → client | TEXT JSON + (optional) BINARY TTS | **BINARY audio agent** + TEXT JSON event |
| Streaming văn bản | `token` (từng mẩu) | `agent_speaking` (**từng câu**, không per-token) |
| Lời khách | không có | `partial_transcript` (ghi đè) + `transcript` (chốt) |
| `tool_done` | **có `result`** | **KHÔNG có `result`** |
| Media | trong `tool_done.result` | event `media` riêng: `{"type":"media", ...payload send_media}` |
| Ngắt lời | không có | `agent_interrupted` + `last_completed_sentence_id` |
| Câu chào | không | có (`turn_id: "greeting"`) |
| Kết thúc lượt | `done` + metrics | `agent_done` + `metrics` |
| Độ tin cậy event | relay đầy đủ | **best-effort, queue 256, đầy thì DROP** — chỉ để hiển thị |

**2 điểm cần backend chốt trước khi FE làm voice:**

1. **Sample rate audio agent (downlink) đang lệch tài liệu.** `gateway/server.py::_bridge_voice` gọi
   `rtc.AudioStream(track)` **không truyền `sample_rate`** → LiveKit SDK mặc định **48000 Hz**;
   trong khi `docs/api/gateway-voice-ws-spec.md` và `scripts/smoke_gateway_voice.py` đều ghi
   **24000 Hz**. Phát sai rate = giọng chậm/trầm một quãng tám. Cần pin rate tường minh ở gateway
   (hoặc khai báo rate trong một event handshake) rồi cập nhật doc. Uplink 16 kHz thì chắc chắn
   (gateway hardcode).
2. **URL trong spec voice vẫn ghi `wss://<tenant>.<domain>/v1/voice`** — đã lỗi thời, nay là
   single-domain như §1.

---

## 9. Nghiệm thu (checklist bàn giao)

1. Nhập URL + key sai → thấy đúng thông điệp `bad_credential`, không phải lỗi chung chung.
2. Nhập đúng → nhận `session_id`, ô nhập mở.
3. Hỏi "dự án nào đang mở bán?" → thấy chip tool → text stream mượt → `done` → chip gợi ý (nếu có).
4. Hỏi "cho xem hình dự án Noble Crystal" → card ảnh có ≥1 ảnh, mở lightbox được; nếu có video →
   nhúng YouTube chạy được.
5. "Mình muốn đặt lịch tham quan" → hoàn tất luồng → **card đặt lịch hiện** (kiểm tra đúng bug §4.3c).
6. Bật TTS → nghe được tiếng, không hở/vấp giữa câu.
7. Rút mạng giữa lượt → UI thoát trạng thái BUSY, hiện mất kết nối, có nút kết nối lại.
8. Gửi `reset` → khung chat xoá, phiên vẫn chạy được lượt mới.

---

## 10. Tham chiếu code (nguồn sự thật khi nghi ngờ)

| Nội dung | Vị trí |
|---|---|
| Route + handshake + close code | [gateway/server.py](../../src/noble_agent/gateway/server.py) — `route`, `_handle`, `_HANDSHAKE_TIMEOUT_SEC` |
| Auth bằng API key → tenant | [gateway/auth.py](../../src/noble_agent/gateway/auth.py), [gateway/credentials.py](../../src/noble_agent/gateway/credentials.py) |
| Reverse-proxy chat + seed identity | [gateway/chat_proxy.py](../../src/noble_agent/gateway/chat_proxy.py) |
| **Toàn bộ event chat + TTS** | [server/text_chat.py](../../src/noble_agent/server/text_chat.py) — `run_text_turn`, `handle_text_session` |
| Map `identity` → hồ sơ khách | [server/app_session.py](../../src/noble_agent/server/app_session.py) — `identity_to_fields` |
| Vòng lặp tool, `tool_done.result` | [agent/tools/dispatcher.py](../../src/noble_agent/agent/tools/dispatcher.py) |
| Payload media | [agent/tools/support_ops.py](../../src/noble_agent/agent/tools/support_ops.py), [data/media_data.py](../../src/noble_agent/data/media_data.py) |
| Payload booking / escalate | [agent/tools/schedule_viewing.py](../../src/noble_agent/agent/tools/schedule_viewing.py), [agent/tools/support_ops.py](../../src/noble_agent/agent/tools/support_ops.py) |
| Chip gợi ý | [agent/suggestions.py](../../src/noble_agent/agent/suggestions.py) |
| Danh mục tool | [agent/agent_config.py](../../src/noble_agent/agent/agent_config.py) — `CORE_TOOLS`, `OPTIONAL_TOOLS` |
| Event voice | [voice/voice_agent.py](../../src/noble_agent/voice/voice_agent.py), [server/base_session.py](../../src/noble_agent/server/base_session.py) |
| Client mẫu (chat) | [static/chat.html](../../static/chat.html) — lưu ý 2 chỗ lệch ở §4.3c và §4.4 |
| Client mẫu (CLI) | [scripts/e2e_dbmode/chat_via_gateway.py](../../scripts/e2e_dbmode/chat_via_gateway.py) |
