# M2a-BE — Xác thực · Phiên · Vỏ API

| | |
|---|---|
| Phiên bản | v1.0 |
| Ngày | 2026-07-30 |
| Trạng thái | Chờ review |
| Module | **M2a-BE** (nửa sau của M2a; M2a-FE đã xong 2026-07-30) |
| Nguồn nghiệp vụ | `pq01-phan-quyen.md` §II.2.3 · §II.2.4 · spec tổng §3.5 · §4① · §4③ |
| Phụ thuộc | M1 (đã xong — migration `0001`–`0007`) · M2a-FE (đã xong) |
| Mở đường cho | M3 · M4 · M5 · M6 · M7 · M8 · M9 — mọi module có endpoint |

---

## 0. Phạm vi

### 0.1 Trong phạm vi

1. **Vỏ API** — FastAPI app, router registry, `require(action)`, cổng CI canh mọi route khai action.
2. **Xác thực** — `users`, `memberships`, đăng nhập bằng mật khẩu (Argon2id), phiên ở Redis.
3. **Phạm vi workspace** — `/api/v1/me`, đổi workspace, dependency trả kết nối đã đặt phạm vi tenant.
4. **Màn đăng nhập FE** + tắt MSW — để chứng minh vòng chạy thật trên trình duyệt.
5. **Danh sách thành viên** (`GET /members` + màn `users` chỉ-đọc) — spec tổng giao danh sách cho M2a.
6. **Bootstrap dev** — seed user/workspace + cấp quyền đăng nhập cho `portal_api` (xem §7).
7. **Đổi tên thư mục module** BE + FE và sửa spec tổng §4① cho khớp (xem §8).

### 0.2 Ngoài phạm vi — và thuộc về đâu

| Thứ | Thuộc |
|---|---|
| Ma trận 4 vai trò × 13 nhóm hành động | **M2b** |
| Mời người · `invitations` · đổi vai trò · chặn gỡ admin cuối (BR-Q05) | **M2b** |
| Luồng xin/duyệt **quyền hỗ trợ NobleX** (§II.2.5) | **M2b** — nhưng cột `expires_at` có sẵn ở đây, xem §3.2 |
| Nhật ký đọc bản ghi thoại (BR-Q07) | **M2b** |
| `audit_log` · rate limit theo API key | **M8** |
| Đổi mật khẩu · quên mật khẩu · xác minh email | **Chưa module nào sở hữu.** Xem §10.2 |
| Back-office mặt phẳng Nền tảng (NobleX xem mọi workspace) | **Chưa module nào sở hữu.** Xem §10.1 |

---

## 1. Bảy quyết định đã chốt

| # | Quyết định | Vì sao |
|---|---|---|
| 1 | **Mật khẩu + Argon2id**, không magic link, không OIDC | Repo chưa có hạ tầng email/SMTP nào. Test integration chạy trọn trong container, không cần giả mail server. Đổi sang OIDC sau là thêm một endpoint, không phải sửa `require()` |
| 2 | **Phiên server nhạc ở Redis**, workspace hiện tại nằm trong bản ghi phiên | FE gọi `/api/v1/me` không mang workspace và `switchWorkspace` đang là state client. Giữ ở server nghĩa là **không module nào phải gắn header**, và quên gắn không thành lỗ hổng im lặng |
| 3 | **Cookie đối xứng (opaque), KHÔNG JWT** — lệch spec tổng, xem §2.4 | Đã tra Redis mỗi request thì JWT chỉ còn là chi phí cộng ba loại lỗi (alg confusion · hạn dài không thu hồi được · token lọt vào JS/log) |
| 4 | **`require()` + phiên + `Principal` ở `core/auth/`**, không ở `modules/auth/` | `test_module_boundaries.py` chỉ cho import `modules.<khác>.contracts`. Và `core/db/session.py` đã nói *"tenant_id PHẢI đến từ membership đã xác thực"* — membership là chân của cách ly, cùng hạng với `current_tenant()` |
| 5 | **`core/auth/actions.py` là nguồn của 13 hành động**; vitest đọc file Python | Nguồn phải nằm ở tầng cưỡng chế thật, không ở tầng trang trí. FE ẩn nav là tiện mắt (BR-Q03); BE chặn request là bảo vệ |
| 6 | **Thư mục module bỏ tiền tố số**: `modules/auth/`, không `modules/m2_auth/` | Tiền tố là siêu dữ liệu lịch thi công, không phải nghĩa. Ba cơ chế tưởng móc vào nó đều không móc — xem §8.1 |
| 7 | **`expires_at` trên `memberships` có từ ngày đầu** | Vé hỗ trợ có hạn của BR-Q08 sau này là *chèn một hàng*, không phải một migration cộng sửa `require()` |

---

## 2. Kiến trúc

### 2.1 Cây file

