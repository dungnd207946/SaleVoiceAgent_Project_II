# Hợp đồng cách ly đa-tenant

> **Đối tượng:** mọi người viết code trong repo này, kể cả người chưa từng dùng RLS.
> **Sở hữu:** M1. Đổi tài liệu này = đổi hợp đồng, phải báo mọi module.
> **Cưỡng chế:** 6 cổng test ở `tests/isolation/` — chạy cho **mọi** PR.

Đọc hết cái này trước khi viết dòng query đầu tiên. Nó ngắn, và phần này sai thì không phải bug —
là sự cố rò dữ liệu giữa hai khách hàng.

---

## 1. Vấn đề

Một database, nhiều khách hàng. Bảng `tenant_data.units` chứa căn hộ của **cả** *An Phú Land* lẫn
*Sunrise*. Làm sao An Phú không bao giờ thấy căn của Sunrise?

**Cách phổ biến — và sai:** code tự thêm `WHERE tenant_id = ...` vào mỗi query.

Vì sao sai: một chỗ quên là rò dữ liệu, và lỗi đó **im lặng**. Query vẫn chạy, vẫn trả kết quả, chỉ
là kết quả của khách hàng khác. Không có exception, không có log, không có gì để thấy. Nó chỉ lộ ra
khi khách hàng gọi lên hỏi *"vì sao tôi thấy dự án của công ty khác"*.

**Cách đúng: để Postgres tự cưỡng chế.** Lập trình viên có quên cũng không rò được.

---

## 2. Ba lớp — mỗi lớp trả lời một câu khác nhau

Đây là chỗ hay bị gộp nhầm nhất, và gộp nhầm thì tưởng an toàn mà không phải.

| Lớp | Trả lời câu | Cưỡng chế bởi | Sở hữu |
|---|---|---|---|
| **1 · Hàng** | *"hàng này thuộc workspace nào"* | Postgres **RLS** | M1 |
| **2 · Cột** | *"agent được đọc cột nào"* | **`agent_api` view** đọc `field_policy_live` | M1 (cơ chế) · M4 (màn khai) |
| **3 · Hành động** | *"người này có được xoá không"* | **Portal API**, mọi endpoint | M2a (chỗ cắm) · M2b (ma trận) |

> ### Lớp 1 KHÔNG thay được lớp 3
>
> Một `Viewer` đọc đúng workspace của mình đi qua RLS **sạch sẽ** — RLS không có ý kiến gì về việc
> họ có được xoá dự án không. Chặn việc đó là lớp 3, ở tầng API. Tưởng "đã có RLS nên an toàn" là
> nhầm lẫn kinh điển, và hậu quả là một lỗ hổng không ai thấy khi đọc code.

---

## 3. Lớp 1 — hàng nào (RLS)

**RLS (Row Level Security)** = dán vào bảng một luật: *"chỉ trả hàng có `tenant_id` = tenant hiện
tại"*. Postgres tự thêm điều kiện đó vào **mọi** câu `SELECT` / `UPDATE` / `DELETE` trên bảng đó —
kể cả câu mà lập trình viên quên viết `WHERE`.

Bạn không tự viết đoạn này. Bạn gọi helper:

```sql
-- Trong migration của module bạn, sau khi CREATE TABLE:
SELECT control.enforce_tenant_isolation('tenant_data.don_hang');
```

Một lời gọi làm bốn việc: `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + policy
`tenant_isolation` + grant chuẩn cho `portal_api`.

**Bảng mới trong `tenant_data` mà không gọi helper ⇒ CI đỏ** (cổng 6 quét `pg_class`/`pg_policies`).
Đó là cố ý: bạn không thể quên, vì có thứ nhắc bạn.

---

## 4. "Tenant hiện tại" là ai — hai nguồn, vì hai bản chất

| | Agent (pod) | Portal API |
|---|---|---|
| Nối vào Postgres bằng | `agent_anphu` — **mỗi workspace một user DB riêng** | `portal_api` — **một user cho mọi workspace** |
| Tenant lấy từ | **tên user đang đăng nhập** (`session_user`) | `SET LOCAL app.tenant_id = 'anphu'` |
| Đặt lại khi nào | Không bao giờ — cố định suốt đời pod | **Mỗi giao dịch** |
| Tự khai tenant khác được? | **Không.** Nó không đổi được tên đăng nhập của chính nó | **Có** ⇒ phải đặt từ membership đã xác thực, **tuyệt đối không từ input của client** |

```sql
CREATE FUNCTION portal.current_tenant() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    NULLIF(substring(session_user FROM '^agent_(.+)$'), ''),   -- agent: từ tên role
    current_setting('app.tenant_id', true)                     -- portal: từ biến giao dịch
  )
