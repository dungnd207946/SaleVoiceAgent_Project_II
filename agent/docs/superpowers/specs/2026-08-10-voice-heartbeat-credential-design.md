# Voice + heartbeat sang PG credential per-tenant (Redis handoff + Fernet)

**Ngày:** 2026-08-10 · **Branch:** feat/share-agent · **Trạng thái:** đã duyệt thiết kế
**Nối tiếp:** [2026-08-10-gateway-runtime-credentials-design.md](2026-08-10-gateway-runtime-credentials-design.md)
(đợt 1 đã live-verify xong cho CHAT; voice + heartbeat khi đó để lại shared DSN).

## Bối cảnh & mục tiêu

Sau đợt 1, chat qua gateway đã chạy pool PG per-tenant (role `agent_<tenant>` từ
runtime-credentials API). Còn hai đường vẫn shared `POSTGRES_DSN`:

1. **Voice (LiveKit qua gateway)** — bị chặn đợt 1 vì kênh duy nhất gateway→worker
   là metadata đi qua LiveKit Cloud (bên thứ ba), không nhét password DB vào được.
2. **Heartbeat** — ghi `control.agent_heartbeats`, cần `deployment_id` mà logic cũ
   SELECT từ `control.deployments`.

Facts đã verify live trên DB Portal mới (10.50.13.208:5442/portal):

- Role `agent_<tenant>`: ✅ INSERT/UPSERT `control.agent_heartbeats`,
  ✅ SELECT `tenant_data.agent_config`, ❌ SELECT `control.deployments`/`control.tenants`
  (least-privilege của Portal — sẽ không xin GRANT).
- `deployment_id` + `kind` đã nằm sẵn trong response runtime-credentials API.
- Gateway và LiveKit voice worker dùng chung Redis nội bộ (worker gọi `get_redis()`
  ngay trong `entrypoint`).
- Thư viện `cryptography` có sẵn trong venv (48.0.0).

Quyết định đã chốt với user:

- Kênh voice: **Redis handoff + mã hoá Fernet** (khoá dẫn xuất từ
  `GATEWAY_WORKER_SECRET` — không thêm env mới).
- Heartbeat: **lấy `deployment_id` từ credential API** (bỏ SELECT
  `control.deployments` khi có credential), fallback đường cũ khi không có.

## 1. Module mới dùng chung: `storage/credential_stash.py`

- `derive_key(secret: str) -> bytes` — `base64.urlsafe_b64encode(sha256(secret))`
  → khoá Fernet.
- `encrypt_credential(secret, payload: dict) -> str` — Fernet token (str).
- `decrypt_credential(secret, token: str) -> dict | None` — lệch secret / token
  rác / JSON hỏng → `None`, KHÔNG raise.
- `stash_key(tenant_id) -> str` = `noble:pgcred:<tenant_id>`.
- `async stash(redis, secret, tenant_id, *, role, password, deployment_id, kind, expires_at)`
  — `SET` ciphertext với `EX = max(1, giây còn lại tới expires_at)` → Redis tự xoá
  khi credential hết hạn. Payload: `{role, password, deployment_id, kind, expires_at
  (ISO)}`.
- `async fetch(redis, secret, tenant_id) -> dict | None` — key không có / giải mã
  fail → `None`.

Redis chỉ nhìn thấy ciphertext; kẻ đọc trộm Redis cần thêm `GATEWAY_WORKER_SECRET`
(env của 2 process) mới mở được.

## 2. Gateway — stash trước khi dispatch voice

Trong `gateway/server.py::_handle` nhánh voice, TRƯỚC `_bridge_voice`:
nếu `result.credentials` có `postgres_role` + `postgres_password` **và**
`settings.gateway_worker_secret` non-empty → `stash(...)` vào Redis
(`storage.redis_client.get_redis()`, import lazy).

**Best-effort:** Redis lỗi / stash fail → log warning, cuộc gọi VẪN tiếp tục
(voice rơi về shared DSN — không bao giờ vì credential mà rớt cuộc gọi).
Metadata qua LiveKit Cloud giữ nguyên như hiện tại (tenant_id + identity, không
secret).

## 3. Voice worker — ingest lúc vào job

`transport/livekit/worker.py::entrypoint`, ngay sau `set_current_tenant(job_tenant)`:
helper mới `_register_job_credentials(redis, secret, tenant_id) -> bool` (pure,
unit-test được) — `fetch` stash, `tenant_credentials.register(...)`. Secret rỗng /
không có key / giải mã fail → trả False, bỏ qua im lặng (shared fallback như hôm
nay), log debug/warning tương ứng. Registry là in-process → đăng ký trong job
subprocess; toàn bộ downstream (`pool_for_tenant`, persistence, config, pg_kb)
tự chạy, không sửa gì thêm.

