# Portal thi công `analyze_projects` — SQL read-only cho agent (tool optional #13)

**Ngày:** 2026-09-07 · **Nguồn:** `docs/contracts/agent-analyze-projects-sql-ro-contract.md`
(agent, nhánh `sql-agent`, 2026-08-26) · **Tiền lệ cùng khuôn:**
`docs/contracts/agent-postgres-billing-write-contract.md` (billing, 2026-08-18).

## 0. ⚠️ CẢNH BÁO BẢO MẬT — CHƯA AN TOÀN ĐỂ BẬT CHO TENANT THẬT

**Phát hiện 2026-09-07, đo trực tiếp trên DB dev, KHÔNG phải suy đoán:**
`agent_sql_ro` — role được thiết kế để CHỈ đọc được 2 view đã lọc — thật ra vẫn
đọc được thẳng `tenant_data.contacts`, `conversations`, và bảng gốc
`projects`/`units` KHÔNG lọc `status='published'`. Test: `SET LOCAL ROLE
agent_anphu` → `SET LOCAL ROLE agent_sql_ro` → `SET TRANSACTION READ ONLY` →
`SELECT * FROM tenant_data.contacts LIMIT 1` chạy được (không `permission
denied`), khớp `\dp tenant_data.contacts` cho thấy `=r/portal_migrator` (PUBLIC
có SELECT).

