# Gọn màn Thành viên & Phân quyền

**Ngày:** 2026-08-09
**Trạng thái:** thiết kế đã chốt, chưa triển khai
**Phạm vi:** FE định hợp đồng trước — backend làm theo sau (cùng lối `POST /agent/try`, `GET/PATCH /linh-vuc`)

---

## 0. Vì sao

Người dùng nói nguyên văn: _"phần các thành viên và phân quyền đang hơi rắc rối, thấy như
dùng các hệ thống SaaS, 1 ô tạo ra workspace xong thêm user vào là xong"_.

Cảm giác đó có con số đằng sau. Để dùng được màn `/users` hôm nay, người dùng phải nắm **tám**
khái niệm: người dùng · vai trò tổ chức (`orgRole`) · vòng đời (`lifecycle`) · vai trò workspace ·
membership · hạn membership (`expiresAt`) · workspace · token mời. Linear có **ba**.

Đối chiếu ba hệ được nêu:

|                       | Odyssey (2026-08-09)               | ElevenLabs           | Linear                 | Vercel                            |
| --------------------- | ---------------------------------- | -------------------- | ---------------------- | --------------------------------- |
| Vai trò dựng sẵn      | 4 (admin/care/editor/viewer)       | Admin + không-admin  | Admin · Member · Guest | Owner · Member · Viewer · Billing |
| **Vai trò tuỳ chỉnh** | ✅ tự tạo, tích 13 nhóm action     | ❌                   | ❌ _cố ý không có_     | ❌                                |
| Tầng thứ hai          | org ↔ workspace                    | seat type            | team membership        | project role                      |
| Gom quyền theo nhóm   | ❌                                 | user groups          | ❌                     | ❌                                |
| Membership hết hạn    | ✅ `expiresAt`                     | ❌                   | ❌                     | ❌                                |
| Mời                   | tạo user → gán membership (2 bước) | email + role, 1 bước | email + role, 1 bước   | email + role, 1 bước              |

Hai điều đọc ra:

1. **Không hệ nào có vai trò tuỳ chỉnh.** Linear ghi thẳng trong docs là không có custom role và
   không có permission set chi tiết ngoài mấy vai trò dựng sẵn. Mình có — và tab «Vai trò» với ma
   trận 13 nhóm action là thứ nặng nhất trên màn. Đó là tính năng hạng enterprise đang bày ra cho
   mọi người từ ngày đầu.
2. **Hướng này đã đi rồi mà chưa gọi tên.** 2026-08-09 đã gộp hai bảng của `/users` làm một và bỏ
   cột «Chức danh». Spec này là bước tiếp theo của cùng mũi tên, không phải đổi hướng.

## 1. Nguyên tắc

> `/users` trả lời **đúng một câu hỏi**: _ai đang ở trong workspace này, làm được gì._
> Mọi thứ không phục vụ câu đó rời khỏi màn.

**Cưỡng chế không đổi.** 13 action ở `core/auth/actions.py` và `require(action)` ở tầng API ở
nguyên. Thứ bị cắt là **bề mặt TÁC GIẢ** — quyền tự _định nghĩa_ vai trò — không phải bề mặt
_kiểm soát_. Không action mới, không migration, không đụng đường cưỡng chế.

Điều này quan trọng vì PQ_01 §BR-Q03 đã nói: ẩn nút không phải bảo vệ. Spec này ẩn nút; nó không
được phép làm gì hơn thế.

## 2. Bốn quyết định

### 2.1 · Giữ 4 vai trò song song, bỏ đường tự tạo

Bốn vai trò của PQ_01 §2.2 — Quản trị · CSKH · Biên tập · Người xem — **ở lại nguyên**. Lý lẽ của
§2.2 vẫn đúng và không hệ nào ở trên bác được nó: _chăm sóc khách hàng và nhập liệu dự án là hai
NGHỀ, không phải hai cấp bậc_. Hạ xuống Admin/Member kiểu ElevenLabs thì hoặc biên tập đọc được
hội thoại khách (dữ liệu cá nhân), hoặc CSKH sửa được quỹ căn.

