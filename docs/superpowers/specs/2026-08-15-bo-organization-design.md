# Bỏ tầng organization — Design

Phạm vi: `odyssey-portal-backend` (chính), `odyssey-portal-frontend`, `odyssey-agent`.

## 1. Vấn đề

`control.organizations` được thêm ở migration `0102_organizations` như một tầng
**trên** `tenants`, với lời hứa nhiều tổ chức cùng vận hành trên một hệ thống.
Lời hứa đó chưa bao giờ thành hiện thực: bảng có **đúng một hàng** (`noble` /
NobleX), không có giao diện tạo tổ chức, và không có đường nào để tổ chức thứ hai
ra đời. Người dùng nhìn thấy tên tổ chức ở đúng một chỗ — `UserMenu.tsx:118` —
và nó không dẫn tới đâu.

Nhưng tầng rỗng nghĩa này không hề miễn phí. Nó đang gánh bốn thứ có thật:

1. **Cổng phân quyền.** `users.org_role = 'owner'` là **cửa thật** của tạo
   workspace (`modules/workspace/service.py:153`), quản trị user
   (`modules/auth/quan_tri_user.py:106`), quản trị vai trò
   (`modules/auth/quan_tri_vai_tro.py:34`), và nhánh "owner đủ 13 action ở mọi
   workspace" (`core/auth/repo.py:102`). Không có nó thì hôm nay không ai tạo
   được workspace.
2. **Khoá ghép trên bốn bảng.** `memberships` FK ghép `(org_id, role_id)`,
   `invites` FK ghép `(org_id, user_id)`, `roles` `UNIQUE (org_id, name)`,
   `tenants`/`users` `UNIQUE (org_id, id)` tồn tại chỉ để làm đích cho hai FK đó.
3. **Trigger seed vai trò.** `organizations_seed_vai_tro` gọi
   `control.seed_vai_tro_mau(p_org)` mỗi lần chèn một org — cho một bảng không
   bao giờ được chèn thêm.
4. **Nhiễu ở bề mặt.** `SessionOut.organization` + `orgRole`,
   `LoiMoiOut.organizationName`, `TaoWorkspaceOut.orgId`, mã lỗi 422
   `ROLE_NOT_IN_ORG`, và một khối dead code ở `odyssey-agent`.

Cái giá thật là ở (1): một cổng phân quyền tựa vào khái niệm không ai dùng thì
không ai đọc ra được nó đang bảo vệ cái gì.

### 1.1 Điều KHÔNG phải vấn đề

Hai chỗ dễ bị đọc nhầm thành rủi ro, đã kiểm và loại:

- **`tenant_id` không mang tiền tố org.** Portal sinh id bằng
  `sinh_tenant_id()` = `slug_tenant(tên)` + hậu tố `_2`..`_50`
  (`modules/workspace/service.py`). Docstring của chính nó ghi rằng spec gốc §7
  đã nhầm khi tưởng phải nhúng `org_id`. Scheme `<org_id>_<slug>` chỉ tồn tại
  trong `odyssey-agent/tenant/identity.py` và **không nằm trên đường serving**:
  `TENANT_RE` không khớp id thật, `loader.py:43` né nhánh store với id không
  org-format, `tenant_store_enabled` mặc định `False`, và plan retire-minio ghi
  "MinIO store + CLI giữ code, chỉ gỡ khỏi serving". ⇒ **Không đổi id tenant nào,
  không di chuyển tệp nào.**
- **RLS không đụng tới.** `org_id` dừng ở schema `control`; nó không xuống
  `tenant_data` và không vào `portal.current_tenant()`. Khoá cách ly vẫn là
  `tenant_id`, đúng một khoá. ⇒ **Không sửa một policy RLS nào.**

## 2. Quyết định thiết kế

**Bỏ tầng tổ chức. Giữ nguyên toàn bộ hệ thống vai trò. Chuyển từ hai trục quyền
xuống một trục.**