```
apps/backend/src/portal/
├─ api/
│  ├─ app.py            create_app() -> FastAPI · gom router · /healthz · handler lỗi
│  └─ registry.py        quét modules/*/router.py tìm biến ROUTER
├─ core/
│  ├─ auth/
│  │  ├─ actions.py      NGUỒN 13 nhóm hành động — vitest đọc file này (cổng 3)
│  │  ├─ principal.py    Principal: user_id · tenant_id · role · actions
│  │  ├─ session.py      phiên Redis: tao() · doc() · xoa() · doi_workspace()
│  │  ├─ require.py      require(action) -> FastAPI dependency
│  │  └─ password.py     Argon2id hash/verify
│  ├─ redis.py           tạo/đóng client Redis theo lifespan của app
│  └─ db/…               (đã có ở M1 — không sửa)
└─ modules/
   └─ auth/
      ├─ contracts.py    SessionOut · WorkspaceOut · MemberOut · UserOut
      ├─ router.py       ROUTER
      ├─ service.py      logic đăng nhập · dựng SessionOut · suy initials
      ├─ repo.py         SQL trên control.users · control.memberships
      ├─ fake.py         bản giả cho module khác dev (spec tổng §4②)
      └─ jobs.py         (chưa có handler nào — file để đúng khuôn registry)
```

`registry.py` đúng khuôn `nav-registry.ts`: thêm module = thêm thư mục có `ROUTER`, **không sửa `app.py`**.

### 2.2 Luồng một request có phạm vi tenant

```
Cookie odyssey_session
  │
  ├─ core/auth/session.py — GET sess:<id> ở Redis
  │     không có / hết hạn -> 401
  │     có -> user_id · current_tenant_id
  │
  ├─ require(action) — MỘT truy vấn, trong cùng giao dịch:
  │     SELECT m.role, u.lifecycle
  │       FROM control.memberships m JOIN control.users u ON u.id = m.user_id
  │      WHERE m.user_id = $1 AND m.tenant_id = $2
  │        AND (m.expires_at IS NULL OR m.expires_at > now())
  │     u.lifecycle <> 'active'  -> DEL sess:<id>, rồi 401   (xem §4.4)
  │     không có hàng            -> 403
  │     M2a: có hàng là đủ.  M2b: tra ma trận role × action ở ĐÚNG chỗ này.
  │
  └─ tenant_conn(pool, tenant_id)   tenant_id lấy từ HÀNG membership
```

**Redis giữ phiên, Postgres giữ quyền.** Redis chỉ trả lời *"ai đang đăng nhập"*, không bao giờ trả lời *"được làm gì"*. Đó là điều làm BR-Q04 thành thật: gỡ một người khỏi workspace có hiệu lực ở **request kế tiếp**, không chờ token hết hạn.

PQ_01 §2.3 đã trả lời trước phản đối "thêm một truy vấn": *"ràng buộc cách ly đã buộc mọi request phải nằm trong một giao dịch — nên việc đọc thêm một hàng đi cùng chuyến"*.

### 2.3 Vì sao `require()` nằm ở `core/`, không ở `modules/auth/`

`test_module_boundaries.py` cưỡng chế bằng AST: `modules.<a>` chỉ được import `portal.core.*` và `modules.<b>.contracts`. Nếu `require()` ở trong ruột `modules/auth/` thì 7 module kia không import được nó.

Hai đường thoát và vì sao chọn đường này:

- **Phơi qua `modules/auth/contracts.py`** — nhưng `contracts.py` được định nghĩa là *"mặt tiền — DTO + Protocol, không logic"*, còn `require()` truy vấn DB. Hoặc bẻ quy ước đó, hoặc thêm một tầng đăng ký implementation vào core lúc startup: công thêm cho một thứ chưa ai cần.
- **`core/auth/` sở hữu seam** ← chọn. Ranh giới: `core` sở hữu *"ai là ai, được làm gì, đọc dữ liệu nào"*; `modules/auth` sở hữu *"user và membership được nhập/sửa/đọc thế nào"*. M2b đổi ruột `require()` tại đúng một file.

### 2.4 Hoà giải với spec tổng — cookie thay JWT

Spec tổng §5 ghi *"phiên **JWT**"* và §6 ghi *"Redis — refresh token · rate limit"*. Spec này lệch, và ghi lại lý do để không ai tranh luận lại (cùng khuôn §3.6 của spec tổng):

> **Chốt: cookie đối xứng opaque, không JWT, không refresh token.**
>
> JWT đáng giá khi nó cho bạn **không phải tra store**. Quyết định #2 đã buộc tra Redis mỗi request — vì workspace hiện tại nằm ở đó và vì thu hồi phiên phải có hiệu lực ngay. Đã tra rồi thì JWT chỉ đổi "so một chuỗi ngẫu nhiên" thành "xác thực chữ ký", cộng thêm ba hố: alg confusion, hạn dài không thu hồi được, và token phải nằm chỗ JS đọc được nếu muốn gắn header.
>
> Không có refresh token vì không có access token ngắn hạn nào để refresh. Hạn phiên gia hạn theo hoạt động (sliding, xem §4.2).
>
> Cái này thay đổi **không gì cả** ở phía module khác: chúng nhận `Principal`, không nhận token.

`Cookie: odyssey_session=<32 byte ngẫu nhiên, base64url>`, `HttpOnly` · `Secure` · `SameSite=Lax` · `Path=/`.

