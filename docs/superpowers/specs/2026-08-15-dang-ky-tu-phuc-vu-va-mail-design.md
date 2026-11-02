# Đăng ký tự phục vụ + gửi mail — Design

Phạm vi: `odyssey-portal-backend` (chính), `odyssey-portal-frontend`.

**Tài liệu này là DELTA của [`2026-08-15-bo-organization-design.md`](2026-08-15-bo-organization-design.md).**
Mọi mục không được nhắc ở đây thì giữ nguyên như spec đó đã chốt.

> **Sửa đổi 2026-08-17.** Bản đầu (2026-08-15) viết khi đợt bỏ organization **chưa
> thi công** và đặt điều kiện "chờ đợt đó xong". Đợt đó **đã xong và đã merge**
> (`0105_roles_thoat_org` + `0106_bo_organizations`). Bản này rà lại toàn bộ theo
> code thật và đổi bốn thứ: §0 (mới — trạng thái code), §1, §4.1 (nay là **viết
> lại** một endpoint đã ship, không phải thêm mới), §6.1 (nhượng bộ một quyết định
> đã chốt), §10 (không còn chờ ai).

---

## 0. Trạng thái code tại 2026-08-17 — đọc trước mọi mục khác

Rà bằng đọc file, không suy từ Change Log.

### 0.1 Nền tảng spec này cần: ĐÃ CÓ, khớp hoàn toàn

| Thứ | Nơi | Trạng thái |
|---|---|---|
| `BanGhiPhien.tenant_id: str \| None` | `core/auth/session.py:36` | ✅ |
| `ss.tao(..., tenant_id: str \| None)` | `core/auth/session.py:54` | ✅ |
| `ss.doc` dung thứ phiên cũ (`d.get("tenant_id")`) | `core/auth/session.py:83` | ✅ |
| `SessionOut.currentWorkspaceId: str \| None` | `modules/auth/contracts.py:100` | ✅ |
| `require()` xử lý `tenant_id is None`, **vẫn kiểm `lifecycle` riêng** | `core/auth/require.py:104-116` | ✅ |
| `invites` đã sạch `org_id`, FK đơn `user_id → users(id)` | `0105:117-121` | ✅ |
| `ghi_loi_moi` UPSERT theo `user_id`, `used_at = NULL` tường minh | `modules/auth/repo.py` | ✅ |
| Head alembic | `0106_bo_organizations` | migration của spec này nối sau |

Nói cách khác: **§5.0 của spec kia đã ship đúng như cần**. Toàn bộ lý lẽ "phiên
không workspace là trạng thái hợp lệ" không phải làm lại.

### 0.2 Năm xung đột với bản spec đầu

| # | Xung đột | Mức |
|---|---|---|
| **1** | `POST /auth/register` **đã ship với hình dạng cũ** — `{email,name,password}` → `active` ngay + **tự phát phiên** (201 `SessionOut`), 409 khi trùng email. FE đã có `routes/dang-ky.tsx` + `api.dangKy()` | Viết lại BE + FE |
| **2** | **Luồng MỜI hiện không có đường nào chạy** — xem §0.3 | ⛔ Chặn §4.4 |
| **3** | `LoiMoiOut` docstring mới **chốt tường minh KHÔNG hiện tên workspace** | Nhượng bộ — §6.1 |
| **4** | `ghi_loi_moi()` đã bỏ `org_id`; migration của spec này thêm `tenant_id` ⇒ chữ ký đổi lần thứ hai | Nhỏ |
| **5** | `VaoDangKy.password` sàn **8**, `NhanLoiMoiIn.password` sàn **10** | Tự tan — §4.5 |

### 0.3 ⛔ Phát hiện ngoài phạm vi spec đầu: chức năng MỜI đang chết

`ghi_loi_moi()` — hàm duy nhất phát lời mời — chỉ có **ba** người gọi:

| Người gọi | Cổng | Trạng thái mặc định |
|---|---|---|
| `quan_tri_user.tao` (`POST /users`) | `_cong_users_admin()` | **403 `FEATURE_DISABLED`** (`users_admin_enabled = False`) |
| `quan_tri_user.moi_lai` (`POST /users/{id}/invite`) | `_cong_users_admin()` | **403 `FEATURE_DISABLED`** |
| `cli/seed_owner.py` | vòng chặn "có user `active` ⇒ từ chối" | **chết ngay sau người đầu tiên** |

Và đường thay thế mà docstring `quan_tri_user.py:23` hứa — *"quản lý người trong
MỘT workspace → `/members`, gate `WORKSPACE_ADMIN`"* — **chưa tồn tại**: backend
chỉ có `GET /members` (`router.py:208`). Frontend thì đã gọi đủ bốn đường ghi
(`thanhVien.ts:101,116,130,136`).

⇒ Trên một hệ vừa deploy, sau khi người đầu tiên tự đăng ký: **không đường nào
phát được lời mời nữa.** `GET /invites/{token}` và `POST /invites/accept` vẫn sống
nhưng không còn ai sinh ra token cho chúng. Nút "Mời" trên `/users` ăn 405.

Đây **không phải lỗi của spec bỏ organization** — spec đó §5.3 ghi "mời người vào
workspace: không đổi", đúng ở thời điểm viết, vì lúc đó `/users*` chưa bị cờ đóng
và `/members` ghi chưa được hứa hẹn. Khoảng hở sinh ra ở chỗ nối giữa hai quyết
định. Nhưng nó là **tiền đề bắt buộc** của §4.4 spec này, nên phải xử lý ở đây.

