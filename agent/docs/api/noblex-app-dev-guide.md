# NobleX App ↔ Luna Agent — Hướng dẫn tích hợp DEV (app gọi thẳng, không qua backend NobleX)

> **Phạm vi:** chế độ tạm cho dev/test. App Flutter gọi thẳng endpoint provisioning của agent
> (thay vai backend NobleX). Lên production chỉ dời đúng **một** call này về backend NobleX
> (backend giữ key, app nhận kết quả qua API riêng của NobleX) — **phần connect chat/voice của
> app giữ nguyên không đổi**.
>
> Contract đầy đủ: `docs/system-design/08-api-contracts-websocket-http.md` §2.6.

## 0. Điều kiện

- **AGENT_HOST dev chuẩn: `10.50.12.70:8766`** (server nội bộ, đã set sẵn key + chạy đủ agent/agent-lk).
- Điện thoại cùng **Wi-Fi công ty / VPN** với server (provisioning + chat WS đi qua LAN).
  Voice **media** chạy qua LiveKit Cloud (public) — chỉ bước provisioning cần LAN.
- Nếu trỏ host khác (vd máy dev cá nhân), host đó phải set trong `.env`: `NOBLE_APP_API_KEY`,
  `APP_WS_PUBLIC_BASE=ws://<LAN-IP>:8766`, và LiveKit (`LIVEKIT_URL/API_KEY/API_SECRET`) nếu test voice.
  Voice cần worker `agent-lk` đang chạy trên cùng LiveKit project.
- ⚠️ Key chỉ nhúng vào **dev build**. Không ship key trong bản release — prod đổi key + chuyển call về backend.

## 1. Provisioning (chung cho cả 2 kênh)

```
POST http://<AGENT_HOST>:8766/api/v1/app/session
Header: X-Noble-App-Key: <NOBLE_APP_API_KEY>
        Content-Type: application/json
```

```json
{
  "noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb",
  "channel": "chat",
  "identity": {
    "full_name": "Lê Viết Thúy Nga",
    "phone": "0378764303",
    "gender": "Female",
    "is_noble_customer": false,
    "email": "ngalvt@noblex.vn",
    "birthday": "25/02/1997",
    "noble_info": "..."
  }
}
```

- `noble_user_id` (bắt buộc): `data.userId` từ `Profile_GetProfileInfo`. `identity.*` đều optional —
  map từ cùng response (`fullName/phone/sex/isUserNoble/nobleInfo/email/birthday`).
- `channel`: `"chat"` (default) hoặc `"voice"`.
- **chat:** `session_id` derive ổn định từ `noble_user_id` → cùng user quay lại là **cùng phiên
  hội thoại** (Luna nhớ context, TTL Redis). Gọi lại nhiều lần an toàn (merge identity, không blank
  field cũ).
- **voice:** mỗi lần provision cấp một `room`/`session_id` **MỚI** (derived id + timestamp), nên **mỗi
  cuộc gọi là một phiên riêng** (không nối tiếp hội thoại cuộc trước; Luna vẫn nhận diện khách qua
  identity đã seed + trí nhớ theo số điện thoại). Đây là chủ ý: room cố định khiến LiveKit bỏ qua
  agent-dispatch khi gọi lại → không có agent. Room mới mỗi lần đảm bảo agent luôn được dispatch.
- Lỗi: `400` thiếu `noble_user_id` · `401` sai key · `405` không phải POST ·
  `503 app_api_disabled` (server chưa set key) · `503 livekit_not_configured` (voice, thiếu LiveKit).

### Response `channel=chat`

```json
{
  "session_id": "app-6cb7cc1dd5d0",
  "channel": "chat",
  "ws_url": "ws://10.50.12.70:8766/chat?session=app-6cb7cc1dd5d0&token=...",
  "connect_token": "...",
  "expires_in": 120
}
```

### Response `channel=voice`

```json
{
  "session_id": "app-6cb7cc1dd5d0-1720000000000-a1b2",
  "channel": "voice",
  "livekit_url": "wss://<project>.livekit.cloud",
  "livekit_token": "<JWT — room + agent dispatch đã nhúng sẵn>",
  "room": "app-6cb7cc1dd5d0-1720000000000-a1b2"
}
```

