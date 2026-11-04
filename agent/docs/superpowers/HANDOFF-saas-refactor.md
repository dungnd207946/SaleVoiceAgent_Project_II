# Bàn giao — SaaS Refactor (noble-voice-agent)

> Cập nhật: 2026-07-24 · Branch: `feat/refactor2` · HEAD: `ea60833`
> Đọc file này trước khi tiếp tục. Spec gốc: `docs/superpowers/specs/2026-07-23-saas-multi-tenant-provider-tools-design.md`.
> Chi tiết từng lát: các plan `docs/superpowers/plans/2026-07-2{3,4}-saas-*`. Ledger thực thi: `.superpowers/sdd/progress.md`.

## 1. Bối cảnh & mục tiêu

Refactor agent theo hướng **SaaS đa-tenant**. Vấn đề gốc: agent + tool đóng cứng cho 1 provider (Noble) — mismatch giữa **field chuẩn của agent** và **data thực tế mỗi provider**, cộng brand/persona/feng-shui hardcode vào core.

**Mô hình mong muốn:** owner ship agent + bộ tool chuẩn; provider mang data/API; **việc của dev thu về: 1 adapter + khai custom field / custom tool param / custom tool + config tenant** — không đụng core, không đụng tenant khác.

**Quyết định thiết kế đã chốt:** 1 deploy = 1 tenant chọn bằng `TENANT_ID` (code viết sẵn đa-tenant); typed extras bag; extras 2 tier (display + filterable param); shape hiển thị = nhãn VN inline JSON; tenant package `tenants/<id>/`.

## 2. Trạng thái hiện tại — **Pha 1 → Pha 3 ĐÃ XONG** (chưa merge)

