# Contract — Bề mặt Postgres agent ĐỌC (Portal ship) để agent bỏ MinIO

> **Đối tượng:** team Portal/Backend (Odyssey).
> **Mục tiêu:** agent hội thoại (1 process share phục vụ N tenant) **bỏ MinIO** khỏi luồng
> config/serving và đọc **trực tiếp Postgres** do Portal sở hữu. Tài liệu này đặc tả **chính
> xác những bề mặt đọc Portal phải để lộ** cho agent, ngữ nghĩa, cách ly RLS, GRANT, và DDL
> **tham khảo** (Portal được đặt tên/hiện thực nội bộ khác, miễn giữ đúng ngữ nghĩa + bề mặt).
> Nền tảng: `docs/api/SPEC-DB-HIEN-TAI.md` (lược đồ hiện tại) + `docs/handoff/spec.md` (contract config).
> Ngày: 2026-08-04.
>
> ---
>
> ⚠️ **TÀI LIỆU NÀY MÔ TẢ MỘT BỀ MẶT ĐÃ BỊ XOÁ — đọc trước khi tin bất cứ dòng nào.**
> Toàn bộ §1 đặc tả schema **`agent_api`**, mà migration `0917` (2026-08-10) đã
> `DROP SCHEMA agent_api` — quyết định có chủ ý, đảo ngược lập luận gốc của `0005`: agent nay
> đọc THẲNG `tenant_data.*`, cách ly dựa vào RLS FORCE (`0913`) chứ không vào view DEFINER.
> §1.1–§1.4 vì thế là **lịch sử**, không phải hiện trạng.
>
> §2 (`control.agent_heartbeats`) VẪN SỐNG và **đã cập nhật theo `0941`** — nhịp tim khoá theo
> `tenant_id`, `control.deployments` bỏ hẳn.
>
> Nguồn sự thật hôm nay: `dau-noi-agent.md` (các banner đầu file, theo thứ tự thời gian).

## 0. Nguyên tắc

- Agent **chỉ ĐỌC**, qua schema **`agent_api`** (giống 5 view KB hiện có). Ngoại lệ ghi **duy
  nhất**: `control.agent_heartbeats` (grant đã có sẵn — SPEC §3.12).
- Agent kết nối bằng **một role runtime dùng chung** `odyssey_agent` (không phải per-tenant
  login `agent_<tenant>`). Vì vậy:
  - **Portal phải `GRANT agent_all TO odyssey_agent`** để role dùng chung thừa hưởng quyền của
    nhóm `agent_all` (SELECT `agent_api.*`, RW `control.agent_heartbeats`).
  - `portal.current_tenant()` với `session_user = 'odyssey_agent'` không khớp regex `^agent_(.+)$`
    ⇒ **tự động fallback về GUC `app.tenant_id`**. Agent set GUC này mỗi transaction (mục §6).
- Mỗi view lọc tenant **tường minh** bằng `WHERE … = portal.current_tenant()` (đúng khuôn 5 view
  KB — không dựa RLS của view-owner), nên tự động cách ly theo tenant hiện tại.
- Tất cả view thuộc `agent_api`, **owner = `portal_api`**, `GRANT SELECT TO agent_all`
  (+ `ALTER DEFAULT PRIVILEGES` như hiện hành). Nhờ owner là `portal_api`, view đọc được
  `control.*` mà **không** cần grant `control.*` trực tiếp cho agent.

## 1. Bốn bề mặt ĐỌC (agent_api)

### 1.1 `agent_api.agent_published_config` — config đang publish
Agent build prompt + pin version từ đây. **Hợp đồng đọc** (agent chạy đúng câu này):
```sql
SELECT version, config FROM agent_published_config WHERE tenant_id = <current>;
```

| Cột | Kiểu | Ngữ nghĩa |
|---|---|---|
| `tenant_id` | `text` | = `portal.current_tenant()` |
| `version` | `int` | version **đang publish** (đơn điệu tăng / tenant) |
| `config` | `jsonb` | object shape `docs/handoff/spec.md §4` (identity/scope/tools/data_source) |

- **Đúng 0 hoặc 1 dòng / tenant.** Chưa publish ⇒ 0 dòng (agent fail-closed: last-good/mặc định).
- Portal quyết cơ chế "đâu là version published" (con trỏ published hay `max(version)`); view
  chỉ cần lộ ra **một** dòng = bản đang chạy. Nguồn thật hiện tại: `control.config_versions
  (tenant_id, version, payload jsonb, …)` — map `payload → config`.
