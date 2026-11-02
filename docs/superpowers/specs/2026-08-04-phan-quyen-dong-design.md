# M2b-quyền — Phân quyền động: vai trò lưu trong CSDL

> **Ngày:** 2026-08-04 · **Trạng thái:** chờ duyệt
> **Giải quyết:** ma trận `role × action` còn treo từ M2a (`require.py` đang trả `ALL_ACTIONS`)
> **Sửa đổi có chủ đích với tài liệu đã chốt:** PQ_01 §III *"4 vai trò cố định, không cho tự
> định nghĩa"* — §1.1 dưới đây ghi lý do và điều kiện.

---

## 0. Một câu

Vai trò trở thành **dữ liệu trong CSDL, thuộc về từng tổ chức**, quản trị viên tổ chức tự tạo ·
sửa · xoá bằng cách tích 13 ô quyền; `require(action)` bật lên tra ma trận đó thay vì cho qua tất.

## 1. Vì sao — và cái gì KHÔNG đổi

Hôm nay `require()` khai đúng trên mọi endpoint nhưng thân hàm dựng `actions=ALL_ACTIONS`. Hệ quả
thật, không phải lý thuyết: **một `viewer` gọi được mọi API ghi.** Cách ly workspace (tầng 1) vẫn
chặn họ đọc dữ liệu tổ chức khác, nhưng trong tổ chức của mình họ xoá được dự án. Đây là đúng lỗ
hổng PQ_01 §II.2.1 mô tả — *"tầng 1 không thay được tầng 2"*.

### 1.1 Sửa đổi với PQ_01 §III

PQ_01 chốt 4 vai trò cố định, và lý lẽ của nó tốt: vai trò tự định nghĩa hay đẻ ra 15 vai trò gần
giống nhau mà không ai nhớ khác nhau chỗ nào. Quyết định 2026-08-04 của người quyết định là **nhận
rủi ro đó để đổi lấy tính linh hoạt**: khách hàng thật có cơ cấu khác nhau, và mỗi lần họ cần một
vai trò mới mà phải chờ NobleX deploy là một lần bán hàng khó.

4 vai trò của PQ_01 §2.2 **vẫn được seed cho mọi tổ chức mới** — chúng là điểm khởi đầu tốt và phủ
phần lớn nhu cầu. Khác biệt duy nhất: chúng là **dữ liệu thường**, sửa · đổi tên · xoá được như
mọi hàng khác. Không có cờ `is_system`, không có vai trò khoá.

### 1.2 Cái KHÔNG đổi — và vì sao

| Không đổi | Vì sao |
|---|---|
| **13 nhóm hành động** của PQ_01 §3.1 | Đủ mịn cho hôm nay. Tách một ô thành hai sau này là một migration + đổi `require()` của vài endpoint — không phải viết lại gì |
| **Danh mục action khai trong code** (`actions.py`) | `require(ACTIONS.CATALOG_WRITE)` là hằng số trong code. Một action tạo từ UI mà không endpoint nào dùng là một ô tích không làm gì |
| **Cách ly tenant (RLS · `current_tenant()`)** | Đây là tầng 1. Spec này chỉ chạm tầng 2 |
| **`org_role ∈ (owner, member)`** | Quyền-trên-tổ chức khác quyền-trong-workspace. `0102` §7 đã loại phương án gộp |
| **Mọi endpoint hiện có** | `require()` đổi ruột, chữ ký giữ nguyên |
| **Tên hàm · biến Python tiếng Việt** | Lề của repo. Chỉ **cột CSDL** dùng tiếng Anh — khớp `lifecycle`, `password_hash`, `token_hash` đã có |

### 1.3 Phương án đã cân nhắc và loại