Thứ bị bỏ là **tab «Vai trò»** — nơi tự tạo vai trò bằng cách tích 13 nhóm action.

13 action ở lại backend làm **định nghĩa** của 4 vai trò đó. Không mất gì về cưỡng chế; mất đúng
khả năng tạo vai trò thứ năm từ giao diện.

> Ngày có khách enterprise đòi vai trò riêng thì dựng lại — endpoint `POST/PATCH/DELETE /roles`
> và `GET /actions` **vẫn sống ở backend**, chỉ là FE thôi gọi. Đây là cắt bề mặt, không phải xoá
> năng lực.

### 2.2 · Trục của bảng = workspace đang mở

`/users` là danh sách thành viên của **workspace đang chọn trên switcher**, không phải của tổ chức.

Vì sao: một người có thể mang vai trò khác nhau ở nhiều workspace. Nếu bảng theo trục tổ chức thì
cột «Vai trò» hoặc phải là hàng lồng, hoặc phải là cột động «Vai trò tại \<workspace\>» kèm một
dòng giải thích. Theo trục workspace thì **mỗi hàng đúng một vai trò** — bảng phẳng, không giải
thích.

Muốn xem workspace khác thì đổi switcher. Giống Linear, Slack.

> ⚠ **Đây đảo một quyết định của 2026-08-09** ("bảng chính là người dùng toàn tổ chức", và tên
> màn đổi theo đó). Quyết định cũ đúng khi màn phải gánh cả hai câu hỏi; spec này bỏ một câu.

Người dùng xác nhận: **một số khách có nhiều workspace**, không phải đa số. Nên hai tầng org ↔
workspace ở lại trong dữ liệu, nhưng **không xuất hiện trên màn thành viên**.

### 2.3 · Mời một bước, theo lối ba hệ kia

Ba hệ đều cùng một hình: **email (nhiều cái một lần) + chọn vai trò trong CÙNG bước** → quyền
được khoanh từ cú bấm đầu tiên. Hôm nay mình là hai bước: tạo user cấp tổ chức, rồi gán membership.

### 2.4 · Cắt `expiresAt` và `jobTitle` khỏi giao diện

- **`expiresAt`** — không hệ nào trong ba hệ có. Nó thêm một cột, một ô ngày, và một trạng thái
  «hết hạn» vào mọi chỗ. Cột DB giữ nguyên; `POST /members` **không nhận** trường này và server đặt
  `NULL`. Thu hồi quyền = gỡ khỏi workspace, một đường.
- **`jobTitle`** — chữ tự do, không lọc được, không sắp được, không quyết định quyền gì. Cột đã bỏ
  2026-08-09; giờ bỏ nốt khỏi form và bản xem.

**Giữ `orgRole = owner`** — phải có một người sở hữu gói cước và tạo được workspace mới. Hiện
thành pill «Chủ tổ chức» trên hàng của người đó.

## 3. Màn «Thành viên»

Route `/users` **giữ nguyên** (nav, `screens.ts`, `requiredActions` không đổi). Nhãn nav đổi
«Người dùng» → «Thành viên».

> Nhãn này vừa đổi **ngược chiều** hôm 2026-08-09 («Thành viên & Phân quyền» → «Người dùng»), với
> lý do _gọi tên màn theo BẢNG PHỤ — bảng chính là người dùng toàn tổ chức_. Lý do đó gắn liền với
> trục cũ. Trục đổi thì nhãn đổi theo: giờ bảng chính **là** thành viên workspace. Không phải đảo
> quyết định cũ — là hệ quả của §2.2. Vế «& Phân quyền» thì **không** quay lại: luật «nhãn nav là
> tên một CHỖ, không phải mục lục» vẫn đứng.

```
Thành viên                                        [Mời thành viên]
[🔍 Tìm tên hoặc email]   [Tất cả ▾]

┌───────────────────────────┬───────────┬────────────────────┬───┐
│ TĐ  Trần Hải Đăng         │ Quản trị  │ Đang hoạt động     │ ⋯ │
│     dang@anphuland.vn     │           │  Chủ tổ chức       │   │
├───────────────────────────┼───────────┼────────────────────┼───┤
│ NL  Nguyễn Lan            │ CSKH      │ Chưa nhận lời mời  │ ⋯ │
│     lan@anphuland.vn      │           │                    │   │
└───────────────────────────┴───────────┴────────────────────┴───┘
                                                    4 thành viên
```

