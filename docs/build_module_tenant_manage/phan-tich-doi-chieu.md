# Phân tích: tạo mới tenant — đối chiếu spec.md với code hiện tại

> Đọc trước khi bắt tay vào `spec.md`. Kết luận ngắn: **spec.md không phải tài liệu
> để implement nguyên bản.** Nó được viết như thể portal chưa có gì, nhưng ~80% nội
> dung nó đặc tả thì repo này đã có rồi (module `config`, `enrollment`), và §7 của nó
> **xung đột trực tiếp với một CHECK constraint đang chạy**.
> Cái đang thật sự thiếu chỉ là **một endpoint tạo workspace**.

---

## 1. Cái đang thiếu — đúng như bạn nói

Không có endpoint nào tạo tenant. `INSERT INTO control.tenants` chỉ xuất hiện ở
`scripts/dev_seed.py:94` và trong tests. Router hiện có:

| Module | Prefix | Có gì |
|---|---|---|
| `auth` | — | login/logout, `/me`, `POST /me/workspace` (đổi ws), `/users`, `/members`, `/invites` |
| `config` | `/config` | `GET·PUT /draft`, `POST /preview`, `GET /status`, `POST /publish`, `GET /versions`, `POST /versions/{v}/rollback` |
| `enrollment` | `/agent` | cấp phát deployment, phát/thu khoá, bootstrap, xoay bí mật |
| `kb`, `realestate` | — | dữ liệu |

⇒ Thiếu đúng một thứ: `POST /workspaces`. Mọi thứ nó cần gọi thì đã tồn tại.

## 2. Cái spec.md đặc tả mà ĐÃ CÓ RỒI — đừng build lại

| spec.md nói Portal phải làm | Thực tế trong repo |
|---|---|
| §3 Form provider điền | `ConfigPayload` ở `modules/config/contracts.py` — FE dựng form từ `contracts/openapi.json` |
| §4 Cấu trúc `config` jsonb | `ConfigPayload` (`schema_version = 2`), `extra="forbid"` mọi tầng |
| §5 Bảng versioned + draft/publish/rollback | `control.config_drafts` + `control.config_versions` (migration 0200). Bất biến cưỡng chế bằng `REVOKE UPDATE, DELETE` |
| §5 con trỏ `published` | Con trỏ `LIVE` **trên MinIO** (một `PUT` = atomic), không phải bảng. `service.doc_version_dang_live()` |
| §6 Validate trước publish | Pydantic + `tools.thieu_phu_thuoc()` (validate phụ thuộc kỹ năng, ở BE chứ không chỉ FE) |
| §9 Danh mục tool | `modules/config/tools.py` — `MUOI_HAI_KY_NANG` + `PHU_THUOC` |
| §10 Placeholder & marker | `bundle.render()` — sinh `SOUL.md`/`RULES.md`/`PROMPT_TEMPLATE.md`/`CUSTOMER_PROFILE.md`/`manifest.toml`. Danh mục kỹ năng **sinh từ `tools.enabled`**, không strip marker |
| "tenant mới phải có config để đọc" | `payload_mac_dinh(ten_workspace)` — trả bộ mặc định dùng được ngay, brand lấy từ tên workspace |
| Provisioning hạ tầng | `enrollment.cap_phat()` + `HaTang` + `control.create_agent_role()` |
| Trạng thái workspace | `core/tenant_status.derive_tenant_status()` — provisioning/ready/disconnected/publishing |

## 3. Ba chỗ spec.md SAI hoặc lệch kiến trúc

### 3.1. §7 `tenant_id` — xung đột với constraint đang chạy ⚠️ NGHIÊM TRỌNG

Spec đề xuất `tenant_id = org_1d9f1a2f_demo-sales`. Nhưng migration 0002:

```sql
CONSTRAINT tenants_id_check CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$')
```

- Không cho dấu `-` → `demo-sales` bị chặn.
- Tối đa 31 ký tự; spec cho slug tới 40 ký tự + tiền tố `org_xxxxxxxx_` (13) → tới 53.
- `org_id` cũng dùng đúng regex đó (0102 `_ID_CHECK`) — org mặc định hiện tại là `noble`, không phải `org_<hex8>`.

