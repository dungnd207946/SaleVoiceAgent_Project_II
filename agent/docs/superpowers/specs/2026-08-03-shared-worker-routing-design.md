# Shared-worker routing (gateway ↔ agent, 1 process / N tenants) — design

> Kiến trúc đã chốt: **một process agent phục vụ N tenant** (nền Plan 1/2/3 — tenant
> resolve per-request qua `current_tenant()`). Nhưng routing hiện tại vẫn giả định
> **"1 worker / 1 tenant"**: dispatch LiveKit dùng tên `agent-<tenant>` và chat proxy
> trỏ DNS `agent-<tenant>`. Spec này bỏ giả định đó — tên dispatch + URL chat **không
> còn mang tenant**; tenant đi kèm **trong dữ liệu request** (voice: participant
> metadata; chat: header) và worker scope per-turn qua `set_current_tenant`.
>
> Đây là phần "infra phase" mà Plan 1 cố ý hoãn (CLAUDE.md: `agent_dispatch_name(settings.tenant_id)`
> để mức process). Gồm 3 gap từ audit gateway↔agent: #1 voice dispatch, #2 chat tenant,
> #3 enforce `X-Gateway-Secret`.

## 1. Mục tiêu & phạm vi

**Trong phạm vi:**
- **#1 Voice:** một tên agent-dispatch **dùng chung** cho mọi tenant; gateway nhét
  `tenant_id` vào participant metadata; một pool worker đăng ký dưới tên chung nhận
  job mọi tenant, scope theo metadata.
- **#2 Chat:** gateway chat-proxy trỏ **worker dùng chung** (bỏ DNS `agent-<tenant>`),
  truyền tenant qua header `X-Tenant-Id`; `ws_handler` đọc header → `handle_text_session(tenant_id=)`.
- **#3 Enforce `X-Gateway-Secret`** ở worker `/chat` (gated khi secret được cấu hình).

