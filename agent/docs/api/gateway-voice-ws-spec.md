# Gateway Voice WS — Spec output cho client provider (`/v1/voice`)

**Ngày:** 2026-08-07 · **Trạng thái:** áp dụng từ commit thêm event-forward vào `_bridge_voice`
(`src/noble_agent/gateway/server.py`). Trước đó đường này CHỈ trả audio.

Tài liệu này là contract cho frontend/backend của provider khi gọi voice qua gateway WS.
Media (`items[]`) dùng chung contract với app — chi tiết render xem
[noblex-app-dev-guide.md §4](noblex-app-dev-guide.md).

---

## 1. Kết nối & handshake

```
wss://<tenant>.<gateway_base_domain>/v1/voice
```

- **Auth:** header `Authorization: Bearer tnt_...` — hoặc query `?key=` / `?token=`
  (cho client không set được header, ví dụ browser WebSocket). Header thắng nếu có cả hai.
- **Frame ĐẦU TIÊN sau khi kết nối** (bắt buộc, TEXT/JSON, trong vòng **10s**):

```json
{ "identity": { "full_name": "Nguyễn Văn A", "phone": "09xxxxxxxx" }, "call_id": "call-123" }
```

`identity` đi vào LiveKit participant metadata (worker dùng để chào/điền hồ sơ);
`call_id` dùng đặt tên room. Cả hai optional — thiếu thì mặc định `{}` / `"call"`.

- **Close code khi lỗi:**

| Code | Reason | Ý nghĩa |
|---|---|---|
| 4001 | `bad_credential` | Sai/không có credential, hoặc credential của tenant khác |
| 4004 | `unknown_route` | Path khác `/v1/voice` và `/v1/chat` |
| 4008 | `handshake_timeout` | Không gửi frame handshake trong 10s |

## 2. Mô hình frame — phân biệt bằng LOẠI frame WS

| Loại frame | Chiều | Nội dung |
|---|---|---|
| **BINARY** | client → gateway | Audio khách: **PCM16 mono 16 kHz**, raw không header. Khuyến nghị frame 20 ms (640 byte). |
| **BINARY** | gateway → client | Audio agent: **PCM16 mono 24 kHz** (rate TTS), raw không header. Phát/ghép tuần tự. |
| **TEXT** | client → gateway | *Reserved* — hiện gateway **bỏ qua** (trừ frame handshake đầu tiên). |
| **TEXT** | gateway → client | **JSON event** — mục 3. Mỗi frame = đúng một object JSON UTF-8. |

Client cũ chỉ đọc binary vẫn chạy y nguyên (backward-compatible).

> **Thời gian thực, không xếp hàng (2026-08-26).** Gateway đọc audio khách ngay sau
> handshake nhưng chỉ đẩy vào room khi worker đã sẵn sàng (~2–4 s sau khi mở WS).
> Audio gửi trong lúc đó **không được giữ lại** ngoài 300 ms cuối, và về sau bộ
> đệm chuyển tiếp cũng chỉ giữ tối đa 300 ms (drop-oldest) — nên độ trễ audio
> khách → pipeline không bao giờ vượt ~0,6 s. Client cứ stream mic từ đầu như
> bình thường; **đừng** tự đệm rồi bơm bù, phần bù sẽ bị cắt. Trước đó phần audio
> gửi sớm bị xếp hàng và thành lag cố định ~2 s cho cả cuộc gọi.

## 3. Catalog event (TEXT frame, gateway → client)

Mọi event là object có khóa `type`. Shape **giống hệt** browser transport / LiveKit data
channel — gateway relay nguyên văn, không thêm bớt field.

> **Bảo đảm delivery: best-effort.** Event đi qua queue giới hạn 256 phần tử,
> **đầy thì DROP** để không bao giờ chặn audio. UI không được dùng event làm
> tín hiệu điều khiển cuộc gọi (âm thanh + trạng thái WS mới là nguồn sự thật);
> event chỉ để hiển thị. Không bảo đảm đồng bộ thời gian chính xác với audio.

### 3.0 `session_id` — event ĐẦU TIÊN, luôn có

```json
{ "type": "session_id", "session_id": "anphu-call-123-1754899200000-9ab3" }
```

