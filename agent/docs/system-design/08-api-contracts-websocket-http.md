# 08 — API Contracts: WebSocket + HTTP

> Browser ↔ Agent communication. One WebSocket carries the full call (signaling JSON + WebRTC offer/answer + control messages). HTTP REST carries everything else: sessions list, bookings, sales summaries, outbound queue, CSV exports. Both terminate on port **8766** of the agent process.

Read [`00-architecture-overview.md`](00-architecture-overview.md) §5 first. The phone-side wire format lives in [`09-api-contracts-audiosocket-tools.md`](09-api-contracts-audiosocket-tools.md).

---

## 1. WebSocket — `/ws`

Single WebSocket connection per browser session. Both the WebRTC signaling channel and the agent control channel share this socket — there's no separate side-channel.

URL: `ws://<host>:8766/ws`

Lifecycle: client connects → agent sends `session_id` → client sends `rtc_offer` → agent answers → media flows over WebRTC peer connection (Opus 48 kHz). Control messages (interrupt, set_voice, set_customer, reset) keep flowing on the same WS during the call.

### 1.1 Message envelope

All WS messages are JSON objects with a string `type` discriminator.

```jsonc
{ "type": "<message-name>", ...payload }
```

Both directions use the same envelope. Unknown types are ignored (logged at DEBUG).

### 1.2 Server → client

| `type` | When | Payload |
|---|---|---|
| `session_id` | Right after connect | `{"session_id": "<UUID>"}` |
| `rtc_answer` | After client `rtc_offer` | `{"sdp": "<SDP>", "type": "answer"}` |
| `reset_ok` | Acks client `reset` | — |
| `voice_ok` | Acks client `set_voice` | `{"voice_id": "<id>"}` |
| `voices` | Reply to `list_voices` | `{"voices": ["voice-1", "voice-2", ...]}` |
| `customer_ok` | Acks client `set_customer` | `{"customer": {...resolved customer record...}}` |
| `partial` | Streaming STT partial | `{"text": "<partial transcript>"}` |
| `final` | STT final | `{"text": "<finalized transcript>"}` |
| `agent_token` | LLM token delta | `{"text": "<chunk>"}` |
| `agent_audio_started` | TTS started for current turn | — |
| `agent_audio_ended` | TTS done | — |
| `tool_start` | Tool call started | `{"name": "<tool>", "args": {...}}` |
| `tool_done` | Tool call returned | `{"name": "<tool>", "result": "..."}` — `result` là chuỗi JSON; có thể chứa `items[]` (ảnh/video) để render thẻ media (xem §2.6) |
| `agent_switch` | Persona switched | `{"target": "consultant"\|"support"\|"router"}` |
| `error` | Recoverable error | `{"error": "<short msg>", "code": "<id>"}` |

`session_id` always lands first — the client uses it as the Redis session key for any later HTTP calls (e.g. `GET /api/v1/sales/summaries?session_id=...`).

### 1.3 Client → server

| `type` | Purpose | Payload |
|---|---|---|
| `rtc_offer` | Initiate WebRTC peer | `{"sdp": "<SDP>", "type": "offer"}` |
| `set_voice` | Select TTS voice | `{"voice_id": "<id>"}` |
| `list_voices` | Ask available voices | — |
| `set_customer` | Pre-populate customer state | `{"phone": "0901234567", "name": "Anh A", "project_interest": "NCLB"}` |
| `interrupt` | Force barge-in (cancel TTS) | — |
| `reset` | Drop conversation history | — |

`set_customer` is what the browser uses when the operator already knows the caller (for outbound calls or warm hand-offs). The agent runs `project_catalog.normalize()` on `project_interest` before persisting.

### 1.4 Order-of-operations example