Trước: `users.org_role` (quyền TRÊN tổ chức) + `memberships.role_id` (quyền
TRONG một workspace) — hai trục độc lập (`modules/auth/contracts.py:16-18`).

Sau: **một trục duy nhất** — `memberships.role_id`. Không có membership thì
không có quyền, không còn ngoại lệ nào.

Ba việc mà `org_role` đang gánh được giao lại như sau:

| Việc | Trước | Sau |
|---|---|---|
| Tạo workspace | `org_role='owner'` | **Bất kỳ ai có phiên.** Người tạo trở thành "Quản trị" của chính workspace đó |
| Quản trị user toàn hệ thống (`/users*`) | `org_role='owner'` | **Không còn chủ.** Đóng bằng cờ, giữ code (§6.2) |
| Quản trị vai trò (`/roles*` ghi) | `org_role='owner'` | **Không còn chủ.** Đóng bằng cờ, giữ code (§6.2) |
| Đủ 13 action ở mọi workspace | nhánh owner trong `doc_quyen()` | **Bỏ hẳn.** Quyền chỉ đến từ `memberships` |

Người dùng tự đăng ký tài khoản. Đăng nhập xong, nếu chưa thuộc workspace nào thì
được đưa tới màn tạo workspace đầu tiên. Người được mời vào workspace đi qua luồng
invite token đã có, không đổi.

### 2.1 Đánh đổi đã chấp nhận tường minh

- **Vai trò trở thành TOÀN CỤC.** Bỏ `roles.org_id` nghĩa là một bộ 4 vai trò dùng
  chung cho mọi workspace. Đây đúng là điều `0104_vai_tro_dong` cố tình tránh
  ("dùng chung nghĩa là tổ chức A sửa vai trò thì đổi quyền của tổ chức B"). Chấp
  nhận, vì lý lẽ đó chỉ có giá trị khi tồn tại tổ chức thứ hai. Hệ quả bảo mật
  được chặn bằng cờ ở §6.2, không bằng khoá ghép.
- **Không rào chống lạm dụng.** Ai cũng đăng ký được, ai cũng tạo được workspace,
  không giới hạn số lượng. Rào sau nếu có vấn đề. Rủi ro bị chặn một phần bởi
  thực tế `service.tao()` **không** cấp phát hạ tầng — `CREATE ROLE agent_<id>`,
  khoá kho tệp và KB collection là hành động riêng ở `/agent/*`; tạo workspace
  chỉ là một hàng DB. Nhưng người tạo là "Quản trị" nên **có** `WORKSPACE_ADMIN`,
  tức gọi được `/agent/*`. Rủi ro này được ghi nhận, không xử lý ở đợt này.
- **Không có admin hệ thống.** Không ai khoá được tài khoản người khác, không ai
  xoá được workspace của người khác qua UI. Việc đó chuyển sang script vận hành.
- **Tên workspace duy nhất theo NGƯỜI TẠO, không toàn cục.** Vì ai cũng tạo được
  workspace nên hai người lạ đặt tên "Test" là chuyện bình thường; duy nhất toàn
  cục sẽ trả 409 vào mặt người thứ hai mà không giải thích được. `tenants.id` vẫn
  duy nhất toàn cục — `sinh_tenant_id()` giữ nguyên.
- **Giữ ba bảng vai trò dù đang fix cứng.** `roles`, `role_actions`, `actions`
  cùng 5 endpoint CRUD và màn `roles.tsx` được giữ nguyên, chưa dùng tới, để ngỏ
  đường bật quyền động sau này. Đánh đổi: giữ ba bảng cho thứ hiện không đổi.

## 3. Schema

### 3.1 Xoá