| Phương án | Lý do loại |
|---|---|
| Tích **từng quyền lẻ** cho từng user × từng workspace (ACL trực tiếp) | 13 ô × N workspace cho MỖI người. Không sửa được quyền cả nhóm cùng lúc; đổi chính sách là sửa tay từng người |
| Giữ 4 vai trò cố định, chỉ bật ma trận trong code | Ít việc nhất, nhưng không đáp ứng yêu cầu không hardcode, tự tạo được |
| Vai trò **dùng chung toàn hệ thống**, tổ chức sửa được | Tổ chức A sửa vai trò ⇒ đổi quyền của tổ chức B. Rò rỉ chính sách giữa hai khách hàng |
| Đưa danh mục action vào CSDL làm **nguồn**, code đọc từ đó | App khởi động phải chờ CSDL để biết action nào tồn tại; gõ sai tên action thành lỗi lúc chạy thay vì lỗi lúc khởi động. Mất đúng cái `require()` đang bảo vệ |
| Cache `actions` vào phiên đăng nhập | PQ_01 §BR-Q04: CMS cũ làm vậy nên *"sa thải xong 15 phút nữa họ vẫn sửa được"*. Và ở đây còn tệ hơn — bỏ tích một ô mà 15 phút sau mới có tác dụng |

---

## 2. Schema

Migration `0104_vai_tro_dong`, `revision = "0104_vai_tro_dong"`,
`down_revision = "0103_user_ho_so_invite"` (head hiện tại).

```
control.actions                     ← DANH MỤC 13 quyền. Bản sao đọc của actions.py
  code         text PRIMARY KEY     -- 'catalog.write' … khớp ALL_ACTIONS
  group_name   text NOT NULL        -- 'operate' | 'knowledge' | 'configure'
  label_vi     text NOT NULL        -- 'Thêm · sửa Dự án · Quỹ căn · Tài liệu · Media'
  label_en     text NOT NULL
  sort_order   int  NOT NULL        -- 1..13, đúng thứ tự bảng PQ_01 §3.1
  UNIQUE (sort_order)

control.roles                       ← VAI TRÒ, thuộc về từng tổ chức
  id           text PRIMARY KEY
  org_id       text NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
  name         text NOT NULL
  description  text
  created_at   timestamptz NOT NULL DEFAULT now()
  UNIQUE (org_id, name)             -- không hai vai trò trùng tên trong một tổ chức
  UNIQUE (org_id, id)               -- đích cho composite FK bên dưới
  INDEX roles_org_idx (org_id)

control.role_actions                ← Ô ĐÃ TÍCH
  role_id      text NOT NULL REFERENCES roles(id)      ON DELETE CASCADE
  action_code  text NOT NULL REFERENCES actions(code)  ON DELETE RESTRICT
  PRIMARY KEY (role_id, action_code)

control.memberships                 ← ĐỔI CỘT
  role text  →  role_id text NOT NULL
  FOREIGN KEY (org_id, role_id) → roles (org_id, id) ON DELETE RESTRICT
  (CHECK role ∈ (admin,care,editor,viewer) bị drop cùng cột)
```

### 2.1 Năm quyết định trong schema này

**`roles.org_id` + composite FK `(org_id, role_id)`.** Cùng lý lẽ `0102` đã ghi cho `memberships`:
gán vai trò của tổ chức khác trở thành **không chèn được ở tầng Postgres**. Không cần trigger,
không cần nhớ kiểm trong service, `psql` tay và seed script cũng không đi vòng được.

**Không có cột `is_system` / `is_locked`.** 4 vai trò mẫu là 4 hàng `roles` như mọi hàng khác. Thêm
cờ khoá là mở lại đúng cuộc tranh luận §1.1 đã khép, và đẻ ra một nhánh vai trò không sửa được
mà UI phải xử lý riêng.

**`memberships.role_id` dùng `ON DELETE RESTRICT`, không `CASCADE`.** `CASCADE` sẽ **xoá luôn tư
cách thành viên** của người đang làm việc khi ai đó xoá vai trò — tức đá họ khỏi workspace, im lặng.
`RESTRICT` biến việc đó thành một câu hỏi phải trả lời: *chuyển 3 người này sang vai trò nào?*

**`role_actions.action_code` cũng `RESTRICT`.** Gỡ một action khỏi danh mục trong khi vai trò còn
tích nó là làm rơi quyền của người thật. Gỡ action là việc của một migration có chủ đích, phải
`DELETE FROM role_actions` trước — và như vậy nó hiện ra trong diff.

**`actions.code` là `text` không phải enum Postgres.** Thêm action = `INSERT`, không phải
`ALTER TYPE`. Enum ở Postgres không xoá giá trị được, nên nó là chiều một-đường.

