# Owner workspace tự phát khoá đấu nối agent — thiết kế

> **Ngày:** 2026-08-04 · **Trạng thái:** đã triển khai
> **Bổ sung cho:** [`docs/contracts/dau-noi-agent.md`](../../contracts/dau-noi-agent.md) — không thay thế.
> **Trải hai repo:** `odyssey-portal-backend` (§4) và `odyssey-portal-frontend` (§5).
>
> ⚠️ **Lệch với code hiện tại (chốt sau khi spec này viết):** mọi ví dụ `ENDPOINT_URL` dưới đây dùng
> `wss://…agents.noblex.vn/…` — đó là giá trị lúc thiết kế. Domain và scheme thật đã đổi thành
> `ws://<tenant_id>.agents-dev.noble.vn/v1/chat` (`ws`, không `wss` — khớp gateway hiện tại, chưa có
> TLS ở tầng đó). Nguồn đúng luôn là `src/portal/modules/enrollment/endpoint.py` +
> `Settings.gateway_base_domain`, không phải các đoạn trích trong spec này.

## 1. Vấn đề

Khoá `AGENT_API_KEY` hôm nay chỉ phát được bằng hai đường, cả hai đều ngoài tầm người dùng portal:

- `POST /api/v1/agent/admin/deployments` — cần header `X-Platform-Admin-Token` (admin nền tảng, xuyên tenant).
- `make seed-agent` — script dev, có guard chỉ-localhost.

Frontend **không có** đường nào: màn `/api-keys` còn là `<ScreenStub screen="api" />`, và FE chưa có hạ tầng gửi token quản trị nền tảng (grep `X-Platform-Admin-Token` trong `odyssey-portal-frontend/src` → 0 kết quả).

Hệ quả: owner một workspace muốn đấu nối pod agent phải nhờ admin nền tảng chạy tay. Không có đường tự phục vụ, không có đường thu hồi từ UI.

## 2. Phạm vi

**Làm:**

- Owner workspace (`ACTIONS.WORKSPACE_ADMIN`) tự phát khoá cho deployment `chat` **của workspace mình**.
- Tự tạo deployment `chat` nếu workspace chưa có.
- Liệt kê khoá đang sống, thu hồi khoá.
- Màn `/api-keys` đầy đủ: bảng, trạng thái rỗng, dialog tạo, dialog hiện khoá một lần, dialog xác nhận thu hồi.
- `ENDPOINT_URL` suy dẫn từ `tenant_id`, hiện kèm khoá để bàn giao cho bên agent.

**Không làm (và vì sao):**

| Không làm | Vì sao |
|---|---|
| Deployment `voice` | Chốt với người yêu cầu: MVP chỉ `chat`. Cột `kind` vẫn giữ, hàm vẫn nhận tham số — không chặn đường sau. |
| Owner xoay bí mật hạ tầng (`xoay_bi_mat`) | Bấm nhầm là mọi pod của tenant mất kết nối sau một chu kỳ TTL. Giữ ở cổng admin nền tảng. |
| Ghi vào cột `deployments.endpoint` | `ENDPOINT_URL` **suy được** từ `tenant_id` + `gateway_base_domain`. Lưu bản suy dẫn thì đổi domain một lần là mọi hàng cũ sai. Cùng lý lẽ `bi_mat.py` đã viết cho `secret_version`. Cột này hôm nay chưa ai ghi và tiếp tục để trống. |
| Giới hạn nhịp khi tạo khoá | Nhịp `10 lần / 5 phút` hiện có là cho `/bootstrap` (chống dò khoá). Tạo khoá đã sau cổng phiên + cổng quyền; thêm nhịp là giải bài chưa có. |
| UI cho admin nền tảng | Đường admin token giữ nguyên, không sửa gì. |

## 3. Bốn quyết định và lý do

### 3.1 Router riêng, tenant-scoped — không mở rộng cổng admin

Thêm 3 endpoint dưới **cổng phiên** + `require(ACTIONS.WORKSPACE_ADMIN)`, tenant suy từ `Principal.tenant_id`.

