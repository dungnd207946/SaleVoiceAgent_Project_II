# Design: hợp nhất tool dữ liệu cấu trúc — 6 tool → 3 tool

**Ngày:** 2026-09-07 · **Nhánh:** feat/merge-tool-agent · **Trạng thái:** IMPLEMENTED 2026-09-07 (unit + lint xanh so baseline; còn eval full-run + smoke live — xem §8)

## 1. Vấn đề

6 tool cùng đọc một nguồn dữ liệu (`tenant_data.projects` / `units`) và chồng lấn vai trò:
`discover_projects`, `get_project_overview`, `search_units`, `recommend_units`,
`check_inventory`, `analyze_projects`. Hệ quả đo được:

- **Ranh giới routing sống bằng luật model phải học thuộc.** `search_units` vs
  `recommend_units` chỉ khác nhau ở "đã chốt dự án hay chưa" — cả hai description phải
  chở câu "Khác tool kia…", RULES phải chở 2 dòng index riêng, và lịch sử eval
  (2026-08-27 routing giá) cho thấy đây đúng là chỗ model chọn nhầm.
- **`check_inventory` là tập con tuyệt đối của `analyze_projects`** — một câu
  `GROUP BY` trên `agent_units_v`. Hai tool cho cùng một câu hỏi "còn bao nhiêu căn".
- **`get_project_overview` không có tham số nào ngoài `project_code`** — nó là "trang
  chi tiết" của `discover_projects`.
- Mỗi tool thừa là ~1 description chiếm chỗ prompt MỌI lượt của tenant bật nó.

Provider `pg_kb` đã hợp nhất một nửa từ trước: `search_units` phía provider **đã hỗ trợ
`project_code` rỗng = tìm xuyên tất cả dự án** (comment tại `postgres_kb.py:370`), tức
khác biệt search/recommend ở tầng provider chỉ còn là bộ filter + region-rank.

## 2. Giải pháp đã chọn

Gom **6 → 3**, phân vai theo **ý định** chứ không theo bảng, **giữ nguyên tên tool
sống sót** để tối thiểu blast radius (eval golden, [TOOL:x] span, session_facts):

| Tool đích (tên giữ nguyên) | Nuốt | Vai trò sau merge |
|---|---|---|
| `discover_projects` | `get_project_overview` | Khám phá dự án (không mã) / chi tiết một dự án (có mã) |
| `search_units` | `recommend_units` | Tìm & gợi ý CĂN — một dự án hoặc xuyên dự án, kèm phong thủy + upsell |
| `analyze_projects` | `check_inventory` | Tổng quát: thống kê / đếm / so sánh / xếp hạng (SQL) — kiêm luôn tồn kho |

Kết quả: **14 → 11 built-in** (4 core + van xả + 6 optional).

Các hướng đã loại:

- *Một siêu-tool duy nhất (structured params + sql)* — description khổng lồ làm loãng
  routing; mất granularity bật/tắt per-tenant; view `agent_*_v` thiếu cột
  (`amenities`/`overview`/`link_360`…) nên đường SQL không thay được overview/upsell;
  lớp kịch bản sale (headroom, directive, phong thủy, paging, state) nằm trong code,
  SQL không chở được.
- *Đặt tên mới (`find_units`, `explore_projects`)* — sạch về ngữ nghĩa nhưng đổi ~93
  reference trong eval golden + mọi [TOOL:x] span + session_facts, và `find_units` dễ
  nhiễu với `find_project`. Giữ tên cũ: 27+24 reference eval sống nguyên.

## 3. Tool `search_units` hợp nhất

### 3.1 Tham số — union + `scope` bắt buộc

Xung đột phải giải: hôm nay `project_code` RỖNG mang hai nghĩa ngược nhau —
search = "dùng dự án đang quan tâm" (dispatcher auto-fill), recommend = "xuyên tất cả
dự án". Merge phải làm nghĩa này tường minh:

```
scope: enum ["in_project", "all_projects"]   (REQUIRED — precedent: booking.action)
```

