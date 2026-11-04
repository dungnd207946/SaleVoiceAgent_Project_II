# Odyssey — Cấp phát Agent & Kết nối Client

Chuỗi lệnh vận hành theo mô hình đa-tenant Odyssey (SRS **HT_01**), khớp mã trên nhánh `feat/agent`.

- **Mỗi workspace = 1 container agent.** NobleX ops/Portal chạy các lệnh cấp phát thay tenant.
- Định danh tenant khi kết nối = **subdomain của Host** (`<tenant>.agents.noblex.vn`) + **Bearer credential**.
- Tài liệu tổng quan luồng: [docs/odyssey-ht01-flow-tracker.html](docs/odyssey-ht01-flow-tracker.html).

Ví dụ dưới đây dùng tenant `acme`.

---

## A. Tạo agent cho một tenant (provisioning)

### 0) Env cho CLI (đọc kho MinIO)

```bash
export TENANT_STORE_ENABLED=true
export MINIO_ENDPOINT=http://10.50.13.220:9000
export MINIO_ROOT_USER=minio  MINIO_ROOT_PASSWORD=•••
export TENANT_BUCKET=hotline-tenants
```

### 1) Bundle cấu hình của tenant

Thư mục bundle (giống `data/tenants/noble/`):

```
tenants/acme/
├── manifest.toml         # tenant_id="acme", data_source, [tools].enabled, [brand]…
├── persona/              # SOUL.md · RULES.md · PROMPT_TEMPLATE.md · CUSTOMER_PROFILE.md · config.json
└── tools/                # tùy chọn — custom tool riêng của tenant
```

### 2) Validate → tạo → publish v1

```bash
noble-tenant validate --dir ./tenants/acme          # kiểm cấu trúc (E08), chưa ghi gì
noble-tenant create acme --dir ./tenants/acme --status active
#   → status=active TỰ publish v1 (bất biến, có con trỏ)
#   (hoặc: create ... không --status → draft, rồi `noble-tenant activate acme`)
```

Vòng đời cấu hình về sau:

```bash
noble-tenant save-draft acme ./tenants/acme         # ghi bản nháp (BR04)
noble-tenant publish acme --by dutn                 # đóng version mới (BR06/07)
noble-tenant list-versions acme                     # xem các version + (published)
noble-tenant rollback acme 3 --by dutn              # quay lui = trỏ lại v3, KHÔNG tạo mới
noble-tenant diff acme 4 3                           # so hai version
noble-tenant show acme                               # trạng thái + danh sách file
noble-tenant list                                    # liệt kê mọi tenant
```

### 3) Cấp role Postgres riêng (cách ly RLS = `current_user`)

```bash
export POSTGRES_ADMIN_DSN='postgresql://postgres:•••@10.50.x.x:5432/odyssey'
noble-tenant pg-apply-schema                # 1 lần/cụm — tạo schema tenant_data (idempotent)
noble-tenant pg-provision acme              # CREATE ROLE acme + GRANT, all-or-nothing (BR12)
#   → provisioned role=acme
#   → password=XXXXX          ← in MỘT lần, nhét vào POSTGRES_DSN của container acme
# gỡ tenant:
# noble-tenant pg-deprovision acme          # xoá rows 3 bảng + DROP ROLE
```

### 4) Phát credential (Bearer) cho provider của tenant

```bash
noble-tenant issue-cred acme                # → tnt_•••••  (in 1 lần, giao cho provider)
noble-tenant list-creds acme                # key_id + trạng thái (không lộ hash)
noble-tenant revoke-cred acme <key_id>      # thu hồi
```

### 5) Chạy container agent của tenant (mỗi workspace 1 bản)

```bash
TENANT_ID=acme \
USE_UNIFIED_AGENT=true  TRANSPORT_BACKEND=livekit \
TENANT_STORE_ENABLED=true \
  MINIO_ENDPOINT=$MINIO_ENDPOINT MINIO_ROOT_USER=$MINIO_ROOT_USER MINIO_ROOT_PASSWORD=$MINIO_ROOT_PASSWORD \
POSTGRES_ENABLED=true  POSTGRES_DSN='postgresql://acme:XXXXX@pg:5432/odyssey' \
LIVEKIT_URL=$LIVEKIT_URL LIVEKIT_API_KEY=$LIVEKIT_API_KEY LIVEKIT_API_SECRET=$LIVEKIT_API_SECRET \
  noble-agent
# Agent tự dò version mỗi 20s → tải gói → kiểm tổng → nạp; tự đẩy _heartbeat.json (SP-D).
```