Phương án bị loại: cho `/agent/admin/*` nhận thêm cổng phiên. `router.py:12` đã cảnh báo thẳng:

> `/agent/bootstrap` KHÔNG nhận cookie phiên. Trộn hai đường xác thực là mở một đường lấy credential hạ tầng bằng phiên của một người dùng workspace.

Endpoint mới **không** trả credential hạ tầng (chỉ trả `api_key`, thứ chỉ dùng để đổi credential), nên nó không phạm điều cảnh báo — nhưng gộp nó vào cùng router với đường admin thì lần sau người đọc không còn thấy ranh giới. Nên: file riêng.

`Principal.tenant_id` **đã được xác thực** qua `control.memberships` còn hiệu lực, không đến từ request (`principal.py:7-8`). Đó là chỗ duy nhất cưỡng chế tenant scoping.

### 3.2 ⚠ Router phụ phải `include_router` vào `ROUTER`

`src/portal/api/registry.py:25` chỉ quét **`modules/<tên>/router.py`** và bắt buộc module-level `ROUTER`:

```python
f = d / "router.py"
if not f.exists(): continue
router = getattr(mod, "ROUTER", None)
if router is None: raise RuntimeError(...)
```

Nên file `router_tenant.py` **tự nó vô hình** — endpoint sẽ không lên, và không có lỗi nào nổ. Bắt buộc:

```python
# router.py
from portal.modules.enrollment.router_tenant import ROUTER_TENANT
ROUTER.include_router(ROUTER_TENANT)   # registry chỉ quét router.py — xem registry.py:25
```

`ROUTER` đã có `prefix="/agent"`, nên `ROUTER_TENANT` khai `prefix=""` và path là `/keys`, cho ra `/api/v1/agent/keys`.

### 3.3 `ENDPOINT_URL` — hàm thuần ở `enrollment/endpoint.py`, KHÔNG ở `core/ten_tai_nguyen.py`

> **Sửa so với bản đầu của spec này.** Bản đầu đặt hàm vào `core/ten_tai_nguyen.py`. Sai — file đó
> có luật ở dòng 25-27: *"mọi hàm ở đây nhận ĐÚNG `tenant_id` và không tham số nào khác"*.

Hai lý do không đặt ở đó, lý do thứ hai mới là lý do thật:

1. **Chữ ký.** Hàm cần `base_domain`, tức hai tham số. (Docstring file đó nói *"Có cổng test canh
   chữ ký này"* — đã kiểm: cổng ấy **không tồn tại**, `grep inspect.signature tests/` trả 0. Luật
   vẫn là luật dù chưa có cổng, nhưng đừng dựa vào nó để đỏ giùm.)
2. **`ENDPOINT_URL` không phải cơ chế cách ly.** Lý lẽ của `ten_tai_nguyen.py` là: với Qdrant và
   kho tệp — hai kho không có RLS — *tên chính là cơ chế cách ly*, nên tên phải ở một chỗ. Còn
   `ENDPOINT_URL` là hostname công khai để gateway định tuyến; đoán đúng nó không mở được gì.
   Nó không thuộc họ bốn cái tên kia.

**Có tiền lệ:** `modules/workspace/service.py:10` gặp đúng tình huống này với `slug_tenant()` và ghi
lại *"VÌ SAO KHÔNG ĐẶT VÀO `core/ten_tai_nguyen.py`: file đó có luật…"*. Làm theo.

Nên: file mới `modules/enrollment/endpoint.py` — thuần, không I/O, test được không cần
Postgres/MinIO/config. Cùng lý lẽ `bi_mat.py` đã viết cho chính nó.

```python
def url_endpoint_agent(tenant_id: str, base_domain: str, kind: str = "chat") -> str:
    """wss://<tenant_id>.<base_domain>/v1/<kind>

    KHÔNG đổi hoa/thường và KHÔNG url-encode tenant_id: CHECK của
    control.tenants là `^[a-z][a-z0-9_]{1,30}$` — đã là subdomain hợp lệ.
    """
    return f"wss://{tenant_id}.{base_domain}/v1/{kind}"
```

