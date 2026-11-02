# Decision Memo — Single tenant-agnostic Agent: contention & isolation

**Ngày:** 2026-07-31 · **Nhánh:** `feat/agent` · **Trạng thái:** O1–O5 ĐÃ CHỐT · CHƯA triển khai
**Mục đích:** Bàn giao cho một session Claude Code khác bắt đầu triển khai. Memo self-contained — không cần ngữ cảnh hội thoại gốc.

> Cách dùng: đây là **quyết định + ràng buộc + điểm chạm mã**, KHÔNG phải task plan.
> Session nhận nên chạy `superpowers:writing-plans` để biến memo thành plan có task + verify
> trước khi đụng code. Tuân thủ `noble-feature-flow` cho thay đổi non-trivial (nhất là RLS).

---

## 0. ⚠️ PHÂN KỲ — phase này làm gì, KHÔNG làm gì

**PHASE NÀY (đợt bàn giao) = REFACTOR ỨNG DỤNG về kiến trúc "1 agent tenant-agnostic".** Trọng tâm là **de-globalize tenant state** ở tầng code: một codebase phục vụ mọi tenant, tenant được resolve **per-request**, system prompt + tool list nạp theo tenant lúc runtime. Chạy như một deployment bình thường (dev có thể 1 process/container) — **KHÔNG** đụng K8s/KEDA.

**PHASE SAU (KHÔNG thuộc đợt này) = TRIỂN KHAI HẠ TẦNG SCALE:**
- Tách Deployment voice-worker / chat-worker trên K8s.
- **KEDA** autoscale (metric = active-sessions).
- Tinh chỉnh multiprocess worker-pool, prewarm, readiness-gate, graceful-drain.
- **Affinity routing** (consistent-hash theo tenant) nếu runner-cache RAM ở 200 tenant đòi hỏi.
- PgBouncer (chỉ nếu sau này rời Option C).

**RÀNG BUỘC BẮT BUỘC — phase này phải "forward-compatible" để phase sau lắp vào không sửa lại:**
1. **Tenant LUÔN per-request** (dùng `contextvar`), KHÔNG BAO GIỜ process-global. Chạy ở 1 process hay N pod đều giống nhau.
2. **KHÔNG code nào được giả định "process này = một tenant".** Đây là công việc chính (§5b).
3. **Option C pooling** → số connection PG **độc lập số tenant** → scale ra N pod không bùng nổ connection (chính vì O4=200 tenant nên bắt buộc thế này).
4. **Admission-cap đọc từ config (env), thực thi in-process ngay từ phase này** (dù đặt rộng/gần no-op) → phase sau KEDA chỉ việc scale replica theo cùng tín hiệu, không thêm code.
5. **Giữ đường vào voice(LiveKit) và chat(WS) tách bạch** để phase sau biến thành 2 Deployment mà không sửa logic.
6. **RAG loop-safe** (đừng bật hipporag inline) → shared process an toàn ngay bây giờ lẫn khi pod nhồi nhiều phiên hơn ở phase sau.

---

## 1. Bối cảnh & thay đổi kiến trúc

**Hiện tại (Odyssey, xem `docs/odyssey-ht01-flow-tracker.html`):** mỗi tenant = **1 agent container**. Gói cấu hình lưu **MinIO/S3** versioned (SP-C). PG data-plane cách ly per-tenant bằng **login role riêng** + RLS `(tenant_id = current_user)` (SP-E).

**Đổi sang:** **1 agent tenant-agnostic** phục vụ mọi tenant; khác biệt tenant chỉ ở **system prompt + tool list**, nạp runtime theo tenant của client. **Phase 1: chỉ built-in core tool, KHÔNG custom tool.**

**Về latency (đặt kỳ vọng đúng):** gộp agent **không** cải thiện latency *trong* hội thoại (STT/LLM/TTS/RAG y hệt). Lợi thật = cold-start / tenant idle. Rủi ro = contention — memo này giải quyết đúng phần đó.

---

## 2. Phạm vi

**Trong phạm vi — 3 rủi ro của việc gộp + de-globalize (§5b):** noisy neighbor · runner-cache thrash · RLS pooling.

**NGOÀI phạm vi:**
- **Store bundle giữ nguyên MinIO** — **O2 chốt KHÔNG chuyển sang PG** (cache đã che chi phí đọc: version-resolver TTL + materialize-once + `_runners` LRU; đọc PG nhanh hơn nhưng vô nghĩa vì hiếm khi chạm store). Single-agent nạp bundle từ MinIO qua đường SP-C sẵn có, chỉ **keyed thêm theo tenant**.
- Custom tool per-tenant (phase 1 chỉ built-in).
- **Toàn bộ K8s/KEDA/multiprocess-pool** (§0 — phase sau).
- SP-E3 (VIEW `agent_*` + field_policy), SP-E4 (Qdrant per-tenant), P8 (kho thoại) — lát cắt Odyssey chưa làm.

