# Hợp đồng — Xác thực · Phiên · Quyền

| | |
|---|---|
| Sở hữu | **M2a-BE** |
| Người tiêu thụ | M3 · M4 · M5 · M6 · M7 · M8 · M9 — mọi module có endpoint |
| Spec | `docs/superpowers/specs/2026-07-30-m2a-be-xac-thuc-phien-vo-api.md` |
| Bản FE đọc | repo `odyssey-portal-frontend`, `src/lib/session.tsx` — cùng hình dạng `SessionOut` |

## Module khác cần biết đúng ba thứ

### 1. Khai quyền trên MỌI endpoint

```python
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import require

@ROUTER.get("/du-an")
async def liet_ke(p: Principal = require(ACTIONS.CATALOG_READ)) -> list[DuAnOut]:
    ...
```

Route công khai phải nói vì sao: `_: None = require(None, ly_do="...")`.

**Thiếu khai ⇒ CI đỏ** (`tests/api/test_moi_route_khai_action.py`). Đây không phải
lời khuyên — nó là cổng. Và gõ sai tên action ⇒ app **không khởi động được**, không
phải một endpoint im lặng không ai kiểm.

Đường trong router viết **tương đối** (`/du-an`, không phải `/api/v1/du-an`) —
tiền tố do `api/app.py` gắn, một chỗ duy nhất.

### 2. Lấy kết nối có phạm vi tenant từ `Principal`

```python
async with tenant_conn(pool, p.tenant_id) as conn:
    rows = await conn.fetch("SELECT ... FROM tenant_data.du_an")
```

`p.tenant_id` **đã được xác thực** — nó đến từ một hàng `control.memberships` còn
hiệu lực. Đưa thẳng vào `tenant_conn()` là đúng.

**Không bao giờ** lấy tenant_id từ path param, query string, hay body. Nếu bạn
thấy mình đang làm vậy, dừng lại — đó là lỗ hổng. Xem `core/db/session.py`.

`tests/modules/auth/test_pham_vi_tenant.py` có một endpoint probe viết đúng khuôn
này; nếu khuôn sai thì cổng đó đỏ trước khi module nào kịp viết theo.

### 3. Dev không cần backend chạy

Phía FE: MSW đã trả `GET /api/v1/me` — repo frontend, `src/lib/msw/handlers.ts`.

## Thêm một module = thêm một thư mục

Thêm module là tạo thư mục có `router.py` khai `ROUTER`, rồi thêm một dòng import +
một dòng vào `ROUTERS` ở `api/app.py`. Quên dòng đó là 404, không có lỗi lúc khởi động.

## Những gì M2a KHÔNG hứa

| | |
|---|---|
| `p.role` quyết định được gì | **Chưa.** M2a chỉ kiểm "có phải thành viên workspace này". Mọi thành viên qua mọi `require()`. M2b tra ma trận |
| `p.actions` phản ánh vai trò | **Chưa.** Luôn là cả 13 ở M2a |
| `/members` chỉ admin đọc được | **Chưa.** Nó khai `workspace.admin` nhưng đó là *chỗ cắm*, chưa phải *chặn*. Trong khoảng M2a→M2b, Người xem cũng đọc được danh sách thành viên. Chấp nhận được vì đó không phải dữ liệu khách hàng — nhưng nếu M2b hoãn lâu thì đây là chỗ xem lại đầu tiên |
| Có nhật ký ai làm gì | **Không.** `audit_log` là M8 |
| Có rate limit đăng nhập | **Không.** M8 |
| Tạo user được qua API | **Không.** Chỉ `make dev-seed`. Thư mời là M2b |
| Đổi/quên mật khẩu | **Không.** Chưa module nào sở hữu — xem spec §10.2 |

## Hình dạng lỗi

Mọi endpoint dùng một hình dạng. Module raise `LoiPortal`, không tự trả JSON.

```jsonc
{ "error": { "code": "FORBIDDEN", "message": "..." } }
```

| Mã | HTTP | Khi nào |
|---|---|---|
| `INVALID_CREDENTIALS` | 401 | Sai email · sai mật khẩu · user bị đình chỉ — **một mã cho cả ba**, để không rò email nào có thật |
| `NO_SESSION` | 401 | Không cookie · cookie rác · phiên hết hạn · bị đình chỉ giữa phiên |
| `FORBIDDEN` | 403 | Không phải thành viên workspace · membership hết hạn · đổi sang workspace không thuộc |
| `NO_WORKSPACE` | 409 | Không thuộc workspace nào — trạng thái **hỏng**, không phải rỗng (PQ_01 Q01) |

Ba mã 401/403 dùng **cùng câu chữ** cho mọi nhánh dẫn tới nó. Cùng mã mà khác
`message` thì máy dò chỉ cần đọc `message` là phân biệt được — có test canh.

## Phiên

Cookie `odyssey_session`: 32 byte ngẫu nhiên, `HttpOnly` · `Secure` · `SameSite=Lax`
· `Path=/`. Không JWT, không refresh token — lý do ở spec §2.4.

Bản ghi ở Redis (`sess:<id>`, TTL 12h trượt theo hoạt động) chứa **đúng hai
trường**: `user_id` và `tenant_id`.

> **Đừng thêm `role` hay `actions` vào bản ghi phiên.** Redis giữ phiên, Postgres
> giữ quyền. Nhét quyền vào phiên nghĩa là gỡ một người khỏi workspace không có
> hiệu lực tới khi phiên hết hạn — đúng cái BR-Q04 và YC03 tồn tại để chặn.
> `tests/modules/auth/test_thu_hoi.py` sẽ đỏ. Đừng sửa test, sửa chỗ đó.

`SameSite=Lax` đủ vì FE và API **cùng gốc** (vite proxy `'^/api/'` ở dev, cùng
domain ở production). Tách domain thì phải chuyển sang `SameSite=None` + `Secure`
+ token CSRF — **cả ba, không phải một**.
