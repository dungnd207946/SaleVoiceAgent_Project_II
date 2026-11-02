# Pha 2 — bỏ hẳn `control.deployments`, nhịp tim khoá theo tenant

Ngày: 2026-08-19 · Phạm vi: `odyssey-portal-backend` **+** `odyssey-agent`
Tiếp theo: [Pha 1](2026-08-19-agent-keys-tenant-id-design.md) (`0940`)

## Phát hiện làm đổi khung câu chuyện

**Nhịp tim đã chết hoàn toàn từ `0919` (12-08), không phải từ Pha 1.**

`tenant/pg_heartbeat.py::beat()` chỉ dùng pool tenant khi `cred.kind == self._kind`. `kind`
được parse từ response `/runtime-credentials` (`gateway/credentials.py`) — trường mà `0919`
đã bỏ. Nên `cred.kind` luôn `''`, không bao giờ khớp `'chat'`/`'voice'`, và mọi lượt beat rơi
xuống nhánh fallback `SELECT control.deployments` bằng role `agent_<tenant>` — role chưa bao
giờ có `SELECT` trên bảng đó. Câu lệnh ném, `beat()` nuốt, trả `False`.

Không test nào bắt được vì **mọi bài đều tiêm `read_deployment_id` giả**; đường thật chưa từng
chạy. DB dev khớp: đúng một hàng heartbeat, do `agent_gia` (chạy bằng DSN portal) ghi.

Pha 2 vì thế **hồi sinh** nhịp tim chứ không phá nó.

## Quyết định

| | |
|---|---|
| `control.deployments` | `DROP TABLE` |
| `agent_heartbeats` | PK `(tenant_id, deployment_id)` → `(tenant_id)`, bỏ cột + FK |
| `GET /admin/deployments` | → `GET /admin/tenants`, nguồn hàng `control.tenants` |
| `POST /admin/deployments` | → `POST /admin/tenants/{tenant_id}/provision` |
| `DeploymentIn`/`DeploymentOut` | xoá / → `TenantVanHanhOut` |
| RLS trên `agent_heartbeats` | **cố ý KHÔNG đụng** — xem dưới |
| `kind` trong chuỗi credential agent | dọn luôn — xem dưới |

### Đổi ngữ nghĩa, không phải dọn dẹp thuần

Trước đây hai pod (chat/voice) của cùng tenant có hai `deployment_id` ⇒ HAI hàng nhịp tim.
Giờ chúng ĐÈ lên nhau ⇒ MỘT hàng. Với người đọc thì không đổi — `config/repo.lay_heartbeat`
vốn đã bỏ qua `deployment_id` và lấy `last_seen_at` mới nhất — nhưng bảng mất khả năng phân
biệt pod. Chấp nhận: phân biệt từng pod là việc của màn Vận hành (M7), và nó chưa từng dùng
cột này.

### RLS để nguyên — có chủ ý

`control.agent_heartbeats` đang TẮT RLS hoàn toàn (policy `hb_agent_own_tenant`/`hb_portal_all`
của `0007` bị `0909` xoá, `0913` không bật lại). Đo trên DB dev 2026-08-19:
`relrowsecurity = f`, 0 policy. Đó là món nợ CLAUDE.md đã ghi và là nguyên nhân hai bài đỏ ở
`tests/modules/test_heartbeat.py`.

Bật lại là một quyết định AN NINH với phạm vi riêng, cần migration + spec riêng. Chôn nó trong
một đợt dọn dẹp là làm cả hai việc mờ đi. **Chủ dự án đã chốt để nguyên.**

### `kind` dọn luôn — vì nó chắn ngay chỗ đang sửa

`RuntimeCredentials.kind`, `TenantPgCredential.kind`, header `X-PG-Kind`, khoá `kind` trong
stash Redis — tất cả luôn rỗng kể từ `0919`, và người đọc DUY NHẤT là phép so trong `beat()`
mà Pha 2 đang gỡ. Giữ lại là để một ống dẫn chết nằm giữa đường. `KIND_CHAT`/`KIND_VOICE`
(công thức URL endpoint) **không** đụng tới — chúng suy từ `tenant_id` + domain, không đọc DB.

## Migration `0941_bo_deployments`

