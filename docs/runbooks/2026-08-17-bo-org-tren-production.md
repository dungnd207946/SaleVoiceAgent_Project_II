# Runbook — đưa `0105`/`0106` (bỏ tầng tổ chức) lên production

Kèm: [`scripts/tien_kiem_bo_org.sql`](../../scripts/tien_kiem_bo_org.sql)
Spec: [`docs/superpowers/specs/2026-08-15-bo-organization-design.md`](../superpowers/specs/2026-08-15-bo-organization-design.md)

---

## §1 — Hai migration này xoá những gì (đo từ chính file migration)

**Không có câu nào xoá hàng `tenants`, `users`, hay bất kỳ bảng `tenant_data.*`.**
Toàn bộ danh sách lệnh làm mất dữ liệu:

| Lệnh | Ở đâu | Mất gì |
|---|---|---|
| `DELETE FROM control.roles WHERE id NOT IN (SELECT id FROM _giu)` | `0105` ② | Bản sao vai trò trùng tên (mỗi tổ chức từng có bộ 4 riêng). Kéo theo `role_actions` của các bản bị xoá qua CASCADE. **`memberships.role_id` được UPDATE trỏ sang bản giữ lại TRƯỚC khi xoá**, nên không membership nào rụng. |
| `ALTER TABLE … DROP COLUMN org_id` (tenants · users · memberships · audit_log · roles · invites) | `0105` ④, `0106` ② | Chỉ nội dung cột đó. `DROP COLUMN` không xoá hàng. |
| `ALTER TABLE control.users DROP COLUMN org_role` | `0106` ② | Cột đó. |
| `DROP TABLE control.organizations` | `0106` ③ | Bảng tổ chức. Chạy **sau** khi mọi `org_id` đã biến mất ⇒ không còn FK nào ⇒ **không có đường cascade tới hàng nào**. Không dùng `CASCADE`, nên nếu còn FK sót thì Postgres báo lỗi và cả giao dịch lùi, chứ không xoá âm thầm. |

### Cascade có thật, nhưng không nằm trên đường đi của migration

DB này có **34 FK `ON DELETE CASCADE` trỏ tới `control.tenants`** — gồm cả 15
bảng `tenant_data.*` (`projects`, `units`, `zones`, `contacts`,
`conversations`, …). Nên **xoá một hàng `control.tenants` là xoá sạch mọi dữ
liệu nghiệp vụ của workspace đó.** Đó là thiết kế có từ trước, không phải do
đợt này, và `0105`/`0106` không hề `DELETE FROM control.tenants`.

`control.tenants.created_by → control.users` (thêm ở `0106`) cố ý là **`NO
ACTION`, không cascade**: xoá một user không được phép kéo theo workspace của họ.

### Bằng chứng: DB dev bị mất dữ liệu KHÔNG do migration

Đo trên `odyssey-portal-backend-postgres-1` ngày 2026-08-17:

- `control.roles` vẫn giữ **4 hàng có `created_at = 2026-08-04 11:17`** — đúng
  bộ seed gốc, và đúng kết quả dedup mong đợi. Nếu bảng từng bị dựng lại, dấu
  thời gian đó không còn.
- `oid` của mọi bảng `control`/`tenant_data` nằm trong dải `16394–16779` =
  sinh lúc initdb ngày 4/8 ⇒ **không bảng nào từng bị DROP/CREATE lại**, tức
  không có ai chạy `alembic downgrade base`.
- Container postgres `Created = 2026-08-04`, volume vẫn là volume gốc ⇒ **không
  có `make reset` / `docker compose down -v`**.
- Mọi hàng `users`/`tenants`/`audit_log` còn lại đều `≥ 06:20 ngày 17/8`, và
  `u_dungnd` được đăng ký **ba lần** (06:20 · 06:42 · 06:53).

Kết luận: các hàng cũ bị xoá bằng SQL trực tiếp trên DB dev trong buổi thử luồng
đăng ký, giữa các lần thử. Không phải migration; cũng không phải `scripts/dev_seed.py`
(thuần `INSERT … ON CONFLICT DO UPDATE`, không có `DELETE`) và không phải bộ test
(`tests/conftest.py` dựng `PostgresContainer` riêng — mọi teardown
`DELETE FROM control.users WHERE id LIKE 'u\_%'` chỉ chạm container throwaway đó,
không chạm cổng 5442).

> ⚠ `scripts/nap_du_lieu_tu_odyssey.py:68` **có** một `DELETE FROM control.tenants`
> theo danh sách `ANH_XA_TENANT` (`acme`, `du_test`, `noble`, …) và nó xoá kèm toàn
> bộ `tenant_data` qua cascade. Script này còn ghi `org_id` (dòng 73) nên hiện tại
> chạy sẽ lỗi. **Đừng để nó tồn tại trên máy chạy được production DSN.**

---

## §2 — Thứ tự triển khai

```bash
# ① Backup TRƯỚC, luôn luôn. 0105 không có đường lùi cho roles đã dedup.
pg_dump "$MIGRATOR_URL" -Fc -f org-truoc-$(date +%F).dump

# ② Tiền kiểm — mọi khối A/B/C/D phải trả 0 hàng
psql "$MIGRATOR_URL" -f scripts/tien_kiem_bo_org.sql

# ③ Lưu lại thông tin tổ chức (§4) và backfill membership cho owner (§3)

# ④ Chạy tiền kiểm lại — D phải sạch

# ⑤ Migrate
uv run alembic upgrade head
```