Và đây không phải một constraint cosmetic. `tenants.id` đi thẳng vào **bốn** chỗ:
policy RLS · `TENANT_ID` của pod · đường dẫn `tenants/<id>/` trên MinIO · collection
`kb_<id>`. Cùng biểu thức đó lại được dùng lần nữa trong `control.create_agent_role()`
để `CREATE ROLE agent_<id>` — 0002 ghi rõ nới lỏng nó là mở một đường SQL injection.

**Khuyến nghị: bỏ §7, giữ format hiện tại.** Slug dùng `_` thay `-`, cắt 30 ký tự.
Và **không nhúng `org_id` vào `tenant_id`**: mẹo "tách 2 segment đầu để suy ra org"
của spec chỉ đáng giá khi hệ thống không có bảng org — bạn đã có
`control.organizations` + `tenants.org_id` NOT NULL + `UNIQUE (org_id, id)`. Nhúng
vào chỉ tạo nguồn sự thật thứ hai cho cùng một quan hệ.

### 3.2. §5 đề xuất bảng mới `agent_config_versions` + `agent_config_pointer`

Trùng nghĩa 1-1 với `config_versions` + `config_drafts` đã có. Tạo thêm là hai
nguồn sự thật cho cấu hình agent. **Bỏ toàn bộ §5.1.**

Khác biệt thật duy nhất đáng bàn: spec muốn con trỏ published là **một hàng Postgres**,
hiện tại nó là **một object trên MinIO**. Đây là quyết định độc lập với việc tạo
tenant — nếu muốn đổi thì đổi riêng, có lý do riêng.

### 3.3. §5.3 + §8 — agent đọc trực tiếp Postgres, retire MinIO

> ⚠️ Câu này ở bản trước dễ gây hiểu nhầm. Nói cho rõ: **agent CÓ đọc trực tiếp Postgres**
> — đó là thiết kế trung tâm của hệ. Xem §7 bên dưới để hiểu cơ chế.
> Chỗ khác biệt hẹp hơn nhiều: **cấu hình/persona** thì agent đọc từ MinIO, không từ Postgres.

Spec muốn agent `SELECT config FROM agent_published_config` dưới RLS. Ba vấn đề:

1. **Công thức RLS của spec sai với codebase này.** Spec đề policy dựa vào
   `current_setting('app.current_tenant')`. Nhưng danh tính tenant của agent ở đây đến từ
   **tên role** (`session_user` = `agent_<tenant_id>`), không từ GUC — và thứ tự
   `coalesce` trong `portal.current_tenant()` **cố ý** đặt tên role TRƯỚC GUC, vì nếu đảo
   lại thì một kết nối agent có GUC bị đặt sẽ leo thang sang tenant khác. Spec đang mô tả
   nửa dưới của một cơ chế mà nửa trên đã được thiết kế khác.
2. **Không cần RLS.** Nếu muốn agent đọc config từ Postgres thì cách khớp với hệ hiện tại
   là **thêm một view DEFINER trong schema `agent_api`** tự lọc `WHERE tenant_id =
   portal.current_tenant()` — đúng khuôn mẫu của 5 view đang chạy. Không cần RLS, không
   cần GUC, không cần đụng vào quyết định "ba bảng config cố ý không dưới RLS" của 0200.
3. **§8 là chuyện khác hẳn** — xem §8 của tài liệu này.

**Tách hẳn ra, đừng gộp vào việc tạo tenant.**

### 3.4. §4 config shape — lệch, và bản hiện tại giàu hơn

