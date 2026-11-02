> ⚠ **ĐÃ BỊ THAY THẾ 2026-08-15** bởi
> `odyssey-portal-backend/docs/superpowers/specs/2026-08-15-bo-organization-design.md`.
> Tầng tổ chức mô tả ở đây đã bị gỡ khỏi hệ thống (migration `0105`/`0106`).
> Giữ lại làm hồ sơ vì sao nó từng tồn tại — **đừng thi công theo**.

# Thiết kế: Cấp Organization trên Tenant

> Ngày: 2026-08-03 · Branch: `feat/share-agent` · Trạng thái: chờ duyệt
> Bối cảnh DB: `docs/api/SPEC-DB-HIEN-TAI.md` (Odyssey Portal backend, head `0900_enrollment`).

## 1. Vấn đề

Dữ liệu đang được phân quyền một cấp: **tenant**. Nay thêm một cấp cao hơn:
**organization**. Một org tạo được nhiều tenant. Cụ thể phải đổi:

1. **MinIO tenant store**: các bundle tenant hiện nằm phẳng cùng cấp (`<tenant_id>/...`);
   phải gom theo org → `<org_id>/<tenant_id>/...`.
2. **Định danh tenant**: người dùng nhập tên tùy ý, hệ thống tự sinh một `tenant_id`
   duy nhất toàn cục có mang org.
3. Org phải khả dụng ở runtime để định vị store, đóng heartbeat, log/guard.

## 2. Quyết định nền tảng (đã chốt với người dùng)

| # | Quyết định | Hệ quả |
|---|---|---|
| D1 | `tenant_id` **duy nhất toàn cục** (như `control.tenants.id` là PK toàn cục trong spec Portal). | Org luôn suy ra được từ tenant; không cần mọi carrier mang cả 2 để định danh. |
| D2 | `org_id` = `org_<rand>` — `<rand>` là alphanumeric **cố định, KHÔNG chứa `_`** (mặc định 8 ký tự hex). Sinh khi tạo org. | Org là một chuỗi opaque, duy nhất. |
| D3 | `tenant_id` = `<org_id>_<slug>` = `org_<rand>_<slug>`. `<slug>` = slug hoá tên người dùng nhập (được phép chứa `_`). | tenant_id mang org ở prefix, duy nhất toàn cục nhờ `org_<rand>`. |
| D4 | `current_org(tenant_id)` = **parse prefix thuần** = `"org_" + tenant_id.split("_", 2)[1]`. Không I/O, không list-map, không index. | Rẻ, không phụ thuộc network; đúng vì tenant_id đã mang org. |
| D5 | **Postgres data path KHÔNG đụng.** Portal sở hữu DDL `tenant_data` (không có cột `org_id`); RLS giữ theo tenant. tenant_id toàn cục đã đủ cách ly (mỗi request đúng 1 tenant → đúng 1 org). | Không đổi `tenant_conn`, không thêm GUC `app.current_org`, không sửa file SQL. |
| D6 | Org **không** đi trong request boundary (LiveKit metadata / `X-Tenant-Id` header / body). Mọi boundary giữ nguyên chỉ-tenant. Chỗ nào cần org tự parse từ tenant. | Không đụng gateway/worker/app_session/ws ở phần định danh. |
| D7 | Code **chỉ hỗ trợ format mới**, không nhánh legacy. Tenant cũ (`noble`, `acme`, `du_test`) được migrate/re-provision sang format mới trước khi chạy. | `org_of()` fail-loud khi gặp id sai format. |

## 3. Phạm vi thực tế

Vì D1 + D5 + D6, "thêm cấp org" trong repo này quy về **3 vùng**:

- **A. Định danh org** (mới, nhỏ): parse/generate id + contextvar org.
- **B. MinIO store reorg** (vùng chính): mọi object key `<tenant>/...` → `<org>/<tenant>/...`.
- **C. Provisioning + CLI**: sinh id theo format mới, quản lý org, tool migrate.

Postgres, gateway, worker, app_session, ws_handler, facade **giữ nguyên** (chỉ dùng
`tenant_id` toàn cục như hiện tại).

## 4. Thiết kế chi tiết

### 4.A — Định danh org (`tenant/identity.py`, mới)

Một module thuần (không I/O) là nguồn sự thật cho format id:

```python
_ORG_RE     = re.compile(r"^org_[a-z0-9]{6,32}$")
_TENANT_RE  = re.compile(r"^org_[a-z0-9]{6,32}_[a-z0-9][a-z0-9_-]{0,62}$")

def new_org_id(*, rand: str) -> str            # f"org_{rand}"  (rand: [a-z0-9], no '_')
def slugify(name: str) -> str                  # tên user → [a-z0-9_-], gộp khoảng trắng
def new_tenant_id(org_id, name) -> str
        # f"{org_id}_{slugify(name)}"  — id sạch, tất định, KHÔNG hậu tố ngẫu nhiên
def org_of(tenant_id: str) -> str
        # parse prefix; raise ValueError nếu không khớp _TENANT_RE
def is_valid_org_id(s) -> bool
def is_valid_tenant_id(s) -> bool
```