---

## §3 — BẮT BUỘC nếu khối D có hàng: cấp membership cho org owner

Trước `0106`, `core/auth/repo.doc_quyen()` có một nhánh riêng cấp toàn quyền cho
`users.org_role = 'owner'` **mà không cần hàng `memberships`**. Nhánh đó đã gỡ:
từ nay **không membership = không quyền**. Người nào đang dựa vào nhánh cũ sẽ
đăng nhập vào và thấy 0 workspace — dữ liệu còn nguyên, nhưng họ không vào được.

`0106` **không** tự vá chuyện này (nó chỉ ghi `tenants.created_by`), nên phải chạy
tay **ở HEAD 0104, trước `0105`** — lúc `memberships.org_id` và `roles.org_id` còn
tồn tại:

```sql
BEGIN;

INSERT INTO control.memberships (org_id, user_id, tenant_id, role_id)
SELECT t.org_id,
       u.id,
       t.id,
       (SELECT r.id FROM control.roles r
         WHERE r.name = 'Quản trị' AND r.org_id = t.org_id
         ORDER BY r.created_at, r.id LIMIT 1)
  FROM control.users u
  JOIN control.tenants t ON t.org_id = u.org_id
 WHERE u.org_role = 'owner'
ON CONFLICT (user_id, tenant_id) DO NOTHING;

-- Không được để `role_id` NULL: tổ chức nào thiếu vai trò 'Quản trị' thì hàng
-- vừa chèn là một membership vô nghĩa. Có hàng ⇒ ROLLBACK và xử tay.
SELECT count(*) AS membership_thieu_vai_tro
  FROM control.memberships WHERE role_id IS NULL;

COMMIT;   -- chỉ commit khi con số trên = 0
```

Sau bước này, chạy lại khối D của tiền kiểm — phải trả 0 hàng.

---

## §4 — Lưu lại thông tin tổ chức trước khi nó biến mất

`DROP COLUMN` / `DROP TABLE` không hoàn lại được, và `downgrade()` của `0106`
**gom mọi workspace về đúng một tổ chức `noble`** — nó không phục hồi bản đồ cũ.
Muốn còn tra được "workspace này từng thuộc tổ chức nào", chụp lại trước:

```sql
CREATE TABLE control.luu_org_20260817           AS SELECT * FROM control.organizations;
CREATE TABLE control.luu_org_tenant_20260817    AS SELECT id AS tenant_id, org_id FROM control.tenants;
CREATE TABLE control.luu_org_user_20260817      AS SELECT id AS user_id, email, org_id, org_role FROM control.users;
```

Ba bảng này không có FK nên `0106` không chạm tới. Xoá khi đã chắc không cần.

> Nếu đặt trong schema `control` thì phải khai vào
> `tests/isolation/test_isolation_catalog.py` (`CONTROL_TABLES_…`) khi bảng mang
> cột `tenant_id` — ba bảng trên **không** mang cột đó nên không vướng cổng.
> Muốn tránh hẳn: `pg_dump -t control.organizations` ra tệp thay vì tạo bảng.

---

## §5 — Nếu khối A có hàng: quyết định trước khi dedup

`0105` giữ bản vai trò **cũ nhất** theo `(name, created_at, id)` và xoá phần còn
lại. Bộ `role_actions` của bản được giữ là bộ sống sót cho **mọi** tổ chức. Nếu
hai tổ chức đã cấu hình quyền khác nhau cho cùng một tên vai trò, một trong hai
cấu hình mất im lặng (chỉ có `RAISE NOTICE` số hàng).

Ba đường xử, chọn một:

1. **Chấp nhận** — hợp lý nếu khối A trả 0 hàng (mọi bản sao giống nhau y hệt,
   tức chưa ai dùng CRUD `/roles`). Đây là trường hợp thường gặp vì
   `ROLES_CRUD_ENABLED` mặc định `false`.
2. **Chuẩn hoá trước** — sửa `role_actions` cho các bản trùng tên bằng nhau, rồi
   dedup không mất gì.
3. **Đổi tên tách ra** — tổ chức nào có bộ quyền riêng thì đổi `roles.name` thành
   tên khác (`Quản trị (Havengroup)`) trước `0105`; nó sẽ tồn tại như một vai trò
   toàn cục độc lập sau migration.

---

## §6 — Sau khi migrate: kiểm ngay bốn con số

```sql
SELECT count(*) FROM control.tenants;                        -- phải bằng trước
SELECT count(*) FROM tenant_data.projects;                   -- phải bằng trước
SELECT count(*) FROM control.tenants t                       -- phải = 0
 WHERE NOT EXISTS (SELECT 1 FROM control.memberships m
                    WHERE m.tenant_id = t.id AND m.user_id = t.created_by);
SELECT count(*) FROM control.users u                         -- phải = 0
 WHERE NOT EXISTS (SELECT 1 FROM control.memberships m WHERE m.user_id = u.id);
```

Hai con số cuối là "không ai bị khoá ngoài cửa". Số thứ tư có thể > 0 một cách
hợp lệ nếu production có tài khoản `pending` chưa nhận lời mời — lọc thêm
`AND u.lifecycle = 'active'` để đọc đúng.