```
client  → ws connect /ws
server  ← {"type":"session_id","session_id":"abc-123"}

client  → {"type":"set_voice","voice_id":"vi-female-warm"}
server  ← {"type":"voice_ok","voice_id":"vi-female-warm"}

client  → {"type":"rtc_offer","sdp":"v=0\no=...","type":"offer"}
server  ← {"type":"rtc_answer","sdp":"v=0\no=...","type":"answer"}

      … WebRTC media flows …

server  ← {"type":"partial","text":"em muốn"}
server  ← {"type":"final","text":"em muốn xem dự án Lakeside"}
server  ← {"type":"agent_token","text":"Dạ "}
server  ← {"type":"agent_token","text":"em "}
server  ← {"type":"tool_start","name":"noble_search","args":{"query":"Lakeside","project_filter":"NCLB"}}
server  ← {"type":"tool_done","name":"noble_search","result":"Noble Crystal Long Biên..."}
server  ← {"type":"agent_token","text":"giúp anh tìm..."}
server  ← {"type":"agent_audio_started"}
      …
server  ← {"type":"agent_audio_ended"}

client  → {"type":"interrupt"}        ← user clicks barge-in button
server   (cancels TTS, `vad.set_idle()`)
```

### 1.5 WebRTC media

Once `rtc_offer` / `rtc_answer` complete, audio flows over the SRTP layer of the WebRTC peer connection — **NOT** over the WebSocket. The agent uses `aiortc` (when `TRANSPORT_BACKEND=aiortc`) or LiveKit (when `TRANSPORT_BACKEND=livekit`).

- **Outbound** (agent → browser): Opus encoded from 48 kHz PCM16, after the resampler (24→48). Detail: [`03-tts-and-audio.md`](03-tts-and-audio.md).
- **Inbound** (browser → agent): Opus decoded to 48 kHz PCM16, resampled to 16 kHz, fed into Silero VAD + STT. Detail: [`01-stt-and-vad.md`](01-stt-and-vad.md).

### 1.6 Errors & reconnect

The server closes the WS on:

- Idle ≥ 15 min (no client message AND no audio).
- Auth fail (when `WS_REQUIRE_AUTH=true`, unimplemented today).
- Unrecoverable backend error (Redis down, etc.) — server emits `error` JSON then closes 1011.

The client should reconnect with exponential backoff. **Sessions don't survive reconnect** by default — the new socket gets a fresh `session_id`. To resume, the client must `set_customer` again with the old phone.

---

## 2. HTTP REST — `/`

Same port as WebSocket (8766). Routes mounted on the same `websockets.asyncio.server.serve` instance via the `_websockets_post_patch.py` shim that allows POST/OPTIONS (the upstream library rejects non-GET at parse level).

Standard `Content-Type: application/json` for both request and response. CORS is permissive (`Access-Control-Allow-Origin: *`) by default — restrict in production.

### 2.1 Routes — sales summaries (CRM hand-off)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/sales/handoff` | Realtime push: agent finished a sale-relevant call, post the summary to CRM |
| `GET` | `/api/v1/sales/summaries?phone=&limit=` | List summaries by phone number |
| `GET` | `/api/v1/sales/summaries/{id}` | Single summary detail |
| `POST` | `/api/v1/sales/summaries/{id}/mark_followed_up` | Operator marks "I called this lead back" |

`POST /api/v1/sales/handoff` body:

```json
{
  "session_id": "abc-123",
  "phone": "0901234567",
  "customer_name": "Anh A",
  "project_interest": "NCLB",
  "summary": "Anh A quan tâm 2PN Lakeside, ngân sách 5tỷ, hẹn xem chiều mai",
  "next_action": "schedule_viewing",
  "next_action_eta": "2026-05-07T14:00:00+07:00",
  "transcript_preview": "..."
}
```

Response: `{"id": "summary-xyz", "status": "queued"}`.

### 2.2 Routes — bookings

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/bookings` | Query bookings with filters (`phone`, `status`, `from`, `to`, `limit`) |
| `GET` | `/bookings/{id}` | Single booking |
| `POST` | `/bookings/{id}/mark_contacted` | Operator marks "I called this booking" |
| `GET` | `/bookings/export.csv` | CSV dump (capped at 10 k rows) |
| `GET` | `/summaries/export.csv` | CSV dump of summaries |

Filter params: ISO 8601 dates, `limit` defaults to 100, max 1000. Beyond 1000, use the CSV export.

### 2.3 Routes — outbound calls (when `HOTLINE_OUTREACH_ENABLED=true`)

Source: `src/noble_agent/server/outbound_endpoints.py`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/queue` | List pending outbound jobs |
| `GET` | `/brief/{phone}` | Get agent brief (instructions + customer context) for a phone |
| `POST` | `/brief/{phone}/instructions` | Set/replace brief instructions |
| `POST` | `/call` | Trigger outbound call now |

