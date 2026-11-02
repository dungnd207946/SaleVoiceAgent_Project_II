# Contract bàn giao: tool `analyze_projects` — SQL read-only trên DB portal (Portal ship)

**Ngày:** 2026-08-26 · **Phía agent:** nhánh `sql-agent` (spec
`docs/superpowers/specs/2026-08-26-analyze-projects-sql-tool-design.md`) ·
**Tiền lệ cùng khuôn:** `agent-postgres-billing-write-contract.md` (billing, 2026-08-18).

## 0. Tính năng & nguyên tắc

Agent có tool mới `analyze_projects`: LLM viết MỘT câu SQL `SELECT` (trong tham số
tool) để trả lời câu hỏi tổng quát/aggregate ("dự án nào nhiều loại hình nhất",
"giá trung bình từng dự án"...). Câu SQL đó là input **không đáng tin**, nên an toàn
được thực thi hoàn toàn bằng Postgres, 3 khoá độc lập:

1. `SET TRANSACTION READ ONLY` — cấm mọi ghi (kể cả DML giấu trong CTE/function);
   Postgres không cho nới lại sau query đầu tiên của transaction.
2. `SET LOCAL ROLE agent_sql_ro` — role **túi quyền dùng chung** (một cái cho mọi
   tenant), `NOLOGIN`, CHỈ có `SELECT` trên đúng 2 VIEW; bảng gốc, `contacts`,
   `conversations`... đều `permission denied`.
3. RLS theo GUC `app.current_tenant` (policy `agent_runtime` sẵn có) — ranh giới
   tenant. Role KHÔNG phải ranh giới tenant; RLS mới là.

Mọi `SET` đều `LOCAL` → transaction kết thúc là connection sạch, trả về pool như cũ.
**Serving path không đổi:** vẫn `POSTGRES_SERVER_DSN` + role/password per-tenant từ
runtime-credentials API; gateway/credentials API **không cần sửa response schema**.

Phân vai (đúng khuôn billing):

- **Agent** sở hữu code tool + viết sẵn toàn bộ DDL/GRANT (dưới đây, trích nguyên
  văn từ `src/noble_agent/storage/sql/kb_real_estate.sql` +
  `src/noble_agent/tenant/pg_provisioning.py::ensure_sql_ro_roles`).
- **Portal** thực thi DDL bằng `portal_migrator` (role duy nhất DDL được trên DB
  `portal`), tích hợp 1 GRANT vào flow provision tenant, và mở tool trong UI config.

## 1. Migration Portal chạy (`portal_migrator`, idempotent — CHẠY LẠI ĐƯỢC)

Chạy trong **đúng database chứa `tenant_data`** (role là object toàn cục của
cluster, nhưng GRANT trên schema/view là per-database). Toàn bộ khối dưới đây gói
được thành MỘT migration; thứ tự trong khối là bắt buộc (role trước, view sau,
rồi owner, rồi grant — `ALTER VIEW ... OWNER` đòi role đã tồn tại).

### 1.1 Migration đầy đủ (copy-paste)

```sql
BEGIN;

-- Bước 1: hai role (guard idempotent — CREATE ROLE không có IF NOT EXISTS).
-- agent_kb_view_owner: owner của 2 view. NOBYPASSRLS là load-bearing: view chạy
-- theo quyền owner (definer semantics), owner bị FORCE RLS siết thì policy
-- agent_runtime (GUC app.current_tenant) vẫn lọc tenant xuyên qua view.
-- agent_sql_ro: túi quyền chạy SQL của LLM. NOLOGIN — không password, không đi
-- qua runtime-credentials; session đã xác thực "mặc tạm" nó bằng SET LOCAL ROLE.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_kb_view_owner') THEN
        CREATE ROLE agent_kb_view_owner NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_sql_ro') THEN
        CREATE ROLE agent_sql_ro NOLOGIN;
    END IF;
END $$;

-- Bước 2: quyền nền cho owner (phải có TRƯỚC khi nó làm chủ view).
GRANT USAGE ON SCHEMA tenant_data TO agent_kb_view_owner, agent_sql_ro;
GRANT SELECT ON tenant_data.projects, tenant_data.units TO agent_kb_view_owner;

-- Bước 3: hai view (CREATE OR REPLACE — chạy lại không mất owner/grant).
-- Filter status='published' ở CẢ units LẪN project cha là khoá an toàn, xem §4.
-- Cột sau dòng `-- 0978` thêm ở migration 0978_realestate_data (chỉ nối vào cuối).
CREATE OR REPLACE VIEW tenant_data.agent_projects_v AS
SELECT project_code, name, region, address, investor, developer,
       category, sale_phase, ownership_form, total_land_area_m2,
       -- 0978
       total_units, num_buildings, management_fee_vnd_m2, parking_car_fee_vnd, parking_moto_fee_vnd
FROM tenant_data.projects
WHERE status = 'published';

CREATE OR REPLACE VIEW tenant_data.agent_units_v AS
SELECT u.project_code, p.name AS project_name, u.zone_code, u.unit_code,
       u.product_type, u.bedrooms, u.block, u.floor, u.direction,
       u.area_built_m2, u.area_land_m2, u.price_vnd, u.price_per_m2_vnd,
       u.sale_status,
       -- 0978: views text[] (song, ho, bien, cong_vien, san_golf, noi_khu, be_boi, duong, thanh_pho,
       -- toa_doi_dien); hr_* chỉ cao tầng, lr_* chỉ thấp tầng
       u.views, u.is_corner, u.open_sides, u.bathrooms, u.handover_condition,
       u.hr_balcony_m2, u.hr_loggia_m2, u.lr_frontage_m, u.lr_depth_m, u.lr_road_width_m
FROM tenant_data.units u
JOIN tenant_data.projects p USING (tenant_id, project_code)
WHERE u.status = 'published' AND p.status = 'published';

-- Bước 4: gán owner + quyền đọc view (idempotent, chạy lại vô hại).
ALTER VIEW tenant_data.agent_projects_v OWNER TO agent_kb_view_owner;
ALTER VIEW tenant_data.agent_units_v    OWNER TO agent_kb_view_owner;
GRANT SELECT ON tenant_data.agent_projects_v, tenant_data.agent_units_v TO agent_sql_ro;

COMMIT;
```

