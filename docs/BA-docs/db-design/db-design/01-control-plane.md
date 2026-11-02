# 01 · Control plane — schema `control` (PostgreSQL)

> Nhóm **A**. Các bảng **metadata quản trị** trong schema `control` của **cùng một Postgres cluster** với `tenant_data`. Trả lời "**có gì ở đâu, ai vào đâu, bản cấu hình nào LIVE**" — KHÔNG chứa dữ liệu nghiệp vụ (nghiệp vụ ở bảng `tenant_data`, xem 02–07).
>
> Chú thích Δ: `🆕` mới vs plan gốc · `✏️` đổi vs plan gốc · `📎` khớp Notion · `⚠️` cố ý khác Notion.
> Quy ước: PK = `id BIGINT GENERATED ALWAYS AS IDENTITY` (hoặc `uuid`); mọi bảng có `created_at`/`updated_at timestamptz`. Bảng nào **có `tenant_id`** thì **bật RLS** (tenant chỉ thấy của mình; org-admin thấy subtree).

## 8 bảng

### 1. `organizations` `🆕` `📎`(0.3)

*Node cha (tập đoàn/đại lý) — sở hữu N workspace. Hoá đơn để ở đây, KHÔNG gắn vào `tenants`. (Tên `organizations` thay `accounts` để khỏi nhầm với "tài khoản đăng nhập" — đăng nhập là `users`.)*

| Field                         | Kiểu                         | Ý nghĩa                                            | Ví dụ                  |
| ----------------------------- | ----------------------------- | ---------------------------------------------------- | ------------------------ |
| `id`                        | PK                            | Khóa chính organization                            | `1`                    |
| `name`                      | text                          | Tên tổ chức/tập đoàn                           | `"Tập đoàn Noble"`  |
| `status`                    | text`active`\|`suspended` | Trạng thái                                         | `"active"`             |
| `billing`                   | jsonb?                        | Chỗ dành sẵn cho hoá đơn (thêm sau, additive) | `null`                 |
| `created_at`/`updated_at` | timestamptz                   | Mốc tạo/cập nhật                                 | `2026-07-29T08:00:00Z` |

Index: `status`. RLS: không (platform/org-admin quản qua app RBAC).

### 2. `tenants` (= workspace) `✔`Phase1 → `✏️`

*Một workspace = một khách trả tiền = một agent. `id` là **khoá cách ly** — mọi bảng `tenant_data` mang `tenant_id` trỏ về đây.*

| Field                         | Kiểu                                           | Ý nghĩa                                         | Ví dụ                  |
| ----------------------------- | ----------------------------------------------- | ------------------------------------------------- | ------------------------ |
| `id`                        | PK                                              | **tenant_id** — khoá RLS xuyên toàn hệ | `12`                   |
| `slug`                      | text UNIQUE                                     | Định danh URL-safe; sinh tên tài nguyên      | `"acme"`               |
| `name`                      | text                                            | Tên hiển thị                                   | `"ACME Land"`          |
| `status`                    | text`active`\|`suspended`\|`provisioning` | Trạng thái                                      | `"active"`             |
| `org_id`                    | FK → organizations                             | Thuộc tổ chức cha (2 tầng)                    | `1`                    |
| `qdrant_documents_coll`     | text                                            | Collection tri thức văn bản (`<slug>_documents`, dense) | `"acme_documents"`     |
| `qdrant_media_coll`         | text                                            | Collection media (`<slug>_media`, hybrid text+visual)   | `"acme_media"`         |
| `s3_prefix`                 | text                                            | Prefix S3 (`<slug>/`)                           | `"acme/"`              |
| `created_at`/`updated_at` | timestamptz                                     | Mốc tạo/cập nhật                              | `2026-07-29T08:00:00Z` |

Index: `slug` UNIQUE · `org_id` · `status`.
`✏️` **Bỏ `mongo_db`** (không còn DB-per-tenant — dữ liệu là bảng chung RLS). **2 collection Qdrant/workspace** `<slug>_documents` (dense) + `<slug>_media` (hybrid — CÓ semantic, xem `02` §8). `📎` **Không có cột `plan`** (hoá đơn ở `organizations`).