---

## 3. Topology

**PHASE NÀY (ứng dụng):**
```
1 agent tenant-agnostic (deployment thường)
 ├─ voice : CHỈ LiveKit (O1) → framework ĐÃ fork subprocess/job mỗi cuộc gọi
 │          ⇒ cách ly per-call SẴN CÓ · noisy neighbor voice ~thấp · chỉ cần set trần jobs/worker
 └─ chat  : aiortc/WS → 1 process ôm NHIỀU phiên qua async
            ⇒ admission-cap per-process (đọc env, thực thi ngay)
```
- **O1 chốt: KHÔNG dùng browser-WebRTC voice** → mọi voice qua LiveKit → cách ly per-call miễn phí, bỏ hẳn lo ngại voice-aiortc.
- Voice = LiveKit đã multiprocess-per-call sẵn nên **de-globalize (§5b) là việc chính cho cả hai** (voice job-subprocess vẫn phải resolve tenant per-job, không dựa `settings.tenant_id`).

**PHASE SAU (hạ tầng — chỉ để tham chiếu thiết kế, KHÔNG làm bây giờ):**
```
KEDA → scale pod theo active-sessions (KHÔNG theo CPU%)
 ├─ voice-worker (LiveKit)  : trần = max jobs/worker-node
 └─ chat-worker (aiortc/WS) : tách Deployment · grace-drain > cuộc dài nhất · readiness sau warm
```

---

## 4. Rủi ro 1 — Noisy neighbor → QUYẾT ĐỊNH

**Bản chất:** một event loop asyncio đơn luồng cho nhiều tenant → CPU-bound *giữa hai await* block MỌI tenant; GIL không cứu Python thuần. Voice nhạy (deadline khung ~20ms + barge-in) → tiếng giật + cắt lời trễ.

**Đã verify — đường CHAT rất loop-safe:** tải nặng đã offload/remote.
- RAG `flat_store` (mặc định): `search_hybrid` offload thread — `agent/rag/flat_store_adapter.py:100` `run_in_executor(None, _search)`.
- RAG `qdrant`: embed + sparse-encode offload thread; Qdrant awaited-remote.
- On-loop chỉ còn việc nhẹ: jinja render (`agent/runner.py:35`→`agent/prompts/builder.py:69`, ≤`MAX_TOOL_ITERATIONS=7`/lượt), think-strip ×2/token (`agent/llm/client.py:291`+`agent/llm/thinking.py:75`), `to_openai` (`agent/runner.py:39`), tool-json, `catalog.normalize` (<1ms). Post-turn (summary/suggestions/warm) fire-and-forget.

**Quyết định:**
- **Voice (LiveKit): GIỮ NGUYÊN** fork subprocess-per-job (`transport/livekit/worker.py`). Chỉ set **trần = max jobs/worker** (đừng vô trần).
- **Chat: pool nhiều-phiên/process + admission-cap per-process** — env (vd `CHAT_MAX_CONCURRENT_SESSIONS`), **thực thi in-process ngay phase này**; chạm trần → từ chối/readiness=false. Tỷ lệ từ-chối / active-sessions = tín hiệu KEDA **phase sau** dùng lại. Cap rộng tay (chat I/O-bound).
- **Hai điểm phải canh (không phải loop):**
  1. **KHÔNG bật `NOBLE_RAG_BACKEND=hipporag` dưới shared-process** đến khi bọc PPR trong thread. Ngoại lệ CPU-on-loop thật: `agent/rag/hipporag/graph.py:185` `personalized_pagerank` chạy INLINE qua `agent/rag/hipporag/expander.py:142`/`agent/rag/hipporag/adapter.py:145`. Fix ~vài dòng (`run_in_executor`).
  2. **Thread-pool sizing:** RAG offload vào default `ThreadPoolExecutor` dùng chung, bounded (`run_in_executor(None, ...)`) → đây là ranh giới năng lực thật của chat. Cân nhắc executor riêng cho RAG, size theo CPU.

---

## 5. Rủi ro 2 — Runner-cache thrash → QUYẾT ĐỊNH