- `scope=in_project`: tìm trong MỘT dự án. `project_code` rỗng → dispatcher
  `default_project_code` điền từ hồ sơ như search hiện tại; hồ sơ cũng rỗng → tool trả
  `needs_info` nhắc gọi `find_project` (KHÔNG xổ xuyên dự án oan).
- `scope=all_projects`: xuyên dự án, BỎ QUA hồ sơ (không auto-fill) — hành vi
  recommend hiện tại.

Hướng loại: (b) suy từ có/không `project_code` — model lười điền code → xổ xuyên dự án
khi khách đang focus 1 dự án; (c) auto-fill luôn + cờ `all_projects` — model quên cờ →
gợi ý chung bị bó trong 1 dự án, rỗng oan → escalate oan. Enum bắt buộc rẻ hơn cả hai
lỗi (finding eval 2026-08: arg_accuracy 0.5 — model under-fill arg tùy chọn).

Tham số còn lại = union, giữ nguyên mô tả từng bên:
từ search — `product_type, max_price, area_m2, min_area, max_area, direction, floor,
block, unit_code, sale_status, index`; từ recommend — `region, bedrooms, purpose,
budget_max` (**gộp `budget_max` vào `max_price`** — một tên duy nhất, mô tả "giá tối đa
/ ngân sách, VNĐ THỰC"), và 4 tham số phong thủy `birth_year/gender/menh/zodiac` vẫn
nằm trong overlay `[FENG_SHUI]` (cơ chế gate per-tenant giữ nguyên, chỉ đổi tên tool
được gate trong `build_schemas` từ `recommend_units` → `search_units`).

Union filter chạy được ở CẢ hai scope — khách hỏi "căn hướng Đông Nam tầm 4 tỷ" chưa
chốt dự án nay lọc được hướng (recommend cũ không có filter hướng cứng).

### 3.2 Envelope — hội tụ về dạng nhóm của recommend

Một shape duy nhất cho cả hai scope (dạng recommend là bản mới hơn, đã eval-tune
2026-09-03/04):

```
{ units, upsell_units?, counts{total, shown, feng_shui_match?},
  index, has_more, next_index?, criteria?, instruction, upsell_instruction?,
  feng_shui?, note?, area_band? }
```

Giữ nguyên toàn bộ hành vi đã tune, chỉ hợp cơ chế:

- Paging 6 căn/trang + tiebreak `unit_code` (SQL không ORDER BY) + phân bổ slot
  within/upsell theo độ-liên-quan-giá (`_alloc`, NEAR_BUDGET_RATIO).
- Dải diện tích ±20% quanh `area_m2` + fallback off-target (trước là search-only, nay
  cả hai scope — chỉ kích hoạt khi có tham số diện tích).
- Căn chưa-có-giá: loại khi lọc giá, xếp cuối, `_NO_PRICE_INSTRUCTION`.
- Upsell: headroom `max(500tr, 12%)`, nhóm `upsell_units` + `upsell_instruction` mức
  nhóm ở MỌI lần gọi có upsell (bài học 2026-09-04). **`upsell.unit_pitch` (per-unit,
  kiểu search cũ) bị mồ côi → xoá**; `group_pitch` dùng cho cả hai scope.
- Instruction chốt lượt giữ HAI văn bản theo scope (`_UNITS_NEXT_STEP_INSTRUCTION` cho
  in_project, văn recommend cho all_projects) — hai văn này tune riêng, không trộn.
- Phong thủy: `feng_shui.compute` + guard con-giáp 2 lần + sort hợp-hướng-trước, chạy
  ở cả hai scope khi tenant bật ranker (trước là recommend-only; trong 1 dự án khách
  hỏi "căn nào hợp tuổi" nay cũng ăn).
- `recent_projects.remember` ghi ở cả hai scope (trước recommend-only — search trong
  1 dự án ghi thêm cũng đúng ngữ nghĩa "vừa giới thiệu").
- Provider `None` / total=0 ở trang đầu → `ESCALATE_SIGNAL` như cũ; lật quá trang cuối
  → thông điệp "đã giới thiệu hết", KHÔNG escalate.

### 3.3 Tầng provider — một query, một method

`UnitQuery` + `RecommendQuery` → MỘT dataclass `UnitSearchQuery`:

```
project_code, product_type, max_price_vnd, direction, floor, block, unit_code,
sale_status="available", min_area_built_m2, max_area_built_m2,
bedrooms=0, region="", good_directions=frozenset()
```

`DataProvider.search_units(query: UnitSearchQuery) -> list[Unit] | None` là method duy
nhất (xoá `recommend_units` khỏi Protocol; `Capability.RECOMMEND` gộp vào
`UNIT_SEARCH`). SQL builder trong `postgres_kb.py` = dynamic WHERE của search hiện tại
+ `_region_rank_expr`/`_region_scoped` của recommend + **LIMIT 200 raw candidates**
(search cũ không LIMIT — vá luôn lỗ này; tool sort trước khi cắt trang nên cap thô
không rơi căn tốt, đúng lý do recommend đã làm vậy). `good_directions` KHÔNG lọc SQL
(soft ranking phía tool, như hiện tại).

## 4. `discover_projects` nuốt `get_project_overview`

- Thêm tham số `project_code` (optional): CÓ mã → trả `overview_json` đầy đủ (đường
  `provider.get_overview`, giữ ESCALATE_SIGNAL khi None), các filter khác bị bỏ qua;
  KHÔNG mã → trang khám phá y hệt hiện tại.
- Executor `_discover_projects` gọi `dispatcher.default_project_code` **chỉ khi model
  chủ động truyền trường `project_code`**? — Không: overview cũ auto-fill từ hồ sơ khi
  rỗng. Để giữ được cả hai nghĩa, dùng đúng quy ước schema: description ghi rõ "khách
  hỏi CHI TIẾT một dự án ('X thế nào', 'giới thiệu X', kể cả 'dự án đó') → truyền mã
  (từ find_project hoặc hồ sơ); khám phá danh sách → bỏ trống". KHÔNG auto-fill ở
  executor (auto-fill sẽ giết chết nghĩa "khám phá" mỗi khi hồ sơ đã có dự án).
- `provider.get_overview` + DTO `ProjectOverview` + `ser.overview_json` giữ nguyên.
- Description merge nêu cả hai mode + giữ nguyên kịch bản sale mode khám phá
  (total → 4-5 nổi bật → MỘT lời chốt).

## 5. `analyze_projects` nuốt `check_inventory`

- **Không đổi code** `analytics.py` — chỉ sửa description: thêm "tồn kho một dự án"
  vào danh sách use-case + **ví dụ 3**: "dự án X còn những loại căn nào, giá từ bao
  nhiêu" → `SELECT product_type, COUNT(*) AS so_can, MIN(price_vnd) FILTER (WHERE
  price_vnd > 0) AS gia_tu FROM tenant_data.agent_units_v WHERE project_code = '<mã>'
  AND sale_status = 'available' GROUP BY 1 ORDER BY so_can DESC LIMIT 10`; và cập nhật
  câu "KHÔNG dùng cho" theo tên tool sau merge.
- Xoá: `agent/tools/check_inventory.py`, registration, schema,
  `provider.get_inventory_summary` + DTO `InventorySummary`/`InventoryByType`/
  `InventoryByDirection` + `ser.inventory_json` + `Capability.INVENTORY` (mồ côi).
- Trade-off chấp nhận: câu tồn kho đổi từ deterministic 1-phát sang SQL do LLM sinh
  (thêm ~vài trăm ms + vòng lỗi-sửa hiếm). Đổi lại bỏ được 1 tool + 1 đường provider.
  Guard sẵn có: analyze degrade "tạm không khả dụng" khi role chưa provision.

## 6. Tương thích tên cũ — alias bắt buộc, không chờ Portal

Config đã publish (path `db`) và manifest (path `legacy`) đang chở tên cũ. Thiếu alias
thì deploy xong tenant mất tool im lặng. Thêm bảng alias áp ở **một chỗ duy nhất**
`agent_config.parse_config` (path db) + chỗ loader đọc `manifest.enabled` (path
legacy), dedupe giữ thứ tự canonical, log `warning` mỗi lần gặp tên cũ:

```python
_TOOL_ALIASES = {
    "recommend_units": "search_units",
    "get_project_overview": "discover_projects",
    "check_inventory": "analyze_projects",
}
```

Lưu ý alias `check_inventory → analyze_projects` là một lần NỚI capability (tenant chỉ
bật inventory nay được cả SQL) — chấp nhận được vì an toàn nằm ở 3 khoá DB
(READ ONLY + role 2-view + RLS), không ở tên tool; ghi rõ trong handoff để Portal dọn
config về tên mới rồi gỡ alias sau.

`feng_shui` derive trong `parse_config` đổi `"recommend_units" in enabled_tools` →
`"search_units" in enabled_tools` (sau khi alias đã áp).

## 7. Bảng mối nối phải sửa

| File | Việc |
|---|---|
| `agent/tools/projects_info.py` | Merge `search_units`+`recommend_units` thành một executor; `discover_projects` thêm nhánh overview; xoá hàm `get_project_overview` riêng |
| `agent/tools/check_inventory.py` | Xoá file |
| `agent/tools/upsell.py` | Xoá `unit_pitch` (mồ côi) |
| `agent/tools/schemas.py` | Schema `search_units` mới (union + scope + [FENG_SHUI]); `discover_projects` thêm mode; `analyze_projects` thêm ví dụ tồn kho; gỡ 3 schema cũ; `build_schemas` gate feng-shui theo `search_units` |
| `agent/tools/builtins.py` | 14→11 registration; `_search_units` fill project chỉ khi `scope=in_project` |
| `agent/agent_config.py` | `OPTIONAL_TOOLS` 9→6; `_TOOL_ALIASES`; feng_shui derive |
| `tenant/loader.py` | Áp `_TOOL_ALIASES` cho `manifest.enabled` (path legacy) |
| `data/providers/base.py` | `UnitSearchQuery`; gỡ `RecommendQuery`/`InventorySummary`/`InventoryByType`/`InventoryByDirection`/`UnitRecommendation`; Protocol còn 1 method căn; capabilities gộp |
| `data/providers/postgres_kb.py` | Một `search_units(UnitSearchQuery)`; xoá `recommend_units`/`get_inventory_summary` |
| `data/providers/_serialize.py` | Xoá `inventory_json` |
| `agent/session_facts.py` | Tuple tên `("recommend_units", "search_units")` → `("search_units",)` (hành vi ghi giữ nguyên: chỉ `units`, không ghi `upsell_units`) |
| `agent/context_compaction.py` | Digest: gỡ nhánh `recommend_units` (dòng 57) + nhánh `get_project_overview` (64) → gộp về tên sống sót |
| `persona/chat/RULES.md` + `persona/voice/RULES.md` | Gộp 4 block marker cũ → 3 dòng index mới (`search_units` một dòng cho cả hai ý định; overview vào dòng discover; inventory vào dòng analyze); giữ budget ≤16k/11k |
| `tenants/noble/manifest.toml` | `enabled` sang tên mới (12→9 mục) |
| Tests unit | Gộp `test_search_units_tool.py`+`test_recommend_units_tool.py`; xoá `test_check_inventory.py`, `test_get_project_overview_tool.py` (case overview chuyển vào test discover); cập nhật `test_tool_schemas.py`, `test_builtins.py`, `test_agent_config.py`, `test_dispatcher.py`, `test_sandbox_readonly.py`, `test_brand_and_rankers.py`, provider tests, `test_persona_skeleton.py` |
| Evals golden (`evals/quality/data/cases/`) | Migrate ~93 reference: `recommend_units→search_units` (19), `get_project_overview→discover_projects` (11), `check_inventory→analyze_projects` (10); case nào expect arg `budget_max` đổi theo (`max_price` + `scope`) — sửa bằng script một-lần, review diff tay |
| `SMOKE.md` | Cập nhật mục tool liên quan |

KHÔNG chạm: DB (view/role/GRANT — merge này không cần Portal), `kb_search`,
`get_document`, `send_media`, `booking`, `find_project`, `escalate`,
`update_customer`, `no_lookup_needed`, `availability.py` (đường booking).
Span `[TOOL:search_units]` trong kb_search và danh sách tool trong description
`find_project` chỉ cần rà lại lời văn (tên vẫn hợp lệ), gỡ `check_inventory`/
`get_project_overview` khỏi câu liệt kê của `find_project`.

## 8. Kiểm chứng

**Unit (TDD trước khi merge code):**
- `search_units` hợp nhất: scope=in_project auto-fill / needs_info khi không có mã;
  scope=all_projects bỏ qua hồ sơ; union filter xuyên dự án (direction + region);
  paging + `_alloc` + tiebreak giữ nguyên (port case từ 2 file test cũ, đổi tham số);
  feng-shui guard 2 lần + sort ở CẢ hai scope; area band ở cả hai scope; upsell
  group-style ở scope in_project (case mới).
- Alias: config db chở tên cũ → enabled_tools ra tên mới, dedupe, có warning; manifest
  legacy tương tự; feng_shui derive theo tên mới qua alias.
- `discover_projects` mode overview: có mã → overview_json; không mã → trang khám phá;
  None → ESCALATE_SIGNAL.
- Schemas: `build_schemas` không còn 3 tên cũ; [FENG_SHUI] cắt đúng trên search_units;
  budget persona skeleton còn xanh.
- Provider: một method, LIMIT 200, region-rank, bedrooms filter.

**Eval:** chạy `make eval-quality` full set (100 case, cùng `pinned_version`, cùng
judge) TRƯỚC merge làm baseline → migrate golden → chạy SAU merge; so
`tool_selection`/`policy` — chấp nhận khi không tệ hơn nhiễu đo được của A/B 0.7-vs-0.4
(§9 review doc 27/08). Case tồn kho: thêm 2 case mới expect `analyze_projects`.

**Smoke thủ công (`scripts/chat_repl.py`):** "có 5 tỷ mua căn nào" (all_projects),
"còn căn 2PN nào ở <dự án>" (in_project auto-fill), "dự án X còn loại căn nào"
(analyze), "giới thiệu dự án X" (discover mode overview), "tuổi Tị hợp căn nào trong
dự án X" (feng-shui in_project — hành vi mới).

## 9. Docs cập nhật cùng commit implement

- `CLAUDE.md`: taxonomy 14→11 built-in (6 optional), mục "Adding a new tool" đoạn
  taxonomy, changelog 2 chỗ (bảng 10-entry + `docs/CHANGELOG-agent.md`).
- Handoff cho Portal: danh sách tên tool mới cho `config.tools.enabled` + lộ trình gỡ
  alias (Portal migrate config đã publish xong thì gỡ `_TOOL_ALIASES`).

## 10. Ngoài phạm vi (YAGNI)

- KHÔNG gộp `kb_search`/`get_document` (corpus khác nhau, ranh giới vừa eval-tune).
- KHÔNG nới view `agent_*_v` (không cần cho merge này; là việc Portal).
- KHÔNG thêm mode `sql` vào tool căn — `analyze_projects` là đường SQL duy nhất.
- KHÔNG đổi semcache classification (3 tool đích đều `read_only=True` như các mảnh cũ).
- KHÔNG dọn `tests/prompt_versions/*` (fixture lịch sử, đóng băng).

## 11. Rủi ro còn lại & cách sống chung

| Rủi ro | Mức | Xử lý |
|---|---|---|
| Model điền sai `scope` | Trung bình | Enum bắt buộc + 2 ví dụ trong description (một cho mỗi scope); đo bằng eval tool_selection + arg check |
| Regression eval sau khi gộp description | Trung bình | Baseline trước/sau cùng config version; description mới port NGUYÊN VĂN các câu đã tune, chỉ gỡ câu phân xử search-vs-recommend |
| Tenant db-path chở tên cũ sau deploy | Thấp | `_TOOL_ALIASES` + warning log; handoff Portal dọn config |
| Câu tồn kho chậm hơn / SQL sai vòng đầu | Thấp | Ví dụ tồn kho few-shot trong description; vocab động sẵn có; voice RULES đã có dòng "đọc top 2–3 làm tròn" |
| `check_inventory`-only tenant được nới sang SQL | Thấp | An toàn ở 3 khoá DB; ghi rõ trong handoff |
