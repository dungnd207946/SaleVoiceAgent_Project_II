# M1 — Nền cách ly đa-tenant + hạ tầng dùng chung

> **Ngày:** 2026-07-29 · **Trạng thái:** chờ duyệt · **Lớp:** backend, **không có UI**
> **Spec tổng:** `2026-07-29-odyssey-portal-kien-truc-va-ban-do-module.md`
> **Hợp đồng:** `docs/contracts/isolation.md` — đọc trước
> **Nguồn:** `docs/product/2026-07-28-slice-1a.ref.md` (plan chi tiết, có SQL sẵn) ·
> `docs/product/2026-07-28-tenant-portal-control-plane-design.ref.md` §5.1–5.4, §5.8, §9

## Bảng đối chiếu màn hình

| Sidebar | `data-screen` | Module |
|---|---|---|
| *(không có mục nào)* | — | **M1** |

M1 **không xuất hiện trong sidebar**. Thiết kế mặc định nó đã tồn tại. Nhưng nó là phần đắt nhất và
duy nhất không retrofit được: nó trả lời *"hàng này thuộc workspace nào"*, và sai thì không phải bug
— là **sự cố rò dữ liệu giữa hai khách hàng**.

Bảng đối chiếu 18 màn ↔ 9 module: xem spec tổng §2.

---

## 1. Mục tiêu

Dựng nền Postgres của control plane và **chứng minh cách ly không vỡ** bằng 6 cổng test. Cụ thể:

1. Bốn schema + mô hình role + hàm xác định tenant.
2. **Một helper DDL duy nhất** để module sau tự tạo bảng mà không lặp lại bốn điều kiện hỏng-âm-thầm.
3. Neo danh tính (`control.tenants`) + cơ chế gate cột (`field_policy_live` + `pol()` + `gated_extras()`).
4. Hai bảng `tenant_data` với **schema lõi tối thiểu** đủ chứng minh cách ly hàng + gate cột.
5. Hợp đồng đọc `agent_api` — view definer.
6. `tenant_conn()` — cửa duy nhất để module khác truy vấn `tenant_data`.
7. **Hạ tầng dùng chung mà 4 module cần** (xem spec tổng §3.2): `control.jobs` + tiến trình worker +
   handler registry · `control.agent_heartbeats` + `derive_tenant_status()`.

**Không** thuộc M1: `users`/`memberships` (M2) · `config_drafts`/`config_versions`/`tenants.live_version`/`deployments`/`apply_config_version()`/bundle render/kho tệp (M3) · cột đầy đủ `projects`/`units` (M4) · `conversations`/`contacts`/`appointments` (M7) · ba bảng Finance (ngoài MVP).

> **Vì sao `jobs` và `agent_heartbeats` ở đây, không ở M3.** Cả hai là hạ tầng dùng chung: `jobs` cần
> cho M4 (import) · M6 (build index) · M8 (job xoá quá hạn) · M3 (publish); `agent_heartbeats` cần
> cho M2 (badge trạng thái workspace) · M9 (bước 3 wizard) · M3. Để chúng ở M3 là buộc bốn module đợi
> một module — và **M3 đã được quyết là làm sau, do người khác** (spec tổng §3.3).
>
> Nó cũng nhất quán về khái niệm: M1 sở hữu **toàn bộ seam agent** — `agent_api` view là đường agent
> **đọc**, `agent_heartbeats` là đường agent **ghi**.

---

## 2. Bốn chỗ M1 khác plan 1a — và vì sao

Plan `slice-1a.ref.md` là điểm xuất phát tốt (2002 dòng, SQL sẵn, TDD từng bước). Bốn chỗ sửa:

### 2.1 M1 không tạo hết bảng — nó ship helper để module khác tự tạo

Plan gốc: M1 tạo **10 bảng `control` + 7 bảng `tenant_data`**. Nghĩa là M1 phải biết trước cột của cả
8 module ⇒ không ai xây module độc lập được, và mọi thay đổi schema đi qua một người.

**Bản M1:** M1 sở hữu **cơ chế** cách ly + **neo danh tính**. Mỗi module tự sở hữu bảng của nó, gọi
`control.enforce_tenant_isolation()`. Catalog test (cổng 6) canh không ai quên.

M1 tạo đúng **4 bảng**: `control.tenants` · `control.tenant_verticals` · `control.field_policy_live` ·
và trong `tenant_data` là `projects` + `units` **lõi** (đủ cột để chứng minh gate — M4 `ALTER` thêm
~40/~45 cột còn lại, đây là ngoại lệ đã hẹn trước ở spec tổng §4④).

### 2.2 Thêm `FORCE ROW LEVEL SECURITY` — plan gốc bỏ sót

Plan gốc chỉ `ENABLE ROW LEVEL SECURITY`, và lập luận: *"`portal_migrator` là owner nên RLS không áp
lên nó — đó là lý do nó là DDL-only"*. Lập luận đó **đúng về mặt chức năng** (`portal_api` không phải
owner nên RLS áp bình thường), nhưng nó biến điều kiện 1 của spec §5.8 từ **cưỡng chế** thành **quy
ước**:

- Ai đó chạy một script backfill bằng role owner ⇒ đọc/ghi xuyên tenant, không có gì chặn.
- Cổng test *"bỏ `FORCE` đi thì test phải đỏ"* (spec §9 cổng 5) **không tồn tại được** nếu không có `FORCE`.

**Chốt: `FORCE` nằm trong `enforce_tenant_isolation()`.** Giá: một dòng DDL, viết một lần.

> ⚠️ **Hệ quả phải nhận:** với `FORCE`, migration nào **backfill dữ liệu** (không chỉ DDL) cũng bị
> RLS lọc, vì nó chạy bằng owner. Luật: migration backfill phải `SET LOCAL app.tenant_id` cho từng
> tenant, hoặc `ALTER TABLE … NO FORCE ROW LEVEL SECURITY` → backfill → `FORCE` lại **trong cùng
> migration**. Ghi vào header file migration đó. Đây là chi phí có thật của việc chọn cưỡng chế thay
> vì quy ước, và nó rẻ hơn cái nó mua.

### 2.3 Thêm cổng test "rò qua connection pool"

Plan gốc có `test_tenant_conn_helper_set_dung_tenant` (kiểm helper đặt đúng tenant) nhưng **không có**
test xen kẽ hai request khác tenant trên cùng một pool. Đó là điều kiện 4 của spec §5.8 và spec §9
cổng 6 — **lỗi chỉ hiện khi có tải thật**, nên không test thì không bao giờ thấy ở dev.

### 2.4 Đánh số cổng lại cho khớp spec §9

Plan gốc dùng cổng 1–4 với nghĩa khác spec. M1 dùng đánh số ở §6 dưới đây và ghi rõ cổng nào ở module
nào, để không ai tưởng "4 cổng là đủ".

Ba sửa lỗi **C1 · C2 · C3** của plan gốc thì **nhận nguyên**: view definer thay `security_invoker` ·
`tenants.lifecycle` là cột lưu còn trạng thái hiển thị là hàm thuần · không tạo role `BYPASSRLS`.

---

## 3. Schema

### 3.1 Bốn schema

| Schema | Chứa | RLS | Ai được `USAGE` |
|---|---|---|---|
| `portal` | hàm hạ tầng: `current_tenant()` · `pol()` · `gated_extras()` | — | `portal_api` · `agent_*` |
| `control` | dữ liệu control plane: `tenants` · `tenant_verticals` · `field_policy_live` · `jobs` · `agent_heartbeats` | **không** — trừ **một ngoại lệ**: `agent_heartbeats` (§3.7) | `portal_api`. Agent: `USAGE` + ghi **đúng `agent_heartbeats`**, zero quyền trên bảng `control` khác |
| `tenant_data` | dữ liệu của tenant | **có, + FORCE** | `portal_api`. Agent: **zero privilege** (trừ bảng M7 đăng ký qua `grant_agent_write()`) |
| `agent_api` | view definer — hợp đồng đọc của agent | — (view) | `agent_all` (`SELECT` trên view) |

### 3.2 `control.tenants` — neo danh tính

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | `text` PK | **slug, chính là `TENANT_ID`** của pod agent. `CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$')` — vì nó đi vào **tên role** `agent_<id>`, **đường dẫn** `tenants/<id>/`, **tên collection** `kb_<id>` |
| `name` | `text` | tên hiển thị |
| `lifecycle` | `text` | `CHECK IN ('active','suspended','closed')` — **ý chí của người vận hành** (sửa lỗi C2) |
| `created_at` | `timestamptz` | |

**Không có** cột `plan` (hoá đơn không gắn vào khoá cách ly — xem `isolation.md` §8).
**Không có** cột `live_version` (M3 thêm bằng migration `02xx`).
**Không có** cột `status` — trạng thái hiển thị (`provisioning · publishing · ready · disconnected`)
là **hàm thuần** của `lifecycle` + heartbeat + `live_version`, và nó thuộc M3.

### 3.3 `control.tenant_verticals`

`(tenant_id, vertical, enabled_at)`, `vertical CHECK IN ('realestate','finance')`. Bật một lĩnh vực =
một hàng. MVP chỉ `realestate`.

### 3.4 `control.field_policy_live` — một chỗ trả lời "agent được đọc gì"

| Cột | Ghi chú |
|---|---|
| `tenant_id` · `entity` · `field` | PK ba cột |
| `is_core` | `true` = cột thật (gate bằng `CASE WHEN` trong view) · `false` = key trong `extras jsonb` (gate bằng `gated_extras()`) |
| `agent_readable` | tier 1 — agent thấy field này |
| `filterable` + `match_op` | tier 2 — field bơm vào tool schema. `CHECK (match_op IN ('eq','substring','gte','lte','exists','contains'))` — **6 toán tử, là CHECK constraint chứ không phải quy ước** |
| `label_vi` · `type` · `enum_values` | render nhãn trong prompt · `CHECK (enum_values IS NULL OR type = 'enum')` |
| | `CHECK (NOT filterable OR match_op IS NOT NULL)` |