| Đối tượng | Nguồn |
|---|---|
| `control.organizations` | `0102_organizations.py` |
| Trigger `organizations_seed_vai_tro` + hàm `control.seed_vai_tro_mau(p_org)` | `0104_vai_tro_dong.py:213-219` |
| `tenants.org_id`, `UNIQUE (org_id, id)`, index `tenants_org_idx` | `0102` |
| `users.org_id`, `UNIQUE (org_id, id)`, `users.org_role` | `0102` |
| `roles.org_id`, `UNIQUE (org_id, id)`, index `roles_org_idx` | `0104:124-132` |
| `invites.org_id` | `0103:80` |
| `audit_log.org_id` | `0103:101` |

### 3.2 Đổi

| Đối tượng | Trước | Sau |
|---|---|---|
| `roles` | `UNIQUE (org_id, name)` | `UNIQUE (name)` |
| `memberships` FK vai trò | ghép `(org_id, role_id) → roles (org_id, id)` (`0104:247-250`) | đơn `role_id → roles (id)` |
| `invites` FK user | ghép `(org_id, user_id) → users (org_id, id)` (`0103:86`) | đơn `user_id → users (id)` |
| Seed 4 vai trò | trigger, mỗi org một bộ | `INSERT` **một lần** trong migration |

### 3.3 Thêm

`tenants.created_by text NOT NULL REFERENCES control.users(id)` — người tạo
workspace. Cột này chưa từng tồn tại; nó vừa thay `org_id` làm phạm vi cho ràng
buộc tên, vừa trả lời câu hỏi "ai mở workspace này" mà trước đây `org_id` trả lời
mơ hồ.

Ràng buộc tên: `UNIQUE (created_by, lower(btrim(name)))` — thay cho phép kiểm
`repo.ten_da_dung(conn, org_id, ten)` hiện tại (`modules/workspace/repo.py:48-66`).

**Backfill `created_by`:** gán cho user có `org_role='owner'` cũ nhất theo
`created_at`. Nếu không tìm được owner nào, migration **phải nổ** — dữ liệu ở
trạng thái đó không có câu trả lời đúng, và im lặng gán bừa là tạo ra một chủ sở
hữu sai mà không ai phát hiện.

**Dedup `roles` trước khi đặt `UNIQUE (name)` — BẮT BUỘC, không phải phòng thủ.**
Production chỉ có org `noble` (4 hàng `roles`), nhưng `scripts/dev_seed.py` dựng
**hai tổ chức** (`noble` + `havengroup`, xem `CLAUDE.md` §Commands) ⇒ trên mọi máy
dev là **8 hàng, 4 cặp trùng tên**. Bỏ `org_id` mà không dedup thì `UNIQUE (name)`
nổ ngay ở `make migrate`.

Thuật toán: với mỗi `name`, giữ hàng `created_at` nhỏ nhất (đồng hạng thì `id` nhỏ
nhất — `created_at` của cùng một lượt seed có thể bằng nhau tới micro giây);
`UPDATE control.memberships SET role_id = <id giữ>` cho mọi `role_id` bị loại;
xoá hàng bị loại (`role_actions` tự rụng theo `ON DELETE CASCADE`).

Thứ tự bắt buộc: dedup → remap `memberships` → drop `org_id` → đặt `UNIQUE (name)`.

⚠ Dedup **giữ ma trận action của hàng được giữ lại và vứt của hàng bị loại**. Hai
org có thể đã sửa vai trò cùng tên theo hai hướng khác nhau; ở dev thì cả hai đều
là bản seed y hệt nên không mất gì. Migration phải `RAISE NOTICE` số hàng đã gộp
để việc này hiện ra trong log, không đi im lặng.

### 3.4 Không đụng

RLS policy, `portal.current_tenant()`, mọi bảng trong `tenant_data`,
`tenants.id`, `sinh_tenant_id()`, đường dẫn kho tệp, `control.role_actions`,
`control.actions`, `memberships.expires_at`.

## 4. Phân quyền sau khi đổi

`core/auth/repo.doc_quyen()` (`core/auth/repo.py:60-104`) bỏ hai thứ:

- Mệnh đề `EXISTS (... t.org_id = u.org_id) AS cung_to_chuc`
- Nhánh `if r["org_role"] == "owner" and r["cung_to_chuc"]: return ... ALL_ACTIONS`

Còn lại: `users.lifecycle` + `LEFT JOIN memberships → roles → role_actions`. Ai
không có hàng `memberships` hợp lệ cho `tenant_id` đang xét thì không có action
nào. Vị từ `expires_at IS NULL OR expires_at > now()` **giữ nguyên trong `ON`**,
không chuyển sang `WHERE` — lý do đã ghi trong docstring hiện tại và vẫn đúng.

`HangQuyen.org_role` bị xoá khỏi dataclass; mọi nơi đọc nó phải sửa theo.

## 5. Luồng

### 5.0 Phiên KHÔNG workspace trở thành trạng thái HỢP LỆ (đảo ngược PQ_01 Q01)

⚠ **Bổ sung sau khi soát code, không có trong bản duyệt đầu.** Hôm nay "phiên
không có workspace nào" là trạng thái **hỏng**, và ba chỗ cưỡng chế điều đó:

- `loi.khong_co_workspace()` — `NO_WORKSPACE`, **409**, docstring ghi thẳng
  "PQ_01 Q01: phiên không có workspace nào là trạng thái HỎNG, không phải rỗng"
- `service.dang_nhap()` raise nó **trước khi tạo phiên**
- `service.dung_session_out()` raise nó ở `/me`
- `ss.BanGhiPhien.tenant_id: str` — không nhận `None`

Điều đó đúng khi user chỉ ra đời qua lời mời (được mời **vào một workspace**).
Với tự đăng ký thì nó là ngõ cụt: người vừa đăng ký có **0** workspace, đăng nhập
ăn 409, và không có đường nào tới màn tạo workspace. Không sửa chỗ này thì §5.1 và
§5.4 không chạy được.

Đổi:

| Chỗ | Trước | Sau |
|---|---|---|
| `ss.BanGhiPhien.tenant_id` | `str` | `str \| None` |
| `ss.tao(r, *, user_id, tenant_id)` | `tenant_id: str` | `tenant_id: str \| None` |
| `service.dang_nhap` | 0 workspace ⇒ 409 | 0 workspace ⇒ phiên với `tenant_id=None` |
| `service.dung_session_out` | 0 workspace ⇒ 409 | trả `workspaces=[]`, `currentWorkspaceId=None`, `actions=[]` |
| `SessionOut.currentWorkspaceId` | `str` | `str \| None` |
| `require(action)` | luôn gọi `doc_quyen(user, tenant)` | `tenant_id is None` ⇒ bỏ qua `doc_quyen`, kiểm `users.lifecycle` riêng rồi `thieu_quyen(action, None)` |

`loi.khong_co_workspace()` **giữ lại** — `POST /me/workspace` vẫn cần nó khi ai đó
đổi sang một workspace họ không thuộc. Chỉ hai chỗ raise ở trên là bỏ; docstring
của hàm lỗi phải viết lại vì lý lẽ PQ_01 Q01 không còn đúng.

`require()` với `tenant_id is None` phải kiểm `lifecycle` **riêng** — không được
bỏ qua: một tài khoản bị đình chỉ mà chưa có workspace vẫn phải bị đẩy về `/login`
(401 + xoá phiên), không phải nhận 403.

### 5.1 Đăng ký (mới)

`POST /api/v1/auth/register` nhận `{email, name, password}`, tạo hàng `users` với
`lifecycle='active'` và không thuộc workspace nào. Trùng email trả 409. Không xác
thực email ở đợt này.

