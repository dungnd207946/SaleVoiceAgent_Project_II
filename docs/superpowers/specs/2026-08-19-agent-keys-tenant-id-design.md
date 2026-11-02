# `agent_keys` treo thẳng vào tenant — bỏ tầng trung gian `deployment_id`

Ngày: 2026-08-19 · Phạm vi: **Pha 1** (chỉ `odyssey-portal-backend`)

## Vấn đề

`control.agent_keys.deployment_id` (từ `0900`) là đường DUY NHẤT để một hàng khoá
biết mình thuộc tenant nào. Mô hình lúc đó: 1 tenant → N pod (`kind` chat/voice,
mỗi pod một `endpoint`) → mỗi pod bộ khoá riêng. Khoá gắn vào **pod**, không gắn
vào tenant.

Ba việc đã làm mô hình đó rỗng nghĩa:

| Migration | Hệ quả |
|---|---|
| `0917` | `DROP SCHEMA agent_api` — view `tenant_keys` (nơi lập luận "JOIN chứ không thêm cột" của `0907:132` được viết ra) không còn tồn tại |
| `0919` | bỏ cột `kind` — "một khoá dùng chung cho cả chat lẫn voice" |
| — | `service.phat_khoa_cho_tenant` tự cấp phát deployment nếu chưa có, và `repo.deployment_cua_tenant` luôn lấy hàng cũ nhất ⇒ thực tế **1 tenant = 1 deployment** |

`control.deployments` hôm nay còn `id, tenant_id, endpoint, provisioned_at`.
`endpoint` mặc định `''` và **không đường code nào ghi vào** — chỉ được `SELECT`
ra ở màn admin (`repo.liet_ke_deployment`).

### Lỗi tiềm ẩn mà tầng trung gian đang giữ

DB **không cấm** >1 deployment cho một tenant (`0906` ghi rõ là cố ý không thêm
unique index). Khi điều đó xảy ra:

- `repo.deployment_cua_tenant` lấy hàng **cũ nhất** (`ORDER BY id LIMIT 1`) → khoá treo vào deployment cũ
- Hợp đồng agent (`0906` §1.4) bảo agent chọn **id lớn nhất** → heartbeat treo vào deployment mới

Hai bên trỏ hai hàng khác nhau, không có lỗi nào phát ra.

### Reader duy nhất đã bỏ qua nó

`modules/config/repo.py:212` đọc heartbeat bằng
`WHERE tenant_id = $1 ORDER BY last_seen_at DESC LIMIT 1` — `deployment_id` không
xuất hiện.

## Quyết định

Thay `agent_keys.deployment_id` bằng `agent_keys.tenant_id`. Không phải *thêm*
cột — nên không sinh ra nguồn sự thật thứ hai, và lập luận của `0907:132` không
áp dụng.

`control.deployments` tụt xuống thành bảng **chỉ admin nền tảng ghi, chỉ admin
nền tảng đọc**. Không đường nào khác chạm nó. Pha 2 vì thế là xoá thuần.

### Cắt hai pha

Pha 1 (spec này) không đụng `odyssey-agent` về mặt *bắt buộc*. Pha 2 — `DROP TABLE
deployments` + rekey `agent_heartbeats` theo `tenant_id` — cần sửa repo agent
trước, và có spec riêng.

Nhưng Pha 1 **có** một breaking change contract, cố ý và đã chốt: bỏ
`deployment_id` khỏi response `/runtime-credentials`.

## Bỏ `deployment_id` khỏi contract — hệ quả đã lường

Agent nhận `deployment_id` là `int | None` ở **mọi** chỗ, không đường nào assert
nó có giá trị:

- `gateway/credentials.py:60` — `data.get("deployment_id")`, `None` nếu vắng
- `gateway/chat_proxy.py:32` — `if ... is not None` mới set header `X-PG-Deployment`
- `server/ws_handler.py:91` — `None` khi parse hỏng
- `storage/tenant_credentials.py:21`, `storage/credential_stash.py:115` — mặc định `None`

`tenant/pg_heartbeat.py::beat()` fail-soft hai lớp:

```python
if dep is None:
    logger.debug("heartbeat: no %s deployment for %s — skip", ...); return False
...
except Exception:
    logger.warning("heartbeat: pg beat failed for %s", ...); return False
```

