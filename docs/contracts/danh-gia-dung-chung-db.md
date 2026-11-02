# Đánh giá: dùng chung Postgres với team agent — kết quả khảo sát thật

> Ngày: 2026-08-04. **CHƯA THAY ĐỔI GÌ trên DB của họ** — toàn bộ khảo sát là chỉ-đọc.
> Đích: `thebc-server.local` = `10.50.13.220`, container `odyssey-postgres`, DB `odyssey`.

## Kết luận

**Làm được, và dễ hơn tôi ước lượng ở bản trước** — vì `tenant_data` hai bên **gần trùng
khít**. Nhưng hình dạng công việc **không phải** "đẩy schema của tôi lên + copy dữ liệu".
Nó là một cuộc **hợp nhất** hai schema cùng tên, và phải quyết **ràng buộc bên nào thắng**.

Dữ liệu thật cần nạp rất nhỏ: **603 units + 41 projects** (đang bị nhân bản 5 lần thành
3015/205), cộng 147 appointments + 11 conversations + 6 contacts của tenant `noble`.

---

## 1. Truy cập: ĐÃ GIẢI QUYẾT (không cần họ mở firewall)

`thebc-server.local` phân giải ra **chính `10.50.13.220`**. Postgres bind
`127.0.0.1:5433` → đó là lý do bên ngoài `Connection refused`. Vào được qua SSH:

```
container:  odyssey-postgres   postgres:16.14   127.0.0.1:5433->5432
roles:      sp_admin (SUPERUSER, bypassrls), odyssey_agent, noble,
            spe_app_role, kb_probe_app_role
            → KHÔNG có portal_api, agent_all, portal_migrator
schemas:    public, tenant_data          → KHÔNG có control, agent_api, portal
alembic:    không có bảng alembic_version (schema của họ không do alembic quản)
extension:  chỉ plpgsql
```

Trên máy đó còn cả stack `santa-*`: qdrant, minio, redis, mongo, grafana, phoenix,
`santa-hotline-agent`. Tức đây là **máy chủ của hệ agent**, không phải một DB server riêng.

✅ **Migration chain của bạn CHẠY ĐƯỢC trên Postgres 16** — tôi đã kiểm thật:
`alembic upgrade head` trên `postgres:16` thành công. Rủi ro lệch major version (dev 18 →
đích 16, `deploy/README.md` §6.1) coi như đã loại cho đường này.

## 2. Phát hiện lớn nhất: schema hai bên gần như CÙNG MỘT THIẾT KẾ

| Bảng `tenant_data` | Portal | Họ | Khác nhau |
|---|---|---|---|
| `documents` | 9 cột | 9 cột | **trùng khớp hoàn toàn** |
| `units` | 21 cột | 21 cột | chỉ nullability: `zone_code`, `product_type` |
| `projects` | 25 cột | 25 cột | chỉ nullability: 11 cột text |
| `zones` | 13 cột | 13 cột | chỉ nullability: `overview`, `product_scale` |
| `media` | 15 cột | 15 cột | chỉ nullability: `caption`, `category`, `content_hash` |
| `kb_files`, `kb_index_state` | có | **không** | Portal thêm mới |
| `contacts`, `conversations`, `appointments` | **không** | có | Portal chưa xây (G-6 đã báo trước) |

**Tên cột trùng 100% trên 5 bảng chung.** Khác biệt duy nhất là Portal `NOT NULL` ở chỗ họ
cho `NULL`, và **Portal có CHECK constraint còn họ có ZERO CHECK nào**.

Và họ **đã build sẵn** bề mặt §1.1 của hợp đồng:
```sql
-- public.agent_published_config, security_invoker=true
SELECT v.tenant_id, v.version, v.config
  FROM agent_config_versions v
  JOIN agent_config_pointer p ON p.tenant_id=v.tenant_id AND p.published_version=v.version;
```
Đúng khuôn DDL trong contract, kèm bảng con trỏ `agent_config_pointer`. Nên câu hỏi treo ở
bản review trước ("con trỏ live nằm ở đâu") **họ đã tự trả lời phía họ**: một bảng con trỏ
trong Postgres.

## 3. Mô hình cách ly của họ khác Portal — bốn điểm

| | Portal | Họ |
|---|---|---|
| Tên GUC | `app.tenant_id` | **`app.current_tenant`** |
| Role → tenant | `agent_<slug>` (có tiền tố) | `tenant_id = CURRENT_USER` (**tên role LÀ tenant_id**) |
| Policy áp cho | `TO agent_all` / `TO portal_api` | **`TO public`** |
| View | DEFINER + `WHERE = current_tenant()`, **cấm** `security_invoker` (cổng 5) | `security_invoker=true`, dựa hoàn toàn vào RLS |