Endpoint này khai `require(None, ly_do="...")` — luật 4 của repo buộc **mọi**
route khai action của nó, và cổng `tests/unit/test_moi_route_khai_action.py` canh
điều đó. Cùng khuôn với `/auth/login` và `/invites/accept`, vốn đã dùng dạng
`require(None, ly_do=...)` vì cùng lý do: chính chúng là đường tạo ra phiên hoặc
mật khẩu đầu tiên, đòi phiên là vòng tròn.

### 5.2 Tạo workspace

`POST /api/v1/workspaces` — cổng chỉ còn "có phiên hợp lệ". `service.tao()`
(`modules/workspace/service.py`) đổi hai chỗ:

- Bỏ khối `if actor is None or actor.org_role != "owner": raise khong_du_quyen()`
- **Ghi một hàng `memberships`** `(user_id=actor_id, tenant_id, role_id=<id của
  "Quản trị">, expires_at=NULL)` trong cùng giao dịch.

Điểm thứ hai là đảo ngược có chủ ý một quyết định cũ: docstring hiện tại ghi
"KHÔNG ghi `control.memberships`" vì owner đã có toàn quyền qua nhánh owner. Nhánh
đó bị bỏ ở §4, nên nếu không ghi membership thì người vừa tạo workspace sẽ không
vào được chính nó.

`role_id` của "Quản trị" tra bằng `SELECT id FROM control.roles WHERE name = 'Quản
trị'`, không suy bằng md5 — cùng lý lẽ mà `0104:162-170` đã ghi: hàng thật có thể
mang id `uuid4()` nếu từng bị xoá và tạo lại qua API. Không tìm thấy hàng nào ⇒
**500, không phải tạo workspace không có membership**: một workspace mà chính
người tạo không vào được là trạng thái hỏng câm. Cờ `ROLES_CRUD_ENABLED=false`
(§6.2) làm tình huống này không xảy ra được từ UI, nhưng `DELETE` thẳng DB thì có.

Không cấp phát hạ tầng, giữ nguyên như hiện tại.

### 5.3 Mời người vào workspace

Không đổi. `POST /api/v1/members` gate `require(ACTIONS.WORKSPACE_ADMIN)`, luồng
invite token (`GET /invites/{token}`, `POST /invites/accept`) giữ nguyên.

Bỏ gate `_kiem_role_thuoc_to_chuc` và mã lỗi 422 `ROLE_NOT_IN_ORG`: vai trò đã
toàn cục nên mọi `role_id` tồn tại đều hợp lệ. Kiểm còn lại là "role_id có tồn tại
không" → 422 với mã mới `ROLE_NOT_FOUND`.

### 5.4 Màn hình đầu tiên

Sau đăng nhập, nếu user không có hàng `memberships` nào, FE đưa tới màn "Tạo
workspace đầu tiên" thay vì dashboard rỗng.

## 6. Bề mặt API và FE

### 6.1 Xoá trường khỏi contract

| Trường | Nơi |
|---|---|
| `SessionOut.organization`, `SessionOut.orgRole` | `modules/auth/service.py:61-62`, `contracts.py`, `fake.py:61` |
| `OrgRole = Literal["owner","member"]`, `TaoUserIn.orgRole` | `modules/auth/contracts.py:16,242,257` |
| `LoiMoiOut.organizationName` | `modules/auth/quan_tri_user.py:322` |
| `TaoWorkspaceOut.orgId` | `modules/workspace/contracts.py:52` |
| FE `Organization`, `Session.organization` | `src/lib/session.tsx:55,70` |
| FE hiện tên tổ chức | `src/components/shell/UserMenu.tsx:118` |
| FE `NhanLoiMoi` prop `toChuc` | `src/features/auth/components/NhanLoiMoi.tsx:70,79,84,118` |
| FE `TaoWorkspaceKetQua.orgId` | `src/features/workspace/api.ts:47` |
| MSW `FAKE_SESSION.organization`, `organizationName` | `src/lib/msw/handlers.ts:26,1098` |

