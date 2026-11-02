# Đăng nhập bằng Google (OAuth 2.0 / OIDC) — thiết kế

Ngày: 2026-08-18 · Trạng thái: đã chốt, chờ implementation plan

## 1. Bối cảnh và phạm vi

Portal hiện chỉ có MỘT đường vào: email + mật khẩu Argon2, phiên là cookie đối
xứng lưu Redis (`core/auth/session.py`). Spec này thêm đường vào THỨ HAI qua
Google, KHÔNG thay đường cũ và KHÔNG đổi mô hình phiên.

**Trong phạm vi:** đăng nhập bằng Google · đăng ký mới bằng Google · liên kết
tài khoản sẵn có với Google.

**Ngoài phạm vi (v1):** đặt mật khẩu cho tài khoản Google-only · gỡ liên kết
Google · nhà cung cấp khác (Microsoft/Apple) · giới hạn domain công ty · One-Tap.

## 2. Câu hỏi «chỉ cần thêm cột gmail vào users?» — không

Ba lý do, ghi lại để không ai đề xuất lại:

**① Nó vỡ CHECK đang có.** Migration 0103 đặt
`CHECK ((lifecycle = 'pending') = (password_hash IS NULL))`. Người đăng nhập
bằng Google là `active` nhưng KHÔNG có mật khẩu — INSERT nổ ngay. Bất biến này
phải nới, và nới nó là một quyết định có hệ quả, không phải một dòng phụ.

**② `email` không phải khoá của Google.** Khoá bất biến là `sub`. Google cho đổi
email của tài khoản; khớp theo email thì đổi email = mất tài khoản, hoặc tệ hơn:
ai chiếm được email cũ thì vào được. Và cột `gmail` trùng lặp với `users.email`
vốn đã UNIQUE — hai cột cho một sự thật là một bug đang chờ lệch (cùng lý lẽ 0100
đã ghi khi từ chối cột `initials`).

**③ Một cột là khoá cứng vào một nhà cung cấp.** Nhà cung cấp thứ hai lại một cột.

## 3. Quyết định đã chốt

| # | Câu hỏi | Chốt |
|---|---------|------|
| Q1 | Google trả email đã có tài khoản mật khẩu | **Tự liên kết**, chỉ khi `email_verified = true` |
| Q2 | Google trả email chưa có tài khoản | **Tạo user mới** `active`, `password_hash = NULL`, 0 workspace |
| Q3 | Tài khoản Google-only có đặt được mật khẩu | **Không, v1 bỏ qua**. Rủi ro đã biết: mất tài khoản Google = mất đường vào |

## 4. Database

### 4.1 Bảng mới `control.identities`

```sql
CREATE TABLE control.identities (
    provider    text NOT NULL
                CONSTRAINT identities_provider_check CHECK (provider IN ('google')),
    subject     text NOT NULL,
    user_id     text NOT NULL REFERENCES control.users(id) ON DELETE CASCADE,
    email_tai_provider text NOT NULL
                CONSTRAINT identities_email_lower_check
                CHECK (email_tai_provider = lower(email_tai_provider)),
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz,
    PRIMARY KEY (provider, subject)
);
CREATE INDEX identities_user_id_idx ON control.identities(user_id);
CREATE UNIQUE INDEX identities_mot_provider_moi_user
    ON control.identities(user_id, provider);
```

- `PRIMARY KEY (provider, subject)` là thứ chặn hai user cùng chiếm một tài khoản
  Google. Không phải một UNIQUE thêm vào sau — nó LÀ danh tính của hàng này.
- `email_tai_provider` chỉ để hiển thị và audit. KHÔNG đường nào được khớp user
  bằng cột này; khớp bằng `(provider, subject)`. Cột này tồn tại để trả lời
  "tài khoản Google nào đang gắn vào đây" mà không phải gọi Google.
- `CHECK lower(...)` cùng lý lẽ `users_email_lower_check` của 0100.
- `UNIQUE (user_id, provider)` chặn một user gắn hai tài khoản Google khác nhau.
- `ON DELETE CASCADE`: xoá user thì identity không còn nghĩa gì.

`control.users` KHÔNG thêm cột nào. `email` vẫn UNIQUE và vẫn là danh tính chính.

### 4.2 Nới bất biến mật khẩu