**Tổ chức mới nhận 4 vai trò mẫu bằng TRIGGER, không bằng lời nhắc trong tài liệu.**
`0104` ship `control.seed_vai_tro_mau(org_id)` + trigger `AFTER INSERT ON control.organizations`.
Backfill tổ chức cũ gọi **đúng hàm đó**, nên hai đường không lệch được.

Quyết định 2026-08-04, sau khi soát kế hoạch phát hiện: nếu chỉ backfill, tổ chức tạo **sau**
migration sẽ có **0 vai trò** — owner của khách hàng mới đăng nhập lần đầu, thấy dropdown rỗng, và
không ai gán được quyền cho ai. Đặt ở trigger chứ không ở service vì hôm nay **chưa có API tạo tổ
chức** (thuộc M9): org sinh ra từ `dev_seed`, từ migration, và từ `psql` tay. Chỉ trigger phủ được
cả ba, và khi M9 có API thì nó không phải nhớ gọi gì.

**`roles.id` sinh bằng `uuid4().hex`, không suy từ tên.** M2b sinh `user_id` từ local-part của
email vì email là bất biến; tên vai trò thì **đổi được**. Suy id từ tên sẽ tạo ra `bien_tap` mang
tên *Trưởng phòng* sau lần đổi thứ nhất — một id nói dối. `UNIQUE (org_id, name)` lo phần chống
trùng, id chỉ cần ổn định.

### 2.2 Bảng `actions` là bản sao đọc, không phải nguồn

Nguồn vẫn là `portal/core/auth/actions.py`. `control.actions` tồn tại để làm **hai** việc mà code
không làm được: cho UI nhãn tiếng Việt/Anh có thứ tự, và cho `role_actions` một FK thật.

Đồng bộ bằng migration seed. Cổng canh: `SELECT code FROM control.actions` phải **bằng đúng**
`ALL_ACTIONS` — lệch một chiều nào cũng CI đỏ. Thêm action mới = thêm hằng số vào `actions.py` +
một dòng seed trong cùng PR, và `make contracts` cho FE.

---

## 3. Cưỡng chế

### 3.1 Đổi đúng một chỗ

`portal/core/auth/require.py` đã chừa sẵn `# ◄── M2b ĐỔI ĐÚNG DÒNG NÀY`:

```python
# trước
return Principal(user_id=..., tenant_id=..., role=m.role, actions=ALL_ACTIONS)

# sau
return Principal(user_id=..., tenant_id=..., role=q.role_name, actions=q.actions)
```

Không endpoint nào sửa. Không nav item nào sửa. 13 `require(ACTIONS.X)` đã rải khắp M4–M8 từ ngày
đầu — đây là chỗ khoản đầu tư đó trả về.

`Principal.role` đổi nghĩa: từ mã cố định (`admin`) sang **tên vai trò do người dùng đặt**
(`Trưởng nhóm CSKH`). Docstring phải nói rõ — nó chỉ dùng để hiển thị trong thông điệp lỗi, không
để quyết định gì.

**Việc bắt buộc đi kèm:** rà `grep -rn '\.role\b' src/ tests/` và sửa mọi chỗ so sánh
`p.role == 'admin'`. Mỗi chỗ như vậy là một phép kiểm quyền **đi vòng qua `require()`** — nó sẽ
âm thầm sai ngay khi ai đó đổi tên vai trò. Thay bằng `ACTIONS.X in p.actions`. Nếu grep ra 0 kết
quả thì ghi lại con số đó trong PR: *"đã rà, không có chỗ nào"* — im lặng không phân biệt được với
quên rà.

### 3.2 Một truy vấn, thay cho hai

`repo.doc_quyen(conn, user_id, tenant_id)` gộp cả `doc_lifecycle` + `doc_membership` hiện đang là
hai lượt:

```sql
SELECT u.lifecycle,
       u.org_role,
       r.name AS role_name,
       coalesce(
         array_agg(ra.action_code) FILTER (WHERE ra.action_code IS NOT NULL),
         '{}'
       ) AS actions
FROM control.users u
LEFT JOIN control.memberships m  ON m.user_id = u.id
                                AND m.tenant_id = $2
                                AND (m.expires_at IS NULL OR m.expires_at > now())
LEFT JOIN control.roles r        ON r.id = m.role_id
LEFT JOIN control.role_actions ra ON ra.role_id = m.role_id
WHERE u.id = $1
GROUP BY u.lifecycle, u.org_role, r.name
```