`config.py` thêm:

```python
gateway_base_domain: str = "agents.noblex.vn"
"""Hằng số nền tảng, ops cấu hình. ENDPOINT_URL của MỌI tenant suy từ nó —
không hardcode rải rác. Đổi giá trị này là đổi endpoint của tất cả tenant."""
```

> **Đã xác nhận với người yêu cầu:** path là `/v1/chat`, không phải `/v1/v1/chat` (bản gõ đầu lặp `v1`).

### 3.4 `PORTAL_URL` không xuất hiện trong khối env

Chốt với người yêu cầu: `PORTAL_URL` là **hằng số nền tảng**, giống nhau cho mọi tenant, ops set sẵn trong pod. Khối env bàn giao chỉ chứa thứ **thay đổi theo tenant**:

```bash
ENDPOINT_URL=wss://anphu.agents.noblex.vn/v1/chat
AGENT_API_KEY=ody_ag_<43 ký tự>
```

Contract G-1 (`dau-noi-agent.md` §1) vẫn nguyên — pod vẫn cần `PORTAL_URL` để gọi `/agent/bootstrap`; UI chỉ không nhắc lại một hằng số. `ENDPOINT_URL` là thông tin cho bên agent biết gateway sẽ route tới pod của họ từ hostname nào.

## 4. Backend

### 4.1 Ba endpoint

Tất cả dưới `/api/v1/agent`, cổng phiên, `require(ACTIONS.WORKSPACE_ADMIN)`.

| Method | Path | Status | Trả về |
|---|---|---|---|
| `GET` | `/keys` | `200` | `DanhSachKhoaOut` — `endpoint_url` + khoá đang sống |
| `POST` | `/keys` | `201` | `KhoaDaTaoOut` — **chứa khoá thô, đúng một lần** |
| `DELETE` | `/keys/{key_id}` | `204` | Rỗng. `404` nếu khoá không thuộc tenant của người gọi |

**`kind` không có trong request.** Router truyền cứng `kind="chat"` xuống service. MVP chỉ
`chat` (§2), và để client chọn `kind` là mở một tham số mà backend chưa có màn hình nào phục vụ
— đường `voice` mở sau thì thêm trường vào `TaoKhoaIn`, không phải sửa chữ ký service (nó đã
nhận `kind`).

### 4.2 Contracts (`enrollment/contracts.py`)

```python
class TaoKhoaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="", max_length=60)
    """Nhãn người dùng đặt. Rỗng là hợp lệ — bảng vẫn nhận ra khoá qua tiền tố."""

class KhoaOut(BaseModel):
    """Một hàng trong bảng. CỐ Ý KHÔNG có `api_key` — không đường nào đọc lại khoá thô."""
    id: int
    key_prefix: str
    label: str
    created_at: datetime
    last_used_at: datetime | None

class DanhSachKhoaOut(BaseModel):
    """Bọc list trong object vì màn hình cần `endpoint_url` KỂ CẢ khi chưa có khoá nào."""
    endpoint_url: str
    keys: list[KhoaOut]

class KhoaDaTaoOut(BaseModel):
    """⚠️ Response CHỨA KHOÁ THÔ. Không log, không trace, không APM span — cùng luật G-10.

    CỐ Ý KHÔNG có `label`/`created_at`: `service._phat_khoa` trả `KhoaMoiOut`
    (`id · deployment_id · api_key · key_prefix`) và không cái nào trong hai
    trường đó có ở đấy. Thêm chúng là phải nới `KhoaMoiOut` — thứ đường admin
    cũng dùng — để phục vụ hai trường mà dialog KHÔNG hiện: nhãn thì người dùng
    vừa gõ, còn thời điểm tạo thì bảng phía sau refetch xong là có.

    CỐ Ý KHÔNG có `deployment_id`: owner không cần biết số hiệu deployment, và
    lộ id nội bộ ra UI là mở một khái niệm không có chỗ nào dùng.
    """
    id: int
    api_key: str
    key_prefix: str
    endpoint_url: str
```