**Bản chất:** `_runners` là cache **in-process của OBJECT SỐNG** (facade `_runners` OrderedDict, cap 4, LRU — giữ TurnRunner với httpx pool + jinja compiled, **không serialize được, gắn loop**). KHÔNG phải tầng dữ liệu dùng chung → **N process → N cache → tối đa N×/tenant**.

**Quyết định: KHÔNG tách runner cache ở phase này** (init rẻ: prompt text + schemas dict; provider client vốn global một-lần/process). Việc cần làm:
- **Key `_runners` theo `(tenant, version)`** (hiện chỉ theo version).
- **Nâng cap** đủ chứa working-set. **O4 = 200 tenant đồng thời** → phase này (có thể chạy ít process) cap phải đủ lớn (vd ≥256 để phủ 200). Runner rẻ → 200 × nhỏ = chấp nhận được.
- **ĐO trọng lượng per-tenant runner** — nhất là **ProjectNameIndex** (§5b) và artifact RAG. Nếu nặng ở 200 tenant → **phase sau** dùng **affinity routing** (mỗi pod giữ subset tenant), KHÔNG phải shared cache tier. Phase này: đo + set cap, không tối ưu sớm.

---

## 5b. 🔑 CHỦ ĐỀ REFACTOR CỐT LÕI — de-globalize tenant state

Đây là **khối việc lớn nhất của phase này**. Kiến trúc single-tenant hiện tại có nhiều **singleton process-global giả định "1 tenant"** — trong shared multi-tenant chúng vừa **sai logic** (tenant A nhận dữ liệu tenant B) vừa cản scale. Phải audit + chuyển sang **per-request / per-tenant keyed**:

| Trạng thái global (giả định 1 tenant) | Vị trí (cần audit + xác nhận) | Chuyển thành |
|---|---|---|
| `settings.tenant_id` trên data-path | `storage/pg_data_plane.py:221` (`_tenant_id`) | contextvar set ở điểm vào request |
| **ProjectNameIndex module-singleton** | `agent/tools/find_project.py` (`set_index`) — CLAUDE.md ghi "installed into module singleton" | per-tenant (trong runner hoặc keyed theo tenant) — **đây là bug logic nếu để global** |
| `db_project_registry._cache` (registry dự án) | `data/db_project_registry.py` (warm bootstrap) | per-tenant keyed |
| Provider/data-source theo `settings.noble_data_source` | `data/providers/__init__.py` (`get_provider`) | theo tenant context |
| PG pool một-role (`settings.postgres_dsn`) | `storage/postgres_client.py:43` | app role + `SET LOCAL` (Option C, §6) |
| `_runners` keyed theo version | facade `_runners` (`agent/facade.py`) | keyed `(tenant, version)` (§5) |
| `get_tenant_context()` singleton đọc `TENANT_ID` | `tenant/loader.py` (CLAUDE.md) | resolve theo tenant per-request |

**Nguyên tắc:** grep mọi nơi đọc `settings.tenant_id` / `TENANT_ID` / các module-level singleton → mỗi chỗ hoặc nhận tenant qua tham số/contextvar, hoặc cache keyed theo tenant. Bảng trên là điểm khởi đầu, **KHÔNG đầy đủ** — session nhận phải làm một pass audit riêng.

---

## 6. Rủi ro 3 — RLS pooling → QUYẾT ĐỊNH: **Option C** (O3 chốt)

**Ground truth (đã verify) — tầng PG đóng đinh "1 process = 1 tenant":**
- Pool singleton một-DSN-một-role: `storage/postgres_client.py:43` (`create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)`); RLS `(tenant_id = current_user)`.
- Tenant từ process-global: `storage/pg_data_plane.py:221`. Wrapper không nhận tham số tenant.
- Role = tenant_id, per-tenant: `tenant/pg_provisioning.py:22`, `:72`.

**Option C = một app role + `set_config('app.current_tenant', …, true)` + RLS trên `current_setting`.** Chọn vì: **pool-native KHÔNG leak-footgun** (SET LOCAL transaction-scoped, chết theo txn — khác `SET ROLE` session-scoped rò qua tái dùng connection), **fail-closed** (quên set → deny-all), **không cần hạ tầng mới**. **Ở O4=200 tenant, Option C là bắt buộc**: số connection **phẳng** theo số tenant (một pool app-role phục vụ cả 200 qua SET LOCAL) — Option B (pool/tenant) sẽ cần 200 pool = cháy `max_connections`.