### 1.2 Backfill membership cho role runtime ĐÃ tồn tại (một lần)

Role nào được `SET LOCAL ROLE agent_sql_ro` = role đó phải là member. Backfill
cho các tenant hiện hữu — **điều chỉnh mệnh đề WHERE theo naming convention role
runtime của Portal** (ví dụ dưới giả định `agent_<tenant_id>`), hoặc thay bằng
loop trên bảng control nội bộ của Portal (nguồn sự thật danh sách role):

```sql
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT rolname FROM pg_roles WHERE rolname LIKE 'agent\_%' AND rolcanlogin
    LOOP
        EXECUTE format('GRANT agent_sql_ro TO %I', r.rolname);
    END LOOP;
END $$;

-- Role app dùng chung/fallback nếu deployment có (vd portal_api / odyssey_agent):
GRANT agent_sql_ro TO portal_api;
```

`GRANT` membership chạy lại chỉ báo NOTICE "already a member" — vô hại, nên khối
này an toàn để nằm luôn trong migration idempotent.

### 1.3 Tái tạo / tiến hoá view về sau — hai bẫy phải biết

- **`CREATE OR REPLACE VIEW` giữ nguyên owner + grant**, nhưng chỉ cho phép
  THÊM cột vào CUỐI danh sách. Muốn bớt/đổi kiểu/đổi thứ tự cột thì phải
  `DROP VIEW` + `CREATE` — lúc đó **owner và grant mất theo view**, bắt buộc chạy
  lại Bước 4 (§1.1). Vì vậy hãy giữ cả khối §1.1 như một migration chạy-lại-được
  thay vì coi nó là one-shot.
- **View là ALLOWLIST cột**: Portal thêm cột mới vào `tenant_data.projects`/`units`
  thì cột đó KHÔNG tự lộ ra tool — muốn expose phải sửa view (thêm vào cuối danh
  sách SELECT) **và báo team agent** cập nhật schema description của tool (LLM chỉ
  biết cột qua description, không introspect DB). Đây là thay đổi phối hợp 2 bên,
  đừng ship lẻ một phía.

(Nếu muốn dùng CLI phía agent thay cho SQL tay — cùng nội dung, cùng idempotent:
`noble-tenant pg-apply-schema --admin-dsn ...` tạo view, rồi
`noble-tenant pg-ensure-sql-ro --admin-dsn ...` tạo role + grant + backfill.)

## 2. Thay đổi VĨNH VIỄN trong flow provision tenant của Portal

Khi Portal mint role PG cho tenant mới (role mà runtime-credentials API sẽ trả về),
**thêm một lệnh**:

```sql
-- Guard theo catalog để không phụ thuộc thứ tự deploy (agent_sql_ro chưa được
-- tạo thì bỏ qua êm — lệnh `pg-ensure-sql-ro`/DDL §1 chạy sau sẽ tự quét
-- pg_roles và grant bù cho mọi role tenant đang tồn tại):
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_sql_ro') THEN
        EXECUTE format('GRANT agent_sql_ro TO %I', '<role vừa tạo>');
    END IF;
END $$;
```