**Nên: agent không crash.** Hệ quả duy nhất là heartbeat ngừng ghi.

Ghi chú: nhánh fallback `read_deployment_id` (`storage/agent_control_store.py:14`,
`SELECT id FROM control.deployments`) **đã hỏng sẵn từ trước spec này** — role
`agent_<tenant>` không có `SELECT` trên `control.deployments` (chính docstring của
`beat()` ghi vậy), và view `agent_api.deployments` bị `0917` xoá cùng cả schema.
Đây là suy từ code, chưa đối chiếu dữ liệu thật.

**Hệ quả người dùng thấy được:** heartbeat ngừng ghi ⇒ sau `HEARTBEAT_STALE_AFTER`,
`core/tenant_status.py:51` trả `DISCONNECTED` và Portal hiển thị workspace là
«Mất kết nối». Đây là **nhãn hiển thị**, KHÔNG phải cổng phục vụ — cổng phục vụ
là `lifecycle = 'active'` (`0907` ghi rõ). Chat/voice không bị chặn.

Chủ dự án đã chốt chấp nhận, và sẽ sửa `odyssey-agent` để bỏ hẳn khái niệm
deployment.

## Thi công

### Migration `0940_agent_keys_tenant_id`

`down_revision = "0939_conversations_agent_key_id"` (head hiện tại, duy nhất).

```sql
ALTER TABLE control.agent_keys ADD COLUMN tenant_id text
    REFERENCES control.tenants(id) ON DELETE CASCADE;

UPDATE control.agent_keys k SET tenant_id = d.tenant_id
  FROM control.deployments d WHERE d.id = k.deployment_id;

ALTER TABLE control.agent_keys ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE control.agent_keys DROP COLUMN deployment_id;
CREATE INDEX agent_keys_tenant_idx ON control.agent_keys (tenant_id);
```

- `DROP COLUMN` tự xoá `agent_keys_deployment_idx` — không cần câu `DROP INDEX` riêng.
- `ON DELETE CASCADE` giữ đúng ngữ nghĩa cũ: trước đây xoá tenant → cascade qua
  `deployments` → cascade tới khoá. Giờ một chặng thay vì hai.
- Grants không đổi: thêm/bớt cột không đụng `GRANT ... ON control.agent_keys TO portal_api`.

`downgrade` phải **dựng lại hàng `deployments` cho tenant nào chưa có**, nếu không
`SET NOT NULL` trên `deployment_id` vỡ:

```sql
ALTER TABLE control.agent_keys ADD COLUMN deployment_id bigint
    REFERENCES control.deployments(id) ON DELETE CASCADE;

INSERT INTO control.deployments (tenant_id)
SELECT DISTINCT k.tenant_id FROM control.agent_keys k
 WHERE NOT EXISTS (SELECT 1 FROM control.deployments d WHERE d.tenant_id = k.tenant_id);

UPDATE control.agent_keys k SET deployment_id = (
    SELECT d.id FROM control.deployments d WHERE d.tenant_id = k.tenant_id ORDER BY d.id LIMIT 1);

ALTER TABLE control.agent_keys ALTER COLUMN deployment_id SET NOT NULL;
ALTER TABLE control.agent_keys DROP COLUMN tenant_id;
CREATE INDEX agent_keys_deployment_idx ON control.agent_keys (deployment_id);
```

`ORDER BY d.id LIMIT 1` khớp với `deployment_cua_tenant` cũ (hàng cũ nhất).

### `modules/enrollment/repo.py`

Bỏ hẳn:
- `tenant_cua_deployment` — không còn ai gọi
- `deployment_cua_tenant` — thay bằng `tenant_da_co_khoa` (dưới)

Giữ nguyên: `them_deployment` (đường admin `cap_phat` vẫn tạo hàng deployment để
`GET /admin/deployments` còn dữ liệu).

Ba câu JOIN thành query một bảng:

| Hàm | Thay đổi |
|---|---|
| `liet_ke_khoa_cua_tenant` (~:82) | bỏ `JOIN control.deployments`, `WHERE k.tenant_id = $1` |
| `tra_khoa` (~:103) | bỏ JOIN, `SELECT k.id, k.tenant_id`, trả `KhoaHopLe(tenant_id, key_id)` |
| `tenant_cua_khoa` (~:173) | `SELECT tenant_id FROM control.agent_keys WHERE id = $1` |

