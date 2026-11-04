# TRẢ LỜI — Portal control-plane cho agent db-mode

- **Ngày:** 2026-08-05
- **Từ:** Team Portal API (Backend)
- **Tới:** Team Agent (Hotline / odyssey-agent)
- **Trả lời:** `bug-portal-control-plane-missing.md`
- **Trạng thái:** ✅ Đã xong phía Portal (migration `0907_view_control_plane`). Còn **một việc
  vận hành** phía các bạn/Portal — xem §4.

---

## 1. Tóm tắt một câu

Trong bốn quan hệ các bạn báo thiếu, **hai cái đã tồn tại từ trước** (`agent_api.deployments`,
`agent_api.agent_published_config`) — nguyên nhân thật khiến các bạn không đọc được chúng là
**`search_path`**, không phải thiếu view. Hai cái còn lại (`tenant_status`, `tenant_keys`) nay
đã dựng xong. Cả ba câu SQL nghiệm thu ở §7 của các bạn đã chạy thật và trả đúng.

---

## 2. Đối chiếu từng mục các bạn yêu cầu

| Yêu cầu | Trạng thái |
|---|---|
| `agent_api.tenant_status` (`tenant_id, active`) | ✅ **Mới tạo** (0907) |
| `agent_api.tenant_keys` (`tenant_id, key_sha256, active`) | ✅ **Mới tạo** (0907) |
| `agent_api.deployments` (`id, tenant_id, kind`) | ✅ **Đã có từ trước** (0906) |
| `agent_published_config` (`tenant_id, version, config`) | ✅ **Đã có từ trước** (0904), tên đầy đủ `agent_api.agent_published_config` |
| `GRANT SELECT` cho role runtime | ✅ Tự động — xem §3.2 |
| `search_path` để query không prefix chạy được | ✅ Đã set — xem §3.3 |

### Xác nhận thuật toán hash — không cần đổi gì

Các bạn ghi *"gateway tính `sha256(plaintext).hexdigest()` (hex thường)"*. Portal lưu **y hệt**
(`bi_mat.bam_khoa()` = `hashlib.sha256(...).hexdigest()`). `key_sha256` trong view dùng thẳng
cột đã lưu, không biến đổi gì thêm. Đã kiểm chứng bằng cách phát một khoá thật qua UI rồi so:

```sql
key_sha256 = encode(sha256('<api_key>'::bytea), 'hex')   -- → KHỚP
```

### Ba câu trả lời của các bạn — Portal đồng ý cả ba

- **Q2 (`active` dùng lifecycle đơn giản):** đồng ý. `tenant_status.active` = `lifecycle = 'active'`,
  khớp đúng điều kiện `/bootstrap` đang dùng. Cố ý **không** dùng logic hiển thị nhiều trạng thái
  (provisioning/publishing/disconnected) — nếu dùng, một pod vừa khởi động chưa kịp gửi nhịp tim
  sẽ tự từ chối chính nó và không bao giờ lên được.
- **Q3 (`last_used_at`):** đồng ý phương án (a). Portal chấp nhận cột đó không phản ánh nhánh
  db-mode, dùng `control.agent_heartbeats` để biết pod còn sống. Đã ghi vào header migration.
- **Q1 (role):** xem §5 — có một điểm quan trọng về `odyssey_app` các bạn nên biết.

---

## 3. Chi tiết kỹ thuật

### 3.1 Định nghĩa hai view mới

```sql
CREATE VIEW agent_api.tenant_status AS
SELECT t.id AS tenant_id, (t.lifecycle = 'active') AS active
  FROM control.tenants t
 WHERE t.id = portal.current_tenant();

CREATE VIEW agent_api.tenant_keys AS
SELECT d.tenant_id, k.key_sha256, (k.revoked_at IS NULL) AS active
  FROM control.agent_keys k
  JOIN control.deployments d ON d.id = k.deployment_id
 WHERE d.tenant_id = portal.current_tenant();
```

`tenant_keys` chỉ có đúng ba cột hợp đồng yêu cầu — không lộ `key_prefix`/`label`/`created_by`.

### 3.2 Quyền — không cần Portal cấp thêm gì

Schema `agent_api` có `ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES TO agent_all`, nên
mọi view mới **tự động** đọc được bởi bất kỳ role nào là thành viên `agent_all`. Role runtime
của các bạn đã là thành viên → không cần `GRANT` thủ công nào.

Quyền ghi `control.agent_heartbeats` (contract C3) cũng đã có sẵn cho `agent_all` từ migration
0007 — `SELECT, INSERT, UPDATE`.

### 3.3 ⚠️ `search_path` — nguyên nhân thật của lỗi B

Các bạn đoán đúng ở §6 của bug report. Portal đã chọn **phương án (b)** các bạn đề xuất:

```sql
ALTER ROLE odyssey_app SET search_path = agent_api, public;
```

Nên `SELECT version, config FROM agent_published_config WHERE tenant_id = $1` (không prefix)
chạy được, **không cần các bạn đổi code**. Cố ý **không** thêm `control` vào `search_path`: một
câu truy vấn quên schema chạm nhầm bảng `control` là lỗi không có triệu chứng.

> Vẫn khuyến nghị các bạn đổi sang `agent_api.agent_published_config` khi tiện — `search_path`
> ở mức role là trạng thái ngoài code, người đọc code không thấy nó.

### 3.4 ⚠️ BẮT BUỘC: phải `set_config` TRƯỚC MỌI câu SELECT, kể cả câu xác thực