Gateway gửi **ngay sau handshake, trước mọi frame audio**. Đây là id phiên THẬT —
chính là tên room LiveKit (`gateway/livekit_bridge.py::room_name`), và cũng là
`session_id` mà worker ghi vào `tenant_data.conversations`
(`transport/livekit/worker.py`: `RoomSession(session_id=ctx.room.name)`).

⚠️ **KHÔNG suy được từ `call_id` bạn gửi**: `room_name()` gắn thêm timestamp ms +
hậu tố ngẫu nhiên sinh Ở SERVER. Muốn ghi feedback cuối phiên
(`POST /api/v1/agent/feedback` của Portal) hay tra lại hội thoại thì phải lưu giá
trị ở event này. Cùng shape với `/v1/chat` (`server/ws_handler.py`) — một handler
dùng cho cả hai kênh.

Khác `/v1/chat` một điểm: bên chat, worker sinh id và gửi; bên voice không có hop
trực tiếp gateway→worker (dispatch qua LiveKit Cloud) nên **gateway** là chỗ duy
nhất biết id, và nó gửi frame này.

### 3.1 Transcript lời KHÁCH

```json
{ "type": "partial_transcript", "text": "tôi muốn hỏi về dự" }
{ "type": "transcript", "text": "tôi muốn hỏi về dự án noble crystal", "turn_id": "<uuid>", "stt_ms": 480 }
```

- `partial_transcript` — kết quả STT tạm, bắn nhiều lần khi khách đang nói; **thay thế**
  (overwrite) bản trước đó trên UI, không append.
- `transcript` — bản chốt của lượt nói, mở đầu một turn. `stt_ms` (optional) = độ trễ STT.

### 3.2 Lời AGENT

```json
{ "type": "agent_speaking", "text": "Em chào anh chị, em là Luna...", "turn_id": "greeting" }
{ "type": "agent_speaking", "text": "Dạ, dự án Noble Crystal nằm ở Tây Hồ ạ.", "turn_id": "<uuid>", "sentence_id": 0, "ttfb_ms": 210 }
```

- Bắn **theo từng mệnh đề/câu**, ngay trước khi audio của câu đó phát — KHÔNG per-token.
  UI append các `agent_speaking` cùng `turn_id` thành một bong bóng.
- `sentence_id` (int, tăng dần trong turn) + `ttfb_ms` (optional): chỉ có ở turn thường.
- `turn_id` đặc biệt: `"greeting"` (câu chào khi worker join), `"idle_0"` / `"idle_1"`
  (câu nhắc khi khách im lặng lâu / câu tạm biệt trước khi tự đóng phiên) — các event này
  **không có** `sentence_id`.

### 3.3 Kết thúc lượt / ngắt lời

```json
{ "type": "agent_done", "turn_id": "<uuid>", "metrics": { "llm_ttft_ms": 350, "llm_total_ms": 2100, "interrupted": false } }
{ "type": "agent_done", "turn_id": "greeting" }
{ "type": "agent_interrupted", "turn_id": "<uuid>", "last_completed_sentence_id": 1 }
```

- `agent_done` — turn kết thúc. Biến thể greeting/idle không có `metrics`.
  Khóa trong `metrics` là optional (chỉ có khi đo được): `llm_ttft_ms`, `llm_total_ms`,
  `interrupted` (bool).
- `agent_interrupted` — khách ngắt lời; audio agent dừng.
  `last_completed_sentence_id` = `sentence_id` cuối đã phát trọn (`-1` nếu chưa câu nào) —
  UI có thể cắt bong bóng agent về đúng câu đó.
- Sau `agent_interrupted` vẫn có `agent_done` (với `metrics.interrupted: true`).

### 3.4 Tool

```json
{ "type": "tool_start", "tool": "kb_search", "args": { "query": "tiện ích noble crystal" } }
{ "type": "tool_done", "tool": "kb_search" }
```

- Hiện "đang tra cứu…" giữa `tool_start` và `tool_done`.
- **Voice `tool_done` KHÔNG mang `result`** (khác kênh chat). Kết quả media đi qua event
  `media` riêng (3.5); kết quả khác chỉ thể hiện qua lời agent.

### 3.5 Media (ảnh / video dự án)

Bắn khi tool trả về payload có `items[]` (thực tế: tool `send_media`):

