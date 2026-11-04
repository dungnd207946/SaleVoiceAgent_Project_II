# HANDOFF — Single-agent multi-tenant refactor (Plan 1 done, Plans 2+3 remain)

**Ngày:** 2026-07-31 · **Nhánh:** `feat/share-agent` · **HEAD:** `fa9e2c6` (local, CHƯA push)
**Mục đích:** Bàn giao cho session Claude Code khác tiếp tục. Self-contained — không cần ngữ cảnh hội thoại gốc.

> Đọc thứ tự: (1) mục §0–§3 dưới đây, (2) memo gốc, (3) plan file của phần bạn sắp làm.
> Dùng harness **superpowers:subagent-driven-development** để chạy tiếp (đã dùng cho Plan 1).

---

## 0. TL;DR — đang ở đâu

Refactor "1 agent tenant-agnostic" (memo: `docs/superpowers/specs/2026-07-31-single-agent-multitenant-decision-memo.md`) đã chia thành **3 plan tuần tự**:

| Plan | File | Trạng thái |
|---|---|---|
| **1. Contextvar spine + de-globalize (§5b)** | `docs/superpowers/plans/2026-07-31-tenant-contextvar-deglobalize.md` | ✅ **XONG** — 12 commit, final review APPROVE (opus) |
| **2. Option C RLS pooling (§6, O3)** | `docs/superpowers/plans/2026-07-31-rls-option-c-pooling.md` | ⏳ CHƯA làm — dựng trên contextvar Plan 1 |
| **3. Noisy-neighbor guards (§4)** | `docs/superpowers/plans/2026-07-31-noisy-neighbor-guards.md` | ⏳ CHƯA làm — độc lập, không cần PG |

**Việc của bạn:** chạy **Plan 2** rồi **Plan 3** (hoặc Plan 3 trước — nó độc lập). Cả hai plan file đã có task + code + verify chi tiết (no-placeholder). Đừng viết lại plan; thực thi nó.

---

## 1. Ràng buộc BẮT BUỘC (giữ nguyên qua mọi plan)

- Nhánh **`feat/share-agent`**, KHÔNG worktree (người dùng đã chốt). **Commit local mỗi task, KHÔNG push / KHÔNG PR / KHÔNG đụng `develop`.** (Người dùng đã cho phép commit local per-task.)
- **Tenant LUÔN per-request qua `ContextVar`, KHÔNG process-global.** Fallback `settings.tenant_id` khi contextvar chưa set → single-tenant dev **byte-identical**.
- **Surgical.** Chỉ sửa cái task yêu cầu. Giữ mọi cache đã có (version TTL, materialize-once, `_runners` LRU) — chỉ đổi KEY sang có tenant.
- **CLAUDE.md self-maintenance:** thay đổi kiến trúc/storage-schema → cập nhật section liên quan + thêm 1 dòng Change Log **trong cùng commit**. RLS policy đổi = storage-schema change.
- Gate: `make test-unit` giữ baseline (xem §5), **0 new**; `make lint`/`ruff check` sạch trên file đụng.
- Non-trivial (nhất là RLS) → harness `noble-feature-flow` (plan→TDD→review+verify). Đã dùng subagent-driven-development cho Plan 1.

---

## 2. Plan 1 đã build gì (contract mà Plan 2+3 DỰA VÀO)

**Spine mới — `src/noble_agent/tenant/current.py`:**
```python
def set_current_tenant(tenant_id: str | None) -> Token      # returns token for reset
def reset_current_tenant(token) -> None
def current_tenant() -> str          # contextvar value, else get_settings().tenant_id
@contextmanager
def use_tenant(tenant_id: str | None) # set on enter, reset on exit (empty/None = inherit)
```
**QUY TẮC VÀNG cho Plan 2+3:** trên đường request/data, KHÔNG đọc `settings.tenant_id` — gọi `current_tenant()`. Nếu code chạy ngoài turn (vd background task tạo NGOÀI scope), phải bọc `use_tenant(...)` hoặc nhận tenant qua tham số.