```sql
-- 1. Gộp nhịp tim: giữ hàng last_seen_at mới nhất mỗi tenant.
--    PHẢI trước khi bỏ cột — sau đó hai hàng cùng tenant là hai hàng không phân biệt được
--    và ADD PRIMARY KEY vỡ mà không nói được hàng nào đáng giữ.
DELETE FROM control.agent_heartbeats a USING control.agent_heartbeats b
 WHERE a.tenant_id = b.tenant_id
   AND (a.last_seen_at, a.deployment_id) < (b.last_seen_at, b.deployment_id);
-- 2. DROP COLUMN kéo theo CẢ PK ghép LẪN agent_heartbeats_deployment_fkey.
ALTER TABLE control.agent_heartbeats DROP COLUMN deployment_id;
ALTER TABLE control.agent_heartbeats ADD PRIMARY KEY (tenant_id);
-- 3.
DROP TABLE control.deployments;
```

`(last_seen_at, deployment_id)` là tie-break tất định: mốc đến từ `now()` của transaction nên
trùng mốc là chuyện có thật.

**`downgrade` CÓ MẤT MÁT, không tránh được**: hai hàng đã gộp thì không tách lại được (số hiệu
pod mất cùng cột). Nó dựng lại `deployments` với đúng một hàng mỗi tenant có heartbeat và trỏ
nhịp tim vào đó — cấu trúc đúng, dữ liệu không đầy như trước.

## Thi công

**Backend** — `repo`: bỏ `them_deployment`, `liet_ke_deployment` → `liet_ke_tenant_van_hanh`
(nguồn `control.tenants`, LEFT JOIN `agent_keys` để workspace chưa cấp phát vẫn hiện).
`service.cap_phat`: bỏ `them_deployment`, audit payload `{"deployment_id": …}` →
`{"key_id": …}`. `router`: hai endpoint đổi đường dẫn theo bảng trên.

**Agent** — `pg_heartbeat._UPSERT` → `ON CONFLICT (tenant_id)`; `beat()` bỏ nhánh tra
deployment, điều kiện chọn pool còn `tenant_credentials.get(tenant_id) is not None`; xoá
`read_deployment_id` + `_SQL_DEPLOY`; gỡ `deployment_id`/`kind` khỏi `RuntimeCredentials` ·
`TenantPgCredential` · stash Redis · `X-PG-Deployment`/`X-PG-Kind` (`chat_proxy`,
`ws_handler`) · phép đối chiếu `kind` vs `mode` ở `gateway/server.py`.

**Thứ tự triển khai an toàn cả hai chiều.** Portal trước, agent sau: agent bản cũ ghi nhịp tim
thất bại và nuốt lỗi — nó vốn đã thất bại từ `0919`, không tệ hơn. Agent trước, Portal sau:
agent bản mới ghi `ON CONFLICT (tenant_id)` lên bảng chưa migrate sẽ lỗi và cũng bị nuốt.

## Kiểm thử

TDD hai đầu. Backend: `tests/modules/enrollment/test_bo_deployments.py` (6 bài — lược đồ, ngữ
nghĩa gộp, contract). Agent: `tests/unit/tenant/test_pg_heartbeat_writer.py` viết lại (7 bài).

Hai bài canh chính là bài học của đợt này, không phải bài canh tính năng:

- `test_beat_khong_query_bang_nao_ngoai_heartbeat` — `beat()` nuốt mọi exception, nên một câu
  `SELECT` sót lại hỏng IM LẶNG. Đúng kiểu đã giấu cái chết của nhịp tim suốt một tuần.
- `test_khong_con_ham_doc_deployment_id` — bài cũ tiêm `_Conn` giả nên xanh suốt kể cả khi hàm
  thật không chạy được. **Đừng tiêm một lối thoát mà production không có.**

## Kiểm chứng đã chạy

- **Backend full suite**: **7 failed · 1835 passed · 9 errors** — danh sách đỏ **trùng khít
  baseline** (7 failed · 1818 passed · 9 errors, cùng tên). Diff hồi quy rỗng cả hai chiều.
