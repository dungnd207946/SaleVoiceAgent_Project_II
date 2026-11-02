# Plan — Tạo workspace (tenant) mới · BE + FE

Spec: `docs/superpowers/specs/2026-08-04-tao-workspace-design.md`
Nền: `docs/build_module_tenant_manage/phan-tich-doi-chieu.md`

## Nguyên tắc chi phối bản plan này

**Session `phan-quyen-dong` đang code song song.** Giao điểm file phải là **rỗng**.
Bảng dưới là danh sách file session đó khai sẽ sửa (đọc từ
`docs/superpowers/plans/2026-08-04-phan-quyen-dong.md`) — **cấm chạm**:

| Cấm chạm (BE) | Cấm chạm (FE) |
|---|---|
| `core/auth/repo.py` · `require.py` · `principal.py` | `features/auth/api.ts` |
| `api/loi.py` | `features/auth/nav.ts` |
| `modules/auth/contracts.py` · `repo.py` · `loi.py` · `quan_tri_user.py` | `lib/nav-registry.ts` · `lib/screens.ts` |
| `tests/integration/test_control_schema.py` | `lib/msw/handlers.ts` |
| `tests/modules/auth/**` | `routes/_app/roles.tsx` |

Hệ quả thiết kế, không phải hạn chế tạm:
- BE: module mới `modules/workspace` — registry tự quét, không sửa `registry.py`/`app.py`.
- FE: **không thêm màn vào sidebar** ⇒ không chạm `nav-registry.ts`/`screens.ts`. Điểm vào
  là mục "+ Tạo workspace mới" **đã có sẵn** trong `WorkspaceSwitcher.tsx` (hiện trỏ
  `/onboarding` stub) — đúng chỗ người dùng tìm, và file đó không nằm trong danh sách trên.
- FE: **không chạm `msw/handlers.ts`**. `.env` đã có `VITE_MSW=0` (dev dùng BE thật); test
  tự khai handler bằng `server.use(...)` như `doi-workspace.test.tsx` đang làm.

Chỉ dùng `git add <đường dẫn cụ thể>`, **không bao giờ** `git add -A`.

---

## Task 1 · BE — hàm thuần `slug_tenant()` + test trước

**Files:** `src/portal/modules/workspace/{__init__,service}.py` ·
`tests/modules/workspace/{__init__,test_slug.py}`

`slug_tenant(ten: str) -> str` — thuần, không DB. Luật ở spec §5:
1. fold dấu (`unicodedata.NFD` + bỏ combining; `đ`/`Đ` xử lý riêng vì NFD **không** tách)
2. lower → `[^a-z0-9]+` → `_` → strip `_`
3. rỗng → `"workspace"`; ký tự đầu không `[a-z]` → tiền tố `w_`
4. cắt ≤ 31

Test (đỏ trước):
- `"Sàn Đông Nam"` → `san_dong_nam` · `"Đất Xanh"` → `dat_xanh`
- `"  A  "` → `a` · `"123 Land"` → `w_123_land` · `"🏠🏠"` → `workspace`
- tên 200 ký tự → độ dài ≤ 31
- **property test:** 500 chuỗi sinh ngẫu nhiên (kèm dấu/emoji/ký tự lạ) → mọi output khớp
  `^[a-z][a-z0-9_]{1,30}$`. Đây là regex mà `tenants_id_check` **và**
  `control.create_agent_role()` cùng dựa vào.

Run: `uv run pytest tests/modules/workspace/test_slug.py -v`

## Task 2 · BE — contracts + loi

**Files:** `modules/workspace/{contracts,loi}.py`

`contracts.py` — camelCase Anh (khuôn `modules/auth`, không phải tiếng Việt của `config`):
- `TaoWorkspaceIn`: `name: str = Field(min_length=1, max_length=80)`
- `WorkspaceTaoRaOut`: `id` · `name` · `orgId` · `lifecycle` · `status` · `createdAt`
  (`serialization_alias` + `populate_by_name`, khuôn `ActionOut`)

