# Handoff: Retire MinIO — agent phục vụ trực tiếp tenant do Portal tạo (Postgres-only)

> Dành cho: một session Claude Code MỚI. Đọc trọn file này trước khi làm gì.
> Ngày viết: 2026-08-04 · Branch làm việc: `feat/share-agent` (KHÔNG đụng `develop`).
> Đây là handoff để tránh tràn context — mọi dữ kiện cần thiết nằm ở đây.

## 0. Bối cảnh 1 đoạn

Repo `santa-hotline-agent` (voice/chat agent, package `src/noble_agent`) đang chạy mô hình
**"1 process share phục vụ N tenant"**, tenant phân theo **organization** (id toàn cục
`org_<rand8>_<slug>`, org = prefix). Config persona/agent đã được chuyển sang đọc từ
**Postgres** (tính năng `AGENT_CONFIG_SOURCE=db`, mới xong). NHƯNG phần **đăng-ký-tenant +
credential + manifest + heartbeat** của agent **vẫn đọc/ghi MinIO** (tenant-store cũ). Portal
API (control-plane thật) lưu MỌI THỨ trên Postgres và **không dùng MinIO**. → Nếu Portal tạo
tenant thuần trên Postgres, agent hiện tại KHÔNG phục vụ được (không tìm thấy creds/active/
manifest trên MinIO). **Task: gỡ nốt MinIO khỏi luồng config/serving, cho agent đọc trực tiếp
Postgres (control.* + VIEW) như Portal quy định.**

## 1. Mục tiêu & định nghĩa "xong"

- Khi Portal tạo org+tenant+credential+config **chỉ trên Postgres**, agent (gateway + worker)
  phục vụ được tenant đó **không cần bất kỳ object MinIO nào**.
- `TENANT_STORE_ENABLED=false` là trạng thái vận hành đích cho luồng config; MinIO không còn
  nằm trên đường request config/serving.
- Đường single-tenant in-wheel (`TENANT_ID=noble`, bundle trong wheel) **vẫn chạy** (đừng phá).

## 2. Trạng thái hiện tại — cái gì ở đâu (đã kiểm bằng code)

MinIO bucket `hotline-tenants`, mỗi tenant dưới prefix `<org>/<tenant>/` (`store.py:243`
`_prefix = f"{org_of(tenant_id)}/{tenant_id}"`). Object: `manifest.toml`, `_meta.json`
(status), `_creds.json` (bearer hashes), `_heartbeat.json`, `pointer.json`,
`versions/<n>/…`, `draft/…`, các file persona.

| Mảnh | Agent đọc từ (HIỆN TẠI) | Đích (Portal/Postgres) |
|---|---|---|
| Persona config (identity/scope/tools) | ✅ Postgres VIEW `agent_published_config` (db-mode) | giữ nguyên |
| Tenant tồn tại + `status=active` | ❌ MinIO `_meta.json` | `control.tenants.lifecycle` |
| Credential (gateway bearer) | ❌ MinIO `_creds.json` | `control.agent_credentials` + `control.agent_keys.key_sha256` |
| Manifest (`data_source`, `tenant_id`) | ❌ MinIO `manifest.toml` via `get_tenant_context()` | DB (xem Quyết định D3) |
| Version pinning (BR05) | ❌ MinIO `pointer.json` + `versions/<n>/` | VIEW `agent_published_config.version` |
| Heartbeat | ❌ MinIO `_heartbeat.json` | `control.agent_heartbeats` |
| KB data (dự án/căn/tài liệu) | ✅ Postgres `tenant_data.*` (provider `pg_kb`) | giữ nguyên |

Nguồn sự thật DB Portal: **`docs/api/SPEC-DB-HIEN-TAI.md`** (lược đồ đầy đủ: schemas
`control`/`tenant_data`/`agent_api`, roles, RLS). Contract Portal↔Agent:
**`docs/handoff/spec.md`** — ĐỌC KỸ, có thể đã chốt sẵn vài quyết định dưới.

## 3. Blast radius — CHÍNH XÁC các call-site chạm MinIO (phải đấu lại)

Tất cả điểm dựng store là `MinioTenantStore.from_settings` / `loader._build_store`:

1. **Gateway (ingress auth)** — `gateway/server.py:74` dựng `CredentialRegistry(MinioTenantStore…)`.
   - `gateway/registry.py:25` `entries_for` → `store.read_creds_raw` (creds).
   - `gateway/registry.py:30` `is_active` → `store.read_meta` (status).
   - `gateway/auth.py:77,84` gọi `registry.is_active` + `credentials.verify(…, registry.entries_for)`.
   → THAY: một `CredentialRegistry` đọc Postgres (verify bearer vs `control.agent_keys.key_sha256`,
     active vs `control.tenants.lifecycle`). Xem Quyết định D2 (mô hình credential).

2. **Worker — resolve TenantContext** — `tenant/loader.py:39-45` `_resolve_tenant_dir`
   (store-first: `read_meta` + `materialize_tenant`) → `get_tenant_context()` (dùng
   `tenant_id` + `data_source`). Facade gọi ở `facade.py:205-208`.
   → THAY: lấy `tenant_id` (đã có từ contextvar) + `data_source`/`enabled_tools`/`brand` từ DB
     (phần lớn đã nằm trong `agent_published_config.config`). Xem D3 (data_source ở đâu).

3. **Worker — version pinning** — `facade.py:317-348` `_resolve_current_version`
   (`store.read_pointer`), `facade.py:351-361` `_build_runner_for_version`
   (`context_for_version` → `materialize_version` → `read_version_bundle` từ MinIO).
   → THAY: version = `agent_published_config.version` (VIEW đã join config_versions+pointer
     phía Portal). Giữ BR05 (conversation đang chạy giữ version đã pin; conversation MỚI đọc
     version hiện tại). Bỏ `version_resolver.py` (MinIO) khỏi đường này.

4. **Heartbeat** — `server/http.py:1032` + `transport/livekit/worker.py:290` dựng
   `HeartbeatSupervisor(_build_store(settings), …)`; `tenant/heartbeat.py:173`
   `store.write_heartbeat`, `:222` `store.list_ids()`.
   → THAY: ghi `control.agent_heartbeats` (cần `deployment_id` — xem D4). Enumeration tenant
     (list_ids) → nguồn tenant nào? (xem D4).

5. **CLI `noble-tenant`** — `tenant/cli.py:37` (create-org/create-tenant/issue-cred… ghi MinIO).
   → Đây là provisioning CŨ/nội bộ. Khi Portal là control-plane, CLI này KHÔNG còn dùng cho
     luồng thật. Quyết định D5: giữ CLI cho dev/legacy hay bỏ.

Config reader đã Postgres rồi (tham chiếu, KHÔNG sửa): `storage/agent_config_store.py`
`read_published_config` → `SELECT version, config FROM agent_published_config WHERE tenant_id=$1`
qua `tenant_conn(pool, tenant_id)` (RLS auto-scope). Postgres pool:
`storage/postgres_client.py` (`get_pool` + `tenant_conn` set `app.current_tenant`).

## 4. Phụ thuộc Portal (CHẶN — verify trước khi code)

Agent chỉ ĐỌC, **không sửa DDL Portal**. Trước khi wiring, xác minh Portal đã ship:

- [ ] VIEW **`agent_published_config`** (cột `tenant_id, version, config jsonb`) — reader đang
      giả định có. ⚠️ `SPEC-DB-HIEN-TAI.md` §5 liệt kê schema `agent_api` chỉ có 5 view KB
      (projects/zones/units/documents/media) — **CHƯA thấy `agent_published_config`**. Phải hỏi
      Portal / kiểm DB thật xem VIEW này đã tồn tại chưa; nếu chưa → chặn, cần Portal tạo.
- [ ] Đường **verify credential** cho agent: agent (role `odyssey_agent`) có được SELECT
      `control.agent_keys.key_sha256` / `control.tenants.lifecycle` không? (RLS/GRANT). Nếu
      không, cần Portal cấp một VIEW/hàm cho agent (vd `agent_api.verify_credential(sha256)`
      hoặc `agent_api.tenant_active(tenant_id)`).