- **Agent** `tests/unit`: 94–95 failed / ~1978 passed, khớp baseline (94 failed / 1981 passed).
  Chênh lệch duy nhất là `tests/unit/test_tool_ack.py` — **flaky theo thời gian**, chứng minh
  bằng ba lượt liên tiếp cho ba tập đỏ KHÁC NHAU (2/3/3 bài), và xanh 6/6 khi chạy riêng; file
  đó không nhắc `deployment`/`heartbeat` dòng nào.
- `ruff check`: backend sạch; agent 200 lỗi trước và sau — không thêm lỗi mới.
- **Migration trên dữ liệu dev thật**: ép ca hai hàng nhịp tim cùng tenant ⇒ gộp còn một, giữ
  đúng hàng `last_seen_at` mới nhất; `deployments` biến mất; PK còn `tenant_id`.
- **Round-trip `upgrade → downgrade → upgrade`**: `deployments` dựng lại, FK trỏ đúng tenant,
  4 khoá nguyên vẹn qua cả ba lượt.

### Sai lầm quy trình đáng ghi

Lượt kiểm chứng ĐẦU chỉ chạy `tests/modules/enrollment` + `tests/isolation` +
`test_control_schema.py` và báo xanh. Full suite sau đó lộ **13 hồi quy** ở bốn file không nằm
trong vùng đó: `tests/modules/test_heartbeat.py` · `tests/modules/config/test_schema.py` ·
`test_repo.py` · `test_agent_gia.py` · `tests/modules/agent_seam/test_dung_chung_db.py`.

Chúng đều `INSERT INTO control.deployments` để dựng dữ liệu, không phải để kiểm deployment —
nên một cuộc grep theo TÊN MODULE bỏ sót hết. Cách đúng: `grep -rn "deployments" tests/` NGAY
sau khi viết migration, trước khi chọn vùng chạy. Đã làm ở lượt hai.

**Lượt quét thứ BA (theo câu hỏi "đã sạch chưa?") còn lộ thêm ba chỗ nữa** — không test nào
chạm nên suite xanh vẫn không chứng minh được:

- `scripts/nap_du_lieu_tu_odyssey.py` — `INSERT INTO control.deployments (tenant_id, kind)`.
  **Đã vỡ từ `0919`** (cột `kind` bỏ 12-08), không ai chạy nên không ai thấy. Bước này bỏ hẳn.
- `scripts/kiem_chung_db_dung_chung.py` — cổng cách ly kỳ vọng `InsufficientPrivilege` trên
  bảng nay đã DROP ⇒ Postgres ném `UndefinedTable`, phép kiểm rơi khỏi tầng quyền. Đúng chế độ
  hỏng mà comment ngay trên vòng lặp đó cảnh báo. Bỏ dòng.
- `scripts/seed_agent.py` — docstring trỏ endpoint cũ.

Cộng bốn docstring/comment mô tả sai ở `ws_handler.py`, `test_credential_stash.py` và
`odyssey-portal-frontend/src/features/platform/api.ts`.

Bài học đầy đủ: **bỏ một bảng thì grep tên bảng trên TOÀN CÂY (src + tests + scripts + FE +
docs), không chỉ vùng có test.** Suite xanh không phủ được script vận hành.

Kiểm chứng bù cho phần không có test: `make seed-agent` (đỏ vì dev DB thiếu tenant `anphu` —
dữ liệu, không phải code) và một lượt gọi `service.cap_phat` THẬT trên tenant có thật ⇒ phát
khoá thành công, `KhoaMoiOut` không còn `deployment_id`, hàng `agent_keys` mang `tenant_id`.

## Nợ để lại

1. **RLS `control.agent_heartbeats`** — cần migration + spec riêng. Hai bài
   `tests/modules/test_heartbeat.py` sẽ còn đỏ tới lúc đó.
2. **`scripts/e2e_dbmode/portal_sim.sql`** — phần `control.deployments` đã dọn, nhưng file vẫn
   dựng schema `agent_api` mà `0917` đã xoá. Chưa viết lại vì nó đòi chốt lại sim đó còn mô
   phỏng cái gì; đã đặt banner cảnh báo ở đầu file.
3. **`docs/contracts/agent-postgres-read-contract.md` §1** — đặc tả `agent_api`, lỗi thời từ
   `0917`. Đã đặt banner; §2 (heartbeat) đã cập nhật theo `0941`.
