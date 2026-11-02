# Thiết kế — Tạo workspace (tenant) mới

> **Trạng thái:** spec, chưa implement.
> **Phạm vi:** đúng một đường: owner tổ chức bấm "Tạo workspace" → có một tenant dùng được.
> **Không thuộc phạm vi:** cấp phát hạ tầng (đã có ở `modules/enrollment`), đổi
> `ConfigPayload`, chuyển cấu hình agent sang Postgres. Xem §9.
> **Tài liệu nền:** `docs/build_module_tenant_manage/phan-tich-doi-chieu.md` — đối chiếu
> `spec.md` gốc với code thật, và ba chỗ `spec.md` sai.

---

## 1. Vấn đề

Không có đường tạo tenant. `INSERT INTO control.tenants` chỉ tồn tại ở
`scripts/dev_seed.py:94` và trong tests. Mọi thứ phía sau đã xong: form cấu hình
(`modules/config`), cấp phát hạ tầng (`modules/enrollment`), lớp đọc của agent
(`agent_api`). Thiếu đúng bước đầu tiên.

## 2. Quyết định đã chốt

| # | Quyết định | Lý do |
|---|---|---|
| Q1 | **Owner tổ chức** tạo workspace (`users.org_role = 'owner'`) | Đúng khuôn `quan_tri_user.py` đang dùng cho `/users`. Không phải platform-admin: tạo workspace là việc thường ngày của khách, không phải của ops |
| Q2 | **Provisioning TÁCH RỜI** — endpoint này không gọi `enrollment` | `CREATE ROLE` và khoá MinIO không rollback cùng transaction DB. Hệ đã thiết kế sẵn cho đường này: `derive_tenant_status` có state `provisioning`, `HaTang.thieu_gi()` báo được còn thiếu gì, `cap_phat()` ghi *"hỏng thì admin bấm lại là xong"* |
| Q3 | **Có ghi `tenant_verticals`** — 1 dòng `('realestate')` | Bảng đã tồn tại (0002) và đã được khai *cố ý* trong danh sách đóng của `test_isolation_catalog.py`. Để nó rỗng vĩnh viễn là tệ hơn cả hai lựa chọn khác. Nó cũng là câu trả lời cấp-dữ liệu cho "workspace này lĩnh vực gì" **trước khi** có config draft đầu tiên; `finance` đã nằm trong CHECK của 0002 |
| Q4 | **`tenant_id` giữ định dạng hiện tại** `^[a-z][a-z0-9_]{1,30}$` | §7 của `spec.md` gốc (`org_1d9f1a2f_demo-sales`) **vi phạm CHECK đang chạy**: không cho `-`, tối đa 31 ký tự. Cùng regex đó được `control.create_agent_role()` dùng lại để `CREATE ROLE agent_<id>` — nới lỏng là mở đường SQL injection. Và `tenants.id` là khoá của 4 chỗ cùng lúc (RLS · `TENANT_ID` pod · `tenants/<id>/` MinIO · `kb_<id>` Qdrant) |
| Q5 | **KHÔNG nhúng `org_id` vào `tenant_id`** | Đã có `tenants.org_id` NOT NULL + `UNIQUE (org_id, id)` + index `tenants_org_idx`. Nhúng vào là nguồn sự thật thứ hai cho cùng một quan hệ |
| Q6 | **Không seed `field_policy_live`** | Cơ chế gate cột đã khai tử ở 0400/0401. `dau-noi-agent.md` G-6: *"cơ chế `field_policy_live` đã bị xoá khỏi hệ, đừng tìm chúng."* |

## 3. Đặt ở đâu — module mới `modules/workspace`

**Đảo quyết định ban đầu.** Bản nháp đầu định đặt vào `modules/auth` vì tưởng phải ghi
`memberships` — bảng auth sở hữu. §6 đã chứng minh **không ghi `memberships`**, nên lý do
đó không còn. Module mới ghi đúng ba bảng: `tenants` · `tenant_verticals` · `audit_log`.

