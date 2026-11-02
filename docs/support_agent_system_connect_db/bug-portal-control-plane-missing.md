# BUG HANDOFF — Portal API: thiếu control-plane DB cho agent db-mode

- **Ngày:** 2026-08-05
- **Từ:** Team Agent (Hotline / odyssey-agent)
- **Tới:** Team Portal API (Backend)
- **Môi trường:** `agents-dev`
- **DB:** Aurora PostgreSQL `odyssey_db`
  (`noblex-dev-database-aurora-postgresql.cluster-czs2osg0imrz.ap-southeast-1.rds.amazonaws.com:5432`)
- **Mức độ:** Blocker — e2e chat db-mode không chạy được cho tới khi có phần này.

---

## 1. Tóm tắt một câu

Gateway + worker đã chạy đúng **db-mode** (`AGENT_CONFIG_SOURCE=db`), nhưng Aurora
`odyssey_db` **chưa có** các schema/view control-plane mà agent đọc theo contract:
`agent_api.tenant_status`, `agent_api.tenant_keys`, `agent_api.deployments`, và
`agent_published_config`. **Đây không phải bug code agent** — agent query đúng theo
hợp đồng; Portal cần tạo các quan hệ này và publish config cho tenant.

---

## 2. Bối cảnh

Ở db-mode, agent **không đọc MinIO** nữa. Toàn bộ control-plane (xác thực gateway,
version worker, config tenant, heartbeat) đọc từ Postgres do Portal sở hữu:

- **Gateway** verify request của provider → đọc `agent_api.tenant_status` +
  `agent_api.tenant_keys`.
- **Worker** khởi tạo agent cho tenant → đọc `agent_published_config`.

Runtime kết nối bằng **một** app role dùng chung (không phải role-per-tenant):

| Vai trò | Role | DSN |
|---|---|---|
| Runtime (gateway + worker) | `odyssey_app` | `POSTGRES_DSN` |
| Provisioning/admin | `odyssey_migrator` | `POSTGRES_ADMIN_DSN` |

Mỗi transaction, agent set 2 GUC trước khi query (dùng cho RLS phía Portal nếu có):

```sql
SELECT set_config('app.current_tenant', <tenant_id>, true);  -- data-plane RLS (agent-owned)
SELECT set_config('app.tenant_id',      <tenant_id>, true);  -- control-plane RLS (Portal-owned)
```

→ Nếu Portal bật RLS trên các view control-plane, hãy scope theo
`current_setting('app.tenant_id', true)`.

---

## 3. Triệu chứng (log thật)

### Lỗi A — thiếu `agent_api.tenant_status` (chặn ở gateway auth)

```
pg_registry: is_active read failed for dufake
Traceback (most recent call last):
  File "/app/src/noble_agent/gateway/pg_registry.py", line 26, in is_active
    return await self._reader.read_tenant_active(tenant_id)
  File "/app/src/noble_agent/storage/agent_control_store.py", line 27, in read_tenant_active
    row = await conn.fetchrow(_SQL_STATUS, tenant_id)
  ...
asyncpg.exceptions.UndefinedTableError: relation "agent_api.tenant_status" does not exist
```

Kết quả: client bị đóng WebSocket `1011` khi kết nối `/v1/chat`.

### Lỗi B — thiếu `agent_published_config` (chặn ở worker khởi tạo LLM)

```
[error] {'type': 'error', 'message': "LLM init failed: no published config for tenant 'dufake'"}
```

Nguyên nhân: `read_published_config('dufake')` bắt `UndefinedTable`/không có row →
trả `None` → worker báo "no published config".

---

## 4. Nguyên nhân gốc

Aurora `odyssey_db` **chưa được Portal khởi tạo** các quan hệ control-plane +
chưa publish config cho tenant. Agent đọc đúng theo contract nhưng không có gì để đọc.

Ranh giới trách nhiệm:

- **Team Agent:** deploy đúng image db-mode (đã xong), query theo contract (đã đúng).
- **Team Portal:** **tạo + cấp quyền + đổ dữ liệu** cho các quan hệ dưới đây. ⬅ phần còn thiếu.

---

## 5. Portal phải cung cấp (yêu cầu chi tiết)

> Ground truth = các câu SQL agent thực sự chạy (trích từ code agent, không thể đổi
> phía agent). Portal phải cung cấp quan hệ khớp **tên + cột + kiểu** này. Có thể là
> TABLE hoặc VIEW, miễn `odyssey_app` `SELECT` được và trả đúng cột.

### 5.1 `agent_api.tenant_status`

Agent chạy:
```sql
SELECT active FROM agent_api.tenant_status WHERE tenant_id = $1;
```
Cột tối thiểu:

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `tenant_id` | `text` | id tenant (trần, ví dụ `dufake`) |
| `active` | `boolean` | tenant có đang hoạt động không |

