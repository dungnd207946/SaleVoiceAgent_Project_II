# Handoff — API tạo agent phải trả **endpoint URL + token** (Portal/Dashboard)

> **Đối tượng:** team Portal/Dashboard (backend provisioning + màn tạo agent).
> **Mục tiêu:** khi provider tạo agent (tenant) xong, API tạo agent **trả về ngay**
> địa chỉ kết nối (URL) **kèm** credential (token) để provider nhúng vào backend/app
> của họ mà nói chuyện với agent.
> **Trạng thái:** contract — mô tả **đúng phần Portal còn thiếu**. Phía agent đã có
> sẵn hàm dựng URL + cấp/verify token (mục [§9](#9-tham-chiếu-code--contract)).
> **Ngày:** 2026-08-04 · **Bổ sung cho:** [`spec.md`](spec.md) (config) và
> C1/C5 trong [`../api/odyssey-agent-interface-contract.md`](../api/odyssey-agent-interface-contract.md).

---

## 1. Khoảng trống hiện tại

Provider kết nối vào agent qua **một** giao diện: **C1 Ingress** — WebSocket per-tenant
qua Gateway. Để dùng được nó provider cần **hai** thứ:

| Cần | Trạng thái hôm nay |
|---|---|
| **URL** endpoint per-tenant (voice `/v1/voice`, chat `/v1/chat`) | ❌ API tạo agent **chưa trả** |
| **Token** — credential per-tenant `tnt_<...>` để đặt `Authorization: Bearer` | ✅ backend đã sinh + đã lưu (hash) trong DB |

Token đã có nhưng **thiếu URL** ⇒ provider không biết nối đi đâu. C5.2 của interface
contract đã ghi rõ trách nhiệm này là của backend:

> *"`endpoint_url(tenant)` … → `wss://<tenant>.<base>/…`; **Backend trả cho provider
> lúc provisioning**."*

Việc cần làm: **thêm khối `endpoint` (URL voice + chat) vào response của API tạo
agent**, trả cùng lúc với token plaintext (token vẫn **chỉ hiện đúng một lần**).

Không cần thêm endpoint mới, không cần gọi API nào của agent. Chỉ là **bổ sung
trường vào response provisioning sẵn có**.

---

## 2. Thay đổi yêu cầu (một câu)

> Response của API **tạo agent** (và API **cấp lại/rotate credential**) phải chứa
> **URL kết nối voice + chat** + **token plaintext** (hiện một lần).

---

## 3. Response contract

### 3.1 Shape

Bổ sung vào response tạo-agent (giữ nguyên các trường đang có, chỉ **cộng thêm**):

```jsonc
{
  "tenant_id": "org_1d9f1a2f_demo-sales",

  // ── PHẦN CẦN THÊM ─────────────────────────────────────────────
  "endpoint": {
    "voice": "wss://org_1d9f1a2f_demo-sales.agents.noblex.vn/v1/voice",
    "chat":  "wss://org_1d9f1a2f_demo-sales.agents.noblex.vn/v1/chat"
  },
  "token": "tnt_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",  // plaintext, HIỆN MỘT LẦN
  "token_key_id": "a1b2c3d4",     // id public để revoke sau này (không phải token)
  // ──────────────────────────────────────────────────────────────

  "created_at": "2026-08-04T09:00:00Z"
}
```

### 3.2 Ngữ nghĩa từng trường mới

| Trường | Kiểu | Ngữ nghĩa |
|---|---|---|
| `endpoint.voice` | string (wss) | URL kênh **voice** — provider mở WS, gửi PCM16 16 kHz, nhận PCM16 24 kHz (C1.3). |
| `endpoint.chat` | string (wss) | URL kênh **chat** — provider mở WS, gửi/nhận JSON message (C1.4). |
| `token` | string | Credential plaintext `tnt_<...>`. Provider đặt vào header `Authorization: Bearer <token>`. **Chỉ trả một lần** — Portal lưu **hash**, không lưu plaintext. |
| `token_key_id` | string | Định danh public của credential (để `revoke` về sau). **Không** phải token, an toàn để log/hiển thị. |

> Trả **cả hai** URL kể cả khi provider dự định chỉ dùng một kênh — provider chọn
> kênh ở phía họ; đừng bắt họ tự ghép URL.

### 3.3 Phạm vi màn Dashboard (chốt với backend)

Dashboard **chỉ** hiển thị cho provider: **token dạng plaintext** (một lần, có nút
copy) + **2 URL** (voice/chat, copy được) để provider tự cầm đi đấu nối. Không cần
màn quản lý phức tạp hơn ở bản này.

- Token plaintext **chỉ hiện một lần ngay sau khi tạo** — sau đó DB chỉ còn hash,
  không hiển thị lại được. UI phải nói rõ điều này (kiểu "lưu lại ngay, không xem
  lại được").
- URL hiển thị lại được bất cứ lúc nào (dựng lại từ `tenant_id`, không phải bí mật).

---

## 4. Cách dựng URL — quy tắc bắt buộc

URL **phải** khớp đúng cách Gateway suy tenant, nếu không auth sẽ fail:

- **Mẫu:** `wss://<tenant_id>.<GATEWAY_BASE_DOMAIN>/v1/voice` (voice) và
  `.../v1/chat` (chat).
- `<tenant_id>` là **subdomain** (không phải path, không phải query). Gateway suy
  tenant từ **Host header** bằng khớp hậu tố **theo ranh giới dấu chấm** trên base
  domain (chống host giả kiểu `t1.evil.com`).
- `GATEWAY_BASE_DOMAIN` là **hằng số nền tảng**, ops cấu hình — Portal đọc từ config
  chung, **không** hardcode rải rác. Mặc định hiện tại: **`agents.noblex.vn`**
  ⇒ base template `wss://{tenant_id}.agents.noblex.vn`
  (nguồn: [config.py:109-110](../../src/noble_agent/config.py#L109-L110)).
- **Không** đổi hoa/thường, **không** URL-encode `tenant_id` (nó đã ở dạng slug
  `[a-z0-9_-]`, hợp lệ subdomain — xem `spec.md §7`).

> **Nguồn sự thật phía agent:** [`endpoint_url(tenant_id, settings)`](../../src/noble_agent/tenant/provisioning.py#L271)
> — Portal dựng URL **giống hệt** hàm này (`base = template.format(tenant_id).rstrip('/')`
> rồi nối `/v1/voice` · `/v1/chat`). Nếu Portal muốn, có thể gọi thẳng hàm này thay
> vì tự ghép chuỗi.

---

## 5. Token — bất biến & định dạng & **cách băm phải khớp agent**

### 5.1 Bất biến

- **Plaintext trả đúng MỘT lần** lúc tạo/cấp lại. Portal lưu **chỉ hash**; không ai
  đọc lại plaintext, kể cả admin. Mất ⇒ cấp lại (rotate), không khôi phục.
- Một tenant có thể có **nhiều** credential (nhiều deployment / rotate). Verify: hợp
  lệ nếu **bất kỳ** credential còn hiệu lực (`active`) của **đúng tenant** khớp.

### 5.2 Định dạng token

- `tnt_` + `token_urlsafe(32)` (C5.4). Tiền tố `tnt_` là bắt buộc — provider trình
  nguyên chuỗi (gồm `tnt_`) trong `Bearer`.

### 5.3 🔴 Cách băm — PHẢI khớp cách agent verify

**✅ CHỐT (backend xác nhận 2026-08-04): lưu `sha256(plaintext)` trần, KHÔNG salt.**
Đây là **đúng** cách agent verify ở đường Postgres — agent tự băm chuỗi sau
`Bearer ` bằng `sha256(...)` hex rồi so với hash trong DB
([pg_registry.py:43](../../src/noble_agent/gateway/pg_registry.py#L43)):

```
Portal lưu:  agent_api.tenant_keys.key_sha256 = encode(sha256(plaintext), 'hex')
Agent verify: hashlib.sha256(plaintext.encode()).hexdigest()  → so khớp
```

Điểm dễ sai nhất là lỡ băm **có salt** — token đúng vẫn bị từ chối `bad_credential`
(WS 4001). Đã chốt bare-sha256 nên không dính; giữ đúng, đừng thêm salt.

Kiểm chứng nhanh (phải ra đúng chuỗi Portal đã lưu):
```python
import hashlib; hashlib.sha256(plaintext.encode()).hexdigest()
```

> Đường MinIO/legacy (`_creds.json`) băm **salted** SHA-256
> ([credentials.py:27-28](../../src/noble_agent/tenant/credentials.py#L27-L28)) —
> **không dùng** ở luồng này (token nằm trong DB, không phải file). Ghi lại chỉ để
> khỏi nhầm sang cách băm đó.

> Bề mặt agent đọc để verify: view `agent_api.tenant_keys(tenant_id, key_sha256, active)`
> — hợp đồng đầy đủ ở [`agent-postgres-read-contract.md §1.3`](agent-postgres-read-contract.md).
> Portal đảm bảo `key_sha256` ở đó = bare-sha256 của plaintext đã phát.

---

## 6. Provider dùng URL + token thế nào (để Portal viết doc cho provider)

Chỉ để Portal hiểu đầu-cuối; chi tiết đầy đủ ở **C1** của interface contract.

1. Mở WS tới `endpoint.voice` **hoặc** `endpoint.chat`.
2. Đặt header `Authorization: Bearer <token>`. Gửi **đúng một** header `Host`
   (2 header Host trùng làm Gateway crash `1011` — C1.5).
3. **Frame đầu tiên** (≤10 s) là **1 text frame JSON handshake**:
   ```json
   {"identity": {"full_name": "Nguyễn Văn A", "phone": "09xxxxxxxx"}, "call_id": "abc-123"}
   ```
   `identity` rỗng ⇒ phiên vô danh; quá 10 s không gửi ⇒ đóng `4008`.
4. Sau đó: voice = binary PCM hai chiều (C1.3); chat = JSON message hai chiều (C1.4).

Mã đóng WS chuẩn (C1.5): `4001` auth fail (`bad_host`/`tenant_inactive`/`no_bearer`/
`bad_credential`), `4004` `unknown_route`, `4008` `handshake_timeout`.

---

## 7. Cấp lại / thu hồi (rotate / revoke)

- **Rotate:** API cấp-lại-credential trả **token plaintext mới** (hiện một lần) +
  `token_key_id` mới; URL **không đổi**. Credential cũ vẫn hiệu lực tới khi bị revoke.
- **Revoke:** theo `token_key_id`. Idempotent. Cuộc **đang chạy** không bị cắt; cuộc
  **mới** bị từ chối sau khi cache verify của Gateway hết TTL (C1.6).
- Idempotent tạo-agent: gọi lại API tạo cho tenant đã tồn tại **không** được âm thầm
  đẻ token mới trùng lặp — hoặc trả token hiện có (nếu Portal giữ được), hoặc yêu cầu
  đi qua đường rotate. (Quyết định của Portal; nêu rõ trong doc provider.)

---

## 8. Điều kiện ops kèm theo (không phải code Portal, nhưng chặn end-to-end)

URL trả về chỉ chạy khi hạ tầng ingress sẵn sàng:

1. ✅ **DNS wildcard** `*.<GATEWAY_BASE_DOMAIN>` trỏ về Gateway — **đã dựng**
   (backend xác nhận 2026-08-04). Mọi `<tenant_id>` là subdomain động, không tạo
   bản ghi DNS mỗi tenant.
2. ✅ **TLS wildcard cert** cho `*.<GATEWAY_BASE_DOMAIN>` — **đã dựng**.
3. **Gateway** (`noble-gateway`) đang chạy và đọc được bề mặt verify (Postgres
   `agent_api.tenant_keys`). Gateway verify từ **cache**, **không** gọi Portal live
   ⇒ Portal chết vẫn mở được cuộc mới (E01/C1.6).
4. Tenant ở trạng thái **active** (`agent_api.tenant_status.active=true`) — nếu
   `suspended/closed` thì Gateway đóng `4001 tenant_inactive` dù URL + token đúng.

---

## 9. Tham chiếu (code + contract)

| Câu hỏi | Nguồn |
|---|---|
| Dựng URL voice/chat từ `tenant_id` | [`tenant/provisioning.py::endpoint_url`](../../src/noble_agent/tenant/provisioning.py#L271) |
| Sinh credential plaintext (một lần) | [`tenant/provisioning.py::issue_credential`](../../src/noble_agent/tenant/provisioning.py#L235) |
| Băm/verify token (đường Postgres, **bare sha256**) | [`gateway/pg_registry.py`](../../src/noble_agent/gateway/pg_registry.py#L43) |
| Băm/verify token (đường MinIO, salted) | [`tenant/credentials.py`](../../src/noble_agent/tenant/credentials.py#L27) |
| Template URL + base domain (mặc định) | [`config.py:109-110`](../../src/noble_agent/config.py#L109-L110) |
| Hợp đồng ingress (handshake, frame, mã đóng) | `../api/odyssey-agent-interface-contract.md` **C1** |
| Hợp đồng cấp phát + credential | `../api/odyssey-agent-interface-contract.md` **C5** |
| Bề mặt Postgres agent đọc để verify token | [`agent-postgres-read-contract.md §1.3`](agent-postgres-read-contract.md) |
| Định dạng `tenant_id` / `org_id` | [`spec.md §7`](spec.md) |

---

## 10. Checklist bàn giao (Portal tick)

- [ ] API tạo agent trả thêm khối `endpoint.voice` + `endpoint.chat`.
- [ ] URL dựng đúng mẫu `wss://<tenant_id>.<GATEWAY_BASE_DOMAIN>/v1/{stream,chat}`
      (subdomain = `tenant_id`, không path/query; không đổi hoa-thường).
- [ ] `GATEWAY_BASE_DOMAIN` đọc từ config nền tảng, không hardcode.
- [ ] Trả `token` plaintext **một lần** + `token_key_id`; lưu **chỉ hash**.
- [x] Hash lưu = **`sha256(plaintext)` trần**, **không salt** (khớp
      `agent_api.tenant_keys.key_sha256`, đường Postgres) — ✅ backend đã chốt.
- [ ] Dashboard hiển thị token plaintext (một lần, có cảnh báo "không xem lại được")
      + 2 URL copy được (§3.3).
- [ ] API rotate credential trả token mới (một lần), URL không đổi.
- [ ] Doc cho provider: cách đặt `Authorization: Bearer` + frame handshake đầu tiên
      (trích C1).
- [x] (Ops) DNS + TLS wildcard `*.<GATEWAY_BASE_DOMAIN>` sẵn sàng — ✅ đã dựng.
- [ ] (Ops) Gateway (`noble-gateway`) đang chạy + đọc được `agent_api.tenant_keys`.