- [ ] `deployment_id` cho heartbeat: `control.agent_heartbeats.PK=(tenant_id,deployment_id)`.
      Agent lấy `deployment_id` từ đâu? (`control.deployments` do Portal tạo; agent nhận qua
      env/bootstrap?). Cần chốt với Portal.
- [ ] Enumeration: agent có được liệt kê "mọi tenant active" để heartbeat không? `control.tenants`
      là Portal-owned; role agent có thể không SELECT-all được (RLS). → Có thể đổi mô hình
      heartbeat (chỉ beat cho tenant đang có kết nối, thay vì quét toàn bộ).

## 5. Quyết định phải CHỐT trước khi viết code (brainstorm gate)

Đừng code ngay — mấy điểm này quyết định thiết kế. Nên chạy `superpowers:brainstorming` với
người dùng, đối chiếu `docs/handoff/spec.md` (có thể đã chốt sẵn):

- **D1 — Bật/tắt:** dùng cờ nào để chuyển "MinIO → Postgres" cho registry/ctx/heartbeat? (đề xuất:
  khi `AGENT_CONFIG_SOURCE=db` thì TẤT CẢ các đường trên đọc Postgres; `TENANT_STORE_ENABLED`
  chỉ còn cho legacy). Giữ đường legacy/in-wheel `noble` nguyên vẹn.
- **D2 — Credential model:** MinIO `_creds.json` (salted hash list, `tenant/credentials.py`) vs
  Portal `control.agent_keys.key_sha256` (sha256, không salt). Gateway verify thế nào cho khớp
  Portal? (nhiều khả năng: sha256(plaintext) → lookup `agent_keys`, join `deployments`→`tenants`
  để ra tenant + active). Có thể cần đổi cả cách provider client lấy token.
- **D3 — `data_source` + `enabled_tools` + `brand` khi bỏ manifest:** `enabled_tools`/`brand` đã
  nằm trong `agent_published_config.config` (`config.tools.enabled`, `config.identity.brand`).
  Còn `data_source` (chọn provider `pg_kb`) hiện ở `manifest.toml`. Chốt: nhét `data_source` vào
  published config, hay 1 cột `control.tenants`, hay hardcode `pg_kb` (Odyssey chỉ có pg_kb)?
- **D4 — Heartbeat:** lấy `deployment_id` ở đâu + enumerate tenant nào để beat (quét-all vs
  beat-theo-kết-nối). Có thể là slice riêng, tách khỏi phần gateway/ctx.
- **D5 — Số phận `noble-tenant` CLI + MinIO store code:** xoá hẳn, hay giữ sau cờ cho dev/test/
  legacy? (đề xuất: giữ code nhưng gỡ khỏi đường serving; xoá là follow-up).
- **D6 — Tenant contextvar:** `current_tenant()` (`tenant/current.py`) vẫn là trục định danh
  per-request; org suy ra bằng `identity.org_of()`. KHÔNG đổi.

## 6. Ràng buộc kỹ thuật (bắt buộc)

- Branch `feat/share-agent`, commit local; **không** push/PR/merge/`develop` nếu không được bảo.
- RLS: agent connect bằng role chung `odyssey_agent` (`POSTGRES_APP_ROLE`), mỗi txn scope qua
  `tenant_conn(pool, tenant_id)` set `app.current_tenant` (local). KHÔNG sửa file SQL Portal-owned;
  chỉ đọc VIEW/bảng Portal cấp quyền. (DDL agent tự sở hữu: `storage/sql/*.sql` — chỉ là data-plane
  `tenant_data`, không phải `control`.)
- Giữ **byte-identical** đường single-tenant in-wheel (`TENANT_ID=noble`, store tắt).
- Theo `superpowers`: brainstorm → writing-plans → subagent-driven-development. TDD, commit nhỏ.
  Chạy `src/noble_agent/SMOKE.md` sau khi đụng turn-loop/transport/gateway.
- CLAUDE.md có luật self-maintenance: cập nhật CLAUDE.md + Change Log trong cùng commit khi đổi
  storage/luồng.

## 7. Hạ tầng test (đã sẵn, verify live được)