`SameSite=Lax` đủ cho MVP vì FE và API **cùng gốc**: `vite.config.ts` proxy khoá `'^/api/'` sang backend ở dev, cùng domain ở production. Nếu sau này tách domain thì phải chuyển sang `SameSite=None` + `Secure` + token CSRF — ghi ở đây để lúc đó không ai quên nửa sau.

> ⚠ Khoá proxy là RegExp `'^/api/'`, **không phải** `'/api'` — comment trong `vite.config.ts` ghi rõ vì sao: khớp chuỗi thường theo tiền tố sẽ cuốn luôn route `/api-keys` của màn Tích hợp & API. Mọi endpoint ở spec này đều dưới `/api/v1/` nên khớp đúng.

### 2.5 Redis — cổng nào

`.env` và `.env.example`: **`PORTAL_REDIS_PORT=6382`**.

> ⚠ Plan M1 (`2026-07-29-m1-nen-cach-ly-da-tenant.md` dòng 168 · 179 · 3169) ghi `redis 6380` và `postgres 5433`. **Cả hai số đó đã cũ** — `docker-compose.dev.yml` hiện là `${PORTAL_REDIS_PORT:-6382}` và postgres `5442`. Đọc `.env`, đừng đọc plan. Ghi ở đây vì hardcode `6380` sẽ nối vào Redis của project khác trên cùng máy dev — đúng loại lỗi mà `docs/dev-ports.md` tồn tại để chặn.

Client Redis tạo và đóng theo `lifespan` của FastAPI app, DSN khai ở `core/config.py` như mọi biến khác (`redis_url`, mặc định `redis://localhost:6382/0`) — không đọc `os.environ` rải rác.

---

## 3. Bảng

### 3.1 Migration `0100` — `control.users`

```sql
CREATE TABLE control.users (
    id            text PRIMARY KEY
                  CONSTRAINT users_id_check CHECK (id ~ '^u_[a-z0-9_]{1,40}$'),
    email         text NOT NULL UNIQUE,      -- luôn lưu lower(), xem §3.3
    password_hash text NOT NULL,
    name          text NOT NULL,
    lifecycle     text NOT NULL DEFAULT 'active'
                  CONSTRAINT users_lifecycle_check
                  CHECK (lifecycle IN ('active', 'suspended')),
    created_at    timestamptz NOT NULL DEFAULT now()
);
```

`id` là `text` có CHECK ký tự — cùng khuôn `control.tenants.id` (migration `0002`). Không phải `uuid`: `tenants.id` đã là text-slug vì nó đi vào tên role `agent_<id>`, và hai loại khoá trong cùng một schema là một nguồn nhầm lẫn không đổi được gì.

**`initials` KHÔNG là cột.** FE cần hai chữ trên avatar; suy từ `name` trong `service.py`. Một nguồn thì không lệch được — cột thứ hai chứa thông tin đã có trong cột thứ nhất là một bug đang chờ.

`lifecycle` dùng đúng từ vựng `tenants.lifecycle` (`active`/`suspended`/`closed`) trừ `closed` — người không bị "đóng", chỉ bị đình chỉ. Từ vựng chung để đọc hai bảng không phải học hai bộ từ.

### 3.2 Migration `0101` — `control.memberships`

```sql
CREATE TABLE control.memberships (
    user_id    text NOT NULL REFERENCES control.users(id)   ON DELETE CASCADE,
    tenant_id  text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    role       text NOT NULL
               CONSTRAINT memberships_role_check
               CHECK (role IN ('admin', 'care', 'editor', 'viewer')),
    expires_at timestamptz,          -- NULL = thành viên thường
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, tenant_id)
);
CREATE INDEX memberships_tenant_idx ON control.memberships (tenant_id);
```

Bốn giá trị `role` là **tên kỹ thuật đã chốt** ở PQ_01 §2.4:

| Giao diện (VI) | Giao diện (EN) | Trong code |
|---|---|---|
| Quản trị | Admin | `admin` |
| CSKH | Customer care | `care` |
| Biên tập | Editor | `editor` |
| Người xem | Viewer | `viewer` |

M2a **lưu và hiện** `role`, nhưng chưa dùng nó để quyết định gì — `require()` ở M2a chỉ hỏi "có hàng không". Lưu từ đầu để M2b không phải backfill.

**`expires_at`.** M2a không làm luồng xin/duyệt quyền hỗ trợ (đó là M2b, và §II.2.5 còn thiếu wireframe). Nhưng cột + vị từ `expires_at > now()` trong `require()` có ngay từ đây. Nhờ vậy BR-Q08 — *"quyền hỗ trợ = một hàng `memberships` có hạn, KHÔNG phải cờ bỏ qua"* — được cài đúng bằng cơ chế sẵn có, và M2b không sinh ra nhánh code thứ hai mà BR10 không áp dụng.

`PRIMARY KEY (user_id, tenant_id)` nghĩa là **một người một vai trò trong một workspace**. Vé hỗ trợ NobleX cũng đi qua khoá này: nhân sự NobleX xin quyền lần hai vào cùng workspace là `UPDATE expires_at`, không phải hàng thứ hai.

