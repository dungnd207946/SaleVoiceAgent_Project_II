# Design — Retire MinIO: agent đọc control-plane trực tiếp từ Postgres

> Ngày: 2026-08-04 · Branch: `feat/share-agent` · Trạng thái: design (chờ user duyệt → writing-plans)
> Handoff nguồn: `docs/handoff/2026-08-04-retire-minio-handoff.md`
> Contract Port↔Agent: `docs/handoff/spec.md` · Lược đồ Portal thật: `docs/api/SPEC-DB-HIEN-TAI.md`
> **Reverse-contract (bàn giao Portal): `docs/handoff/agent-postgres-read-contract.md`** (viết kèm design này).

## 1. Vấn đề

Agent chạy mô hình **1 process share phục vụ N tenant** (tenant theo org, id `org_<rand8>_<slug>`).
Phần **compose config** (persona/identity/scope/tools) đã đọc **Postgres** qua
`AGENT_CONFIG_SOURCE=db` → VIEW `agent_published_config`. NHƯNG bốn mảnh còn lại của luồng
config/serving vẫn đọc/ghi **MinIO** (tenant-store cũ):

1. **Gateway credential + active** (`gateway/*` → `MinioTenantStore.read_creds_raw`/`read_meta`).
2. **Worker version pinning** (`facade._resolve_current_version`/`_build_runner_for_version`
   → MinIO `pointer.json` + `versions/<n>/`).
3. **Worker tenant-context** (`facade.py:205` → `get_tenant_context()` → `manifest.toml` MinIO).
4. **Heartbeat** (`server/http.py` + `transport/livekit/worker.py` → `store.write_heartbeat`).

Portal (control-plane thật) lưu **mọi thứ trên Postgres, không dùng MinIO**. Nếu Portal tạo
tenant thuần Postgres, agent hiện tại **không phục vụ được** (không thấy creds/active/manifest/
version trên MinIO).

**Mục tiêu:** khi Portal tạo org+tenant+credential+config **chỉ trên Postgres**, agent
(gateway + worker) phục vụ được tenant đó **không cần bất kỳ object MinIO nào**. Trạng thái vận
hành đích: `AGENT_CONFIG_SOURCE=db` ⇒ toàn bộ control-plane đọc Postgres; MinIO rời khỏi đường
request. Đường single-tenant in-wheel (`TENANT_ID=noble`) **giữ nguyên byte-identical**.

## 2. Phát hiện định hình thiết kế (đã kiểm bằng code + DB live)

- **Compose config đã off MinIO trong db-mode.** `facade._build_runner_from_ctx:238` rẽ theo
  `agent_config_source=="db"` → `_agent_def_from_db` → `read_published_config`. Phần agent-def
  không còn cần bundle MinIO; chỉ còn version-int + `TenantContext` là vẫn lấy từ MinIO.
- **Portal thật CHƯA ship bề mặt agent cần.** `SPEC-DB-HIEN-TAI.md` (HEAD `0900_enrollment`):
  `agent_api` chỉ có 5 view KB — **không** có `agent_published_config`, **không** có bề mặt
  verify credential; role `agent_all` không đọc được `control.agent_keys`/`control.tenants`.
  DB dùng chung `10.50.13.220:5433` hiện cũng **chỉ mô phỏng** `public.agent_published_config`
  + `agent_config_*` + `tenant_data.*` (chưa có `control.*`/`agent_api.*`/hàm `portal.*`).
  → Reverse-contract là thứ Portal **phải ship**; ta thiết kế agent-side + mô phỏng để test.
- **Hai điểm không tương thích trong code hiện tại (phải viết lại, không re-point được):**
  - **Hash credential:** MinIO model (`tenant/credentials.py`) là **SHA-256 có salt**
    (`sha256(salt||plaintext)`, `hmac.compare_digest`); Portal `agent_keys.key_sha256` là
    **sha256 trần**. Verify ở gateway phải đổi thuật toán.
  - **Tên GUC:** `tenant_conn` set `app.current_tenant`; Portal `portal.current_tenant()` đọc
    `app.tenant_id` (hoặc suy từ `session_user` `agent_*`). Sim local dùng `app.current_tenant`.