Router dựng `KhoaDaTaoOut` từ `KhoaMoiOut` mà service trả về, cộng `endpoint_url` suy từ `p.tenant_id`.

### 4.3 Repo (`enrollment/repo.py`) — hai hàm mới

```python
async def deployment_cua_tenant(conn, tenant_id: str, kind: str) -> int | None:
    """id deployment của tenant theo kind, hoặc None. Dùng để biết có phải cấp phát không."""

async def liet_ke_khoa_cua_tenant(conn, tenant_id: str) -> list[dict]:
    """Khoá CHƯA thu hồi của mọi deployment thuộc tenant, mới nhất trước.

    `revoked_at IS NULL` — khoá đã thu hồi không hiện lại. Nó vẫn ở DB cho nhật ký,
    nhưng màn hình nói "khoá đang dùng được", và một hàng chết trong đó là gây nhầm.
    """
```

`tenant_cua_khoa(conn, key_id)` **đã tồn tại** — dùng nó cho phép kiểm sở hữu lúc thu hồi, không thêm hàm mới.

### 4.4 Service (`enrollment/service.py`)

```python
async def phat_khoa_cho_tenant(pool, ha_tang, tenant_id, kind, label, boi) -> KhoaMoiOut:
    """Phát khoá cho tenant, tự cấp phát deployment nếu chưa có.

    `cap_phat` idempotent ở phần hạ tầng (dat_mat_khau_role tạo-nếu-chưa-có,
    dat_khoa_kho_tep ghi đè) nên nhánh "chưa có deployment" an toàn khi gọi lại.
    """
    dep_id = await repo.deployment_cua_tenant(pool, tenant_id, kind)
    if dep_id is None:
        return await cap_phat(pool, ha_tang, tenant_id, kind, label, boi)
    return await _phat_khoa(pool, dep_id, tenant_id, label, boi)

async def liet_ke_khoa(pool, tenant_id: str) -> list[contracts.KhoaOut]: ...

async def thu_hoi_khoa_cua_tenant(pool, key_id: int, tenant_id: str, boi: str) -> None:
    """Thu hồi CHỈ KHI khoá thuộc tenant người gọi.

    Khoá của tenant khác trả 404 y như khoá không tồn tại — cố ý không phân biệt,
    cùng lý lẽ 401 của bootstrap: phân biệt được là một đường dò xem tenant khác
    có khoá id bao nhiêu.
    """
```

**Sửa `phat_khoa_them`:** hôm nay hardcode `label=""` (service.py:70). Nhận thêm tham số `label: str = ""`. Đường admin gọi không truyền → hành vi cũ không đổi.

### 4.5 Router (`enrollment/router_tenant.py` — file mới)

```python
"""Ba endpoint tenant-scoped của M10 — CỔNG THỨ BA của module.

    /agent/bootstrap  → Bearer api_key            (pod gọi)
    /agent/admin/*    → X-Platform-Admin-Token    (admin nền tảng gọi)
    /agent/keys       → phiên + WORKSPACE_ADMIN   (owner workspace gọi)   ← file này

VÌ SAO FILE RIÊNG CHỨ KHÔNG THÊM VÀO router.py: ba cổng xác thực khác nhau trong
một file thì lần sau người đọc không còn thấy ranh giới. Nhưng registry.py:25 CHỈ
quét `router.py`, nên file này phải được `ROUTER.include_router()` từ đó — nếu
không, endpoint không lên và KHÔNG có lỗi nào nổ.

Tenant KHÔNG đến từ request — nó là `p.tenant_id`, đã xác thực qua membership.
"""
```

Cập nhật docstring `router.py`: *"Sáu endpoint"* → *"Chín endpoint · BA cổng xác thực"*.

### 4.6 Mã lỗi