Hai điểm đầu vô hại — contract §4 đã nói agent set **cả hai** GUC.

⚠️ **Điểm phải nói thẳng: `odyssey_agent` đang có `SELECT + INSERT + UPDATE + DELETE`
trực tiếp trên MỌI bảng gốc** — `tenant_data.units`, `projects`, và cả
`agent_config_versions` + `agent_config_pointer`. Tôi đã kiểm bằng
`has_table_privilege`. Nghĩa là hôm nay agent **xoá được chính config version của nó**.
Đối chiếu thiết kế Portal: agent có **zero quyền** trên bảng gốc (cổng 5), chỉ đọc qua view
`agent_api` để có gate cột, và `config_versions` **bất biến** (0200 `REVOKE UPDATE, DELETE`).
Đây là khoảng cách lớn nhất giữa hai hệ, và nó là khoảng cách về quyền, không phải về schema.

✅ Điểm họ làm đúng, tôi đã nghi sai: `security_invoker=true` có mặt, nên RLS áp cho
**người gọi**. Thực nghiệm: nối bằng `odyssey_agent` **không khai GUC → 0 hàng**
(`agent_published_config` và `units` đều 0). Fail-closed hoạt động. Khai
`app.current_tenant='noble'` → 603 units.

## 4. Dữ liệu thật: 5 tenant, cùng một bộ dữ liệu nhân bản

| tenant_id | units | projects | contacts | conv. | appt. | config |
|---|---|---|---|---|---|---|
| `''` **(rỗng)** | 603 | 41 | – | – | – | – |
| `acme` | 603 | 41 | 1 | 2 | – | – |
| `du_test` | 603 | 41 | 1 | – | – | – |
| `noble` | 603 | 41 | 4 | 9 | **147** | 1 |
| `org_f1d72eac_demo-sales_5d74` | 603 | 41 | – | – | – | – |

`zones` = **0 hàng**. `documents` = 0. `media` = 0.

Chỉ `noble` trông như tenant thật. Bốn cái còn lại là bản demo/test — trong đó
`tenant_id = ''` là **rác** (chuỗi rỗng, không phải tenant nào).

## 5. Năm chỗ dữ liệu của họ sẽ VỠ ràng buộc của Portal

| # | Vấn đề | Ảnh hưởng | Cần quyết định |
|---|---|---|---|
| 1 | **`units.zone_code` NULL 3015/3015**, mà `zones` rỗng | Portal: `NOT NULL` + FK về `zones` ⇒ **0/3015 hàng nạp được** | Sinh một zone mặc định mỗi project, hay nới `zone_code` thành nullable? |
| 2 | `tenant_id = ''` (603 units, 41 projects) | Vỡ `tenants_id_check ^[a-z][a-z0-9_]{1,30}$` | Bỏ hẳn, hay gán về một tenant? |
| 3 | `org_f1d72eac_demo-sales_5d74` có **dấu gạch ngang** | Vỡ cùng CHECK đó | Đổi tên slug (`_` thay `-`)? |
| 4 | `projects.category` chứa `studio` ở **5 project** | Portal cho `chung_cu·biet_thu·lien_ke·shophouse·dat_nen·van_phong` — **không có `studio`** | Thêm `studio` vào CHECK của projects, hay sửa 5 hàng đó? (`studio` HỢP LỆ cho `units.product_type` — Portal cố ý hai danh sách khác nhau) |
| 5 | ~16 cột text `NULL` mà Portal `NOT NULL` (vd `projects.overview` 30/205) | Chặn INSERT | Mechanical: `coalesce(col,'')` khi nạp. Không cần ai quyết. |

✅ **Tin tốt — những thứ khớp sẵn, không phải làm gì:** `sale_phase` toàn `dang_ban` ✓ ·
`status` toàn `published` ✓ (nên agent sẽ THẤY dữ liệu, không rơi vào bẫy `draft`) ·
`sale_status` toàn `available` ✓ · `direction` mọi giá trị nằm trong danh sách Portal ✓ ·
`product_type` 0 NULL và cả 3 giá trị đều hợp lệ ✓.

Và: `contacts` · `conversations` · `appointments` (154 hàng của `noble`) **chưa có chỗ ở
trong Portal** — Portal chưa xây ba bảng đó.

## 6. Vì sao KHÔNG chạy `alembic upgrade head` thẳng lên DB `odyssey`