| spec.md | Hiện tại | Nhận xét |
|---|---|---|
| `identity.honorific_self` + `honorific_customer` (2 field) | `danh_tinh.xung_ho` = `"em ↔ anh/chị"` (1 chuỗi) | Tách 2 field thì FE dễ hơn — thay đổi hợp lý nhưng phải bump `SCHEMA_VERSION` lên 3 |
| `scope.handoff_department` (1 chuỗi) | `pham_vi.phong_ban: list[PhongBan]` (min 1, max 8, có `khi_nao`) | **Hiện tại giàu hơn.** Đừng hạ cấp |
| — | `giong.giong_dieu` + `giong.do_dai` (3 preset đóng) | Spec **thiếu** |
| `tools.feng_shui`, `tools.media_channel` | chưa có | Chưa có. Thêm được, nhưng xem lại: `PHU_THUOC` đã là cơ chế tổng quát hơn cho "A cần B" |
| `enabled` không chứa 4 core, agent tự union | `TEN_KY_NANG` = 12 kỹ năng, `enabled` min_length=1 | Khác mô hình. Cân nhắc kỹ: "agent luôn tự union 4 core" là van an toàn tốt |
| `data_source: "pg_kb"` | không có | Spec tự nhận là field chết. Bỏ |

Mỗi lần đổi shape là **bump `SCHEMA_VERSION_HIEN_TAI`**, không sửa tại chỗ — các hàng
`config_versions` bất biến, một hàng v2 phải đọc được mãi mãi.

## 4. Nghiệp vụ THẬT khi tạo tenant (rút từ code, không từ spec)

Một transaction, theo thứ tự:

1. **Authz** — ai được tạo? `users.org_role = 'owner'` (quyền TRÊN tổ chức) hay platform
   admin (`require_quan_tri_nen_tang()`, token header)? → **cần bạn quyết**.
2. **Mint id** — slug tên → `^[a-z][a-z0-9_]{1,30}$`. Trùng trong org ⇒ 409, chặn ở form.
3. `INSERT control.tenants (id, name, org_id, lifecycle='active')`.
4. ~~`INSERT control.memberships (…, role='admin')` cho người tạo~~ → **SAI, không cần.**
   Đã xác minh ở `core/auth/repo.py` (`doc_quyen`): `org_role='owner'` + tenant cùng org
   ⇒ đủ 13 action **không cần hàng membership nào** (`cung_to_chuc` chỉ kiểm
   `tenants.org_id = users.org_id`). `LEFT JOIN memberships` được giữ có chủ đích cho
   đúng trường hợp này. Ngoài ra 0104 đã **xoá cột `memberships.role`**, thay bằng
   `role_id` FK sang `control.roles` — nên câu INSERT ở trên còn sai cả tên cột.
5. `INSERT control.tenant_verticals (tenant_id, 'realestate')` — ⚠️ hiện **không dòng code
   nào** ghi bảng này (`grep` sạch). Bảng có từ 0002 nhưng chưa ai dùng. Cần xác định:
   dùng thật hay bỏ?
6. **Config draft mặc định** — `payload_mac_dinh(ten_ws)` rồi `repo.ghi_ban_nhap()`.
   Tùy chọn, vì `GET /config/draft` đã tự trả bộ mặc định khi chưa có draft.
7. **Provisioning hạ tầng** — `enrollment.cap_phat()`: role Postgres `agent_<id>` + khoá MinIO
   + deployment. **Nằm ngoài transaction DB** — đây là chỗ phức tạp thật (xem §5).
8. ~~`field_policy_live` — seed 56 hàng gate cột~~ → **KHÔNG cần.** Cơ chế gate cột đã bị
   khai tử ở `0400_kb_real_estate` (drop view cũ) + `0401_agent_doc_kb` (dựng lại 5 view
   **không** gọi `pol()`). Bảng `control.field_policy_live` vẫn tồn tại nhưng là **bảng
   chết** — không code nào ghi, không view nào đọc. `docs/contracts/dau-noi-agent.md` G-6
   nói thẳng: *"Ba cột `commission`·`bank_support`·`csbh_full` và cơ chế `field_policy_live`
   đã bị xoá khỏi hệ, đừng tìm chúng."* Tạo tenant **không phải seed gì** cho bảng này.
9. **Audit log** — `nhat_ky.ghi(pool, tenant_id, "tenant.tao", boi, {...})`.
10. **Publish v1** — tùy chọn. `derive_tenant_status` trả `provisioning` khi chưa có
    heartbeat và coi đó là **bình thường**, nên không publish ngay cũng không sao.

## 5. Có quá phức tạp không?