> **`room`/`session_id` voice là duy nhất mỗi lần provision** (khác chat vốn cố định). App chỉ cần
> dùng `room`/`livekit_token` để connect như bên dưới — không cần và không nên cache lại giữa các cuộc.

**Token nào cũng ngắn hạn** (`connect_token` TTL 120 s) → connect ngay sau khi provision;
mỗi lần mở bubble thì provision lại (nhẹ, idempotent).

## 2. Kênh CHAT — WebSocket

Mở WS tới `ws_url` nhận được. Protocol JSON text:

**App gửi:**

| Message | Ý nghĩa |
|---|---|
| `{"type":"user_text","text":"..."}` | chạy một lượt hội thoại |
| `{"type":"reset"}` | xoá lịch sử phiên |

**Server gửi (theo thứ tự stream):**

| Event | Ý nghĩa |
|---|---|
| `{"type":"session_id","session_id":...}` | ngay khi connect |
| `{"type":"user_text",...}` | echo lượt user |
| `{"type":"token","text":"..."}` | từng mẩu text trả lời — append để render streaming |
| `{"type":"tool_start"/"tool_done",...}` | agent đang tra cứu. **`tool_done` có thể kèm ảnh/video** (`result.items[]`) → render thẻ media như demo. Xem §4. |
| `{"type":"done", ...}` | hết lượt |
| `{"type":"suggestions","items":[{"label","text"}]}` | gợi ý follow-up (quick-reply chips), **gửi SAU `done`**. `label` = chữ trên nút, `text` = câu gửi đi khi bấm chip (như một `user_text`). **Có thể không có** event này nếu không có gợi ý phù hợp (khách chào tạm biệt / đã chuyển chuyên viên / đã chốt lịch). Voice: **TBD** (đợt sau). |
| `{"type":"error","message":...}` | lỗi lượt |

Flutter (dùng `web_socket_channel`):

```dart
final resp = await http.post(
  Uri.parse('http://$agentHost:8766/api/v1/app/session'),
  headers: {'X-Noble-App-Key': devKey, 'Content-Type': 'application/json'},
  body: jsonEncode({
    'noble_user_id': user.id,
    'channel': 'chat',
    'identity': {'full_name': user.fullName, 'phone': user.phone, 'gender': user.sex},
  }),
);
final ws = WebSocketChannel.connect(Uri.parse(jsonDecode(resp.body)['ws_url']));

ws.stream.listen((raw) {
  final ev = jsonDecode(raw as String);
  switch (ev['type']) {
    case 'token': appendToBubble(ev['text']); break;
    case 'done': finishTurn(); break;
    case 'error': showError(ev['message']); break;
  }
});
ws.sink.add(jsonEncode({'type': 'user_text', 'text': userInput}));
```

## 3. Kênh VOICE — LiveKit