**Đã keyed theo tenant (Plan 1):**
- `tenant/loader.py::get_tenant_context()` — dict `_ctx_by_tenant`, resolve qua `current_tenant()`. Chữ ký no-arg giữ nguyên.
- `agent/tools/find_project.py` — `_INDEX_BY_TENANT`; `set_index(idx, *, tenant=None)` / `get_index(*, tenant=None)` (None→current_tenant()).
- `data/providers/__init__.py` — `_INSTANCES` keyed `(tenant, source)`; **source từ `get_tenant_context().data_source`** (manifest), fallback `settings.noble_data_source`.
- `agent/facade.py` — `_runners: OrderedDict[tuple[str,int], TurnRunner]` cap **256**; `_legacy_runners: dict[str, TurnRunner]` (version 0 per-tenant); `_get_runner(tenant_id)`, `_resolve_current_version(tenant_id)`, `_build_runner_for_version(tenant_id, version)`, `_get_runner_for_version(tenant_id, version)`, `ensure_version_built(version, *, tenant_id=None)`.
- **`NobleAgent`** — `create(session_id, customer=None, *, tenant_id=None)` capture tenant (→ `self.tenant_id`); MỌI method chạy runner work bọc `with use_tenant(self.tenant_id)` (`stream_response`/`ensure_session_started`/`suggest_followups`/`set_customer_fields`).
- Entry boundary: voice `transport/livekit/worker.py::entrypoint` set contextvar từ `_job_tenant(caller.metadata, settings.tenant_id)`; chat `server/text_chat.py::handle_text_session(ws, sid, *, tenant_id=None)`.

**CÒN process-global CÓ CHỦ Ý (infra phase, ĐỪNG đổi trong Plan 2/3):** `agent_dispatch_name(settings.tenant_id)` ở worker registration + heartbeat emitter (`server/http.py:1027`, `worker.py:294/322`) + `app_session.py:241`. RAG corpus (`query_noble_kb`) + `catalog._REGISTRY` cũng còn global (isolation RAG = tương lai, ngoài scope 3 plan này).

---

## 3. Quyết định/ruling đã chốt (ĐỪNG mở lại)

1. **Provider source = manifest-driven** (memo §5b): `get_tenant_context().data_source` thắng `NOBLE_DATA_SOURCE`; env chỉ là fallback cho tenant KHÔNG bundle. Production KHÔNG đổi hành vi (noble manifest=`nbx`=default). **Hệ quả test:** mọi test ép `NOBLE_DATA_SOURCE=mongo` phải pin thêm `monkeypatch.setenv("TENANT_ID", "_no_bundle_test_tenant")` để `get_tenant_context()` raise → fallback về settings. (4 file đã pin: test_factory / test_project_financial_mongo / test_projects_info_mongo / test_recommend_units / test_db_project_registry.)
2. **⚠️ MERGE NOTE quan trọng cho Plan 2:** `storage/pg_data_plane.py::_tenant_id()` (dòng ~221) VẪN đọc `settings.tenant_id` — đây CHÍNH LÀ việc Plan 2 phải sửa (→ `current_tenant()`). **ĐỪNG bật multi-tenant PG writes cho tới khi Plan 2 xong.** Hôm nay inert (PG wrappers no-op khi chưa provision role + `POSTGRES_ENABLED=false`).
3. Workspace: `feat/share-agent`, không worktree, commit local per-task, không push. (Nếu Plan 2/3 muốn worktree → phải hỏi lại người dùng: CLAUDE.md cấm `git worktree add` không có chỉ thị.)

---

## 4. CÁCH RESUME bằng subagent-driven-development

**SDD workspace của MỖI plan riêng.** Plan 1 ở `.superpowers/sdd/2026-07-31-tenant-contextvar-deglobalize/` (ledger `progress.md` + brief/report/diff mỗi task) — có thể đọc để tham khảo, nhưng Plan 2/3 tạo workspace MỚI.