Và có một lý do vận hành quyết định: **session `phan-quyen-dong` đang sửa đồng thời**
`core/auth/repo.py` · `require.py` · `principal.py` · `api/loi.py` ·
`modules/auth/{contracts,repo,loi,quan_tri_user}.py`. Đặt vào `modules/auth` là đè nhau
trên đúng những file đó.

`modules/workspace` cho **giao điểm rỗng**:
- `api/registry.py` tự quét `modules/*/router.py` → **không sửa** `registry.py` hay `app.py`
- `contracts.py` riêng → **không sửa** `modules/auth/contracts.py`
- `repo.py` riêng, tự `SELECT id, org_id, org_role FROM control.users WHERE id = $1` →
  **không import** `modules/auth/repo` (cấm bởi cổng ranh giới) và không sửa nó

Đọc `control.users` từ module khác là chấp nhận được — nhiều module đã đọc bảng `control`.
Ranh giới mà cổng bảo vệ là **import ruột**, và hai module cùng **ghi** một bảng; ở đây
không có cả hai.

**File mới:** `src/portal/modules/workspace/{__init__,contracts,loi,repo,service,router}.py`

## 4. Hợp đồng API

Router: `src/portal/modules/auth/router.py` (`ROUTER` không prefix; `create_app()` thêm
`/api/v1`). Contracts: `modules/auth/contracts.py` — **camelCase Anh**, khớp phần còn lại
của auth (khác `modules/config` dùng tiếng Việt, vì đó là hợp đồng với màn hình).

### 4.1. `POST /api/v1/workspaces` → `201`

```
Request                          Response 201
──────────────────────────       ──────────────────────────
{ "name": "Sàn Đông Nam" }       { "id": "san_dong_nam",
                                   "name": "Sàn Đông Nam",
                                   "orgId": "noble",
                                   "lifecycle": "active",
                                   "status": "provisioning",
                                   "createdAt": "2026-08-04T…" }
```

| Trường vào | Ràng buộc |
|---|---|
| `name` | `min_length=1`, `max_length=80`, strip khoảng trắng hai đầu |

`status` là **hàm thuần** `derive_tenant_status(lifecycle, last_seen_at=None,
running_version=None, live_version=None, now)` — workspace mới luôn ra `provisioning`, và
`core/tenant_status.py` ghi rõ *"Workspace mới tạo là đây, và đó KHÔNG phải lỗi."*
Không lưu cột `status`.

### 4.2. Khai quyền

```python
@ROUTER.post("/workspaces", response_model=WorkspaceTaoRaOut, status_code=201)
async def tao_workspace(
    vao: TaoWorkspaceIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> WorkspaceTaoRaOut:
    async with pool.acquire() as conn, conn.transaction():
        return await quan_tri_workspace.tao(conn, p.user_id, vao)
```

`require(ACTIONS.WORKSPACE_ADMIN)` là **chỗ cắm** để qua cổng
`test_moi_route_khai_action.py` — y hệt `POST /users`. **Cửa thật là `_lay_owner()`**
trong service, kiểm `org_role != 'owner'` → `403`. Hai thứ khác nhau, và
`quan_tri_user.py` đã ghi cảnh báo này ở header — spec này không phát minh gì mới.

`p.tenant_id` **không dùng**: đây là hành động cấp tổ chức, `org_id` suy từ `p.user_id`
trong service. Dùng `p.tenant_id` là thu hẹp sai phạm vi.

> ⚠️ `Principal` hiện **không có** `org_id`/`org_role` (chỉ `user_id`, `tenant_id`,
> `role`, `actions`). Đó là lý do phải đi qua `_lay_owner()` — không phải quên.

### 4.3. Mã lỗi

| Mã | HTTP | Khi nào |
|---|---|---|
| `KHONG_DU_QUYEN` | 403 | không phải `org_role='owner'` (dùng `loi_chung.khong_du_quyen()`) |
| `WORKSPACE_TRUNG_TEN` | 409 | tổ chức đã có workspace cùng tên (so sánh sau khi chuẩn hoá) |
| — | 422 | `name` rỗng hoặc quá 80 ký tự (FastAPI + Pydantic) |

## 5. Sinh `tenant_id`