**Bản thân việc tạo tenant: không.** Bước 1–4 + 9 là một endpoint, một transaction,
khoảng 80 dòng + tests. Toàn bộ form/config/validate/publish đã có sẵn.

**Chỗ phức tạp duy nhất là bước 7:** `CREATE ROLE` Postgres và khoá MinIO **không rollback
được cùng transaction DB**. Ba lựa chọn:

| Cách | Đánh giá |
|---|---|
| **A. Tách hai bước** — tạo tenant xong ở `lifecycle='active'`, provisioning là hành động riêng (đã có `POST /agent/...`) | ✅ **Khuyến nghị.** Khớp đúng thiết kế đang có: `derive_tenant_status` đã có state `provisioning`, `HaTang.thieu_gi()` đã biết báo còn thiếu gì, `cap_phat` đã ghi "hỏng thì admin bấm lại là xong" |
| B. Một endpoint làm hết, best-effort | Tenant nửa vời khi lỗi giữa chừng, không ai biết đang thiếu gì |
| C. Một endpoint + job nền có retry | Đúng nhất về lý thuyết, nhưng thêm một job kind mới cho vấn đề mà cách A đã giải |

## 6. Việc cần chốt trước khi viết plan

1. **Ai được tạo workspace** — org owner, hay chỉ platform admin?
2. **Provisioning tách rời hay gộp** (khuyến nghị: tách — cách A).
3. **`tenant_verticals` và `field_policy_live`** — có seed lúc tạo tenant không? Hai bảng
   này hiện không có code nào ghi vào.
4. **Có đổi `ConfigPayload` theo §4 không** — nếu có thì bump schema_version 3, và đó là
   một việc riêng, không phải phần của "tạo tenant".

---

## 7. Giải thích: agent đọc dữ liệu thế nào, và `agent_api` là gì

### 7.1. Có, agent đọc trực tiếp Postgres — đó là thiết kế trung tâm

Agent **không** gọi REST API của portal để lấy dữ liệu. Nó **nối thẳng vào Postgres** bằng
DSN riêng của mình. Bốn kho nó chạm tới:

| Kho | Nội dung | Cách ly cưỡng chế bằng |
|---|---|---|
| **Postgres** | dữ liệu nghiệp vụ: dự án, căn, tài liệu, media | role riêng + view DEFINER (§7.2) |
| **Qdrant** | vector cho `kb_search` | collection riêng `kb_<tenant_id>` |
| **Kho tệp (MinIO)** | bundle persona + tệp media | policy tiền tố `tenants/<id>/` |
| **Redis** | trạng thái hội thoại | ⚠️ **chưa có gì** — `dau-noi-agent.md` §5 cảnh báo |

Credential của cả bốn: pod chỉ giữ `PORTAL_URL` + `AGENT_API_KEY`, gọi
`POST /agent/bootstrap` một lần rồi nhận về `postgres_dsn`, `kb.collection`,
`storage.prefix`. Nguyên tắc trong hợp đồng: *"api_key nói **tôi là ai**; credential nói
**tôi được làm gì**. Không gộp hai vai."*

### 7.2. `agent_api` là gì — bốn lớp, đọc từ dưới lên

**Lớp 1 — ba schema, ba hạng dữ liệu.**

| Schema | Chứa gì | Agent có quyền gì |
|---|---|---|
| `control` | control-plane: `tenants`, `users`, `memberships`, `config_versions`… | **không gì**, trừ `INSERT`/`UPDATE` trên `agent_heartbeats` |
| `tenant_data` | dữ liệu nghiệp vụ thật: `projects`, `units`, `zones`… | **ZERO quyền** |
| `agent_api` | **chỉ chứa view** | `SELECT` — và đây là **cửa duy nhất** |

**Lớp 2 — danh tính tenant nằm trong TÊN ROLE, không phải tham số.**

Mỗi tenant có một role Postgres riêng: `agent_<tenant_id>`, sinh bởi
`control.create_agent_role()` lúc provisioning. Tenant được suy ra từ chính danh tính
kết nối:

```sql
CREATE FUNCTION portal.current_tenant() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        substring(session_user::text from '^agent_(.+)$'),  -- pod agent
        nullif(current_setting('app.tenant_id', true), '')  -- portal API
    )
$$
```

Đây là chỗ then chốt: **agent không thể khai mình là tenant khác.** Nó không truyền
`tenant_id` vào đâu cả — Postgres tự biết, từ role đã đăng nhập. Đổi `session_user` cần
`SET SESSION AUTHORIZATION`, mà cái đó cần superuser.

Hai nguồn vì hai bản chất khác nhau: pod agent phục vụ **đúng một** tenant suốt đời tiến
trình (⇒ thuộc tính của *danh tính kết nối*); portal API phục vụ **mọi** tenant, đổi theo
từng request (⇒ thuộc tính của *đơn vị công việc*, đặt bằng `SET LOCAL app.tenant_id`).
Và thứ tự `coalesce` là một quyết định an ninh: nguồn **không đổi được** (tên role) đứng
TRƯỚC nguồn **đổi được** (GUC). Đảo lại thì một kết nối agent có GUC bị đặt sẽ leo thang
sang tenant khác. Trả `NULL` khi không xác định được ⇒ mọi `tenant_id = NULL` ra false ⇒
0 hàng. **Hỏng thì trả rỗng, không trả nhầm của người khác.**

**Lớp 3 — view là SECURITY DEFINER, và đó là toàn bộ điểm mấu chốt.**

```sql
CREATE VIEW agent_api.units AS
SELECT u.code, u.project_code, u.unit_type, u.status, ...
  FROM tenant_data.units u
 WHERE u.tenant_id = portal.current_tenant();   -- ← view TỰ lọc
```

Vì sao DEFINER (mặc định) chứ không `security_invoker = true`: `security_invoker` bắt
Postgres kiểm quyền của **người gọi** trên bảng gốc ⇒ agent phải được `GRANT SELECT ON
tenant_data.units` ⇒ **có quyền đó là nó query thẳng bảng gốc**, bỏ qua view luôn.

Với DEFINER thì view chạy bằng quyền của owner, nên agent cần **zero quyền** trên
`tenant_data`. Câu trong migration 0005: *"Không vào được cửa" mạnh hơn "được vào nhưng
bị lọc hàng".*

Hai hệ quả phải xử lý tường minh:
- View chạy bằng quyền owner ⇒ RLS **không** áp cho nó ⇒ **view phải tự có `WHERE`**.
  Thiếu `WHERE` là rò hết, và **không có lỗi nào báo**.
- Phải dùng `session_user`, **không** phải `current_user` — trong view DEFINER thì
  `current_user` trả về *owner của view*, không phải role đang gọi.

**Lớp 4 — quyền cấp cho role NHÓM, một lần.**

`agent_all` là role nhóm NOLOGIN; mọi `agent_<tenant>` là thành viên. Toàn bộ grant cấp
cho nhóm, cộng thêm `ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api GRANT SELECT ... TO
agent_all` ⇒ view thêm về sau tự động được cấp. Nhờ vậy `create_agent_role()` chỉ còn
hai dòng (`CREATE ROLE` + `GRANT agent_all`), không có danh sách grant nào phải nhớ
cập nhật.

### 7.2b. Bề mặt quyền ĐẦY ĐỦ của agent trên Postgres

Toàn bộ quyền cấp cho role nhóm `agent_all`, không sót dòng nào:

| Quyền | Cấp ở | Nghĩa |
|---|---|---|
| `USAGE ON SCHEMA agent_api, portal` | 0005 | vào được hai schema đó |
| `SELECT ON ALL TABLES IN SCHEMA agent_api` + `ALTER DEFAULT PRIVILEGES … GRANT SELECT` | 0005 | 5 view hiện có, **và mọi view thêm về sau tự động** |
| `EXECUTE` trên `portal.current_tenant()`, `portal.pol()`, `portal.gated_extras()` | 0005 | ba hàm view gọi tới |
| `USAGE ON SCHEMA control` | 0007 | **chỉ USAGE** — không kèm `SELECT` trên bảng nào |
| `SELECT, INSERT, UPDATE ON control.agent_heartbeats` | 0007 | ⬅️ **ngoại lệ duy nhất ngoài `agent_api`** |