- **Lệch kiến trúc deployment (định hình model heartbeat):** Portal model là **1 deployment /
  tenant** (`control.deployments.tenant_id NOT NULL`; `agent_keys`/`agent_heartbeats` theo
  `deployment_id`), còn agent là **1 process share N tenant**. Role agent **không enumerate**
  được `control.tenants`. ⇒ heartbeat đổi từ "quét-all + beat" sang "beat theo tenant đang có
  kết nối", `deployment_id` tra per-tenant qua view (không lấy từ env).

## 3. Quyết định đã chốt (D1–D6)

**D1 — Công tắc.** `AGENT_CONFIG_SOURCE=db` là công tắc DUY NHẤT. Ở db-mode: gateway-creds,
worker-ctx, version, heartbeat **đều đọc Postgres**; **không dựng `MinioTenantStore`** trên
đường serving. `TENANT_STORE_ENABLED` tụt xuống chỉ còn cho legacy MinIO bundle (không phải
đường Odyssey). `AGENT_CONFIG_SOURCE≠db` (mặc định `legacy`) ⇒ đường in-wheel/MinIO cũ **y
nguyên**. In-wheel `TENANT_ID=noble` né `org_of` qua `is_valid_tenant_id` như hiện tại.

**D2 — Credential model (theo Portal, bỏ salt).** Gateway băm **`sha256(plaintext)` trần**,
verify qua 2 view Postgres scoped-RLS theo `current_tenant()` (tenant lấy từ Host-subdomain),
map 1-1 với `CredentialRegistry` hiện có:
- `is_active(tenant)` → đọc `agent_api.tenant_status(tenant_id, active)`.
- `verify(plaintext, tenant)` → tra `sha256(plaintext)` trong `agent_api.tenant_keys(tenant_id,
  key_sha256, active)`; có dòng `active=true` ⇒ hợp lệ. RLS chỉ trả key của đúng tenant nên
  token của tenant khác gửi kèm Host tenant này ⇒ 0 dòng ⇒ từ chối (đúng semantics `bad_credential`).
- **Bỏ ràng buộc prefix `tnt_`** (quy ước MinIO cũ). Prefix do Portal quyết; agent băm nguyên
  chuỗi bearer sau `Bearer `.

**D3 — Bỏ manifest, mọi thứ từ published config.** `enabled_tools`/`brand`/`media_channel`/
`feng_shui`/`data_source` đã nằm trong `agent_published_config.config` (spec.md §4). Trên db-path,
**bỏ `get_tenant_context()`** (đọc `manifest.toml` MinIO); thay bằng `context_from_config(
tenant_id, cfg)` dựng `TenantContext` từ published config: `persona_dir` = skeleton dùng chung,
`data_source = cfg.data_source or "pg_kb"`, `enabled_tools = cfg.enabled_tools`, `brand`/
`media_channel`/`rankers` từ `cfg`. `current_tenant()` vẫn là trục định danh; provider-factory +
find_project index không đổi (vẫn key theo `current_tenant()`).

**D4 — Version pinning từ VIEW.** Bỏ `read_pointer`/`versions/<n>` MinIO khỏi db-path.
`version = agent_published_config.version`. Giữ **BR05**: `NobleAgent` pin version lúc
`create()` cho suốt cuộc gọi; cuộc gọi MỚI đọc version hiện tại; TTL-refresh
(`NOBLE_CONFIG_POLL_SEC`); last-good on-disk fallback (đã có ở `agent_config_store`). Runner
cache của facade đổi key sang `(tenant, version)` như hiện tại nhưng version nguồn từ VIEW.
`tenant/version_resolver.py` (MinIO) rời khỏi db-path.

**D5 — Heartbeat (slice cuối, model đổi).** Ghi `control.agent_heartbeats` (grant INSERT/UPDATE
cho `agent_all` đã có — SPEC §3.12). Model: agent giữ tập **tenant đang/vừa có kết nối** (TTL
set, cập nhật mỗi lượt phục vụ), mỗi chu kỳ với từng tenant → set GUC → tra `deployment_id`
khớp **`kind`** của process này (`chat` cho aiortc/http, `voice` cho livekit) qua
`agent_api.deployments` → upsert heartbeat `(tenant_id, deployment_id)`. **Không** enumerate
`control.tenants`, **không** lấy `deployment_id` từ env (env không mang N giá trị).