## 1. Vấn đề

Hình dạng đăng ký đã ship (§0.2 #1) khác với hình dạng người yêu cầu muốn:

> Người đăng ký nhập email, hệ thống **gửi một link qua email**, họ bấm link để tự
> đặt mật khẩu.

Ba hệ quả:

1. `password` rời khỏi thân `POST /auth/register`. Tài khoản ra đời `pending`,
   không `active`, và **không** tự phát phiên.
2. Hệ thống cần bộ gửi mail. Hôm nay **không có**: `grep -rEil
   'smtp|sendgrid|mailgun|send_email' src` trả rỗng (đo 2026-08-17), và
   `core/config.py` không có trường SMTP nào.
3. "Trùng email trả 409" trở thành lỗ dò email — §4.2.

Điều may mắn không đổi: **đăng ký tự phục vụ chính là "tự mời chính mình"**. Luồng
mời đã có sẵn phát token 256 bit, lưu `sha256`, và một màn công khai đặt mật khẩu
lần đầu. Không cần luồng thứ hai — cần **sửa đường vào** cho khớp.

## 2. Quyết định thiết kế

**Đăng ký dùng lại nguyên luồng lời mời. Không có luồng thứ hai.**

Một bảng token (`control.invites`), một màn đặt mật khẩu
(`routes/invite.$token.tsx`), một endpoint nhận mật khẩu (`POST /invites/accept`)
— phục vụ **cả hai** đường vào. Khác biệt duy nhất là **ai phát token** và **token
có gắn workspace hay không**:

| | Ai phát | `invites.tenant_id` | Sau khi đặt mật khẩu |
|---|---|---|---|
| Tự đăng ký | chính người đó, qua `POST /auth/register` | `NULL` | 0 workspace ⇒ màn "Tạo workspace đầu tiên" |
| Được mời | một `WORKSPACE_ADMIN`, qua `POST /members` | id workspace đó | thấy đúng workspace đó |

Hệ quả trực tiếp: **xác thực email trở thành miễn phí.** Ai đặt được mật khẩu là
người mở được hộp thư đó. Spec kia §12 xếp "xác thực email" ngoài phạm vi vì tốn
công; ở hình dạng này nó không tốn gì, và mục đó của §12 được gỡ.

### 2.1 Vì sao KHÔNG tự phát phiên sau khi đặt mật khẩu

`POST /invites/accept` giữ nguyên: **204, không tạo phiên**, FE đẩy về `/login`.
Docstring `quan_tri_user.nhan_loi_moi` đã ghi lý do và nó vẫn đúng — đường này
công khai, tự phát phiên nghĩa là ai mở được link thì có phiên.

⚠ Đây là chỗ hành vi **đi lùi** so với cái đang chạy: `POST /auth/register` hôm nay
trả `SessionOut` + đặt cookie, đăng ký xong là vào thẳng. Sau đợt này người dùng
phải qua hộp thư rồi đăng nhập. Đó là cái giá của xác thực email, **có chủ ý**, và
phải nói rõ ở màn FE chứ không để người dùng tự phát hiện.

## 3. Delta so với spec bỏ organization

| § spec kia | Đang ghi / đã ship | Đổi thành | Xem |
|---|---|---|---|
| **5.1** | `{email,name,password}` → `active` + phiên, 201 | `{email, name}` **không password** → `pending` → phát token → gửi mail → **201 mới / 200 `daGuiLai` / 409 `EMAIL_TAKEN`** theo ba nhánh, không phiên | §4.1 |
| **5.1** | "Trùng email trả **409**" | **GIỮ NGUYÊN 409** — quyết định người yêu cầu 2026-08-17 | §4.2 |
| **5.3** | "Mời vào workspace: **không đổi**" | Phải **dựng 4 endpoint `/members` ghi** trước (§0.3), rồi ba nhánh theo trạng thái email | §4.4 |
| **6.1** | `LoiMoiOut` bỏ `organizationName`, không hiện tên workspace | Thêm **`kind`** (giữ nguyên quyết định không hiện tên workspace) | §6.1 |
| **2.1** | "Không rào chống lạm dụng" | **Giữ nguyên** — quyết định người yêu cầu 2026-08-15 | §7 |
| **12** | "Xác thực email" — ngoài phạm vi | **Bỏ khỏi §12** — đã có, miễn phí | §2 |

Thêm mới: **§5 bộ gửi mail**, **§8 migration `invites.tenant_id`**, và **§4.4a
dựng `/members`**.

## 4. Luồng

### 4.1 `POST /api/v1/auth/register` — VIẾT LẠI

**Gỡ khỏi code hiện tại:**

| Gỡ | Nơi |
|---|---|
| `VaoDangKy.password` | `contracts.py:345` |
| `service.dang_ky` trả `(session_id, SessionOut)` và gọi `ss.tao` | `service.py:139` |
| `pw.bam(mat_khau)` lúc đăng ký | `service.py` |
| `raise loi_auth.email_da_ton_tai()` | `service.py` |
| `response_model=SessionOut, status_code=201` + `_dat_cookie` | `router.py:116` |
| FE `dangKy(email, name, matKhau)` trả `Session` | `features/auth/api.ts:55` |

**Thân mới:** `{email: str, name: str}`. Không `password`, không `workspaceId`.

**Cổng:** `require(None, ly_do="đường tạo tài khoản đầu tiên — đòi phiên là vòng tròn")`.
Luật 4 buộc mọi route khai action; `tests/unit/test_moi_route_khai_action.py` canh.

**Các bước, một giao dịch** (router mở, theo khuôn repo):

1. `service.chuan_hoa_email` — cùng hàm `TaoUserIn` đang dùng.
2. Tra `users` theo email. Ba nhánh:

| Trạng thái email | Việc làm | Trả |
|---|---|---|
| chưa tồn tại | tạo `users` (`pending`, `password_hash=NULL`) → `ghi_loi_moi(tenant_id=NULL)` → gửi thư | **201** |
| tồn tại, `pending` | **phát token mới** + gửi lại thư (`ON CONFLICT (user_id) DO UPDATE` ⇒ token cũ chết) | **200** `{"daGuiLai": true}` |
| tồn tại, `active` / `suspended` | **không làm gì**, không gửi thư | **409 `EMAIL_TAKEN`** |

Nhánh giữa là đường "gửi lại link" mà không cần endpoint thứ hai, và là lối thoát
khi SMTP hỏng giữa chừng (§5.4). **Nó phải KHÁC nhánh ba** — gộp cả hai vào 409 là
nhốt người mất thư trong một ngõ cụt: họ có tài khoản `pending`, không có mật khẩu
để đăng nhập, và đăng ký lại thì bị từ chối.

3. Ghi nhật ký `user.dang_ky`. **Không** ghi token vào `chi_tiet` — nhật ký là bảng
   chỉ-ghi-thêm mà nhiều người đọc được.
4. **Sau khi commit**, gửi mail (§5.3).

Ba mã khác nhau cho ba nhánh là **có chủ ý** (§4.2): FE cần phân biệt để nói đúng
việc người dùng phải làm tiếp — đăng nhập, hay mở hộp thư.

`repo.tao_user_tu_dang_ky` đổi: bỏ tham số `password_hash`, ghi
`lifecycle='pending'`. CHECK `users_password_theo_lifecycle_check` (0103) buộc
`pending` ⇔ `password_hash IS NULL`, nên không có cách nào tạo sai trạng thái.

### 4.2 Nói thẳng khi trùng email — quyết định người yêu cầu, 2026-08-17

Bản spec trước chọn "luôn 202, không bao giờ tiết lộ" để bịt kênh dò email. Người
yêu cầu chốt ngược lại: **trùng email thì báo thẳng là trùng, làm như các app
thông thường.** Rủi ro đã được nêu (§7.6) và quyết định được giữ.

Đây cũng là lối phổ biến nhất trong thực tế, và nó **mua lại** thứ đáng giá: người
dùng gõ nhầm email của người khác biết ngay, thay vì ngồi chờ một lá thư không bao
giờ tới. Nó cũng giữ nguyên tiện ích mà code hiện tại đang có — FE gợi ý "đăng nhập
thay vì đăng ký", đúng lợi ích docstring `service.dang_ky` đã nêu.

Câu chữ FE theo ba mã của §4.1:

| Mã | Câu | Hành động gợi ý |
|---|---|---|
| 201 | "Đã gửi liên kết đặt mật khẩu tới **{email}**. Kiểm tra hộp thư (kể cả mục spam)." | — |
| 200 | "Tài khoản này chưa hoàn tất đăng ký. Chúng tôi vừa **gửi lại** liên kết tới **{email}**." | — |
| 409 | "Email này đã có tài khoản." | nút **Đăng nhập** |

Ở 201 và 200 nay được phép nói **"Đã gửi tới {email}"** — một khẳng định đúng, vì
nhánh im lặng không còn tồn tại.

### 4.2b Đăng nhập giữ nguyên thông báo chung — KHÔNG sửa

`service.dang_nhap` gộp ba tình huống (sai mật khẩu · tài khoản `pending` · bị đình
chỉ) vào cùng một `sai_dang_nhap()` — *"Tài khoản hoặc mật khẩu chưa chính xác"* —
và nhánh `pending` gọi `pw.kiem_gia()` để không nhanh hơn nhánh băm thật.

**Không đụng vào đoạn này.** Nó đã đúng đúng thứ người yêu cầu muốn, và nó vẫn còn
giá trị **sau khi** §4.2 mở kênh dò ở đường đăng ký:

- `/auth/register` chỉ tiết lộ **một** bit: email này có tài khoản hay không.
- `dang_nhap` gộp mã + `kiem_gia()` giấu **trạng thái** tài khoản — chưa đặt mật
  khẩu? bị đình chỉ? — và giấu cả kênh thời gian.

Hai thứ khác nhau. Đừng ai đọc §4.2 rồi kết luận "đằng nào cũng lộ" và đi gỡ
`kiem_gia()` hay tách mã lỗi ở `dang_nhap`.

### 4.3 Đặt mật khẩu — không đổi một dòng

`GET /invites/{token}` + `POST /invites/accept` giữ nguyên: hạn 7 ngày, dùng một
lần, `pw.bam` (Argon2), `lifecycle → active`, 204.

Sau đó: `/login` → `dang_nhap` thấy 0 workspace → phiên `tenant_id=None` (**đã
ship**, §0.1) → FE `workspaces: []` → màn "Tạo workspace đầu tiên" → `POST /workspaces`
ghi membership "Quản trị" cho chính họ.

### 4.4a ⛔ Tiền đề: dựng bốn endpoint `/members` ghi

Không có mục này thì §4.4 không có chỗ bám và chức năng mời vẫn chết (§0.3).

| Endpoint | Việc | Cổng |
|---|---|---|
| `POST /members` | mời nhiều email vào **workspace đang mở**, một `roleId` | `require(ACTIONS.WORKSPACE_ADMIN)` |
| `PATCH /members/{user_id}` | đổi vai trò **tại workspace đang mở** | `require(ACTIONS.WORKSPACE_ADMIN)` |
| `DELETE /members/{user_id}` | gỡ khỏi workspace (**không** xoá tài khoản) | `require(ACTIONS.WORKSPACE_ADMIN)` |
| `POST /members/{user_id}/invite` | phát lại lời mời | `require(ACTIONS.WORKSPACE_ADMIN)` |

Hình dạng thân/response **đã được frontend chốt sẵn** ở
`odyssey-portal-frontend/src/features/auth/thanhVien.ts` — BE khớp theo, không tự
nghĩ lại: `POST` nhận `{emails: string[], roleId: string}` trả `{invites: KetQuaMoi[]}`;
`PATCH` nhận `{roleId}` trả `MemberOut`; `DELETE` trả 204; `POST .../invite` trả
`{invitePath: string | null}`.

Ba điểm phải giữ đúng:

- **`tenant_id` lấy từ `Principal`, không từ body.** Luật cách ly, không thương lượng.
- **Chỉ chạm ĐÚNG một hàng `memberships`.** Không tái dùng `repo.dat_lai_membership`
  (thay thế toàn bộ) — chính nó gây bug mất dữ liệu 2026-08-06, và docstring
  `thanhVien.ts:116` đã ghi lại nguyên nhân. `PATCH /members/{id}` là một `UPDATE`
  một dòng.
- **`DELETE` gỡ membership, không xoá `users`.** Xoá tài khoản là việc khác và
  hiện không có chủ (khối `/users*` đang tắt).

`_kiem_role_thuoc_to_chuc` **không còn** (vai trò đã toàn cục). Phép kiểm còn lại
là "`roleId` có tồn tại không" → 422 `ROLE_NOT_FOUND`, đúng như spec kia §5.3 chốt.

### 4.4 Ba nhánh của đường mời

`POST /members`, với mỗi email trong lô:

| Email được mời | Việc làm | `invitePath` |
|---|---|---|
| chưa có tài khoản | tạo `users` `pending` + `memberships` + token (`tenant_id` = workspace này) + gửi mail | `null` nếu mail đi được, ngược lại đường dẫn để copy tay |
| đã có, `active` | **không phát token** — chỉ `INSERT memberships` + gửi mail "bạn vừa được thêm vào workspace X" | **luôn `null`**: không có token nào tồn tại để copy, kể cả khi mailer tắt |
| đã có, `pending` | **bỏ qua, báo lỗi cho riêng email đó** — `USER_PENDING_SIGNUP` | — |

Nhánh hai đóng một lỗ đang có: hôm nay không có cách nào thêm người **đã có tài
khoản** vào workspace thứ hai qua luồng mời, và phát token cho người đã `active`
là tạo một đường đặt lại mật khẩu không ai yêu cầu (docstring `moi_lai` nói đúng
điều này).

Nhánh ba là quyết định có chủ ý: `invites.user_id` UNIQUE + `DO UPDATE` ⇒ phát
token mời cho người đang chờ hoàn tất đăng ký sẽ **giết token đăng ký của họ**;
họ bấm link trong hộp thư và nhận `INVITE_INVALID` mà không hiểu vì sao. Rẻ hơn
nhiều so với gỡ ràng buộc UNIQUE để hai token cùng sống.

⚠ Vì `POST /members` nhận **một lô** email, lỗi phải **theo từng dòng**, không phải
409 cho cả lô: mời 40 người mà một người đang `pending` thì 39 người kia phải vào
được. `KetQuaMoi` mọc thêm một trường trạng thái cho mỗi email.

**Hệ quả mất membership — quyết định GIỮ NGUYÊN, ghi lại chứ không đổi code**
(review cuối trước merge). Nhánh ba KHÔNG ghi bất kỳ `membership` nào cho email
đang `pending`, bất kể người đó đang dở đăng ký vì tự đăng ký hay vì một admin
KHÁC đã mời trước. Người mời (admin gọi `POST /members` lần này) phải **tự nhớ
quay lại mời lại SAU KHI** người kia đặt xong mật khẩu (`lifecycle` chuyển
`active`) — không có hàng chờ nào ghi nhớ ý định "B muốn mời", và lượt gọi hiện
tại không tạo ra gì ngoài một dòng lỗi cho email đó. Lý do giữ nguyên: cấp quyền
workspace cho một tài khoản chưa có mật khẩu có mùi riêng (token đăng ký bị lộ
là lộ luôn quyền vào workspace vừa gán), và lỗi hiện tại đã nói rõ ràng ("đang
chờ hoàn tất đăng ký... hãy thêm lại") chứ không im lặng nuốt lời mời.

### 4.5 Sàn mật khẩu: 8 → 10, tự tan

`VaoDangKy.password` (sàn **8**) biến mất cùng §4.1. Mọi mật khẩu đầu tiên nay đi
qua `NhanLoiMoiIn.password` (sàn **10**). Đây là **siết**, không phải nới — và lý
lẽ "sàn 8 vì đăng ký mở cho cả internet" trong docstring `VaoDangKy` hết hiệu lực
cùng lúc, vì mật khẩu không còn đặt ở đường công khai không token nữa. Xoá cả
docstring đó, đừng để lại một lý lẽ mồ côi.

## 5. Bộ gửi mail

### 5.1 `src/portal/core/mailer.py`

Module mới trong `core/` — luật 3 (module chỉ import `portal.core.*`) buộc nó phải
ở đây để `modules/auth` gọi được.

Bề mặt tối thiểu, đúng một hàm:

```python
async def gui(*, den: str, tieu_de: str, than_text: str, than_html: str) -> None
```

Không hàng đợi, không retry, không template engine. **Ba** loại thư dựng bằng
f-string trong `modules/auth`, không trong `core/mailer.py` — core không biết
nghiệp vụ:

| Thư | Sinh ở | Có link token |
|---|---|---|
| Hoàn tất đăng ký | §4.1 nhánh 1, 2 | ✅ |
| Được mời vào workspace | §4.4 nhánh "chưa có tài khoản" | ✅ |
| Đã được thêm vào workspace | §4.4 nhánh "`active`" | ❌ — chỉ link tới `/login` |

Gửi `multipart/alternative` (cả `text` lẫn `html`): thư chỉ có HTML bị nhiều bộ lọc
chấm điểm spam cao hơn, và đây là thư **phải** tới hộp thư chính.

### 5.2 Cấu hình

Thêm vào `core/config.py` `Settings`:

| Biến env | Mặc định | Ghi chú |
|---|---|---|
| `SMTP_HOST` | `""` | **Rỗng ⇒ mailer in thư ra stdout thay vì gửi.** Cùng lối `public_base_url` ("RỖNG = không sinh link (an toàn)") — `make up` chạy được không cần credential SES |
| `SMTP_PORT` | `587` | |
| `SMTP_USER` | `""` | |
| `SMTP_PASS` | `""` | |
| `SMTP_FROM` | `""` | `no-reply@noblex.vn` |
| `SMTP_FROM_NAME` | `"NobleX"` | |
| `SMTP_STARTTLS` | `True` | |
| `PUBLIC_BASE_URL` | `""` | Gốc URL của **FE**, để ghép link tuyệt đối |

⚠ **`SMTP_SECURE=false` trong cấu hình đang có KHÔNG có nghĩa "không mã hoá".**
Cổng 587 + `secure=false` là quy ước Nodemailer cho **STARTTLS**: mở kết nối
plaintext rồi nâng cấp TLS bằng lệnh `STARTTLS` **trước khi** gửi credential.
`secure=true` mới là TLS ngầm (cổng 465). Dịch nhầm thành `use_tls=False` là gửi
`AKIA…`/`BMFx…` qua Internet dưới dạng chữ thường. Đó là lý do trường ở đây tên
`smtp_starttls`, **không** copy tên `smtp_secure`.

⚠ `PUBLIC_BASE_URL` rỗng ⇒ không ghép nổi link tuyệt đối từ `invitePath` tương đối
⇒ mailer log cảnh báo và cư xử như "mailer tắt". Giữ `invitePath` **tương đối** ở
API là đúng và không đổi (docstring `TaoUserRaOut.invitePath`); chỗ ghép origin nay
có hai người: FE dùng `location.origin`, mailer dùng `PUBLIC_BASE_URL`.

### 5.3 Gửi NGOÀI giao dịch, sau khi commit

Gọi SMTP bên trong `conn.transaction()` sai theo hai hướng:

- Giao dịch giữ kết nối Postgres suốt thời gian bắt tay TLS + gửi. SMTP chậm ⇒ giao
  dịch dài ⇒ pool cạn.
- **Mail không rollback được.** Giao dịch hỏng sau khi thư đã đi = một người cầm
  link đặt mật khẩu cho tài khoản không tồn tại.

Thứ tự cứng: mở giao dịch → ghi `users` + `invites` + nhật ký → **commit** → gửi
thư. Token thô giữ trong biến Python qua ranh giới đó, không đọc lại từ DB (DB chỉ
có `sha256`).

### 5.4 Lỗi gửi mail không được làm hỏng request

SMTP chết ⇒ `gui()` log lỗi và **nuốt exception**. Request vẫn trả đúng mã của
nhánh đó (**201** mới / **200** `{"daGuiLai": true}` gửi lại) — lỗi gửi thư không
đổi mã HTTP, chỉ là thư không tới hộp thư (xem §5.3, giao dịch đã commit trước đó).

Tới thời điểm đó giao dịch **đã commit** — user và token đã tồn tại. Ném lỗi ra
ngoài cho người dùng một 500 trong khi tài khoản của họ đã được tạo, và lần thử
lại đi vào nhánh "`pending` ⇒ phát token mới" chứ không phải nhánh tạo mới. Nói
cách khác: 500 ở đây **mô tả sai trạng thái hệ thống**.

Đường phục hồi: đăng ký lại cùng email (§4.1 nhánh giữa), hoặc "Mời lại" từ UI.

### 5.5 Phụ thuộc mới

`aiosmtplib` vào `[project].dependencies` — luật repo: gói `src/portal` import
thẳng phải khai ở đó, cổng `tests/unit/test_khai_bao_phu_thuoc.py`.

Đã loại: `smtplib` + `anyio.to_thread.run_sync` — tránh một phụ thuộc, đổi lấy một
thread pool cho việc thuần I/O mạng trong ứng dụng async.

## 6. Bề mặt API và FE

### 6.1 `LoiMoiOut` — thêm `kind`, KHÔNG thêm tên workspace

Bản spec đầu đề xuất thêm cả `kind` lẫn `workspaceName`. Docstring `LoiMoiOut`
(`contracts.py:313-316`) đã chốt ngược lại điều thứ hai:

> `organizationName` ĐÃ BỎ 2026-08-15 cùng tầng tổ chức. KHÔNG thay bằng tên
> workspace: lời mời được mở TRƯỚC khi có phiên, người nhận chưa có ngữ cảnh
> workspace nào, và một cái tên lạ trên màn đặt mật khẩu là thêm câu hỏi chứ không
> thêm sự yên tâm.

**Nhượng bộ: bỏ `workspaceName`.** Lý lẽ đó đúng và không bị yêu cầu mới làm sai.

**Giữ `kind`**, vì nó giải một vấn đề khác hẳn: từ đợt này có **hai loại token trên
cùng một màn**, và một người tự đăng ký đọc "Bạn được mời tham gia" là câu sai sự
thật — không phải thiếu ngữ cảnh, mà là **sai**.

```
LoiMoiOut:
  email: str
  name: str
  kind: Literal['signup', 'invite']   # suy từ invites.tenant_id IS NULL
```

| `kind` | Tiêu đề màn | Nút |
|---|---|---|
| `signup` | "Hoàn tất đăng ký" | "Đặt mật khẩu" |
| `invite` | "Bạn được mời tham gia" | "Đặt mật khẩu và tham gia" |

`kind` là một enum hai giá trị, **không** rò thông tin nào về workspace — nó chỉ
nói người giữ link đang ở luồng nào, mà chính họ đã biết.

### 6.2 Endpoint và FE

| Mới / đổi | Nơi |
|---|---|
| `POST /auth/register` — **viết lại** (§4.1) | `modules/auth/router.py:116`, `service.py:139`, `contracts.py:331` |
| 4 endpoint `/members` ghi — **mới** (§4.4a) | `modules/auth/router.py` |
| `LoiMoiOut` + `kind` | `modules/auth/contracts.py:306` |
| `KetQuaMoi` + trạng thái từng email | `modules/auth/contracts.py` |
| `invitePath` trả `null` khi đã gửi mail | `TaoUserRaOut`, `MoiLaiRaOut`, `KetQuaMoi` |
| `dangKy(email, name)` — bỏ `matKhau`, trả `void` | `src/features/auth/api.ts:55` |
| `routes/dang-ky.tsx` — bỏ ô mật khẩu, ba màn kết quả theo 201/200/409 (§4.2) | `src/routes/dang-ky.tsx` |
| `NhanLoiMoi` đọc `kind` | `src/features/auth/components/NhanLoiMoi.tsx` |

`routes/dang-ky.tsx` **đã tồn tại và đã nằm ngoài `_app`** — không phải tạo route
mới, chỉ sửa nội dung. Sau submit nó **không** điều hướng vào app nữa (không còn
phiên); nó hiện màn "kiểm tra hộp thư" với câu chữ §4.2.

MSW handlers (`src/lib/msw/handlers.ts`) cập nhật `POST /api/v1/auth/register`
(**201** mới / **200** `{"daGuiLai": true}` / **409 `EMAIL_TAKEN`**, theo ba nhánh
§4.1 — không phải 202/thân rỗng), thêm bốn đường `/members`, mở rộng
`GET /invites/:token` với `kind`.

## 7. Đánh đổi đã chấp nhận tường minh

### 7.1 Không rào chống lạm dụng — QUYẾT ĐỊNH NGƯỜI YÊU CẦU, 2026-08-15

Giữ nguyên quyết định của spec kia §2.1, sau khi rủi ro đã được nêu và người yêu
cầu xác nhận: hệ thống dùng nội bộ, ưu tiên đơn giản trước, tầng chống thiệt hại
thiết lập sau nếu cần.

Ghi lại **không phải để phản đối** mà để người sau biết rủi ro đã được cân nhắc
chứ không bị bỏ sót, và biết chính xác phải mở lại cái gì nếu portal ra Internet.

Rủi ro đổi bản chất khi thêm email, so với lúc §2.1 được viết:

1. **Không đảo ngược được.** Trước: lạm dụng = thêm hàng `users`, dọn bằng `DELETE`.
   Sau: mỗi lượt gọi làm hệ thống **gửi thư ra Internet tới địa chỉ do người gọi
   chọn**. Thư đã gửi không thu về.
2. **Thiệt hại rơi vào tài sản dùng chung.** SES tính reputation theo bounce +
   complaint rate của cả identity `noblex.vn`. Đủ bounce ⇒ AWS review ⇒ sending
   pause ⇒ **mất luôn** thư mời và mọi thư hệ thống khác.
3. **Hệ thống thành công cụ gửi thư tới người thứ ba.** Nhập email người bất kỳ ⇒
   họ nhận thư từ `noblex.vn` dù chưa từng tương tác.

Thứ tự rẻ-trước nếu cần bật rào về sau: công tắc `SIGNUP_ENABLED` (§7.2, đã có) →
theo email (1 thư/60s, 3/24h) → theo IP (10/giờ) → trần toàn cục thư/giờ. Redis đã
có sẵn và repo đã có tiền lệ `_cho_qua_nhip` ở `modules/enrollment`.

### 7.2 `SIGNUP_ENABLED` — công tắc, không phải rào

Cờ boolean trong `Settings`, **mặc định `True`** (đăng ký công khai mở, đúng §7.1).
`False` ⇒ `POST /auth/register` trả 403 `FEATURE_DISABLED` — dùng lại
`loi.tinh_nang_dang_tat()` đã có, cùng khuôn hai cờ `ROLES_CRUD_ENABLED` /
`USERS_ADMIN_ENABLED`.

Nó **không** là tầng an toàn — nó là khả năng **tắt đăng ký không cần deploy** khi
có sự cố. Ba dòng; không có nó thì cách duy nhất dừng một đợt lạm dụng đang diễn ra
là sửa code và ship.

### 7.3 SES sandbox — ràng buộc vận hành

Tài khoản SES mặc định ở **sandbox**: chỉ gửi tới địa chỉ/domain đã verify, trần
200 thư/ngày, 1 thư/giây. Trong sandbox, **đăng ký công khai không hoạt động cho
người lạ** — SES từ chối, người đăng ký không bao giờ nhận link.

Phải xin **production access** trước khi mở `/dang-ky` cho người ngoài. Việc trên
AWS console, không phải việc repo, nhưng là điều kiện cần để tính năng chạy thật.

### 7.4 Không có "quên mật khẩu" ở đợt này

Mất mật khẩu vẫn phải can thiệp thủ công. Đăng ký lại cùng email **không** giải
quyết: nhánh ba §4.1 im lặng bỏ qua tài khoản `active`.

Có mailer rồi thì "quên mật khẩu" gần như miễn phí (cùng cơ chế token), nhưng là
một luồng riêng với phép kiểm riêng. Xem §11.

### 7.5 `cli/seed_owner.py` trở thành gần như thừa

Vòng chặn của nó ("có user `active` ⇒ từ chối") nghĩa là nó chỉ chạy trên môi
trường chưa ai vào được — mà `/auth/register` công khai đã giải đúng bài toán đó.

**Giữ lại**, không xoá: nó là đường duy nhất tạo người đầu tiên khi
`SIGNUP_ENABLED=false` (§7.2), tức đúng cấu hình của một bản self-host đóng. Không
sửa gì ở đợt này ngoài việc nó phải truyền `tenant_id` cho `ghi_loi_moi` (§8).

### 7.6 `/auth/register` tiết lộ email đã tồn tại — QUYẾT ĐỊNH NGƯỜI YÊU CẦU, 2026-08-17

`POST /auth/register` trả **409 `EMAIL_TAKEN`** cho email đã có tài khoản (§4.2),
thay vì im lặng trả 202 như bản spec đầu đề xuất.

> **Ghi chú 2026-08-17 (thi công).** Mã THẬT trong code là `EMAIL_TAKEN`, không
> phải `EMAIL_EXISTS` như bản spec/plan gốc viết ở đây. `loi.email_da_ton_tai()`
> đã tồn tại từ trước với mã `EMAIL_TAKEN` và dùng chung cho cả `/users`; đổi tên
> mã cho khớp tài liệu là đổi một hợp đồng HTTP đang chạy để đổi lấy lợi ích bằng
> không, nên implementer giữ mã thật và spec được sửa lại theo code, không ngược
> lại. Xem CLAUDE.md Change Log 2026-08-17.

Rủi ro, ghi lại để người sau không tưởng là sơ suất: đường này **công khai và không
có rate limit** (§7.1), nên nó là một máy dò email — gọi hàng loạt là biết địa chỉ
nào có tài khoản trong hệ thống. Với một portal nội bộ thì tập email vốn đã đoán
được (`ten@noblex.vn`), nên bit thông tin đó gần như không có giá trị cho kẻ tấn
công; đổi lấy UX rõ ràng là hợp lý.

Nếu về sau portal mở ra Internet, hai việc đi **cùng nhau**, không làm riêng lẻ:
bật rate limit theo IP (§7.1) **và** cân nhắc đưa nhánh 409 về 202. Bật rate limit
mà giữ 409 chỉ làm chậm máy dò; đổi về 202 mà không rate limit thì vẫn spam thư
được.

⚠ Việc này **không** kéo theo thay đổi nào ở `dang_nhap` — xem §4.2b.

## 8. Migration — `invites.tenant_id`

Một cột, một FK:

```sql
ALTER TABLE control.invites
  ADD COLUMN tenant_id text
    REFERENCES control.tenants(id) ON DELETE CASCADE;
```

`NULL` = token đăng ký tự phục vụ. Có giá trị = token mời vào đúng workspace đó.
`kind` (§6.1) suy từ `tenant_id IS NULL`, **không** lưu thành cột thứ hai — hai cột
nói cùng một sự thật là hai cột sẽ lệch nhau.

`ON DELETE CASCADE`: workspace bị xoá thì lời mời vào nó không còn nghĩa.

**Không backfill.** Mọi hàng `invites` đang sống lúc chạy migration đều là token
mời, nhưng để `NULL` là **đúng** — chúng sinh ra ở thời kỳ chưa có khái niệm này,
và đoán ngược `tenant_id` từ `memberships` sẽ sai với người thuộc nhiều workspace.
Token hạn 7 ngày; hàng cũ tự hết.

**`down_revision` = `0106_bo_organizations`** (head đo được 2026-08-17) — nhưng
**đọc lại `alembic heads` lúc thi công**, đừng tin con số trong spec. Hai MR song
song cùng nhận một cha ⇒ hai head ⇒ `alembic upgrade head` gãy cho cả team; đã xảy
ra ba lần (`0914`, `0919`, `0920`), cổng canh `tests/unit/test_alembic_mot_head.py`.

**Kéo theo — `repo.ghi_loi_moi` đổi chữ ký lần thứ hai.** `0105` vừa bỏ `org_id`
khỏi hàm này; nay thêm `tenant_id: str | None`. Ba người gọi phải sửa theo:
`quan_tri_user.tao`, `quan_tri_user.moi_lai`, `cli/seed_owner.py` (truyền
`tenant_id` của workspace nó vừa tạo).

`downgrade()`: `DROP COLUMN tenant_id`. Mất mát duy nhất là phân biệt hai loại
token của hàng còn sống — chấp nhận được, chúng hết hạn trong 7 ngày.

## 9. Test

**Backend — thêm:**

- `POST /auth/register` tạo user `pending` + `password_hash IS NULL` + hàng
  `invites` với `tenant_id IS NULL`, và **không** đặt cookie phiên
- **Ba nhánh §4.1 trả đúng ba mã 201 / 200 / 409** — bài neo quyết định §4.2
- Đăng ký lại khi `pending` ⇒ **200**, token cũ chết, token mới sống, thư gửi lại
- Đăng ký email `active` ⇒ **409 `EMAIL_TAKEN`**, không hàng `invites` nào được
  ghi, **không thư nào gửi** (nhánh này không được là một đường bắt server gửi thư)
- **`dang_nhap` vẫn gộp ba tình huống vào một mã** và vẫn gọi `pw.kiem_gia()` cho
  nhánh `pending` — bài canh §4.2b, để đợt sau không ai gỡ nhầm theo §4.2
- `GET /invites/{token}` trả `kind='signup'` cho token đăng ký, `kind='invite'` cho
  token mời
- Trọn vòng: register → accept → login ⇒ phiên `tenant_id=None`, `workspaces=[]`
- **Bốn endpoint `/members`**: `POST` ba nhánh (§4.4) với lỗi theo từng dòng;
  `PATCH` chỉ đổi một hàng và **không** đụng membership ở workspace khác — bài này
  neo trực tiếp bug 2026-08-06; `DELETE` gỡ membership mà `users` còn nguyên;
  `POST .../invite` giết token cũ
- `SIGNUP_ENABLED=false` ⇒ 403 `FEATURE_DISABLED`
- Mailer: `SMTP_HOST` rỗng ⇒ không gửi, `invitePath` **khác** `null`
- Mailer ném exception ⇒ request vẫn trả đúng mã của nhánh đó (201/200), user vẫn
  tồn tại (§5.4)
- `Settings(_env_file=None)` cho mọi bài đo giá trị mặc định — gotcha ở `CLAUDE.md`
- Migration: upgrade/downgrade, `ON DELETE CASCADE` thật sự dọn hàng

**Backend — sửa:** mọi test đang khẳng định `POST /auth/register` trả `SessionOut`
/ 201 / 409 (viết lại theo §4.1), `test_nhan_loi_moi.py` (thêm `kind`),
`test_contracts_user.py`, `test_schema.py`, `tests/api/test_contracts.py`,
`tests/integration/test_seed_owner.py` (chữ ký `ghi_loi_moi`).

**Frontend — sửa:** `dang-ky.tsx` test (bỏ ô mật khẩu; **ba màn kết quả theo
201/200/409**, gồm nút "Đăng nhập" ở nhánh 409 — §4.2), `nhan-loi-moi.test.tsx`
(mock `kind`), `thanh-vien-seam.test.ts`, MSW handlers.

## 10. Thứ tự thi công

Đợt bỏ organization **đã merge**, nên **không còn chờ ai**. Điều kiện chặn của bản
spec đầu đã hết hiệu lực.

Thứ tự bên trong đợt này:

1. `core/mailer.py` + `Settings` (SMTP, `PUBLIC_BASE_URL`, `SIGNUP_ENABLED`) —
   độc lập, không chạm `modules/auth`
2. Migration `invites.tenant_id` + sửa chữ ký `ghi_loi_moi` và ba người gọi
3. **Bốn endpoint `/members` ghi (§4.4a)** — làm trước §4.4 vì §4.4 là hành vi
   bên trong chúng; và làm sớm vì nó **sửa một chức năng đang chết**, độc lập với
   phần email
4. Viết lại `POST /auth/register` (§4.1) + `LoiMoiOut.kind`
5. Ba nhánh đường mời (§4.4) + `invitePath` trả `null`
6. FE: `dang-ky.tsx`, `NhanLoiMoi` theo `kind`, seam `/members`

⚠ Bước 3 và bước 4 đều chạm `modules/auth/router.py` và `contracts.py`. Nếu tách
MR thì làm **nối tiếp**, không song song — cùng lý do đã làm gãy alembic ba lần.

## 11. Ngoài phạm vi

- **Quên mật khẩu** (§7.4) — luồng riêng, cùng cơ chế token, đợt sau
- **Rào chống lạm dụng** (§7.1) — quyết định tường minh; `SIGNUP_ENABLED` là thứ
  duy nhất có ở đợt này
- Bật lại `USERS_ADMIN_ENABLED` / `ROLES_CRUD_ENABLED` — cần mô hình admin thật
- Đổi email của tài khoản đã có
- Thư nhắc khi token sắp hết hạn
- Hàng đợi / retry cho mail hỏng — §5.4 chọn nuốt lỗi và dựa vào "đăng ký lại"
- Template engine cho thư — ba loại thư dựng bằng f-string
- Xin SES production access (§7.3) — việc vận hành