### 5.2 `agent_api.tenant_keys`

Agent chạy:
```sql
SELECT key_sha256, active FROM agent_api.tenant_keys WHERE tenant_id = $1;
```
Cột tối thiểu:

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `tenant_id` | `text` | id tenant |
| `key_sha256` | `text` | **hex lowercase** của `sha256(<api_key_plaintext>)` |
| `active` | `boolean` | key còn hiệu lực không |

**Quan trọng về verify:** gateway tính `sha256(plaintext).hexdigest()` (hex thường)
rồi so bằng nhau với `key_sha256`. Portal lưu hash y hệt cách này. Ví dụ trong PG:
```sql
encode(sha256('<api_key_plaintext>'::bytea), 'hex')
```

### 5.3 `agent_api.deployments`

Agent chạy (cho heartbeat):
```sql
SELECT id FROM agent_api.deployments WHERE tenant_id = $1 AND kind = $2 ORDER BY id DESC LIMIT 1;
```
Cột tối thiểu:

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `id` | `bigint` | id deployment (dùng cho `control.agent_heartbeats.deployment_id`) |
| `tenant_id` | `text` | id tenant |
| `kind` | `text` | loại process (ví dụ `chat` / `voice`) |

### 5.4 `agent_published_config`  ⚠️ (xem thêm mục 6 — schema/search_path)

Agent chạy (**không có prefix schema**):
```sql
SELECT version, config FROM agent_published_config WHERE tenant_id = $1;
```
Cột tối thiểu:

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `tenant_id` | `text` | id tenant |
| `version` | `integer` | số phiên bản config đã publish (immutable, tăng dần) |
| `config` | `jsonb` | cấu hình identity/scope/tools của tenant |

**Shape của `config` jsonb** (agent parse bằng `agent/agent_config.py::parse_config`,
mọi field có default nên có thể thiếu, nhưng nên đủ):

```json
{
  "identity": {
    "agent_name": "Luna",
    "brand": "NobleX",
    "honorific_self": "em",
    "honorific_customer": "anh/chị",
    "greeting": "Dạ em chào anh/chị, em là Luna ạ."
  },
  "scope": {
    "does": "tư vấn dự án mở bán, đặt lịch tham quan",
    "does_not": "hậu mãi, giá nội bộ",
    "refusal": "",
    "handoff_department": "CVTV"
  },
  "tools": {
    "enabled": ["discover_projects","get_project_overview","get_document",
                "search_units","check_inventory","recommend_units","booking","send_media"],
    "feng_shui": true,
    "media_channel": "noblex_app"
  },
  "data_source": "pg_kb"
}
```

Ràng buộc phía agent khi parse (để Portal biết giá trị hợp lệ):
- **4 tool lõi luôn bật, không cần khai báo:** `update_customer`, `kb_search`,
  `find_project`, `escalate`. `escalate` không được phép tắt.
- **8 tool optional** (chỉ các tên này là hợp lệ, tên lạ bị bỏ qua):
  `discover_projects`, `get_project_overview`, `get_document`, `search_units`,
  `check_inventory`, `recommend_units`, `booking`, `send_media`.
- `feng_shui` chỉ có tác dụng khi `recommend_units` nằm trong `enabled`.
- `data_source` mặc định `pg_kb` (đọc dữ liệu dự án/căn từ `tenant_data.projects/units`).

### 5.5 Quyền (GRANT) cho role runtime

Tất cả quan hệ trên phải cho `odyssey_app` đọc:
```sql
GRANT USAGE  ON SCHEMA agent_api TO odyssey_app;
GRANT SELECT ON ALL TABLES IN SCHEMA agent_api TO odyssey_app;   -- hoặc từng view
GRANT SELECT ON <schema>.agent_published_config TO odyssey_app;
```
Ngoài ra (cho heartbeat, contract C3): cấp **INSERT/UPDATE** cho `odyssey_app` trên
`control.agent_heartbeats`.

### 5.6 Luồng publish

`agent_published_config` phải được sinh ra qua **luồng publish của Portal** (tạo config
draft → publish thành version immutable), không seed tay. Mỗi lần đổi config = publish
version mới; agent tự nhận version mới ở cuộc hội thoại kế tiếp (poll TTL ~20s).

---

## 6. Điểm cần hai team chốt (không phải bug, là mơ hồ contract)

Trong code agent hiện tại:
- Query control-plane **có prefix schema**: `agent_api.tenant_status`, `agent_api.tenant_keys`, `agent_api.deployments`.
- Query config **không có prefix**: `agent_published_config` → phụ thuộc `search_path` của role `odyssey_app`.

→ Cần chốt: **`agent_published_config` đặt ở schema nào?** Hai lựa chọn:
- (a) Đặt ở schema nằm trong `search_path` của `odyssey_app` (mặc định `"$user", public` → tức `public`), hoặc
- (b) Portal set `ALTER ROLE odyssey_app SET search_path = "$user", public, agent_api;` nếu muốn để nó trong `agent_api`.