### 3.3 Email: chuẩn hoá ở biên nhập

`UNIQUE` trên `email` chỉ có nghĩa nếu mọi đường ghi đều `lower(trim(email))`. Đặt phép chuẩn hoá ở **service**, không ở SQL và không ở FE:

- Không dùng `citext` — thêm một extension cho một cột là chi phí vận hành không cần.
- Không đặt `UNIQUE (lower(email))` làm cách duy nhất: index biểu thức đúng, nhưng nếu code vẫn ghi `Dang@X.vn` thì hai người khác nhau nhìn thấy email khác nhau trong danh sách thành viên.

Nên: **service chuẩn hoá, cột `UNIQUE` thường, cộng một CHECK `email = lower(email)`** để một đường ghi quên chuẩn hoá là lỗi to ngay lúc INSERT, không phải một hàng lệch phát hiện sáu tháng sau.

### 3.4 Hai cổng test của M1 mà hai bảng này chạm vào

Đây là chỗ thêm bảng mà không đọc kỹ sẽ làm đỏ test của M1.

**(a) `tests/integration/test_control_schema.py` — `M1_OWNED_CONTROL_TABLES` assert bằng `==`.**
Docstring của nó đã hẹn trước `users`/`memberships` → M2a. Cách sửa: thêm một set thứ hai và assert hợp của hai set.

```python
M1_OWNED_CONTROL_TABLES = { ... }          # không đụng
M2A_OWNED_CONTROL_TABLES = {
    "users",        # 0100 — neo danh tính người
    "memberships",  # 0101 — người × workspace × vai trò
}
```

Giữ hai set riêng chứ không gộp một: phép `==` vẫn là cổng, và **ai sở hữu bảng nào vẫn đọc được** từ file test. Gộp một set là mất đúng thông tin mà cổng này tồn tại để giữ.

**(b) `tests/isolation/test_isolation_catalog.py` — `CONTROL_TABLES_DUOC_MANG_TENANT_ID`, danh sách đóng.**
`memberships` mang `tenant_id`, nên phải khai kèm lý do. Lý do phải thật, vì file này nói rõ dữ liệu phạm vi-tenant đặt ở `control` được bảo vệ bởi *"ĐÚNG KHÔNG GÌ CẢ"*:

```python
# 0101 — control-plane theo đúng nghĩa: nó CHÍNH LÀ thứ quyết định phạm vi tenant
# của một request. Đặt nó dưới RLS của tenant_data là vòng tròn — muốn đọc
# membership để biết tenant thì đã phải biết tenant trước. Cùng dạng với `jobs`
# (worker đọc TRƯỚC khi biết tenant nào). Agent có ZERO quyền trên bảng này.
"memberships",
```

`users` **không** mang `tenant_id` (một người thuộc nhiều workspace), nên không phải khai.

**(c) Quyền `portal_api` — không cần GRANT mới.** Migration `0003` đã đặt `ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal_api`, nên hai bảng mới tự có DML. Mặt sau của tiện lợi đó chính là lý do cổng (b) tồn tại.

---

## 4. Hợp đồng API

### 4.1 Endpoint

| Method | Đường | Action | Vào | Ra |
|---|---|---|---|---|
| POST | `/api/v1/auth/login` | *(công khai)* | `{email, password}` | `SessionOut` + `Set-Cookie` |
| POST | `/api/v1/auth/logout` | *(chỉ cần phiên)* | — | `204` |
| GET | `/api/v1/me` | *(chỉ cần phiên)* | — | `SessionOut` |
| POST | `/api/v1/me/workspace` | *(phải là thành viên ws đích)* | `{workspaceId}` | `SessionOut` |
| GET | `/api/v1/members` | `workspace.admin` | — | `MemberOut[]` |
| GET | `/healthz` | *(công khai)* | — | `{status, db, redis}` |

Ba đường không khai action (`login`, `logout`, `me`) phải khai **tường minh** `action=None` kèm lý do một dòng — cổng 1 (§6) coi "thiếu khai" và "khai là công khai" là hai việc khác nhau. Bỏ trống không lọt qua được.

> ⚠ **`workspace.admin` ở `/members` là khai, chưa phải chặn.** Ở M2a `require()` chỉ kiểm "có phải thành viên workspace này không" (§2.2), nên mọi thành viên đều gọi được `/members` bất kể vai trò. Cột Action trong bảng trên là **chỗ cắm** — nó ghi lại *sẽ* kiểm gì, để M2b bật lên bằng cách đổi ruột `require()` mà không sửa endpoint nào.
>
> Đây chính là cái làm "hoãn quyết định" khác với "để lại nợ" (spec tổng §3.5). Nhưng nói thẳng: **trong khoảng M2a→M2b, `/members` là một endpoint mà Người xem cũng đọc được.** Chấp nhận được vì danh sách thành viên không phải dữ liệu khách hàng, và vì cổng 1 bảo đảm không endpoint nào sau này lọt khỏi rà soát. Nếu M2b bị hoãn quá lâu thì đây là chỗ phải xem lại đầu tiên.