```json
{
  "type": "media",
  "ok": true,
  "project_name": "Noble Crystal",
  "caption": "Hình ảnh dự án Noble Crystal",
  "count": 4,
  "message": "Dạ em gửi hình ảnh dự án qua app cho anh/chị rồi ạ.",
  "items": [
    { "kind": "image", "url": "https://...", "label": "Phối cảnh tổng thể", "thumb": "https://..." },
    { "kind": "video", "video_id": "dQw4w9WgXcQ", "title": "Video giới thiệu" }
  ]
}
```

- `items[].kind = "image"` → `url` (ảnh gốc), `label`, `thumb` (optional).
  `kind = "video"` → `video_id` (YouTube id), `title`.
- Có thể nhiều video (tối đa 3 khi khách xin video) — **iterate toàn bộ `items`**, đừng lấy
  cái đầu rồi bỏ. Chi tiết render + biến thể `no_media`
  (`{"ok": false, "items": [], "note": "no_media", ...}`): xem
  [noblex-app-dev-guide.md §4](noblex-app-dev-guide.md).

### 3.6 Lifecycle / lỗi

```json
{ "type": "error", "message": "STT chain failed to connect: tried ['soniox', 'sherpa']" }
{ "type": "session_ended", "reason": "idle_timeout" }
```

- `error` — lỗi phía worker (STT chết, lỗi turn); phiên có thể vẫn tiếp tục.
- `session_ended` — worker tự đóng phiên (hiện chỉ `idle_timeout`). Sau đó room giải tán →
  gateway đóng WS.

## 4. Trình tự một cuộc gọi điển hình

```
client                          gateway → client (TEXT trừ khi ghi BINARY)
──────                          ──────────────────────────────────────────
connect + Bearer
{"identity":...,"call_id":...}
                                {"type":"session_id","session_id":"<tenant>-<call_id>-<ms>-<hex>"}
                                {"type":"agent_speaking","turn_id":"greeting",...}
                                BINARY audio (greeting)
                                {"type":"agent_done","turn_id":"greeting"}
BINARY audio khách (liên tục)
                                {"type":"partial_transcript",...} ×N
                                {"type":"transcript","turn_id":T,...}
                                {"type":"tool_start",...} / {"type":"tool_done",...}   (nếu có)
                                {"type":"media",...}                                   (nếu có)
                                {"type":"agent_speaking","turn_id":T,"sentence_id":0,...}
                                BINARY audio agent ...
                                {"type":"agent_speaking","turn_id":T,"sentence_id":1,...}
                                BINARY audio agent ...
                                {"type":"agent_done","turn_id":T,"metrics":{...}}
(lặp các turn tiếp theo; khách ngắt lời → agent_interrupted chen vào)
close ws = cúp máy
```

## 5. Quy tắc phòng thủ cho frontend

1. **Bỏ qua `type` lạ** — event mới có thể được thêm; parse fail / type không biết → skip.
2. **Mọi field ngoài `type` coi là optional** khi parse (nhiều field chỉ có ở một biến thể).
3. Không suy ra trạng thái cuộc gọi từ event (có thể bị drop khi nghẽn) — chỉ dùng để render.
4. Audio và event là hai luồng độc lập về thời gian; muốn "karaoke-sync" tuyệt đối thì
   không có bảo đảm, chỉ có thứ tự tương đối (event câu N tới trước audio câu N).

## 6. Tham chiếu code (nguồn sự thật khi nghi ngờ spec lệch)

| Gì | Ở đâu |
|---|---|
| Bridge + relay event | `src/noble_agent/gateway/server.py::_bridge_voice`, `enqueue_event`, `_pump_agent_events` |
| `session_id` (§3.0) — dựng frame + tên room | `src/noble_agent/gateway/livekit_bridge.py::session_id_frame`, `::room_name` |
| Emit event turn (transcript/agent_speaking/tool/media/interrupted/done) | `src/noble_agent/voice/voice_agent.py` |
| Emit partial_transcript / idle / session_ended / error | `src/noble_agent/server/base_session.py` |
| Payload media | `src/noble_agent/agent/tools/support_ops.py` (send_media), `src/noble_agent/data/media_data.py` |
| Smoke e2e | `scripts/smoke_gateway_voice.py` (in event dạng `[control] {...}`) |