`loi.py` — `WORKSPACE_TRUNG_TEN` 409. Ở module, không vào `api/loi.py` (cấm chạm).

## Task 3 · BE — repo

**File:** `modules/workspace/repo.py`

```
tim_actor(conn, user_id)      -> HangActor(id, org_id, org_role) | None
ten_da_dung(conn, org, ten)   -> bool     # so sánh chuẩn hoá, xem dưới
id_da_dung(conn, tenant_id)   -> bool
them_tenant(conn, id, ten, org) -> hàng vừa tạo (id, name, org_id, lifecycle, created_at)
them_vertical(conn, tenant_id, vertical) -> None
```

Trùng tên: so `lower(btrim(name))` — "Sàn A" và "sàn a " là một tên với người dùng. Phạm vi
`org_id`, khớp `UNIQUE (org_id, id)` của 0102.

## Task 4 · BE — service + router

**Files:** `modules/workspace/{service,router}.py`

`service.sinh_tenant_id(conn, ten)`: `slug_tenant()` → thử `_2`…`_50` (cắt gốc để tổng
vẫn ≤ 31) → hết thì `_<hex6>`. Trần vòng lặp, không `while True`.

`service.tao(conn, actor_id, vao)`:
1. `tim_actor` → `None` hoặc `org_role != 'owner'` ⇒ 403
2. `ten_da_dung` ⇒ 409 `WORKSPACE_TRUNG_TEN`
3. `sinh_tenant_id`
4. `them_tenant`
5. `them_vertical(..., 'realestate')`
6. `nhat_ky.ghi(conn, tenant_id, "workspace.tao", actor_id, {...})`
7. `status = derive_tenant_status(lifecycle, None, None, None, now)` → `provisioning`

**Không** `INSERT memberships` — spec §6.

`router.py`: `ROUTER = APIRouter(tags=["workspace"])` (không prefix — `create_app()` thêm
`/api/v1`). `POST /workspaces`, 201, `require(ACTIONS.WORKSPACE_ADMIN)` (chỗ cắm để qua
`test_moi_route_khai_action.py`; cửa thật là bước 1). `conn.transaction()` mở ở router.

## Task 5 · BE — test tích hợp

**Files:** `tests/modules/workspace/{conftest,test_tao.py}`

Conftest **riêng** của `tests/modules/workspace/` — không import
`tests/modules/auth/conftest.py` (cấm chạm, và nó đang bị sửa).

- owner → 201; đọc lại thấy `tenants` + `tenant_verticals` + `audit_log`
- non-owner → 403 (cửa thật)
- trùng tên cùng org → 409; **trùng tên khác org → 201**
- `status` = `provisioning`
- tên tiếng Việt có dấu → id không dấu, khớp regex
- rollback: `them_vertical` hỏng ⇒ **0 hàng** ở `tenants`
- **owner mở được workspace mới ngay dù không có `memberships`** — neo §6, và là chỗ sẽ đỏ
  nếu ai đó đổi `LEFT JOIN` thành `INNER JOIN` trong `doc_quyen()`

Run: `uv run pytest tests/modules/workspace -v` rồi **cả suite**:
`uv run pytest -q` (phải không làm đỏ test nào của session kia).

## Task 6 · BE — contracts: KHÔNG cần làm gì

~~`gen_contracts.py` → `contracts/openapi.json`~~ **Tiền đề sai, đã kiểm chứng.**
`contracts/` chỉ có **`actions.json`** + **`tools.json`**; **không có `openapi.json`**.
`make contracts` sinh đúng hai file đó từ `core/auth/actions.py` và
`modules/config/tools.py` — module workspace không đụng file nào trong hai nguồn đó, nên
`make contracts` chạy ra **diff rỗng**.