- **Không còn hàng tab** — màn chỉ còn một thứ. `NhomTab` rời màn này.
- Bộ lọc trạng thái: `Tất cả` · `Đang hoạt động` · `Chưa nhận lời mời` · `Đã khoá`.
- Cột **Trạng thái** đọc `lifecycle` (`pending` | `active` | `suspended`) — kiểu này **đã có sẵn**,
  spec không thêm giá trị nào. Màn **hiện** cả ba nhưng **không cấp đường đặt** `suspended`; gỡ
  người là gỡ khỏi workspace.
- Ô tìm dùng `O_LOC`, nhóm lọc dùng `CAO_O` — đã là hệ chung từ 2026-08-09.

### 3.1 · Menu `⋯`

| Mục                 | Khi nào hiện                                      |
| ------------------- | ------------------------------------------------- |
| `Đổi vai trò…`      | luôn                                              |
| `Sửa hồ sơ…`        | luôn                                              |
| `Gửi lại lời mời`   | `lifecycle === 'pending'`                         |
| `Huỷ lời mời`       | `lifecycle === 'pending'`                         |
| `Gỡ khỏi workspace` | luôn, trừ chính mình và trừ `orgRole === 'owner'` |

**Vai trò chuyển từ `<select>` sống trong hàng sang sau `⋯`.** Đây là đổi so với hôm nay, và lý do
là chính luật của repo (CLAUDE.md, «Xem trước, sửa sau»):

> _form mở sẵn nói «hãy điền» trong khi việc thật là «hãy đọc», và nó mời gõ nhầm vào dữ liệu đang
> phát hành … ở `/users` còn nặng hơn — mở thẳng form là bày một bảng phân quyền đang sửa được cho
> một thao tác chỉ để xem._

Một `<select>` quyền hạn luôn sống trong bảng là đúng ca đó. Linear cũng đặt sau `⋯`. Giá: thêm
một cú bấm để đổi vai trò — chấp nhận, vì đổi vai trò là việc hiếm còn đọc bảng là việc thường.

`Sửa hồ sơ…` mở form **hai ô**: tên + số điện thoại. Không có `jobTitle`, không có email (email là
khoá đăng nhập), không có vai trò (đã có mục riêng).

> **Đã cân nhắc và bỏ:** dựng màn hồ sơ cá nhân để chính chủ tự sửa (lối Linear — admin không sửa
> hộ ai). Đúng hơn về nguyên tắc nhưng là **một màn mới** = 4 bước theo luật repo, cho một việc
> chưa ai đòi. Đổi sang lối đó sau này rẻ: bỏ một mục khỏi `⋯`.

### 3.2 · Hộp thoại «Mời thành viên»

```
Email      [lan@anphuland.vn ×] [minh@anphuland.vn ×] [gõ email…]
Vai trò    ( ) Quản trị   (•) CSKH   ( ) Biên tập   ( ) Người xem

                                        [Huỷ]   [Gửi lời mời]
```

- **Nhiều email một lần**, cùng một vai trò. Muốn hai vai trò thì mời hai lượt — đúng lối ba hệ kia.
- Email đã có trong tổ chức ⇒ **thêm thẳng vào workspace**, không tạo user trùng, không sinh lời mời.
- Email đã ở trong workspace này ⇒ báo tại chỗ, không gửi.
- Gửi xong hàng hiện **ngay** với trạng thái «Chưa nhận lời mời».
- Hàng nút theo `HANG_NUT` (căn phải, nút chính cuối).

### 3.3 · Panel sau khi gửi — chỗ DUY NHẤT lệch với Linear

**Backend không có bộ gửi mail.** `grep -rEi 'smtp|sendgrid|mailgun|send_email|aiosmtplib'` trên
`odyssey-portal-backend/src` → rỗng (đo 2026-08-09). Luồng hiện tại là backend trả `invitePath`,
admin tự copy link đi gửi qua Zalo.