**Vị từ `expires_at` phải nằm trong `ON`, không phải `WHERE`.** Đặt ở `WHERE` biến `LEFT JOIN`
thành `INNER JOIN` một cách âm thầm: user không có membership sẽ mất luôn hàng, và bước 2 (owner)
không bao giờ chạy tới. Đây là chỗ hỏng kinh điển của việc gộp hai truy vấn thành một.

Kết quả: **ít hơn một round-trip so với hôm nay**, dù làm nhiều việc hơn. Đi trong transaction mà
ràng buộc cách ly đã bắt buộc phải có.

Thứ tự xử lý trong `require()` giữ nguyên ngữ nghĩa hiện có:

```
1. lifecycle ≠ 'active'  → xoá phiên, 401   (đình chỉ là chuyện danh tính)
2. org_role = 'owner'    → actions = ALL_ACTIONS, role_name = 'Chủ tổ chức'
3. không có membership   → 403
4. ngược lại             → actions từ truy vấn (có thể rỗng)
```

### 3.3 Owner không đi qua ma trận — và vì sao đó là điểm chính

`org_role='owner'` ⇒ đủ 13 action ở **mọi** workspace của tổ chức, không cần hàng `memberships`.

Đây không phải cửa sau: `0102` §3 đã chốt owner thấy mọi workspace dù `memberships` rỗng; spec này
chỉ nói tiếp phần quyền của cùng một quy tắc. Vẫn là **một** đường kiểm tra trong `require()`, chỉ
khác nguồn của tập action.

**Hệ quả quan trọng: sửa vai trò không bao giờ khoá cửa được.** Một owner bỏ tích cả 13 ô của mọi
vai trò thì chính họ vẫn vào được và sửa lại. Nhờ vậy toàn bộ màn Vai trò **không cần luật an
toàn nào** — chỉ màn Người dùng cần, và luật đó đã có từ M2b §3.2.

### 3.4 403 phải nói lý do

PQ_01 §3 phi chức năng: *"người dùng thấy lý do bị chặn, không phải một nút xám vô nghĩa"*.

```json
{
  "ma": "FORBIDDEN",
  "thong_diep": "Việc này cần quyền Thêm · sửa Dự án · Quỹ căn. Vai trò của bạn ở An Phú Land là Người xem.",
  "chi_tiet": { "action": "catalog.write", "role": "Người xem" }
}
```

`label_vi` trong thông điệp lấy từ `control.actions` — đó là việc thứ hai bảng đó tồn tại để làm.

### 3.5 Đọc mỗi request, không cache

Bỏ tích một ô ⇒ request **kế tiếp** của người đó bị chặn. Không có cửa sổ 15 phút. Mất kết nối CSDL
⇒ từ chối, không cho qua (PQ_01 §3: *"quyền là thứ duy nhất hỏng theo chiều đóng"*).

### 3.6 `SessionOut.actions` phải truyền từ `Principal` — HAI chỗ, một PR

Thêm 2026-08-04 sau review Task 2. Bản đầu của spec ngầm giả định `SessionOut.actions` tự hẹp lại
khi ma trận bật. **Sai.** `service.py::_dung_session_out` dựng nó từ hằng số `ALL_ACTIONS`; đổi
`require()` không chạm tới dòng đó. Docstring của `contracts.py` đã ghi đúng từ trước:
*"M2b đổi hai chỗ trong cùng một PR"*.

Bỏ chỗ thứ hai thì một Người xem thấy đủ mọi mục nav và mọi nút quản trị, bấm cái nào cũng 403 —
tức đúng cái nghịch lý mà §3.4 tồn tại để tránh. Shell FE không phải sửa gì; nó đã ẩn theo
`session.actions` từ M2a.

### 3.7 Là thành viên không phải có quyền — `doi_workspace`