### 4.2 `SessionOut` — đúng hình dạng `Session` mà FE đã có

```jsonc
{
  "user":      { "id": "u_dang", "name": "Trần Hải Đăng",
                 "email": "dang@anphuland.vn", "initials": "TĐ" },
  "workspaces": [ { "id": "anphu", "slug": "anphu", "name": "An Phú Land", "plan": null } ],
  "currentWorkspaceId": "anphu",
  "actions": ["overview.read", "..."]
}
```

`actions` ở M2a = **cả 13** cho mọi thành viên, vì `require()` chưa tra ma trận. Trả đúng cái mà `require()` thực thi là điều kiện để FE không bao giờ ẩn một mục mà API lại cho, hoặc hiện một mục mà API chặn. M2b đổi cả hai chỗ trong cùng một PR.

**Hạn phiên:** `sess:<id>` TTL 12 giờ, `EXPIRE` lại mỗi request có phiên hợp lệ (sliding). Không có "remember me" ở MVP.

### 4.3 Hai chỗ hợp đồng FE không có dữ liệu thật

**① `Workspace.plan` — không có nguồn.**
FE khai `plan: string` (bắt buộc) và MSW trả `'Growth'`. Nhưng migration `0002` ghi rõ: *"VÌ SAO `tenants` KHÔNG có cột `plan`: hoá đơn không được gắn vào khoá cách ly"*, đường lùi đã để sẵn là bảng `accounts` phía trên `tenants`. Và màn `billing` đã hoãn khỏi MVP.

> **Chốt: `plan` thành `string | null`. M2a trả `null`. Sidebar hiện slug, không hiện dấu `·` và tên gói.**
>
> Trả `'Growth'` cứng là bơm dữ liệu giả vào một luồng đăng nhập thật — đúng loại thứ sống sót tới lúc demo cho khách. Sửa: `session.tsx` đổi kiểu, `components/shell` bỏ nhánh render gói khi `plan == null`.

**② `Workspace.id` và `slug` mang cùng một giá trị.**
MSW trả `id: 'ws_anphu'` + `slug: 'anphu'`, nhưng thực tế `control.tenants.id` **chính là** slug — nó đi thẳng vào tên role `agent_<id>` và vào đường dẫn `tenants/<id>/` trên kho tệp.

> **Chốt: giữ cả hai trường, cùng giá trị, ghi là dư có chủ ý.**
>
> Bỏ `slug` khỏi hợp đồng là sửa `session.tsx` cộng sidebar cho một thứ không sai. Giữ lại thì lúc nào có người thật sự cần hai khái niệm khác nhau (ví dụ đổi tên hiển thị mà giữ khoá cách ly) trường đã có sẵn chỗ. Ghi vào `docs/contracts/auth.md` để không ai tưởng là sót.

### 4.4 Hình dạng lỗi

Một hình dạng cho mọi endpoint, đặt ở `api/app.py`:

```jsonc
{ "error": { "code": "INVALID_CREDENTIALS", "message": "Email hoặc mật khẩu không đúng" } }
```

| Tình huống | Mã | HTTP |
|---|---|---|
| Sai email **hoặc** sai mật khẩu **hoặc** user `suspended` | `INVALID_CREDENTIALS` | 401 |
| Không có cookie · cookie rác · phiên hết hạn | `NO_SESSION` | 401 |
| User bị `suspended` **giữa phiên** | `NO_SESSION` | 401 |
| Có phiên, không phải thành viên ws · membership hết hạn | `FORBIDDEN` | 403 |
| Đổi sang workspace mình không thuộc | `FORBIDDEN` | 403 |

**Vì sao `suspended` giữa phiên là 401 chứ không 403.** Đình chỉ là chuyện của **danh tính**, không phải của một workspace cụ thể. 403 nói *"bạn là ai đó, chỉ không được vào chỗ này"* — sai tín hiệu, và FE sẽ hiện màn "không có quyền" trong khi đúng ra phải đẩy về `/login`. Nên `require()` **xoá luôn bản ghi phiên** rồi trả 401: một người bị đình chỉ không được còn phiên sống. Đây cũng là cùng một chỗ mà BR-Q04 áp dụng — có hiệu lực ở request kế tiếp, không chờ TTL.

**Một mã cho ba tình huống đăng nhập là cố ý.** Phân biệt "email không tồn tại" với "sai mật khẩu" là cho không một máy dò danh sách email khách hàng. Cùng lý do, service phải verify Argon2 **kể cả khi không tìm thấy user** (so với một hash mồi) — nếu không, thời gian phản hồi tự tố ra email nào có thật.

Phiên không có workspace nào (`memberships` rỗng) là **trạng thái hỏng, không phải trạng thái rỗng** — PQ_01 Q01. `/api/v1/me` trả `409 NO_WORKSPACE` chứ không trả mảng rỗng; FE đã có nhánh `throw new Error('Phiên không có workspace nào')`.

---

## 5. Frontend