Tất cả thực thi bằng subagent-driven-development (TDD, mỗi task implementer + task-reviewer, cuối mỗi lát final-review opus → **"Ready to merge"**). Gate cuối mỗi lát: **ZERO lỗi unit mới** (8 failure baseline cố định: 2 USD-normalize, 2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:', 1 local-.env media). Toàn bộ là **commit local trên `feat/refactor2`**, **chưa merge/push**.

| Pha | Range | Nội dung | Behaviour |
|---|---|---|---|
| **1 — Extras bag** | `668397c..c5054b2` | `ExtraFieldSpec` + `extras: dict` trên `Unit`/`ProjectOverview`; `provider.extra_specs`; serializer nhãn VN inline (shape A) qua `active_extra_specs()`; `builder.render_extras_appendix()` gộp phụ lục vào `customer_block`. Demo: nbx `fundType`→`fund_type`. | Additive; đường extras rỗng byte-identical |
| **2 — Custom filter param (Tier-2)** | `5c77939..762c2a7` | `ToolParamSpec` (tool/name/type/desc/maps_to/match/enum) + `UnitQuery.custom_params` + `provider.tool_params`; engine thuần `agent/tools/custom_params.py` (`collect` + `filter` 6 toán tử `eq/substring/gte/lte/exists/contains`); `active_tool_params()`; `build_schemas()` bơm param vào schema; `search_units` gom + lọc `extras[maps_to]` (safety net). Demo: nbx `fund_type` filterable. | Additive; path rỗng byte-identical |
| **3a+3b — TenantContext + persona** | `b6f174d..2122a53` (+`7eac2c1`) | `tenant/context.py` (`TenantContext` frozen) + `tenant/loader.py` (`get_tenant_context()` singleton, `TENANT_ID`→`tenants/<id>/manifest.toml` qua `tomllib`, fail-loud); `tenants/noble/manifest.toml`; git-mv `agent/definitions/*`→`tenants/noble/persona/*`; `load_agent_def(persona_dir,*,tool_names)` (tool list từ `manifest.enabled`, bỏ `config.json` "tools"); facade dựng agent từ ctx. | Identical cho `TENANT_ID=noble` |
| **3c — ToolSpec registry + custom tools** | `59ba766..d4c8e52` | `agent/tools/registry.py` (`ToolSpec` keyed `(tenant,name)` + `resolve`), `builtins.py` (15 tool chuẩn `tenant="*"` qua adapter — nhà mới của cờ `dirties_customer`/`read_only`); dispatcher `_exec`→registry (outer `dispatch()` invariants byte-identical); semcache đọc `read_only` từ registry; `loader._import_tenant_tools` walk `tools/` bằng pkgutil → thả 1 file tự đăng ký; isolation chứng minh bằng tenant in-package `tenants/demo_acme/`. | Identical cho 12 tool chuẩn |
| **3d — Brand neutralization** | `bd6c49d..ea60833` | Rename tool `noble_search`→`kb_search` (module RAG nội bộ giữ tên); brand templating `{{ brand.company }}`/`{{ brand.app_name }}` trong tool descriptions + SOUL (render từ `ctx.brand`, không rò token thô, "Noble Crystal"/RULES giữ nguyên); feng-shui = ranker tùy chọn (`build_schemas` gỡ params + executor skip overlay khi `feng_shui ∉ ctx.rankers`). | Identical cho `TENANT_ID=noble` (brand→Noble/NobleX, feng_shui ON) |

**Kết quả:** tenant mới = **1 `manifest.toml` + 1 persona dir** + (tùy chọn) adapter / custom field (Pha 1) / filter param (Pha 2) / custom tool (3c). Persona/tool-list/brand/data_source/rankers khai trong manifest; brand + feng-shui đã trung tính. `tenants/demo_acme/` là ví dụ tenant thứ hai (inert, chỉ chạy nếu `TENANT_ID=demo_acme`).

**Kiến trúc chốt (đọc trước khi sửa tiếp):**
- `src/noble_agent/tenant/` — `context.py` (`TenantContext`), `loader.py` (`get_tenant_context()` singleton, mirror `get_settings()`).
- `src/noble_agent/tenants/<id>/` — `manifest.toml` (`data_source`, `[tools].enabled`, `rankers`, `media_channel`, `[brand]`, `persona_dir`) + `persona/` (SOUL/RULES/PROMPT_TEMPLATE/CUSTOMER_PROFILE/config.json) + `tools/*.py` (custom tool `@tool`-decorated). **Nằm trong package** (ship theo wheel; lệch có chủ đích so với sơ đồ top-level của spec).
- `src/noble_agent/agent/tools/` — `registry.py` + `builtins.py` (dispatch table), `schemas.py::build_schemas(names)` (3 pass: inject tool_params → strip feng-shui theo rankers → render brand + guard token dư), `custom_params.py` (engine lọc Tier-2).
- `data/providers/` — `base.py` (DTO + `ExtraFieldSpec` + `ToolParamSpec` + Protocol), `__init__.py` (`get_provider`/`active_extra_specs`/`active_tool_params`), `nbx_mongo.py` (provider mặc định, khai `extra_specs`+`tool_params` demo).

## 3. Việc cần làm (lộ trình còn lại)

> ⚠️ **CHƯA merge/push.** Rule repo cấm merge/push/PR/đụng `develop` khi user chưa ra lệnh rõ trong cùng session.

### A. Bắt buộc trước khi tin dùng prod
- **Smoke `/chat` thật** (theo `src/noble_agent/SMOKE.md`) — Pha 3 chạm prompt-build + boot + dispatch. Xem mục 5 để chạy. Verify: `kb_search` chạy RAG; brand hiện "NobleX" (không lòi `{{ }}`); `discover_projects`/`search_units`/`recommend_units`(phong thủy)/`send_media` OK; 12 tool đúng.
- **Quyết định số phận nhánh** (merge / PR / giữ) — chờ lệnh user.

### B. Các phần đã HOÃN có chủ đích (chưa bắt đầu — là lát kế tiếp)
1. **Provider-through-`TenantContext` cutover** — hiện `get_provider()` vẫn đọc `settings.noble_data_source`; `manifest.data_source` chỉ mirror (có test canh). Spec muốn `get_provider()` → `ctx.provider`. Rủi ro: phá các test `NOBLE_DATA_SOURCE=x` → cần cho ctx honor env override HOẶC cập nhật test. Làm thành lát riêng.
2. **Dời core field Noble-specific → extras** (spec Part 1: `wall_area_m2`, `price_early_vnd`, `price_progress_vnd`, `price_loan_vnd`, `max_discount_pct`, `view`, `image_url`). DTO change rủi ro, chạm serializer + mọi provider — orthogonal với tenant isolation, để riêng.
3. **media_channel full abstraction** — hiện mới template tên app trong `send_media`; chưa có channel routing (`media_channel="none"` → tắt gửi, hay channel khác). Manifest đã có `media_channel` (declared-not-consumed).

### C. Pha 4 (roadmap) — provider thứ hai chứng minh isolation
- Thêm 1 tenant/provider thật (không phải Noble) chỉ bằng adapter + manifest + persona + (tùy chọn) custom tool/field, KHÔNG đụng core. `tenants/demo_acme/` đã là khung mẫu.
- SMOKE case đa-tenant: đổi `TENANT_ID` → chạy tenant khác.

## 4. Ràng buộc BẮT BUỘC giữ (từ CLAUDE.md)
- **Không đụng `develop`** (checkout/merge/push/fetch). Không `worktree add`/`merge`/`rebase --onto`/`push`/`gh pr create` khi chưa có lệnh rõ. Commit local trên feature branch thì OK.
- Commit message kết thúc bằng: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Trả lời user bằng tiếng Việt.**
- Non-trivial → dùng skill superpowers workflow (brainstorm → writing-plans → subagent-driven-development) hoặc `noble-feature-flow`. Trivial (≤1–2 file, text/config/prompt) → làm trực tiếp.
- **Behaviour-identical cho `TENANT_ID=noble`** là bất biến của mọi lát Pha 3 — mọi refactor phải giữ (dùng test cũ làm gate).
- Cập nhật `CLAUDE.md` (bảng layout + Change Log) trong cùng commit khi đổi kiến trúc/tool/schema.

## 5. Cách chạy thử (text chat, không cần audio)

Môi trường đã sẵn: `.venv` cài `noble_agent`; `.env` có `USE_UNIFIED_AGENT=true`, `NOBLE_DATA_SOURCE=nbx`, `NOBLE_RAG_BACKEND=qdrant`, `TRANSPORT_BACKEND=aiortc`, `WS_PORT=8766`, đủ LLM key; `TENANT_ID` không đặt → mặc định `noble`. Services (Mongo/Qdrant/embed) trỏ stack hosted `10.50.13.220`.

```bash
cd ~/Documents/Hotline-Agent/santa-hotline-agent
source .venv/bin/activate
scripts/run.sh              # hot-reload (hoặc --no-reload)
# Mở http://localhost:8766/chat  — mỗi tab = 1 session (nối lại: ?session=<id>)
```

**Cạm bẫy đã biết:**
- **Cổng 8766 kẹt / code cũ:** nếu đã có server chạy (nhất là chạy từ hôm trước), nó phục vụ **code cũ** → phải dừng và chạy lại để test thay đổi mới. `ss -ltnp | grep :8766` để tìm pid, `kill <pid>`, rồi chạy lại. (Đúng tình huống lúc bàn giao: server chạy từ 23/07 giữ cổng — đã restart bằng code hiện tại, boot sạch: Qdrant 112 điểm, Mongo OK, nbx warmed 40 dự án.)
- **Test hồ sơ theo SĐT:** `NOBLE_SIMULATE_PHONE=true` cấp số ngẫu nhiên (0-hit DB). Đặt `NOBLE_SIMULATE_PHONE_NUMBER=<số có thật trong customers/bookings_flat>` để test lookup, rồi restart.
- Console script `noble-agent` có thể lỗi — dùng `scripts/run.sh` (đã set `PYTHONPATH`).
- Env export ở shell **thắng** `.env` (pydantic-settings) — nếu config "không ăn", kiểm `/proc/<pid>/environ`.

## 6. Tài liệu tham chiếu
- Spec tổng: `docs/superpowers/specs/2026-07-23-saas-multi-tenant-provider-tools-design.md` (Part 1 extras, 2 custom-param, 3 tool-set/brand, 4 registry/custom-tool, 5 persona, 6 loader).
- Plans: `docs/superpowers/plans/2026-07-2{3,4}-saas-phase*.md` (1 extras-bag, 2 custom-params, 3ab tenant-context-persona, 3c registry-custom-tools, 3d brand-neutralization).
- Ledger thực thi (mọi task + commit + gate + Minor): `.superpowers/sdd/progress.md`.
- Contract provider: `docs/BA/spec_provider.md`. Handover nbx: `docs/BA/nbx_projects_ingest_handover.md`.
- Change Log chi tiết từng row: `CLAUDE.md` mục `## Change Log` (các row 2026-07-23/24).