**Ngoại lệ `agent_heartbeats`** được canh bằng RLS thay vì bằng view, vì đây là chiều
**ghi** (agent báo nhịp tim + version đang chạy) mà view không làm được:

```sql
ALTER TABLE control.agent_heartbeats ENABLE ROW LEVEL SECURITY;
CREATE POLICY hb_agent_own_tenant ON control.agent_heartbeats
    TO agent_all
    USING      (tenant_id = portal.current_tenant())
    WITH CHECK (tenant_id = portal.current_tenant());
CREATE POLICY hb_portal_all ON control.agent_heartbeats  -- portal_api đọc hết
    USING (true) WITH CHECK (true);
```

**Agent có ZERO quyền trên:** toàn bộ `tenant_data.*` · và mọi bảng `control` còn lại —
`tenants`, `users`, `memberships`, `config_drafts`, `config_versions`, `deployments`,
`jobs`, `agent_keys`, `agent_credentials`, `field_policy_live`. Riêng hai bảng khoá,
0900 ghi rõ lý do: *"VÌ SAO KHÔNG CẤP QUYỀN CHO `agent_all`: pod đã nhận credential của
nó qua bootstrap"* — agent không đọc được kho khoá, kể cả khoá của chính nó.

**Đường ghi `tenant_data` để dành sẵn nhưng chưa mở:** `control.grant_agent_write()`
(0005) — hàm này chỉ nhận bảng thuộc `tenant_data`, `RAISE EXCEPTION` với schema khác.
Dành cho `contacts`/`conversations`/`appointments` của M7. **Chưa migration nào gọi nó.**

**Có cổng CI canh, không phải chỉ nội quy:** `tests/isolation/test_isolation_catalog.py`
quét ba seam — bảng `tenant_data` thiếu RLS/FORCE/policy · **view `agent_api` thiếu vị từ
tenant** · bảng `control` mang cột `tenant_id` mà không khai báo trong danh sách đóng
`CONTROL_TABLES_DUOC_MANG_TENANT_ID`. Cả ba hỏng theo cùng một kiểu: **không triệu chứng**.

> ⚠️ Hệ quả cho người thêm view mới: `ALTER DEFAULT PRIVILEGES` khiến view mới trong
> `agent_api` **tự động** được agent đọc, mà view DEFINER thì RLS **không** áp bên trong.
> Thêm view mà quên `WHERE tenant_id = portal.current_tenant()` là rò toàn bộ tenant,
> im lặng. Đó chính là lý do có cổng `test_moi_view_agent_api_tu_loc_tenant`.

### 7.2c. `agent_api` KHÔNG có bảng nào — và đó là đúng thiết kế

Kiểm chứng: `grep "CREATE TABLE agent_api"` toàn bộ migrations ⇒ **0 kết quả**. Schema
`agent_api` chứa **đúng 5 view, không bảng nào**. Dữ liệu nằm ở `tenant_data` — 7 bảng:
`projects`, `zones`, `units`, `documents`, `media`, `kb_files`, `kb_index_state`.

**View không phải bản sao dữ liệu. View là một câu query được đặt tên.**
`SELECT … FROM agent_api.units` chạy **ngay lúc đó** vào `tenant_data.units`. Không có
bảng thứ hai, không có job đồng bộ, không có độ trễ.

Nên dữ liệu lưu **một chỗ duy nhất**, có **hai cửa** vào:

```
                    tenant_data.projects · zones · units · documents · media
                    (NƠI LƯU DUY NHẤT — 7 bảng thật)
                              ▲                        ▲
        ┌─────────────────────┘                        └──────────────────┐
        │ cửa 1                                                    cửa 2  │
   role portal_api                                          role agent_<tenant>
   ĐỌC + GHI bảng gốc                                       CHỈ SELECT 5 view
   canh bằng RLS                                            canh bằng WHERE
   (SET LOCAL app.tenant_id)                                trong chính view
        │                                                                 │
   thấy MỌI hàng của tenant                              thấy đúng phần đã published
   (kể cả draft — sale đang nhập)                         của tenant mình
```

