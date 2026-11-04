# Tích hợp Luna agent vào NobleX mobile app (bubble Chat/Voice)

**Ngày:** 2026-07-09
**Branch:** `feat/app-integration` (đề xuất — chưa tạo; xem "Ghi chú branch")
**Phạm vi (agent repo):** `server/http.py` (endpoint provisioning mới + khoá `/livekit/token`), `server/text_chat.py` (auth WS), `storage/models.py` (Customer +`noble_user_id`), `config.py` (settings mới), tests. **KHÔNG đụng:** agent core / RAG / LLM / audio pipeline / tool catalog / Luna prompt (scope pre-sale hiện tại vừa khít).
**Phía ngoài repo này:** NobleX backend (thêm 1 lời gọi server-to-server) + Flutter client (WS chat, sau đó LiveKit voice).

## Bối cảnh

Giai đoạn tiếp theo: nhúng agent Luna vào NobleX mobile app (Flutter). App có 1 bubble agent, user chọn **Voice** hoặc **Chat**. App đã biết user Noble nào đang muốn nói chuyện (đã đăng nhập qua Keycloak).

Agent hiện tại đã có sẵn nền tảng cần thiết:
- Agent core tách rời transport qua facade `NobleAgent` — thêm client mới = thêm transport, không viết lại agent.
- **Chat:** WS `/chat` (JSON `user_text` → stream `token`/`tool_start`/`tool_done`/`done`, optional TTS PCM16).
- **Voice:** `GET /livekit/token` mint JWT → client join LiveKit room (SDK Flutter chính thức `livekit_client`); worker tự chạy agent, `room name = session_id`.
- **Seed identity:** `Customer` model + `facade.set_customer_fields()`; Redis 3 key/session.
- **Auth mẫu:** REST `/api/v1/sales/*` đã có `X-Noble-API-Key` + rate-limit Redis theo tier.

Ba khoảng trống cho mobile:
1. **Không có auth** ở entry point client (`/livekit/token`, WS `/ws`, WS `/chat` — chỉ rate-limit theo IP). App public trên 4G ⇒ bắt buộc phải khoá.
2. **Chưa có đường bơm identity thống nhất trước câu chào** — path aiortc WS có `set_customer` nhưng chat WS chỉ có `user_text`/`reset`, và worker LiveKit khởi tạo phiên chỉ với `session_id = room.name`, không seed Customer.
3. Voice cần hạ tầng LiveKit public (wss + TURN).

## Quyết định đã chốt (brainstorm 2026-07-09)

| Câu hỏi | Chốt |
|---|---|
| Stack app | **Flutter** (LiveKit có SDK Dart; chat qua `web_socket_channel`) |
| Topology | **Qua backend NobleX** — backend xác thực user, mint token + seed identity thay app; API key nằm ở backend |
| Đối tượng | **Khách pre-sale (prospect)** — Luna fit sẵn, KHÔNG đổi scope/agent/tool |
| Seed | **Chỉ identity** (tên/SĐT/hồ sơ), KHÔNG truyền ngữ cảnh màn hình — Luna khai thác chủ đề trong hội thoại như hiện tại |
| Thứ tự | **Phase 1: Chat trước** (nhẹ, khoá được auth + seed + UX). **Phase 2: Voice (LiveKit)** sau |
| Provisioning/auth | **Direct WS + connect-token ngắn hạn** (không proxy qua backend) |

## Mục tiêu

- Backend NobleX provision được 1 phiên agent cho user đã đăng nhập, **seed danh tính vào Redis trước lượt đầu tiên**, và trả cho Flutter thông tin để nối thẳng WS (Phase 1) / LiveKit room (Phase 2).
- Đóng lỗ auth: client-facing entry point chỉ nhận phiên đã được provision.
- Identity là **server-authoritative** — client không tự khai danh tính.
- Luna chào đích danh và gắn lead/handoff đúng người ngay từ đầu.

### Phi mục tiêu (out of scope)
- Không mở rộng scope post-sale (khách đã mua) — vẫn `escalate`.
- Không đổi Luna prompt / tool catalog / audio pipeline.
- Không truyền ngữ cảnh màn hình app (dự án đang xem) — để phase sau nếu cần.
- Không xây UI Flutter trong repo này (chỉ định nghĩa hợp đồng API/WS để app team implement).

## Hợp đồng dữ liệu Noble → agent (đã kiểm chứng live 2026-07-09)

Nguồn: `GET https://dev-api-noble-app.unicloudgroup.com.vn/api/v1/profile/GetProfileInfo` (auth Keycloak bearer của user, realm `realm_ssg_home`, client `web_noble_app`). Backend đã có sẵn token/profile này.