Đây là **bản hiệu lực** — M3 ghi lại toàn bộ bảng này mỗi lần publish (`apply_config_version()`), màn
khai trường của M4 ghi vào `config_drafts`. M1 chỉ tạo bảng + hàm đọc nó.

### 3.5 `tenant_data.projects` / `units` — schema lõi

Lấy nguyên từ plan gốc Task 3, giữ **toàn bộ cột đã có** (chúng đã khớp `nbx_projects`/`nbx_units` và
đã được view Task 5 dùng), bỏ 5 bảng còn lại:

```
projects   id · tenant_id · code · name · slug · type · region · location · investor
           status · is_hot · sort_hot · overview jsonb · lat · lng · extras jsonb · updated_at
           UNIQUE (tenant_id, code)

units      id · tenant_id · code · project_code · unit_type · status · direction
           price_vnd bigint · price_tts_vnd bigint · area_m2 · area_build_m2 · bedrooms · floor
           fund_type · commission ← GATED · bank_support ← GATED · csbh_full ← GATED
           csbh_brief · gift · legal · extras jsonb · updated_at
           UNIQUE (tenant_id, code)
           INDEX (tenant_id, project_code) · (tenant_id, status)
```

Ba điều bắt buộc:

| | |
|---|---|
| **Giá là `bigint` VND** | Không cột nào tên `*_ty`. Đổi đơn vị (tỷ → VND) làm **ở biên nhập** (M4), không ở tầng đọc. Đây chính là bug agent đã phải sửa một lần |
| **`UNIQUE (tenant_id, code)`**, không phải `UNIQUE(code)` | Hai tenant được dùng cùng mã căn. `phone`/`code` unique **toàn cục** là đúng chỗ đơn-tenant của CMS cũ lộ ra |
| **Không có cột `tower`** · `floor` **có cột nhưng không `filterable`** | Quyết định #17 nói gỡ hai **filter** `floor`/`tower` khỏi tool schema, **không** nói xoá cột: `nbx_mongo` khai hai filter đó cho LLM nhưng **không đọc chúng** — khách hỏi "căn tầng 14" thì trả căn tầng bất kỳ, và agent đọc như thể đúng tầng. **Sai âm thầm tệ hơn trả rỗng.** Nên: `floor` giữ làm cột dữ liệu (M4 nạp được), `tower` không tạo (nó vốn hardcode `""`), và **M1 không được seed `field_policy_live` với `filterable=true` cho `floor`** |

