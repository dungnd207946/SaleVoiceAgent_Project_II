# SaaS Slice #2 — Provider gọi thẳng worker qua URL + credential riêng

| | |
|---|---|
| Ngày | 2026-07-29 |
| Branch | `feat/refactor2` |
| Trạng thái | Design — chờ user review trước khi lập plan |
| Tài liệu nền | Notion HT_01 "Quan hệ Dashboard · Backend · Agent" (v1.1), §II. Mô tả tính năng |
| Slice trước | #1 — Externalize tenant store to MinIO (`tenant/store.py`, `provisioning.py`, `materialize.py`, `loader.py`, `cli.py`) |

## 1. Bối cảnh & mục tiêu

SaaS này để **provider client tự tạo agent rồi tích hợp vào nền tảng của họ**. Kiến trúc đích (HT_01): **ba lớp, hai chiều, một nguồn sự thật** — Dashboard → Backend (control plane) → Agent (worker mỗi tenant một bản). Control plane **KHÔNG nằm trên đường hội thoại**; client gọi **thẳng** worker.

Slice này hiện thực **cái pivot đó** với thay đổi nhỏ nhất, dưới dạng gộp hai sub-project:

- **SP-A** — Provider-facing per-tenant transport + credential verify (kênh client → worker trực tiếp).
- **SP-B** — Provisioning cấp credential + trả `{endpoint, credential}`.

Mục tiêu đo được: một provider, cầm `{endpoint_url, credential}` do provisioning trả, mở được **cả cuộc voice lẫn phiên chat** thẳng tới worker của **đúng tenant mình**, không chạm control plane trên đường setup, và **không** provider nào chạm được tenant khác.

### Vì sao pivot này là bắt buộc, không phải tuỳ chọn

Mô hình cũ (message → control plane → route tới worker) **vi phạm E01** của HT_01 ("Backend chết → agent vẫn phục vụ khách hàng cuối"): control plane trên đường hội thoại nghĩa là control plane chết = mọi tenant chết. Với full voice stack + audio real-time, proxy audio qua control plane cũng vô nghĩa về kỹ thuật. Nên client → worker trực tiếp là lựa chọn khả thi duy nhất.

## 2. Các quyết định đã chốt

| # | Quyết định | Ghi chú |
|---|---|---|
| D1 | **Client = backend của provider (server-to-server)** | Provider cầm credential, tự forward cho end-user của họ. Auth ở tầng provider, không phải end-user. |
| D2 | **Addressing = URL riêng mỗi tenant** (subdomain) | DNS/ingress trỏ về gateway, route theo Host. "Địa chỉ pod là việc của ops" (HT_01). |
| D3 | **Worker = full voice stack**, GPU ở service `remote` dùng chung | Pod nhẹ (orchestration + transport), chi phí cố định thấp → đầu vào bảng giá §II.2.3. Service chia sẻ vô trạng thái → ngoài ranh giới cách ly (BR15). |
| D4 | **LiveKit = media plane NỘI BỘ**; provider chỉ thấy API đơn giản | Worker LiveKit **giữ nguyên** media path. |
| D5 | **Biến thể A** — gateway dùng chung, nhận-diện-tenant, đứng trước LiveKit | Dồn code mới/rủi ro vào một service ingress stateless; worker proven không bị động. |
| D6 | **Credential dài hạn, verify cục bộ từ cache, control plane ngoài path setup** | Giữ E01 tuyệt đối: Portal chết vẫn mở được cuộc mới. |
| D7 | **WS audio là giao thức ingress đầu tiên** | SIP + native-LiveKit fast-path để sau (chỉ tài liệu hoá). |
| D8 | **6b — seed identity trong slice này** | Handshake mang `identity`; worker chạm 1 chỗ để seed `Customer`. |
| D9 | **Chat cũng chạy, ý tưởng tương tự voice; route bằng reverse-proxy WS** | Gateway proxy tới `text_chat.py` của worker; chat handler santa gần như nguyên vẹn. |

## 3. Kiến trúc

```
Provider backend  (giữ per-tenant credential)
   │  VOICE: wss://<tenant>.agents.noblex.vn/v1/stream   + Bearer <tenant-cred>
   │  CHAT : wss://<tenant>.agents.noblex.vn/v1/chat     + Bearer <tenant-cred>
   ▼
DNS/ingress  →  ┌─ Ingress Gateway (dùng chung, stateless, nhận-diện-tenant) ─┐
                │  1. tenant ← Host                                           │
                │  2. verify Bearer  ← credential registry CACHE (TTL)        │  ← KHÔNG gọi Portal sống
                │  3a VOICE: mint LiveKit token → join room → bridge audio    │
                │  3b CHAT : reverse-proxy WS → worker chat endpoint          │
                └──────────────┬───────────────────────┬─────────────────────┘
                     VOICE      │                       │  CHAT (proxy)
                                ▼                       ▼
                    LiveKit room (tenant+call)   ws://agent-<tenant>:PORT/chat
                                ▲                       │
                       dispatch │ agent-<tenant>        │
                                └────── Worker pod (TENANT_ID=<tenant>) ───────┘
                                        • media path GIỮ NGUYÊN
                                        • agent_name = agent-<TENANT_ID>
                                        • đọc identity handshake → seed Customer (6b)

Control plane (provisioning lib + tenant store) — NGOÀI data path
   • create tenant → cấp credential → trả {endpoint_url, credential}
Shared GPU services: STT/TTS/LLM/embed (ngoài ranh giới cách ly)
```

