# Design: tool `analyze_projects` — SQL analytics trên VIEW (read-only tuyệt đối)

**Ngày:** 2026-08-26 · **Nhánh:** feat/share-agent · **Trạng thái:** approved-design, chưa implement

## 1. Vấn đề

Luna trả lời tốt câu hỏi *specific* (một dự án, một căn) nhưng rối với câu hỏi
*tổng quát/aggregate* — ví dụ "dự án nào có nhiều loại hình nhất", "giá trung bình
mỗi dự án ở Long Biên", "khu nào còn nhiều căn 2PN nhất". Nguyên nhân: toàn bộ tool
hiện tại là point-lookup có filter (`discover_projects`, `search_units`,
`get_inventory_summary` theo TỪNG dự án). Một câu aggregate cần `GROUP BY` trên toàn
bộ `units`; muốn ghép từ tool hiện có phải gọi inventory × 15 dự án — vượt
`MAX_TOOL_ITERATIONS=5` và tốn ~1.3s/vòng.

## 2. Giải pháp đã chọn

Một tool mới **`analyze_projects(sql)`**: LLM chính viết câu SQL SELECT ngay trong
tham số tool (không tốn thêm lượt gọi LLM), chạy trên **2 VIEW được phép** dưới
**role riêng chỉ-đọc** trong **transaction READ ONLY**. An toàn thực thi bởi
Postgres server (GRANT + read-only txn + RLS), **không** dựa vào parse/regex câu SQL.

Các hướng đã loại:
- *Tool aggregate tham số hoá* — an toàn nhưng chính là cách tiếp cận hiện tại,
  long tail câu tổng quát lại vượt khỏi tham số định nghĩa sẵn.
- *Snapshot per-tenant + SQLite/DuckDB in-process* — an toàn tuyệt đối với PG nhưng
  sinh bản dữ liệu thứ hai cần invalidation (gotcha staleness kiểu cache 300s của
  `send_media`), thêm dialect lệch Postgres.

## 3. Lớp DB — 3 khoá độc lập

Nguyên tắc: SQL do LLM sinh là input không đáng tin. Validator ứng dụng chỉ để trả
lỗi thân thiện; **hàng rào an toàn nằm hết ở tầng Postgres**, ba lớp độc lập.

### 3.1 Hai VIEW (thêm vào `storage/sql/kb_real_estate.sql`, idempotent)

```sql
CREATE OR REPLACE VIEW tenant_data.agent_projects_v AS
SELECT project_code, name, region, address, investor, developer,
       category, sale_phase, ownership_form, total_land_area_m2
FROM tenant_data.projects
WHERE status = 'published';

CREATE OR REPLACE VIEW tenant_data.agent_units_v AS
SELECT u.project_code, p.name AS project_name, u.zone_code, u.unit_code,
       u.product_type, u.bedrooms, u.block, u.floor, u.direction,
       u.area_built_m2, u.area_land_m2, u.price_vnd, u.price_per_m2_vnd,
       u.sale_status
FROM tenant_data.units u
JOIN tenant_data.projects p USING (tenant_id, project_code)
WHERE u.status = 'published' AND p.status = 'published';
```

- Lọc sẵn `status='published'` (cả units lẫn project cha — đúng class bug
  `get_document` đã vá 2026-08-25). LLM không thể quên filter vì filter không nằm
  trong tay nó.
- KHÔNG expose: `tenant_id`, `status`, `created_at`, media id, và cố ý bỏ
  `projects.overview` (text dài — đã có `get_project_overview`; bỏ khỏi view thì
  `SELECT *` không thể vô tình nổ context).
- View để **mặc định (definer semantics)**, KHÔNG `security_invoker=true` — invoker
  semantics bắt role truy vấn có SELECT trên bảng gốc, phá mục đích cô lập.

### 3.2 Hai ROLE (provisioning `tenant/pg_provisioning.py`, CLI `noble-tenant pg-ensure-sql-ro`)