Hai bên "biết nhau" qua đúng MỘT thứ: cái tên `agent_sql_ro` ghi trong contract này
(role là object toàn cục của cluster, cùng một catalog cho cả hai bên) — không có
API call nào giữa agent và Portal cho việc nối quyền; guard `pg_roles` ở cả hai
phía làm mối nối độc lập thứ tự deploy.

Thiếu grant này thì tenant mới gọi tool sẽ nhận `permission denied to set role`
→ agent degrade "nguồn thống kê tạm không khả dụng" (không vỡ cuộc gọi, nhưng
tính năng chết với riêng tenant đó). Phía agent, đường provision dev
(`noble-tenant pg-provision`) đã tự grant tương tự.

## 3. Mở tool trong Portal UI/API config

`analyze_projects` là tool **optional thứ 9** (không thuộc core). Bật per-tenant =
thêm chuỗi `"analyze_projects"` vào mảng `skills` (jsonb) của row
`tenant_data.agent_config` rồi publish như mọi thay đổi config khác (bump
`version` để worker build runner mới). Agent đọc qua view
`tenant_data.agent_published_config`, đối chiếu whitelist `OPTIONAL_TOOLS`
(`src/noble_agent/agent/agent_config.py`) — giá trị lạ bị bỏ qua im lặng.

Việc của Portal: thêm `analyze_projects` vào catalog tool trong UI editor
(label gợi ý: "Thống kê / so sánh dự án").

## 4. Bất biến KHÔNG được đổi (đổi là thủng khoá)

| Bất biến | Vì sao |
|---|---|
| View giữ nguyên filter `status='published'` (cả units LẪN project cha) | Khoá chống lộ draft/archived — LLM không tự lọc được |
| View KHÔNG thêm cột `tenant_id`, text dài (`overview`, `body`...) | Chống lộ nội bộ + chống `SELECT *` nổ context |
| KHÔNG set `security_invoker = true` trên 2 view | Invoker semantics bắt role truy vấn có SELECT trên bảng gốc → phá cô lập |
| `agent_kb_view_owner` giữ `NOBYPASSRLS`, không owner bảng gốc | Owner bypass RLS là mất ranh giới tenant xuyên view |
| `agent_sql_ro` giữ `NOLOGIN`, CHỈ `SELECT` trên 2 view, KHÔNG grant gì thêm | Túi quyền tối thiểu; thêm bảng nào là LLM đọc được bảng đó |
| Tên 2 role không trùng bất kỳ `tenant_id` nào | Policy `tenant_isolation` khớp `current_user` — trùng tên là khớp nhầm |
| Thêm cột vào `projects`/`units` KHÔNG tự lộ ra tool | View là allowlist cột; muốn expose thì sửa view + báo agent cập nhật schema description |

## 5. Checklist verify (chạy sau khi áp DDL)

```sql
-- 1) Membership đủ chưa (mỗi tenant role):
SELECT pg_has_role('agent_<tenant>', 'agent_sql_ro', 'member');   -- t

-- 2) Khoá hoạt động (login bằng role runtime của một tenant):
BEGIN;
SELECT set_config('app.current_tenant', '<tenant>', true);
SET LOCAL ROLE agent_sql_ro;
SET TRANSACTION READ ONLY;
SELECT count(*) FROM tenant_data.agent_units_v;                    -- OK, chỉ published
SELECT * FROM tenant_data.contacts LIMIT 1;                        -- permission denied
WITH x AS (DELETE FROM tenant_data.units RETURNING *) SELECT 1;    -- read-only error
ROLLBACK;
```

Bộ probe đầy đủ 6 khoá nằm ở `tests/integration/tenant/test_analyze_sql_live.py`
(chạy với `SPE_PG_ADMIN_DSN` trỏ DB **test** — đã pass trên Postgres 16).

## 6. FYI — nút vặn phía agent (env, không cần Portal đụng)

| Env | Default | Ý nghĩa |
|---|---|---|
| `ANALYZE_SQL_ROLE` | `agent_sql_ro` | Tên role SET LOCAL (đổi tên role thì đổi env này theo) |
| `ANALYZE_SQL_TIMEOUT_MS` | `2000` | `statement_timeout` mỗi query |
| `ANALYZE_SQL_MAX_ROWS` | `50` | Trần số dòng trả về + LIMIT auto-chèn |
| `ANALYZE_VOCAB_TTL_SEC` | `600` | TTL cache vocab giá trị cột (chèn vào tool description) |

## 7. Rollback

Tắt tính năng = gỡ `"analyze_projects"` khỏi `skills` của tenant (publish lại) —
tool biến mất khỏi catalog ngay phiên mới, không cần đụng DB objects. Gỡ hẳn:
`DROP VIEW tenant_data.agent_units_v, tenant_data.agent_projects_v;
DROP ROLE agent_sql_ro; DROP ROLE agent_kb_view_owner;` (không mất dữ liệu —
toàn bộ là object phái sinh).