**View lo ba việc, và đó mới là ý nghĩa thật của nó** (`0401`):

```sql
CREATE VIEW agent_api.units AS
SELECT u.…
  FROM tenant_data.units u
  JOIN tenant_data.projects p                       -- ③ cascade lên dự án cha
    ON p.tenant_id = u.tenant_id AND p.project_code = u.project_code
 WHERE u.tenant_id = portal.current_tenant()        -- ① cách ly tenant
   AND u.status = 'published'                       -- ② chỉ bản đã duyệt
   AND p.tenant_id = portal.current_tenant()
   AND p.status = 'published'
```

**`draft` nghĩa là gì — nói cho chính xác.** `status` là
`text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived'))`.
Nó **không** phải "form đang gõ dở" (cái đó chưa vào DB). Nó là **hàng đã lưu, chưa
đủ điều kiện công bố**: tạo qua `POST /projects`, qua KB ingest, hoặc qua seed — rồi chờ
`PATCH {"status":"published"}`. Và có cổng completeness chặn publish
(`realestate/completeness.py`): `project` cần `name`+`region`+`overview`; `unit` cần
`price_vnd`+`area_built_m2`+`sale_status`.

Nên một hàng `draft` là hàng **có thể đang thiếu `price_vnd`**. Agent tư vấn khách bằng
một căn không có giá là sai thật, không phải sai giả định.

### 7.2d. Vì sao lọc bằng view mà không để agent tự `WHERE status='published'`

Câu hỏi đúng, và câu trả lời **không** phải "cho agent tiện". Bốn lý do, theo thứ tự
trọng lượng:

**① Lọc phía agent là KỶ LUẬT; lọc bằng view là CƯỠNG CHẾ.**
Nếu agent có `GRANT SELECT ON tenant_data.units` thì `WHERE status='published'` là
**lựa chọn** của agent. Quên một lần — trong một tool mới, một lần refactor, một câu
query sinh động — là đọc được `draft`, và **không có lỗi nào báo**. Với view + zero quyền
trên bảng gốc thì agent **không thể viết được** câu query đó: `permission denied`.
Đây đúng là nguyên tắc 0005 đã ghi khi từ chối `security_invoker`:
*"Không vào được cửa" mạnh hơn "được vào nhưng bị lọc hàng".*

**② `WHERE status='published'` KHÔNG tương đương với view.**
Một `unit` có `status='published'` nhưng thuộc `project` có `status='draft'` thì **lọt**
qua filter đơn giản, và bị view loại. Muốn đúng, agent phải JOIN lên dự án cha — đó là
**luật nghiệp vụ**, không phải một điều kiện. Bằng chứng nó dễ sai: chính portal cũng phải
viết lại đúng cascade đó ở **bốn** chỗ trong `realestate/repo.py` (dòng 362, 435, 515,
594), mỗi chỗ một lần phải nhớ. Đặt luật đó bên agent thì số chỗ phải nhớ là "mọi tool
nào chạm `units`", ở một repo team khác sở hữu.

**③ Ai sở hữu hợp đồng.** M4 đã `ALTER TABLE` thêm ~40 cột vào `projects` và ~45 cột vào
`units`. Nếu agent query `tenant_data` trực tiếp thì mỗi lần portal đổi schema là một lần
agent có thể vỡ. View là một **projection ổn định** — biên phiên bản giữa hai repo.

**④ Có cổng CI cưỡng chế được — chỉ nhờ có view.**
`test_moi_view_agent_api_tu_loc_tenant` khẳng định **máy móc** rằng mọi view trong
`agent_api` tự lọc tenant. Không có cách nào khẳng định máy móc rằng "code của agent luôn
kèm `WHERE status='published'`" — nhất là ở repo mình không sở hữu.