```sql
ALTER TABLE control.users DROP CONSTRAINT users_password_theo_lifecycle_check;
ALTER TABLE control.users ADD CONSTRAINT users_co_duong_dang_nhap_check
    CHECK (lifecycle <> 'pending' OR password_hash IS NULL);
```

Cái CŨ là song điều kiện và giữ HAI lời hứa cùng lúc (0103 ghi rõ):
1. `pending` mà đã có hash → thư mời còn sống sau khi mật khẩu đã đặt.
2. `active` mà chưa có hash → tài khoản đăng nhập được không cần mật khẩu.

Ràng buộc mới giữ lời hứa ①. Lời hứa ② KHÔNG đặt được bằng CHECK vì nó phải nhìn
sang `control.identities` — CHECK trong Postgres không làm được điều đó, và một
TRIGGER cho việc này là chi phí vận hành không tương xứng.

⚠️ Đây là một sự NỚI THẬT, không phải viết lại cho gọn: sau migration này, DB
cho phép một hàng `active` không mật khẩu và không identity — tức một tài khoản
không đường nào vào. Nó vô hại (không ai đăng nhập được) nhưng nó là rác. Neo
lời hứa ② bằng test contract, xem §8.

### 4.3 Revision

`0108_dang_nhap_google`, `down_revision = "0935_hop_nhat_hai_head"` (head lúc
viết spec — kiểm lại lúc thi công, có thể đã đổi).

`downgrade()`: DROP bảng `identities` TRƯỚC, rồi mới đặt lại CHECK cũ. Và phải
XOÁ mọi user KHÔNG `pending` có `password_hash IS NULL` trước khi đặt lại — nếu
không ALTER nổ và downgrade dừng giữa đường (cùng lỗi mà 0103 đã xử ở nhánh
`pending`).

⚠ `lifecycle <> 'pending'`, KHÔNG PHẢI `lifecycle = 'active'`: ràng buộc mới cho
phép cả `suspended` + `password_hash IS NULL`, và đó là trạng thái ĐÚNG — một user
Google-only bị admin đình chỉ chính là như vậy. Lọc theo `active` bỏ sót họ, và
CHECK cũ dựng lại sẽ nổ đúng ở môi trường đã dùng tính năng này lâu nhất.

## 5. Lối kỹ thuật: Authorization Code + PKCE

**Chọn A, không chọn B.**

- **A — Authorization Code + PKCE, redirect toàn trang.** `client_secret` không
  bao giờ rời server; không credential nào nằm chỗ JS đọc được. Khớp đúng lý lẽ
  `session.py` đã ghi khi từ chối JWT.
- **B — Google Identity Services, FE nhận `id_token` rồi POST lên BE.** Ít bước
  hơn nhưng đưa một credential vào JS, vẫn phải verify y hệt ở BE. Không đổi được gì.

FE và BE CÙNG GỐC nhờ proxy `'^/api/'` của vite → `SameSite=Lax` giữ nguyên,
không phải đụng `_dat_cookie` và không cần token CSRF. **Tách domain thì phải
đổi sang `SameSite=None` + Secure + CSRF token** — cùng cảnh báo mà `_dat_cookie`
đã ghi.

## 6. Endpoint và luồng

Ba đường, đều công khai, đều khai `require(None, ly_do=...)` tường minh theo lối
router hiện tại.

### 6.1 `GET /auth/google/start`

1. Sinh `state` (32 byte `secrets.token_urlsafe`) và `code_verifier` (PKCE S256).
2. `SETEX oauth:state:<state>` = `code_verifier`, **TTL 300 giây**. Redis đã có
   sẵn cho phiên; một bảng Postgres cho dữ liệu sống 5 phút là sai công cụ.
2b. **Đặt cookie `odyssey_oauth_state = <state>`** — HttpOnly, `Secure` theo
   `_secure()`, `SameSite=Lax`, `max_age=300`, `path=/`.

   ⚠ THIẾU BƯỚC NÀY LÀ MỘT LỖ HỔNG LOGIN-CSRF, không phải một thiếu sót nhỏ.
   Hàng Redis một mình là một token TOÀN CỤC: bất kỳ trình duyệt nào cầm được
   `state` đều đổi được nó. Kẻ tấn công tự gọi `/start`, tự đăng nhập Google
   bằng tài khoản CỦA HỌ, rồi đưa nạn nhân cái URL callback kèm `code`+`state`
   của mình — nạn nhân nhận cookie phiên của TÀI KHOẢN KẺ TẤN CÔNG và mọi thứ
   họ nhập sau đó rơi vào đó. PKCE không cứu được: `code_verifier` nằm ở server
   và cũng không buộc vào trình duyệt nào.

   `SameSite=Lax` là đúng và cần: callback là một điều hướng GET top-level từ
   Google, nên cookie Lax VẪN được gửi. `Strict` sẽ chặn mất chính nó.