## 4. Registry + chat header mang thêm `deployment_id` / `kind`

- `TenantPgCredential` thêm field: `deployment_id: int | None = None`,
  `kind: str = ""`. `register()` nhận 2 kwarg mới (default giữ tương thích).
- Chat: `proxy_headers` gửi thêm `X-PG-Deployment` (str) + `X-PG-Kind`;
  `ws_handler._register_pg_credentials` parse — giá trị hỏng → `None`/`""`,
  KHÔNG từ chối kết nối (2 field chỉ phục vụ heartbeat; role/password/expires
  vẫn là điều kiện bắt buộc như đợt 1).
- Voice: nằm trong payload stash (§1).

## 5. Heartbeat — bỏ query `control.deployments` khi có credential

`tenant/pg_heartbeat.py::PgHeartbeatWriter.beat(tenant_id)`:

```
cred = tenant_credentials.get(tenant_id)
if cred is not None and cred.deployment_id is not None and cred.kind == self._kind:
    pool = await pool_for_tenant(tenant_id)   # role agent_<tenant>
    dep  = cred.deployment_id                 # từ API — khỏi SELECT control.deployments
else:
    pool = self._pool or get_pool()           # đường cũ NGUYÊN VẸN
    dep  = await self._read_dep(tenant_id, self._kind, pool=pool)
```

Version config đọc `tenant_data.agent_config` qua pool đã chọn; UPSERT
`control.agent_heartbeats` qua `tenant_conn(pool, tenant_id)`. Điều kiện
`cred.kind == self._kind` để không beat nhầm deployment khi key chat/voice lẫn
nhau — lệch kind thì đi đường cũ. Áp dụng cho cả `PgHeartbeatSupervisor` (chat)
lẫn `run_job_heartbeat` (voice per-job) vì cả hai đi qua `PgHeartbeatWriter.beat`.

## 6. Không đổi

- Browser WebRTC + telephony Asterisk: không qua gateway → shared DSN như cũ.
- `POSTGRES_DSN` vẫn là fallback (dev/REPL/không-credential); chưa bỏ được.
- Không thêm biến env nào. `GATEWAY_WORKER_SECRET` rỗng ⇒ voice cũng KHÔNG stash
  /ingest credential (nhất quán với hardening chat đợt 1).

## 7. Error handling

- Stash fail (Redis down, secret rỗng) → warning + tiếp tục cuộc gọi (shared).
- Fetch/decrypt fail ở worker → False + shared, warning khi có key mà không giải
  mã được (lệch secret giữa 2 process — đáng báo), debug khi đơn giản là không
  có key (dev, direct call).
- Credential hết hạn → Redis TTL đã tự xoá → không có key → shared.
- Pool per-tenant dựng fail trong heartbeat → `beat()` đã có catch-all trả False
  (best-effort sẵn có) — giữ nguyên.

## 8. Testing

- `credential_stash`: roundtrip encrypt/decrypt; wrong-secret → None; token rác
  → None; TTL = giây tới expires_at (clamp ≥1); fetch key vắng → None.
- Registry: 2 field mới lưu/trả đúng; default tương thích call cũ.
- `proxy_headers`: emit X-PG-Deployment/X-PG-Kind khi có; không emit khi thiếu.
- `ws_handler`: parse 2 header mới; giá trị hỏng → None/"" nhưng vẫn register
  role/password; thiếu hẳn 2 header vẫn register (optional).
- Heartbeat: (a) credential khớp kind → dùng pool_for_tenant + dep từ credential,
  KHÔNG gọi read_deployment_id; (b) lệch kind → đường cũ; (c) không credential →
  đường cũ.
- Worker ingest helper: fake redis — có key → register True; không key → False;
  secret rỗng → False không đụng Redis.
- Live verify: gọi voice qua gateway → log `postgres: pool per-tenant connected`
  trong job process + row `control.agent_heartbeats` đúng `deployment_id` từ
  credential; chat heartbeat cũng chuyển nguồn tương tự.

## Ngoài phạm vi

- Bỏ hẳn `POSTGRES_DSN` (vẫn còn dev/REPL/direct-transport dùng).
- Dùng các trường `storage`/`kb` trong credential response.
- Rotation credential giữa cuộc gọi voice đang chạy (pool giữ tới khi fingerprint
  đổi — như đợt 1).