$$;
```

**Hỏng theo chiều nào:** không xác định được tenant ⇒ hàm trả `NULL` ⇒ `tenant_id = NULL` không bao
giờ đúng ⇒ **0 hàng**. Trả rỗng, **không** trả nhầm của người khác. Đó là chiều hỏng đúng, và nó có
chủ đích.

### 4.1 `SET LOCAL`, không bao giờ `SET`

`SET LOCAL` chỉ sống trong **một giao dịch**. `SET` trần sống cả **kết nối**.

Vì sao khác nhau chí tử: kết nối được tái dùng từ pool.

```
request A (anphu)   → lấy kết nối #7 → SET app.tenant_id='anphu' → xong → trả #7 về pool
request B (sunrise) → lấy kết nối #7 → quên set          → KẾ THỪA 'anphu'
                                                            → đọc dữ liệu của An Phú
```

Lỗi này **chỉ hiện khi có tải thật**. Ở máy dev một người bấm một lúc thì không bao giờ thấy.
Cổng 4 canh đúng nó.

### 4.2 Luật cho mọi module: không có đường đọc ngoài giao dịch

Mọi truy vấn `tenant_data` đi qua đúng một cửa:

```python
from portal.core.db import tenant_conn

async with tenant_conn(pool, tenant_id) as conn:   # mở txn + SET LOCAL app.tenant_id
    rows = await conn.fetch("SELECT code, price_vnd FROM tenant_data.units")
    #  ^ không cần WHERE tenant_id — RLS đã lo. Viết thêm cũng không sai, chỉ là dư
```

`tenant_id` truyền vào đây phải đến từ **membership đã xác thực của người đăng nhập**, không phải từ
path param, query string, hay body. Nếu bạn thấy mình đang đọc `tenant_id` từ request rồi truyền
thẳng vào đây — dừng lại, đó là lỗ hổng.

---

## 5. Lớp 2 — cột nào (view) — ⚠️ TOÀN BỘ MỤC 5 ĐÃ LỖI THỜI, ĐỌC BOX NÀY TRƯỚC

**Hiện trạng thật (2026-08-10), hai lớp đã xoá:**
1. Cơ chế gate cột (`commission`/`bank_support`/`csbh_full`, `portal.pol()`, `field_policy_live`) đã
   bỏ khi KB viết lại theo `real_estate` — schema mới không còn cột thương mại nhạy cảm.
2. `agent_api` — TOÀN BỘ SCHEMA — đã bỏ ở migration `0917_bo_agent_api`. Đảo ngược có chủ ý lý lẽ
   "view definer, zero privilege trên bảng gốc" của §5.1 dưới đây: agent giờ đọc THẲNG
   `tenant_data.{projects,units,zones,documents,media}`, cách ly chỉ còn dựa vào RLS FORCE (§3,
   migration `0913`). `grant_agent_write()` (§5.3) không đổi — vẫn là cách agent ghi 4 bảng
   write-back.

Mục 5/5.1/5.2/5.3 dưới đây giữ nguyên làm **hồ sơ lịch sử** (lý do gốc của thiết kế view, và vì sao
nó bị đảo ngược — người yêu cầu đã được cảnh báo đúng lý lẽ này trước khi quyết định, xem docstring
`0917_bo_agent_api.py`). Đừng viết code theo các ví dụ `CREATE VIEW agent_api.*` bên dưới — chúng
không còn tồn tại trong DB. Chi tiết thiết kế hiện hành: `CLAUDE.md` mục "`agent_api` đã bỏ hoàn
toàn".

---

Có cột nhạy cảm thương mại: `commission` (hoa hồng), `bank_support`, `csbh_full`. Có tenant muốn
agent biết để trả lời khách, có tenant không. **Hoa hồng lộ ra cho khách là sự cố thật**, không phải
tính năng phụ.

Giải bằng view, không bằng code:

```sql
CREATE VIEW agent_api.units AS      -- view DEFINER (mặc định), KHÔNG security_invoker
SELECT u.tenant_id, u.code, u.project_code, u.unit_type, u.status, u.price_vnd, u.area_m2,
       CASE WHEN portal.pol('unit','commission') THEN u.commission END AS commission,
       portal.gated_extras('unit', u.extras) AS extras