Mirror `sinh_user_id()` (`quan_tri_user.py:76`) — cùng hình dạng, cùng lý do: `tenants.id`
đọc được bằng mắt vì nó xuất hiện trong `audit_log`, trong tên role Postgres, trong đường
dẫn MinIO và tên collection Qdrant. `t_a3f9c1b2` ở đó không nói gì cho người đọc log.

```
"Sàn Đông Nam"  ->  "san_dong_nam"
"Sàn Đông Nam"  ->  "san_dong_nam_2"   (nếu id đã dùng)
```

**Khác `sinh_user_id` một điểm — phải fold dấu tiếng Việt.** `sinh_user_id` chạy trên
local-part của email (đã là ASCII) nên `re.sub(r"[^a-z0-9]+", "_", …)` là đủ. Tên
workspace là tiếng Việt: `"Sàn Đông Nam"` qua đúng biểu thức đó ra `s_n_ng_nam`.

Fold bằng **stdlib, không thêm dependency**:
```python
import unicodedata
def _bo_dau(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")   # NFD KHÔNG tách đ/Đ
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))
```

Luật, khớp CHECK `^[a-z][a-z0-9_]{1,30}$` (2–31 ký tự):
1. `_bo_dau(name).lower()` → thay mọi `[^a-z0-9]+` bằng `_` → strip `_`.
2. Cắt còn tối đa 31; nếu ký tự đầu không thuộc `[a-z]` thì thêm tiền tố `w_`.
3. Rỗng sau khi fold (tên toàn emoji/CJK) → `"workspace"`.
4. Trùng: hậu tố `_2`…`_50`, **cắt gốc để tổng vẫn ≤ 31**. Hết 50 lần → `_<hex6>`.
   Vòng lặp có trần, không `while True` — một tên lạ không được làm treo request.

**Không đặt vào `core/ten_tai_nguyen.py`.** File đó có luật *"mọi hàm ở đây nhận ĐÚNG
`tenant_id` và không tham số nào khác"* — nó suy tên tài nguyên **từ** `tenant_id`. Hàm
này đi chiều ngược (display name → id) và cần `conn` để tra trùng. Chỗ đúng của nó là
`quan_tri_workspace.py`, cạnh `sinh_user_id`.

## 6. Chuỗi ghi — một transaction

`conn.transaction()` mở ở **tầng router**, không trong service — khuôn `repo.py` đã chốt
(*"caller quyết định giao dịch"*).

| # | Việc | Ghi chú |
|---|---|---|
| 1 | `_lay_owner(conn, actor_id)` | 403 nếu không phải owner. Trả cả hàng vì cần `org_id` |
| 2 | Kiểm trùng tên trong org | `409 WORKSPACE_TRUNG_TEN` |
| 3 | `sinh_tenant_id(conn, name)` | §5 |
| 4 | `INSERT control.tenants (id, name, org_id)` | `lifecycle` mặc định `'active'` |
| 5 | `INSERT control.tenant_verticals (tenant_id, 'realestate')` | Q3 |
| 6 | `nhat_ky.ghi(conn, tenant_id, "workspace.tao", actor_id, {...})` | `ghi()` không `ghi_to_chuc()`: đã có `tenant_id` hợp lệ |

**Bốn bước, KHÔNG có `INSERT memberships`.** Đã xác minh ở `core/auth/repo.py`
(`doc_quyen`): owner **không cần** hàng membership nào.

```sql
EXISTS (SELECT 1 FROM control.tenants t
         WHERE t.id = $2 AND t.org_id = u.org_id)   AS cung_to_chuc
...
if r["org_role"] == "owner" and r["cung_to_chuc"]:
    return HangQuyen(..., ALL_ACTIONS, ...)
```

Hàng `tenants` vừa `INSERT` xong là `cung_to_chuc = true` ⇒ owner có đủ 13 action trên
workspace mới **ngay lập tức**. Docstring của `doc_quyen()` nói thẳng: *"NHÁNH OWNER:
`org_role='owner'` ⇒ đủ 13 action ở MỌI workspace của tổ chức, không cần hàng
memberships."* Và `LEFT JOIN memberships` được giữ có chủ đích — chính để owner không
membership nào vẫn ra hàng.