### 3. `tenant_verticals` `🆕` `📎`(0.3)

*Đa lĩnh vực = nhiều hàng trên 1 tenant, không cần nhiều workspace.*

| Field          | Kiểu                   | Ý nghĩa                     | Ví dụ                  |
| -------------- | ----------------------- | ----------------------------- | ------------------------ |
| `id`         | PK                      | Khóa chính                  | `5`                    |
| `tenant_id`  | FK → tenants           | Thuộc tenant nào            | `12`                   |
| `vertical`   | text`real_estate`\|… | Lĩnh vực (MVP: real_estate) | `"real_estate"`        |
| `enabled`    | bool                    | Bật/tắt lĩnh vực          | `true`                 |
| `created_at` | timestamptz             | Mốc tạo                     | `2026-07-29T08:00:00Z` |

Constraint: `UNIQUE(tenant_id, vertical)`. RLS theo `tenant_id`.

> Lĩnh vực đang bật **quyết định template** (bộ bảng + cột do code khai — vd `real_estate` → `02a`) + khối hướng dẫn agent theo lĩnh vực `📎`(AG_01 BR04).

### 4. `memberships` `🆕` `📎`(0.2 §5.1)

*Ai — vai trò gì — ở phạm vi nào. 1 user NHIỀU hàng → nền cho switcher + org-admin (2 tầng).*

| Field                         | Kiểu                                    | Ý nghĩa                                | Ví dụ                  |
| ----------------------------- | ---------------------------------------- | ---------------------------------------- | ------------------------ |
| `id`                        | PK                                       | Khóa chính                             | `7`                    |
| `user_id`                   | FK → users                              | Người dùng nào                       | `3`                    |
| `scope_type`                | text`platform`\|`org`\|`workspace` | Cấp phạm vi                            | `"workspace"`          |
| `scope_id`                  | bigint?                                  | org_id / tenant_id;`NULL` khi platform | `12`                   |
| `role`                      | text (4 vai trò, tên N4)               | Tenant Admin·CSKH·Data Editor·Viewer  | `"tenant_admin"`       |
| `created_at`/`updated_at` | timestamptz                              | Mốc tạo/cập nhật                     | `2026-07-29T08:00:00Z` |

Constraint: `UNIQUE(user_id, scope_type, scope_id)`. Index: `(scope_type, scope_id)` (liệt kê thành viên).
`✏️` **Thay `users.tenant_id` của Phase 2** — tenant_id cũ = 1 membership scope=workspace. Đổi quyền có hiệu lực **phiên đăng nhập kế** `📎`.

### 5. `users` `✔`Phase2 → `✏️`

*Danh tính toàn cục. Scope + role đã chuyển sang `memberships`.*

| Field                         | Kiểu                    | Ý nghĩa                    | Ví dụ                  |
| ----------------------------- | ------------------------ | ---------------------------- | ------------------------ |
| `id`                        | PK                       | Khóa chính                 | `3`                    |
| `username`                  | text UNIQUE (toàn cục) | Tên đăng nhập            | `"an.nguyen"`          |
| `full_name`                 | text                     | Họ tên                     | `"An Nguyễn"`         |
| `password_hash`             | text                     | Bcrypt hash                  | `"$2b$12$…"`          |
| `is_active`                 | bool                     | Còn hoạt động            | `true`                 |
| `last_login_at`             | timestamptz?             | Lần đăng nhập gần nhất | `2026-07-29T07:55:00Z` |
| `created_at`/`updated_at` | timestamptz              | Mốc tạo/cập nhật         | `2026-07-01T00:00:00Z` |

`✏️` **Bỏ `tenant_id`** (→ memberships). `is_platform_admin` = có membership scope=platform.

### 6. `field_definitions` `✔`Phase1 → `✏️`