- **Postgres live:** `localhost:5432/odyssey`. `.env`: `POSTGRES_DSN=…odyssey_agent…` (runtime,
  RLS), `POSTGRES_ADMIN_DSN=…sp_admin…` (superuser, provisioning/seed). `POSTGRES_ENABLED=true`,
  `POSTGRES_APP_ROLE=odyssey_agent`. `tenant_data.*` đã có data 3 tenant (noble/acme/du_test, mỗi
  cái 41 dự án). ⚠️ DB `odyssey` local này có thể CHƯA có schema `control.*` + VIEW
  `agent_published_config` của Portal — kiểm trước (đây là DB test data-plane của agent, không
  phải DB Portal thật). Có thể phải tự tạo bản mô phỏng `control.*` + VIEW để test (xem script
  mô phỏng dưới).
- **MinIO live (đường cũ):** `http://10.50.13.220:9000`, bucket `hotline-tenants`,
  `TENANT_STORE_ENABLED=true`. Dùng để so sánh/đối chứng đường cũ.
- **LLM:** `NOBLE_AGENT_MODEL=gemini-2.5-flash` (+ keys trong `.env`).
- **Script mô phỏng Portal có sẵn** (scratchpad, tham khảo cách seed VIEW + đọc qua RLS):
  `…/scratchpad/tang2_seed_and_read.py` và `…/scratchpad/seed_tenant_config.py` —
  tạo `public.agent_published_config` (VIEW security_invoker, RLS `app.current_tenant`) rồi seed
  1 config publish + đọc lại qua `read_published_config`. Đây là khuôn để mô phỏng Portal khi
  test cho tới khi Portal thật ship VIEW.
- **Client chat qua gateway có sẵn:** `…/scratchpad/gateway_chat_client.py` (dùng `sock=` để gửi
  Host subdomain tới gateway ở localhost, không cần DNS). Recipe pipeline đầy đủ (org→tenant→
  gateway→chat) ở lịch sử session trước; hỏi người dùng nếu cần.
  (scratchpad path gốc: `/tmp/claude-1000/-home-dutn-…/5097aa1a-…/scratchpad/`)

## 8. Trình tự đề xuất

1. Đọc `docs/handoff/spec.md` + `docs/api/SPEC-DB-HIEN-TAI.md` + mục 3-5 file này.
2. Kiểm DB Portal thật: có `agent_published_config`? có đường verify credential cho role agent?
   có `deployment_id` cho agent? → chốt các mục §4 với người dùng.
3. `superpowers:brainstorming` để chốt D1-D5 (§5). Viết spec.
4. `superpowers:writing-plans` → chia slice (đề xuất: **Slice A** = gateway credential/active từ
   Postgres; **Slice B** = ctx/version resolution từ Postgres [bỏ MinIO khỏi worker]; **Slice C**
   = heartbeat → `control.agent_heartbeats`; **Slice D** = dọn MinIO/CLI [tuỳ D5]). Mỗi slice
   giữ gate xanh + đường legacy nguyên.
5. `superpowers:subagent-driven-development` thực thi từng slice.
6. Live smoke: Portal(mô phỏng)-tạo-tenant-trên-Postgres → gateway auth qua Postgres → worker
   compose từ Postgres → chat trả lời, KHÔNG đụng MinIO (verify bằng cách tắt/không tạo object
   MinIO cho tenant đó).

## 9. Bẫy đã biết

- `redis_client._redis_url()` đọc thẳng `os.getenv("REDIS_URL")`, KHÔNG qua settings → chạy
  `python` trần phải `load_dotenv(".env")` với path tuyệt đối (bare `find_dotenv()` fail trong
  heredoc). Server thật (`scripts/run.sh`) tự export `.env`.
- Env var shell **override** `.env` (pydantic-settings). Kiểm `/proc/<pid>/environ` khi "config
  không áp dụng".
- `tenant_id` global-unique, org-prefix `org_<rand8>_<slug>`; `org_of()` parse 2 segment đầu,
  fail-loud với id sai format (vd legacy `noble`). Đường in-wheel/legacy phải né `org_of` (loader
  `_resolve_tenant_dir` đã gate bằng `is_valid_tenant_id`). Giữ pattern này khi đấu Postgres.
- Có 2 transport khởi tạo heartbeat (aiortc `server/http.py` + livekit `worker.py`) — sửa cả hai.