### 6) Chạy gateway (1 process chung cho mọi tenant)

```bash
GATEWAY_CREDENTIALS_API_URL=https://<portal>/api/v1/runtime-credentials  GATEWAY_PORT=9200 \
TENANT_STORE_ENABLED=true  MINIO_ENDPOINT=… MINIO_ROOT_USER=… MINIO_ROOT_PASSWORD=… \
LIVEKIT_URL=…  LIVEKIT_API_KEY=…  LIVEKIT_API_SECRET=… \
WORKER_CHAT_INTERNAL_URL_TEMPLATE='ws://agent-{tenant_id}:8766/chat' \
  noble-gateway
```

---

## B. Client của provider tenant kết nối vào agent (qua gateway)

Sau khi connect phải gửi **frame handshake JSON đầu tiên**: `{"identity":{…},"call_id":"…"}`.
Endpoint: `/v1/voice` (voice) · `/v1/chat` (chat).

### Chat — thử nhanh bằng websocat

```bash
websocat -H='Host: acme.agents.noblex.vn' \
         -H='Authorization: Bearer tnt_•••••' \
         wss://acme.agents.noblex.vn/v1/chat
# frame 1 (handshake): định danh khách (seed set_customer cho worker)
{"identity":{"phone":"0900000000","name":"Anh Duy"},"call_id":"c-001"}
# các frame sau: đúng schema /chat của worker (relay thẳng)
```

### Chat — client Python

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect(
        "wss://acme.agents.noblex.vn/v1/chat",
        additional_headers={
            "Host": "acme.agents.noblex.vn",           # subdomain = tenant_id
            "Authorization": "Bearer tnt_•••••",       # credential của acme
        },
    ) as ws:
        await ws.send(json.dumps({"identity": {"phone": "0900000000", "name": "Duy"},
                                  "call_id": "c-001"}))          # handshake
        await ws.send(json.dumps({"type": "message", "text": "Cho hỏi dự án ABC"}))  # theo /chat
        async for m in ws:
            print(m)

asyncio.run(main())
```

### Voice — `/v1/voice` (skeleton)

Sau handshake: **frame binary = PCM16 16 kHz mono**, frame text = JSON control (mirror `voice/service/protocol.py`). Gateway bridge audio 2 chiều vào phòng LiveKit của tenant.

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect(
        "wss://acme.agents.noblex.vn/v1/voice",
        additional_headers={"Host": "acme.agents.noblex.vn",
                            "Authorization": "Bearer tnt_•••••"},
    ) as ws:
        await ws.send(json.dumps({"identity": {"phone": "0900000000"}, "call_id": "c-002"}))
        # -> bơm PCM16 16kHz (bytes) lên; nhận lại bytes = audio agent nói

asyncio.run(main())
```

### Test local (không có DNS thật)

Ghi đè `Host` trong khi trỏ IP:port gateway — logic chỉ đọc header `Host`:

```bash
websocat -H='Host: acme.agents.noblex.vn' -H='Authorization: Bearer tnt_•••••' \
         ws://127.0.0.1:9200/v1/chat
```

### Mã đóng WS khi lỗi (debug)

| Code | Nghĩa |
|------|-------|
| `4004` | `unknown_route` — path không phải `/v1/voice` hay `/v1/chat` |
| `4001` | `bad_host` / `tenant_inactive` / `no_bearer` / `bad_credential` (credential tenant A gửi lên host tenant B → `bad_credential`) |
| `4008` | `handshake_timeout` — không gửi frame handshake trong 10s |

> Đây chính là kênh mà **"Thử ngay" (BR03)** dùng — đi qua đúng đường khách hàng cuối, nên bài thử mới chứng minh được cấu hình chạy thật.
