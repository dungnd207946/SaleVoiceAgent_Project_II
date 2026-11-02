# Design — đẩy KB data từ mockdb sang Postgres `portal`

- **Ngày:** 2026-08-10
- **Nguồn:** container `odyssey-mockdb` — `postgresql://sp_admin:***@localhost:5432/odyssey`
- **Đích:** container `odyssey-portal-backend-postgres-1` — `postgresql://portal_api:***@10.50.13.208:5442/portal`
- **Phạm vi:** 5 bảng KB của `tenant_data` (`projects`, `zones`, `units`, `media`, `documents`), 4 tenant.

## 1. Bối cảnh

Dữ liệu KB đã tồn tại đầy đủ trong mockdb, dựng bởi chuỗi ở
`~/Desktop/santa-models/mockdb/`: `sync.sh` (pg_dump từ `10.50.13.209`, chỉ đọc) →
`fill.py` (lấp zones/media/documents từ NBX Sales API dev) → `reshape.py` (chia 41 dự án
thành 4 tenant / 3 org) → `verify.py`. Container đang ở trạng thái Exited nhưng chưa
`down`, nên dữ liệu còn nguyên: **41 projects · 56 zones · 603 units · 270 media ·
5 documents**, chia 7 / 6 / 14 / 14.

`tenant_data` ở `portal` hiện **rỗng hoàn toàn** (12 bảng, 0 hàng). Việc cần làm là copy
5 bảng KB sang, không đụng Mongo `nbx_*` và không cần `10.50.13.209` hay NBX API.

Đây **không phải** đường `migration/kb_backfill/` của repo agent — cái đó đọc Mongo
`nbx_projects`/`nbx_units` và chỉ ghi projects + units cho một tenant `noble`.

## 2. Ràng buộc đã đo ở đích

| # | Ràng buộc | Hệ quả |
|---|---|---|
| 1 | Schema 5 bảng **khớp 100%** giữa hai bên (đúng số cột, đúng kiểu) | Không cần transform, chỉ cần remap khoá |
| 2 | RLS `ENABLE` + `FORCE` trên mọi bảng `tenant_data`; policy `tenant_isolation` dùng `portal.current_tenant()`, hàm này đọc GUC **`app.tenant_id`** | Mỗi transaction phải `set_config('app.tenant_id', <tenant>, true)`; sai tenant thì `WITH CHECK` chặn |
| 3 | `portal_api`: không `SUPERUSER`, không `BYPASSRLS`; owner bảng là `portal_migrator` | Không có đường vòng qua RLS — phải đi đúng GUC |
| 4 | FK `tenant_id → control.tenants(id)` | Tenant phải tồn tại trước; mockdb **không có** schema `control` nên tenant_id ở đó là chuỗi tự do |
| 5 | Vòng FK: `projects/zones.cover_media_id,map_media_id → media(tenant_id,id)`; `units.zone_code → zones`; `media/documents.project_code → projects` | Phải nạp 2 pha, nối lại media_id sau |
| 6 | `portal_api` có full CRUD trên cả `tenant_data` lẫn `control` | Script tự tạo được tenant thiếu |
| 7 | Cả 5 bảng đích có `id DEFAULT nextval(...)` và `portal_api` có `USAGE` trên cả 5 sequence (đã đo) | Bỏ hẳn cột `id` khi INSERT, sequence đích tự cấp |
| 8 | Đích **chặt hơn** nguồn về nullability: 17 cột `NOT NULL` ở đích nhưng nullable ở nguồn, và nguồn có NULL thật (41 `projects.developer`, 56 `zones.overview`, 262 `media.caption`…) | NULL được quy về đúng `DEFAULT` literal của đích (đọc từ `information_schema`); cột NOT NULL không default thì cố ý để nổ |
| 9 | Đích có **19 CHECK constraint**, nguồn **không có cái nào** (mockdb restore từ schema cũ hơn) | Đã soát cả 19 trên toàn bộ dữ liệu nguồn: chỉ 2 vi phạm (§3b) |

**Cảnh báo môi trường:** cổng `5442` xuất hiện ở **hai máy khác nhau**, cùng chạy compose
`odyssey-portal-backend` với cùng tên container `odyssey-portal-backend-postgres-1`:
`10.50.12.62` (máy dev haidt, cũng là chỗ chạy script) và `10.50.13.208` (đích). Một lệnh
`docker exec … psql` gõ ở máy này **không** chạm tới `.208` — đã vấp một lần khi nới CHECK.

GUC `app.tenant_id` là của control-plane Portal, **khác** `app.current_tenant` mà agent
dùng cho data plane (`storage/postgres_client.py::tenant_conn`). Dùng nhầm → 0 hàng, im lặng.

## 3. Map tenant

| mockdb `tenant_id` | Ở `control.tenants` | Hành động |
|---|---|---|
| `an-phu-land_q8w2_retail` | đã có (`org_id='noble'`) | dùng nguyên |
| `noble-homes_k3n7_retail` | chưa có | INSERT, `org_id='noble'` |
| `noble-homes_k3n7_wholesale` | chưa có | INSERT, `org_id='noble'` |
| `an-phu-land_z5r1_retail` | chưa có | INSERT, `org_id='noble'` |