- ⚠️ **Tên/vị trí:** reader agent gọi **không kèm schema** (`FROM agent_published_config`). Portal
  bảo đảm nó resolve được cho role agent: đặt trong `agent_api` **và** để `agent_api` trên
  `search_path` của `odyssey_agent` (vd `ALTER ROLE odyssey_agent SET search_path = agent_api,
  public`), hoặc tạo alias. (Reader agent giữ nguyên, không sửa.)

Reference DDL (biến thể "có con trỏ published"; nếu dùng `max(version)` thì đổi phần JOIN):
```sql
CREATE VIEW agent_api.agent_published_config AS
SELECT v.tenant_id, v.version, v.payload AS config
FROM   control.config_versions v
JOIN   control.config_pointer  p            -- hoặc: điều kiện max(version)
       ON p.tenant_id = v.tenant_id AND p.published_version = v.version
WHERE  v.tenant_id = portal.current_tenant();
GRANT SELECT ON agent_api.agent_published_config TO agent_all;
```

### 1.2 `agent_api.tenant_status` — tenant còn hoạt động?
Gateway kiểm active trước khi verify credential.

| Cột | Kiểu | Ngữ nghĩa |
|---|---|---|
| `tenant_id` | `text` | = `portal.current_tenant()` |
| `active` | `bool` | `lifecycle = 'active'` |

- 0 dòng ⇒ tenant không tồn tại trong scope ⇒ agent coi như **không active**.

```sql
CREATE VIEW agent_api.tenant_status AS
SELECT id AS tenant_id, (lifecycle = 'active') AS active
FROM   control.tenants
WHERE  id = portal.current_tenant();
GRANT SELECT ON agent_api.tenant_status TO agent_all;
```

### 1.3 `agent_api.tenant_keys` — verify bearer (sha256 trần)
Gateway băm **`sha256(plaintext)`** (KHÔNG salt) rồi tra bảng này. Có dòng `active=true` khớp
`key_sha256` ⇒ hợp lệ.

| Cột | Kiểu | Ngữ nghĩa |
|---|---|---|
| `tenant_id` | `text` | = `portal.current_tenant()` |
| `key_sha256` | `text` | `= encode(sha256(plaintext_token), 'hex')` (khớp `control.agent_keys.key_sha256`) |
| `active` | `bool` | `revoked_at IS NULL` |

- Một tenant có thể có **nhiều** key (xoay khoá không gián đoạn). Agent chấp nhận nếu **bất kỳ**
  dòng `active=true` khớp sha256.
- **Cách ly:** vì view lọc theo `current_tenant()`, gửi token của tenant khác kèm Host của tenant
  này ⇒ 0 dòng ⇒ từ chối (`bad_credential`). Không lộ key chéo tenant.
- **Định dạng token:** Portal tự quyết (prefix, độ dài). Agent băm nguyên chuỗi sau `Bearer `.
  `key_sha256` = sha256 của **đúng chuỗi plaintext Portal phát cho provider**.

```sql
CREATE VIEW agent_api.tenant_keys AS
SELECT d.tenant_id, k.key_sha256, (k.revoked_at IS NULL) AS active
FROM   control.agent_keys k
-- ⚠️ LỖI THỜI: 0940 bỏ `agent_keys.deployment_id` (khoá có `tenant_id` trực tiếp),
-- 0941 bỏ hẳn bảng `control.deployments`. Câu JOIN này không chạy được nữa.
JOIN   control.deployments d ON d.id = k.deployment_id
WHERE  d.tenant_id = portal.current_tenant();
GRANT SELECT ON agent_api.tenant_keys TO agent_all;
```

### 1.4 `agent_api.deployments` — ĐÃ BỎ, KHÔNG CÒN CẦN

Mục này từng đặc tả một view để agent tra `deployment_id` cho nhịp tim. Ba bước đã xoá nó:
`0917` bỏ cả schema `agent_api`; `0919` bỏ cột `kind` (một khoá dùng chung chat lẫn voice);
`0941` bỏ hẳn bảng `control.deployments` và đổi khoá `agent_heartbeats` sang `tenant_id`.

**Agent không cần tra id nào nữa** — `tenant_id` là thứ duy nhất cần, và nó luôn có sẵn ở
caller. Xem §2.

## 2. Bề mặt GHI — `control.agent_heartbeats`