**Nguyên nhân:** `tenant_data.*` có `GRANT SELECT ... TO PUBLIC` trên MỌI bảng
từ migration `0909` (di sản đã ghi trong CLAUDE.md: "Cách ly hoàn toàn dựa vào
RLS FORCE, không dựa vào GRANT"). PUBLIC trong Postgres = mọi role không trừ
ai — không có cách REVOKE riêng một role khỏi quyền đã cấp cho PUBLIC mà giữ
nguyên cho role khác. Vì vậy tạo `agent_sql_ro` "không grant gì thêm" (đúng như
bất biến §3/§4 yêu cầu) KHÔNG đạt được mục tiêu cô lập — nó vẫn thừa hưởng toàn
bộ quyền PUBLIC như mọi role khác trong cluster.

**Phía agent cũng tin nhầm điều này**: docstring `analytics.py:3-8` (đã đọc trực
tiếp) khẳng định "contacts/conversations/bảng gốc đều permission denied" — sai
trên DB thật. `sanitize_sql()` phía họ không parse/chặn tên bảng trong
FROM/JOIN, nên toàn bộ kỳ vọng an toàn đặt vào Postgres role, và role đó không
chặn được gì vì PUBLIC.

**Hậu quả nếu bật thật:** LLM sinh (vô tình hoặc bị injection) một câu SQL đọc
`contacts`/`conversations` sẽ lộ thông tin liên hệ/hội thoại của KHÁCH KHÁC
cùng tenant, và lộ dữ liệu dự án chưa published — có thể lọt thẳng vào câu trả
lời cho khách đang chat.

**Trạng thái hiện tại:** migration `0958` đã áp lên DB dev (2 view + 2 role tồn
tại thật), `tools.py`/`contracts/tools.json` đã có entry `analyze_projects` —
đường bật tool cho một tenant thật đã THÔNG kỹ thuật, kể cả lỗ hổng này. Theo
quyết định 2026-09-07: **KHÔNG sửa RLS trong đợt này** — việc này để lại thành
một task riêng, và **tool `analyze_projects` KHÔNG được bật cho bất kỳ tenant
thật nào cho tới khi lỗ hổng này đóng**, bất kể catalog UI đã có entry.

**Hướng sửa đề xuất cho task sau** (không làm ở đây): thêm RESTRICTIVE RLS
policy dạng `USING (current_user <> 'agent_sql_ro')` FORCE trên các bảng nhạy
cảm của `tenant_data` — restrictive policy AND với policy permissive
`tenant_isolation` sẵn có, nên khi `current_user = agent_sql_ro` mọi hàng biến
mất mà không đụng GRANT/PUBLIC của bất kỳ role nào khác. Khớp đúng triết lý
"RLS là ranh giới, không phải GRANT" hệ thống đang theo. Cần rà soát áp dụng
cho TOÀN BỘ bảng `tenant_data` (không chỉ contacts/conversations) để chặn cả
`projects`/`units` phiên bản chưa lọc.

## 1. Bối cảnh

Agent thêm tool `analyze_projects`: LLM viết MỘT câu SQL `SELECT` tự do để trả lời
câu hỏi thống kê/tổng hợp trên dữ liệu dự án/căn. Vì SQL do LLM sinh là input không
đáng tin, contract khoá bằng 3 lớp Postgres độc lập (transaction read-only, role
túi quyền chỉ `SELECT` trên 2 view đã lọc sẵn, RLS theo tenant). Phân vai đúng khuôn
billing: **agent viết sẵn DDL, Portal thực thi bằng `portal_migrator`.**

Đã verify DDL của contract khớp schema thật trước khi viết spec này:

- Cột 2 view (`agent_projects_v`/`agent_units_v`) khớp đúng tên cột thật của
  `tenant_data.projects`/`units` (`migrations/versions/0400_kb_real_estate.py:135-283`).
- RLS `tenant_isolation` đã có sẵn trên cả 2 bảng từ `0400` (dòng 166, 283, qua
  `control.enforce_tenant_isolation(...)`) — 2 view mới không cần Portal dựng gì
  thêm cho phần cách ly, chỉ cần giữ đúng invariant owner ở §3 dưới.

⚠️ **Hai chỗ contract dùng sai tên (agent tự sửa, không chặn spec này):** policy
RLS thật tên `tenant_isolation` (không phải `agent_runtime` — đó là một policy
BUG vừa bị `migrations/versions/0956_dong_bo_lai_rls_tenant_data.py` xoá), GUC
thật là `app.tenant_id` (không phải `app.current_tenant`). Không ảnh hưởng migration
Portal chạy — các tên sai đó chỉ nằm trong prose/comment/checklist verify của
contract, không nằm trong DDL executable.

⚠️ **Một điểm CHƯA chốt, không phải lỗi chính tả — nằm NGOÀI phạm vi Portal có
thể tự đóng:** contract §3 nói agent đọc `skills` qua view
`tenant_data.agent_published_config`. View đó (thật ra từng ở schema `agent_api`,
chưa bao giờ ở `tenant_data`) đã bị xoá cùng cả schema `agent_api` ở migration
`0917_bo_agent_api.py` (2026-08-10). Đường đọc config publish hiện nay là agent tự
poll object `LIVE` (bundle.md) trên kho tệp, không qua Postgres nữa. Spec này chỉ
đảm bảo phần Portal chắc chắn đúng (bump `version` khi publish — giống mọi thay đổi
config khác); việc "agent có thật sự đọc được `skills` mới hay không" cần bên agent
xác nhận riêng, xem mục 6.

## 2. Việc làm — 3 phần độc lập

### 2.1 Migration DDL (2 view + 2 role + grant)

File mới `migrations/versions/0958_analyze_projects_sql_ro.py`,
`down_revision = "0957_hop_nhat_hai_head"` (HEAD hiện tại, xác nhận bằng
`alembic heads` — repo đã tiến xa hơn `0956` một mergepoint).

Nội dung lấy nguyên từ contract §1.1, **bỏ `BEGIN;`/`COMMIT;`** — Alembic tự quản
lý transaction quanh `op.execute()`; giữ lại sẽ đóng sớm transaction của Alembic và
làm hỏng bước ghi `alembic_version`. Giữ nguyên toàn bộ guard idempotent (`DO $$ IF
NOT EXISTS ... CREATE ROLE`, `CREATE OR REPLACE VIEW`) đúng quy ước "migration
chạy-lại-được" của repo.

**Membership — ĐƠN GIẢN HƠN contract §1.2, không dùng vòng lặp backfill:**
`GRANT agent_sql_ro TO agent_all;` một dòng duy nhất. `agent_all` (NOLOGIN,
`0003_role_and_isolation_helper.py:45`) là role nhóm mà MỌI `agent_<tenant_id>`
đã là thành viên sẵn (`create_agent_role()` luôn `GRANT agent_all TO %I` lúc tạo
role) — Postgres cho `SET ROLE` bắc cầu qua chuỗi membership theo mặc định, nên
một dòng grant này phủ cả tenant hiện có LẪN tenant tạo sau này, không cần vòng
lặp quét `pg_roles` và không cần đụng `control.create_agent_role()` (hàm
`SECURITY DEFINER`, càng ít sửa càng tốt). Đúng khuôn quy ước đã ghi sẵn trong
comment của chính `create_agent_role()` (`0911:102-104`): "Toàn bộ quyền đến từ
nhóm... thêm view hay bảng mới thì grant cho `agent_all`, không sửa đây."

Dòng `GRANT agent_sql_ro TO portal_api` (dự phòng, theo yêu cầu riêng của bên
agent dù Portal không dùng `portal_api` làm đường phục vụ agent) vẫn giữ, ghi chú
rõ trong migration đây là theo yêu cầu contract chứ không phải quyền Portal tự
thêm.

`downgrade()`: theo contract §7 — `DROP VIEW` 2 view, `DROP ROLE` 2 role (an toàn,
toàn bộ là object phái sinh, không mất dữ liệu nghiệp vụ).

Không cần khai báo gì thêm ở 2 cổng cách ly tenant hiện có
(`tests/isolation/test_isolation_catalog.py`,
`tests/isolation/test_loc_tenant_o_tang_app.py`) — đã đọc code xác nhận: cả hai chỉ
quét bảng thật (`relkind IN ('r','p')` trong `pg_class`) và AST của `src/portal`
(Portal không viết code Python nào query 2 view mới — agent tự query qua
`SET LOCAL ROLE agent_sql_ro`, ngoài tầm cổng AST đó).

### 2.2 Provision tenant mới — KHÔNG cần đổi gì

Vì §2.1 grant thẳng `agent_sql_ro TO agent_all`, và `control.create_agent_role()`
(`0911:90-107`) đã tự động `GRANT agent_all TO %I` cho mọi tenant mới, phần "thay
đổi vĩnh viễn trong flow provision tenant" mà contract §2 yêu cầu **coi như đã
xong ngay khi §2.1 chạy** — không cần sửa `control.create_agent_role()`, không
downgrade/upgrade lại `0911`, không thêm mã nào vào flow provision của
`enrollment/service.py::cap_phat()` hay `ha_tang.py`. Đây là điểm khác biệt lớn
nhất so với văn bản contract (viết cho một model "mỗi tenant role phải được nối
quyền riêng"), nhưng đạt đúng yêu cầu chức năng của họ (§2 contract): "tenant mới
tạo tự động có qua `agent_sql_ro`" — bằng con đường module hoá qua nhóm sẵn có
thay vì đụng vào code provision.

### 2.3 Catalog tool UI (`skills`)

`src/portal/modules/config/tools.py`: thêm 1 phần tử vào cuối tuple
`MUOI_HAI_KY_NANG` (dòng 32-55, đúng khuôn `KyNang(ten, nhan, mo_ta)`):

```python
KyNang(
    "analyze_projects", "Thống kê / so sánh dự án (SQL)",
    "<mô tả 1 dòng — cần thống nhất câu chữ với bên agent, xem mục 6>",
),
```

Không thêm vào `PHU_THUOC` (dòng 59-66) — contract không khai tool này phụ thuộc
tool khác. Chạy `make contracts` sau khi sửa → sinh lại `contracts/tools.json`,
copy tay sang `odyssey-portal-frontend` (không job CI so hai bên — quên bước này
thì `tests/api/test_contracts.py` đỏ). UI hiện tool này y hệt 12 tool hiện có,
không cần code riêng.

⚠️ Tên hằng `MUOI_HAI_KY_NANG` ("mười hai kỹ năng") lệch nghĩa sau khi thêm phần
tử thứ 13 — chỉ ghi chú lại, không tự ý đổi tên hằng trong spec này (đổi tên là
việc riêng, không ảnh hưởng hành vi).

## 3. Bất biến giữ nguyên (đổi là thủng khoá — copy từ contract §4, đã sửa một
dòng cho khớp cơ chế RLS thật)

| Bất biến | Vì sao |
|---|---|
| View giữ nguyên filter `status='published'` (cả units LẪN project cha) | Khoá chống lộ draft/archived — LLM không tự lọc được |
| View KHÔNG thêm cột `tenant_id`, text dài (`overview`, `body`...) | Chống lộ nội bộ + chống `SELECT *` nổ context |
| KHÔNG set `security_invoker = true` trên 2 view | Invoker semantics bắt role truy vấn có SELECT trên bảng gốc → phá cô lập |
| `agent_kb_view_owner` giữ `NOBYPASSRLS`, không owner bảng gốc | Owner bypass RLS là mất ranh giới tenant xuyên view |
| `agent_sql_ro` giữ `NOLOGIN`, CHỈ `SELECT` trên 2 view, KHÔNG grant gì thêm | Túi quyền tối thiểu; thêm bảng nào là LLM đọc được bảng đó |
| Tên 2 role không trùng bất kỳ `tenant_id` nào | `portal.current_tenant()` ưu tiên khớp `session_user` theo mẫu `agent_<tenant>` — trùng tên là khớp nhầm |
| Thêm cột vào `projects`/`units` KHÔNG tự lộ ra tool | View là allowlist cột; muốn expose thì sửa view + báo agent cập nhật schema description |

## 4. Test

- `tests/integration/tenant/test_analyze_sql_live.py` — VIẾT XONG (2026-09-07),
  6 bài: 4 pass thật (membership qua `agent_all` · view lọc published + không lộ
  `tenant_id` · `READ ONLY` chặn DML giấu trong CTE · `SET LOCAL ROLE` tự hết
  hiệu lực ngoài transaction) + 2 bài `xfail(strict=True)` ghi lại đúng lỗ hổng
  §0 (`contacts` và bảng gốc chưa lọc vẫn đọc được) — XPASS sẽ làm CI đỏ, bắt
  buộc gỡ `xfail` khi ai đó đóng lỗ hổng thật. Dùng đúng GUC/role thật của Portal
  (`agent_<tenant>` → `SET LOCAL ROLE agent_sql_ro`), không copy tên sai từ
  contract.
- Migration idempotent: `alembic upgrade head` 2 lần liên tiếp trên DB dev, không
  lỗi (guard `IF NOT EXISTS`/`CREATE OR REPLACE` phải thật sự vô hại khi chạy lại).
- Round-trip `upgrade → downgrade → upgrade` trên DB dev — xác nhận downgrade
  không xoá nhầm gì ngoài 2 view + 2 role + khôi phục đúng bản cũ của
  `create_agent_role`.
- `make check` toàn repo trước khi coi là xong. Baseline hiện có 2 dòng đỏ đã biết
  (`test_heartbeat.py`, RLS thiếu trên `agent_heartbeats`) — không liên quan việc
  này, không cần sửa cùng đợt.

## 5. Rollback

- Tắt tính năng: gỡ `"analyze_projects"` khỏi `skills` của tenant, publish lại —
  không đụng DB objects.
- Gỡ hẳn: `alembic downgrade` migration `0958` (drop 2 view, 2 role, khôi phục hàm
  `create_agent_role` về bản `0911`).

## 6. Việc CHƯA chốt — cần bên agent xác nhận trước khi Portal merge

1. Cơ chế đọc `skills`/`OPTIONAL_TOOLS` thật của agent (không còn qua view Postgres
   nào phía Portal) — họ cần sửa lại mô tả ở contract §3 cho khớp thực tế, và xác
   nhận việc bump `version` của `tenant_data.agent_config` là đủ để agent thấy tool
   mới bật, qua đúng đường bundle.md hiện hành.
2. Câu chữ mô tả 1 dòng cho `KyNang` mới (§2.3) — nếu câu này lọt vào system
   prompt/schema description mà LLM đọc, cần bên agent duyệt nội dung.
3. ~~Ai viết `tests/integration/tenant/test_analyze_sql_live.py`~~ — Portal đã viết
   (mục 4). Bên agent có thể vẫn muốn một bộ test riêng cho executor của họ
   (`sanitize_sql`, vocab cache) — đó là việc của họ, không trùng phạm vi bài này.
4. **CHẶN SHIP** — đóng lỗ hổng PUBLIC-grant ở §0 trước khi bật tool cho bất kỳ
   tenant thật nào. Việc này KHÔNG nằm trong phạm vi migration `0958` (quyết định
   2026-09-07) — cần một task/migration riêng, và rất có thể cần phối hợp với
   bên agent (họ cũng cần biết claim "permission denied" trong `analytics.py`
   là sai, phòng khi họ dựa vào đó để bỏ qua việc parse SQL ở tầng app).