Nên phần **hình dạng thao tác** bê nguyên được, phần **giao link** thì không:

```
Đã mời 2 người. Chưa có email tự động — gửi link này cho họ:

  lan@anphuland.vn     https://…/invite/a1b2c3      [Sao chép]
  minh@anphuland.vn    https://…/invite/d4e5f6      [Sao chép]
```

Thiết kế để khác biệt gói **trọn trong panel này**. Ngày backend có mailer, `invitePath` về `null`
và panel đổi thành một dòng «Đã gửi email tới 2 người.» — không đụng gì khác trong màn.

## 4. Hợp đồng API — FE định trước

`/api/v1/members` lên làm seam chính. Khai ở `features/auth/thanhVien.ts` (đã là chỗ của
`MemberOut`).

### 4.1 · `GET /api/v1/members`

`MemberOut` mọc thêm **hai** trường:

```ts
export interface MemberOut {
  readonly userId: string
  readonly name: string
  readonly email: string
  readonly roleId: string // neo — KHÔNG đối chiếu ngược theo tên
  readonly role: string // hiện
  readonly lifecycle: Lifecycle // MỚI — 'pending' | 'active' | 'suspended'
  readonly isOrgOwner: boolean // MỚI — pill «Chủ tổ chức»
}
```

`roleId` là **bắt buộc** và mọi `<select>`/menu neo vào nó. Đối chiếu ngược tên → id đã bị xoá
2026-08-07 vì nó là lỗi leo thang quyền xuyên workspace **đo được**, không phải rủi ro lý thuyết.
Đừng dựng lại.

`isOrgOwner` là trường **phái sinh** ở server (`users.org_role === 'owner'`), không phải cột mới.
Lý do trả kèm thay vì để FE tự suy: sau khi bỏ trục org, FE **không còn** đọc `GET /users` nữa —
nó không có chỗ nào khác biết ai là chủ tổ chức.

### 4.2 · Bốn endpoint

| Method   | Đường                      | Thân                                 | Trả                                                                       |
| -------- | -------------------------- | ------------------------------------ | ------------------------------------------------------------------------- |
| `POST`   | `/members`                 | `{emails: string[], roleId: string}` | `{invites: [{email, userId, invitePath: string \| null, daCo: boolean}]}` |
| `PATCH`  | `/members/{userId}`        | `{roleId: string}`                   | `MemberOut`                                                               |
| `DELETE` | `/members/{userId}`        | —                                    | `204`                                                                     |
| `POST`   | `/members/{userId}/invite` | —                                    | `{invitePath: string \| null}`                                            |

- **`POST /members`** làm cả hai việc trong một lượt: email chưa có trong tổ chức thì tạo user
  `pending` + membership + token; email đã có thì chỉ tạo membership (`daCo: true`,
  `invitePath: null`). Trả **mảng theo từng email** để panel §3.3 nói đúng từng người.
- **`DELETE /members/{userId}`** gỡ khỏi **workspace đang mở**, KHÔNG xoá user khỏi tổ chức.
  Việc này giải luôn một lỗ đang có: `DELETE /users/{id}` chỉ chạy khi user còn `pending`, ngoài
  ra `409 USER_NOT_PENDING` — tức **hôm nay không có đường gỡ một người đang hoạt động**.
- **`invitePath` là `string | null`** ngay từ hợp đồng, để ngày có mailer backend đổi giá trị chứ
  không đổi hình dạng.

### 4.3 · Mã lỗi

| Mã                    | Khi nào                    | UI nói gì                                  |
| --------------------- | -------------------------- | ------------------------------------------ |
| `ROLE_NOT_IN_ORG`     | `roleId` của tổ chức khác  | «Vai trò không thuộc tổ chức này.»         |
| `ALREADY_MEMBER`      | email đã ở trong workspace | báo tại chỗ cạnh chip email đó             |
| `CANNOT_REMOVE_OWNER` | gỡ chủ tổ chức             | mục `⋯` không hiện; 409 là phòng tuyến hai |
| `CANNOT_REMOVE_SELF`  | tự gỡ mình                 | như trên                                   |