Cả 6 view `agent_api` đều lọc bằng `portal.current_tenant()`, **không** theo tham số `$1` các
bạn truyền vào. Đây là yêu cầu cưỡng chế bằng test phía Portal, không phải lựa chọn.

Nghĩa là: **quên `set_config` ⇒ view trả 0 hàng ⇒ xác thực trượt** (fail-closed, đúng thiết kế),
chứ không phải ném lỗi. Nếu các bạn thấy "khoá đúng mà vẫn từ chối", kiểm chỗ này trước tiên —
đặc biệt ở đường **gateway auth**, nơi dễ chạy query trước khi thiết lập tenant context.

`WHERE tenant_id = $1` trong câu SQL của các bạn vẫn giữ được, chỉ là thừa (view đã lọc rồi).

---

## 4. ⛔ Việc CÒN LẠI — không phải schema, là dữ liệu

`agent_api.agent_published_config` đã tồn tại và query được, **nhưng chưa tenant nào publish
config**. Đã kiểm trên DB: `control.config_live` rỗng.

Nên lỗi `"no published config for tenant 'dufake'"` **sẽ vẫn còn** sau khi deploy migration này,
cho tới khi:

1. Workspace `dufake` được tạo trong Portal, và
2. Có người bấm **Lưu và áp dụng** ở màn **Agent & Kênh** của Portal cho workspace đó.

Đúng như §5.6 các bạn viết: config phải sinh qua luồng publish, không seed tay. Portal không tự
publish thay được — nội dung config (tên agent, phạm vi, tools) là quyết định của chủ workspace.

---

## 5. ⚠️ Một điểm về `odyssey_app` cần hai team thống nhất

Các bạn viết *"role runtime thật là `odyssey_app`... đã tồn tại + đã LOGIN"*. Đúng — nhưng lý do
nó tồn tại là vì **`odyssey_app` là role runtime của chính Portal backend**
(`.gitlab-ci.yml:150`), và nó được cấp:

```sql
GRANT portal_api, agent_all TO odyssey_app;
```

Qua tư cách thành viên `portal_api`, role này có **`SELECT/INSERT/UPDATE/DELETE` trên toàn bộ
schema `control`** — gồm `users`, `memberships`, `tenants`, `agent_keys`. Tức là credential các
bạn đang dùng **không phải least-privilege** như §5.5 của bug report mong muốn; nó là credential
đầy đủ của backend Portal.

**Đề xuất của Portal (đúng tinh thần least-privilege mà chính các bạn nêu):** dùng role riêng chỉ
có `agent_all`, không có `portal_api`. Role `odyssey_agent` đã tồn tại sẵn cho đúng mục đích này
và đã được cấu hình `search_path` từ trước. Chỉ cần ops đặt mật khẩu:

```sql
ALTER ROLE odyssey_agent LOGIN PASSWORD '<bí mật>';
```

rồi đổi `POSTGRES_DSN` phía gateway/worker sang role đó. Bề mặt thu hẹp còn đúng những gì agent
cần, và một credential lộ không còn đồng nghĩa với mất toàn bộ dữ liệu Portal.

Việc này **không chặn** e2e — hiện tại chạy được với `odyssey_app`. Nhưng nên làm trước khi có
dữ liệu khách hàng thật.

---

## 6. Nghiệm thu — Portal đã chạy thật, đây là kết quả

Phát một khoá thật qua UI Portal (`POST /api/v1/agent/keys` → workspace `anphu`), rồi chạy đúng
luồng gateway bằng quyền agent trên DB:

```
0. chưa khai tenant  -> tenant_status  0 hàng   ✅ fail-closed
0. chưa khai tenant  -> tenant_keys    0 hàng   ✅ fail-closed
1. tenant_status.active = true                  ✅
2. tenant_keys: 2 khoá sống                     ✅
3. XÁC THỰC: KHỚP -> cho phép kết nối           ✅  ← hash khoá thật khớp
4. deployment_id = 4                            ✅  (cho heartbeat)
5. published_config: (chưa publish)             ⛔ ← xem §4
6. cách ly (hỏi tenant khác) -> 0 hàng          ✅
```

Bộ test tự động đi kèm: `tests/isolation/test_view_control_plane_dbmode.py` — 11 ca, gồm cả ba
câu SQL nghiệm thu §7 chép nguyên văn. Toàn repo 815/815 xanh.

---

## 7. Các bạn cần làm gì

1. Chờ Portal deploy migration `0907` lên `agents-dev`.
2. **Không cần đổi code.** Ba query `agent_api.*` và query `agent_published_config` không prefix
   đều chạy đúng như hiện tại.
3. Kiểm chắc gateway `set_config('app.tenant_id', ...)` **trước cả câu xác thực** (§3.4).
4. Publish config cho tenant test qua UI Portal (§4) — nếu không, lỗi B vẫn còn.
5. Cân nhắc đổi sang role `odyssey_agent` (§5).

---

## 8. Tham chiếu phía Portal

| Thứ | Chỗ |
|---|---|
| Migration mới | `migrations/versions/0907_view_control_plane_cho_agent_dbmode.py` |
| View `deployments` (có sẵn) | `migrations/versions/0906_view_deployments_cho_agent.py` |
| View `agent_published_config` (có sẵn) | `migrations/versions/0904_con_tro_config_live.py` |
| Thuật toán hash khoá | `src/portal/modules/enrollment/bi_mat.py::bam_khoa` |
| Cổng canh | `tests/isolation/test_view_control_plane_dbmode.py` |
| Vì sao mọi view phải lọc tenant | `tests/isolation/test_isolation_catalog.py::test_moi_view_agent_api_tu_loc_tenant` |