`NhanLoiMoi` mất tên tổ chức thì câu mời đọc là "Bạn được mời tham gia" — không
thay bằng tên workspace, vì lời mời ở màn đó được nhận **trước** khi có phiên và
người nhận chưa có ngữ cảnh workspace nào.

### 6.2 Hai khối endpoint mất chủ — giữ code, đóng cổng bằng cờ

Bỏ `org_role` làm mất cửa thật của hai khối. Chúng **không** bị xoá; chúng bị
đóng, để ngỏ đường bật lại khi có mô hình quyền động.

| Khối | Endpoint | Xử lý |
|---|---|---|
| Ghi vai trò | `POST /roles`, `PATCH /roles/{id}`, `DELETE /roles/{id}` | cờ `ROLES_CRUD_ENABLED`, mặc định `false` → 403 |
| Đọc vai trò | `GET /roles`, `GET /roles/{id}`, `GET /actions` | **vẫn mở** — FE cần để render dropdown vai trò |
| Quản trị user | 6 đường `/users*` (`router.py:217-279`) | cờ `USERS_ADMIN_ENABLED`, mặc định `false` → 403 |

Route FE `users.tsx` ẩn khỏi `src/lib/nav-registry.ts`; file và test giữ nguyên.
Route `roles.tsx` giữ nguyên và vẫn vào được (chỉ đọc).

Cờ đọc từ settings, đặt cạnh các cờ hiện có. Kiểm cờ nằm ở tầng service, không ở
router — cùng khuôn với `_lay_owner()` mà nó thay thế.

## 7. odyssey-agent — xoá dead code

Không thay đổi hành vi, chỉ gỡ code đã chứng minh là không chạy (§1.1):

`tenant/identity.py`: `ORG_RE`, `is_valid_org_id`, `new_org_id`, `new_tenant_id`,
`org_of` — xoá cả file nếu không còn gì; `TENANT_RE` giữ nếu còn ai kiểm định dạng.
`tenant/store.py`: `_prefix()` trả thẳng `tenant_id` (bỏ tiền tố org), `list_orgs`,
`migrate_legacy_layout` — xoá. `tenant/provisioning.py`: bỏ tham số `org_id` ở
`provision_tenant`, `list_tenants`; xoá `list_orgs`. `tenant/current.py:56`,
`tenant/cli.py:217-232` (lệnh `tenant new-org`, cờ `--org`).

Test xoá theo: `tests/unit/tenant/test_provisioning_org.py`,
`test_org_isolation.py`; sửa `test_identity.py`, `test_loader.py`.

⚠ Đường legacy phải giữ **byte-identical** — đây là ràng buộc mà plan retire-minio
đã đặt và vẫn còn hiệu lực. Nếu gỡ `_prefix` làm đổi object key của một tenant
đang sống, dừng lại: giữ nguyên `store.py` và chỉ gỡ phần định danh.

## 8. `require()` đã cưỡng chế action — chỉ còn comment lỗi thời phải dọn

⚠ **Đính chính so với bản nháp trước của spec này.** Ba comment trong repo nói
rằng `require()` mới chỉ kiểm "có phải thành viên không" và M2b sẽ bật ma trận
sau — `modules/auth/router.py:191-193`, `modules/auth/quan_tri_user.py:12,17`, và
docstring đầu `core/auth/require.py`. **Cả ba đã lỗi thời.** Thân hàm `_kiem()`
hiện tại (`core/auth/require.py`) có đúng dòng cưỡng chế:

```python
if action not in q.actions:
    raise loi.thieu_quyen(action, q.role_name)
```

kèm comment tại chỗ ghi "M2b: ma trận đã BẬT". Ma trận vai trò **đang chạy thật**.

Hệ quả cho đợt này: **không có bước "bật cưỡng chế action" nào phải làm.** Việc
duy nhất còn lại là sửa ba comment lỗi thời trên cho khớp sự thật — chúng nguy
hiểm đúng theo kiểu khó thấy nhất: người đọc kết luận hệ thống đang hở và đi vá
một lỗ không tồn tại, hoặc tệ hơn, tin rằng có một cổng chưa bật nên không dám gỡ
`org_role`.