| HTTP | `error.code` | Khi nào |
|---|---|---|
| `401` | (cơ chế phiên hiện có) | Chưa đăng nhập |
| `403` | `FORBIDDEN` (`api/loi.py:36` — cơ chế `require` hiện có) | Có phiên nhưng thiếu `workspace.admin` |
| `404` | `NOT_FOUND` | Thu hồi khoá không tồn tại **hoặc** thuộc tenant khác |
| `409` | `NOT_PROVISIONED` (`loi.chua_cap_phat`) | `cap_phat` hỏng ở hạ tầng (MinIO/Postgres không tới được) |
| `422` | (Pydantic) | `label` dài quá 60, hoặc gửi trường lạ (`extra="forbid"`) |

Thêm vào `enrollment/loi.py` — dùng **`NOT_FOUND`**, không mã mới, vì `khong_co_deployment()`
ở cùng file đã chọn mã đó cho đúng loại tình huống này:

```python
def khong_co_khoa(key_id: int) -> LoiPortal:
    """404 cho CẢ HAI nhánh: khoá không tồn tại, và khoá của tenant khác.

    Không phân biệt là cố ý — cùng lý lẽ `_KHOA_KHONG_HOP_LE` đã viết: phân biệt
    được là một đường dò xem tenant khác đang có khoá id bao nhiêu.
    """
    return LoiPortal("NOT_FOUND", 404, f"Không có khoá {key_id}")
```

Docstring `loi.py` hiện nói *"Bốn lỗi của M10"* nhưng file đã có năm hàm — sửa thành *"Sáu lỗi"*.

### 4.7 Kiểm thử backend (`tests/modules/enrollment/test_router_tenant.py`)

1. `POST /keys` khi tenant **chưa có** deployment → `201`, deployment `chat` được tạo, response có `api_key` + `endpoint_url` đúng công thức.
2. `POST /keys` khi **đã có** deployment → khoá thứ hai cùng `deployment_id`, không tạo deployment mới.
3. `GET /keys` → không chứa `api_key` ở bất kỳ hàng nào; khoá đã thu hồi không xuất hiện.
4. `GET /keys` khi chưa có khoá → `keys: []` nhưng vẫn có `endpoint_url`.
5. **Cách ly tenant:** người của tenant A gọi `DELETE /keys/{id}` với khoá của tenant B → `404`, và khoá B **vẫn sống**.
6. Thiếu `workspace.admin` → `403`.
7. `label` 61 ký tự → `422`.
8. Khoá vừa tạo bootstrap được thật: `POST /keys` → lấy `api_key` → `POST /agent/bootstrap` → `200`.

Thêm vào `tests/modules/enrollment/test_bi_mat.py` (hoặc test mới cho `ten_tai_nguyen`):
9. `url_endpoint_agent("anphu", "agents.noblex.vn")` → `wss://anphu.agents.noblex.vn/v1/chat`.

## 5. Frontend

Màn `api` thuộc **M8**, nav đã có sẵn ở `features/platform/nav.ts` với label **"Tích hợp & API"** và `requiredActions: [ACTIONS.WORKSPACE_ADMIN]`. Nên code đặt ở `features/platform/` — nav và màn ở cùng module, đúng nếp `features/agent`.

### 5.1 File

| File | Việc |
|---|---|
| `features/platform/api.ts` | `LoiApi` + `goi()` + 3 hàm gọi API + kiểu TS |
| `features/platform/components/TichHopApiScreen.tsx` | Màn chính: header, khối endpoint, bảng, trạng thái |
| `features/platform/components/TaoKhoaDialog.tsx` | Ô nhãn + submit |
| `features/platform/components/KhoaMoiDialog.tsx` | Hiện khoá một lần |
| `features/platform/components/ThuHoiKhoaDialog.tsx` | Xác nhận thu hồi |
| `routes/_app/api-keys.tsx` | Bỏ `<ScreenStub>`, render `<TichHopApiScreen/>` |
| `lib/msw/handlers.ts` | 3 handler mới |
| `tests/khoa-dau-noi.test.tsx` | Xem §5.6 |