**D6 — Contextvar (không đổi).** `current_tenant()`/`use_tenant()`/`org_of()` giữ nguyên. Đây
là trục per-request; org suy từ tenant bằng prefix. Đường legacy `noble` né `org_of`.

## 4. Kiến trúc theo slice (seam chính xác)

Store-factory seam trung tâm: `tenant/loader.py:24 _build_store` (dùng bởi facade + 2 wire-up
heartbeat) + `gateway/server.py:74`. Ý tưởng chung: **ở db-mode, không đi qua các seam MinIO
này**; thay bằng lối đọc Postgres.

### Slice A — Gateway credential từ Postgres
- Thêm `gateway/pg_registry.py`: `PostgresCredentialRegistry` cùng bề mặt `CredentialRegistry`
  (`is_active(tenant)`, `entries_for(tenant)`/hoặc `verify(tenant, plaintext)`), TTL-cache như
  bản MinIO, đọc `agent_api.tenant_status` + `agent_api.tenant_keys` qua `tenant_conn`.
- `gateway/server.py:66-77`: khi `settings.agent_config_source=="db"` inject
  `PostgresCredentialRegistry`, else giữ `CredentialRegistry(MinioTenantStore…)`.
- `gateway/auth.py` không đổi logic (vẫn gọi `registry.is_active` + verify); chỉ đổi cách băm:
  verify dùng `sha256(plaintext)` trần (đẩy vào registry pg). Reason-codes `tenant_inactive` /
  `bad_credential` / `bad_host` giữ nguyên (4001).

### Slice B — Worker ctx + version từ Postgres
- `facade._resolve_current_version(tenant_id)`: ở db-mode trả `read_published_config(tenant_id).
  version` (qua pool + TTL, tái dùng cache của `agent_config_store`), **không** dựng store MinIO.
  Không có config published → last-good/`0` fail-closed.
- `facade._build_runner_for_version(tenant_id, version)`: ở db-mode dựng ctx bằng
  `context_from_config(tenant_id, cfg)` (cfg = published config đã đọc), rồi `_build_runner_from_ctx`
  (nhánh db đã có sẵn ở `:238`). **Không** gọi `context_for_version`/`materialize_version` MinIO.
- `facade._build_runner`/`NobleAgent.create`: ở db-mode luôn đi nhánh version>0 (VIEW), không rơi
  về `get_tenant_context()` in-wheel. Legacy path (`≠db`) giữ nguyên hoàn toàn.
- `context_from_config` đặt ở `tenant/` (vd `tenant/db_context.py`) để tách khỏi loader MinIO.

### Slice C — Heartbeat từ Postgres
- Thêm `tenant/pg_heartbeat.py`: `PgHeartbeatWriter` upsert `control.agent_heartbeats`
  (`ON CONFLICT (tenant_id, deployment_id)`), cột `running_version`/`bundle_sha`/`agent_version`/
  `last_error`/`last_seen_at`. `deployment_id` tra `agent_api.deployments` theo `kind`.
- Nguồn "tenant đang hoạt động": một `ActiveTenantTracker` (TTL set) được facade/turn-loop
  chạm mỗi lượt phục vụ (hook nhẹ ở `NobleAgent`/turn entrypoint). Supervisor beat theo set này.
- Wire-up `server/http.py` (kind=`chat`) + `transport/livekit/worker.py` (kind=`voice`): ở
  db-mode dùng supervisor Postgres; else MinIO như cũ. Gate `should_emit` mở rộng: db-mode chỉ
  cần `heartbeat_enabled` (không cần `tenant_store_enabled`).

### Slice D — Dọn MinIO khỏi serving
- `MinioTenantStore` + `noble-tenant` CLI **giữ code**, chỉ còn reachable ở legacy path
  (`agent_config_source≠db` / `tenant_store_enabled`). Thêm ghi chú deprecate. **Xoá hẳn =
  follow-up** (không trong task này) để giữ rollback + dev/legacy.