Cũng từ review Task 2. `POST /me/workspace` không được dùng `actions` rỗng làm phép kiểm tư cách
thành viên: một vai trò bỏ tích cả 13 ô là **trạng thái hợp lệ** mà màn Vai trò cố ý cho phép. Dùng
`actions` thì người đó thấy workspace trên switcher rồi bấm vào ăn 403 — đúng khoảng lệch mà
`0102` §3 đã cảnh báo.

`HangQuyen` mang thêm `co_membership: bool` (`m.user_id IS NOT NULL`). Không dùng
`role_name is not None` thay thế: owner hợp lệ có `role_name = None`.

---

## 4. Hợp đồng API

Sáu endpoint ở `modules/auth/`. Tất cả khai `require(ACTIONS.WORKSPACE_ADMIN)` để qua cổng 1, rồi
kiểm `org_role = 'owner'` trong service — đúng khuôn M2b §3.1.

| Endpoint | Trả về · ghi chú |
|---|---|
| `GET /actions` | 13 ô: `code · groupName · labelVi · labelEn · sortOrder`. Để FE vẽ form |
| `GET /roles` | danh sách vai trò của tổ chức + **`userCount`** mỗi cái |
| `GET /roles/{id}` | chi tiết + mảng `actions` |
| `POST /roles` | `{name, description, actions[]}` |
| `PATCH /roles/{id}` | `actions` là **THAY THẾ TOÀN BỘ** |
| `DELETE /roles/{id}` | 409 nếu `userCount > 0` |

**`userCount` không phải trang trí.** Không có nó thì nút Xoá là một cái bẫy: người dùng bấm, nhận
409, và không biết phải làm gì tiếp.

**`PATCH` thay thế toàn bộ, không cộng dồn** — cùng lý lẽ M2b §4.4 đã dùng cho memberships. Form là
13 checkbox người dùng sửa trực tiếp; diễn dịch nó thành chuỗi add/remove ở FE là đặt logic hoà giải
vào chỗ không có transaction, và hai tab mở cùng lúc sẽ trộn ra một tập quyền không ai chọn.
Service `DELETE` mọi `role_actions` của vai trò rồi `INSERT` lại, trong một `conn.transaction()`.

**Vai trò 0 quyền được phép.** Đó là *đã tạo, chưa cấu hình* — một trạng thái thật. Chặn nó là
bắt người dùng tích bừa một ô để lưu được.

### 4.0 `POST /users` · `PATCH /users` — membership mang `roleId`, không mang tên

M2b hiện gửi `{"workspaceId": ..., "role": "editor"}` — một trong 4 mã cố định. Mã đó không còn
tồn tại. Chốt 2026-08-04: đổi thành `{"workspaceId": ..., "roleId": "r_..."}`.

**Vì sao id chứ không phải tên.** Tên vai trò đổi được — đó là cả điểm của spec này. Nếu membership
tham chiếu bằng tên thì một lần đổi tên Biên tập → Trợ lý kinh doanh biến mọi assignment đang có
thành trỏ vào hư không, hoặc tệ hơn: đổi tên rồi tạo lại một vai trò Biên tập khác sẽ khiến các
assignment cũ âm thầm trỏ sang bộ quyền mới. Id là thứ duy nhất ổn định.

FE không phải tra gì thêm: `GET /roles` đã trả `id` cùng `name`, và dropdown vốn cần cả hai —
`value` là id, nhãn là tên.

> **Ghi chú bổ sung 2026-08-07.** Câu ngay trên ĐÚNG cho việc **VẼ** dropdown, nhưng bỏ sót việc
> **CHỌN SẴN** giá trị hiện tại. Để đánh dấu vai trò user ĐANG giữ, FE cần `roleId` của membership
> đó — mà đường ĐỌC (`MembershipOut`, `MemberOut`) lúc ấy chỉ trả TÊN. Nên FE vẫn phải tra thêm:
> dò ngược TÊN → id qua chính `GET /roles`. Phép dò đó khớp SAI khi tên trùng hoặc tên vừa đổi, và
> đó là gốc của một lỗi **leo thang quyền** đo được ở frontend.
>
> Nói cách khác: neo đường GHI vào id mà để đường ĐỌC trả tên là một hợp đồng bất đối xứng, và
> khoảng chênh bị đẩy sang client tự bắc cầu bằng một phép đoán. Đã sửa bằng cách cho cả hai DTO
> đọc mang thêm `roleId` — xem [`2026-08-07-membership-roleid-duong-doc.md`](2026-08-07-membership-roleid-duong-doc.md),
> trong đó có cả lý do vì sao lần đó **không** dính ràng buộc hai deploy là một đơn vị của §8.1①.