Đề xuất: thống nhất **đặt cùng `agent_api`** và bổ sung `agent_api` vào `search_path`,
cho nhất quán với 3 view kia. (Nếu chọn cách này, team agent có thể chỉnh query thành
`agent_api.agent_published_config` để hết phụ thuộc search_path — cần một dòng đổi ở
`storage/agent_config_store.py`; báo team agent nếu Portal muốn hướng này.)

---

## 7. Tiêu chí nghiệm thu (acceptance)

Với một tenant test (ví dụ `dufake`) đã publish, các truy vấn sau (chạy như
`odyssey_app`, sau khi `set_config('app.tenant_id','dufake',true)`) phải trả đúng:

```sql
SELECT active FROM agent_api.tenant_status WHERE tenant_id = 'dufake';           -- → true
SELECT key_sha256, active FROM agent_api.tenant_keys WHERE tenant_id = 'dufake'; -- → 1+ row active, hash khớp
SELECT version, config FROM agent_published_config WHERE tenant_id = 'dufake';   -- → version + jsonb hợp lệ
```

Và e2e:
```bash
python scripts/e2e_dbmode/chat_via_gateway.py "Dự án nào đang mở bán ạ?"
```
→ trả về token câu trả lời + `[done]`, không còn `1011` / `no published config`.

---

## 8. Tham chiếu

- Contract gốc: `docs/handoff/agent-postgres-read-contract.md` (Portal read contract)
- Shape config + luồng publish: `docs/handoff/spec.md` §4, §5
- Code agent (ground truth query):
  - `src/noble_agent/storage/agent_control_store.py` (3 query `agent_api.*`)
  - `src/noble_agent/storage/agent_config_store.py` (`agent_published_config`)
  - `src/noble_agent/gateway/pg_registry.py` (cách verify token = sha256 hex)
  - `src/noble_agent/agent/agent_config.py` (`parse_config` — giá trị hợp lệ của `config`)

---

## Phụ lục A — SQL giả lập team Agent đã dùng để tự test (KHÔNG dùng cho prod)

> Chỉ để Portal tham khảo đúng shape. Trên môi trường thật, Portal phải sinh
> `agent_published_config` qua luồng publish, không seed tay như dưới đây.

```sql
-- control-plane auth
CREATE SCHEMA IF NOT EXISTS agent_api;

CREATE TABLE IF NOT EXISTS agent_api.tenant_status (
  tenant_id text PRIMARY KEY,
  active    boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS agent_api.tenant_keys (
  tenant_id  text NOT NULL,
  key_sha256 text NOT NULL,
  active     boolean NOT NULL DEFAULT true,
  PRIMARY KEY (tenant_id, key_sha256)
);
CREATE TABLE IF NOT EXISTS agent_api.deployments (
  id        bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  kind      text NOT NULL
);

INSERT INTO agent_api.tenant_status (tenant_id, active) VALUES ('dufake', true)
  ON CONFLICT (tenant_id) DO UPDATE SET active = EXCLUDED.active;

INSERT INTO agent_api.tenant_keys (tenant_id, key_sha256, active)
VALUES ('dufake', encode(sha256('<api_key_plaintext>'::bytea), 'hex'), true)
  ON CONFLICT (tenant_id, key_sha256) DO UPDATE SET active = EXCLUDED.active;

GRANT USAGE  ON SCHEMA agent_api TO odyssey_app;
GRANT SELECT ON ALL TABLES IN SCHEMA agent_api TO odyssey_app;

-- published config (đặt tạm ở public vì query không có prefix schema — xem mục 6)
CREATE TABLE IF NOT EXISTS public.agent_published_config (
  tenant_id text PRIMARY KEY,
  version   integer NOT NULL DEFAULT 1,
  config    jsonb   NOT NULL
);

INSERT INTO public.agent_published_config (tenant_id, version, config) VALUES (
  'dufake', 1,
  '{"identity":{"agent_name":"Luna","brand":"NobleX","honorific_self":"em","honorific_customer":"anh/chị","greeting":"Dạ em chào anh/chị, em là Luna ạ."},
    "scope":{"does":"tư vấn dự án mở bán, đặt lịch tham quan","does_not":"hậu mãi, giá nội bộ","handoff_department":"CVTV"},
    "tools":{"enabled":["discover_projects","get_project_overview","get_document","search_units","check_inventory","recommend_units","booking","send_media"],"feng_shui":true,"media_channel":"noblex_app"},
    "data_source":"pg_kb"}'::jsonb
)
ON CONFLICT (tenant_id) DO UPDATE SET version = EXCLUDED.version, config = EXCLUDED.config;

GRANT SELECT ON public.agent_published_config TO odyssey_app;
```