3. `307` sang `https://accounts.google.com/o/oauth2/v2/auth` với
   `scope=openid email profile`, `code_challenge`, `code_challenge_method=S256`,
   `redirect_uri`, `prompt=select_account`.

### 6.2 `GET /auth/google/callback?code=&state=`

1. **Đối chiếu cookie trước tiên.** Đọc `odyssey_oauth_state`; thiếu, hoặc khác
   `state` trên query → `302 /login?loi=STATE_HET_HAN`. Đây là phép chống
   login-CSRF; xem §6.1 bước 2b. Xoá cookie này trên MỌI đường ra, thành công
   lẫn thất bại — một `state` đã dùng còn nằm trong trình duyệt là rác biết nói.
2. **`GETDEL oauth:state:<state>`** — dùng MỘT LẦN. Atomic, không `GET` rồi `DEL`:
   hai lệnh rời nhau là một cửa sổ replay. Không có key → `302 /login?loi=STATE_HET_HAN`.

   ⚠ `GETDEL` chống REPLAY, KHÔNG chống login-CSRF. Hai chuyện khác nhau và cần
   hai phép khác nhau — bước 1 lo chuyện còn lại.
2. `POST https://oauth2.googleapis.com/token` bằng `httpx` (đã là dep chính), kèm
   `client_secret` + `code_verifier` → nhận `id_token`.
3. Đọc claims, kiểm `iss` ∈ {`accounts.google.com`, `https://accounts.google.com`},
   `aud == google_client_id`, `exp` chưa qua, `email_verified == true`.

   **KHÔNG verify chữ ký RS256, và đây là chủ ý — phải ghi thành comment trong
   code.** `id_token` vừa đến TRỰC TIẾP từ Google qua TLS ở bước 2, không đi qua
   trình duyệt; OIDC Core §3.1.3.7 miễn verify đúng trường hợp này. Tự viết verify
   JWT là mở lại hố `alg confusion` mà `session.py` đã cố ý tránh khi từ chối JWT.
   Thiếu comment thì người đọc sau tưởng là quên và sẽ "sửa" bằng một verify tự viết.

4. Mở transaction, chạy §7.
5. `ss.tao(r, user_id=..., tenant_id=...)` — DÙNG LẠI nguyên hàm cũ. `_dat_cookie`
   cũng dùng lại, không viết bản thứ hai (`_secure()` lệch nhau một cờ là đăng nhập
   chạy còn đăng xuất hỏng — router đã ghi).
6. `302` về `/dashboard`, hoặc `/tao-workspace` nếu `tenant_id is None`.

### 6.3 `GET /auth/providers`

Trả `{"google": true|false}` — công khai, không đòi phiên (màn đăng nhập chưa có
phiên nào để đòi). Tồn tại vì FE KHÔNG có đường nào khác biết tính năng bật hay
tắt: `/config/*` là agent config và đòi phiên, `/me` cũng vậy.

KHÔNG dùng biến build-time của Vite thay cho endpoint này: cờ thật nằm ở
`.env` của backend, và một bản FE build sẵn đem sang môi trường khác sẽ nói sai.
Một sự thật, một nguồn.

Đường này CHỈ trả tên nhà cung cấp. Không `client_id`, không URL, không gì khác —
mỗi trường thêm vào là một thứ nói cho người chưa đăng nhập biết về hệ thống.

### 6.4 Lỗi trả về đâu

Callback là điều hướng trình duyệt, KHÔNG trả JSON — `LoiPortal` không dùng được
ở đây. Mọi lỗi thành `302 /login?loi=<MA>`:

`STATE_HET_HAN` · `GOOGLE_TU_CHOI` · `EMAIL_CHUA_XAC_THUC` · `TAI_KHOAN_DINH_CHI`
· `DANG_KY_DANG_TAT`.

## 7. Ba nhánh khớp danh tính

Thứ tự BẮT BUỘC: khớp `(provider='google', sub)` TRƯỚC, email chỉ dùng ở nhánh sau.