(Docstring của `modules/config/contracts.py` có nhắc `contracts/openapi.json` — đó là câu
mô tả đã cũ so với thư mục thật. Không sửa nó ở đây: file đó thuộc module `config`, ngoài
phạm vi bản plan này.)

⇒ **Không chạm file dùng chung nào.** Giao điểm với session `phan-quyen-dong` vẫn rỗng.

## Task 7 · FE — api + dialog

**Files (mới):** `src/features/workspace/api.ts` ·
`src/features/workspace/components/TaoWorkspaceDialog.tsx`

`api.ts`: copy khuôn `LoiApi` + `goi<T>()` của `features/auth/api.ts` — **copy, không
import** (cấm chạm file đó, và cổng `module-boundaries.test.ts` chặn import chéo feature).
`taoWorkspace(name): Promise<WorkspaceMoi>`.

Dialog — style khớp template hiện có, dùng đúng token có sẵn (`bg-surface`, `border-border-field`,
`text-[12.5px]`, `rounded-[10px]`, `bg-ac`/`hover:bg-acd`, `text-badge-alert-fg`):
- `role="dialog"` + `aria-modal`, backdrop mờ, Esc + bấm ngoài để đóng, autofocus ô tên
- một ô `name`; nút "Tạo workspace" disabled khi rỗng hoặc đang gửi
- **xem trước id**: hiện slug sẽ sinh dưới ô nhập, font mono — người dùng thấy trước
  `san_dong_nam`. Dùng bản TS của `slug_tenant` (chỉ để hiển thị; BE vẫn là nguồn thật)
- lỗi 409 hiện tại chỗ, không toast
- thành công: `queryClient` bỏ cache + đặt phiên mới, rồi **chuyển sang workspace vừa tạo**

## Task 8 · FE — nối vào WorkspaceSwitcher

**File (sửa):** `src/components/shell/WorkspaceSwitcher.tsx` — **không** nằm trong danh
sách cấm chạm.

Đổi mục "+ Tạo workspace mới" từ `<Link to="/onboarding">` thành `<button>` mở dialog.
**Chỉ hiện khi `session.orgRole === 'owner'`** — khớp cửa thật ở BE; hiện cho member là mời
họ bấm vào một 403.

⚠ Trước khi sửa: `grep -rn "onboarding" tests/` — nếu `shell.test.tsx` neo link đó thì cập
nhật test cho đúng hành vi mới (đó là test của màn này, không phải của session kia).

## Task 9 · FE — test + cổng

**File (mới):** `tests/tao-workspace.test.tsx` — khuôn `doi-workspace.test.tsx`
(`server.use(...)`, `boot()`, `FAKE_SESSION` chỉ **đọc**).

- owner: mở menu → bấm "Tạo workspace mới" → dialog hiện
- gõ tên → **`POST /api/v1/workspaces` được gọi với đúng `name`**
- 409 → thông điệp hiện trong dialog, dialog **không** đóng
- thành công → `switchWorkspace` được gọi với id mới
- `orgRole: 'member'` → **không** thấy mục "Tạo workspace mới"

Run: `npm test` · `npm run typecheck` · `npm run lint` · `npm run format:check`

## Task 10 · Kiểm chứng end-to-end thật

1. BE: `make up` (đã chạy: postgres 5442, redis 6382, minio 9002, qdrant 6343) →
   `uv run python scripts/dev_seed.py` → `make api` (:8100)
2. Gọi `POST /api/v1/workspaces` bằng phiên owner thật, xác nhận 201 + hàng trong DB
3. FE: `npm run dev` với `VITE_MSW=0`, đăng nhập owner, tạo workspace, xác nhận nó xuất
   hiện trong switcher và chuyển vào được
4. `git status` — xác nhận **không** có file nào của session kia bị sửa

## Không làm (spec §9)

Cấp phát hạ tầng · `GET /workspaces` · sửa/đình chỉ/xoá workspace · publish config v1 tự
động · đổi `ConfigPayload` · chuyển config agent sang Postgres.