FROM tenant_data.units u
WHERE u.tenant_id = portal.current_tenant();   -- ← view TỰ lọc, xem §5.1
```

`portal.pol(entity, field)` và `portal.gated_extras(entity, extras)` tra `control.field_policy_live` — bảng mà màn
"khai trường" của M4 ghi vào. Một chỗ trả lời *"agent được đọc gì"*.

### 5.1 Vì sao view definer, không phải `security_invoker`

⚠️ **Đây là chỗ dễ mất cách ly nhất trong toàn hệ, và spec gốc §5.4 ghi SAI.** Theo bản đúng (sửa
lỗi C1 của plan lát 1a):

`security_invoker = true` khiến Postgres kiểm quyền người gọi **trên bảng gốc**. Nghĩa là agent phải
được `GRANT SELECT ON tenant_data.units`. Và khi agent đã có quyền đó, nó **query thẳng bảng gốc** —
bỏ qua toàn bộ gate cột. Cơ chế "view lo cột" bị vô hiệu hoàn toàn.

Bản đúng:

| | |
|---|---|
| View | **definer** (mặc định), ở schema riêng `agent_api` |
| Quyền của agent | `USAGE` trên `agent_api` + `SELECT` trên từng view. **Zero privilege trên `tenant_data`** |
| Ai lọc tenant | **View tự lọc** trong `WHERE`. Definer view chạy bằng quyền owner nên RLS của owner không áp — không tự lọc là rò hết |
| Suy tenant từ | **`session_user`**, không phải `current_user`. Trong definer view `current_user` trả về **owner của view**, không phải agent |

"Agent không có quyền chạm bảng gốc" **mạnh hơn** RLS: RLS lọc hàng, còn cái này là không vào được
cửa. Đánh đổi: mất defense-in-depth của RLS trên đường đọc của agent — bù bằng `current_tenant()`
fail-closed (§4).

### 5.2 View `agent_api` mới: `WHERE tenant_id = portal.current_tenant()` là BẮT BUỘC

Migration `0005` đặt `ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api GRANT SELECT ON TABLES TO
agent_all`, nên **mọi view bạn thêm vào `agent_api` được cấp cho mọi agent, tự động**. Đó là chủ ý
(thêm view không phải sửa `create_agent_role()`), nhưng nó có nghĩa là **quyền không phải thứ chặn
bạn** — vị từ tenant trong chính view mới là thứ đó. Và vì view là definer, RLS **không** áp bên
trong nó.

Thiếu `WHERE` ⇒ agent của một workspace `SELECT` view đó và nhận về hàng của **mọi** workspace, không
có lỗi nào. Cổng 6 (`test_isolation_catalog.py::test_moi_view_agent_api_tu_loc_tenant`) quét
`pg_get_viewdef()` của mọi view `agent_api` và đỏ nếu không thấy `current_tenant` — nhưng đừng dựa
vào nó thay cho việc hiểu: cổng chỉ kiểm *có tham chiếu*, còn *lọc đúng cột* là việc của bạn.

### 5.3 `grant_agent_write()` mở luôn đường đọc TRỰC TIẾP — biết mà chọn

`control.grant_agent_write('tenant_data.<bảng>')` cấp `SELECT`, `INSERT`, `UPDATE` cho `agent_all`
**trên chính bảng gốc**. Nghĩa là với bảng đó, agent đọc thẳng bảng và **không đi qua gate cột
`agent_api`** — mọi cột của bảng đó agent thấy hết. Đây là **chủ ý** cho bảng write-back (agent ghi
thì phải đọc lại được cái nó vừa ghi, và một view definer read-only không làm được việc đó), nhưng
nó là một quyết định, không phải mặc định vô hại: đừng gọi hàm này cho bảng có cột thương mại nhạy
cảm. RLS vẫn áp trên bảng gốc, nên hàng thì vẫn chỉ của tenant đó — cái mất là gate **cột**.

Mỗi lần gọi hàm này, thêm tên bảng vào `AGENT_WRITABLE_TENANT_DATA_TABLES` trong
`tests/isolation/test_role_privileges.py` kèm lý do; nếu không, cổng 5 đỏ.

---

## 6. Bốn điều kiện — cả bốn hỏng ÂM THẦM

Đây là lý do phần này có 6 cổng test mà không được skip cái nào. Cả bốn điều kiện, nếu sai, **không
có triệu chứng nào**: app chạy bình thường, test một-tenant vẫn xanh, chỉ dữ liệu là rò.

| # | Điều kiện | Sai thì sao | Cổng |
|---|---|---|---|
| 1 | `FORCE ROW LEVEL SECURITY` trên mọi bảng `tenant_data` | Postgres **miễn RLS cho role sở hữu bảng**. Bỏ `FORCE` thì RLS bật cũng vô nghĩa với owner | 3 |
| 2 | `portal_migrator` (chỉ DDL) ≠ `portal_api` (runtime). Không role runtime nào `BYPASSRLS`, `SUPERUSER`, hay là owner bảng | Như trên — role phục vụ mà sở hữu bảng thì đi xuyên RLS | 5 |
| 3 | ~~Agent đọc qua `agent_api` view definer, zero privilege trên `tenant_data`~~ — **đảo ngược ở `0917`**: agent nay `SELECT` thẳng `tenant_data`, cách ly chỉ còn RLS FORCE | (không còn áp dụng — xem box đầu mục 5) | 1 · 2 |
| 4 | `SET LOCAL` trong giao dịch tường minh, không bao giờ `SET` trần | Rò qua connection pool (§4.1) | 4 |

### 6.0 Dữ liệu phạm vi-tenant KHÔNG được nằm ở schema `control`

Bảng của bạn có cột `tenant_id`? Nó thuộc **`tenant_data`**, và phải gọi
`control.enforce_tenant_isolation()`.

**Vì sao đây là luật, không phải sở thích sắp xếp:** schema `control` **không có RLS**, và migration
`0003` đặt

```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA control
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal_api;
```

nên `portal_api` có DML **trọn gói** trên mọi bảng `control` tạo về sau — kể cả bảng bạn thêm tuần
sau. Ghép hai điều đó: dữ liệu tenant đặt ở `control` được bảo vệ bởi **đúng không gì cả**. Không
policy, không `FORCE`, và cổng RLS thì chỉ quét `tenant_data` nên không đỏ. Một truy vấn quên `WHERE
tenant_id = ...` ở đó trả về hàng của mọi workspace, im lặng.

Ngoại lệ có, nhưng phải **tường minh**: `control.jobs` (worker đọc *trước khi* biết tenant nào, nên
không đặt dưới RLS được — bù lại handler chạy trong `tenant_conn()` và `enqueue()` suy tenant từ kết
nối), `control.agent_heartbeats` (có RLS riêng với hai policy theo role), `control.tenant_verticals`
và `control.field_policy_live` (cấu hình control-plane; `field_policy_live` **phải** ở ngoài RLS của
`tenant_data`, vì nó chính là cơ chế gate cột — đặt nó dưới RLS là gate tự chặn chính nó).

Danh sách ngoại lệ đó là một **allow-list đóng** trong
`tests/isolation/test_isolation_catalog.py::CONTROL_TABLES_DUOC_MANG_TENANT_ID`. Thêm bảng `control`
có `tenant_id` mà không khai ⇒ cổng 6 đỏ, kèm thông điệp nói rõ hai lựa chọn.

**Bốn bảng `tenant_data` mới của M4a** (migration `0400`) — khai ở đây để người đọc thấy toàn cảnh,
KHÔNG phải vì cổng 6 cần một allow-list cho `tenant_data` (cổng 6 quét **động** mọi bảng trong schema
đó, không cần khai riêng từng bảng). Đáng chú ý nhất là `import_jobs`: tên gần giống `control.jobs`
(một ngoại lệ ở trên) nhưng **không** đi theo lối đó — `report` của nó chứa mã căn và giá khách, tức
dữ liệu nghiệp vụ thật, nên nó ở `tenant_data` và được `enforce_tenant_isolation()`.

| Bảng | Module | Mô tả | Migration |
|---|---|---|---|
| `tenant_data.project_highlights` | M4a | điểm nhấn vị trí, 1-N theo `project_code` | `0400` |
| `tenant_data.project_progress`   | M4a | mốc tiến độ dự án, 1-N                    | `0400` |
| `tenant_data.project_documents`  | M4a | tài liệu dự án (chỉ link), 1-N            | `0400` |
| `tenant_data.import_jobs`        | M4a | phiếu import chờ xác nhận — `report` chứa mã căn và giá của khách, nên là dữ liệu nghiệp vụ | `0400` |

### 6.1 Sáu cổng test

| Cổng | Kiểm điều gì | File |
|---|---|---|
| 1 | Cross-tenant read = **0 hàng**. Role A `SELECT` view thấy 0 hàng của B | `test_rls_isolation.py` |
| 2 | Gate cột: `agent_readable=false` ⇒ cột về `NULL`, key `extras` bị lọc | `test_view_column_gate.py` |
| 3 | Chủ bảng **không** bypass RLS. **Bỏ `FORCE` đi ⇒ test phải đỏ** | `test_force_rls.py` |
| 4 | Rò qua pool: hai request khác tenant xen kẽ trên **cùng một pool**; request không `SET LOCAL` phải trả **0 hàng**, không kế thừa tenant trước | `test_pool_leak.py` |
| 5 | `portal_api` / `agent_*` không superuser, không `BYPASSRLS`, không owner bảng nào. Quét **động** mọi bảng `tenant_data`: agent zero quyền, trừ bảng khai trong `AGENT_WRITABLE_TENANT_DATA_TABLES` (rỗng ở M1 — mỗi module gọi `grant_agent_write()` tự thêm, §5.3) thì đúng `SELECT`/`INSERT`/`UPDATE` | `test_role_privileges.py` |
| 6 | **Catalog test**, hai phép quét (phép quét view `agent_api` đã bỏ cùng `0917`, không còn view nào để quét): mọi bảng `tenant_data` có RLS + FORCE + policy `tenant_isolation` · mọi bảng `control` mang `tenant_id` phải được khai báo (§6.0) | `test_isolation_catalog.py` |

Hai cổng nữa ở module khác, **cùng hạng bắt buộc**:

| Cổng | Kiểm | Module |
|---|---|---|
| 7 | **Kho tệp:** credential của workspace A `GET` một đường dẫn dưới `tenants/B/` phải bị **từ chối**. MinIO thật trong container ở test; production là **S3 + IAM policy** cùng cơ chế tiền tố (deploy/README.md §7.1) | M3 |
| 8 | **Knowledge:** query với `TenantContext` của A trả **0 chunk** của B | M6 |

> Cổng 7 không thay thế được bằng 6 cổng trên. Postgres **từ chối câu truy vấn** — sai tenant thì 0
> hàng, không lách được. Kho tệp chỉ kiểm *"khoá này có quyền vào tiền tố này không"*. Một lỗi ghép
> đường dẫn — `tenants/` cộng một biến bị nhầm — là workspace A đọc được bản ghi hội thoại của B. Và
> bản ghi hội thoại là **thứ nhạy cảm nhất trong hệ**: tên, số điện thoại, ngân sách, hoàn cảnh gia
> đình của khách hàng cuối.

---

## 7. Bảng ghi cheat sheet

**Làm:**

```python
async with tenant_conn(pool, tenant_id) as conn:      # ✅ txn + SET LOCAL
    await conn.fetch("SELECT ... FROM tenant_data.units")