*Schema **custom field** cho vertical CÓ dùng custom field (data ở JSONB `custom_fields`). `⚠️` **real_estate (MVP) KHÔNG dùng** — mọi field là **cột thật** do template khai (xem `02a`). Bảng này **dành cho vertical tương lai** cần thêm field lúc chạy (không qua migration). Dùng để FE render form + validate + cấp options enum. KHÔNG có cờ per-field.*

| Field                         | Kiểu                                                                          | Ý nghĩa                                                                          | Ví dụ                  |
| ----------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------ |
| `id`                        | PK                                                                             | Khóa chính                                                                       | `21`                   |
| `tenant_id`                 | FK → tenants                                                                  | Custom field thuộc tenant nào                                                    | `12`                   |
| `table_name`                | text`contacts`\|`projects`\|`units`\|`conversations`\|`appointments` | Bảng field này áp vào (đóng vai**namespace** cho `key`)              | `"units"`              |
| `key`                       | text                                                                           | Tên field trong`custom_fields` (JSONB) của bảng đó                          | `"khoang_cach_bien_km"`|
| `label`                     | text                                                                           | Nhãn hiển thị trên form                                                        | `"Khoảng cách tới biển (km)"` |
| `type`                      | text string\|number\|date\|bool\|enum\|phone\|email\|text                      | Kiểu dữ liệu (render input + validate)                                          | `"number"`             |
| `options`                   | text[]?                                                                        | Giá trị hợp lệ khi`type=enum`                                              | `["Hiện đại","Tân cổ điển"]` |
| `required`                  | bool                                                                           | Có bắt buộc nhập không                                                        | `false`                |
| `created_at`/`updated_at` | timestamptz                                                                    | Mốc tạo/cập nhật                                                               | `2026-07-29T08:00:00Z` |

Constraint: `UNIQUE(tenant_id, table_name, key)` — `key` định danh **theo từng bảng**; mỗi field nằm trong `custom_fields` (JSONB) của đúng bảng đó. RLS theo `tenant_id`.
`✏️` **Bỏ `in_rag`/`searchable`/`order`/mọi cờ** — chỉ mô tả *field tồn tại + kiểu + options*.
`⚠️` **Bỏ gate đọc** (khác DL_01 BR09): KB chỉ chứa dữ liệu hướng khách; trường nội bộ nhạy cảm KHÔNG lưu trong KB.

> **real_estate:** mọi field là **cột thật** (`02a`); `field_definitions`/`custom_fields` **không tham gia**. Agent lọc trên bộ field CORE (cột thật, index) — không cấu hình per-field.

### 7. `config_versions` `🆕` `📎`(HT_01 YC02/BR06)

*Bản cấu hình agent **bất biến, đánh số**, publish → agent poll. Nội dung bundle ở `07-agent-config.md`.*

| Field            | Kiểu                                        | Ý nghĩa                                               | Ví dụ                    |
| ---------------- | -------------------------------------------- | ------------------------------------------------------- | -------------------------- |
| `id`           | PK                                           | Khóa chính                                            | `88`                     |
| `tenant_id`    | FK → tenants                                | Của workspace nào                                     | `12`                     |
| `version`      | int                                          | Số phiên bản tăng dần, không ghi đè             | `12`                     |
| `status`       | text`draft`\|`published`\|`superseded` | Trạng thái bản                                       | `"published"`            |
| `bundle_ref`   | text (S3 key)                                | Prompt đã render (workspace không thấy prompt thô) | `"acme/config/v12.json"` |
| `is_live`      | bool                                         | Bản agent đang chạy (con trỏ LIVE)                  | `true`                   |
| `published_at` | timestamptz?                                 | Thời điểm publish                                    | `2026-07-29T09:00:00Z`   |
| `published_by` | FK → users?                                 | Ai publish                                              | `3`                      |
| `created_at`   | timestamptz                                  | Mốc tạo                                               | `2026-07-29T08:59:00Z`   |

Constraint: `UNIQUE(tenant_id, version)`. Index: `(tenant_id, is_live)`. RLS theo `tenant_id`.
Bất biến: không ghi đè; **quay lui = trỏ `is_live` về bản cũ**, không tạo bản mới.

