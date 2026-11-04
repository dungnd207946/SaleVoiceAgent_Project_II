# Gateway auth qua Runtime-Credentials API + Postgres per-tenant role

**Ngày:** 2026-08-10 · **Branch:** feat/share-agent · **Trạng thái:** đã duyệt thiết kế

## Bối cảnh & mục tiêu

Kiến trúc cũ: provider gọi `wss://<tenant-id>.<base-domain>/v1/{chat,stream}` — gateway
lấy tenant từ **subdomain Host**, verify Bearer key bằng cách đọc thẳng
`control.tenants` / `control.agent_keys` (PostgresCredentialRegistry). Worker nối
Postgres bằng **một shared app role** (`POSTGRES_DSN`), isolation per-transaction qua
`tenant_conn()` → `set_config('app.current_tenant', …)` + RLS policy `agent_runtime`.

Kiến trúc mới (Portal đã chuyển):

1. **Một domain chung duy nhất** (`noble-saas.<domain>`; test: `lvh.me`) + API key.
   Tenant KHÔNG còn nằm trong DNS.
2. Gateway xác thực bằng cách gọi API ngoài:

   ```http
   POST {GATEWAY_CREDENTIALS_API_URL}
   Authorization: Bearer <api_key>
   ```

   Response 200:

   ```jsonc
   {
     "tenant_id": "anphu",
     "deployment_id": 12,
     "kind": "chat",
     "postgres_role": "agent_anphu",
     "postgres_password": "<mật khẩu>",
     "storage": { "endpoint": "…", "bucket": "…", "access_key": "…", "secret_key": "…", "prefix": "tenants/anphu/" },
     "kb": { "url": "…", "collection": "kb_anphu" },
     "live_url": "tenants/anphu/LIVE",
     "expires_at": "2026-08-10T09:00:00Z"
   }
   ```

3. Agent dùng `postgres_role`/`postgres_password` để nối PG — **isolation do danh tính
   đăng nhập DB quyết định**, không phụ thuộc code truyền đúng tenant_id nữa
   (tránh lộ lọt dữ liệu do bug code).

Các quyết định đã chốt với user:

- Credential từ gateway sang worker: **forward qua header WS nội bộ** (hop đã có
  `X-Gateway-Secret`).
- Auth API lỗi/không phản hồi: **fail-closed + cache theo `expires_at`**.
- Đường auth cũ (subdomain + đọc control.*): **xoá hẳn**, không gate env.
- RLS phía DB cho role `agent_<tenant>`: **Portal chịu trách nhiệm** (policy/GRANT);
  repo này verify bằng test live.
- Địa chỉ PG server: env mới **`POSTGRES_SERVER_DSN`** (không chứa user/password);
  `POSTGRES_DSN` giữ làm fallback, lộ trình bỏ hẳn sau.
- Auth API URL: env mới **`GATEWAY_CREDENTIALS_API_URL`**; rỗng → gateway từ chối
  mọi kết nối (fail-closed) + log rõ thiếu config.

## 1. Gateway — thay toàn bộ đường auth

**Module mới `gateway/credentials.py`:**

- `RuntimeCredentials` (frozen dataclass): `tenant_id`, `deployment_id`, `kind`,
  `postgres_role`, `postgres_password`, `storage: dict`, `kb: dict`, `live_url`,
  `expires_at: datetime` (parse ISO-8601, hậu tố `Z`).
