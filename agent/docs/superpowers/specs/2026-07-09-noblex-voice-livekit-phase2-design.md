# NobleX app — Phase 2: Voice qua LiveKit

**Ngày:** 2026-07-09
**Branch:** `feat/app-integration` (tiếp nối Phase 1 chat)
**Phạm vi (agent repo):** `server/app_session.py` (nhánh `channel="voice"` + helper mint LiveKit token), `server/http.py` (gate `/livekit/token`), `config.py` (1 setting), tests. **KHÔNG đụng:** `transport/livekit/worker.py` / `room_session.py` / `base_session.py` (đã xác minh không cần sửa), agent core, audio pipeline, Luna prompt.
**Ngoài repo này:** Flutter client (LiveKit SDK `livekit_client`) + hạ tầng LiveKit public (runbook, ops làm).

## Bối cảnh

Phase 1 (chat) đã xong trên nhánh này: `POST /api/v1/app/session` provision phiên (seed identity vào Redis + connect-token), app nối WS `/chat` thẳng. Phase 2 thêm kênh **voice**: cùng endpoint provisioning trả thêm **LiveKit access token** để app join room; agent chạy trong room và nói chuyện real-time.

**Xác minh code (2026-07-09):**
- `worker.py::entrypoint` tạo `RoomSession(session_id = ctx.room.name)`; `RoomSession` (subclass `BaseSession`) greet qua `_run_greeting → agent.greet(session_id)`. Mọi turn/greeting load state theo `session_id`. ⇒ **Nếu provisioning seed Customer theo `session_id` và token đặt `room = session_id`, worker tự load đúng identity — KHÔNG sửa worker.** (Đây là lý do chọn `room = session_id`.)
- **Gap phát hiện:** `worker.py` set `agent_name=settings.livekit_agent_name` ⇒ LiveKit dùng **explicit dispatch** — agent không tự join room. Toàn bộ `src/` + `static/` **không có code dispatch** (`RoomAgentDispatch`/`create_dispatch`/`room_config`). Hiện agent chỉ vào room qua **SIP trunk dispatch rule** (telephony). Client WebRTC (app / browser tester) join room thì **agent không vào** — endpoint `GET /livekit/token` mint token không kèm dispatch nên vô dụng cho client. Phase 2 phải thêm dispatch.
- SDK khả dụng: `livekit.api` có `AccessToken.with_room_config`, `RoomConfiguration`, `RoomAgentDispatch` (verified trong `.venv`).

**Hạ tầng (chốt scope):** `hotline-agent.noble.vn → 10.50.12.70` (IP LAN nội bộ, RFC1918); probe `/health`, `/livekit/token`, `/` từ mạng ngoài đều ERR. ⇒ App 4G **chưa** tới được agent/LiveKit (Phase 1 chat cũng vậy). Phase 2 giao **code agent-side (build + unit-test ngay) + runbook infra**; **e2e từ mobile hoãn** tới khi ops expose public.

## Quyết định đã chốt (brainstorm 2026-07-09)

| Vấn đề | Chốt |
|---|---|
| Nguồn identity cho voice | Redis seed theo `session_id` (y hệt chat) → worker tự load. KHÔNG dùng dispatch metadata. |
| Dispatch | **(A) Nhúng `RoomAgentDispatch` vào LiveKit token** (`with_room_config`). Không gọi dispatch API riêng. |
| `/livekit/token` public | Gate sau setting `LIVEKIT_TOKEN_PUBLIC` (default `false`); dev bật để dùng browser tester. |
| Sửa worker? | Không — `session_id = room.name` + greet-by-session đã đủ. |
| Infra | Runbook trong spec (ops thực thi); repo không đụng hạ tầng. |

## Kiến trúc / luồng voice

```
Flutter app (bubble → Voice)
  │  user đã login NobleX
  ▼
NobleX backend ──POST /api/v1/app/session {channel:"voice", noble_user_id, identity}──▶ Agent
                                                                                         │ seed Customer (Redis, theo session_id)
                                                                                         │ mint LiveKit token (room=session_id, +RoomAgentDispatch)
                                    ◀── {session_id, channel:"voice", livekit_url, livekit_token, room} ──
  ◀── {livekit_url, livekit_token, room} ── backend
  │
  ▼  Flutter livekit_client.connect(livekit_url, livekit_token)
LiveKit server ── room=session_id ── participant join
  │ token mang RoomAgentDispatch → LiveKit dispatch agent-lk vào room
  ▼
agent-lk worker::entrypoint → RoomSession(session_id = room.name = "app-…")
  → BaseSession greet + turns load Customer đã seed (đích danh)
```

## 1. `provision_session` — nhánh `channel="voice"`

Mở rộng hàm đã có (Phase 1). Seed Customer **giống hệt** chat (cùng `_derive_session_id`, cùng merge truthy vào Redis) — chỉ khác phần token trả về, rẽ theo `channel`:

- `channel == "chat"` (mặc định, hiện có): mint connect-token + trả `{session_id, channel, ws_url, connect_token, expires_in}`.
- `channel == "voice"`: mint **LiveKit token** (mục 2) + trả `{session_id, channel:"voice", livekit_url, livekit_token, room}`. **Không** mint connect-token/ws_url (không dùng cho voice).

`room = session_id` (`_derive_session_id(noble_user_id)`, ổn định/resumable — cùng user cùng room). Nếu LiveKit chưa cấu hình (`livekit_api_key`/`secret` rỗng) → trả `503 {"error":"livekit_not_configured"}`.

## 2. Mint LiveKit token + nhúng dispatch (phương án A)

Helper mới trong `app_session.py`, dùng chung cho cả nhánh voice của provisioning **và** endpoint `/livekit/token`:

```
_mint_livekit_token(session_id, identity, name) -> (token, url, room)
  AccessToken(livekit_api_key, livekit_api_secret)
    .with_identity(identity)                 # identity = f"user-{session_id}" (khác agent, ổn định theo phiên)
    .with_name(name or identity)
    .with_grants(VideoGrants(room_join=True, room=session_id,
                             can_publish=True, can_subscribe=True, can_publish_data=True))
    .with_room_config(RoomConfiguration(
        agents=[RoomAgentDispatch(agent_name=settings.livekit_agent_name)]))
  url = settings.livekit_public_url or settings.livekit_url
  room = session_id
```

`RoomAgentDispatch(agent_name=...)` là mảnh khiến LiveKit dispatch `agent-lk` vào đúng room khi participant join — chính là cái đang thiếu. Không cần credential ngoài `api_key/secret` sẵn có, không round-trip phụ.

## 3. Gate `/livekit/token`

`GET /livekit/token` (http.py) hiện mở + không dispatch. Đổi:
- Dùng chung `_mint_livekit_token` (nay CÓ dispatch) → sửa luôn "browser tester không có agent".
- Gate sau `settings.livekit_token_public` (default `false`): `false` → `503 {"error":"livekit_token_disabled"}`; `true` → mint (dev). Prod dùng provisioning nên để `false`.
- Vẫn giữ guard `livekit_api_key/secret` rỗng → 503 (như hiện tại).

Lưu ý: default `false` sẽ tắt browser LiveKit tester ở cấu hình mặc định — chấp nhận (prod-safe); dev set `LIVEKIT_TOKEN_PUBLIC=true`.

## 4. Config thêm

`config.py`: `livekit_token_public: bool = False` (env `LIVEKIT_TOKEN_PUBLIC`). Không thêm gì khác — `livekit_public_url` / `livekit_agent_name` / `livekit_api_key` / `livekit_api_secret` đã có.

## 5. Worker / identity — KHÔNG sửa (invariant đã xác minh)

`session_id = room.name` + greet/turn load Customer theo `session_id` (đã seed) → agent biết khách là ai từ câu chào. Ghi lại làm invariant: **provisioning voice PHẢI đặt `room = session_id`** (nếu lệch, worker load nhầm/không có identity).

Greeting đích danh ("Chào chị Nga…") phụ thuộc `agent.greet()` đi qua system prompt (đã chèn customer). Nếu greeting hiện tại là chuỗi tĩnh, cá nhân hoá là chỉnh prompt — **ngoài scope Phase 2** (Phase 2 chỉ lo transport: token + dispatch + gate).

## 6. Runbook hạ tầng (prerequisite — ops, không phải code)

Để app 4G dùng được voice (và chat):
1. Expose agent `:8766` (HTTP/WS) ra public qua reverse proxy TLS tại `hotline-agent.noble.vn` (đang trỏ `10.50.12.70` nội bộ).
2. Expose LiveKit: signaling wss (`:7880`) + media (UDP `:7881` / port range) ra public; set `LIVEKIT_PUBLIC_URL = wss://…` công khai.
3. Dựng **TURN (coturn)** cho NAT/4G — bắt buộc cho mobile (media UDP thường bị chặn). Khai báo TURN trong LiveKit server config.
4. Giữ `LIVEKIT_TOKEN_PUBLIC=false` ở prod; provisioning là đường mint token.

## Error handling

- `provision_session(channel="voice")` khi LiveKit chưa cấu hình → `503 livekit_not_configured` (không crash).
- `channel` lạ (không `chat`/`voice`) → mặc định `chat` (giữ tương thích) hoặc `400`; chốt: coi như `chat` để không vỡ caller cũ, log warning.
- `/livekit/token` gate off → `503 livekit_token_disabled`.

## Testing

- **Unit** (`tests/unit/unified/test_app_session.py`): `provision_session(channel="voice")` → seed Customer trong Redis y như chat (dùng lại assertion), response có `livekit_url`/`livekit_token`/`room==session_id`, **decode JWT** (bằng `livekit.api` verifier hoặc PyJWT + secret) xác nhận: `sub/identity` đúng, grant `room == session_id` + `room_join`, và **room config chứa `RoomAgentDispatch` với `agent_name == settings.livekit_agent_name`**. LiveKit chưa cấu hình → 503.
- **Unit** (http): `/livekit/token` với `livekit_token_public=false` → 503; `true` → 200 và token cũng mang dispatch (dùng chung helper).
- **E2E mobile:** hoãn tới khi infra public (theo runbook) — Flutter join room, nghe greeting đích danh, nói chuyện, barge-in.

## Out of scope

- Flutter client (nhúng `livekit_client`, UI bubble) — app team.
- Thực thi hạ tầng (expose public + TURN) — ops, chỉ có runbook ở đây.
- Cá nhân hoá lời chào (prompt) — nếu cần, chu kỳ prompt riêng.
- Test e2e từ thiết bị thật — sau khi expose public.

## Open questions

1. Giá trị `identity` participant: `f"user-{session_id}"` (đề xuất, opaque, ổn định) hay `noble_user_id` thô? (không ảnh hưởng agent, chỉ là nhãn participant).
2. TURN: dùng coturn tự dựng hay TURN kèm LiveDeploy — ops quyết.

## References

- Phase 1 spec `docs/superpowers/specs/2026-07-09-noblex-app-agent-integration-design.md` (§Phase 2 outline).
- `src/noble_agent/server/app_session.py` (provision_session — Phase 1), `server/http.py` (`/livekit/token` :844-875).
- `src/noble_agent/transport/livekit/worker.py` (`entrypoint`, `agent_name`), `room_session.py` (`session_id = room.name`).
- `src/noble_agent/config.py` (livekit_* settings).