Đổi chữ ký:
- `them_khoa(conn, tenant_id: str, sha, api_key, prefix, label, boi)` — INSERT cột `tenant_id`
- `liet_ke_deployment` — `LEFT JOIN control.agent_keys k ON k.tenant_id = d.tenant_id`

Thêm:
```python
async def tenant_da_co_khoa(conn: Conn, tenant_id: str) -> bool:
    """Tenant đã từng được cấp phát chưa. Thay `deployment_cua_tenant` ở đường
    owner tự phát khoá.

    VÌ SAO ĐẾM KHOÁ CHỨ KHÔNG ĐẾM `agent_credentials`: `doc_version()` tạo hàng
    `agent_credentials` NGAY LÚC ĐỌC (INSERT ... ON CONFLICT), nên sự tồn tại của
    hàng đó không phân biệt được "đã cấp phát" với "vừa có ai gọi /runtime-credentials".
    Khoá thì không bao giờ bị DELETE — chỉ đặt `revoked_at` — nên EXISTS trên
    `agent_keys` là dấu vết bền của "tenant này đã đi qua cap_phat".
    """
```

### `modules/enrollment/service.py`

| Chỗ | Thay đổi |
|---|---|
| `KhoaHopLe` (contracts) | bỏ field `deployment_id` |
| `cap_phat` (~:58) | bỏ `dep_id = ...them_deployment(...)` khỏi lời gọi `_phat_khoa`; VẪN gọi `them_deployment` để giữ hàng cho màn admin; audit `{"deployment_id": dep_id, "kho_tep": …}` giữ nguyên (đây là đường admin, id đó vẫn thật) |
| `phat_khoa_them` | `(pool, tenant_id: str, boi, label="")`; kiểm tenant tồn tại bằng `repo.lifecycle_tenant` → `None` thì `loi.khong_co_tenant(tenant_id)` |
| `_phat_khoa` | bỏ tham số `deployment_id`; `repo.them_khoa(pool, tenant_id, …)`; trả `KhoaMoiOut` không có `deployment_id` |
| `phat_khoa_cho_tenant` (~:116) | `if not await repo.tenant_da_co_khoa(...)` → `cap_phat`, ngược lại `_phat_khoa` |
| `runtime_credentials` (~:179, ~:188) | bỏ `deployment_id` khỏi audit payload **và** khỏi `RuntimeCredentialsOut` |

### `modules/enrollment/loi.py`

`khong_co_deployment(deployment_id: int)` → `khong_co_tenant(tenant_id: str)`.
Giữ nguyên HTTP status và cấu trúc `LoiPortal` cũ.

### `modules/enrollment/contracts.py`

- `KhoaMoiOut`: bỏ `deployment_id` (~:143)
- `RuntimeCredentialsOut`: bỏ `deployment_id` (~:90) + cập nhật docstring ~:94
- `KhoaHopLe`: bỏ `deployment_id`
- `DeploymentOut`: **giữ nguyên** — Pha 2 mới bỏ

### `modules/enrollment/router.py`

```
POST /admin/deployments/{deployment_id}/keys   →   POST /admin/tenants/{tenant_id}/keys
```
`tenant_id: str = Path(pattern=TENANT_ID_PATTERN)`. Hai endpoint `/admin/deployments`
còn lại (`POST` cấp phát, `GET` liệt kê) giữ nguyên đường dẫn.

Frontend **không gọi** endpoint `/admin/*` nào — chỉ `/agent/keys`
(`features/platform/api.ts:53`). Đổi URL này an toàn.

### `scripts/seed_agent.py`

Dòng ~48: bỏ `khoa.deployment_id` khỏi câu print, còn `workspace {TENANT_DEMO}`.

## Kiểm thử

TDD: viết test đỏ trước cho `tra_khoa` / `liet_ke_khoa_cua_tenant` theo `tenant_id`,
rồi mới sửa implementation.

Phải cập nhật:
- `tests/modules/enrollment/test_runtime_credentials.py`
- `tests/modules/enrollment/test_router_tenant.py`
- `tests/integration/test_control_schema.py`
- `tests/isolation/test_isolation_catalog.py`
- `tests/modules/ingest/test_token.py`
- `scripts/kiem_chung_db_dung_chung.py`