**Vậy còn "cho agent đọc thoải mái không phải lo"?** Đó là **hệ quả**, không phải lý do —
và hợp đồng có ghi nó (`dau-noi-agent.md` G-6: *"Bạn KHÔNG phải tự lọc `status='published'`,
cũng không phải tự join lên anchor cha"*). Nhưng nếu tiện lợi là lý do duy nhất thì một
hàm helper phía agent đã đủ. Lý do thật là ①: **tiện lợi thì agent có thể bỏ qua; quyền
thì không.**

Đó cũng là lý do schema tên là `agent_api`: **nó LÀ API**, chỉ viết bằng SQL view thay vì
REST endpoint. Giá phải trả cho biên này là 5 câu `CREATE VIEW` — rẻ một cách bất thường
so với thứ nó cưỡng chế.

### 7.3. View hiện tại (sau 0401) và một cơ chế đã bị khai tử

`0400_kb_real_estate` drop hai view cũ; `0401_agent_doc_kb` dựng lại **năm** view:
`agent_api.projects` · `zones` · `units` · `documents` · `media`.
`0402` thêm `AND project_code <> '__ALL__'` vào `projects` (ẩn row sentinel).

View lo sẵn ba việc, agent **không phải** tự làm: lọc tenant · chỉ trả
`status = 'published'` · ẩn cây con khi dự án cha chưa published.

**Đã khai tử:** cơ chế gate cột (`portal.pol()` + `control.field_policy_live` + ba cột
`commission`/`bank_support`/`csbh_full`). Bản 0005 có; từ 0401 thì view **trả đủ cột** vì
KB mới không lưu trường nội bộ nhạy cảm nữa. Bảng `field_policy_live` vẫn còn trong DB
nhưng **chết** — không ai ghi, không view nào đọc.

### 7.4. Vậy khác biệt thật của spec §5.3 nằm ở đâu

| | Dữ liệu nghiệp vụ | Cấu hình / persona |
|---|---|---|
| Agent lấy từ | **Postgres** — `SELECT` trên `agent_api.*` | **MinIO** — poll con trỏ `LIVE` mỗi 20s, tải bundle, verify sha256 |
| Ai render | không render, là dữ liệu | **Portal** render sẵn 6 tệp markdown |
| Spec §5.3 muốn | (không đổi) | chuyển sang **Postgres**, agent tự render |

Con trỏ `LIVE` hiện là một object JSON `{"version": 12, "bundle": "sha256:9f2c…"}`, ghi
bằng **một** `PUT` và luôn ghi **sau** khi bundle đã lên kho đủ — nhờ đó M3 không cần
transaction hai pha giữa Postgres và kho tệp, và agent không bao giờ thấy bundle nửa vời.

### 7.5. Câu hỏi thật sau §5.3 + §8: **ai render prompt?**

Đây mới là quyết định, không phải "Postgres hay MinIO".

| | **Portal render** (hiện tại) | **Agent render** (spec muốn) |
|---|---|---|
| Portal lưu | config có cấu trúc **+ 6 tệp đã render** | chỉ config có cấu trúc |
| Skeleton persona ở | code portal (`bundle.py`) | disk agent, 1 bản dùng chung |
| Sinh danh mục kỹ năng | sinh từ `tools.enabled` lúc render | strip vùng `<!-- TOOL:x -->` lúc chạy |
| Sửa câu chữ prompt | deploy portal | deploy agent |
| Prompt đã chạy có tái dựng được? | **Có, byte-for-byte** — version bất biến + `bundle_sha` | **Không** — nó là `config × skeleton-trên-disk`, mà skeleton không đánh version |
| Quay lui | đổi con trỏ, **không render lại** | render lại bằng skeleton *hiện tại*, không phải skeleton lúc đó |
| `POST /config/preview` | chính xác | chỉ đúng nếu portal giữ một bản copy skeleton ⇒ hai nguồn sự thật |

Cái spec đánh đổi để lấy "agent team tự sửa câu chữ không cần deploy portal" là **tính
tái dựng được của prompt đã chạy** và **tính đúng của rollback**. Với hệ thống bán cho
nhiều sàn thì hai thứ đó đắt hơn.

**Khuyến nghị:** giữ portal render. Nếu về sau muốn agent render thì skeleton phải được
đánh version và `config_versions` phải ghi kèm `skeleton_version` — nếu không thì
"quay lui về đúng bản đã chạy", lời hứa trung tâm của M3, không còn đúng.