### GUC (áp cho cả A/B/C)
`storage/postgres_client.tenant_conn` set **cả hai** GUC cùng giá trị mỗi txn:
`set_config('app.current_tenant',$1,true)` **và** `set_config('app.tenant_id',$1,true)`. Rẻ,
không thêm knob, chạy đúng cả RLS data-plane agent-owned (dùng `app.current_tenant`) lẫn RLS
Portal-owned (dùng `app.tenant_id`). (Đổi 1 dòng, kèm test.)

## 5. Reverse-contract (Portal phải ship) — tóm tắt

Chi tiết đầy đủ + DDL tham khảo: `docs/handoff/agent-postgres-read-contract.md`. Tóm tắt bề mặt
`agent_api` (RLS scope theo `portal.current_tenant()`, GRANT SELECT `agent_all`):

| Bề mặt | Cột | Dùng cho |
|---|---|---|
| `agent_published_config` (view) | `tenant_id, version, config jsonb` | compose config + version pin (đã dùng) |
| `tenant_status` (view) | `tenant_id, active bool` | gateway `is_active` |
| `tenant_keys` (view) | `tenant_id, key_sha256, active bool` | gateway verify (sha256 trần) |
| `deployments` (view) | `tenant_id, id, kind` | heartbeat tra `deployment_id` theo kind |
| `control.agent_heartbeats` | (ghi) | agent upsert nhịp tim (grant đã có) |

Contract phải bảo đảm: (1) các view resolve được cho role agent (unqualified hoặc trên
search_path — để reader hiện tại giữ nguyên); (2) RLS scope theo tenant giống các view KB;
(3) hiểu GUC `app.tenant_id` (agent sẽ set cả `app.current_tenant` lẫn `app.tenant_id`).

## 6. Chiến lược test

- **Unit (offline):** fake registry/reader/heartbeat-writer; kiểm nhánh db-mode chọn đúng lối
  Postgres, verify sha256-trần, `context_from_config` map đúng field, version từ VIEW, BR05 pin.
- **Live (mô phỏng Portal):** dựng các view `agent_api.*` + bảng `control.agent_heartbeats` +
  hàm `portal.current_tenant()` **mô phỏng** để chạy A/C end-to-end. ⚠️ **DB `…:5433` dùng chung
  với Portal team** → mô phỏng phải **tách biệt**: ưu tiên **PG docker cục bộ** (throwaway), hoặc
  nếu buộc dùng DB chung thì đặt trong schema/role riêng, gỡ sạch sau test, **tuyệt đối không**
  tạo `control.*`/`agent_api.*` "thật" đè migration Portal. Script mô phỏng để trong
  `scripts/` (hoặc scratchpad) + tài liệu rõ.
- **Smoke:** Portal(mô phỏng)-tạo-tenant-Postgres → gateway auth qua PG → worker compose từ PG →
  chat trả lời, **không** tạo object MinIO cho tenant đó (chứng minh MinIO ngoài luồng).
  Chạy `src/noble_agent/SMOKE.md` sau khi đụng turn-loop/transport/gateway.

## 7. Backward-compat & rollout

- `AGENT_CONFIG_SOURCE` mặc định `legacy` → deploy hiện tại **byte-identical**, MinIO như cũ.
- Bật Odyssey = set `AGENT_CONFIG_SOURCE=db` (+ Postgres DSN trỏ Portal DB). Không cần MinIO.
- CLAUDE.md self-maintenance: cập nhật mục storage/flows + Change Log trong cùng commit khi land.
- **DB dùng chung** `POSTGRES_DSN=…10.50.13.220:5433/odyssey` (loopback trên server → agent chạy
  máy khác cần SSH tunnel `-L 5433:127.0.0.1:5433 thebc-server`). `POSTGRES_APP_ROLE=odyssey_agent`.

## 8. Ngoài phạm vi / follow-up

- Xoá hẳn `MinioTenantStore` + `noble-tenant` CLI (task này chỉ gỡ khỏi serving).
- Portal thật ship `control.*`/`agent_api.*` migration lên DB chung (đang chờ Portal team).
- Cutover LIVE với Portal thật (agent đọc `control.config_versions` qua `agent_published_config`
  view thật + verify creds thật) — chờ Portal ship contract §5.
- Chuẩn hoá `deployment_id`/`kind` bàn giao (Portal tạo deployment row lúc provisioning).