| Field Noble (`data.*`) | → agent `Customer` | Ghi chú |
|---|---|---|
| `userId` (UUID) | **`noble_user_id`** (field mới) | khoá định danh ổn định → derive `session_id` |
| `fullName` | `full_name` + `name` | |
| `phone` | `phone` | |
| `sex` (`Female`/`Male`) | `gender` (`F`/`M`) | agent normalize (Female/Nữ→F, Male/Nam→M) |
| `isUserNoble` (bool) | `is_noble_customer` | ⚠️ xác nhận nghĩa cờ (xem Open Q) |
| `nobleInfo` (string) | `noble_info` | ⚠️ dev = placeholder; xác nhận prod (xem Open Q) |
| `email`, `birthday`, `referralCd`, `ranking`/`rank`/`point` | gộp vào `noble_info` | enrichment optional, không phình model |

`GET /api/v1/profile/GetProfileInfoNoble` (eKYC + `res_add`/`origin_add`) là KYC/địa chỉ thường trú — **KHÔNG** map vào `preferred_area` (đó là quê, không phải khu vực muốn mua). Không dùng ở phase này.

**KHÔNG có trong profile** (Luna khai thác trong hội thoại): `project_interest`, `purpose`, `budget`, `preferred_area`, `bedroom_count`, `is_buyer`.

## Kiến trúc

```
Flutter app  ──(bubble: Chat | Voice)──┐
  user đã login NobleX (Keycloak)      │
                                       ▼
NobleX backend (đã có) ── xác thực user; có Keycloak token + profile
   │ POST /api/v1/app/session   (header X-Noble-App-Key, server-to-server)
   ▼
Agent santa-hotline (:8766)
   ├─ tạo session_id (derive từ noble_user_id) + SEED Customer vào Redis
   ├─ mint connect-token ngắn hạn (Redis, TTL ~120s)
   └─ trả {session_id, ws_url + token}  [Phase 2: + livekit_url/token/room]
                                       │
        ┌──────────────────────────────┘
        ▼
Flutter nối THẲNG:  Phase 1 → WS /chat?session=&token=
                    Phase 2 → LiveKit room = session_id (token đã mint)
```

Backend là người gác cổng; agent chỉ nhận phiên đã provision. Vì Customer được seed theo `session_id` và cả chat WS lẫn worker LiveKit đều khoá phiên theo `session_id`, **identity tự có mặt cho cả hai kênh** mà không phải sửa client-supplied `set_customer`.

## Provisioning endpoint (mới)

`POST /api/v1/app/session` — trong `server/http.py`, tái dùng pattern auth của sales API (`server/http.py` khối `X-Noble-*` + CORS + rate-limit).

- **Auth:** header `X-Noble-App-Key` khớp `settings.noble_app_api_key` (settings mới, tách khỏi `noble_sales_api_key` để phân quyền app vs dashboard). Thiếu key cấu hình → 503; sai → 401.
- **Request:**
  ```jsonc
  {
    "noble_user_id": "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb",  // bắt buộc
    "channel": "chat",                                         // "chat" | "voice"
    "identity": {
      "full_name": "Lê Viết Thúy Nga",
      "phone": "0378764303",
      "gender": "Female",            // agent normalize → F/M (nhận cả F/M/Nữ/Nam)
      "is_noble_customer": false,
      "noble_info": "…",             // optional
      "email": "…", "birthday": "…"  // optional → gộp vào noble_info
    }
  }
  ```
- **Xử lý:**
  1. `session_id = "app-" + <12 hex đầu của noble_user_id>` (khớp format 12-hex hiện có → deterministic → resumable).
  2. Normalize `gender`; gộp email/birthday/loyalty vào `noble_info`.
  3. `set_customer_fields()` seed Customer (chỉ ghi field truthy — không xoá field cũ nếu phiên đã tồn tại).
  4. Mint `connect_token` (opaque ngẫu nhiên), lưu Redis `session:{sid}:connect_token` TTL `settings.app_connect_token_ttl` (~120s).
  5. `channel=voice` (Phase 2): mint thêm LiveKit token với `room = session_id`.
- **Response:**
  ```jsonc
  {
    "session_id": "app-6cb7cc1dd5d0",
    "channel": "chat",
    "ws_url": "wss://<host>/chat?session=app-6cb7cc1dd5d0&token=<connect_token>",
    "connect_token": "<opaque>",
    "expires_in": 120
    // Phase 2 (voice): + "livekit_url", "livekit_token", "room"
  }
  ```

## Auth cho WS `/chat`