`updated_at` là tiền đề cho rào chắn hedge theo độ tươi dữ liệu (quyết định sản phẩm #4) — có sẵn từ
M1 dù rào chắn nằm ở phía agent.

### 3.6 `control.jobs` + worker — hạ tầng dùng chung

| Cột | Ghi chú |
|---|---|
| `id` `bigserial` PK · `tenant_id` · `kind` · `state` · `actor` | `state CHECK IN ('queued','running','success','failed')` |
| `payload jsonb` · `started_at` · `finished_at` · `count` · `message` · `force` | `payload` để handler tự định nghĩa hình dạng của mình |
| | `INDEX (state, id) WHERE state = 'queued'` — cho `SKIP LOCKED` |

`kind` là **`text` tự do, không `enum`** — module sau thêm loại job mà không cần migration. Danh sách
đã biết: `publish` (M3) · `import` (M4) · `rag_build` (M6) · `retention_delete` (M8).

**Worker** (`src/portal/worker/`) là tiến trình riêng, không phải `BackgroundTasks` của FastAPI (nó
chết cùng tiến trình và không để lại dấu vết nào):

```sql
-- Vòng lặp worker: nhặt một job, khoá nó, không chặn worker khác.
SELECT id, tenant_id, kind, payload FROM control.jobs
 WHERE state = 'queued' ORDER BY id
   FOR UPDATE SKIP LOCKED LIMIT 1;
```

**Handler registry** — cơ chế làm module độc lập, giống nav registry của FE:

```python
# portal/core/jobs.py  (M1 ship)
JobHandler = Callable[[asyncpg.Connection, dict], Awaitable[JobResult]]
def register(kind: str, handler: JobHandler) -> None: ...

# portal/modules/m4_realestate/jobs.py  (M4 ship — M1 KHÔNG phải sửa gì)
register("import", handle_import)
```

Worker gom handler bằng cách import `modules/*/jobs.py`. **Thêm loại job không sửa file của M1.**

Handler chạy **trong** `tenant_conn(pool, job.tenant_id)` — nên job cũng bị RLS như mọi thứ khác. Job
không có `tenant_id` (nếu về sau cần job toàn nền tảng) là trường hợp chưa có; khi cần thì thêm tường
minh, không nới lỏng cách ly cho tiện.

**Job theo giờ:** `cron` trên máy chủ gọi một lệnh **ghi một hàng vào `jobs`**. Không dùng scheduler
trong tiến trình. Đây là cách rẻ nhất để lời hứa *"job xoá quá hạn phải có giám sát"* (quyết định #19)
thành thật thay vì khẩu hiệu — job không chạy thì bảng `jobs` cho thấy ngay.

### 3.7 `control.agent_heartbeats` + `derive_tenant_status()`

Bảng **hẹp riêng**, không nhét vào `tenants`: `(tenant_id, deployment_id, running_version, bundle_sha,
agent_version, last_error, last_seen_at)`. **Agent ghi** (UPSERT), portal đọc.

> **Ngoại lệ duy nhất của "schema `control` không RLS".** Đây là bảng control plane **duy nhất** agent
> được ghi, nên phải có gì đó chặn `agent_hb1` ghi hàng của `hb2`. Cách rẻ hơn —
> `CHECK (tenant_id = portal.current_tenant())` — **làm `pg_restore` vỡ**: restore nạp lại từng hàng mà
> không có `app.tenant_id` nào được đặt nên CHECK ra false và **mọi hàng bị từ chối**. Dùng **RLS với
> hai policy theo role**: `TO agent_all` chỉ tenant mình · `TO portal_api` tất cả (admin nền tảng xem
> tình trạng vận hành là quyền control plane, không phải quyền đọc dữ liệu tenant). RLS chỉ áp lúc
> truy vấn, không áp lúc `COPY`. **Không** dùng `FORCE` ở đây — owner cần khôi phục được bằng tay.

`derive_tenant_status()` là **hàm thuần Python** (`src/portal/core/tenant_status.py`), không phải cột
DB — đó là sửa lỗi **C2**: không thể vừa lưu vừa suy ra.

```python
def derive_tenant_status(
    lifecycle: str,            # 'active' | 'suspended' | 'closed'
    last_seen_at: datetime | None,
    running_version: int | None,
    live_version: int | None,  # None khi M3 chưa có → luôn coi là chưa publish
    now: datetime,
) -> str: ...                  # 'provisioning'|'publishing'|'ready'|'disconnected'|'suspended'|'closed'
```

| Trả về | Điều kiện |
|---|---|
| `suspended` / `closed` | `lifecycle` nói vậy — thắng mọi thứ khác |
| `provisioning` | chưa có heartbeat nào |
| `disconnected` | `last_seen_at` cũ hơn **90 giây** (4.5 lần chu kỳ poll 20s — chịu được vài lần miss mà không báo động giả) |
| `publishing` | heartbeat tươi nhưng `running_version < live_version` |
| `ready` | heartbeat tươi + version khớp |

**Tự lành:** pod chết → heartbeat cũ → `disconnected`; pod lên lại → tự về `ready`. Không có trạng
thái nào phải sửa tay.

`live_version` là cột M3 thêm vào `tenants`. Hàm nhận nó là **tham số**, nên M1 test được đầy đủ bằng
unit test (không cần DB, không cần M3) và M2 gọi được ngay với `live_version=None`.

---

## 4. Mô hình role

```
Portal API ──role portal_api──┐ mỗi txn: SET LOCAL app.tenant_id
                              ▼
                   ┌────────────────────────────────────────┐
                   │ POSTGRES                               │
                   │ owner mọi schema = portal_migrator     │
                   │   → CHỈ chạy migration, không phục vụ  │
                   └────────────────────────────────────────┘
                        ▲          ▲          ▲
                   agent_anphu  agent_sunrise  agent_haven
                   (SELECT trên agent_api view — hết)
```

| Role | Dùng khi | Quyền | Không được |
|---|---|---|---|
| `portal_migrator` | **chỉ** chạy migration | owner của 4 schema | superuser · dùng lúc runtime |
| `portal_api` | runtime Portal API + worker | `USAGE` 3 schema (`portal`,`control`,`tenant_data`) · CRUD mọi bảng · `EXECUTE portal.current_tenant()` | superuser · `BYPASSRLS` · `CREATEROLE` · owner bảng nào |
| `agent_all` | **role nhóm NOLOGIN** — mọi `agent_<slug>` là thành viên | Nơi cấp **toàn bộ** quyền của agent, một lần | LOGIN · superuser · `BYPASSRLS` |
| `agent_<slug>` | pod agent của một workspace | Chỉ `GRANT agent_all` — không có grant riêng nào. Qua nhóm: `USAGE` trên `portal`+`agent_api`, `SELECT` trên view `agent_api.*`, `USAGE` trên `control` + ghi **đúng `agent_heartbeats`**, và các bảng M7 đăng ký sau qua `grant_agent_write()` | **bất kỳ quyền nào trên `tenant_data`** chưa đăng ký · **bất kỳ quyền nào trên bảng `control` khác `agent_heartbeats`** |

`control.create_agent_role(p_tenant text, p_password text)` sinh role rồi `GRANT agent_all` — **không
chứa danh sách grant nào**. Thêm view hay bảng agent chạm được thì cấp cho `agent_all` (hoặc gọi
`control.grant_agent_write()`), **không sửa hàm này**. Đây là chỗ cắm thứ tư của thiết kế, cùng khuôn
với `enforce_tenant_isolation()` · `require(action)` · handler registry. Dùng lúc cấp workspace. Cấp workspace đầy đủ là bốn việc cả-bốn-hoặc-không (hàng `tenants` + role Postgres +
collection Qdrant + tiền tố kho tệp) — M1 chỉ ship việc thứ hai; ghép lại là M3/M9.

> **Ràng buộc production, không test được trong testcontainers** (ở đó `POSTGRES_USER` là bootstrap
> superuser): `portal_migrator` phải là **non-superuser**, chỉ `CREATEROLE`, owner của 4 schema.
> Việc của runbook deploy. Ghi vào `deploy/README.md`.

> **`portal_api` ra khỏi migration ở dạng `NOLOGIN`, KHÔNG mật khẩu.** Không bí mật nào của role
> runtime nằm trong git — `portal_api` được `SET app.tenant_id` sang giá trị nào cũng được, nên một
> mật khẩu published là quyền đọc-ghi mọi tenant cho bất kỳ ai chạm tới cổng Postgres. Cấp quyền đăng
> nhập là việc riêng sau migration: `ALTER ROLE portal_api LOGIN PASSWORD '<bí mật>'`
> (`deploy/README.md` §3; `tests/conftest.py` làm đúng thế với `API_PASSWORD`). Quên ⇒ app **không
> nối được**, không phải nối được bằng mật khẩu ai cũng đọc.

---

## 5. `enforce_tenant_isolation()` — helper trung tâm

Đây là API mà **8 module còn lại** dùng. Nó là lý do M1 tồn tại như một module riêng.

```sql
CREATE FUNCTION control.enforce_tenant_isolation(p_qualified_table text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  -- 1. RLS bật
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', p_qualified_table);
  -- 2. FORCE: Postgres MIỄN RLS cho role sở hữu bảng. Thiếu dòng này thì mọi
  --    truy vấn chạy bằng owner (script backfill, phiên debug) đi xuyên cách ly
  --    mà không có triệu chứng nào.
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', p_qualified_table);
  -- 3. Policy: USING chặn ĐỌC hàng tenant khác, WITH CHECK chặn GHI sang tenant khác.
  --    current_tenant() = NULL -> tenant_id = NULL -> false -> 0 hàng (fail-closed).
  EXECUTE format($f$
    CREATE POLICY tenant_isolation ON %s
      USING (tenant_id = portal.current_tenant())
      WITH CHECK (tenant_id = portal.current_tenant())
  $f$, p_qualified_table);
  -- 4. Grant chuẩn cho role runtime của portal.
  EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %s TO portal_api', p_qualified_table);
END $$;
```

**Hợp đồng:** bảng truyền vào phải nằm trong schema `tenant_data` và có cột `tenant_id text NOT NULL
REFERENCES control.tenants(id) ON DELETE CASCADE`. Hàm `RAISE EXCEPTION` nếu không — thà vỡ lúc
migrate hơn vỡ lúc chạy.

`portal.current_tenant()` (chi tiết ở `isolation.md` §4):

```sql
CREATE FUNCTION portal.current_tenant() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    NULLIF(substring(session_user FROM '^agent_(.+)$'), ''),
    current_setting('app.tenant_id', true)
  )
$$;
```

**`session_user`, không phải `current_user`** — trong definer view `current_user` trả về owner của
view, không phải agent. Đây là chỗ dễ sai nhất và cổng 1 canh nó.

---

## 6. Hợp đồng đọc `agent_api`

```sql
CREATE VIEW agent_api.units AS       -- DEFINER (mặc định). KHÔNG security_invoker — xem isolation.md §5.1
SELECT u.tenant_id, u.code, u.project_code, u.unit_type, u.status, u.direction,
       u.price_vnd, u.price_tts_vnd, u.area_m2, u.area_build_m2, u.bedrooms,
       u.fund_type, u.csbh_brief, u.gift, u.legal, u.updated_at,
       CASE WHEN portal.pol('unit','commission')   THEN u.commission   END AS commission,
       CASE WHEN portal.pol('unit','bank_support') THEN u.bank_support END AS bank_support,
       CASE WHEN portal.pol('unit','csbh_full')    THEN u.csbh_full    END AS csbh_full,
       portal.gated_extras('unit', u.extras) AS extras
FROM tenant_data.units u
WHERE u.tenant_id = portal.current_tenant();   -- ← view TỰ lọc: definer nên RLS của owner không áp
```

M1 ship **2 view**: `agent_api.projects` · `agent_api.units`. (Plan gốc ship 5; ba view Finance đi
cùng ba bảng Finance sang ngoài MVP.)

**Trùng lặp có chủ đích:** bundle của M3 cũng mang `extras.toml` để agent **dựng tool schema + render
nhãn**; nhưng **VIEW mới là chỗ cưỡng chế**. Bundle lệch cũng không rò được dữ liệu.

**Vì sao view chứ không phải bảng:** portal refactor `tenant_data` tự do — đổi tên cột, tách bảng,
thêm index — miễn giữ view. Đó là điều làm cả hệ dễ refactor về sau.

---

## 7. Sáu cổng test — không được skip cái nào

Vị trí: `tests/isolation/`. CI chạy job này **không path-filter**, cho **mọi** PR.

| Cổng | Kiểm | Điều kiện §5.3 | File |
|---|---|---|---|
| **1** | **Cross-tenant read = 0 hàng.** Hai tenant, hai role `agent_*`; role A `SELECT agent_api.units` thấy **0 hàng** của B. Canh `session_user` + `WHERE` trong view | 3 | `test_rls_isolation.py` |
| **2** | **Gate cột.** `agent_readable=false` ⇒ cột về `NULL`, key `extras` bị lọc. Đổi `field_policy_live` ⇒ view đổi theo **không cần migrate** | — | `test_view_column_gate.py` |
| **3** | **Chủ bảng không bypass RLS.** Nối bằng owner ⇒ vẫn bị chặn. **Xoá `FORCE` khỏi helper ⇒ test này phải ĐỎ** | 1 | `test_force_rls.py` |
| **4** | **Rò qua connection pool.** Hai request khác tenant xen kẽ trên **cùng một pool**; request không `SET LOCAL` phải trả **0 hàng**, không kế thừa tenant của request trước | 4 | `test_pool_leak.py` |
| **5** | **Quyền role.** `portal_api`/`agent_*` không superuser · không `BYPASSRLS` · không owner bảng nào. Quét **động** mọi bảng `tenant_data`: `agent_*` có **zero privilege**, trừ bảng khai trong `AGENT_WRITABLE_TENANT_DATA_TABLES` (rỗng ở M1; mỗi module gọi `grant_agent_write()` tự thêm kèm lý do) thì đúng `SELECT`/`INSERT`/`UPDATE`. `USAGE` trên schema `tenant_data` phải **vắng khi danh sách rỗng**. Trên `control`: chỉ `agent_heartbeats` | 2 · 3 | `test_role_privileges.py` |
| **6** | **Catalog test — ba phép quét**, tất cả đều là "canh module SAU": ① **mọi** bảng `tenant_data` có `relrowsecurity` + `relforcerowsecurity` + policy `tenant_isolation` (quên helper ⇒ CI đỏ ngay) · ② **mọi** view `agent_api` tham chiếu `current_tenant` — view definer nên RLS không áp bên trong, và 0005 auto-grant mọi view mới cho mọi agent · ③ **mọi** bảng `control` mang cột `tenant_id` phải nằm trong allow-list có lý do — `control` không có RLS | 1 · tất cả | `test_isolation_catalog.py` |

Hai cổng ở module khác, **cùng hạng bắt buộc** — ghi ra để không ai tưởng 6 cổng là đủ:

| Cổng | Kiểm | Module |
|---|---|---|
| 7 | Kho tệp: credential của A `GET` `tenants/B/*` phải bị **từ chối**. MinIO thật trong container ở test; production **S3 + IAM policy** | M3 |
| 8 | Knowledge: query của A trả **0 chunk** của B | M6 |

**Cách viết:** TDD — test trước, xác nhận đỏ, rồi mới viết migration. Plan gốc đã có sẵn phần lớn
code test này; nhấc sang và sửa theo bốn chỗ ở §2.

---

## 8. Contract M1 xuất ra cho module khác

Đây là **toàn bộ** bề mặt module khác được dùng. Đổi bất kỳ dòng nào = đổi hợp đồng, phải báo.

### 8.1 SQL

| | |
|---|---|
| `control.enforce_tenant_isolation(qualified_table text)` | Bật cách ly cho một bảng mới. **Bắt buộc gọi** cho mọi bảng `tenant_data` |
| `control.create_agent_role(tenant text, password text)` | Sinh role + grant hẹp cho một workspace |
| `portal.current_tenant() → text` | Tenant hiệu lực. `NULL` = không xác định được |
| `portal.pol(entity text, field text) → boolean` | Field này agent đọc được không |
| `portal.gated_extras(entity text, extras jsonb) → jsonb` | Lọc key `extras` theo policy |
| `control.tenants(id, name, lifecycle, created_at)` | Neo danh tính. FK của mọi bảng `tenant_data` |
| `control.tenant_verticals(tenant_id, vertical, enabled_at)` | |
| `control.field_policy_live(...)` | M3 ghi lại toàn bộ khi publish · view đọc |
| `control.jobs(...)` + view `control.jobs_stuck` | Hàng đợi job. M4·M6·M8·M3 ghi vào · worker đọc. `jobs_stuck` là bề mặt giám sát: job `running` > 15 phút |
| `control.grant_agent_write(qualified_table)` | Mở đường **ghi** cho agent lên một bảng `tenant_data`. M7 gọi trong migration của nó |
| `control.agent_heartbeats(...)` | Agent ghi · M2·M9·M3 đọc |
| `agent_api.projects` · `agent_api.units` | Hợp đồng đọc của agent. **Không lộ cột `tenant_id`** — agent chỉ có một tenant |

### 8.2 Python

```python
# portal.core.db
async def create_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool: ...

@asynccontextmanager
async def tenant_conn(pool, tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    """Mở giao dịch + SET LOCAL app.tenant_id. CỬA DUY NHẤT để truy vấn tenant_data.

    tenant_id PHẢI đến từ membership đã xác thực (M2), không bao giờ từ input client.
    tenant_id rỗng -> ValueError. Không có đường đọc ngoài giao dịch.
    """

# portal.core.config
class Settings(BaseSettings):
    database_url: str      # DSN RUNTIME (asyncpg), role portal_api — API + worker
    migrator_url: str      # DSN chỉ-DDL, role portal_migrator — CHỈ alembic
    alembic_url: str       # @property, suy từ migrator_url (đổi driver sang psycopg)
    # HAI credential, không phải một. Không tiến trình runtime nào dùng migrator_url:
    # portal_migrator là owner (và là superuser ở container dev), nên nó đi xuyên RLS
    # bất kể FORCE. deploy/README.md §1–§2.

# portal.core.jobs — module khác dùng để khai handler và xếp job
def register(kind: str, handler: JobHandler) -> None: ...
async def enqueue(conn, *, tenant_id: str, kind: str, actor: str, payload: dict) -> int: ...

# portal.core.tenant_status — hàm THUẦN, test được không cần DB
def derive_tenant_status(lifecycle, last_seen_at, running_version, live_version, now) -> str: ...
```

### 8.3 Cấu hình

`docker-compose.dev.yml`: Postgres 18-alpine, cổng **5433** (cổng lệch để không đụng Postgres có sẵn trên máy).
Production là **Aurora PostgreSQL**, devops chuyển lúc deploy (chốt 2026-07-30) — major của Aurora gần như chắc
chắn **thấp hơn** dev, và **không có gì tự động kiểm sai lệch đó**. Khoảng hở đã biết: deploy/README.md §6.1.
`.env.example` có mẫu cả hai DSN — `DATABASE_URL` (`portal_api`) và `MIGRATOR_URL`
(`portal_migrator`) — kèm chú thích vì sao không được gộp. Sàn cứng **Postgres ≥ 15** (vì `security_invoker` tồn tại từ 15 —
ta không dùng nó, nhưng ràng buộc bản đã ghi trong tài liệu nguồn thì giữ), dùng bản mới nhất ở dev. **Trần
thực tế do Aurora đặt ở production**, và dev không bị ràng theo — xem deploy/README.md §6.1.

---

## 9. Danh sách file

| File | Trách nhiệm |
|---|---|
| `pyproject.toml` | deps · ruff (120, `E,F,W,I,UP,B,SIM`) · pytest markers |
| `alembic.ini` · `migrations/env.py` | DSN từ `Settings.alembic_url` (suy từ `migrator_url`); **URL do caller nạp sẵn thắng** (nếu không, fixture test bị ghi đè DSN container → migrate sai database, tệ nhất là migrate DB dev của người đang chạy) |
| `migrations/versions/0001_schemas_and_functions.py` | 4 schema (`portal` · `control` · `tenant_data` · `agent_api` tạo ở 0005) · `portal.current_tenant()` |
| `migrations/versions/0002_control_core.py` | `tenants` · `tenant_verticals` · `field_policy_live` |
| `migrations/versions/0003_role_and_isolation_helper.py` | role `agent_all` (nhóm) · role `portal_api` (**`NOLOGIN`, không mật khẩu** — fail-closed, xem `deploy/README.md` §3) · grant + default privileges trên `control` · `control.enforce_tenant_isolation()` |
| `migrations/versions/0004_tenant_data_core.py` | schema `tenant_data` · `projects` · `units` + gọi `enforce_tenant_isolation()` cho cả hai |
| `migrations/versions/0005_agent_api.py` | `portal.pol()` · `portal.gated_extras()` · schema `agent_api` · 2 view definer · auto-grant `agent_all` · `control.grant_agent_write()` · `control.create_agent_role()` |
| `migrations/versions/0006_jobs.py` | `control.jobs` + index riêng cho `SKIP LOCKED` · view giám sát `control.jobs_stuck` |
| `migrations/versions/0007_agent_heartbeats.py` | `control.agent_heartbeats` + RLS với 2 policy theo role · grant ghi cho `agent_all` |
| `src/portal/core/config.py` | `Settings` — **hai** DSN (§8.2) |
| `src/portal/core/db/pool.py` · `session.py` | `create_pool()` · `tenant_conn()` |
| `src/portal/core/jobs.py` | `register()` · `enqueue()` (suy tenant từ kết nối) · `run_once()` + hằng số `_CAU_NHAT_JOB` (`SKIP LOCKED`) · `JobHandler` |
| `src/portal/core/tenant_status.py` | `derive_tenant_status()` — hàm thuần |
| `src/portal/worker/__main__.py` | Vòng lặp `FOR UPDATE SKIP LOCKED` · gom handler từ `modules/*/jobs.py` |
| `tests/conftest.py` | container Postgres · chạy migration bằng DSN migrator · `ALTER ROLE portal_api LOGIN PASSWORD` sau migration (`API_PASSWORD` là nguồn duy nhất) · fixture `pool` (owner) và `api_dsn` (runtime) |
| `tests/unit/test_config.py` | Hai DSN · default runtime KHÔNG được là `portal_migrator` · `.env.example` có cả hai |
| `tests/isolation/test_*.py` | 6 cổng (§7) |
| `tests/unit/test_tenant_status.py` | Bảng trạng thái §3.7 — 6 nhánh, không cần DB |
| `tests/modules/test_worker.py` | Worker nhặt job · `SKIP LOCKED` không nhặt trùng · handler chạy trong `tenant_conn` |
| `tests/test_module_boundaries.py` | Test AST: cấm import chéo ruột module (spec tổng §4①) |
| `docker-compose.dev.yml` · `.env.example` · `Makefile` | dev · test · `test M=<module>` · lint · migrate |
| `.gitlab-ci.yml` | job `isolation` (không path-filter) + khung job theo module |
| `deploy/README.md` | Ràng buộc production của `portal_migrator` (§4) |

---

## 10. Suy biến

| Hỏng gì | Hành vi |
|---|---|
| Không xác định được tenant | `current_tenant()` → `NULL` → **0 hàng**. Trả rỗng, không trả nhầm của người khác |
| `tenant_conn()` gọi với `tenant_id` rỗng | `ValueError` ngay, không mở giao dịch |
| Truy vấn `tenant_data` ngoài giao dịch | `app.tenant_id` không được đặt → 0 hàng. Cổng 4 canh |
| Module thêm bảng mà quên helper | Cổng 6 đỏ ở CI |
| Migration backfill chạy bằng owner | Bị `FORCE` lọc → 0 hàng. Xem cảnh báo §2.2 — phải `SET LOCAL` hoặc toggle `NO FORCE` trong cùng migration |
| Lỗi store | **Fail loud.** Không nuốt lỗi thành danh sách rỗng như `BaseRepo` của CMS |
| Handler job ném exception | Job → `state='failed'` + `message` = lỗi thật. **Không** retry vô hạn: retry là quyết định của từng loại job, mặc định không retry |
| Worker chết giữa lúc chạy job | Job kẹt ở `running`. Worker lên lại **không** tự nhặt lại (không biết job đã làm tới đâu). Có một truy vấn giám sát: job `running` quá 15 phút là bất thường — người xử lý, không phải máy đoán |
| Không có heartbeat nào | `derive_tenant_status()` → `provisioning`, không phải lỗi. Workspace mới tạo là trường hợp này |

---

## 11. Định nghĩa "xong"

- [ ] `make test` xanh; 6 cổng §7 đều **có** và đều xanh
- [ ] Xoá `FORCE` khỏi `enforce_tenant_isolation()` ⇒ **cổng 3 đỏ**. Kiểm bằng tay một lần, ghi kết quả vào commit message
- [ ] Thêm một bảng `tenant_data` mà **không** gọi helper ⇒ **cổng 6 đỏ**. Kiểm bằng tay một lần
- [ ] `derive_tenant_status()` phủ **cả 6 nhánh** của bảng §3.7 bằng unit test, không cần DB
- [ ] Worker: hai worker chạy song song **không nhặt trùng một job** (test `SKIP LOCKED`); handler
      chạy trong `tenant_conn` nên bị RLS như mọi thứ khác
- [ ] Một module giả trong test đăng ký `kind` mới và worker chạy được nó **mà không sửa file nào của M1**
- [ ] `make lint` xanh (ruff)
- [ ] `docker compose -f docker-compose.dev.yml up` + `make migrate` chạy được từ repo sạch
- [ ] `deploy/README.md` ghi ràng buộc `portal_migrator` non-superuser
- [ ] Mọi file migration có header tiếng Việt giải thích **vì sao**, không chỉ **cái gì**
- [ ] Contract §8 khớp code thật; `docs/contracts/isolation.md` khớp §5–§7

## 12. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| `security_invoker` bị ai đó "sửa lại cho đúng spec" | Cao | `isolation.md` §5.1 giải thích tại sao spec sai. Cổng 2 + 5 đỏ nếu đổi |
| `FORCE` làm vỡ migration backfill của module sau | Trung bình | Ghi luật ở §2.2 + trong docstring của helper. Người đầu tiên gặp sẽ đọc được lý do |
| Cổng 3 và 4 hay bị bỏ nhất (chúng không bảo vệ tính năng nào, chỉ bảo vệ giả định) | Cao | Job CI `isolation` không path-filter; định nghĩa "xong" buộc kiểm tay một lần |
| `tenant_id` slug đi vào tên role/đường dẫn/collection ⇒ injection nếu không validate | Trung bình | `CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$')` ở tầng DB, không chỉ ở tầng app |