| # | `identities` | `users.email` | Làm gì |
|---|---|---|---|
| 1 | **có** | — | `UPDATE last_login_at`, tạo phiên. Không tạo gì. ~99% lượt. |
| 2 | không | **có**, `active` | INSERT 1 hàng `identities` trỏ user sẵn có. KHÔNG tạo user. |
| 3 | không | không | INSERT 1 `users` + 1 `identities`, cùng transaction. |

**Vì sao tra `sub` trước:** người dùng đổi email tài khoản Google thì `sub` không
đổi → nhánh 1 vẫn khớp, họ vào được tài khoản cũ. Tra email trước thì cùng người
đó rơi xuống nhánh 3 và bị tạo user thứ hai — mất sạch workspace.

### Nhánh biên

**a) `users` tồn tại nhưng `lifecycle = 'pending'`** (đã được mời, chưa đặt mật
khẩu): link identity, chuyển `pending → active`, **và XOÁ hàng `control.invites`
của user đó**. Token mời đang sống phải chết — đã vào được rồi thì một link đặt
mật khẩu còn hiệu lực là một cửa thừa không ai theo dõi.

**b) `lifecycle = 'suspended'`**: TỪ CHỐI. Không link, không tạo, không phiên.

Đây là nhánh QUAN TRỌNG NHẤT của cả spec. Cửa mật khẩu đã chặn nó
(`service.dang_nhap`: `if u.lifecycle != "active": raise loi.sai_dang_nhap()`).
Cửa Google mà không chặn thì: admin đình chỉ người vừa nghỉ việc → mật khẩu hết
tác dụng → **họ bấm nút Google vẫn vào được**. Lệnh đình chỉ thành vô nghĩa.

Không phải giả thuyết: repo đã vấp đúng loại lỗi này ở `thanh_vien.py` — trước
một bản sửa, user `suspended` rơi chung nhánh "đã có tài khoản" và ĐƯỢC cấp
membership.

**Thông báo: nói THẲNG** ("Tài khoản của bạn đã bị đình chỉ, liên hệ quản trị
viên"), KHÔNG gộp vào `sai_dang_nhap()`. Lý lẽ chống dò email của `loi.py` không
áp được ở đây: muốn thử email X qua cửa Google thì phải đăng nhập được vào tài
khoản Google của X — đã là chủ hộp thư rồi, không còn gì để rò. Và
"Email hoặc mật khẩu không đúng" là câu vô nghĩa với người không gõ mật khẩu nào.

⚠️ Câu này CHỈ xuất hiện sau khi Google xác thực thành công. Không đường nào chưa
đăng nhập Google được chạm tới nó.

**c) `email_verified = false`**: từ chối ở CẢ nhánh 2 và 3. Email chưa xác thực
không chứng minh được gì, và toàn bộ quyết định "tự liên kết" (Q1) đứng trên
đúng claim này.

## 8. Ranh giới file

- **`core/auth/oauth_google.py`** — CHỈ nói chuyện với Google: build URL, đổi
  code, đọc claims. Không biết `users`, không biết Redis phiên. Test bằng
  `httpx.MockTransport`, không cần DB.
- **`modules/auth/dang_nhap_google.py`** — 3 nhánh + a/b/c, gọi repo. Không biết
  HTTP. Test bằng claims dựng tay, không cần dựng OAuth giả.
- **`modules/auth/repo.py`** — thêm `tim_identity`, `ghi_identity`,
  `cham_last_login`. Giao dịch do người gọi mở, đúng lối repo đã ghi.
- **`modules/auth/router.py`** — 2 endpoint mỏng, ghép hai cái trên + cookie.

Chia vậy để hai loại test không phải kéo nhau.

## 9. Frontend

**Nút là thẻ `<a href="/api/v1/auth/google/start">`, KHÔNG phải `onClick` +
`fetch`.** OAuth cần trình duyệt rời khỏi trang; `fetch` sẽ đâm CORS của Google
và không bao giờ chạy. `<a>` thật còn cho middle-click hoạt động miễn phí.

Ba chỗ sửa:

1. **`features/auth/components/LoginForm.tsx`** — thêm nút + dải "hoặc". **Và
   SỬA DOCSTRING**: nó đang ghi "KHÔNG có nút Google/Apple/SSO... Vẽ chúng ra là
   hứa tính năng không tồn tại". Lời hứa đó sắp thành thật; để nguyên là để lại
   một lời dối cho người đọc sau.