**Triển khai — CHÚ Ý O5 (giữ per-tenant role cho Portal/admin):**
Vì Portal/admin **vẫn** dùng per-tenant LOGIN role (RLS qua `current_user`), **KHÔNG được thay** policy `current_user`. **THÊM** một PERMISSIVE policy thứ hai cho app role (nhiều PERMISSIVE policy ⇒ OR):

1. **DDL** (`storage/sql/odyssey_data_plane.sql`), mỗi bảng trong 3 bảng — GIỮ policy cũ + THÊM:
   ```sql
   -- GIỮ NGUYÊN (Portal/admin per-tenant role):
   -- CREATE POLICY tenant_isolation ... USING (tenant_id = current_user) WITH CHECK (tenant_id = current_user);
   -- THÊM (agent runtime app-role):
   CREATE POLICY agent_runtime ON tenant_data.<t>
     USING       (tenant_id = current_setting('app.current_tenant', true))
     WITH CHECK  (tenant_id = current_setting('app.current_tenant', true));
   ```
   Giữ **RLS ENABLE + FORCE**. `true` (missing_ok) → chưa set → NULL → 0 dòng (**fail-closed**).
   - **Định tuyến sạch từng path:** app role có `current_user = <app_role>` (không phải tenant) → clause `current_user` không khớp → chỉ clause `current_setting` áp dụng. Portal role KHÔNG set `app.current_tenant` → NULL → chỉ clause `current_user` áp dụng.
   - **Bẫy phải tránh:** đặt tên app role **khác mọi tenant_id** (nếu trùng, clause `current_user` khớp nhầm). Ghi rõ trong provisioning.
2. **Runtime role:** `POSTGRES_DSN` → **một app role dùng chung**, non-owner, non-superuser, **KHÔNG BYPASSRLS**, GRANT CRUD 3 bảng. (RLS FORCE ⇒ vẫn chịu policy.)
3. **Set tenant per-transaction bằng hàm (KHÔNG string-interpolate `SET`):** asyncpg không parameterize `SET` → dùng
   `SELECT set_config('app.current_tenant', $1, true)` (`true` = is_local, txn-scoped). Tránh injection.
4. **Helper `async with tenant_conn(pool, tenant_id) as conn:`** → acquire → `async with conn.transaction():` → `set_config` → yield. Mọi DAO ở `storage/pg_data_plane.py` (`:39` trở đi) chạy **trong** txn này (hiện execute thẳng trên pool — phải đổi sang conn-trong-txn).
5. **Thread tenant per-request:** giết `settings.tenant_id` (`:221`) → contextvar (gateway đã resolve tenant từ Host/Bearer).
6. **Giữ `tenant_id` tường minh trong query** làm defense-in-depth (WITH CHECK bắt lệch param vs `current_setting`).
7. **Provisioning (O5):** `tenant/pg_provisioning.py` **vẫn tạo per-tenant LOGIN role** cho Portal/admin; **thêm** một app role runtime (một lần, không per-tenant). Runtime path dùng app role; Portal path dùng per-tenant role.

**Latency:** +1 `set_config`/txn, chỉ trên 2 điểm critical-path (bootstrap đầu cuộc: `read_customer_profile`/`read_contact_snapshot`/`read_latest_booking_hint`/`list_conversation_hints`; tool booking: `persist_appointment`). Sub-ms→vài ms, không đáng kể. Rủi ro chính = **tính đúng cách ly**, không phải latency (leak = sự cố chéo tenant / NĐ13).

**Đã loại:** Option A (`SET ROLE`) — leak-footgun cao (quên RESET → rò qua tái dùng connection) + switcher role hóa thân mọi tenant. Option B (pool/tenant) — cháy connection ở 200 tenant, chỉ khả thi sau PgBouncer.

---

## 7. Bằng chứng từ mã (đã inspect)

| Khẳng định | Vị trí |
|---|---|
| PG pool singleton một-DSN-một-role | `storage/postgres_client.py:43` |
| Tenant từ process-global | `storage/pg_data_plane.py:221` (`_tenant_id`) |
| DAO execute thẳng (chưa qua txn set-tenant) | `storage/pg_data_plane.py:39`+ |
| Role = tenant_id, per-tenant LOGIN role | `tenant/pg_provisioning.py:22`, `:72` |
| RAG flat_store offload thread (loop-safe) | `agent/rag/flat_store_adapter.py:100` |
| HippoRAG PPR INLINE trên loop (ngoại lệ CPU) | `agent/rag/hipporag/graph.py:185` ← `expander.py:142` ← `adapter.py:145` |
| Jinja render on-loop ≤7×/lượt | `agent/runner.py:35` → `agent/prompts/builder.py:69` |
| Think-strip ×2/token on-loop (nhẹ) | `agent/llm/client.py:291` + `agent/llm/thinking.py:75` |
| Runner cache in-process LRU cap 4 | facade `_runners` (`agent/facade.py`; CLAUDE.md) |
| LiveKit fork job-subprocess mỗi cuộc | `transport/livekit/worker.py` (`_prewarm`) |
| ProjectNameIndex module-singleton (⚠ per-tenant hazard) | `agent/tools/find_project.py` (`set_index`; CLAUDE.md) |

