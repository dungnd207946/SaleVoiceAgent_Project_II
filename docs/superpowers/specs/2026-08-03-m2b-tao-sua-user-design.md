# M2b — Tạo · sửa user và phân quyền workspace

> Trạng thái: thiết kế đã chốt, thi công ngay trong cùng lượt (không qua bước plan —
> chủ dự án chốt 2026-08-03: "đây chỉ là 1 chức năng nhỏ, tạo dữ liệu user để demo
> theo các quyền").
>
> Tiền đề: [M2a](2026-07-30-m2a-be-xac-thuc-phien-vo-api.md) ·
> [tầng organization](2026-08-03-organization-layer-design.md)

---

## 0. Phạm vi

### 0.1 Trong phạm vi

1. **Trường hồ sơ tuỳ chọn** — `users.phone`, `users.job_title`.
2. **`lifecycle = 'pending'`** — user đã tạo, chưa đặt mật khẩu.
3. **`control.invites`** — thư mời một-lần, lưu `sha256(token)`.
4. **CRUD user cấp tổ chức** — liệt kê · tạo · sửa · xoá-khi-chưa-nhận-mời · mời lại.
5. **Gán membership nhiều workspace** trong cùng một lần lưu, mỗi dòng có `role` + `expires_at` riêng.
6. **Màn FE**: danh sách user của tổ chức · form tạo/sửa · màn đặt mật khẩu từ link mời.
7. **Sửa hai bug đã có**: `fake.py` vỡ lúc import · `dang_nhap()` sẽ nổ khi gặp `password_hash IS NULL`.

### 0.2 Ngoài phạm vi — và thuộc về đâu

| Thứ | Thuộc |
|---|---|
| **Gửi email thật** | Chủ dự án chốt: API trả đường dẫn mời, admin tự đưa. Đánh đổi đã ghi nhận ở §1④ |
| Đổi mật khẩu · quên mật khẩu | M8 (cùng rate limit đăng nhập) |
| Ma trận `role × action` trong `require()` | Vẫn treo. Xem §3.3 — vì sao việc này **không** chặn M2b |
| Console Nền tảng xuyên tổ chức | Module mới, chưa ai sở hữu (M2a §10.1) |
| Vai trò tuỳ chỉnh · 2FA · SSO | Sau MVP (PQ_01 §III) |

---

## 1. Sáu quyết định đã chốt

① **Không có module mới.** Mở rộng `modules/auth/`, đúng ranh giới M2a §2.3: *"`core` sở hữu 'ai là ai, được làm gì'; `modules/auth` sở hữu 'user và membership được nhập/sửa/đọc thế nào'"*. Thêm module = thêm một `contracts.py` phải bảo trì cho một việc mà module đã có sở hữu sẵn.

② **`org_id` KHÔNG BAO GIỜ đọc từ thân request** — luôn suy từ phiên của admin. Cho client gửi `orgId` là cho một org owner đẩy user sang tổ chức khác; composite FK của 0102 sinh ra để chặn đúng điều đó ở tầng Postgres, và mở lại lỗ ở tầng HTTP thì FK chỉ còn tác dụng biến lỗ hổng thành lỗi 500.

③ **Cửa thật là `org_role = 'owner'`, không phải `require(WORKSPACE_ADMIN)`.** Ở M2a `require()` cấp cả 13 action cho mọi thành viên, nên khai `WORKSPACE_ADMIN` là **chỗ cắm**, chưa phải chặn. Mọi endpoint ghi ở đây kiểm `org_role` một lần nữa trong service — và phép kiểm đó là phép kiểm duy nhất đang thật sự chặn. Ghi rõ ở đây để lúc M2b-quyền bật ma trận lên, không ai xoá phép kiểm này vì tưởng nó dư.

④ **Không gửi email.** `POST /users` trả `invitePath`. Đánh đổi chủ dự án đã chấp nhận: **không có seam gửi thư**, nên lúc muốn gửi thật sẽ phải sửa `service.py`, không phải cắm thêm một adapter.

⑤ **Trả đường dẫn TƯƠNG ĐỐI (`/invite/<token>`), không phải URL tuyệt đối.** URL tuyệt đối buộc BE phải biết origin của FE — một biến môi trường nữa, và nó sai ở đúng lúc tệ nhất (mở portal qua IP LAN, qua proxy, qua domain staging). FE ghép `location.origin`; nó biết chắc mình đang ở đâu.

⑥ **Lưu `sha256(token)`, không lưu token thô.** Cùng lý lẽ với `password_hash`: người đọc được DB không dùng được thư mời.

---

## 2. Bảng

### 2.1 Migration `0103_user_ho_so_va_invite`

`down_revision = "0900_enrollment"` (head hiện tại).

```sql
-- ① Hồ sơ tuỳ chọn
ALTER TABLE control.users ADD COLUMN phone     text;
ALTER TABLE control.users ADD COLUMN job_title text;

-- ② lifecycle thêm 'pending'
ALTER TABLE control.users DROP CONSTRAINT users_lifecycle_check;
ALTER TABLE control.users ADD  CONSTRAINT users_lifecycle_check
  CHECK (lifecycle IN ('pending', 'active', 'suspended'));

-- ③ password_hash NULL đúng khi và chỉ khi pending
ALTER TABLE control.users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE control.users ADD CONSTRAINT users_password_theo_lifecycle_check
  CHECK ((lifecycle = 'pending') = (password_hash IS NULL));

-- ④ Thư mời
CREATE TABLE control.invites (
    token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    user_id    text NOT NULL UNIQUE,
    org_id     text NOT NULL,
    expires_at timestamptz NOT NULL,
    used_at    timestamptz,
    created_by text REFERENCES control.users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT invites_org_user_fkey
      FOREIGN KEY (org_id, user_id) REFERENCES control.users (org_id, id) ON DELETE CASCADE
);

-- ⑤ audit_log ghi được hành động cấp tổ chức
ALTER TABLE control.audit_log ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE control.audit_log ADD COLUMN org_id text REFERENCES control.organizations(id) ON DELETE CASCADE;
ALTER TABLE control.audit_log ADD CONSTRAINT audit_log_co_pham_vi_check
  CHECK (tenant_id IS NOT NULL OR org_id IS NOT NULL);
```

### 2.2 Bốn quyết định trong migration này

**`(lifecycle = 'pending') = (password_hash IS NULL)` là song điều kiện, không phải một chiều.** Nó chặn cả hai trạng thái vô nghĩa cùng lúc: `pending` mà đã có hash (thư mời còn sống trong khi mật khẩu đã đặt), và `active` mà chưa có hash — cái sau là một tài khoản đăng nhập được không cần mật khẩu, tức một cửa hậu lặng lẽ. Một chiều thì chỉ bắt được một nửa.

**`invites.user_id UNIQUE`** — mỗi user tối đa một thư mời còn sống. Mời lại ghi đè dòng cũ bằng `ON CONFLICT (user_id) DO UPDATE`, nên token trước đó **chết ngay**. Không UNIQUE thì mỗi lần bấm Mời lại sinh thêm một token dùng được, và thu hồi thành việc phải xoá n hàng mà không ai biết n bằng mấy.

**`invites` dùng COMPOSITE FK `(org_id, user_id)`, không phải FK đơn cột.** Cùng lý lẽ 0102 đã ghi cho `memberships`: `org_id` trên hàng invite phải khớp org của user, và ràng buộc đó chỉ thật khi nằm ở FK. Đặt trong service thì `psql` tay và mọi seed script đều đi vòng được.

**`created_by` NULLABLE + `ON DELETE SET NULL`.** Xoá người mời không được xoá thư mời của người được mời — hai chuyện khác nhau, và `CASCADE` gộp chúng lại.

**`invites` ở schema `control`, không `tenant_data`.** Nó là control-plane theo đúng nghĩa 0101 đã định: thư mời tồn tại **trước khi** user có tenant nào, nên đặt nó dưới RLS của tenant là vòng tròn. Grant đến từ `ALTER DEFAULT PRIVILEGES` của 0003 — không cần GRANT tay, và agent role vẫn có zero quyền.

**`audit_log_co_pham_vi_check`** — nới `tenant_id` thành NULL mà không thêm gì là mở đường cho một hàng nhật ký không thuộc phạm vi nào, tức một hàng không màn hình nào của M8 tìm thấy. CHECK buộc mỗi hàng phải có ít nhất một phạm vi.

---

## 3. Quyền

### 3.1 Ai làm được gì

| Hành động | Điều kiện |
|---|---|
| `GET /users`, `GET /users/{id}` | phiên + `org_role = 'owner'` |
| `POST /users`, `PATCH /users/{id}`, `DELETE /users/{id}`, mời lại | phiên + `org_role = 'owner'` |
| `GET /invites/{token}`, `POST /invites/accept` | **công khai** — người nhận mời chưa có phiên |

Mọi endpoint đọc/ghi user khai `require(ACTIONS.WORKSPACE_ADMIN)` để qua cổng 1, rồi kiểm `org_role` trong service (xem §1③). Hai đường thư mời khai `require(None, ly_do=...)`: token **chính là** chứng cứ, và bắt đăng nhập để đặt mật khẩu lần đầu là một vòng tròn.

### 3.2 Hai luật chống tự khoá cửa

Cả hai nằm trong service (`quan_tri_user.sua`), kiểm trước khi ghi, cùng mã `SELF_LOCKOUT`:

1. **Không tự hạ `org_role` của mình** từ `owner` xuống `member`.
2. **Không tự đình chỉ mình.**

Vì sao hai luật này không phải chuyện lý thuyết: `owner` là con đường duy nhất vào màn quản trị tổ chức, và không có console Nền tảng (M2a §10.1) để cứu. Mất owner cuối cùng nghĩa là phải sửa DB bằng tay trên production.

**"Không xoá owner cuối cùng" KHÔNG cần một phép kiểm thứ ba** — nó đã được hai luật trên cộng hai ràng buộc khác bao trùm kín:

- `DELETE` chỉ nhận user còn `pending`. Người thao tác luôn `active` (họ vừa gọi API), nên họ không xoá được chính mình, và một owner `pending` bị xoá thì owner `active` kia vẫn còn.
- `PATCH` hạ quyền một owner **khác** vẫn để lại người thao tác — vốn là owner.

Nên mọi đường ghi đều để tổ chức có ≥1 owner `active`. Thêm một phép `dem_owner() > 1` nữa là một phép kiểm không bao giờ sai được: nó chỉ tạo cảm giác an toàn và một nhánh code không có test nào đi qua. (`repo.dem_owner()` vẫn tồn tại — nó là chỗ cắm sẵn cho ngày có đường ghi thứ ba, ví dụ xoá user `active`.)

### 3.3 Vì sao M2b-user không chờ M2b-quyền

Ma trận `role × action` trong `require()` vẫn treo. Nó **không** chặn việc này, vì phép chặn thật ở đây là `org_role` — một cột đọc trực tiếp, không đi qua ma trận. Khi ma trận bật lên, `actions` trong `SessionOut` hẹp lại và FE ẩn thêm mục nav; không endpoint nào ở spec này phải sửa.

Nói thẳng hệ quả còn lại: **hôm nay một `member` có membership `viewer` vẫn gọi được `GET /members`** (M2a §4.1 đã ghi). Spec này không làm chuyện đó tệ hơn và cũng không sửa nó.

---

## 4. Hợp đồng API

Tiền tố `/api/v1` do `api/app.py` gắn.

| Method | Đường | Vào | Ra |
|---|---|---|---|
| GET | `/users` | — | `UserListItemOut[]` |
| GET | `/users/{user_id}` | — | `UserDetailOut` |
| POST | `/users` | `TaoUserIn` | `TaoUserRaOut` (201) |
| PATCH | `/users/{user_id}` | `SuaUserIn` | `UserDetailOut` |
| DELETE | `/users/{user_id}` | — | 204 · chỉ khi `lifecycle = 'pending'` |
| POST | `/users/{user_id}/invite` | — | `MoiLaiRaOut` · chỉ khi `pending` |
| GET | `/invites/{token}` | — | `LoiMoiOut` |
| POST | `/invites/accept` | `NhanLoiMoiIn` | 204 |

### 4.1 Hai luật cross-field, cưỡng chế trong Pydantic

```
orgRole = 'owner'  →  memberships PHẢI rỗng
orgRole = 'member' →  memberships PHẢI có ≥ 1 dòng
```

Đặt ở contract chứ không ở service để chúng trả **422** ngay tại biên nhập, cùng khuôn lỗi với mọi lỗi kiểu khác.

**Một chỗ nói rõ để không ai kỳ vọng sai** (đo được lúc verify): vì đây là `model_validator`, `error.fields[0].field` là `"body"` — không phải tên một ô cụ thể. Điều đó **đúng về nghĩa** (luật cross-field không thuộc ô nào), nhưng nghĩa là FE **không** tô đỏ được một ô từ payload lỗi. Cơ chế thật ở FE là hai nhắc nhở tại chỗ ở §5.1 — 422 chỉ là lưới cuối. Đừng thay hai nhắc nhở đó bằng "cứ để server báo".

Nửa đầu là hệ quả trực tiếp của org spec §3: `owner` thấy mọi tenant trong org **không cần** dòng membership nào. Nhận dữ liệu membership từ một form `owner` rồi lặng lẽ bỏ qua là loại bug tệ nhất — người dùng nhập, hệ thống nhận, và không gì xảy ra.

Nửa sau là PQ_01 Q01 đọc ngược: phiên không có workspace nào là trạng thái **HỎNG**. `POST /auth/login` đã trả `409 NO_WORKSPACE` cho nó. Tạo ra một user như vậy rồi mới phát hiện lúc họ đăng nhập là đẩy lỗi của admin sang cho người dùng.

### 4.2 Mã lỗi mới — ở `modules/auth/loi.py`

`api/loi.py` ghi: *"Module sau thêm hằng số của nó vào file của nó"*. Theo đúng khuôn `modules/enrollment/loi.py`.

| Mã | HTTP | Khi nào |
|---|---|---|
| `EMAIL_TAKEN` | 409 | email đã có trong `control.users` (UNIQUE toàn cục, không theo org) |
| `USER_NOT_FOUND` | 404 | không có user đó **trong org của admin** — org khác cũng trả 404, không 403 |
| `WORKSPACE_NOT_IN_ORG` | 422 | `workspaceId` không thuộc org của admin |
| `USER_NOT_PENDING` | 409 | xoá/mời lại một user đã nhận mời |
| `USER_PENDING` | 409 | đổi `lifecycle` của user chưa đặt mật khẩu (§2.2 song điều kiện chặn) |
| `SELF_LOCKOUT` | 409 | ba luật §3.2 |
| `INVITE_INVALID` | 404 | token sai · đã dùng · hết hạn — **một mã cho ba** |

**`USER_NOT_FOUND` cho user ở org khác, không `FORBIDDEN`.** 403 xác nhận id này tồn tại, chỉ là không phải của bạn — đủ để dò danh sách user của mọi khách hàng. Cùng lý lẽ `doi_workspace` đã dùng cho `khong_du_quyen()`.

**`INVITE_INVALID` gộp ba tình huống.** Phân biệt hết hạn với không tồn tại cho một máy dò biết token nào đã từng có thật.

### 4.3 `POST /users` — thứ tự trong MỘT giao dịch

```
1. kiểm org_role = 'owner'                 → 403 nếu không
2. chuẩn hoá email (lower + trim)
3. kiểm email chưa tồn tại                 → 409 EMAIL_TAKEN
4. kiểm mọi workspaceId thuộc org          → 422 WORKSPACE_NOT_IN_ORG
5. sinh user_id từ local-part của email, chống trùng bằng hậu tố số
6. INSERT users (lifecycle='pending', password_hash=NULL)
7. INSERT memberships (org_id = org của admin)
8. INSERT invites (token_hash, expires_at = now() + 7 ngày)
9. nhat_ky.ghi(org_id=..., 'user.tao', actor=admin, chi_tiet={...})
10. trả UserDetailOut + invitePath
```

Bước 4 **trước** bước 6 là cố ý. Composite FK sẽ chặn dòng membership lệch org ở bước 7, nhưng nó chặn bằng một `ForeignKeyViolationError` → 500. Kiểm trước biến cùng một sự thật thành một 422 có tên field.

Cả 10 bước trong một `conn.transaction()`: một user `pending` không có thư mời là một hàng không đường nào tới được, và không UI nào xoá được (DELETE chỉ nhận `pending` — nó xoá được, nhưng chỉ khi admin đoán ra phải làm vậy).

### 4.4 `PATCH /users/{user_id}` — memberships là THAY THẾ TOÀN BỘ

Danh sách gửi lên là trạng thái mong muốn cuối cùng: service `DELETE` mọi membership của user trong org rồi `INSERT` lại danh sách mới, trong cùng giao dịch.

Vì sao thay thế chứ không patch từng dòng: form là một bảng người dùng sửa trực tiếp — thêm dòng, xoá dòng, đổi role. Diễn dịch nó thành chuỗi add/remove/update ở FE là đặt logic hoà giải vào chỗ không có giao dịch, và hai tab mở cùng lúc sẽ trộn ra một tập quyền không ai chọn.

Không sửa được qua PATCH: `email` (là khoá đăng nhập — đổi nó thuộc luồng khác), `id`, `org_id`.

### 4.5 `POST /invites/accept`

```
1. sha256(token) → tra invites: used_at IS NULL AND expires_at > now()   → 404 INVITE_INVALID
2. UPDATE users SET password_hash = argon2(mật khẩu), lifecycle = 'active'
3. UPDATE invites SET used_at = now()
4. nhat_ky.ghi(org_id, 'user.nhan_moi', actor=user_id)
```

Bước 2 và 3 trong cùng giao dịch. Đổi mật khẩu xong mà không đánh dấu đã dùng là để token sống tiếp — người khác đọc được link vẫn đặt lại được mật khẩu của người đó.

**Không tự đăng nhập sau khi đặt mật khẩu.** FE đẩy về `/login`. Tạo phiên ngay là tiện hơn một lần bấm, nhưng nó nghĩa là ai mở được link mời thì có phiên — và đường này công khai.

Mật khẩu tối thiểu **10 ký tự**. Không có rate limit ở đây (M8); ghi ra để không ai tưởng đã có.

---

## 5. Frontend

| Tệp | Việc |
|---|---|
| `routes/_app/users.tsx` | đổi `component` sang `UserAdmin` |
| `features/auth/components/UserAdmin.tsx` | danh sách user của tổ chức + nút Thêm người dùng; nhúng `MemberList` bên dưới |
| `features/auth/components/UserForm.tsx` | form tạo/sửa (một component cho cả hai), gồm bảng membership nhiều dòng + màn hiện link mời |
| `features/auth/components/NhanLoiMoi.tsx` | màn đặt mật khẩu từ link mời |
| `routes/invite.$token.tsx` | **ngoài `_app`** — chưa có phiên nên không vào được `<SessionProvider>` |
| `features/auth/api.ts` | 8 hàm gọi + kiểu, dùng lại `goi<T>()` đã có; `urlMoiTuyetDoi()` là chỗ DUY NHẤT ghép `location.origin` |
| `features/auth/nhan.ts` | **mới** — nhãn VI + đổi ngày `<input date>` ↔ ISO. `MemberList` giữ bản `NHAN_VAI_TRO` riêng của nó, và M2b thêm ba màn nữa cùng cần: bốn bản sao là bốn chỗ lệch khi PQ_01 §2.4 đổi từ ngữ |
| `features/auth/components/MemberList.tsx` | dùng nhãn chung; thêm tiêu đề Thành viên workspace hiện tại để nó tự chủ khi bị nhúng |
| `lib/msw/handlers.ts` | handler cho 8 đường mới — không có thì `VITE_MSW=1` vỡ. **Có trạng thái** (`USERS_GIA`), xem §5.3 |

### 5.3 MSW giả phải CÓ TRẠNG THÁI

Handler trả hằng số làm mọi thao tác trông như thành công mà bảng không đổi — và cả màn này *là* một vòng tạo → hiện trong bảng → sửa → mất khỏi bảng. Nên `USERS_GIA` là mảng module-level mà các handler ghi vào.

Kiểu khai **tại chỗ** trong `handlers.ts`, không import từ `features/auth/api`: MSW là hạ tầng của `lib/`, và `lib/` biết hình dạng endpoint của một module là chiều phụ thuộc mà `tests/module-boundaries.test.ts` cấm.

### 5.1 Hai quy tắc UI bắt buộc

**`orgRole = 'owner'` → bảng workspace bị vô hiệu hoá**, kèm một câu giải thích *Chủ tổ chức thấy mọi workspace — không cần cấp riêng*. Đây là nửa còn lại của luật §4.1: contract trả 422, nhưng để người dùng nhập xong rồi mới báo lỗi thì UI đang đặt bẫy.

**Nút Thêm người chỉ hiện khi `session.orgRole === 'owner'`.** Ẩn nút là cho đỡ rối mắt (PQ_01 §BR-Q03), **không** phải bảo vệ — endpoint vẫn kiểm.

### 5.2 `invitePath` → URL tuyệt đối

FE ghép `location.origin + invitePath` và hiện trong một ô có nút Copy. Đây là điểm cuối của quyết định §1⑤: một chỗ duy nhất biết origin, và nó là chỗ duy nhất chắc chắn biết đúng.

---

## 6. Hai bug đã có, sửa trong cùng PR

**① `modules/auth/fake.py` vỡ lúc import.** `PHIEN_GIA` thiếu `organization` và `orgRole` — hai trường 0102 thêm vào `SessionOut` mà `fake.py` không cập nhật. `from portal.modules.auth.fake import PHIEN_GIA` raise `ValidationError` ngay. Không test nào đang import nó, nên nó đã hỏng im lặng. Thêm hai trường + một test import nó, để lần sau `SessionOut` đổi thì CI đỏ chứ không phải một module khác phát hiện.

**② `dang_nhap()` sẽ nổ `TypeError` khi gặp user `pending`.** `pw.kiem(u.password_hash, ...)` nhận `None` sau migration 0103. Thêm nhánh: `password_hash IS NULL` → `pw.kiem_gia()` rồi `sai_dang_nhap()`. Dùng `kiem_gia()` chứ không return sớm — nếu không, đồng hồ tố ra email nào đang ở trạng thái chờ mời, đúng loại rò rỉ mà `kiem_gia()` sinh ra để bịt.

---

## 7. Cổng test

Tất cả trong `odyssey-portal-backend/tests/modules/auth/`, trừ nơi ghi khác.

| # | Cổng | Ở đâu |
|---|---|---|
| 1 | Owner tạo user → `pending`, `password_hash IS NULL`, đúng 1 invite; nhật ký có `org_id`, `tenant_id` NULL, **không** chứa token | `test_tao_user.py` |
| 2 | `member` gọi `POST /users` → 403 (dù `actions` là cả 13) | cùng trên |
| 3 | Email trùng → 409 `EMAIL_TAKEN`, **không** để lại hàng nào | cùng trên |
| 4 | `workspaceId` của org khác → 422, **không** để lại hàng nào | cùng trên |
| 5 | `orgRole='owner'` + memberships không rỗng → 422 | `test_contracts_user.py` |
| 6 | `orgRole='member'` + memberships rỗng → 422 | cùng trên |
| 7 | Nhận mời → `active` + có hash; token dùng lần hai → 404 | `test_nhan_loi_moi.py` |
| 8 | Mời lại → token cũ chết, token mới sống, vẫn đúng 1 hàng invite | cùng trên |
| 9 | User `pending` đăng nhập → 401, **không** `TypeError` | `test_pending.py` |
| 10 | PATCH thay thế toàn bộ membership, không cộng dồn | `test_sua_user.py` |
| 11 | Hai luật §3.2 → 409 `SELF_LOCKOUT`, và **không chặn quá tay** (owner vẫn sửa được hồ sơ của mình) | cùng trên |
| 12 | `fake.py` import được và khai **đủ** mọi trường của `SessionOut` | `test_fake.py` |
| 13 | CHECK song điều kiện chặn `active`+hash NULL **và** `pending`+có hash, ở cả INSERT lẫn UPDATE (SQL trực tiếp) | `test_pending.py` |
| — | `control.invites` khai trong allowlist bảng `control` | `tests/integration/test_control_schema.py` |
| — | FE: `orgRole` (không phải `actions`) quyết định hiện nút; owner → bảng workspace bị khoá; link mời hiện sau khi tạo; token chết → không hiện form | `odyssey-portal-frontend/tests/user-admin.test.tsx` |

Cổng 3 và 4 kiểm **không để lại hàng nào** — đó là phép kiểm giao dịch §4.3, và nó là thứ duy nhất phân biệt "có `conn.transaction()`" với "trông như có".

Cổng 13 gọi SQL trực tiếp, không qua API: nó kiểm một RÀNG BUỘC DB. Phép kiểm ở service cũng chặn được, nhưng chỉ CHECK là thứ `psql` tay, seed script và mọi migration sau không đi vòng được.

---

## 8. Định nghĩa "xong" — đã xác minh 2026-08-03

1. ✅ `alembic upgrade head` sạch; head = `0103_user_ho_so_invite`. Schema đã đối chiếu trên DB dev: `invites` đủ 7 cột + composite FK + CHECK sha256, `users.password_hash` nullable, `audit_log.tenant_id` nullable + `org_id` + CHECK phạm vi. Grant `portal_api` trên `invites` đến từ `ALTER DEFAULT PRIVILEGES` của 0003 — không cần GRANT tay.
2. ✅ **BE 660/660** test xanh (13 cổng mới + toàn bộ test cũ, gồm `test_role_privileges.py`), `make lint` sạch.
3. ✅ **FE 173/173** test xanh, `tsc --noEmit` sạch, eslint sạch, prettier sạch, `vite build` chạy.
4. ✅ `make contracts` không sinh diff — spec này không thêm action nào (xem §3.3).
5. ✅ Đầu-cuối qua HTTP thật trên API dev (cổng 8100), dữ liệu `dev_seed`:
   owner đăng nhập → tạo `u_demo_mai` (`member`, chỉ cấp `anphu`) → xác nhận `pending` + `password_hash NULL` →
   `pending` đăng nhập trả **401 chứ không 500** (bug §6② đã sửa) → mở link mời **không cookie** → đặt mật khẩu →
   token lần hai **404** → user mới đăng nhập, `initials` suy đúng, thấy **đúng `[anphu]`** và không thấy `sunrise` →
   member gọi `GET /users` **403** → đổi sang workspace chưa cấp **403**.
   Kèm: owner tạo mới với `memberships: []` thấy **mọi** workspace của org; PATCH thay thế toàn bộ; hai luật `SELF_LOCKOUT`; `WORKSPACE_NOT_IN_ORG` cuộn giao dịch lại. Dữ liệu demo đã dọn, DB về đúng trạng thái seed.

### 8.1 Còn treo — ghi để không ai tưởng đã có

- **Không gửi email.** Chủ dự án chốt. Không có seam gửi thư, nên lúc muốn gửi thật sẽ phải sửa `quan_tri_user.py`, không phải cắm thêm adapter.
- **Không rate limit** trên `POST /invites/accept` và `POST /auth/login` (M8). Ở đường nhận mời, phòng thủ duy nhất đang có là 256 bit ngẫu nhiên + hạn 7 ngày + dùng một lần.
- **Đổi / quên mật khẩu** vẫn chưa có (M8). Admin bấm Mời lại chỉ được cho user còn `pending` — cố ý.
- **`require()` vẫn cấp cả 13 action** cho mọi thành viên. Nên `GET /members` vẫn mở cho `viewer` (M2a §4.1 đã ghi). Spec này không làm tệ hơn và cũng không sửa.