### 4.4 · Endpoint FE thôi gọi (backend giữ nguyên)

`POST /roles` · `PATCH /roles/{id}` · `DELETE /roles/{id}` · `GET /actions` ·
`POST /users` · `PATCH /users/{id}` · `DELETE /users/{id}` · `POST /users/{id}/invite` ·
`GET /users` · `GET /users/{id}`.

`GET /roles` **vẫn gọi** — cần để dựng danh sách 4 vai trò trong hộp thoại mời và menu đổi vai trò.

`GET /invites/{token}` và `POST /invites/accept` **không đổi** — màn nhận lời mời (`NhanLoiMoi.tsx`)
ở nguyên.

## 5. Cố ý KHÔNG làm

| Không làm                                                 | Vì sao                                                                                                                                                                      |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Màn "tất cả người trong tổ chức"                          | Nhiều workspace thì đổi switcher. Thêm khi thật sự vướng, không thêm trước.                                                                                                 |
| `suspend` như Linear                                      | Suspend chỉ đáng khi cần giữ lịch sử «ai tạo bản ghi này»; portal chưa hiện thông tin đó ở đâu. Giá trị `suspended` đã có trong kiểu nên vẫn HIỆN được, chỉ không đặt được. |
| User group như ElevenLabs                                 | Group có nghĩa khi quyền gắn vào _tài nguyên rời_. Quyền của mình gắn vào _loại việc_.                                                                                      |
| Seat type như ElevenLabs                                  | Đó là cấu trúc **tính tiền**, không phải phân quyền. Thuộc màn Gói cước, và màn đó đang hoãn.                                                                               |
| Agent-as-principal, scope API key, cổng phê duyệt publish | Đã khảo sát trong phiên này, **không thuộc spec này**. Xem §7.                                                                                                              |
| Đụng `core/auth/actions.py`                               | Không action mới. Cưỡng chế không đổi.                                                                                                                                      |

## 6. Ảnh hưởng lên code

### 6.1 · Xoá

| Tệp                                           | Dòng      |
| --------------------------------------------- | --------- |
| `features/auth/components/DanhSachVaiTro.tsx` | 321       |
| `features/auth/components/FormVaiTro.tsx`     | 201       |
| `features/auth/components/TomTatVaiTro.tsx`   | 60        |
| `features/auth/components/TomTatUser.tsx`     | 65        |
| `features/auth/components/MemberList.tsx`     | 267       |
| `features/auth/tabUsers.ts`                   | 25        |
| `tests/vai-tro.test.tsx`                      | 389       |
| **Tổng xoá hẳn**                              | **~1328** |

`MemberList` xoá chứ không gộp: nó tồn tại cho **nhánh không-phải-chủ-tổ-chức** của màn cũ. Sau
khi trục đổi sang workspace thì mọi người thấy **cùng một bảng** — nhánh đó không còn.

Cắt bớt (không xoá tệp): `UserForm.tsx` 777 → ~120 (còn hai ô tên + điện thoại) ·
`UserAdmin.tsx` 697 → ~350 (viết lại quanh một bảng) · `api.ts` bỏ 7 hàm role/user.

Ước lượng ròng: **−1500 đến −1800 dòng**.

### 6.2 · Sửa

- `features/auth/thanhVien.ts` — `MemberOut` + 4 hàm mới của §4.2
- `features/auth/components/UserAdmin.tsx` — viết lại
- `features/auth/components/MoiThanhVienDialog.tsx` — **MỚI**
- `features/auth/nav.ts` + `i18n` — nhãn «Người dùng» → «Thành viên»
- `lib/msw/handlers.ts` — 4 handler mới; bỏ handler `/roles` ghi và `/actions` thì **giữ**
  (backend vẫn có, và luật repo là fake phải nói đúng backend chứ không nói đúng UI)

### 6.3 · Test