`api.ts` **sao lại** `LoiApi` + `goi()` thay vì import từ `features/auth` — `tests/module-boundaries.test.ts` cấm import chéo feature. Cùng lý lẽ `features/workspace/api.ts:4-11` đã viết.

> **Hai chỗ lệch so với bản đầu của spec, phát hiện lúc code:**
>
> 1. **Màn KHÔNG render `<h1>`.** `Topbar.tsx:43` đã render một `<h1>` từ nhãn nav, và comment ở
>    đó ghi *"mỗi màn phải có đúng một tiêu đề cấp"*. Bản mockup §5.2 dưới đây vẽ tiêu đề Tích hợp
>    & API — đó là `<h1>` của Topbar, không phải của màn. Đây là đúng lỗi đã được sửa một lần cho
>    `UserAdmin` (xem `boot.test.tsx`, mục `users`).
> 2. **`khoiEnv()` ở `api.ts`, không ở `KhoaMoiDialog.tsx`.** eslint
>    `react-refresh/only-export-components` cảnh báo khi file component export thêm thứ không phải
>    component. Nó là hàm thuần nên chỗ đúng là cạnh hai hàm định dạng thời gian.

### 5.2 Màn chính

```
Tích hợp & API
Cấu hình đường đấu nối giữa workspace này và pod agent.

┌─ Endpoint ────────────────────────────────────────────────┐
│  ENDPOINT_URL                                             │
│  wss://anphu.agents.noblex.vn/v1/chat            [Copy]   │
│  Không phải bí mật. Gateway route hostname này tới pod     │
│  agent của workspace bạn.                                 │
└───────────────────────────────────────────────────────────┘

┌─ Khoá đấu nối agent ─────────────────  [+ Tạo khoá mới] ──┐
│  Mỗi khoá cho phép một pod agent xác thực với workspace    │
│  này. Khoá chỉ hiện một lần lúc tạo.                      │
│                                                            │
│  NHÃN            TIỀN TỐ         TẠO LÚC     DÙNG CUỐI     │
│  Pod chat prod   ody_ag_7Fk2…    04/08 16:2  2 phút trước  │
│                                              [Thu hồi]     │
│  —               ody_ag_Qm91…    01/08 09:1  Chưa dùng     │
│                                              [Thu hồi]     │
└───────────────────────────────────────────────────────────┘
```

Trạng thái rỗng dùng primitive `KhoRong` sẵn có: *"Chưa có khoá đấu nối nào"* + CTA. Lỗi tải dùng `LoiTai` (có nút thử lại). Bảng dùng `Bang`/`DauBang`/`Hang`.

`endpoint_url` hiện **kể cả khi chưa có khoá** — đó là lý do `DanhSachKhoaOut` bọc list trong object (§4.2).

### 5.3 Dialog tạo khoá

Ô nhãn tuỳ chọn (`OChu`, `max 60`), gợi ý *"vd: Pod chat production"*. Nút `Tạo khoá` / `Huỷ`. `Escape` đóng — cùng nếp `TaoWorkspaceDialog.tsx:48`.

Vì sao có bước này thay vì bấm một nút là ra khoá ngay: ba khoá không nhãn chỉ khác nhau ở tiền tố ngẫu nhiên, và lúc cần thu hồi đúng một cái thì không ai biết cái nào. Cột `agent_keys.label` đã có sẵn trong DB từ migration 0900.

### 5.4 Dialog hiện khoá — **trung tâm của tính năng**

```
┌─ Khoá đã tạo ─────────────────────────────────────┐
│                                                    │
│  ⚠  Khoá này chỉ hiện MỘT LẦN.                    │
│     Đóng hộp thoại này rồi thì không xem lại được, │
│     kể cả admin. Mất khoá ⇒ tạo khoá mới.          │
│                                                    │
│  Gửi hai dòng này cho bên agent:                   │
│  ┌──────────────────────────────────────────────┐ │
│  │ ENDPOINT_URL=wss://anphu.agents.noblex.vn/…  │ │
│  │ AGENT_API_KEY=ody_ag_7Fk2xQ9mL…              │ │
│  └──────────────────────────────────────────────┘ │
│                                  [Copy cả khối]   │
│                                                    │
│  ☐ Tôi đã lưu khoá                                │
│                                        [ Đóng ]   │
└────────────────────────────────────────────────────┘
```