2. **`features/auth/components/DangKyForm.tsx`** — cùng nút, cùng URL. Không cần
   đường riêng cho đăng ký: nhánh 3 ở BE tự lo.
3. **`routes/login.tsx`** — đọc `?loi=` từ search params, đẩy vào `LoginForm`.
   Hiện TẠI CHỖ, không đẩy sang màn lỗi toàn trang — đúng lối docstring đã đặt.

Sau callback BE `302` thẳng `/dashboard`, nên FE KHÔNG gọi `/me` thủ công:
`SessionProvider` của `_app` chạy như mọi lần tải trang khác.

**Ẩn nút khi tính năng tắt**: FE gọi `GET /auth/providers` (§6.3) khi vào màn
đăng nhập; `google: false` ⇒ không vẽ nút. Đang tải thì KHÔNG vẽ chỗ trống rồi
nhét nút vào sau — một nút nhảy ra dưới ngón tay người đang bấm «Đăng nhập» là
một cú bấm nhầm. Vẽ nút chỉ khi đã biết câu trả lời.

## 10. Config

Trong `core/config.py`, cạnh `signup_enabled`:

```
google_client_id: str = ""      # RỖNG ⇒ tắt hẳn tính năng
google_client_secret: str = ""
```

`redirect_uri` **suy từ `public_base_url`** đã có, KHÔNG thêm biến thứ ba — cùng
lý lẽ file đó đã ghi cho mailer.

Rỗng ⇒ `/auth/google/start` trả **403** `FEATURE_DISABLED`
(`loi.tinh_nang_dang_tat` — 403 chứ không 404 vì cửa CÓ tồn tại và sẽ bật lại;
xem lý lẽ trong `api/loi.py`) và `/auth/providers` trả `google: false`. HAI cửa cùng đọc MỘT cờ: endpoint kia chỉ
để FE khỏi vẽ một nút chết, nó KHÔNG phải phép chặn. Phép chặn nằm ở `start`.

Thêm phép kiểm vào `kiem_tra_dang_ky_mau_thuan_san_xuat()`: production mà có
`google_client_id` nhưng thiếu `public_base_url` là một cấu hình sinh ra
`redirect_uri` sai — Google từ chối lúc CHẠY, ở production, và thông báo của
Google không nói ra nguyên nhân.

Việc ngoài code: tạo OAuth Client (loại Web) ở Google Cloud Console, khai
Authorized redirect URI khớp CHÍNH XÁC `<public_base_url>/api/v1/auth/google/callback`,
và cấu hình consent screen.

## 11. Test

**① Contract DB**
- Nhánh 3 INSERT được: `active` + `password_hash = NULL` (neo migration mới).
- Hai user cùng `(provider, subject)` phải vỡ PK.
- Một user gắn hai `sub` Google khác nhau phải vỡ `UNIQUE (user_id, provider)`.
- **Neo lời hứa ②** (§4.2): `active` phải có `password_hash` HOẶC ≥1 identity —
  không CHECK được nên test này LÀ chỗ duy nhất giữ nó.

**② Ba nhánh + a/b/c** — gọi thẳng `dang_nhap_google.py` với claims dựng tay.
- a: `pending` → thành `active` VÀ hàng `invites` biến mất.
- c: `email_verified = false` → từ chối ở cả nhánh 2 và 3.

**③ OAuth** — `httpx.MockTransport`: `state` sai · `state` dùng lại lần hai (phải
hỏng, nhờ `GETDEL`) · `aud` sai · `exp` quá hạn.

**④ Cửa hậu — test quan trọng nhất của cả tính năng:** user `suspended` KHÔNG
vào được bằng Google.

## 12. Rủi ro đã biết, chấp nhận cho v1

- **Mất tài khoản Google = mất đường vào portal** (Q3). Cách gỡ hôm nay: admin
  đổi email hoặc phát lại thư mời thủ công.
- **DB cho phép hàng rác** `active` + không mật khẩu + không identity (§4.2). Vô
  hại, chỉ neo được bằng test.
- **`prompt=select_account`** làm người dùng phải chọn tài khoản mỗi lượt. Cố ý:
  máy dùng chung mà tự đăng nhập bằng tài khoản Google đang mở là một bất ngờ tệ.