`CREATE TABLE tenant_data.units` (0400) không có `IF NOT EXISTS`, và bảng đó **đã tồn tại
với 3015 hàng**. Migration sẽ vỡ ở đó. Cùng vấn đề với `projects`, `zones`, `documents`,
`media`, và `CREATE ROLE odyssey_agent` (0901). Chạy thẳng = vỡ giữa đường, trên một DB
đang phục vụ.

**Ba đường đi — tôi khuyến nghị (B):**

**(A) Nhận nuôi schema sẵn có.** Viết một migration "adopt": bỏ qua tạo 5 bảng trùng, thay
bằng `ALTER TABLE` để thêm dần `NOT NULL` + CHECK + FK của Portal — sau khi đã dọn dữ liệu ở
§5. Ưu: một DB duy nhất ngay từ đầu. Nhược: sửa cấu trúc bảng **đang được agent ghi vào**;
mỗi `ALTER` là một lần khoá bảng và một lần có thể vỡ vì dữ liệu bẩn.

**(B) ⭐ Dựng DB riêng `odyssey_portal` trên cùng server đó, rồi nạp dữ liệu vào.** Ưu:
`alembic upgrade head` chạy sạch trên DB rỗng (đã kiểm chạy được trên PG16); không chạm một
byte nào của DB đang sống; có chỗ tập dượt việc nạp dữ liệu và sửa lại bao nhiêu lần cũng
được; khi xong thì việc chuyển sang chỉ là **đổi một dòng DSN** phía agent. Nhược: một
khoảng thời gian có hai DB — nhưng đó là khoảng thời gian bạn kiểm soát được.

**(C) Đổi tên `tenant_data` của họ, để Portal sở hữu tên đó.** Sạch về schema nhưng phá
mọi truy vấn của agent ngay lập tức. Không khuyến nghị.

*Lưu ý cho cả ba đường:* role là phạm vi **cluster**, nên `CREATE ROLE odyssey_agent` ở 0901
vẫn trùng dù đổi database. Hoặc họ `DROP ROLE` để migration tạo lại (sạch, giữ đúng
`NOLOGIN` fail-closed), hoặc tôi sửa 0901 thành idempotent.

## 7. Ba việc về an toàn, không liên quan schema

1. **`odyssey_agent_pw` phải coi như đã lộ** — nó nằm trong file env chuyền tay giữa hai
   team, và role đó đọc được mọi tenant. Xoay trước khi có dữ liệu thật.
2. **`sp_admin` là SUPERUSER + BYPASSRLS.** Nó đọc được mọi tenant, bỏ qua toàn bộ RLS, và
   `deploy/README.md` §1 đòi `portal_migrator` **không** được là superuser (nếu migration
   chạy bằng superuser thì view `agent_api` thuộc sở hữu superuser và FORCE RLS không áp bên
   trong nó — hai lớp lọc tenant tụt còn một). Cần tạo `portal_migrator` (non-superuser,
   `CREATEROLE`) và `portal_api` riêng.
3. **Thu hẹp quyền của `odyssey_agent`** về đúng mô hình Portal: zero quyền trên bảng gốc,
   chỉ `SELECT` trên `agent_api.*`, và `config_versions` bất biến. Hôm nay agent xoá được
   config của chính nó.

## 8. Việc cần bạn chốt (5 câu, không phải kỹ thuật)

1. Đường **(A)/(B)/(C)** ở §6 — tôi khuyến nghị **(B)**.
2. `units.zone_code`: sinh zone mặc định, hay nới thành nullable? (§5.1)
3. Bốn tenant `''`/`acme`/`du_test`/`org_f1d72eac_demo-sales_5d74`: **nạp hay bỏ?** Nếu chỉ
   `noble` là thật thì việc nạp gọn lại còn 603+41+154 hàng của một tenant.
4. `studio` trong `projects.category`: thêm vào CHECK của Portal, hay sửa 5 hàng đó? (§5.4)
5. `contacts`/`conversations`/`appointments` (154 hàng): Portal xây ba bảng đó bây giờ, hay
   để lại bên họ?

Trả lời xong 5 câu này thì việc nạp dữ liệu là script mechanical — dữ liệu nhỏ và schema đã
gần trùng, nên đây là phần dễ nhất của cả việc.

## Ranh giới tôi tự đặt

Tôi sẽ không `CREATE`/`ALTER`/`DROP` gì trên DB `odyssey` của họ, cũng không chạy migration
lên đó, mà không có: bạn xác nhận rõ + một bản backup đã kiểm chứng + team họ biết và đồng ý.
Toàn bộ khảo sát trong tài liệu này là `SELECT` và `has_table_privilege`, cộng đúng một
`SET app.current_tenant` trong phiên rồi `RESET`.