`roleId` không thuộc tổ chức của admin ⇒ **422 `ROLE_NOT_IN_ORG`**, cùng khuôn
`WORKSPACE_NOT_IN_ORG` của M2b §4.2: composite FK cũng chặn, nhưng bằng một
`ForeignKeyViolationError` → 500. Kiểm trước biến cùng một sự thật thành một câu có tên field.

### 4.1 Mã lỗi mới — `modules/auth/loi.py`

| Mã | HTTP | Khi nào |
|---|---|---|
| `ROLE_NOT_FOUND` | 404 | không có vai trò đó **trong tổ chức của admin** — tổ chức khác cũng 404, không 403 |
| `ROLE_NAME_TAKEN` | 409 | trùng `name` trong cùng tổ chức |
| `ROLE_IN_USE` | 409 | xoá vai trò còn người dùng. `chi_tiet.userCount` |
| `UNKNOWN_ACTION` | 422 | `actions[]` chứa mã không có trong `control.actions` |

`ROLE_NOT_FOUND` cho vai trò của tổ chức khác, **không** `FORBIDDEN` — 403 xác nhận *id này tồn
tại, chỉ là không phải của bạn*, đủ để dò cấu hình quyền của mọi khách hàng. Cùng lý lẽ M2b §4.2.

### 4.2 Hai luật an toàn còn lại

1. **Xoá vai trò đang gán** → `409 ROLE_IN_USE`. FK `RESTRICT` là lưới cuối; service kiểm trước để
   ra 409 có tên field thay vì một `ForeignKeyViolationError` → 500.
2. **Tổ chức phải luôn còn ≥1 owner** → `409 SELF_LOCKOUT`. Mở rộng luật M2b §3.2, không phải luật
   mới.

Chỉ hai — nhờ §3.3. Nếu owner đi qua ma trận thì đây sẽ là năm luật, và ba trong số đó rất khó test.

---

## 5. Frontend

Chín chỗ. Theo đúng quy ước *thêm một màn = 3 việc* của `lib/nav-registry.ts`.

| # | File | Việc |
|---|---|---|
| 1 | `features/auth/nav.ts` | thêm `rolesNav` — `key:'roles'`, `path:'/roles'`, `requiredActions:[WORKSPACE_ADMIN]` |
| 2 | `lib/nav-registry.ts` | **một dòng** vào nhóm *Cấu hình*, ngay sau `usersNav` |
| 3 | `routes/_app/roles.tsx` | route mới |
| 4 | `lib/screens.ts` | một dòng |
| 5 | `features/auth/api.ts` | 6 hàm + React Query keys |
| 6 | `features/auth/components/DanhSachVaiTro.tsx` | bảng + cột đang gán cho N người + nút Xoá |
| 7 | `features/auth/components/FormVaiTro.tsx` | tên · mô tả · 13 checkbox gom theo `groupName` |
| 8 | màn `users` hiện có | dropdown vai trò: bỏ 4 hằng số, đọc `GET /roles` |
| 9 | `lib/msw/handlers.ts` | handler **có trạng thái** (M2b §5.3) |

Không ai sửa `components/shell/*`.

### 5.1 Ba quy tắc UI bắt buộc

**Dropdown vai trò có thể RỖNG.** Hôm nay nó là 4 lựa chọn cứng nên trường hợp này không tồn tại.
Sau khi đổi, một tổ chức vừa xoá hết vai trò sẽ thấy dropdown trống. Form phải hiện *Chưa có vai
trò nào — tạo vai trò trước* kèm link sang `/roles`, không phải một ô select rỗng không giải thích.

**Nút Tạo vai trò chỉ hiện khi `session.orgRole === 'owner'`.** Ẩn nút là cho đỡ rối mắt
(PQ_01 §BR-Q03), **không** phải bảo vệ — endpoint vẫn kiểm.