### 8. `audit_log` `✔`Phase2 → `✏️`

*Nhật ký thao tác. Giữ 365 ngày.*

| Field                         | Kiểu          | Ý nghĩa                                              | Ví dụ                     |
| ----------------------------- | -------------- | ------------------------------------------------------ | --------------------------- |
| `id`                        | PK             | Khóa chính                                           | `9001`                    |
| `tenant_id`                 | FK → tenants? | Lọc audit theo tenant                                 | `12`                      |
| `actor_user_id`             | FK → users    | Ai thực hiện                                         | `3`                       |
| `action`                    | text           | Loại hành động                                     | `"unit.update"`           |
| `target_type`/`target_id` | text           | Đối tượng bị tác động                          | `"unit"` / `"NT2-29"`   |
| `before`/`after`          | jsonb?         | Ảnh trước/sau                                       | `{"price":5000000000}`    |
| `diff`                      | jsonb?         | **Thay đổi cấp field** (field từ gì → gì) | `{"price":[5.0e9,4.8e9]}` |
| `ip`/`user_agent`         | text?          | Ngữ cảnh request                                     | `"10.50.13.220"`          |
| `created_at`                | timestamptz    | Thời điểm                                           | `2026-07-29T09:10:00Z`    |

Index: `(tenant_id, created_at DESC)` · `(actor_user_id, created_at)` · `(target_id, created_at)`. RLS theo `tenant_id`.
`🆕📎`(DL_01 BR13) `diff` cấp field. `⚠️` Postgres không có TTL native → giữ 365 ngày bằng **partition theo tháng (drop partition cũ)** hoặc job `pg_cron` xoá `created_at < now()-365d`.

## Quan hệ

```
organizations 1───N tenants 1───N tenant_verticals
                      │  └───N field_definitions · config_versions · audit_log (đều RLS theo tenant_id)
users 1───N memberships ──▶ scope (platform | org | workspace)
```

## Provisioning / teardown `📎`(HT_01 BR12, NĐ13)

- **Tạo workspace** = insert `tenants` + tạo **Qdrant collection** + **S3 prefix**. **KHÔNG cần tạo DB/schema** (dữ liệu là bảng chung RLS) → provision nhẹ hơn hẳn Mongo. Cả-hoặc-không.
- **Xoá workspace** = `DELETE FROM tenants WHERE id=…` (FK `ON DELETE CASCADE` quét sạch tenant_data) + drop Qdrant coll + xoá S3 prefix.
- Tạo workspace là hành động **platform-privileged** `📎`(0.3).
- `⚠️` Phase 1 `provision_tenant` (Mongo) sẽ viết lại: bỏ tạo Mongo DB; thêm tạo Qdrant + S3; RLS lo phần dữ liệu.

## Δ tổng hợp domain A

- `✏️` Toàn bộ chuyển sang **bảng Postgres schema `control`** (thay Mongo `cms_control`); PK/FK/UNIQUE/RLS thật.
- `🆕` `organizations` (đổi tên từ `accounts`), `tenant_verticals`, `memberships`, `config_versions`.
- `✏️` `tenants` +`org_id`, −`mongo_db`, −`qdrant_media_coll`, không `plan`.
- `✏️` `users` −`tenant_id` (→ memberships).
- `✏️` `field_definitions` tối giản (bỏ flags/order/in_rag/searchable); bỏ read-gate.
- `✏️` `audit_log` +diff cấp field; TTL bằng partition/pg_cron.
- `❌` Bỏ `sources` khỏi MVP.

## Quyết định còn mở (liên quan A)

- Tên 4 vai trò (N4) + vai trò nào đọc bản ghi thoại.
- Đổi tên `memberships` → `role_assignments`/`access_grants`? (mặc định giữ).
- PK kiểu `bigint identity` hay `uuid` (mặc định bigint; uuid nếu cần id public không đoán).
- Migrate Phase 2 (Mongo `users.tenant_id`) → Postgres `memberships` khi triển khai.