Ca phải có:
1. Backfill đúng — khoá cũ giữ đúng tenant sau `upgrade`
2. `upgrade` → `downgrade` → `upgrade` không mất khoá nào
3. `tra_khoa` trả đúng tenant cho khoá còn sống, `None` cho khoá đã thu hồi
4. `dat_trang_thai_khoa_cua_tenant` vẫn 404 khi khoá thuộc workspace khác
5. `/runtime-credentials` response **không còn** field `deployment_id`
6. `phat_khoa_cho_tenant` gọi hai lần liên tiếp → lần hai không chạy lại hạ tầng

⚠️ Suite backend **đã đỏ sẵn** (~6 failed + 126 errors do `org_id`). Chụp baseline
`pytest` TRƯỚC khi sửa, so sánh sau, để phân biệt hồi quy với nền đỏ có sẵn.

## Ngoài phạm vi Pha 1

Để lại cho spec Pha 2, sau khi `odyssey-agent` bỏ xong khái niệm deployment:

- `DROP TABLE control.deployments`
- `control.agent_heartbeats`: PK `(tenant_id, deployment_id)` → `tenant_id`, bỏ cột `deployment_id`, bỏ FK
- Bỏ `POST /admin/deployments`, `GET /admin/deployments`, `service.liet_ke_deployment`, `repo.them_deployment`, `repo.liet_ke_deployment`, `contracts.DeploymentOut` / `DeploymentIn`
- Cập nhật `docs/handoff/agent-postgres-read-contract.md` §1.4

---

## Thi công thực tế — những chỗ lệch spec

Spec viết trước khi chạm code. Năm thứ phát sinh lúc thi công, ghi lại để người
đọc sau không tưởng là bỏ sót:

1. **`tests/isolation/test_isolation_catalog.py` phải khai `agent_keys`.** Cổng
   "bảng `control` mang cột `tenant_id` phải được khai báo kèm lý do" bắt đúng
   migration này — đó là việc của nó. Đã khai kèm lập luận (đường đọc nóng là
   `tra_khoa(key_sha256)`, không phải liệt kê theo tenant; đường liệt kê chỉ mở
   sau `require(WORKSPACE_ADMIN)` với tenant lấy từ phiên).

2. **`tests/modules/enrollment/conftest.py` phải xoá `agent_keys` tường minh.**
   Fixture `hai_tenant` xoá `deployments`, và trước `0940` câu đó cuốn theo khoá
   bằng cascade. Giờ không còn — thiếu dòng này thì khoá tích luỹ qua các test
   trên cùng container `pg_dsn` scope session.

3. **`scripts/agent_gia.py`** đọc `d["deployment_id"]` và ghi heartbeat. Đổi sang
   `d.get(...)` + bỏ nhịp khi `None`, khớp chính xác agent thật — một agent giả
   bắt buộc field mà agent thật coi là tuỳ chọn thì không còn mô phỏng đúng.

4. **Audit payload `agent.runtime_credentials`** đổi từ `{"deployment_id": …}`
   sang `{"agent_key_id": …}`. Bỏ field mà không thay là để lại một dòng nhật ký
   không truy được về đâu.

5. **`loi.khong_co_deployment(int)` → `loi.khong_co_tenant(str)`**, kèm test 422
   cho path param sai định dạng — không có nó thì test 404 xanh vì dừng ở
   validation, không phải vì tìm không thấy workspace.

## Kiểm chứng đã chạy

- **Full suite**: 7 failed · 1828 passed · 9 errors — **trùng khít baseline**
  (7 failed · 1818 passed · 9 errors, cùng danh sách tên). +10 test mới.
- **Migration trên dữ liệu thật** (DB dev `portal`, 4 khoá): backfill đúng tenant,
  không khoá nào mồ côi.
- **Round-trip `upgrade → downgrade → upgrade`**: không mất khoá, tenant khớp
  chính xác trước/sau.
- **Nhánh `INSERT` bù của `downgrade`**: ép ca tenant có khoá mà không có
  deployment ⇒ `downgrade` tự dựng hàng bù, cả hai khoá bám vào đó, `SET NOT NULL`
  không vỡ.
- `ruff check` + `ruff format --check`: sạch.