**Xác nhận xoá phải nói số người bị ảnh hưởng**, lấy từ `userCount` — kể cả khi nó bằng 0.

### 5.2 MSW phải có trạng thái

M2b §5.3 đã đặt luật này và nó áp ở đây mạnh hơn: tạo một vai trò ở màn `/roles` rồi sang màn
`/users` phải **thấy nó trong dropdown**. Handler trả mảng cứng sẽ làm test xanh trong khi luồng
thật hỏng.

---

## 6. Migration dữ liệu — chỗ dễ hỏng nhất

`0104` upgrade, trong một transaction:

```
1. CREATE actions, roles, role_actions
2. seed 13 hàng actions từ ACTIONS (code · group_name · label_vi · label_en · sort_order)
3. VỚI MỖI hàng organizations:
     tạo 4 roles — 'Quản trị' · 'CSKH' · 'Biên tập' · 'Người xem'
     + role_actions theo ĐÚNG ma trận PQ_01 §3.1
4. ALTER memberships ADD role_id; UPDATE map từ cột role cũ
     admin→Quản trị · care→CSKH · editor→Biên tập · viewer→Người xem
5. SET NOT NULL; ADD composite FK; DROP CHECK cũ; DROP COLUMN role
```

**Bước 3 chạy theo từng `org_id`**, không tạo một bộ dùng chung — nếu dùng chung thì §1.3 dòng thứ
ba đã bị vi phạm ngay từ migration.

**`downgrade()` phải raise, không đoán.** Khôi phục cột `role` cần map ngược tên vai trò → 4 mã cố
định. Nếu tổ chức đã đổi tên hoặc thêm vai trò thì không map được. `downgrade()` kiểm trước: có vai
trò nào ngoài 4 tên gốc, hoặc có membership trỏ tới nó ⇒ **raise với thông điệp nêu tên vai trò
vướng**. Đoán bừa (gán hết về `viewer`) là âm thầm tước quyền của cả tổ chức.

`dev_seed.py` cập nhật: sinh 4 vai trò cho `noble` và `havengroup`, gán `dang@anphuland.vn` làm
owner (không cần membership), thêm một user `member` có vai trò `Biên tập` ở `anphu` để test có
đối tượng thật.

---

## 7. Cổng test

`tests/modules/auth/test_vai_tro.py`, trừ nơi ghi khác.

| # | Cổng |
|---|---|
| 1 | `SELECT code FROM control.actions` **bằng đúng** `ALL_ACTIONS` — lệch chiều nào cũng đỏ |
| 2 | User có vai trò không tích `catalog.write` gọi `POST /du-an` → **403**, thông điệp chứa nhãn quyền và tên vai trò |
| 3 | Owner đủ 13 action ở mọi workspace của tổ chức **dù `memberships` rỗng** |
| 4 | `INSERT memberships` với `role_id` của tổ chức khác → **FK violation ở tầng Postgres** |
| 5 | `DELETE /roles/{id}` khi `userCount>0` → 409 `ROLE_IN_USE`, **không xoá hàng nào** |
| 6 | Gỡ `org_role` của owner cuối → 409 `SELF_LOCKOUT` |
| 7 | `PATCH /roles/{id}` **thay thế** tập actions, không cộng dồn |
| 8 | Bỏ tích một ô ⇒ request **kế tiếp** của người đang đăng nhập bị chặn (chứng minh không cache) |
| 9 | `POST /roles` với action lạ → 422 `UNKNOWN_ACTION`, **không để lại hàng nào** |
| 10 | Vai trò 0 quyền tạo được; user mang nó → 403 ở mọi endpoint có action, 200 ở route công khai |
| 11 | `GET /roles/{id}` của tổ chức khác → **404**, không 403 |
| 12 | `0104` upgrade → downgrade → upgrade sạch trên DB có dữ liệu 4 vai trò gốc |
| 13 | `0104` downgrade **raise** khi tổ chức có vai trò tuỳ chỉnh, thông điệp nêu tên vai trò |
| — | `control.actions`/`roles`/`role_actions` khai trong allowlist bảng `control` (`tests/integration/test_control_schema.py`) |
| — | FE: tạo vai trò → hiện trong dropdown màn users · dropdown rỗng hiện lời nhắc + link · nút Xoá hiện `userCount` · nav `roles` ẩn khi thiếu `workspace.admin` (`tests/vai-tro.test.tsx`) |
| — | `tests/nav-registry.test.ts` cập nhật thứ tự sidebar |