Điều **thật sự** thay đổi hành vi khi bỏ `org_role` nằm ở `doc_quyen()`, không ở
`require()`: hôm nay nhánh owner trả `ALL_ACTIONS` bất kể có hàng `memberships`
hay không. Bỏ nhánh đó (§4) ⇒ owner cũ mất toàn quyền ở những workspace họ chưa
từng được thêm vào. Đây là lý do §5.2 buộc `service.tao()` phải ghi membership:
không có nó, người vừa tạo workspace rơi vào đúng cái lỗ này.

Kèm theo, `Principal.role` hiện rơi về chuỗi `"Chủ tổ chức"` khi `role_name` là
`None` (`core/auth/require.py`, cuối `_kiem`). Sau khi bỏ nhánh owner, `role_name`
chỉ `None` khi không có membership — mà trường hợp đó đã bị `action not in
q.actions` chặn từ trước. Bỏ giá trị mặc định đó, để `Principal.role` là `str`.

## 9. Migration

Hai migration, chạy theo thứ tự. Head hiện tại xác định bằng `alembic heads` lúc
thi công — **không đoán trước ở spec này**, và `revision` id khác tên file theo
quy ước repo (`CLAUDE.md` §Migration). Hai MR song song cùng nhận một cha ⇒ hai
head ⇒ gãy cho cả team; đã xảy ra ba lần (`0914`, `0919`, `0920`). A và B phải
nối tiếp nhau, B lấy A làm `down_revision`.

**A — vai trò:** dedup `roles` theo `name` → remap `memberships.role_id` → drop FK
ghép `memberships_role_cung_to_chuc_fkey`, dựng FK đơn `role_id → roles(id)` →
drop FK ghép của `invites`, dựng FK đơn `user_id → users(id)` → **drop
`invites.org_id`** → drop `roles.org_id`, `UNIQUE (org_id, name)`,
`UNIQUE (org_id, id)`, index `roles_org_idx` → đặt `UNIQUE (name)` → drop trigger
`organizations_seed_vai_tro` và hàm `control.seed_vai_tro_mau(text)`.

**B — tổ chức:** thêm `tenants.created_by` (nullable) → backfill từ owner cũ nhất,
nổ nếu không có → `SET NOT NULL` → `UNIQUE (created_by, lower(btrim(name)))` →
drop `org_id` khỏi `tenants`/`users`/`audit_log` cùng các `UNIQUE (org_id, id)` và
index `tenants_org_idx` → drop `users.org_role` → `DROP TABLE control.organizations`.

`downgrade()` viết đầy đủ cho cả hai.

⚠ `downgrade` là nơi mất mát không đảo ngược được, phải nói thẳng trong docstring
của từng file: B dựng lại org `noble` và gán **mọi** hàng về nó (cùng lý lẽ
backfill của `0102`) — nhưng nếu dữ liệu sinh ra sau khi upgrade có nhiều người
tạo workspace độc lập, `downgrade` **gom tất cả vào một tổ chức**, và
`UNIQUE (org_id, lower(name))` cũ có thể nổ vì hai người đã đặt trùng tên hợp lệ.
A tương tự: hàng `roles` bị dedup không dựng lại được. Kết luận thực dụng —
`downgrade` chỉ dùng được ngay sau `upgrade` trên máy dev, không phải đường lùi
cho production. Ghi câu này vào docstring, đừng để người sau tự phát hiện.

## 10. Test