- `CredentialsClient` (httpx.AsyncClient, transport inject được để unit test):
  - `authorize(api_key) -> RuntimeCredentials` — POST kèm `Authorization: Bearer`.
  - Cache in-RAM keyed `sha256(api_key)`, sống tới `min(expires_at, now + GATEWAY_CRED_CACHE_TTL_SEC)`.
    Cache hit → không gọi API (auth API down vẫn phục vụ được key đã cache).
  - Lỗi phân loại theo triết lý `gateway/errors.py` (phân biệt "câu trả lời là
    không" với "không hỏi được"):
    - 401/403 → reason `bad_credential` (key sai/revoked).
    - Timeout / 5xx / lỗi mạng / URL chưa cấu hình / response thiếu trường bắt
      buộc → reason `auth_api_unavailable`.
    - Mọi nhánh đều fail-closed: ok=False → close 4001 + reason.
  - Không negative-cache (key sai thì lần sau vẫn hỏi lại API).

**`gateway/auth.py` viết lại:**

- `authorize(authorization, *, credentials) -> AuthResult` — bỏ tham số
  `host`/`base_domain`/`registry`. Không kiểm tra Host nữa.
- `AuthResult` thêm trường `credentials: RuntimeCredentials | None`.
- `kind` trong credential lệch route (key `chat` gọi `/v1/stream`) → **log
  warning, không chặn** (contract voice-key chưa rõ).

**Xoá:**

- `tenant_from_host` + toàn bộ logic subdomain.
- `gateway/pg_registry.py` (PostgresCredentialRegistry).
- `gateway/registry.py` (MinIO CredentialRegistry) + `build_registry` trong
  `server.py`.
- `read_tenant_active` / `read_tenant_key_hashes` trong
  `storage/agent_control_store.py` (chỉ gateway cũ dùng; `read_deployment_id`
  GIỮ — heartbeat cần).
- Gateway sau thay đổi **không đọc Postgres nữa**.

## 2. Truyền credential gateway → worker

**Chat** (`gateway/chat_proxy.py` → worker `server/ws_handler.py`):

- `proxy_headers` thêm `X-PG-Role` + `X-PG-Password` (chỉ khi credential có
  role/password). Hop WS nội bộ đã bảo vệ bằng `X-Gateway-Secret`.
- Worker chỉ đọc 2 header này **sau khi** `_gateway_secret_ok` pass, rồi gọi
  `tenant_credentials.register(tenant_id, role, password, expires_at)` trước khi
  mở session. Thêm header `X-PG-Expires` (ISO-8601) để worker biết hạn.

**Voice** (`_bridge_voice`): **giới hạn có chủ đích đợt này** — credential KHÔNG
đi qua LiveKit (metadata đi qua LiveKit Cloud = lộ secret cho bên thứ ba). Voice
worker giữ fallback shared `POSTGRES_DSN` + set_config RLS. Auth ở gateway vẫn
theo kiến trúc mới (tenant_id từ credential API). Follow-up: kênh an toàn cho
voice worker (hoặc Portal cấp endpoint cho worker tự lấy credential).

## 3. Worker — pool Postgres per-tenant

**Module mới `storage/tenant_credentials.py`:**

- Registry in-process `{tenant_id → TenantPgCredential(role, password, expires_at)}`.
- `register(...)` ghi đè khi role/password đổi; `get(tenant_id)` — hết hạn → trả
  `None` và xoá entry.

**`storage/postgres_client.py`:**

- Thêm `pool_for_tenant(tenant_id) -> pool`:
  - Có credential đăng ký → dựng DSN từ `POSTGRES_SERVER_DSN` + role/password →
    pool riêng per-tenant. Cache theo tenant_id + fingerprint (role,
    sha256(password)); fingerprint đổi → đóng pool cũ, dựng lại. Loop-aware như
    pool shared hiện tại (LiveKit per-job loop).
  - Không có credential (dev local, REPL, voice, heartbeat) → fallback
    `get_pool()` shared như cũ.
- `tenant_conn` **giữ nguyên** (vẫn set cả `app.current_tenant` +
  `app.tenant_id`): trên connection per-tenant là defense-in-depth vô hại; trên
  fallback shared vẫn là cơ chế isolation duy nhất; control-plane RLS
  Portal-owned (`app.tenant_id`) vẫn cần GUC.

**Call sites** đổi `get_pool()` → `pool_for_tenant(tid)` (liệt kê đủ bằng grep ở
bước plan): `storage/pg_data_plane.py`, `storage/agent_config_store.py`,
provider `data/postgres_kb.py`, và các đường per-tenant tương tự. Heartbeat
(`tenant/pg_heartbeat.py`) + provisioning giữ pool/DSN cũ (ghi schema `control`,
ngoài phạm vi credential per-tenant).

## 4. Config (`config.py`)

- Thêm `GATEWAY_CREDENTIALS_API_URL` (str, default "") — rỗng → gateway
  fail-closed toàn bộ.
- Thêm `POSTGRES_SERVER_DSN` (str, default "") — DSN không chứa credential, ví
  dụ `postgresql://10.50.13.220:5433/odyssey`.
- Xoá `GATEWAY_BASE_DOMAIN` + mọi tham chiếu.
- `GATEWAY_CRED_CACHE_TTL_SEC` tái dùng làm cap TTL cache credential.
- `POSTGRES_DSN` giữ nguyên vai trò fallback.

## 5. Error handling

- Gateway close codes giữ nguyên hợp đồng: 4001 + reason
  (`no_bearer` / `bad_credential` / `auth_api_unavailable`), 4004 unknown_route,
  4008 handshake_timeout.
- Response auth API thiếu `tenant_id` hoặc `expires_at` → coi như
  `auth_api_unavailable` (không tin dữ liệu nửa vời).
- Worker: thiếu header PG creds (voice, dev) → im lặng dùng fallback shared —
  không phải lỗi.
- Pool per-tenant dựng fail (password sai, PG từ chối) → lỗi nổi lên như lỗi DB
  bình thường của turn đó; KHÔNG tự động rơi về shared pool (rơi về shared là mở
  rộng quyền — sai hướng an toàn).

## 6. Testing

- **Unit** (httpx MockTransport): credentials client — 200 parse đúng; cache hit
  không gọi lại; quá `expires_at` gọi lại; 401 → `bad_credential`;
  timeout/5xx/thiếu URL/response thiếu trường → `auth_api_unavailable`.
- **Unit** `authorize` mới: ok / no_bearer / lỗi client truyền qua đúng reason.
- **Unit** `proxy_headers`: có creds → 2 header PG; không creds → không thêm.
- **Unit** `pool_for_tenant`: DSN lắp đúng từ `POSTGRES_SERVER_DSN` + creds;
  không creds → shared; password đổi → rebuild pool; creds hết hạn → shared.
- **Unit** worker header ingest: secret pass → register; secret fail → không.
- Xoá/viết lại test đường cũ (`tests/unit/unified/gateway/…` phần
  tenant_from_host, pg_registry).
- **E2E:** sửa `scripts/e2e_dbmode/chat_via_gateway.py` — connect
  `ws://noble-saas.lvh.me:9200/v1/chat` + Bearer key (không còn subdomain
  tenant). Chạy live nếu auth API reachable; verify dữ liệu trả về đúng tenant.
- `make test-unified` + `make lint` sạch.

## Ngoài phạm vi (ghi nhận, không làm đợt này)

- Voice worker nhận PG credential (cần kênh an toàn — follow-up).
- Dùng các trường `storage` / `kb` / `live_url` trong response (mới chỉ lưu vào
  `RuntimeCredentials`, chưa thay đường MinIO/Qdrant hiện tại).
- Bỏ hẳn `POSTGRES_DSN` (chờ voice + heartbeat chuyển xong).
- Rotation credential giữa chừng session (pool giữ tới khi fingerprint đổi).
