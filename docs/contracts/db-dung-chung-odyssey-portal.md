# DB dùng chung `odyssey_portal` — bàn giao

> Trạng thái: **ĐÃ DỰNG VÀ ĐÃ NẠP DỮ LIỆU.** Ngày 2026-08-04.
> Khảo sát dẫn tới quyết định: `danh-gia-dung-chung-db.md`. Hợp đồng agent:
> `agent-postgres-read-contract.md`.
> **Database `odyssey` của team agent KHÔNG bị chạm** — mọi truy cập vào nó là `SELECT`.

## 1. Kết nối

Cùng cluster `10.50.13.220:5433` (= `thebc-server.local`, container `odyssey-postgres`,
**PostgreSQL 16.14**). Postgres bind `127.0.0.1` nên từ ngoài phải qua SSH:

```bash
ssh -f -N -L 15433:127.0.0.1:5433 thebc@thebc-server.local
```

| Vai | Role | Biến môi trường | Database |
|---|---|---|---|
| Chạy migration | `portal_migrator` | `MIGRATOR_URL` | `odyssey_portal` |
| API + worker Portal | `portal_api` | `DATABASE_URL` | `odyssey_portal` |
| Pod agent | `odyssey_agent` | `POSTGRES_DSN` phía họ | `odyssey_portal` |

**Phía agent đổi đúng một chỗ:** `/odyssey` → `/odyssey_portal`. User, mật khẩu, host, cổng
giữ nguyên.

⚠️ **Mật khẩu `portal_migrator` và `portal_api` đang nằm ở file scratchpad của phiên làm việc**
(`bi_mat_odyssey_portal.txt`, chmod 600). Chuyển vào secret store rồi xoá file. Cả hai role đọc
được mọi tenant.

⚠️ **`odyssey_agent_pw` phải coi như đã lộ** — nó đã đi qua chat và nằm trong file env chuyền
tay giữa hai team, mà role đó đọc được config + catalog của **mọi** tenant. Xoay trước khi có
dữ liệu khách thật.

## 2. Có gì trong DB

```
odyssey_portal  (owner: portal_migrator, non-superuser — deploy/README.md §1)
├── control      20 bảng/view   — control plane (tenants · users · config · deployments · …)
├── tenant_data  10 bảng        — dữ liệu tenant, MỌI bảng đã RLS + FORCE RLS
├── agent_api     6 view        — cửa đọc DUY NHẤT của agent
└── portal                      — portal.current_tenant()
```

`agent_api`: `units` · `projects` · `zones` · `documents` · `media` ·
**`agent_published_config`** · **`deployments`**.

alembic head: `0906_view_deployments`.

### Dữ liệu đã nạp

| tenant (đích) | units | projects | contacts | conversations | appointments | config |
|---|---|---|---|---|---|---|
| `noble` | 603 | 41 | 4 | 9 | 147 | v1 (đang publish) |
| `acme` | 603 | 41 | 1 | 2 | – | – |
| `du_test` | 603 | 41 | 1 | – | – | – |
| `legacy_unassigned` | 603 | 41 | – | – | – | – |
| `org_f1d72eac_demo_sales_5d74` | 603 | 41 | – | – | – | – |

`zones` · `documents` · `media` = 0 hàng ở cả nguồn và đích.
Mỗi tenant có 1 `control.deployments` row `kind='chat'`.

**Hai tenant đổi tên** (CHECK `^[a-z][a-z0-9_]{1,30}$` của `control.tenants.id`):

| nguồn | đích | vì sao |
|---|---|---|
| `''` (chuỗi rỗng) | `legacy_unassigned` | chuỗi rỗng không là tenant id hợp lệ |
| `org_f1d72eac_demo-sales_5d74` | `org_f1d72eac_demo_sales_5d74` | dấu `-` không qua CHECK |

## 3. Sáu migration mới

| # | Làm gì | Vì sao |
|---|---|---|
| `0901` | role `odyssey_agent` + `GRANT agent_all` + `search_path` | role dùng chung của agent; **idempotent** vì role đã có sẵn trên cluster |
| `0902` | `units.zone_code` bỏ NOT NULL | 3015/3015 hàng nguồn NULL và `zones` rỗng ⇒ 0 hàng nạp được. Theo tiền lệ `media.zone_code` |
| `0903` | 3 bảng `contacts` · `conversations` · `appointments` | agent đang ghi chúng, Portal chưa có chỗ chứa (`dau-noi-agent.md` G-6) |
| `0904` | `control.config_live` + view `agent_published_config` | con trỏ LIVE của Portal ở kho tệp nên agent đọc Postgres không thấy |
| `0905` | `grant_agent_write()` cấp cả USAGE trên sequence | **lỗi thật**: thiếu nó thì agent không INSERT nổi bảng có `bigserial` |
| `0906` | view `agent_api.deployments` | agent cần `deployment_id` mới ghi được heartbeat (FK) |

Mỗi migration có header ghi lý do và đánh đổi. Ba chỗ đáng đọc trước khi sửa:

- **`0904` là quyết định một chiều.** Kể từ nó, `control.config_live` là **sự thật duy nhất**
  về bản đang chạy, và object `LIVE` trên kho tệp là **bản phái sinh**. `service.publish()` và
  `service.tro_lai()` ghi Postgres trước (nguyên tử cùng `them_version`), kho tệp sau.
  `service.doc_version_dang_live()` đọc Postgres. Khi không còn pod nào poll `LIVE`, xoá
  `_ghi_con_tro()`.
- **`0903` mở đường ghi trực tiếp** cho agent trên 3 bảng đó, tức KHÔNG qua gate cột
  `agent_api`. Chấp nhận được vì chúng không mang dữ liệu catalog. Thêm cột nhạy cảm vào một
  trong ba bảng thì phải tách bảng, không phải thêm cột.
- **`0905` sửa một lỗi đã ngủ từ `0005`.** `grant_agent_write()` chưa từng được gọi nên không
  ai thấy. Caller thứ hai sẽ không mắc lại.

## 4. Đã kiểm chứng những gì

Local: **756 test xanh**, `make lint` sạch, migration chain chạy được trên **PostgreSQL 16**
(bản của cluster đích, khác bản dev 18).

Trên `odyssey_portal`, bằng đúng credential `odyssey_agent`
(`scripts/kiem_chung_db_dung_chung.py`, chạy lại được, không để lại rác):

| | |
|---|---|
| Chưa khai tenant | `current_tenant()` NULL, cả 3 view trả **0 hàng** (fail-closed) |
| Gọi view không kèm schema | `FROM agent_published_config` và `FROM units` resolve được |
| Cách ly | mỗi tenant thấy đúng 603 units / 41 projects; chỉ `noble` có config |
| Ranh giới giao dịch | giao dịch sau không kế thừa tenant của giao dịch trước |
| Đường ghi | INSERT được cả 3 bảng write-back |
| 9 cửa phải đóng | KHÔNG đọc được `tenant_data.units/projects` gốc, `control.tenants`, `config_versions`, `config_live`, `agent_keys`, `deployments`, `users`, `memberships` |
| Heartbeat | tra `deployment_id` từ view → ghi `agent_heartbeats` chạy |
| Quay lui | trỏ v1001 → agent thấy v1001; quay lui v1 → agent thấy v1 **dù max(version)=1001** |

## 5. Hai script vận hành

```bash
# Nạp lại dữ liệu (XOÁ sạch 5 tenant ở đích trước khi nạp — kể cả hàng agent ghi thêm)
SRC_DSN=postgresql://sp_admin:...@127.0.0.1:15433/odyssey \
TGT_DSN=postgresql://portal_migrator:...@127.0.0.1:15433/odyssey_portal \
uv run python scripts/nap_du_lieu_tu_odyssey.py

# Kiểm chứng (chạy sau mỗi lần đổi schema hoặc đổi quyền)
AGENT_DSN=postgresql://odyssey_agent:...@127.0.0.1:15433/odyssey_portal \
MIGRATOR_DSN=postgresql://portal_migrator:...@127.0.0.1:15433/odyssey_portal \
uv run python scripts/kiem_chung_db_dung_chung.py
```

## 6. Còn treo — việc của người, không phải của code

1. **Xoay `odyssey_agent_pw`** và chuyển 2 mật khẩu mới vào secret store (§1).
2. **Đổi DSN phía agent** sang `/odyssey_portal`, rồi chạy lại `kiem_chung_db_dung_chung.py`.
3. **Thu hẹp quyền `odyssey_agent` trên DB `odyssey` cũ.** Ở đó nó có
   `SELECT+INSERT+UPDATE+DELETE` trực tiếp trên mọi bảng gốc, kể cả `agent_config_versions` —
   agent xoá được config của chính nó. Trên `odyssey_portal` đã đóng; DB cũ thì chưa.
4. **`sp_admin` là SUPERUSER + BYPASSRLS** — nó đọc xuyên mọi tenant trên cả hai database.
   Cách ly nhiều tenant của Portal không áp cho role đó.
5. **Chốt với team agent: `/runtime-credentials` còn hay bỏ?** Nếu bỏ thì còn thiếu 3 bề mặt:
   Host→tenant, `tenant_status` (§1.2), `tenant_keys` (§1.3). Cả ba **cố ý chưa dựng** —
   `tenant_keys` là bề mặt rộng nhất (hash khoá của cả tenant) và chưa luồng nào cần.
6. **Sửa hợp đồng của họ:** version **không** đơn điệu tăng (Portal có quay lui). Agent giả
   định "chỉ tăng" sẽ hỏng đúng lúc vận hành rollback.
7. **`voice` deployment** chưa cấp — cấp khi thật có pod voice, không cấp trước.
8. **Khuyến nghị chưa làm:** `UNIQUE (tenant_id, kind)` trên `control.deployments`. Không làm
   vì `enrollment.them_deployment()` chèn vô điều kiện, thêm index sẽ biến lần provisioning
   thứ hai thành lỗi 500 — cần sửa hàm đó trước.
9. **Backup `odyssey_portal`** trước khi có dữ liệu khách thật.