| Tệp                                     | Việc                                                                                                                                  |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/vai-tro.test.tsx`                | xoá                                                                                                                                   |
| `tests/user-admin.test.tsx` (1200 dòng) | viết lại quanh bảng mới + hộp thoại mời                                                                                               |
| `tests/members.test.tsx`                | xoá — nó test `MemberList`, tệp đó không còn. Phép kiểm còn giá trị (đọc được danh sách thành viên) chuyển sang `user-admin.test.tsx` |
| `tests/membership-shape-parity.test.ts` | **cập nhật** — cổng này neo vào đúng khai báo `MemberOut`, thêm 2 trường là phải sửa fake cho khớp                                    |
| `tests/nav-registry.test.ts`            | nhãn nav đổi                                                                                                                          |
| `tests/actions-parity.test.ts`          | **KHÔNG đổi** — 13 action không đụng tới                                                                                              |

Bài mới cần có:

1. Mời 2 email cùng lúc ⇒ `POST /members` nhận đúng `{emails: [2 cái], roleId}`
2. Mời email đã có trong tổ chức ⇒ không sinh `invitePath`, hàng vẫn hiện
3. Đổi vai trò qua `⋯` ⇒ `PATCH /members/{id}` mang `roleId`, **không** mang tên
4. `⋯` **không** có mục «Gỡ khỏi workspace» trên hàng chủ tổ chức và trên hàng chính mình
5. Bảng **không** chứa `<select>` nào ở chế độ nghỉ (neo luật «xem trước, sửa sau»)
6. Lọc «Chưa nhận lời mời» ⇒ chỉ còn hàng `pending`

## 7. Việc KHÔNG thuộc spec này

Phiên khảo sát 2026-08-09 tìm ra bốn hạng mục về quyền cho **agent**, tách riêng vì chúng đụng
backend enforcement và không liên quan tới cảm giác «rắc rối» của màn thành viên:

| #   | Việc                                                  | Ghi chú                                                                                                                                  |
| --- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Tách action **phát hành** khỏi **sửa** cấu hình agent | Rẻ nhất, bán kính sát thương lớn nhất — sửa cấu hình đổi thứ agent nói với **mọi** khách                                                 |
| 2   | Xác minh chặn tự-leo-thang khi gán vai trò            | Một admin có gán được vai trò chứa action họ không có? Nếu có thì mọi ràng buộc khác vô nghĩa. Nằm ở backend, chưa kiểm được từ repo này |
| 3   | Scope cho API Key                                     | Khoá hiện là bearer cấp workspace; một khoá rò là rò trọn workspace. Fin của Intercom phát token scope tối thiểu                         |
| 4   | Nhật ký đổi quyền                                     | BR-Q07 đã log _đọc transcript_; chưa log _ai đổi vai trò của ai_                                                                         |

**Một kết luận cần ghi lại** để lần sau không đi lại: _"agent đọc dữ liệu theo quyền của người
hỏi"_ — mẫu của Fin (lọc article theo audience của khách) — **không áp dụng được cho Odyssey**.
Agent của mình hướng **khách hàng cuối** (qua số điện thoại, `/convos/$phone`), và khách **không có
danh tính** trong hệ thống. Câu đúng cho mình là _agent được phép TIẾT LỘ gì cho một người lạ chưa
xác thực_ — tức họ hàng của 6 rào chắn và `tools.enabled`, không phải của RBAC.

## 8. Nguồn tham khảo

- [ElevenLabs — Workspace Members](https://elevenlabs.io/docs/overview/administration/workspaces/members) · [User groups](https://elevenlabs.io/docs/overview/administration/workspaces/user-groups)
- [Linear — Members and roles](https://linear.app/docs/members-roles)
- [Vercel — RBAC](https://vercel.com/docs/rbac) · [Managing team members](https://vercel.com/docs/rbac/managing-team-members)
- [WorkOS — Designing multi-tenant RBAC](https://workos.com/blog/how-to-design-multi-tenant-rbac-saas) · [What Slack, Notion, Linear teach us](https://workos.com/blog/multi-tenant-permissions-slack-notion-linear)
- [Intercom — Fin AI Agent explained](https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained) · [Fin Agent API setup](https://developers.intercom.com/docs/guides/fin-agent-api/setup)
