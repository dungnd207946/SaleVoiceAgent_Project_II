# Tầng organization trên tenants — thiết kế

**Ngày:** 2026-08-03 · **Phạm vi:** schema `control` + module `auth`. Không chạm `tenant_data`, không chạm RLS.

## 1. Vì sao

`control.tenants` đang phẳng — không có gì ở trên. Cần một tổ chức sở hữu nhiều workspace, user
đăng nhập gắn với đúng một tổ chức, và truy cập workspace trong tổ chức đó theo phân quyền.

Spec M1 (§9 của `PHAN-TICH-THIET-KE-DB.md`) đã để sẵn đường lùi này: *thêm bảng phía trên
`tenants`, không sửa `tenants.id`* — vì `tenants.id` đang gánh bốn vai (policy RLS, `TENANT_ID` của
agent pod, đường dẫn `tenants/<id>/` trên kho tệp, tên collection `kb_<id>`). Thiết kế này đi đúng
đường đó.

## 2. Schema

Một migration mới, `0102_organizations`, `down_revision = "0401_agent_api_bds"` (head hiện tại).

```
control.organizations                          ← MỚI, tầng trên cùng
  id         text PRIMARY KEY  CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$')
  name       text NOT NULL
  lifecycle  text NOT NULL DEFAULT 'active'  CHECK IN ('active','suspended','closed')
  created_at timestamptz NOT NULL DEFAULT now()
      │
      ├──< control.tenants   + org_id NOT NULL REFERENCES organizations(id)
      │                      + UNIQUE (org_id, id)        -- đích cho composite FK
      │                      + INDEX tenants_org_idx (org_id)
      │
      └──< control.users     + org_id   NOT NULL REFERENCES organizations(id)
                             + org_role text NOT NULL DEFAULT 'member'
                                        CHECK IN ('owner','member')
                             + UNIQUE (org_id, id)

control.memberships   + org_id text NOT NULL
  PRIMARY KEY (user_id, tenant_id)                          -- giữ nguyên
  FOREIGN KEY (org_id, user_id)   → users   (org_id, id) ON DELETE CASCADE
  FOREIGN KEY (org_id, tenant_id) → tenants (org_id, id) ON DELETE CASCADE
  (hai FK đơn cột cũ bị drop — composite FK đã bao trùm)
```

`id` của `tenants`/`users` vốn đã là PK nên `UNIQUE (org_id, id)` không thêm ràng buộc mới về tính
duy nhất; nó tồn tại **chỉ** để làm đích hợp lệ cho composite FK.

**Composite FK là điểm chính.** Membership xuyên tổ chức trở thành không chèn được ở tầng
Postgres — không cần trigger, không cần nhớ kiểm trong service, và `psql` tay cũng không đi vòng
được.

Không có bảng permission mới. Enum `role` (`admin | care | editor | viewer`) giữ nguyên.

## 3. Quy tắc quyền — hai dòng

| `org_role` | Thấy gì |
|---|---|
| `owner`  | **Mọi** tenant trong org của mình, không cần `memberships`, quy về `role = 'admin'` |
| `member` | Chỉ tenant có trong `memberships` còn hiệu lực, role như hiện tại |

`org_role` là quyền **trên tổ chức**; `memberships.role` là quyền **trong một workspace**. Hai khái
niệm tách bạch, không suy ra nhau.

Chạm code:

- `repo.liet_ke_workspace()` rẽ nhánh theo `org_role`: `owner` → `SELECT ... FROM tenants WHERE
  org_id = $1 ORDER BY name`, role gán cứng `'admin'`; `member` → giữ nguyên câu JOIN `memberships`
  hiện tại.
- `repo.lay_user()` trả thêm `org_id`, `org_role`.
- `SessionOut` thêm `organization: {id, name}` và `orgRole`.

## 4. RLS không đổi

`org_id` **không** xuống `tenant_data`, **không** vào `portal.current_tenant()`. `tenant_id` vẫn là
khoá cách ly duy nhất. Hệ quả: mọi policy RLS hiện có, `control.enforce_tenant_isolation()`, và
agent pod không phải sửa dòng nào.

Cách ly cross-org được bảo đảm gián tiếp và đủ chặt: user chỉ lấy được `tenant_id` của org mình
(§3), mà không có `tenant_id` thì `SET app.tenant_id` không dẫn tới đâu.

## 5. Dữ liệu

**Migration backfill tối thiểu** — chỉ đủ để siết `NOT NULL`: tạo org `noble` / `"NobleX"`, gán mọi
`tenants` và `users` hiện có vào đó, `memberships.org_id` lấy theo `users.org_id`.

**`dev_seed.py` khai bức tranh đầy đủ**, idempotent UPSERT:

```
noble       NobleX        →  anphu, sunrise
havengroup  Haven Group   →  haven
dang@anphuland.vn         →  org noble, org_role owner
```

`haven` cố ý nằm ngoài `noble`: nó là dữ liệu để kiểm cách ly cross-org, thay cho vai trò cũ của nó
trong seed ("tenant user không có membership"). Vai cũ chuyển sang test dùng fixture user
`org_role = 'member'`, không đổi seed.

## 6. Test

1. `INSERT memberships (org_id='noble', user_id='u_dang', tenant_id='haven')` → **FK violation** ở
   tầng Postgres, không phải lỗi tầng app.
2. `owner` của `noble` → `liet_ke_workspace` trả `anphu` + `sunrise`, role `admin`, dù bảng
   `memberships` rỗng; và **không** trả `haven`.
3. `member` → hành vi y hệt trước. Toàn bộ test `tests/modules/auth/` hiện có phải còn xanh.
4. `DELETE FROM control.organizations WHERE id='noble'` → cascade sạch `tenants`, `users`,
   `memberships` của org đó.
5. `downgrade()` chạy được: drop composite FK, khôi phục FK đơn cột, drop cột, drop bảng.

## 7. Đã cân nhắc và loại

| Phương án | Lý do loại |
|---|---|
| Sửa thẳng `0002`/`0100`/`0101` rồi drop-recreate DB | DB dev đang có dữ liệu; migration đã apply — sửa file cũ là viết lại lịch sử alembic |
| Bảng M:N `control.org_tenants` | Cho phép 1 tenant thuộc nhiều org — không có nhu cầu, YAGNI |
| Không `org_role`, mọi thứ qua `memberships` | Không có ai ở trên để cấp membership đầu tiên |
| `role='admin'` ở bất kỳ tenant nào ⇒ admin toàn org | Trộn quyền-trong-workspace với quyền-trên-org; admin của `anphu` tự nhiên quản được `sunrise` |
| Đưa `org_id` xuống `tenant_data` + RLS theo org | Nhân đôi khoá cách ly, buộc sửa mọi policy và agent pod, đổi lấy con số không |