Scripts của skill (base: `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.2.0/skills/subagent-driven-development/scripts/`):
```bash
SKILL=~/.claude/plugins/cache/claude-plugins-official/superpowers/6.2.0/skills/subagent-driven-development
PLAN=docs/superpowers/plans/2026-07-31-rls-option-c-pooling.md      # (hoặc noisy-neighbor)
bash "$SKILL/scripts/sdd-workspace" "$PLAN"           # → in ra thư mục workspace của plan
bash "$SKILL/scripts/task-brief"    "$PLAN" <N>       # → trích brief task N ra file
bash "$SKILL/scripts/review-package" "$PLAN" <BASE> <HEAD>   # → diff cho reviewer
```

**Vòng lặp mỗi task (đã dùng cho Plan 1, chạy trơn):**
1. Ghi BASE = `git rev-parse --short HEAD` TRƯỚC khi dispatch.
2. `task-brief` → dispatch 1 implementer subagent (general-purpose, model `sonnet`; task lớn/rủi ro → review bằng `opus`). Dispatch gồm: brief path (nguồn requirement), context từ task trước, report-file path. KHÔNG dán cả plan.
3. Implementer trả DONE → `review-package BASE HEAD` → dispatch task-reviewer (spec ✅ + quality). Reviewer nhận: brief + report + diff + global constraints.
4. Finding Critical/Important → fix loop (resume implementer qua **SendMessage** tới agentId của nó, gửi finding verbatim) → scoped re-review (`review-package FIX_BASE HEAD`). Minor → ghi ledger "deferred", KHÔNG vào loop.
5. Sạch → ghi ledger `Task N: complete (commits <base7>..<head7>, review clean)`, mark todo.
6. Xong hết task → final whole-branch review (opus, `review-package <plan-start> HEAD`) → chỉ 1 fix wave nếu có → finishing-a-development-branch (NHƯNG nhớ ràng buộc không push).