```sql
-- Chủ sở hữu view: có SELECT bảng gốc nhưng FORCE RLS vẫn siết nó.
CREATE ROLE agent_kb_view_owner NOLOGIN NOBYPASSRLS;
GRANT USAGE ON SCHEMA tenant_data TO agent_kb_view_owner;
GRANT SELECT ON tenant_data.projects, tenant_data.units TO agent_kb_view_owner;
ALTER VIEW tenant_data.agent_projects_v OWNER TO agent_kb_view_owner;
ALTER VIEW tenant_data.agent_units_v    OWNER TO agent_kb_view_owner;

-- Role thực thi SQL của LLM: CHỈ SELECT trên đúng 2 view.
CREATE ROLE agent_sql_ro NOLOGIN;
GRANT USAGE ON SCHEMA tenant_data TO agent_sql_ro;
GRANT SELECT ON tenant_data.agent_projects_v, tenant_data.agent_units_v TO agent_sql_ro;
GRANT agent_sql_ro TO odyssey_agent;   -- để SET LOCAL ROLE được
```

- Provisioning idempotent (`DO $$ ... IF NOT EXISTS`), chạy bằng
  `POSTGRES_ADMIN_DSN`, ngoài đường nóng — cùng pattern `ensure_app_role`.
- Tên 2 role đi qua guard kiểu `assert_app_role_distinct` (không trùng tenant_id
  nào — tránh khớp nhầm policy `tenant_isolation` theo `current_user`).

### 3.3 Thực thi mỗi lượt gọi tool

```
BEGIN;                                                      -- tenant_conn (như mọi tool)
  SELECT set_config('app.current_tenant', $tenant, true);
  SELECT set_config('app.tenant_id',      $tenant, true);
  SET LOCAL ROLE agent_sql_ro;                              -- khoá 2: tước quyền
  SET TRANSACTION READ ONLY;                                -- khoá 1: cấm ghi
  SET LOCAL statement_timeout = '2000ms';                   -- chống DoS/treo
  <SQL của LLM>;                                            -- asyncpg fetch (1 statement)
COMMIT;                                                     -- SET LOCAL tự reset, pool sạch
```

Bảng số phận tấn công (mọi lỗi trả về LLM trong tool result → model tự sửa):

| SQL của LLM | Chặn bởi | Lỗi |
|---|---|---|
| `UPDATE/INSERT/DELETE/TRUNCATE/DDL` (kể cả giấu trong CTE `WITH x AS (DELETE …)` hay function) | READ ONLY txn **và** không GRANT | `cannot execute ... in a read-only transaction` |
| `SET TRANSACTION READ WRITE` / `set_config('transaction_read_only','off',…)` | Postgres cấm NỚI read-only sau query đầu tiên (set_config tenant đã chạy trước) | error |
| `SELECT * FROM tenant_data.contacts` / `conversations` (PII nội-tenant) | GRANT (khoá 2) | `permission denied` |
| `SELECT * FROM tenant_data.units` (bảng gốc, có draft) | GRANT (khoá 2) | `permission denied` |
| Dữ liệu tenant khác | RLS `agent_runtime` theo GUC (khoá 3) | 0 dòng |
| `pg_sleep` / cross join khổng lồ | `statement_timeout` | `canceling statement due to statement timeout` |
| Nhiều statement trong một chuỗi | asyncpg extended protocol | `cannot insert multiple commands into a prepared statement` |

## 4. Lớp tool

- **File mới** `agent/tools/analytics.py`: executor async
  `analyze_projects(args, *, provider, tenant, **_) -> str`, nhận `args["sql"]`.
- **Đăng ký** `ToolSpec` trong `agent/tools/builtins.py`:
  `read_only=True`, `dirties_customer=False`.
- **Offer**: thêm `"analyze_projects"` vào `OPTIONAL_TOOLS`
  (`agent/agent_config.py`) — bật per-tenant qua Portal; legacy = thêm vào
  `tenants/<id>/manifest.toml` của tenant muốn dùng. KHÔNG vào `CORE_TOOLS`.
- **Guardrail mức app** (defense-in-depth + lỗi đẹp, KHÔNG phải hàng rào an toàn):
  - đúng 1 statement, phải bắt đầu `SELECT` hoặc `WITH` (strip comment/space);
  - tự chèn `LIMIT 50` nếu câu SQL thiếu LIMIT;
  - serializer kết quả: cap 50 dòng, truncate mỗi cell ~200 ký tự, render bảng
    text gọn (header + rows) — tool result chỉ cho LLM đọc, không render ra khách.
- **Lỗi SQL** → tool result = nguyên văn error Postgres + một dòng
  "Cột hợp lệ: agent_projects_v(...), agent_units_v(...)". Runner sẵn có guard
  chống gọi lại trùng tham số + vòng chốt `tools=[]` nên không lặp vô hạn.