`POST /call` body:

```json
{
  "phone": "0901234567",
  "from_user": "operator-1",
  "instructions": "Gọi xác nhận lịch xem chiều mai",
  "max_attempts": 3
}
```

Response: `{"call_id": "...", "status": "originated"}`.

When the feature is **disabled** (`HOTLINE_OUTREACH_ENABLED=false`), all outbound endpoints return **HTTP 503** with a clear message — even if the caller forgets to gate them.

### 2.4 Routes — admin / health

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness — returns `{"status":"ok"}` if process is up |
| `GET` | `/readyz` | Readiness — checks Redis + Mongo + LLM key + STT WS health |
| `GET` | `/version` | Build SHA + dirty flag |
| `GET` | `/metrics` | Prometheus-style scrape (basic counters) |

`/readyz` returns 503 if any dependency is down. Use this in your container orchestrator's readiness probe.

### 2.5 Routes — static + browser tester

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Static `index.html` — minimal browser tester |
| `GET` | `/static/<path>` | JS / CSS for the tester |

Static assets live in `src/noble_agent/server/static/` (committed). Use this as a reference client when building a real UI.

### 2.6 Routes — NobleX app session (server-to-server)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/app/session` | `X-Noble-App-Key` | Backend NobleX provision phiên: seed identity + mint connect-token |

Body:
```json
{"noble_user_id":"<uuid>","channel":"chat","identity":{"full_name":"...","phone":"...","gender":"Female","is_noble_customer":false,"noble_info":"...","email":"...","birthday":"..."}}
```
Response: `{"session_id","channel","ws_url","connect_token","expires_in"}`.

WS `/chat` chỉ chấp nhận `?token=<connect_token>` khi `CHAT_WS_REQUIRE_TOKEN=true` (prod); sai/thiếu → close `4401`. Identity là server-authoritative (client không gửi `set_customer`).

Errors: `503` nếu `NOBLE_APP_API_KEY` chưa cấu hình · `401` nếu key sai/thiếu · `405` nếu method ≠ POST.

`session_id` suy ra ổn định (resumable) từ `noble_user_id`: `"app-" + 12 ký tự hex đầu` (bỏ dấu `-`, lowercase) → cùng user luôn cùng `session_id`, giữ lịch sử hội thoại (dùng chung cho cả chat và voice phase sau).

Settings liên quan: `NOBLE_APP_API_KEY` (key auth), `CHAT_WS_REQUIRE_TOKEN` (bật gate WS `/chat`), `APP_CONNECT_TOKEN_TTL_SECONDS` (TTL connect-token, mặc định 120), `APP_WS_PUBLIC_BASE` (base wss ghép vào `ws_url`; trống → `ws_url` là path).

**Voice channel** (`channel: "voice"`): response thay chat fields bằng `{"session_id","channel":"voice","livekit_url","livekit_token","room"}` (`room == session_id`). App dùng `livekit_client.connect(livekit_url, livekit_token)`; token nhúng `RoomAgentDispatch(agent_name)` nên LiveKit tự đưa agent vào room, và Customer đã seed theo `session_id` → agent chào đích danh. `503 livekit_not_configured` nếu LiveKit key/secret trống. `GET /livekit/token` chỉ bật khi `LIVEKIT_TOKEN_PUBLIC=true` (dev tester), prod dùng đường provisioning này.

**Media (ảnh/video) — cả 2 kênh:** khi Luna gọi `send_media`, event `tool_done` mang `result.items[]` (chat: qua WS message; voice: qua LiveKit **data channel** topic `agent-events`, bắt `DataReceivedEvent`) → app render thẻ ảnh/video như demo. `items[]`: ảnh `{kind:"image",url,thumb?,label}`, video YouTube `{kind:"video",video_id,title}`; payload kèm `caption`/`project_name`/`message`. Contract đầy đủ + snippet Flutter: `docs/api/noblex-app-dev-guide.md` §4.