**Backend.** Sửa: `tests/modules/auth/conftest.py`, `test_vai_tro.py`,
`test_tao_user.py`, `test_pending.py`, `test_login.py`, `test_repo.py`,
`test_contracts_user.py`, `test_schema.py`, `tests/modules/workspace/conftest.py`,
`test_tao.py`, `tests/api/test_core_auth_repo.py`,
`tests/integration/test_seed_owner.py`, `test_control_schema.py`.
Xoá: `tests/modules/auth/test_to_chuc.py`, `test_repo_vai_tro_org_scope.py`,
`test_migration_0104.py` (viết lại cho hình dạng mới).
Thêm: test migration A/B (dedup, backfill, nổ khi thiếu owner), test đăng ký, test
`tao()` ghi membership 'Quản trị', test hai cờ trả 403, test `require()` cưỡng chế
action cho cả 4 vai trò.

**Frontend.** Sửa: `dang-xuat.test.tsx:133,146`, `shell.test.tsx:325`,
`nhan-loi-moi.test.tsx:48,86`, `tao-workspace.test.tsx:30`,
`thanh-vien-seam.test.ts:101` (422 `ROLE_NOT_IN_ORG` → `ROLE_NOT_FOUND`).
Thêm: test trang đăng ký, test màn tạo workspace đầu tiên.

**Agent.** Xoá `test_provisioning_org.py`, `test_org_isolation.py`; sửa
`test_identity.py`, `test_loader.py`.

## 11. Script và tài liệu

**`scripts/dev_seed.py` phải viết lại, không chỉ sửa.** Bộ seed hiện tại dựng
"3 user · 3 workspace · **2 tổ chức**", và bất biến mà nó dạy là *"`haven@haven.vn`
thuộc org khác nên **không** hiện trên switcher của `dang`"* (`CLAUDE.md`
§Commands). Bất biến đó biến mất cùng org. Thay bằng bất biến mới, mạnh tương
đương và đúng với mô hình mới: **`haven` không có hàng `memberships` nào ở
`anphu`/`sunrise` nên không thấy hai workspace đó.** Cách ly giờ do `memberships`
canh, không do org. Ba tài khoản và mật khẩu giữ nguyên để tài liệu và thói quen
của team không phải học lại.

`scripts/nap_du_lieu_tu_odyssey.py`, `scripts/seed_kho_tep.py` bỏ tham chiếu org.
`src/portal/cli/seed_owner.py` giữ lại như đường tạo user đầu tiên cho dev, bỏ
phần org; cân nhắc đổi tên (`seed_owner` không còn nghĩa khi không còn "owner"),
nhưng đó là việc của plan, không phải ràng buộc của spec.

`core/nhat_ky.py` bỏ tham số `org_id` ở cả hai hàm ghi. Hai hàm vẫn giữ nguyên là
**hai hàm** — lý lẽ tách chúng (docstring `nhat_ky.py:46`) không liên quan tới org.

Cập nhật: `CLAUDE.md` (§Commands dòng `make dev-seed` + tài khoản seed, §Kiến trúc
bảng `control`, và một dòng Change Log — theo luật tự bảo trì của chính file đó),
`SPEC-DB-HIEN-TAI.md`, `PHAN-TICH-THIET-KE-DB.md`, `docs/architecture/*`, và
`CLAUDE.md` của hai repo kia nếu có nhắc org.

Spec cũ `2026-08-03-organization-level-above-tenant-design.md` và plan tương ứng
đánh dấu **đã bị thay thế** bởi tài liệu này — không xoá, chúng là hồ sơ vì sao
tầng đó từng tồn tại.

Không đụng `make contracts`: `actions.json` sinh từ `core/auth/actions.py`, mà 13
action không đổi. `tools.json`/`agent-config.json` không liên quan.

## 12. Ngoài phạm vi

- Rào chống lạm dụng đăng ký (giới hạn số workspace, mã mời, duyệt) — quyết định
  rào sau nếu cần
- Xác thực email khi đăng ký
- Quyền động (bật `ROLES_CRUD_ENABLED` và thiết kế cổng cho nó)
- Xoá / khoá workspace và user qua UI
- Đổi định dạng `tenants.id`