| Việc | File |
|---|---|
| Route `/login` **ngoài** `_app` (18 route hiện có đều sau phiên) | `routes/login.tsx` |
| Form email + mật khẩu · lỗi 401 hiện tại chỗ · redirect về `/` khi xong | `features/auth/components/LoginForm.tsx` |
| **Chuyển `<SessionProvider>` từ `main.tsx` vào `_app.tsx`** — xem ngay dưới | `main.tsx` · `routes/_app.tsx` |

> **Vì sao phải chuyển `SessionProvider`.** Hôm nay nó bọc `<RouterProvider>` trong `main.tsx`, và nó **chặn toàn bộ app** trên `GET /api/v1/me`: chưa xong thì hiện *"Đang tải phiên…"*, lỗi thì hiện màn lỗi có nút Thử lại. Nghĩa là khi chưa đăng nhập, `/api/v1/me` trả 401 → **màn đăng nhập cũng không render được**, vì nó cũng nằm trong cây bị chặn.
>
> Sửa đúng chỗ: chuyển `SessionProvider` vào `component` của route `_app`. `_app` đã được định nghĩa là *"layout của MỌI màn sau đăng nhập"*, nên "cần phiên" và "nằm trong `_app`" là cùng một điều kiện. `/login` nằm ngoài `_app` nên render tự do, không cần phiên.
>
> Chỗ chặn chưa-đăng-nhập nằm trong `SessionProvider` (một chỗ duy nhất, không phải 18 chỗ — đúng như docstring `_app.tsx` đã hẹn): `GET /api/v1/me` trả 401 ⇒ `<Navigate to="/login" replace />`.
>
> **Không dùng `beforeLoad`** dù nó là chỗ TanStack Router quen dùng: `beforeLoad` cần `queryClient` trong router context, tức thêm plumbing ở `main.tsx` cho cùng một kết quả. Giữ trong `session.tsx` để seam phiên sống ở đúng một file. 401 phải phân biệt với lỗi hạ tầng (`ChuaDangNhap`) — hiện màn lỗi có nút Thử lại khi chưa đăng nhập là vô nghĩa, và gộp hai thứ làm một thì một sự cố hạ tầng trông như bị đăng xuất.
>
> `tests/boot.test.tsx` đang boot app bằng `routeTree.gen.ts` thật nên nó sẽ đổi theo — phải sửa cùng PR, không để đỏ.
| `switchWorkspace` gọi `POST /api/v1/me/workspace` rồi invalidate `['session']` | `lib/session.tsx` |
| `plan: string \| null` + sidebar bỏ nhánh gói khi null | `lib/session.tsx` · `components/shell/` |
| Màn `users`: bảng thành viên (tên · email · vai trò VI) | `features/auth/components/MemberList.tsx` |
| Tắt MSW ở dev khi có backend | `.env`: `VITE_MSW=0` |

`session.tsx` giữ nguyên `useSession()`, `can()`, và hình dạng `Session` — đúng lời hứa ở docstring của nó: *"M2a-BE thay ruột của file này, KHÔNG ai khác phải sửa gì"*. Ba chỗ sửa (`plan` nullable, `switchWorkspace` gọi API, 401 → `/login`) đều nằm trong file đó cộng sidebar.

**MSW không bị xoá.** Nó vẫn là cơ chế ② để 6 module kia dev màn khi chưa có endpoint. `VITE_MSW=0` chỉ tắt ở luồng có backend; `build-fe` đã canh bundle production không chứa msw.

---

## 6. Cổng test

| # | Cổng | Chứng minh điều gì | File |
|---|---|---|---|
| 1 | **Mọi route đã đăng ký khai `action`** (hoặc khai tường minh là công khai). Thiếu ⇒ đỏ | M2b không thành *"rà mọi endpoint và thêm kiểm tra"* | `tests/api/test_moi_route_khai_action.py` |
| 2 | `require()` **raise lúc import** nếu action không thuộc 13 | Sai chính tả một action không thành một endpoint không ai kiểm | `tests/api/test_require.py` |
| 3 | `actions.py` ↔ `actions.ts`: **set bằng nhau VÀ đếm đúng 13** | Đếm để bắt regex hỏng — set rỗng so với set rỗng thì bằng nhau | `apps/frontend/tests/actions-parity.test.ts` |
| 4 | Gỡ membership giữa hai request ⇒ request sau **403 ngay** | BR-Q04 · YC03: sa thải xong không còn cửa sổ 15 phút | `tests/modules/auth/test_thu_hoi.py` |
| 5 | `expires_at` quá hạn ⇒ 403; `NULL` ⇒ vào được | Vé hỗ trợ tự hết hạn (YC08), không ai phải nhớ thu hồi | `tests/modules/auth/test_membership_het_han.py` |
| 6 | User của ws A gọi endpoint đọc `tenant_data` ⇒ **0 hàng của B** | Vỏ API không phá cách ly M1 đã dựng | `tests/modules/auth/test_pham_vi_tenant.py` |
| 7 | Sai mật khẩu · user suspended · email không tồn tại ⇒ **cùng một mã 401** | Không rò danh sách email khách hàng | `tests/modules/auth/test_login.py` |
| 8 | `memberships` rỗng ⇒ `/me` trả 409, **không** trả mảng rỗng | PQ_01 Q01: hỏng không được hoá trang thành rỗng | `tests/modules/auth/test_khong_workspace.py` |
| 9 | Đổi sang workspace mình không thuộc ⇒ 403, phiên **không đổi** | Không leo phạm vi bằng cách gọi thẳng API | `tests/modules/auth/test_doi_workspace.py` |
| 10 | Đăng xuất ⇒ cookie cũ dùng lại **401** | `DEL sess:<id>` thật sự thu hồi | `tests/modules/auth/test_logout.py` |
| 11 | `lifecycle='suspended'` giữa phiên ⇒ 401 **và** bản ghi phiên bị xoá | Đình chỉ là chuyện danh tính, không hoá trang thành 403 (§4.4) | `tests/modules/auth/test_dinh_chi_giua_phien.py` |