- **0 dòng ≠ lỗi, ≠ cớ escalate**: tool result ghi rõ
  "0 dòng — thử nới điều kiện lọc rồi truy vấn lại" (đồng bộ RULES 2026-08-24).
- **Infra lỗi** (PG chưa cấu hình, role chưa provision, timeout kết nối): trả
  chuỗi "nguồn thống kê tạm không khả dụng — trả lời bằng tool khác hoặc đề nghị
  gửi thông tin sau"; KHÔNG raise, KHÔNG `ESCALATE_SIGNAL`.

### Settings mới (`config.py`)

| Env | Default | Ý nghĩa |
|---|---|---|
| `ANALYZE_SQL_ROLE` | `agent_sql_ro` | Role SET LOCAL khi chạy SQL của LLM |
| `ANALYZE_SQL_TIMEOUT_MS` | `2000` | `statement_timeout` per-query |
| `ANALYZE_SQL_MAX_ROWS` | `50` | Cap dòng trả về (và LIMIT auto-chèn) |

(Tên role view-owner chỉ dùng lúc provisioning — hằng số trong
`pg_provisioning.py`, không cần env.)

## 5. Description sinh per-tenant — LLM biết schema bằng cách nào

Description của tool (nằm trong `schemas.py` — bài học 2026-08-24: model nghe
schema hơn RULES) gồm 4 phần:

1. **Mini-DDL 2 view** (tĩnh): tên view + danh sách cột như §3.1.
2. **Quy ước nghiệp vụ** (tĩnh): `price_vnd` 0/NULL = CHƯA CÓ GIÁ (lọc/AVG phải
   `FILTER (WHERE price_vnd > 0)`); `category` là `text[]` → dùng `'x' = ANY(category)`;
   đơn vị VND; dialect PostgreSQL.
3. **2–3 ví dụ NL→SQL** (tĩnh), tối thiểu:
   - "dự án nào nhiều loại hình nhất" →
     `SELECT project_code, project_name, COUNT(DISTINCT product_type) c FROM tenant_data.agent_units_v GROUP BY 1,2 ORDER BY c DESC LIMIT 3`
   - "giá trung bình mỗi dự án ở <khu vực>" → mẫu có
     `AVG(price_vnd) FILTER (WHERE price_vnd > 0)` + `region ILIKE`.
4. **Khối vocab giá trị thật** (động, per-tenant): `SELECT DISTINCT` các cột
   categorical — units: `product_type, direction, sale_status`; projects:
   `region, sale_phase, investor` + unnest `category`. Chống lỗi chết người của
   text-to-SQL: `WHERE product_type='chung cư'` trong khi DB lưu `'căn hộ'`
   → 0 dòng trông y hệt "không có dữ liệu".

**Cơ chế build vocab** (module mới `agent/tools/analytics_vocab.py`):
- Query DISTINCT chạy **qua chính `agent_sql_ro` + view** (ăn luôn filter
  published + RLS, không thêm bề mặt đọc mới).
- Chạy ở **bootstrap async của orchestrator** — cùng chỗ rebuild
  `ProjectNameIndex` per-tenant (`orchestrator.py` quanh `_build_project_index`,
  fix 2026-08-25), chỉ khi tenant có bật tool này. Kết quả stash vào cache
  in-process keyed theo tenant, TTL 10 phút.
- `build_schemas` (sync, đã deep-copy per-call) đọc cache: có vocab → chèn khối
  §5.4 vào description; chưa có → ship description không kèm vocab (**degrade
  mềm**, không chặn turn, không I/O trong build_schemas).
- Mỗi giá trị vocab cap độ dài; mỗi cột cap ~30 giá trị (quá thì cắt + ghi "…").

Chi phí ước tính ~400–600 token, chỉ trả khi tenant bật tool.

### Ranh giới chọn tool (ghi trong description, cả hai phía)

- `analyze_projects`: thống kê / so sánh / xếp hạng / đếm / min-max-avg trên
  TOÀN BỘ dự án và quỹ căn.
- Câu về MỘT dự án/căn cụ thể → `search_units` / `get_project_overview` /
  `check_inventory` như cũ; nội dung tài liệu/chính sách → `kb_search`.