- `rand` **được inject** (mặc định `secrets.token_hex(4)`) để test tất định.
- `org_of` là hàm được store + `current_org()` gọi. Fail-loud (D7).
- **Chống trùng slug trong 1 org**: hai tenant cùng org, cùng tên hiển thị → cùng slug →
  cùng tenant_id. Giải (cập nhật 2026-08-04 — Phương án 2): **KHÔNG** thêm hậu tố ngẫu
  nhiên; `tenant_id = org_<rand8>_<slug>` (id sạch). Tính duy nhất trong org do
  `provision_tenant` **bắt buộc tên hiển thị unique/org**: id tất định → nếu id đã tồn tại
  thì raise "tên đã dùng trong org này". (Dashboard đã enforce unique tên/org ở tầng trên;
  guard này là lưới an toàn.) `org_of` chỉ đọc 2 segment đầu nên không đổi.

### 4.B — Contextvar org (`tenant/current.py`)

Thêm, song song tenant, **suy ra chứ không lưu độc lập**:

```python
def current_org() -> str:
    return org_of(current_tenant())
```

Không thêm `set_current_org`/`use_org` (org luôn đi kèm tenant; set tenant là đủ).

### 4.C — `TenantContext` + `TenantMeta` (`context.py`, `store.py`)

- `TenantContext`: thêm `org_id: str` (parse tại `_context_from_dir`).
- `TenantMeta`: thêm `org_id: str` (đọc/ghi trong `_meta.json`, và trong `manifest.toml`
  dưới `[org] id = "..."` để làm nguồn khai báo). `org_id` trong meta phải khớp
  `org_of(tenant_id)` — mismatch = fail-loud lúc load (bắt lỗi provisioning sai).

### 4.D — MinIO store reorg (`tenant/store.py`)

Nguyên tắc: **API công khai của `MinioTenantStore` KHÔNG đổi** (mọi method vẫn nhận
`tenant_id`). Chỉ nội bộ đổi cách dựng key.

- Helper mới `_prefix(tenant_id) -> str` = `f"{org_of(tenant_id)}/{tenant_id}"`.
  Mọi key hiện `f"{tenant_id}/..."` đổi thành `f"{_prefix(tenant_id)}/..."`.
  Các hằng `_MANIFEST/_META/_CREDS/_POINTER/_HEARTBEAT/_VERSION/_VERSIONS_DIR/_DRAFT_DIR`
  giữ nguyên; chỉ prefix đổi.
- `list_ids()` → **scan 2 cấp**: LIST `Delimiter="/"` ở root ra các `<org>/`, rồi LIST
  trong mỗi org ra `<org>/<tenant>/`. Trả về `sorted(tenant_id)` (giữ nguyên kiểu trả
  về để heartbeat supervisor không đổi). org của mỗi tenant lấy trực tiếp từ path.
  - (Không cần map tenant→org — path đã mang cả hai.)
- `FakeTenantStore`: cập nhật để phản ánh cùng layout 2 cấp (hoặc giữ key nội bộ theo
  tenant nhưng expose `list_ids` giống thật — chọn cho khớp hành vi test isolation).
- **Không** giữ nhánh đọc back-compat `<tenant>/` (D7). Migration chạy trước.

### 4.E — Materialize + version_resolver (local dir)

- Thư mục materialize **cục bộ** (`dest_root/<tenant_id>/`) **giữ phẳng theo tenant_id**
  (đã duy nhất toàn cục) — không lồng org, giảm churn. `materialize_tenant`,
  `materialize_version` chỉ đổi ở phần đọc-từ-store (đã org-aware qua store), không đổi
  đường ghi cục bộ.

### 4.F — Heartbeat (`tenant/heartbeat.py`)

- `write_heartbeat`/`read_heartbeat` đi qua store → tự org-nested. Không đổi.
- `HeartbeatSupervisor._active_tenants()` dùng `store.list_ids()` (đã 2 cấp). Không đổi
  logic; chỉ hưởng lợi từ list_ids mới.

### 4.G — Provisioning + CLI (`provisioning.py`, `cli.py`)

- **Org lifecycle (mới, nhẹ)**: org không có bundle riêng — nó chỉ là namespace + record.
  Lựa chọn: lưu một record org tối thiểu tại `<org_id>/_org.json`
  (`{id, name, created_at, lifecycle}`) để `list-orgs` liệt kê được. (Đủ cho nhu cầu
  hiện tại; không dựng bảng control — đó là việc Portal.)
  - `create_org(store, name, *, rand=None) -> org_id`
  - `list_orgs(store) -> list[...]`
- `create_tenant(store, *, org_id, name, ...)`:
  - đổi chữ ký: nhận `org_id` + `name` (thay `tenant_id` trực tiếp).
  - sinh `tenant_id = new_tenant_id(org_id, name)`; validate org_id tồn tại
    (`<org_id>/_org.json` có mặt); ghi `org_id` vào meta+manifest; ghi bundle vào
    `<org>/<tenant>/`.