**Ngoài phạm vi (gap khác, đợt sau):** endpoint issuance cho Portal (#4); chạy
`noble-gateway` + bật flag/`POSTGRES_DSN` (#5); heartbeat/app_session token per-tenant
ở mức process (#6). `send_media`/`kb_search` và các backend RAG: không đụng.

## 2. Bối cảnh (mã hiện tại)

- `tenant/naming.py::agent_dispatch_name(tenant_id)` → `f"agent-{tenant_id}"`.
- Ba site mint/register per-tenant: `gateway/livekit_bridge.py:66`, `server/app_session.py:241`,
  `transport/livekit/worker.py:322` (đăng ký `agent_name=agent_dispatch_name(settings.tenant_id)`).
- `gateway/server.py:99`: `identity_json = json.dumps(hs.get("identity") or {})` — **KHÔNG**
  có `tenant_id`. Worker `worker.py:169-180 _job_tenant(metadata, settings.tenant_id)` đọc
  `data.get("tenant_id")` → hôm nay luôn fallback `settings.tenant_id` (đúng chỉ vì worker per-tenant).
- `gateway/chat_proxy.py:15-17`: `worker_chat_url = template.format(tenant_id=...)`; default
  `config.py:109` = `ws://agent-{tenant_id}:8766/chat`; gửi header `X-Gateway-Secret` khi
  `gateway_worker_secret` set (`chat_proxy.py:52-53`).
- `server/ws_handler.py:98`: `handle_text_session(ws, session_id, tenant_id=None)` — làm rớt tenant.
  `handle_text_session` (`text_chat.py:224,234-235`) đã `set_current_tenant(tenant_id)` khi truthy.
- `config.py:710`: `livekit_agent_name: str = "noble-hotline-agent"` (field sẵn có → dùng làm tên chung).

## 3. #1 Voice — dispatch dùng chung + tenant trong metadata

### 3.1 Tên dispatch chung (dùng field sẵn có)
- Tên dispatch dùng chung = **`settings.livekit_agent_name`** (mặc định `noble-hotline-agent`),
  không còn suy ra từ tenant.
- `tenant/naming.py::agent_dispatch_name`: **bỏ tham số tenant**. Vì tên chung nằm ở
  `settings`, đơn giản nhất là **xóa helper** và 3 site tham chiếu thẳng `settings.livekit_agent_name`.
  (Trước khi xóa: grep xác nhận không còn caller nào khác của `agent_dispatch_name`; nếu có
  site không lấy được `settings` thuận tiện thì giữ 1 shim `agent_dispatch_name(settings) -> str`
  trả `settings.livekit_agent_name`.)
- Ba site đổi sang tên chung:
  - `worker.py:322` `agent_name=settings.livekit_agent_name`.
  - `gateway/livekit_bridge.py:66` `RoomAgentDispatch(agent_name=settings.livekit_agent_name)`
    — `build_dispatch_token` nhận thêm tham số tên (hoặc đọc settings) thay cho `agent_dispatch_name(tenant_id)`.
  - `server/app_session.py:241` `RoomAgentDispatch(agent_name=settings.livekit_agent_name)`.

### 3.2 Gateway nhét `tenant_id` vào metadata (mắt xích bắt buộc)
- `build_dispatch_token(tenant_id, identity_json, ...)` merge `tenant_id` vào metadata JSON
  trước khi `.with_metadata(...)`: parse `identity_json` (rỗng → `{}`), set `data["tenant_id"] = tenant_id`,
  dump lại. (Đặt trong `build_dispatch_token` để token là nguồn sự thật duy nhất; `_bridge_voice`
  không cần đổi.) Kết quả: worker `_job_tenant` đọc `tenant_id` từ metadata → resolve đúng tenant
  dù dispatch name không còn mang tenant.
- `room_name` giữ nguyên `tenant-callid-ms-hex` (chỉ là nhãn/unique; không dùng để resolve tenant).

### 3.3 Worker
- Không đổi logic: `_job_tenant` đã đọc `tenant_id` từ metadata → `set_current_tenant`. Chỉ đổi
  tên đăng ký (3.1). Một pool worker (num_idle_processes ≥ 1) nhận job mọi tenant.
- `app_session` voice (NobleX app): đổi tên dispatch (3.1); metadata giữ `settings.tenant_id`
  như hiện tại (app đơn-tenant → worker fallback đúng). Không nhét tenant khác.

## 4. #2 Chat — worker dùng chung + tenant qua header

### 4.1 Config
- `worker_chat_internal_url_template` → **URL cố định không còn `{tenant_id}`**, ví dụ
  `ws://agent:8766/chat` (default mới). `worker_chat_url(tenant_id, settings)` chỉ trả
  `settings.worker_chat_internal_url_template` (bỏ `.format(tenant_id=...)`; template không có
  placeholder → `.format()` an toàn, nhưng bỏ hẳn để rõ ý). Giữ chữ ký `worker_chat_url(tenant_id, settings)`
  cho tương thích call-site; `tenant_id` không còn dùng để dựng URL.

### 4.2 chat_proxy gửi tenant qua header
- `proxy_chat`: thêm `headers["X-Tenant-Id"] = tenant_id` (cạnh `X-Gateway-Secret`). Header là
  cách truyền tenant tới worker (đối xứng với secret; `ws_handler` đọc được `ws.request.headers`).

### 4.3 ws_handler đọc header → truyền tenant
- Nhánh chat (`ws_handler.py:89-99`): đọc `X-Tenant-Id` từ `ws.request.headers` (case-insensitive;
  `websockets` `Headers` hỗ trợ `.get`). Rỗng/thiếu → `None`.
- `handle_text_session(ws, session_id, tenant_id=<header or None>)`. `None` → fallback
  `settings.tenant_id` (giữ nguyên đường browser trực tiếp / single-tenant).

## 5. #3 Enforce `X-Gateway-Secret` ở worker `/chat`

- Trong nhánh chat của `ws_handler`, **trước** khi vào `handle_text_session`:
  - Nếu `settings.gateway_worker_secret` **KHÔNG rỗng**: yêu cầu header `X-Gateway-Secret` khớp
    (so sánh hằng-thời-gian `hmac.compare_digest`). Không khớp/thiếu → `ws.close(4403, "gateway_secret_mismatch")`, return.
  - Nếu `gateway_worker_secret` rỗng: **bỏ qua** (trust-network / dev — giữ hành vi hiện tại,
    browser tester trực tiếp vẫn vào được).
- Thứ tự kiểm trong nhánh chat: (1) `chat_ws_require_token` token check (giữ nguyên, đường NobleX app);
  (2) `gateway_worker_secret` check (mới); (3) đọc `X-Tenant-Id`; (4) `handle_text_session`.
  (Ghi chú: đường gateway dùng secret, không cấp connect-token; đường NobleX-app dùng token,
  không qua gateway — hai cơ chế độc lập, không cần hợp nhất ở đợt này.)

## 6. Bất biến — deploy single-tenant / direct không đổi

- Browser `/chat` trực tiếp (không gateway): không `X-Tenant-Id` → `tenant_id=None` → fallback
  `settings.tenant_id`; không `X-Gateway-Secret` nhưng `gateway_worker_secret` rỗng ở dev → không enforce.
  → **byte-identical**.
- Voice không qua gateway (telephony/SIP dispatch không set metadata tenant): `_job_tenant` fallback
  `settings.tenant_id`. Worker đăng ký tên chung `noble-hotline-agent` (đổi từ `agent-noble`) — cần
  đảm bảo mọi dispatch (kể cả SIP trunk) trỏ tên chung này; single-tenant chỉ có một tên nên nhất quán.
- `gateway_worker_secret` rỗng (mặc định) → #3 no-op.

## 7. Close codes (chat, worker side)

| Code | Khi nào |
|---|---|
| `4401 unauthorized` | (sẵn có) `chat_ws_require_token` + connect-token sai |
| `4403 gateway_secret_mismatch` | (mới) `gateway_worker_secret` set nhưng `X-Gateway-Secret` thiếu/sai |

## 8. Testing

- `agent_dispatch_name`/tên chung: 3 site dùng `settings.livekit_agent_name`; không còn `agent-<tenant>`.
- `build_dispatch_token`: metadata JSON chứa `tenant_id` (merge vào identity); `identity_json` rỗng →
  metadata `{"tenant_id": ...}`; dispatch `agent_name == settings.livekit_agent_name`.
- `worker._job_tenant`: metadata có `tenant_id` → trả tenant đó (không fallback) — đã có test, xác nhận
  vẫn xanh với đường gateway mới.
- `chat_proxy`: `worker_chat_url` trả URL cố định (không cần `{tenant_id}`); `proxy_chat` gửi
  `X-Tenant-Id` + (khi set) `X-Gateway-Secret`.
- `ws_handler` chat: header `X-Tenant-Id` → `handle_text_session(tenant_id=...)`; thiếu header → `None`;
  `gateway_worker_secret` set + header khớp → pass; thiếu/sai → close 4403; secret rỗng → bỏ qua.
- Cập nhật test gateway/naming cũ đang assert per-tenant dispatch.

## 9. Điểm còn mở (đợt sau, không thuộc spec này)

1. #4 endpoint issuance cho Portal (tạo tenant → mint API key).
2. #5 service unit chạy `noble-gateway` + bật `TENANT_STORE_ENABLED`/`MINIO_*`/`POSTGRES_ENABLED` +
   `POSTGRES_DSN`→`odyssey_agent`.
3. #6 heartbeat (SP-D) + app_session token đang ở mức `settings.tenant_id` — shared-process có thể
   cần phát/mint per-tenant. Quyết sau.