- Một dòng ngắn chiều ngược lại được thêm vào description `kb_search` +
  `search_units` (trong marker để không ảnh hưởng tenant tắt tool).

## 6. Persona / RULES

Block `<!-- TOOL:analyze_projects:START/END -->` ở **cả hai** skeleton:
- `persona/chat/RULES.md`: đầy đủ — khi nào dùng, không bịa số liệu ngoài kết
  quả, 0 dòng thì nới điều kiện, không escalate vì rỗng.
- `persona/voice/RULES.md`: ngắn — khi nào dùng + **đọc kết quả thành lời**
  (top 2–3, làm tròn số), tuyệt đối không đọc bảng/liệt kê dài.
- Legacy: thêm mục "Tool catalog" trong `tenants/noble/persona/RULES.md` nếu bật
  cho noble.

## 7. Kiểm chứng

**Unit** (`tests/unit/unified/`):
- Validator: chặn multi-statement, chặn non-SELECT/WITH, auto-LIMIT, strip comment.
- Serializer: cap dòng, truncate cell, bảng rỗng → thông điệp "0 dòng…".
- Vocab: cache hit/miss, TTL, miss → description không vocab (không raise),
  cap 30 giá trị/cột.
- `build_schemas`: tenant bật tool + có vocab → description chứa vocab; tenant
  tắt → schema không xuất hiện.

**Integration** (gated theo pattern needs-PG hiện có của tests/integration; cần
DSN + role đã provision):
- Qua `agent_sql_ro`: SELECT từ 2 view OK; `tenant_data.contacts` →
  `permission denied`; bảng gốc `units` → `permission denied`.
- Row draft không hiện qua view.
- `WITH x AS (DELETE …) SELECT …` → lỗi read-only.
- Đổi `app.current_tenant` → chỉ thấy dữ liệu tenant đó (0 dòng tenant khác).
- Timeout: `SELECT pg_sleep(5)` → canceled.
- Sau lượt tool lỗi, connection trả về pool vẫn ghi được bình thường ở query kế
  (SET LOCAL đã reset — chứng minh dưới pool size-1, giống bài test RLS Option-C).

**Eval** (`evals/`): thêm 2–3 case câu tổng quát (chính câu "dự án nhiều loại hình
nhất") vào suite quality — đo tool_selection + groundedness trước/sau khi bật tool.

**Smoke thủ công**: `python scripts/chat_repl.py --ask "dự án nào có nhiều loại
hình sản phẩm nhất?"` (REPL in nguyên SQL + raw result) + mục mới trong `SMOKE.md`.

## 8. Docs phải cập nhật cùng commit implement

- `CLAUDE.md`: tool taxonomy 13→14 built-in (9 optional), mục "Adding a new
  tool" không đổi; changelog 2 chỗ (bảng 10-entry + `docs/CHANGELOG-agent.md`).
- `docs/architecture/backends.md`/`layout.md` nếu chạm; contract role mới ghi
  chú trong `docs/architecture/multi-tenant.md` (mục RLS/roles).

## 9. Ngoài phạm vi (YAGNI)

- Không expose `documents` / `media` / `zones` chi tiết (zone chỉ hiện qua cột
  `zone_code` của units).
- Không cho SQL chạm bảng hội thoại/appointments/contacts — vĩnh viễn, không phải
  "chưa làm".
- Không semcache cho tool này (read_only=True là đủ phân loại; prefetch off by default).
- Không chart/visualization, không tự viết lại SQL bằng LLM phụ.
- Không đổi các tool hiện có (ngoài 1 dòng ranh giới trong description
  `kb_search`/`search_units`).

## 10. Rủi ro còn lại & cách sống chung

| Rủi ro | Mức | Xử lý |
|---|---|---|
| Model viết SQL sai cột/giá trị | Trung bình | Vocab thật + error feedback loop (5 vòng tool) + ví dụ few-shot |
| Model chọn nhầm tool này cho câu specific | Thấp | Ranh giới 2 chiều trong description; đo bằng eval tool_selection |
| Vocab stale ≤10 phút sau khi Portal đổi dữ liệu | Thấp | Chỉ ảnh hưởng gợi ý giá trị, không ảnh hưởng đúng/sai an toàn; TTL chỉnh được |
| Role chưa provision trên môi trường cũ | Thấp | Tool degrade "tạm không khả dụng"; checklist deploy chạy `pg-ensure-sql-ro` |