- `list_tenants(store, *, org_id=None)`: lọc theo org khi có.
- CLI:
  - `noble-tenant create-org --name "..."` → in ra org_id.
  - `noble-tenant list-orgs`.
  - `noble-tenant create --org <org_id> --name "..."` (bỏ tham số id trực tiếp) → in tenant_id.
  - `noble-tenant list [--org <org_id>]`.
  - `noble-tenant migrate-org-layout` (xem §5).
  - Guard trùng `POSTGRES_APP_ROLE` giữ nguyên (kiểm trên tenant_id sinh ra).

### 4.H — Validation (`tenant/validation.py`)

- `SLUG_RE` hiện dùng cho tenant_id → tách vai: thêm `is_valid_tenant_id`/`is_valid_org_id`
  từ `identity.py`. `validate_bundle` kiểm `org_of(tenant_id)` khớp `[org].id` trong manifest.

### 4.I — Loader + gateway registry

- `loader._resolve_tenant_dir`: đọc store (đã org-aware); materialize cục bộ theo tenant_id.
  `_context_from_dir` parse `org_id`.
- `gateway/registry.py`: `read_meta`/`read_creds_raw`/`is_active` đi qua store (org-aware nội
  bộ) — chữ ký không đổi.

## 5. Migration tenant cũ → format mới

Tenant cũ (`noble`, `acme`, `du_test`) không theo format mới. Chuẩn hoá:

1. **Tạo org mặc định**: `create_org(name="Noble")` → `org_<rand>` (gọi là `ORG0`).
2. **MinIO (repo này lo)**: `noble-tenant migrate-org-layout --org ORG0` — với mỗi tenant
   cũ ở root: sinh `tenant_id` mới = `new_tenant_id(ORG0, <tên cũ>)`, copy bundle
   `<old>/...` → `<ORG0>/<new_id>/...`, chèn `org_id` vào meta+manifest, xoá key cũ. In
   bảng `old_id → new_id`.
3. **Postgres (Portal sở hữu — bước phối hợp/ops, NGOÀI code repo này)**: dữ liệu test
   hiện đều dưới tenant `noble`. Hai đường:
   - Re-provision + re-seed dev tenant dưới id mới (khuyến nghị cho dev/test); hoặc
   - Rename `tenant_id` trong `tenant_data.*` bằng admin/superuser (bypass RLS) + đổi role
     `agent_<tenant>` tương ứng — **phối hợp Portal**, vì Portal sở hữu role/DDL.
   Spec này **không** tự chạy rename PG; chỉ tài liệu hoá + cung cấp bảng ánh xạ từ bước 2.
4. **Cấu hình live**: cập nhật `.env` `TENANT_ID=<new_id>` và mọi tham chiếu test.

> ⚠️ Rủi ro: đổi tên tenant chạm dữ liệu Portal-owned; phần PG phải phối hợp Portal.
> Repo này chỉ đảm bảo code + MinIO + tool ánh xạ. Trước khi bật code mới trên môi
> trường có dữ liệu thật, migration MinIO + PG phải hoàn tất (D7: không có fallback legacy).

## 6. Kiểm thử

- **identity**: `new_org_id`/`new_tenant_id`/`org_of` round-trip; `org_of` fail-loud id sai;
  slug hoá tên có dấu/khoảng trắng; guard tên trùng cùng org (raise); id tất định.
- **store 2 cấp**: write→read→list qua `MinioTenantStore` (dùng `FakeTenantStore`/mock boto3):
  bundle/meta/creds/pointer/versions/draft/heartbeat đều ở `<org>/<tenant>/`; `list_ids`
  trả đúng tập tenant khắp nhiều org.
- **current_org**: resolve đúng từ contextvar tenant.
- **heartbeat supervisor**: enumerate nhiều org × nhiều tenant.
- **isolation gate** (mở rộng `test_deglobalize_isolation.py`): 2 org, mỗi org 1 tenant có
  **cùng tên hiển thị** → tenant_id khác nhau, bundle/context/org không lẫn khi interleave
  trong 1 process.
- **provisioning**: `create_org`→`create_tenant` sinh id đúng format, org_id khớp meta;
  `migrate-org-layout` copy đúng + xoá cũ + in ánh xạ (test trên fake store).
- **regression**: Postgres/gateway/worker/app_session không đổi hành vi (byte-identical path).

## 7. Không làm (YAGNI)

- Không thêm cột `org_id` / GUC `app.current_org` / policy vào SQL (D5).
- Không mang org trong LiveKit metadata / header / body (D6).
- Không dựng bảng `control.organizations` trong repo này (Portal sở hữu control-plane);
  chỉ giữ record org tối thiểu trong MinIO để store tự quản namespace.
- Không giữ nhánh đọc legacy trong store (D7).
- Không lồng org vào thư mục materialize cục bộ (tenant_id đã đủ duy nhất).