Cổng 5 và 9 kiểm **không để lại hàng nào** — đó là phép kiểm transaction, thứ duy nhất phân biệt
có `conn.transaction()` với trông như có.

Cổng 4 gọi SQL trực tiếp: nó kiểm một **ràng buộc CSDL**. Phép kiểm ở service cũng chặn được, nhưng
chỉ composite FK là thứ `psql` tay và mọi seed script sau không đi vòng được.

Cổng 8 là cổng khó viết nhất và quan trọng nhất — nó là thứ duy nhất chứng minh §3.5.

---

## 8. Định nghĩa "xong"

- [ ] `require()` tra ma trận; `tests/api/test_moi_route_khai_action.py` vẫn xanh
- [ ] 13 cổng §7 xanh; toàn bộ `tests/modules/auth/` hiện có vẫn xanh
- [ ] `0104` upgrade/downgrade/upgrade sạch trên bản sao DB dev
- [ ] Owner tạo được vai trò mới, gán cho user, user đó bị chặn đúng ở endpoint không được tích
- [ ] Màn `/roles` và dropdown màn `/users` chạy trên MSW **và** trên backend thật
- [ ] `make contracts` chạy, `contracts/actions.json` không đổi (13 action giữ nguyên)

### 8.1 Hai việc review cuối chốt là "theo dõi, không sửa bằng code"

**① `role` → `roleId` không có cửa sổ tương thích.** `POST/PATCH /users` nay **bắt buộc** `roleId` và
từ chối `role`. Backend và frontend không deploy cùng lúc, nên bên nào lên trước thì màn quản trị
người dùng trả 422 cho tới khi bên kia theo. Phạm vi nhỏ — màn chỉ owner vào, không hỏng dữ liệu,
không ảnh hưởng an ninh — nhưng **hai deploy này là một đơn vị, phải ghi vào runbook**. Cách khác nếu
muốn nới: nhận `role` làm alias phế bỏ trong một release.

**② Bản sao `contracts/actions.json` giữa hai repo là mắt duy nhất không có cổng canh.**
`test_contracts.py` chứng minh artefact = nguồn Python; `actions-parity.test.ts` chứng minh
`actions.ts` = artefact **của repo frontend**. Không gì chứng minh artefact hai repo là cùng một file.
Hôm nay chúng giống nhau từng byte và bước copy đã ghi trong `contracts/README.md` — nhưng đó là một
bước tay, và là bản sao duy nhất có thể mục trong im lặng. Đóng lại bằng một job CI `diff` hai file,
hoặc vendor artefact theo checksum. **Đây là khoảng hở của thiết kế, không phải của thi công:** spec
đặt `contracts/actions.json` làm artefact biên mà không nói ai kiểm việc băng qua biên.

### 8.2 Ghi để không ai tưởng đã có

- **Quyền hỗ trợ có hạn** (PQ_01 §II.2.5 — membership tạm cho nhân sự NobleX) **không** thuộc spec
  này. Cột `memberships.expires_at` đã tồn tại và `doc_membership` đã lọc theo nó (BR-Q08); cái
  còn thiếu là luồng cấp/thu hồi vé. Truy vấn mới ở §3.2 **phải giữ nguyên vị từ
  `expires_at IS NULL OR expires_at > now()`** — bỏ nó là làm sống lại mọi vé đã hết hạn.
- **Nhật ký đọc bản ghi thoại** (PQ_01 §II.2.4, BR-Q07) vẫn treo. Spec này cấp `convos.transcript.read`
  đúng cách nhưng không ghi vết mỗi lần đọc.
- **Sao chép vai trò** (tạo từ bản sao của Biên tập) không có trong MVP. Người dùng tích lại 13 ô.
- **Nhật ký thay đổi vai trò** — `POST/PATCH/DELETE /roles` ghi `audit_log` với `org_id`,
  `tenant_id` NULL. Có trong spec này; màn xem nó là của M8.