Quy tắc hành vi:

- Nút `Đóng` **disabled** cho tới khi tick `Tôi đã lưu khoá`.
- `Escape` và click ra ngoài **không** đóng dialog này (khác `TaoKhoaDialog`) — đóng vô tình là mất khoá thật.
- `[Copy cả khối]` copy đúng hai dòng, có `\n`, không có dấu nháy.
- Sau khi đóng: dialog biến mất, bảng refetch, khoá thô **xoá khỏi state React**.
- Khoá thô chỉ sống trong state của component này. Không đưa vào React Query cache, không `localStorage`, không URL.

### 5.5 Dialog thu hồi

> **Thu hồi khoá `ody_ag_7Fk2…`?**
> Pod đang dùng khoá này sẽ mất kết nối ở lần làm mới TTL kế tiếp (≈1 giờ) và `/agent/bootstrap` trả `401`. Không hoàn tác được.
> `[Huỷ]` `[Thu hồi]` ← nút thu hồi tô màu cảnh báo

### 5.6 Kiểm thử frontend (`tests/khoa-dau-noi.test.tsx`)

1. Trạng thái rỗng: hiện `KhoRong` + `endpoint_url` vẫn hiện.
2. Bảng render nhãn · tiền tố · "Chưa dùng" khi `last_used_at` null.
3. Tạo khoá → `KhoaMoiDialog` hiện, khối env chứa **cả hai** dòng đúng định dạng.
4. Nút `Đóng` disabled; tick checkbox → enabled.
5. `Escape` **không** đóng `KhoaMoiDialog`.
6. Đóng dialog → khoá thô không còn trong DOM.
7. Thu hồi: mở confirm, xác nhận → hàng biến mất.
8. Lỗi API lúc tạo → thông điệp lỗi hiện trong dialog, không mất dữ liệu đã gõ.

### 5.7 `screens.ts`

Mục `api` đang `mvp: 'partial'`, `note: 'MVP bản tối thiểu'`. Đổi `note` cho khớp thực tế sau khi làm (`'Khoá đấu nối agent; chưa có webhook/tích hợp ngoài'`). **Giữ `mvp: 'partial'`** — màn này còn thiếu phần "Tích hợp" mà nav label hứa. `tests/nav-registry.test.ts:86` chỉ ràng `owner === null ⇔ mvp === 'deferred'`, nên đổi `note` không làm đỏ test.

## 6. Rủi ro

| Rủi ro | Giảm nhẹ |
|---|---|
| `router_tenant.py` không được `include_router` → endpoint im lặng không lên | §3.2; test §4.7 gọi thật qua HTTP nên sẽ đỏ |
| Khoá thô lọt vào log/APM | `KhoaDaTaoOut` có cảnh báo trong docstring, cùng luật G-10. FE không log response |
| Owner bấm tạo khoá nhiều lần, tích khoá rác | Bảng hiện hết khoá đang sống + nút thu hồi. Không giới hạn số khoá ở MVP |
| `gateway_base_domain` sai ở môi trường nào đó → bàn giao URL sai | Một hằng số, một chỗ. Test §4.7 mục 9 neo công thức |

## 7. Thứ tự triển khai

1. BE: `config.gateway_base_domain` + `ten_tai_nguyen.url_endpoint_agent` + test (nhỏ, thuần, không cần DB)
2. BE: repo → service → contracts → `router_tenant.py` + `include_router`
3. BE: `test_router_tenant.py` — 8 mục §4.7
4. FE: `api.ts` + MSW handler
5. FE: màn + 3 dialog
6. FE: `tests/khoa-dau-noi.test.tsx`
7. Cập nhật `docs/contracts/dau-noi-agent.md` §1: nói thêm rằng owner workspace tự phát khoá được từ **Tích hợp & API**, và giải thích `ENDPOINT_URL`