**Bài học từ Plan 1 (áp cho Plan 2/3):**
- Khi đổi tên/xoá symbol module-global HOẶC đổi chữ ký hàm: BẮT implementer `grep -rn` toàn `src/ tests/` cho symbol đó + chạy các test file liên quan (KHÔNG chỉ test của task). Plan 1 dính 3 regression kiểu này (test_brand_and_rankers, mongo-source fixtures, synthetic/*) — đều do test/caller ngoài file của task.
- Bắt implementer chạy **full unit suite** và so baseline, không chỉ test task.

---

## 5. Baseline test (để phân biệt "new failure" vs đã đỏ sẵn)

- Chạy: `source .venv/bin/activate && make test-unit` (hoặc `python -m pytest tests/unit -q`). `asyncio_mode=auto`.
- **Baseline hiện tại (sau Plan 1): ~1629 passed / 11 failed / 1 skipped.** 11 đỏ đã-biết, KHÔNG phải do refactor: 2× `test_normalize_for_voice` (USD), 2× `test_tool_ack` (flaky timing — pass 6/6 khi chạy riêng), `test_vieneu_vllm` (chat-format), 2× `test_qdrant_adapter`, `test_qdrant_store`, `test_prompt_builder` ('Tên:'), `test_send_media` (local .env), `test_project_financial_mongo` (pricing filter). "0 new" = số đỏ mới ngoài danh sách này = 0.
- Live PG test dùng marker `needs_postgres` + env `SPE_PG_ADMIN_DSN` (superuser DSN). File: `tests/integration/tenant/test_pg_rls_live.py`.

---

## 6. Plan 2 — Option C RLS (tóm tắt để vào việc nhanh; chi tiết ở plan file)

**Mục tiêu:** 1 app-role pool phục vụ mọi tenant, cách ly per-txn bằng `set_config('app.current_tenant', <t>, true)` + policy RLS trên `current_setting`. Connection phẳng theo tenant (O4=200).

**6 task:** (1) DDL thêm policy `agent_runtime` (`current_setting`) GIỮ `tenant_isolation` (`current_user`, cho Portal — O5), RLS ENABLE+FORCE, trong `storage/sql/odyssey_data_plane.sql` (vòng DO $$ dòng ~83-94). (2) `tenant/pg_provisioning.py`: `ensure_app_role` (1 role dùng chung, NOBYPASSRLS, CRUD) + `assert_app_role_distinct` (tên ≠ mọi tenant_id — bẫy). (3) `storage/postgres_client.py`: `tenant_conn(pool, tenant_id)` = acquire→txn→`set_config(...,true)`→yield. (4) `storage/pg_data_plane.py`: `_tenant_id()`→`current_tenant()`; mỗi wrapper chạy DAO trong `tenant_conn`. (5) `.env.example`/config `POSTGRES_APP_ROLE`. (6) Live gate: isolation + **leak-on-reuse** (pool size 1, đổi scope A→B, B thấy 0 row A) + fail-closed (chưa set → 0 row) + Portal per-tenant role vẫn chạy.

**Cần từ người dùng:** `SPE_PG_ADMIN_DSN` (Postgres 16 superuser) cho live gate. Nếu chưa có → làm code + unit test trước, hoãn live gate (report rõ).

**Điểm chạm code thật (đã verify khi viết plan):** pool `postgres_client.py:43` (`create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)`, KHÔNG có init hook); DAO execute thẳng trên pool (chưa có txn) `pg_data_plane.py:39+`; RLS policy hiện tại `USING (tenant_id = current_user)` `odyssey_data_plane.sql:83-94`; provisioning role=tenant_id `pg_provisioning.py:22,72`; live test connect per-tenant DSN `test_pg_rls_live.py` (env `SPE_PG_ADMIN_DSN`).

---

## 7. Plan 3 — Noisy-neighbor (độc lập, KHÔNG cần PG)

**3 task:** (1) `agent/rag/hipporag/adapter.py:145` — `expander.expand(...)` INLINE trên event loop → bọc `await loop.run_in_executor(None, lambda: expander.expand(...))` (PPR là CPU-on-loop duy nhất; đã verify inline). (2) `server/admission.py` mới — `ChatAdmission` (counter async-safe) + config `CHAT_MAX_CONCURRENT_SESSIONS` (default 200) + enforce trong `handle_text_session` (admit/release). (3) readiness `http.py` phản ánh `at_capacity` + docs/CLAUDE.md. **Voice KHÔNG đụng** (LiveKit đã fork-per-job). Có thể làm Plan 3 TRƯỚC Plan 2 (không phụ thuộc).

---

## 8. Deferred minors (Plan 1 — final review nói "fine to defer", ghi lại để đừng quên)

- `tenant/current.py` `use_tenant` nhánh inherit hơi khó đọc (cosmetic).
- Thiếu test path restore-on-exception cho `use_tenant` (code có try/finally — đúng cấu trúc).
- `agent/tools/find_project.py:4` docstring còn chữ "singleton" (giờ per-tenant).
- `tenant/heartbeat.py:129` `ensure_version_built(version)` warm `settings.tenant_id` không phải `self._tenant` — inert hôm nay (2 bằng nhau); sửa khi có per-tenant heartbeat fleet.
- `NobleAgent.create` param `customer` unused (pre-existing).
- (Review cuối thêm) `_legacy_runners` unbounded — chỉ lo nếu nhiều store-disabled tenant chung 1 process (lý thuyết).

---

## 9. Con trỏ nhanh

- Memo gốc (quyết định O1–O5): `docs/superpowers/specs/2026-07-31-single-agent-multitenant-decision-memo.md`
- 3 plan file: `docs/superpowers/plans/2026-07-31-{tenant-contextvar-deglobalize,rls-option-c-pooling,noisy-neighbor-guards}.md`
- Ledger Plan 1 (đọc để hiểu từng quyết định): `.superpowers/sdd/2026-07-31-tenant-contextvar-deglobalize/progress.md`
- CLAUDE.md: đã cập nhật section `tenant/` (per-request note) + 1 Change Log row 2026-07-31 cho Plan 1.
- Lưu ý môi trường (từ memory): shell env export ĐÈ `.env` (pydantic-settings); RTK hook làm hỏng output text của grep/diff/git-show → dùng Read tool hoặc `rtk proxy` khi cần ground truth.