## 4. Thành phần

### 4.1 Credential model & storage

- Sinh secret entropy cao: `secrets.token_urlsafe(32)`. Plaintext format: **`tnt_<tenant_id>_<secret>`** — đọc được tenant từ chính token (defense-in-depth cạnh Host).
- **Chỉ lưu HASH** (SHA-256 có salt per-credential; salt lưu kèm). Plaintext trả **đúng một lần**, không bao giờ lưu.
- Lưu **danh sách credential active** (mỗi entry: `key_id`, `salt`, `hash`, `created_at`, `revoked_at?`) để **xoay vòng** không đứt provider đang chạy.
- Vị trí lưu: object `<tenant_id>/_creds.json` trong tenant store (cạnh `_meta.json`/bundle). **KHÔNG** đưa plaintext vào bundle. Hash **có thể** đi xuống worker qua bundle nếu sau này cần verify tại worker; slice này verify tại **gateway** nên gateway là bên đọc `_creds.json`.

### 4.2 Provisioning (SP-B) — mở rộng `tenant/provisioning.py`

Hàm mới (thuần trên `TenantStore` đã inject, style slice #1):

- `issue_credential(store, tenant_id, *, now=None) -> str` — sinh + lưu hash vào `_creds.json`, trả plaintext (một lần). Fail nếu tenant không tồn tại.
- `revoke_credential(store, tenant_id, key_id, *, now=None) -> None` — đánh dấu `revoked_at`.
- `list_credentials(store, tenant_id) -> list[CredentialMeta]` — chỉ metadata (key_id/created/revoked), **không** hash/plaintext.
- `create_tenant(...)` — thêm tuỳ chọn auto-cấp credential đầu tiên; trả kèm plaintext.
- `endpoint_url(tenant_id) -> str` — render từ `TENANT_ENDPOINT_TEMPLATE`.

Payload provisioning trả về provider:
```json
{ "tenant_id": "...", "endpoint": { "voice": "wss://<t>.../v1/stream", "chat": "wss://<t>.../v1/chat" }, "credential": "tnt_<t>_<secret>" }
```

CLI `noble-tenant`: thêm `issue-cred <tenant>`, `revoke-cred <tenant> <key_id>`, `list-creds <tenant>`.

### 4.3 Ingress gateway (SP-A) — package mới `gateway/`

Server WS độc lập (chạy tiến trình riêng, scale ngang). Chung cho cả hai mode:

1. **Resolve tenant** từ `Host` header (subdomain). Sai định dạng / tenant không active → 404/403.
2. **Verify** `Authorization: Bearer <cred>`:
   - Đọc credential registry từ **cache** (`gateway.cred_registry` — nạp `_creds.json` theo tenant, TTL refresh `GATEWAY_CRED_CACHE_TTL_SEC`). **Không gọi Portal API sống** (E01).
   - So `token` với các hash active của tenant (recompute với salt tương ứng, `hmac.compare_digest`). Optional: đối chiếu `<tenant_id>` nhúng trong token khớp Host.
   - Revoked / không khớp / tenant lệch → 401.
3. **Handshake**: message JSON đầu mang `{ identity: {...}, call_id? }`. Gateway validate, không thực thi gì từ payload (no-execution).

**Voice (`/v1/stream`)**:
- Mint LiveKit token (gateway giữ LiveKit secret — hạ tầng chung, không phải dữ liệu tenant). Room scoped `tenant+call` (unique mỗi cuộc, theo pattern `app_session._derive_session_id` + suffix ms/hex). `RoomConfiguration(agents=[RoomAgentDispatch(agent_name="agent-<tenant>")])`.
- Nhét `identity` vào **participant/room metadata**.
- Join room như participant "caller"; relay: provider WS audio frames ⇄ published LiveKit audio track; JSON control ⇄ data channel.

**Chat (`/v1/chat`)**:
- Reverse-proxy WS tới `ws://agent-<tenant>:PORT/chat` (service discovery §4.5). Chuyển `identity` xuống handshake được proxy.
- Bỏ `connect_token` per-session cũ; auth thật ở gateway. Worker chat endpoint tin gateway qua **shared internal secret** (`GATEWAY_WORKER_SECRET`) hoặc network policy.

**Tính chất:** gateway thuộc **serving plane** (ngang LiveKit server / LiveKit SIP-ingress), **không** control plane → giữ BR01/BR02. Chỉ auth + relay, **không thực thi code tenant**.

### 4.4 Worker touch (tối thiểu)

- `agent_name` suy từ `TENANT_ID`: `agent-<TENANT_ID>` (cấu hình, để LiveKit dispatch đúng worker). Chạm `transport/livekit/worker.py` phần đăng ký.
- **6b seed identity — 1 chỗ**:
  - Voice: đầu session đọc participant/room metadata → nếu có `identity`, seed `Customer` qua `StateRepo.save_all` (đúng path `app_session` đang dùng).
  - Chat: đọc `identity` từ handshake được proxy (thay `provision_session` seed trước-WS) → seed tương tự.
- Media path + turn loop **không đụng**.

### 4.5 Config / settings mới

| Setting | Default | Vai trò |
|---|---|---|
| `TENANT_ENDPOINT_TEMPLATE` | `wss://{tenant_id}.agents.noblex.vn` | Render `endpoint.voice/chat` (gắn `/v1/stream`, `/v1/chat`). |
| `GATEWAY_HOST` / `GATEWAY_PORT` | `0.0.0.0` / `9200` | Bind của gateway. |
| `GATEWAY_CRED_CACHE_TTL_SEC` | `30` | TTL cache credential registry (đọc từ store). |
| `GATEWAY_WORKER_SECRET` | empty | Shared secret gateway↔worker chat endpoint (empty = tin network). |
| `WORKER_CHAT_INTERNAL_URL_TEMPLATE` | `ws://agent-{tenant_id}:8766/chat` | Service discovery gateway→worker cho chat proxy. |

Reuse sẵn có: `LIVEKIT_API_KEY/SECRET`, `LIVEKIT_URL/PUBLIC_URL`, `livekit_agent_name` (nay suy theo tenant).

## 5. Bất biến phải giữ (map sang HT_01)

- **BR01** (agent không gọi Portal API): worker không đổi; gateway verify từ cache, không gọi Portal sống.
- **BR02** (backend không gọi xuống agent): mọi thứ do provider/gateway khởi xướng đi vào; control plane không gọi worker.
- **E01** (backend chết, khách cuối không sao): gateway + worker + LiveKit + service chia sẻ đủ để mở cuộc mới; Portal/provisioning không nằm trên path setup.
- **Cách ly tenant**: gateway chỉ bridge/proxy vào tài nguyên của tenant khớp credential; voice dispatch `agent-<tenant>`; chat proxy `agent-<tenant>`. Một provider không chạm tenant khác.
- **No-execution** (giữ tính chất slice #1): gateway chỉ auth + relay, không import/thực thi code tenant.

## 6. Ngoài phạm vi (hoãn — ghi để không hiểu nhầm)

- SIP ingress; native-LiveKit fast-path (provider tự join room bằng token) — chỉ **tài liệu hoá**, không xây.
- Config versioning bất biến + con trỏ + rollback (SP-C).
- Nhịp tim ↑ + suy ra trạng thái dashboard (SP-D).
- Data-plane Postgres + RLS + role riêng + Qdrant collection riêng (SP-E) — **độc lập**, không chặn slice này.
- Cơ chế nhân bản credential registry đa-vùng; slice này cache đọc thẳng store là đủ.

## 7. Kế hoạch test (TDD)

**Unit (offline, fake store + fake LiveKit minter + fake WS):**
- Credential: issue → verify khớp; wrong secret → fail; revoked → fail; rotate (2 active) → cả hai verify; `_creds.json` chỉ chứa hash (không plaintext).
- Gateway auth: tenant từ Host đúng/sai; Bearer hợp lệ/sai/nhầm-tenant/revoked; tenant không active → từ chối.
- Endpoint URL render đúng template (voice + chat).
- No-execution: payload handshake độc hại không được import/eval.
- Worker seed: identity handshake → `Customer` được seed đúng field (voice metadata + chat handshake), thiếu identity → session ẩn danh (không crash).

**Integration / smoke (cần LiveKit + worker thật):**
- Voice: provider WS → nghe được agent nói (relay audio hai chiều), dispatch đúng `agent-<tenant>`.
- Chat: provider WS → nhận được token/tool_done, seed identity phản ánh trong lượt đầu.
- Cross-tenant: credential tenant A + Host tenant B → từ chối.

Gate: `make test-unit` không thêm failure mới ngoài baseline đã biết; ruff sạch trên file mới.

## 8. Rủi ro & câu hỏi mở

- **R1 — Service discovery cho chat proxy** phụ thuộc hạ tầng (K8s Service mỗi tenant). Nếu triển khai không phải K8s, template URL phải đổi. Ghi rõ là điểm cấu hình.
- **R2 — LiveKit `agent_name` collision**: mỗi tenant worker phải đăng ký tên duy nhất `agent-<tenant>`; provisioning/deploy phải đảm bảo tên khớp `TENANT_ID`.
- **R3 — Cache credential trễ thu hồi**: revoke có độ trễ tối đa `GATEWAY_CRED_CACHE_TTL_SEC`. Chấp nhận; nếu cần thu hồi tức thì → thêm invalidation event (ngoài phạm vi).
- **Q1 — Rate limit / abuse** tại gateway per-tenant: cần không trong slice này? (đề xuất: hoãn, ghi nhận.)
- **Q2 — Định dạng khung audio WS** (PCM16/opus, sample rate, khung control JSON): chốt trong plan, mô phỏng theo `voice/service/protocol.py` sẵn có.