---

## 3. Auth

Currently **none** on either WebSocket or HTTP. (Ngoại lệ: endpoint NobleX app `POST /api/v1/app/session` yêu cầu header `X-Noble-App-Key`, và WS `/chat` yêu cầu connect-token khi `CHAT_WS_REQUIRE_TOKEN=true` — xem §2.6.) Production deployments rely on:

1. Network ACLs (only operator VPN can reach 8766).
2. CORS origin whitelist (when locked down).
3. Reverse proxy (nginx) doing the actual auth — the agent trusts whatever it sees.

If you front the agent with nginx + bearer-auth, set `WS_HOST=127.0.0.1` so the agent only accepts loopback connections.

Future plan (`src/noble_agent/server/rate_limit.py` is a placeholder):

- HMAC-signed session tokens for WS connect.
- Per-phone rate limiting on `/call` (3/hour by default).

---

## 4. CORS + preflight

Default CORS headers (`server/http.py:58`):

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

Set `CORS_ALLOW_ORIGINS=https://operator.noble.vn` in `.env` to restrict.

The `_websockets_post_patch.py` is **load-bearing** — without it, every POST endpoint here fails at the websockets library's parse level (it rejects non-GET method tokens). Don't remove the side-effect import at the top of `http.py`.

---

## 5. Sample browser session — JS pseudocode

```js
const ws = new WebSocket("ws://localhost:8766/ws");
let sessionId = null;
const pc = new RTCPeerConnection();

ws.onmessage = async (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "session_id") {
    sessionId = msg.session_id;
    // Negotiate WebRTC after we have session_id
    pc.addTrack(localMicTrack);
    pc.ontrack = (ev) => attachToAudioElement(ev.streams[0]);
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    ws.send(JSON.stringify({type: "rtc_offer", ...offer}));
  } else if (msg.type === "rtc_answer") {
    await pc.setRemoteDescription(msg);
  } else if (msg.type === "agent_token") {
    appendToTranscript(msg.text);
  } else if (msg.type === "tool_start") {
    showToolBadge(msg.name);
  }
};

document.querySelector("#barge").onclick = () => {
  ws.send(JSON.stringify({type: "interrupt"}));
};
```

Real implementation: `src/noble_agent/server/static/`.

---

## 6. Versioning

API version lives in the URL path for HTTP (`/api/v1/...`). WebSocket has no version on the URL — the message envelope's `type` field is the surface, and we evolve by:

- Adding new `type` values (clients ignore unknown).
- Never changing the meaning of an existing `type`.
- Dropping a `type` requires a major-version bump (and adding `/api/v2/ws`).

Today only `/api/v1` exists. WS is at v1 implicitly.

---

## 7. Common debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| WS connects then immediately closes 1011 | Redis / Mongo down | Check `/readyz` |
| Browser hears no audio | WebRTC ICE failed | Check NAT / TURN config; aiortc default uses host candidates only — add STUN if not LAN |
| `final` text correct but agent says nothing | LLM call failed silently | Check server logs for retry warnings; `error` event should fire |
| `interrupt` doesn't barge in | TTS already drained final chunk | Normal. Barge-in cancels future chunks, not the in-flight 20 ms frame |
| `set_customer` rejected | `project_interest` is an alias not in catalog | Use canonical 4-char code (NCLB / NPLB / NCTH / NTTL / SSLC) |
| `/api/v1/sales/handoff` returns 404 | Served by aiohttp / FastAPI in front of agent? | This is on the agent itself; route exists; check WS_PORT env |
| CORS preflight fails for POST | Forgot the `_websockets_post_patch` import | First line of `http.py` must be that side-effect import |

---

## 8. References

- websockets library: https://websockets.readthedocs.io
- WebRTC + aiortc: https://aiortc.readthedocs.io
- LiveKit (alternative transport): https://docs.livekit.io
- `src/noble_agent/server/static/index.html` — minimal reference client

Continue → [`09-api-contracts-audiosocket-tools.md`](09-api-contracts-audiosocket-tools.md) for the binary protocols (AudioSocket + tool schemas).