Đã tồn tại + đã có RLS 2-policy + grant cho `agent_all` (SPEC §3.12). Agent **upsert**:
```sql
INSERT INTO control.agent_heartbeats
  (tenant_id, running_version, bundle_sha, agent_version, last_error, last_seen_at)
VALUES ($1,$2,$3,$4,$5, now())
ON CONFLICT (tenant_id) DO UPDATE
SET running_version=EXCLUDED.running_version, bundle_sha=EXCLUDED.bundle_sha,
    agent_version=EXCLUDED.agent_version, last_error=EXCLUDED.last_error,
    last_seen_at=now();
```
- `running_version` = version đang chạy (từ `agent_published_config.version`).
- `bundle_sha` = sha config đang chạy (nếu view lộ; nếu không, `''`).
- **MỘT hàng mỗi TENANT** từ `0941` (trước là một hàng mỗi `(tenant, deployment)`). Hai pod
  chat/voice của cùng workspace nay đè lên nhau — Portal vốn đã đọc hàng `last_seen_at` mới
  nhất nên chip trạng thái không đổi, nhưng bảng này không còn phân biệt được pod.
- Không còn điều kiện tiên quyết nào: không cần hàng `deployments`, không cần tra id. Agent có
  `tenant_id` là beat được.

## 3. GRANT / role checklist (Portal chạy 1 lần)

```sql
-- role runtime dùng chung của agent thừa hưởng nhóm agent_all
GRANT agent_all TO odyssey_agent;
-- search_path để reader gọi agent_published_config không kèm schema
ALTER ROLE odyssey_agent SET search_path = agent_api, public;
-- 4 view ở §1 + GRANT SELECT agent_all (đã kèm trên)
-- control.agent_heartbeats: RW cho agent_all đã có sẵn (SPEC §3.12) — xác nhận.
```

## 4. GUC / cách ly (khớp `portal.current_tenant()`)

- `portal.current_tenant()` suy tenant: `session_user` khớp `^agent_(.+)$` → else GUC
  `app.tenant_id`. Role `odyssey_agent` **không** khớp regex ⇒ **dùng `app.tenant_id`**.
- Agent set **`app.tenant_id`** (và cả `app.current_tenant` cho tương thích data-plane
  agent-owned) qua `SET LOCAL` mỗi transaction. Portal **không cần** làm gì thêm ngoài việc
  `portal.current_tenant()` đọc `app.tenant_id` (đã đúng theo SPEC §6).

## 5. Bất biến & lỗi (semantics agent dựa vào)

| Tình huống | Bề mặt trả | Hành vi agent |
|---|---|---|
| Chưa publish config | `agent_published_config` 0 dòng | last-good on-disk hoặc mặc định an toàn (không crash) |
| Tenant `suspended`/`closed` | `tenant_status.active=false` | gateway từ chối (`tenant_inactive`, WS 4001) |
| Token sai/không thuộc tenant | `tenant_keys` 0 dòng khớp | `bad_credential` (WS 4001) |
| Token bị revoke | dòng `active=false` | `bad_credential` |
| Chưa có deployment cho (tenant,kind) | `deployments` 0 dòng | bỏ beat tenant đó (log), không lỗi |
| Config đã publish nhưng đang đổi | version bất biến / tenant | cuộc gọi đang chạy giữ version pin; cuộc gọi mới đọc version mới (BR05) |

**Bất biến version (bắt buộc):** một `(tenant, version)` **không đổi nội dung** sau publish
(chỉ đổi con trỏ published). Đây là điều kiện để agent pin version an toàn suốt cuộc gọi.

## 6. Điều Portal KHÔNG cần làm

- Không gọi API nào của agent (agent tự đọc + tự đẩy heartbeat — BR02).
- Không đụng persona skeleton (agent-owned trên disk).
- Không cần MinIO (bề mặt này thay thế hoàn toàn tenant-store MinIO cho luồng config/serving).

## 7. Checklist bàn giao (Portal tick)

- [ ] `agent_api.agent_published_config` (§1.1) + resolvable cho `odyssey_agent` (search_path).
- [ ] `agent_api.tenant_status` (§1.2).
- [ ] `agent_api.tenant_keys` (§1.3) — `key_sha256 = sha256(plaintext)` trần, khớp cách agent băm.
- [ ] `agent_api.deployments` (§1.4) + đảm bảo 1 deployment/tenant/kind khi provisioning.
- [ ] `GRANT agent_all TO odyssey_agent` (§3) + xác nhận RW `control.agent_heartbeats`.
- [ ] `portal.current_tenant()` đọc `app.tenant_id` (đã đúng — xác nhận).
- [ ] Publish v1 ngay khi tạo tenant (để `agent_published_config` có dòng cho agent đọc).