Trong `server/text_chat.py` (chỗ parse `?session=` + handshake):
- Đọc `?token=`, so với `session:{sid}:connect_token` trong Redis. Không khớp/không có → đóng WS code `4401`.
- Gate bằng setting **`settings.chat_ws_require_token`** (default `false` để giữ nguyên chat tester dev `static/chat.html` + back-compat; **prod set `true`**).
- Token dùng lại được trong TTL (cho reconnect); hết TTL → app re-provision (session_id vẫn giữ nguyên nên lịch sử không mất).

## Thay đổi data model

`storage/models.py` `Customer`: thêm `noble_user_id: str | None = None`. Không đổi field khác. `email`/`birthday`/loyalty **không** thêm field — nối vào `noble_info` để tránh phình model + rebuild prompt.

## Session continuity

`session_id` deterministic theo `noble_user_id` → **resumable**: mở lại bubble hôm sau vẫn cùng phiên; voice ↔ chat **dùng chung** một session (chuyển kênh không mất ngữ cảnh). TTL = `session_ttl_seconds` hiện có (cân nhắc nới cho app). `reset` sẵn có nếu user muốn bắt đầu lại. ⚠️ Cần xác nhận (Open Q #3).

## Phase 2 — Voice (LiveKit), phác

- Cùng endpoint provisioning mint LiveKit token + `room = session_id`. Vì Customer đã seed theo `session_id` và worker dùng `session_id = room.name` → **worker tự load đúng identity, không sửa worker**.
- **Khoá `GET /livekit/token` public hiện tại** — chỉ cho provisioning (server-side) mint; hoặc gate bằng setting yêu cầu app-key.
- Hạ tầng: `LIVEKIT_PUBLIC_URL` (wss public) + TURN cho 4G/NAT; chạy LiveKit worker (`TRANSPORT_BACKEND=livekit`) song song transport hiện có.
- Flutter: `livekit_client` join room bằng token; render transcript qua data channel `agent-events` (đã có ở `room_session.py`).

## Escalate / handoff trong ngữ cảnh app

Không đổi logic. Khi Luna `escalate` (post-sale / giá private / hết luồng pre-sale) → dùng `POST /api/v1/sales/handoff` (đã có) đẩy lead về sales dashboard, báo user "CVTV sẽ liên hệ". Lead gắn đúng người nhờ identity đã seed.

## Error handling

- Provisioning: `noble_user_id` thiếu → 400; identity thiếu field → best-effort (agent chạy với identity một phần, không fail). Redis down → 503.
- WS `/chat` (khi require_token): token sai/hết hạn → close `4401` + message rõ; client re-provision.
- Provisioning là **idempotent** theo `noble_user_id`: gọi lại chỉ refresh connect-token + merge identity, không tạo phiên trùng.

## Testing

- **Unit** (`tests/unit`): provisioning derive `session_id` đúng & ổn định; normalize gender (Female/Nữ→F, Male/Nam→M); seed Customer đúng field; auth 401/503/200; connect-token TTL.
- **Integration**: WS `/chat` với `require_token=true` — token hợp lệ pass, sai bị đóng `4401`; identity đã seed xuất hiện trong system prompt (Luna chào tên).
- **E2E** (`tests/e2e_scenarios`, `make e2e`): kịch bản seeded-user → Luna chào đích danh + không hỏi lại tên/SĐT.
- Chạy `src/noble_agent/SMOKE.md` (chạm turn loop / prompt / transport boundary).

## Open questions (xác nhận với team Noble trước khi implement)

1. **`nobleInfo` prod chứa gì?** (dev = `"Noble Information"` placeholder). Quyết định giá trị nội dung bơm cho Luna.
2. **Nghĩa cờ `isUserNoble`** để map `is_noble_customer` đúng (user test = `false` dù là tài khoản nội bộ).
3. **Session resumable per-user** (như trên) OK, hay mỗi lần mở bubble là phiên mới?
4. Dùng **key riêng `X-Noble-App-Key`** (khuyến nghị) hay tái dùng `X-Noble-API-Key` của sales API?

## Ghi chú branch

Đang ở `develop` (CLAUDE.md: **không commit vào develop**, không tự tạo branch khi chưa được duyệt). Spec này ghi ra working tree; cần user duyệt tạo branch `feat/app-integration` để commit.

## References

- `docs/system-design/08-api-contracts-websocket-http.md` (WS/HTTP contract — một phần đã cũ: personas consultant/support đã bỏ, mã dự án cũ).
- `src/noble_agent/agent/facade.py` (`set_customer_fields`, `get_customer`).
- `src/noble_agent/storage/models.py` (`Customer`).
- `src/noble_agent/server/http.py` (sales API auth + `/livekit/token`), `server/text_chat.py`, `server/ws_handler.py`.
- `src/noble_agent/transport/livekit/{worker,room_session}.py`.
- Noble profile API: `https://dev-api-noble-app.unicloudgroup.com.vn/swagger/index.html`.