Thêm membership cho owner sẽ là **hai lỗi**: (a) dư, quyền đã có qua nhánh owner; (b) nó
đòi `memberships.role_id` — 0104 đã **xoá cột `role`** và thay bằng `role_id` FK sang
`control.roles` với composite FK `memberships_role_cung_to_chuc_fkey`. Nghĩa là phải chọn
một vai trò tuỳ ý cho chính người đã có toàn quyền. Không có cơ sở nào để chọn.

Bước 6 sau cùng: `nhat_ky.ghi()` ghi việc **đã xảy ra**.

## 7. Kiểm thử

Khuôn `tests/modules/auth/` (đã có `conftest.py` dựng org/tenant/user).

**Hàm thuần — không cần DB:**
- `sinh_tenant_id` fold dấu: `"Sàn Đông Nam"` → `san_dong_nam`; `"Đất Xanh"` → `dat_xanh`
- cắt 31 ký tự; tên dài + hậu tố `_2` vẫn ≤ 31
- tên toàn emoji → `workspace`; tên bắt đầu bằng số → tiền tố `w_`
- **mọi output khớp `^[a-z][a-z0-9_]{1,30}$`** — property test, vì chính CHECK của DB và
  `create_agent_role()` dựa vào nó

**Tích hợp — cần DB:**
- owner tạo được; `201`; đọc lại thấy `tenants` + `tenant_verticals` + `audit_log`
- **non-owner → 403** (cửa thật, không phải cổng cắm)
- trùng tên trong cùng org → `409`; **trùng tên khác org → `201`**
- `status` trả về là `provisioning`
- rollback: cho bước 5 hoặc 6 hỏng → **không** còn hàng nào ở `tenants`
- **owner mở được workspace mới ngay** (`POST /me/workspace` với id vừa nhận) **dù không
  có hàng `memberships` nào** — đây là test neo lại §6, và là chỗ sẽ đỏ nếu ai đó sau này
  đổi `LEFT JOIN memberships` thành `INNER JOIN` trong `doc_quyen()`
- thành viên **không** phải owner cùng org: **không** thấy workspace mới (không membership,
  không owner ⇒ `doc_quyen` trả actions rỗng)

**Cổng sẵn có phải vẫn xanh:** `test_moi_route_khai_action.py` ·
`test_module_boundaries.py` · `test_isolation_catalog.py`.

## 8. Migration

**Không cần migration.** Cả 4 bảng đã tồn tại. Nếu về sau cần một cái, `down_revision`
phải là **`0104_vai_tro_dong`** (head hiện tại) — số thứ tự trong tên file **không** phản
ánh thứ tự áp dụng: chuỗi thật là `… 0401 → 0102_organizations → 0402 → 0900 → 0103 →
0500 → 0501 → 0104`.

Cần chạy `scripts/gen_contracts.py` để `contracts/openapi.json` có endpoint mới (FE dựng
form từ đó).

## 9. Ngoài phạm vi — cố ý

| Việc | Vì sao tách |
|---|---|
| Cấp phát hạ tầng | Q2. Đã có `POST /agent/...` ở `modules/enrollment` |
| `GET /workspaces`, sửa tên, đình chỉ, xoá | Chưa cần để đóng đường "tạo". Thêm sau, cùng file |
| Publish config v1 tự động | `derive_tenant_status` coi "chưa publish" là bình thường; `GET /config/draft` đã tự trả bộ mặc định qua `payload_mac_dinh(ten_ws)` |
| Đổi `ConfigPayload` theo §4 `spec.md` | Phải bump `SCHEMA_VERSION_HIEN_TAI` → 3. Việc riêng, và bản hiện tại **giàu hơn** spec ở `phong_ban` + `giong` |
| Agent đọc config từ Postgres (§5.3/§8 `spec.md`) | Thay đổi kiến trúc phía agent, quy mô ngang M3. Đánh đổi thật là **tính tái dựng được của prompt đã chạy** — xem `phan-tich-doi-chieu.md` §7.5 |