Dùng package [`livekit_client`](https://pub.dev/packages/livekit_client). Token đã nhúng sẵn
room + agent dispatch — app chỉ cần connect + bật mic; agent tự join room (đã verify: join < 5 s).

```dart
final resp = await http.post(/* như trên, channel: 'voice' */);
final d = jsonDecode(resp.body);

final room = Room();
await room.connect(d['livekit_url'], d['livekit_token']);
await room.localParticipant?.setMicrophoneEnabled(true);
// Audio của agent tự phát khi track subscribe; lắng nghe event nếu cần UI trạng thái:
room.events.listen((e) {
  if (e is ParticipantConnectedEvent) { /* agent đã vào phòng */ }
  if (e is TrackSubscribedEvent) { /* agent bắt đầu nói */ }
});
// Kết thúc: await room.disconnect();
```

iOS cần `NSMicrophoneUsageDescription`; Android cần `RECORD_AUDIO` + foreground service nếu giữ call khi background.

### 3.1 Lấy text STT + TTS qua data channel

Audio (mic khách ↔ giọng Luna) chạy qua **LiveKit media track** — LiveKit tự lo, app không đụng.
Còn **toàn bộ TEXT** (lời khách do STT nhận ra + lời Luna đang đọc) agent đẩy song song qua
**LiveKit data channel**, topic **`agent-events`**, dạng JSON UTF-8.

> **App KHÔNG cần gọi STT/TTS riêng.** STT text và TTS text đã có sẵn trong các event dưới đây —
> chỉ cần subscribe data channel và route theo `type`.

**Cách nghe (một chỗ duy nhất):**

```dart
room.events.on<DataReceivedEvent>((e) {
  if (e.topic != null && e.topic != 'agent-events') return;   // lọc đúng topic
  final Map<String, dynamic> msg = jsonDecode(utf8.decode(e.data));
  // -> route theo msg['type'] (bảng bên dưới)
});
```

**Danh mục event (đúng theo agent hiện tại):**

| `type` | Payload | Loại | Dùng để |
|---|---|---|---|
| `partial_transcript` | `{text}` | **STT** (tạm) | lời khách đang nói — **ghi đè** dòng subtitle mờ/typing |
| `transcript` | `{text, turn_id}` | **STT** (chốt) | lời khách đã chốt — **commit** thành 1 dòng thoại khách |
| `agent_speaking` | `{text, ttfb_ms, turn_id}` | **TTS text** | câu Luna đang đọc — **theo TỪNG CÂU** (không phải token). Mỗi event = **append** thêm 1 câu + bật trạng thái "đang nói" |
| `agent_done` | — | trạng thái | Luna đọc xong cả lượt → tắt "đang nói" |
| `agent_interrupted` | — | trạng thái | khách chen ngang (barge-in) → dừng/huỷ câu Luna đang hiện |
| `tool_start` | `{tool, args}` | trạng thái | badge "đang tra cứu…" |
| `tool_done` | `{tool}` | trạng thái | tra cứu xong — **CHỈ có tên tool, KHÔNG kèm `result`** (khác chat) |
| `media` | `{items[], caption, project_name, ...}` | media | ảnh/video → render thẻ (xem §4). **Ở voice, media về qua event `media` riêng — KHÔNG nằm trong `tool_done`** |
| `error` | `{message}` | lỗi | báo lỗi lượt |
| `session_ended` | `{reason}` | vòng đời | agent đóng phiên → kết thúc call |

**Quy tắc dựng UI hội thoại (STT + TTS):**

- **Lời khách (STT):** cập nhật liên tục theo `partial_transcript.text` (ghi đè cùng một dòng
  "đang nói"), đến khi nhận `transcript.text` thì chốt dòng đó.
- **Lời Luna (TTS):** mỗi `agent_speaking` là **một câu hoàn chỉnh** → nối tiếp nhau thành đoạn
  trả lời của Luna. `ttfb_ms` = độ trễ tới câu đầu (dùng cho metrics/UX, không bắt buộc hiển thị).
  Khi `agent_done` → coi như Luna nói hết. Nếu `agent_interrupted` tới giữa chừng → dừng nối câu.

**Listener đầy đủ (STT + TTS + media):**

```dart
String? _partial;   // dòng khách đang nói (tạm)

room.events.on<DataReceivedEvent>((e) {
  if (e.topic != null && e.topic != 'agent-events') return;
  final msg = jsonDecode(utf8.decode(e.data)) as Map<String, dynamic>;
  switch (msg['type']) {
    // ---- STT: lời khách ----
    case 'partial_transcript':
      _partial = msg['text'] as String?;
      showCustomerTyping(_partial);            // dòng mờ, ghi đè liên tục
      break;
    case 'transcript':
      commitCustomerLine(msg['text']);         // chốt thành 1 dòng
      _partial = null;
      break;

    // ---- TTS: lời Luna (theo TỪNG CÂU) ----
    case 'agent_speaking':
      appendAgentSentence(msg['text']);        // nối tiếp các câu
      setAgentSpeaking(true);
      break;
    case 'agent_done':
      setAgentSpeaking(false);
      break;
    case 'agent_interrupted':
      stopAgentSentence();                     // khách chen ngang
      break;

    // ---- trạng thái tra cứu ----
    case 'tool_start':
      showToolBadge(msg['tool'], msg['args']);
      break;
    case 'tool_done':
      hideToolBadge(msg['tool']);              // KHÔNG có result ở voice
      break;

    // ---- media ----
    case 'media':                              // xem §4 để render items[]
      final items = (msg['items'] as List?) ?? const [];
      if (items.isNotEmpty) renderMediaCard(msg);
      break;

    // ---- lỗi / kết thúc ----
    case 'error':
      showError(msg['message']);
      break;
    case 'session_ended':
      endCall(msg['reason']);
      break;
  }
});
```

Demo canonical: `static/livekit.html` → `renderEvent()` (map các `type` trên → `userSay`/
`agentSay`/`addCarousel`). Chi tiết parse media ở §4.3.

> **Khác biệt chat vs voice (dễ sai khi copy code giữa 2 kênh):**
> - **Text trả lời của Luna:** chat = `token` (token-by-token) · voice = `agent_speaking.text`
>   (theo từng câu, vì đã cắt câu để TTS).
> - **Media:** chat nằm **trong `tool_done.result`** (chuỗi JSON, §4.2) · voice về qua **event
>   `media` riêng** (voice `tool_done` chỉ có `{tool}`, §4.3).

## 4. Media — ảnh/video (`items[]`) hiển thị như demo

Khi agent gọi tool `send_media` (Luna chủ động gửi hình/mặt bằng/phối cảnh/video), nó trả về
một **payload media** để app render **thẻ ảnh/video** — y hệt phần demo (`static/chat.html`,
`static/livekit.html`). App **không tải byte ảnh về**: chỉ nhận URL/`video_id`, cho `<img>` /
WebView tải trực tiếp (nhanh, ngoài luồng hội thoại).

### 4.1 Payload / contract
```jsonc
{
  "ok": true,
  "project_name": "Alluvia Sunshine Marina",
  "caption": "Hình ảnh dự án Alluvia Sunshine Marina",   // chú thích trên thẻ
  "items": [
    { "kind": "image",
      "url":    "https://agent-cms.noble.vn/api/v1/projects/media/<id>/download?inline=true", // ảnh GỐC (có thể nhiều MB)
      "thumb":  "https://agent-cms.noble.vn/api/v1/projects/media/<id>/thumbnail",             // OPTIONAL — WebP ~1024px cho lưới
      "medium": "https://agent-cms.noble.vn/api/v1/projects/media/<id>/medium",                // OPTIONAL — WebP ~2048px cho lightbox
      "label": "Mặt bằng tầng 5" },
    { "kind": "video", "video_id": "abcABC12345", "title": "Phối cảnh dự án" },  // YouTube
    { "kind": "video",                                                              // KHÔNG phải YouTube (2026-08-25)
      "url":       "https://drive.google.com/file/d/<id>/view",                     // link gốc — mở tab mới/WebView
      "embed_url": "https://drive.google.com/file/d/<id>/preview",                  // OPTIONAL — có thì nhúng iframe được
      "thumb":     "https://drive.google.com/thumbnail?id=<id>&sz=w400",            // OPTIONAL — ảnh tile
      "title": "Tiến độ T5/2026" }
  ],
  "count": 3,
  "message": "Dạ em gửi hình ảnh dự án qua app cho anh/chị rồi ạ."   // câu Luna nói/đọc
}
```
- **image:** lưới ảnh — tile dùng `thumb ?? url`; chạm mở lightbox dùng **`medium ?? url`**
  (medium ~2048px ~vài trăm KB → mở nhanh; tránh tải ảnh gốc nhiều MB). Muốn ảnh gốc HD thì
  dùng `url`. `label` = chú thích dưới ảnh. Các URL là redirect **công khai** (không cần token, không hết hạn).
- **video:** HAI biến thể (2026-08-25) — nhận theo trường có mặt, không đoán theo host:
  - `video_id` → **YouTube**: thumbnail `https://img.youtube.com/vi/<video_id>/hqdefault.jpg`,
    phát bằng embed `https://www.youtube.com/embed/<video_id>` (WebView / YoutubePlayer).
  - `url` → video **không phải YouTube** (Google Drive, Vimeo, mp4…): có `embed_url` thì nhúng
    iframe/WebView bằng nó (Drive `/preview` phát được với link chia sẻ công khai); không có thì
    mở `url` ở tab mới/WebView. Tile dùng `thumb` nếu có, không có thì ô ▶ + `title`. Agent dựng
    `embed_url`/`thumb` sẵn cho Drive — app **không** cần biết luật Drive.
  - Thiếu CẢ `video_id` lẫn `url` → bỏ qua. **`items[]` có thể chứa nhiều video (tối đa 3 khi
  khách xin video) — app phải iterate toàn bộ `items` để render tất cả, KHÔNG được lấy video đầu
  tiên rồi bỏ phần còn lại.**
- **`thumb` optional — hiện agent KHÔNG gửi** (cờ `MEDIA_SEND_THUMB=false`): `thumb_url` phía
  ingest đang trỏ MinIO nội bộ nên app không tải được, gửi ra chỉ thành ảnh vỡ. App **cứ giữ
  `thumb ?? url`** như hợp đồng — khi thumbnail trỏ domain public, agent bật cờ và `thumb` tự
  xuất hiện lại (lưới nhẹ hơn), app **không phải sửa gì**. Tương tự với `medium`.
- **no_media:** không có ảnh → `{ "ok": false, "items": [], "note": "no_media", "message": "..." }`
  → **không render thẻ**, chỉ hiển thị/đọc `message`.

### 4.2 CHAT — media nằm trong `tool_done`
`result` của `tool_done` là **chuỗi JSON**; parse rồi kiểm `items[]`:
```dart
case 'tool_done':
  final result = ev['result'] is String ? jsonDecode(ev['result']) : ev['result'];
  final items = (result?['items'] as List?) ?? const [];
  if (items.isNotEmpty) renderMediaCard(result);   // ảnh + video như demo
  break;
```

### 4.3 VOICE — media qua event `media` (KHÔNG qua `tool_done`)
Khác chat: ở voice, `tool_done` **chỉ báo tên tool** (`{tool}`, không kèm `result`). Media về qua
một **event `media` riêng**, payload chính là contract §4.1 (`items[]`, `caption`, …) kèm `type:"media"`.
App bắt `DataReceivedEvent`, decode UTF-8, chỉ cần bắt `media`:
```dart
room.events.on<DataReceivedEvent>((e) {
  if (e.topic != null && e.topic != 'agent-events') return;
  final msg = jsonDecode(utf8.decode(e.data)) as Map<String, dynamic>;
  if (msg['type'] == 'media') {
    final items = (msg['items'] as List?) ?? const [];
    if (items.isNotEmpty) renderMediaCard(msg);   // ảnh + video như demo
  }
  // (các type khác — STT/TTS/trạng thái — xem §3.1)
});
```

### 4.4 Tham chiếu demo (canonical)
- Chat: `static/chat.html` → `addMediaCard(payload)` (lưới ảnh + lightbox + video card).
- Voice: `static/livekit.html` → `renderEvent()` → `addCarousel(payload)` / `openVideo()`.

Map `kind`→UI y như hai file trên là ra giao diện như demo.

> **Điều kiện để CÓ media:** cần bản agent đã deploy tính năng `send_media → items[]`
> (branch `fix/agent-improvements` / lần deploy kế). `thumb` nhẹ cần CMS bật web-thumbnail +
> backfill (repo `santa-agent-cms`, branch `feat/media-web-thumbnails`). Chưa deploy → agent
> chạy bản cũ, chưa gửi `items[]`.

## 5. Đã verify (2026-07-10, dev)

- Chat E2E: provision → WS connect bằng `ws_url` → 1 lượt thật — Luna chào đúng tên user đã seed.
- Voice E2E: provision `channel=voice` → join LiveKit Cloud bằng token → agent participant join < 5 s.
- Auth: sai key → `401`; chưa set key → `503`.

## 6. Chuyển sang production (checklist)

1. Call provisioning dời về backend NobleX (server-to-server, sau khi user đã đăng nhập); app nhận
   `{ws_url|livekit_url+token}` qua API của NobleX. Body/response **không đổi**.
2. Đổi `NOBLE_APP_API_KEY` (key dev coi như lộ vì nằm trong build).
3. Server bật `CHAT_WS_REQUIRE_TOKEN=true` (WS /chat bắt buộc connect-token).
4. Ops expose agent qua `wss://hotline-agent.noble.vn` (TLS) — `APP_WS_PUBLIC_BASE` trỏ domain public.