```

```sql
SELECT control.enforce_tenant_isolation('tenant_data.bang_moi');   -- ✅ bảng mới
```

**Không làm:**

```python
await pool.fetch("SELECT ... FROM tenant_data.units")   # ❌ ngoài giao dịch → 0 hàng, hoặc tệ hơn
await conn.execute("SET app.tenant_id = $1", t)          # ❌ SET trần → rò qua pool
tenant_id = request.path_params["tenant_id"]             # ❌ tenant từ input client
```

```sql
CREATE VIEW agent_api.x WITH (security_invoker = true)   -- ❌ vô hiệu hoá gate cột
GRANT SELECT ON tenant_data.units TO agent_anphu;        -- ❌ agent không được chạm bảng gốc
ALTER TABLE tenant_data.units ADD COLUMN ...             -- ❌ nếu units không thuộc module bạn
```

---

## 8. Chỗ cố tình KHÔNG linh hoạt

`control.tenants.id` là **một khoá dùng cho bốn việc cùng lúc**:

| Vai | Chỗ dùng |
|---|---|
| Khoá cách ly hàng | policy RLS trên mọi bảng `tenant_data` |
| Danh tính runtime | biến `TENANT_ID` của container agent |
| Tiền tố kho tệp | `tenants/<id>/` |
| Phạm vi knowledge | tên collection Qdrant `kb_<id>` |

Đổi mô hình *1 khách = 1 workspace* → *1 khách = N workspace* là đổi **cả bốn cùng lúc** — đắt nhất
trong toàn bộ thiết kế. Rắn ở đây là có chủ đích.

**Hedge rẻ đã đặt sẵn:** cần nhiều workspace cho một khách thì thêm bảng `accounts` **phía trên**
`tenants` (một `account` sở hữu N `tenant`) — thay đổi *thêm vào*, không đánh lại khoá cách ly. Vì
vậy cột `plan` **không** được gắn vào `tenants`: hoá đơn không bao giờ gắn vào khoá cách ly.

## 9. Cái làm refactor về sau rẻ

| Cơ chế | Đổi tốn gì |
|---|---|
| Một chỗ duy nhất mỗi khái niệm: `portal.current_tenant()` · `control.enforce_tenant_isolation()` · `tenant_conn()` | Đổi cách xác định tenant = sửa **một hàm SQL** |
| Agent nói chuyện qua **view**, không qua bảng | Refactor bảng thoải mái — đổi tên cột, tách bảng, thêm index — miễn giữ view. Đây chính là lý do view tồn tại |
| Migration **SQL thuần**, mỗi file có header tiếng Việt giải thích *vì sao* | Đọc được, diff được, review được |
| **6 cổng test** | Thứ khiến refactor **dám làm**: sửa xong chạy test, vỡ thì biết ngay chỗ nào |

---

## 10. Cách ly ≠ phân quyền

Tài liệu này chỉ trả lời *"hàng này thuộc workspace nào"* và *"agent đọc được cột nào"*.

Nó **không** trả lời *"người này có được làm việc này không"* — đó là `docs/product/2026-07-29-pq01-phan-quyen.md`,
cưỡng chế ở tầng Portal API, sở hữu bởi M2. Hai cơ chế, đừng gộp.

Và: **quyền hỗ trợ của NobleX là một hàng `memberships` có `expires_at`**, không phải cờ `BYPASSRLS`
hay một nhánh kiểm tra riêng. Cờ bỏ qua tạo một đường code mà lời hứa *"NobleX không đọc được dữ
liệu workspace"* không áp dụng — và đường đó sớm muộn bị chạm nhầm.

---

## 11. ⚠️ Kho thứ tư — Redis của agent, CHƯA CÓ CƠ CHẾ

> **Phát hiện 2026-08-02, khi thiết kế M10.** Hợp đồng này khai **ba** kho (§2 + cổng 7 · 8). Có
> một kho thứ tư đang chạy mà chưa cơ chế nào phủ. Ghi ở đây để không ai đọc §2 rồi tưởng đã đủ.

`santa-hotline-agent` lưu trạng thái hội thoại vào Redis theo key:

```
session:<id>:meta · session:<id>:customer · session:<id>:state
```

(`tests/integration/unified/test_booking_flow.py:110-116` của repo agent). Nội dung là **tên, số
điện thoại, ngân sách, hoàn cảnh gia đình của khách hàng cuối** — đúng thứ mà §6.1 gọi là *"thứ nhạy
cảm nhất trong hệ"* khi giải thích vì sao cổng 7 tồn tại. Và `.env:357` trỏ tới một Redis **dùng
chung**.

**Key không mang `tenant_id`. Không cơ chế nào chặn hai tenant đọc key của nhau.**

Đây đúng loại rò mà §3 và §6.1 tồn tại để ngăn, chỉ là ở một kho mà tài liệu chưa biết tới. Nó
**không** liên quan tới Redis của portal (`sess:<id>`, hai trường `user_id`/`tenant_id`, xem
`auth.md`) — đó là kho khác, của tiến trình khác.

| | Luật đề xuất (chờ chốt) |
|---|---|
| **R01** | Redis ACL user theo tenant, key pattern cưỡng chế `~t:<tenant_id>:*`. Cưỡng chế ở **server Redis**, không ở kỷ luật code — cùng lý do chọn RLS thay vì filter tay (§3) |
| **R02** | Key prefix suy từ `tenant_id` bằng **một hàm duy nhất**, không nhận tham số nào khác — cùng khuôn với `ten_collection()` của M6 |
| **R03** | Credential Redis cấp qua `/runtime-credentials` của M10 (thêm khối `redis` vào response — cộng thêm, không phá hợp đồng) |
| **R04** | **Cổng 9:** client Redis của tenant A `GET` một key dưới `t:B:*` phải bị **từ chối**. Cùng hạng bắt buộc với cổng 7 · 8 |

**Không thuộc M10** — M10 chỉ cấp ba credential kia. Nhưng việc này **chặn đưa tenant thứ hai lên
production**, nên phải làm trước M7 (`conversations`). Chi tiết:
`docs/superpowers/specs/2026-08-02-m10-dau-noi-agent-ngoai-design.md` §8.