Và **6 cổng cách ly của M1 phải vẫn xanh** — không path-filter, chạy cho mọi PR.

Cổng 3 chạy ở vitest: JS đọc `core/auth/actions.py`, trích chuỗi bằng regex, so với `ALL_ACTIONS`. Hướng đọc là **JS đọc Python** vì nguồn nằm ở tầng cưỡng chế (quyết định #5).

### 6.1 Cổng 1 hình dạng thế nào

FastAPI cho duyệt `app.routes`. Với mỗi route không thuộc danh sách miễn (`/healthz`, `/docs`, `/openapi.json`), quét `dependencies` tìm marker do `require()` gắn. Không thấy ⇒ đỏ, kèm **method + đường** trong thông điệp để người đọc log sửa được ngay không phải đoán.

Route công khai khai bằng `require(None, ly_do="...")` — nó cũng gắn marker, nên "công khai có chủ ý" và "quên khai" phân biệt được. Đây là chỗ dễ làm sai thành cổng trang trí: nếu route công khai chỉ đơn giản không có dependency thì cổng không phân biệt được hai trường hợp và mọi endpoint quên khai đều lọt.

---

## 7. Bootstrap dev — không có bước này thì server không nối được DB

`portal_api` được migration `0003` tạo ở dạng **NOLOGIN, không mật khẩu**, và docstring nói rõ đó là cố ý: *"Để NOLOGIN làm hệ FAIL CLOSED: quên bước cấp mật khẩu ở môi trường thật thì app KHÔNG NỐI ĐƯỢC (lỗi to, thấy ngay lúc deploy)"*. `tests/conftest.py` tự `ALTER ROLE portal_api LOGIN PASSWORD` bằng superuser trong container.

**Nửa việc đã có sẵn.** Makefile đã có target `grant-api-dev` làm đúng phép `ALTER ROLE portal_api LOGIN PASSWORD 'apidev'` qua `docker compose exec postgres psql`, kèm comment giải thích vì sao cần. Nên M2a **không** phải làm lại phần đó — chỉ phải (a) nói rõ nó là bước bắt buộc trong luồng khởi động, và (b) thêm phần còn thiếu là **seed**.

> **Chốt: thêm một target `make dev-seed`**, idempotent, **chỉ chạy trên container dev**:
> 1. Seed **1 user · 3 workspace · 2 membership** — chi tiết ngay dưới
> 2. In ra email + mật khẩu để đăng nhập
>
> Script phải **từ chối chạy** nếu DSN không trỏ `localhost`/`127.0.0.1`. Một script ghi mật khẩu đã hash vào bảng `users` là thứ không được lỡ tay chạy trên production.
>
> Và thêm một target tổng `make up` = `dev` → `migrate` → `grant-api-dev` → `dev-seed`. Bốn bước theo đúng thứ tự, chạy lệch thứ tự là lỗi khó đọc — `grant-api-dev` trước `migrate` thì role chưa tồn tại.

Seed cụ thể:

| Thứ | Giá trị | Vì sao |
|---|---|---|
| User | `u_dang` · `dang@anphuland.vn` | Trùng user giả của MSW → so màn thật với màn MSW được ngay |
| Workspace | `anphu` · `sunrise` · `haven` | Ba, đúng ba workspace giả của MSW |
| Membership | `anphu` (`admin`) · `sunrise` (`admin`) | Chỉ **hai** — để đổi workspace thử được |
| Không membership | `haven` | Switcher phải hiện **2, không phải 3**. Đó là phép chứng minh cách ly bằng mắt |

`haven` tồn tại trong DB mà không hiện trên UI là toàn bộ ý nghĩa của seed này. Seed đúng những workspace user thuộc thì không chứng minh được gì — mọi bug lọc đều trông như chạy đúng.

---

## 8. Đổi tên thư mục module

### 8.1 Bỏ tiền tố số — và ba lý lẽ không đứng được

Spec tổng §4① viết `modules/m2_auth/`, `modules/m3_config/`. Spec này bỏ tiền tố: **`modules/auth/`**.

Ba cơ chế tưởng móc vào tiền tố, kiểm lại thì không:

| Lý lẽ | Thực tế |
|---|---|
| Dải revision `0100`–`0149` gắn với module | Số revision nằm trong **tên file migration**, không liên quan tên thư mục |
| `make test-module M=m4` cần tiền tố | Makefile là `pytest tests/modules/$(M)` — `M=auth` chạy y hệt |
| CI job path-filtered theo module | `.github/workflows` **chưa tồn tại**; và path filter dùng tên nào cũng được |

Cái tiền tố thật sự cho: thứ tự khi `ls` (`m1…m9` sắp theo thứ tự phụ thuộc). Không đủ để đánh đổi bằng một tên không nói lên nội dung. Bù lại bằng **bảng đối chiếu module ↔ thư mục** trong spec tổng §3.

### 8.2 Ba chỗ phải sửa trong spec tổng, cùng một lần

| Dòng | Hiện | Đổi thành |
|---|---|---|
| 275–279 | `modules/m1_foundation/` · `m2_auth/` · `m3_config/` | `modules/auth/` · `config/` (M1 không có thư mục module — code ở `core/`) |
| 293–296 | `features/m2-auth/` | `features/auth/` |
| 364 | `tests/modules/m2_auth/` | `tests/modules/auth/` |

Kèm một dòng ghi **vì sao** đổi. Không có nó thì người sau đọc spec thấy `m2_auth`, thấy cây thật là `auth`, và sẽ tưởng cây thật là chỗ sai.

### 8.3 FE đổi theo, sáu thư mục

```
features/m2a-auth      -> features/auth
features/m4-realestate -> features/realestate
features/m5-agent      -> features/agent
features/m6-kb         -> features/kb
features/m7-ops        -> features/ops
features/m8-platform   -> features/platform
```

Mỗi thư mục hiện chỉ có `nav.ts`, cộng vài dòng import ở `nav-registry.ts`. **Đây là lúc rẻ nhất** — sau khi 6 module kia đổ code vào thì không còn rẻ. `features/deferred/` giữ nguyên: nó không phải tên module.

---

## 9. Định nghĩa "xong"

- [ ] `make dev` lên được; mở trình duyệt thấy **màn đăng nhập**
- [ ] Đăng nhập bằng user seed → vào portal, sidebar hiện tên · chữ viết tắt · slug workspace, **tất cả từ Postgres** (`VITE_MSW=0`)
- [ ] Đổi workspace ở chân sidebar → gọi API thật → dữ liệu theo ws mới
- [ ] Switcher hiện **2** workspace (`anphu`, `sunrise`), **không** hiện `haven` dù nó có trong DB
- [ ] Màn `users` hiện danh sách thành viên thật kèm vai trò tiếng Việt
- [ ] `/docs` liệt kê mọi endpoint kèm action nó đòi
- [ ] Đăng xuất → về `/login`; bấm back không vào lại được
- [ ] 11 cổng ở §6 xanh; **6 cổng cách ly của M1 vẫn xanh**
- [ ] `make lint` và `make lint-fe` xanh
- [ ] `tests/test_module_boundaries.py` thoát nhánh early-return (đã có `modules/auth/`) và xanh
- [ ] `docs/contracts/auth.md` viết xong: `Principal` · `require()` · `SessionOut` · ai sở hữu gì
- [ ] Spec tổng §4① sửa xong ba chỗ ở §8.2
- [ ] **Một module thứ hai cắm thử được**: thêm `modules/_probe/router.py` một endpoint, chạy lên, thấy nó bị cổng 1 canh và bị `require()` chặn đúng — rồi xoá. Không có phép thử này thì "vỏ API dùng được" chỉ là lời hứa

---

## 10. Hai khoảng trống spec này KHÔNG lấp — ghi để không ai tưởng đã có

### 10.1 Mặt phẳng Nền tảng chưa có module nào sở hữu

PQ_01 §II chia quyền thành hai mặt phẳng. Mặt phẳng **Nền tảng** (nhân sự NobleX: ai được tạo workspace · đình chỉ · xem tình trạng vận hành · **xem số liệu tính tiền**) không nằm trong 18 màn — cả 18 đều là tenant portal — và không module nào M1–M9 sở hữu nó.

M2a-BE dựng đúng cơ chế mà mặt phẳng đó sẽ cần (`require()` · `memberships.expires_at` cho vé hỗ trợ), nhưng **không** dựng back-office. Khi nào có người quyết định làm nó, nó là một module mới, không phải một màn thêm vào portal.

### 10.2 Vòng đời mật khẩu

M2a có: hash Argon2id, verify, đăng nhập. M2a **không** có: đổi mật khẩu, quên mật khẩu, xác minh email, chống dò mật khẩu (rate limit ở M8).

Hệ quả cụ thể, nói thẳng: **user chỉ tạo được bằng seed script.** Không có đường tự đăng ký, không có thư mời (M2b). Đó là đủ cho MVP nội bộ và cho demo, **không đủ để mở cho khách thật**. Điều kiện tối thiểu trước khi có khách thật: thư mời (M2b) + đặt lại mật khẩu + rate limit đăng nhập (M8).