---

## 8. Quyết định đã chốt (O1–O5)

- **O1 — Voice CHỈ LiveKit, KHÔNG browser-WebRTC.** ⇒ mọi voice cách ly per-call sẵn; bỏ đường voice-aiortc khỏi thiết kế scale.
- **O2 — Store bundle GIỮ MinIO, KHÔNG chuyển PG.** Cache đã che chi phí đọc; single-agent nạp từ MinIO qua SP-C, keyed thêm theo tenant.
- **O3 — RLS = Option C** (app role + `set_config` + `current_setting`, fail-closed).
- **O4 — 200 tenant đồng thời.** ⇒ (a) Option C bắt buộc (connection phẳng); (b) `_runners` cap ≥256 + đo trọng lượng per-tenant; (c) affinity routing để dành phase sau nếu RAM đòi.
- **O5 — GIỮ per-tenant LOGIN role cho Portal/admin.** ⇒ policy `current_user` giữ nguyên, **thêm** policy `current_setting` cho app role (PERMISSIVE OR); tên app role ≠ mọi tenant_id.

---

## 9. Verification / định nghĩa "XONG"

- **Isolation live** (mở rộng `tests/integration/tenant/test_pg_rls_live.py`): dưới **app role + SET LOCAL**, hai tenant trong **cùng pool/process**: A ghi row mình OK; A không ghi được row gắn B (WITH CHECK); B đọc 0 row của A (USING). **+ Portal per-tenant role vẫn hoạt động qua `current_user`** (không bị policy mới phá).
- **Leak test (quan trọng nhất):** mượn connection phục vụ A → trả pool → mượn lại phục vụ B → B **chỉ** thấy dữ liệu B (SET LOCAL không rò qua tái dùng connection).
- **Fail-closed test:** app role không set `app.current_tenant` → mọi query trả **0 dòng**.
- **De-globalize test (§5b):** hai tenant xen kẽ trong một process → mỗi bên nhận **đúng** ProjectNameIndex / registry / prompt / tool-list của mình (không lẫn).
- **Noisy neighbor (đối kháng, có thể để nhẹ ở phase này):** 1 tenant burst → đo p99 tenant khác + event-loop lag.
- **Gate:** `make test-unit` giữ baseline (8 known failures trong CLAUDE.md, **0 new**); `make lint` sạch trên file đụng.
- **Smoke:** `src/noble_agent/SMOKE.md` (chạm turn loop + storage boundary).

---

## 10. Ràng buộc (BẮT BUỘC)

- Nhánh `feat/agent`. **KHÔNG commit/push/PR** nếu không có chỉ thị rõ trong cùng session. **KHÔNG đụng `develop`.**
- `CLAUDE.md` self-maintenance: thay đổi kiến trúc/storage-schema → cập nhật section liên quan (Storage/Postgres, Architecture) + thêm dòng Change Log **trong cùng commit**. RLS policy đổi = storage-schema change.
- Non-trivial (nhất là RLS + de-globalize) → harness `noble-feature-flow` (plan → TDD → review+verify).
- Surgical; giữ semantics best-effort/E05 của wrapper (PG down → no-op, không bịa).
- Giữ mọi cache đã có (version TTL, materialize-once, `_runners` LRU) — chỉ đổi key sang `(tenant, version)`.

---

## 11. Tóm tắt một dòng

- **Phase này = refactor 1-agent + de-globalize tenant state (§5b) + Option C RLS.** K8s/KEDA/multiprocess-pool = **phase sau**, nhưng thiết kế phải forward-compatible (§0).
- **Noisy neighbor:** voice=LiveKit fork sẵn; chat=shared-process + admission-cap in-process; đừng hipporag inline; canh thread-pool.
- **Runner-cache:** key `(tenant, version)`, cap ≥256, đo ProjectNameIndex; affinity để phase sau.
- **RLS:** Option C — thêm policy `current_setting` cho app role, giữ `current_user` cho Portal (O5); `set_config(...,true)`; contextvar tenant; giữ tenant_id defense-in-depth.