Giữ nguyên tên có gạch ngang. Tenant `noble_homes_k3n7_retail` (gạch **dưới**) mà Portal
đã tạo sẵn là một tenant khác — không đụng tới, không gộp.

**Đánh đổi đã chấp nhận:** ở mockdb, `an-phu-land_q8w2_retail` và `an-phu-land_z5r1_retail`
cố ý thuộc *hai org khác nhau trùng cả tên org lẫn tên tenant* — cặp duy nhất bắt được bug
"slugify `(org_name, tenant_name)` bỏ random → gộp hai org". Ở `portal` chỉ có 2 org
(`noble`, `havengroup`) và `q8w2` đã bị gán `org_id='noble'`. Đưa cả bốn tenant về org
`noble` làm **mất tầng org** của bộ test, chỉ còn tầng tenant. Không tạo org mới và không
sửa `org_id` của tenant Portal đã tạo, vì `control.organizations` là dữ liệu Portal sở hữu.

## 3b. Map giá trị về enum của đích

Hai chỗ duy nhất dữ liệu nguồn vi phạm CHECK của đích:

| Nguồn | Số hàng | → Đích | Lý do |
|---|---|---|---|
| `media.category = 'csbh'` | 34 | `'tong_quan'` | enum đích không có `csbh` (ảnh chính sách bán hàng); `tong_quan` là ô gần nghĩa nhất — mất độ chính xác của nhãn, giữ được ảnh |
| `projects.category` chứa `'studio'` | 1 dự án | `'chung_cu'` + khử trùng | studio là một loại căn hộ chung cư |

`units.product_type` **không** đụng: enum đích của `units` vốn đã có `studio`.

Phương án thay thế (nới CHECK ở đích) đã bị loại: `tenant_data` do `portal_migrator` sở hữu,
sửa constraint ở DB dev sẽ bị migration kế tiếp của Portal dựng lại và nổ trên đúng 35 hàng này.

## 4. Pipeline

Một script, chạy lại được, ghi **chỉ** vào `:5442`. Không câu lệnh nào ghi lên mockdb.

**Pha 0 — control.** `INSERT INTO control.tenants (id, name, lifecycle, org_id)
VALUES (…) ON CONFLICT (id) DO NOTHING` cho 3 tenant thiếu.

**Pha 1 — copy, mỗi tenant một transaction**, mở đầu bằng
`SELECT set_config('app.tenant_id', $tenant, true)`:

```
DELETE FROM tenant_data.projects WHERE tenant_id = $t   -- cascade sạch 4 bảng con
INSERT projects   (bỏ id, cover_media_id, map_media_id → NULL)
INSERT zones      (bỏ id, cover_media_id, map_media_id → NULL)
INSERT media      (bỏ id)  → thu map src_media_id → dst_media_id
UPDATE projects, zones  SET cover_media_id/map_media_id theo map
INSERT units      (bỏ id)
INSERT documents  (bỏ id)
```

`id` để sequence đích tự cấp. Mọi tham chiếu nối lại qua business key (`project_code`,
`zone_code`) và map media — cùng cách `reshape.py` đã dùng (`SKIP` bỏ cột id, nối lại sau).

Idempotent bằng delete-then-insert theo tenant: `projects` là gốc cascade nên một lệnh
DELETE dọn sạch cả zones/units/media/documents của tenant đó.

**Pha 2 — verify.**

1. Đếm 5 bảng × 4 tenant, khớp đúng số nguồn (7/6/14/14 projects; tổng 41·56·603·270·5).
2. `cover_media_id`/`map_media_id`: số hàng non-NULL ở đích bằng ở nguồn (không nuốt tham chiếu).
3. Kiểm chứng RLS: set GUC tenant A rồi `count(*)` phải bằng đúng số hàng của A — không
   thấy hàng của tenant khác.
4. Spot-check một `project_code` bất kỳ: so từng cột giữa nguồn và đích.

## 5. Vị trí file

`~/Desktop/santa-models/mockdb/push_portal.py` — bước 5 nối tiếp chuỗi hiện có, dùng chung
pattern DSN của thư mục đó.

Đánh đổi: thư mục ấy có `.gitignore` chứa `*` nên script không được version control. Chấp
nhận vì nó là đồ thử tay cùng họ với `sync.sh`/`fill.py`/`reshape.py`; nếu sau này cần giữ
trong git thì chuyển sang `odyssey-agent/migration/mockdb_to_portal/`.

## 6. Ngoài phạm vi

- `appointments` / `contacts` / `conversations` (dữ liệu vận hành) — không đẩy.
- `agent_config`, `kb_files`, `kb_index_state`, `conversation_messages` — 4 bảng chỉ có ở
  đích, không có nguồn tương ứng.
- Ingest Qdrant (`<tenant>_documents` / `<tenant>_media`) — việc riêng, không thuộc spec này.
- `control.organizations` và `org_id` của tenant Portal đã tạo — không sửa.
