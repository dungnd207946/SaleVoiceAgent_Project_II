# Thiết kế: MongoProvider đọc `nbx_*` + nắn lại tool overview/financial

- **Ngày:** 2026-07-23
- **Branch:** `feat/refactor2`
- **Nguồn tham chiếu:** `docs/BA/nbx_projects_ingest_handover.md`, inspect Mongo trực tiếp (`noble_agent` @ `10.50.13.220`)
- **Phạm vi:** 1 spec — 2 phase độc lập. **Phần A** (data-adapter) và **Phần B** (tool reshape) có thể triển khai tuần tự hoặc song song; Phần B provider-agnostic nên không phụ thuộc Phần A.

---

## Bối cảnh & mục tiêu

Job ingest mới ghi dữ liệu dự án vào bộ collection `nbx_*` (mirror NBX Sales API) làm **nguồn sự thật duy nhất**. Adapter Mongo hiện tại (`data/providers/mongo.py`) vẫn đọc schema cũ `project_du_an`/`project_can_ho` (đã "không còn dùng"). Đồng thời tool `get_project_financial` không hiệu quả cho việc hỏi giá.

Mục tiêu:
- **A.** Viết lại `MongoProvider` đọc `nbx_projects` + `nbx_units`, trở thành **bản mirror offline của roster sales_api** (cùng canonical code, cùng DTO, cùng `DataProvider` contract).
- **B.** Chuyển hiển thị **giá** từ `get_project_financial` sang `get_project_overview`; thu hẹp `get_project_financial` (đổi tên `get_financial_policy`) chỉ còn chính sách thanh toán/vay/ưu đãi/phí (luôn hand-off).

## Phát hiện then chốt (inspect data thật)

- `nbx_projects.projectCode` (40/41 có code: ALM, GM, VGP, MEL, IGP…) **trùng khớp** `docs/api/project_code_map.json` → nbx và Sales API cùng roster, cùng shape. MongoProvider chỉ cần join **trực tiếp trên `projectCode`** (case-insensitive), **không cần `catalog.normalize`**.
- `catalog.normalize` không phải sửa: nó đã fallback về `db_project_registry.cached_codes()` → `provider.cached_codes()`, nên nhận code nbx y hệt cách đang làm với sales_api.
- **Data thật lệch spec doc** (spec mô tả shape API lý tưởng):
  - `nbx_units.unitType` là **string viết tắt** (`LK`/`SL`/`ĐL`/`STU`/`HOT`/`KHE`) hoặc `null` (527/614 null), KHÔNG phải `{name, group}`.
  - **Không có field số phòng ngủ**; chỉ suy được `STU`→0.
  - `status` = 100% `"available"` ở dev.
  - `direction` chuỗi bẩn (vd `"Tây Bắc Thông thủy 0 m² -->"`); 508/614 non-null.
  - `price`/`priceTts` theo **tỷ**; `nbx_units` KHÔNG có `priceTttd`/`priceLoan`/`gia_m2`.
  - Join: `nbx_units.projectId == nbx_projects._id` (UUID), 0 orphan; **26/41 dự án có units**.
  - Khác Sales API dev: `nbx_projects` **có** `isHot/isFeatured/sortHot/sortOrder` + `location` + `description` + `overview{}` đầy đủ trong 1 doc.
- Contract không đổi → tool layer, `dispatcher`, `_serialize` (gọi qua `get_provider`) không cần sửa cho Phần A.
- `structured_data.py` giờ là **shim test-only** (tool đã bỏ dùng), nhưng re-export 3 helper private của schema cũ (`_resolve_du_an_id`, `_all_overview_fields_empty`, `resolve_project_ref`) → phải dọn.
- `resolve_project_ref` **không còn caller thực** (media đã chuyển sang HTTP service).

---

# PHẦN A — MongoProvider đọc `nbx_*`

## A.1 Kiến trúc & định vị

Hai provider là hai mirror của cùng nguồn NBX, nói cùng canonical code + DTO:

| Provider | Nguồn | Ghi chú |
|---|---|---|
| `sales_api.py` | NBX Sales API (HTTP) | mặc định hiện tại |
| `mongo.py` (viết lại) | `nbx_projects` + `nbx_units` (job ingest ghi) | bản offline; giàu hơn ở overview/hot-flags |

Bỏ hẳn đường `project_du_an`/`project_can_ho` + `catalog.normalize`. `NOBLE_DATA_SOURCE=mongo` giữ nguyên; mặc định vẫn `sales_api`.

## A.2 Module dùng chung `data/providers/_mapping.py` (mới)

Rút các helper **thuần, không I/O** đang private trong `sales_api.py` ra để cả hai provider import (chống drift giữa 2 mirror):

`to_vnd` · `canon_status` + `_STATUS_MAP` · `region_to_slug` + `_REGION_SLUG_ALIASES` · `fold` · `product_type_matches` + `_PRODUCT_TYPE_KW` · `hot_sort_key` · `bedrooms`

`sales_api.py` sửa để import từ `_mapping` (đổi tên nội bộ, **giữ hành vi y hệt**). Nếu test import trực tiếp tên private của sales_api → giữ alias mỏng trong sales_api hoặc cập nhật test (xử lý ở plan). `test_sales_api_provider.py` phải xanh nguyên trạng sau refactor.

## A.3 Field mapping

**Resolve code:** `nbx_projects.find_one({projectCode: /^CODE$/i})`. **Join units:** `nbx_units.find({projectId: project._id})`.

### `nbx_units` → `base.Unit`

| `base.Unit` | Nguồn | Transform |
|---|---|---|
| `project_code` / `project_name` | (project) `projectCode` / (unit) `projectName` | |
| `unit_code` | `code` | |
| `unit_type` / `unit_type_group` | `unitType` (str/null) | **abbrev map** → (tên, group); `HOT`/`KHE`/null/`""` → `("Khác","")` |
| `bedrooms` | ← `unit_type` đã map | `mapping.bedrooms()`: Studio→0, "2PN"→2… else `None` |
| `area_m2` | `area` (fallback `areaBuild`) | `to_float` |
| `wall_area_m2` | — | `None` |
| `price_vnd` | `price` (tỷ) | `to_vnd` (×1e9) |
| `price_early_vnd` | `priceTts` (tỷ) | `to_vnd` |
| `price_progress_vnd` / `price_loan_vnd` / `price_per_m2_vnd` | — | `None` |
| `direction` | `direction` | strip thô (data bẩn upstream — **chấp nhận**, không cố làm sạch) |
| `floor` / `view` / `max_discount_pct` | — | `None` |
| `status` | `status` | `mapping.canon_status` (dev → 100% available) |
| `image_url` | `image` | `or None` |

**Abbrev map (mongo-local, dựng từ `nbx_apartment_types` + viết tắt quan sát được):**
```
LK → ("Liền kề", "thap_tang")
SL → ("Song lập", "thap_tang")
ĐL → ("Đơn lập", "thap_tang")
STU → ("Studio", "can_ho")
# passthrough tên đầy đủ hợp lệ: "1PN"/"2PN"/"3PN"/"Penthouse"/"Biệt thự"/"Shophouse"… + lấy group tương ứng
# còn lại (HOT / KHE / null / ""): ("Khác", "")
```
`nbx_apartment_types` chỉ dùng để dựng bảng group **tĩnh baked-in**, không query runtime.

### `nbx_projects` → `base.ProjectOverview`

code=`projectCode`, name, region=`areaRegion`, district=`location`, type=`type`, investor, `total_units`=`overview.units_text`, `ownership`=`overview.ownership`, `land_area`=`overview.scale`, `description`=`description` (HTML thô), `product`=`overview.product`; `management`/`handover`/`total_investment_vnd`=`None`. (Trùng mapping overview của sales_api.)

## A.4 Hành vi từng method (giữ nguyên `DataProvider` contract)

- **`list_projects(region)` / `discover_projects(query)`** — quét `nbx_projects`; lọc region (macro slug `region_to_slug` trên `areaRegion`, hoặc fold-match district trên `location`+`areaRegion`), `product_type` (`product_type_matches` trên `type`), `investor` (fold substring trên `investor`). **Rank hot-first thật** bằng `hot_sort_key` (nbx CÓ flags) + tiebreak thứ tự fetch; paginate `offset/limit`. `ProjectSummary.price_from_vnd`=`None`, `hot`=`isHot`. Bỏ doc thiếu `projectCode`.
- **`get_overview(code)`** — map như A.3.
- **`get_pricing` / `get_inventory_summary`** — gom units theo `unit_type`, tổng hợp min/max giá + diện tích + đếm (giống sales_api).
- **`search_units(query)`** — lọc inventory; bỏ `tower`/`floor`/`view` (không có field) thay vì loại hết units.
- **`recommend_units(query)`** — cross-project hoặc scope theo `project_code`; lọc region/budget/bedrooms/available; trả **RAW không cắt** (tool tự sort feng-shui + cắt 6). `None` chỉ khi Mongo down / `nbx_projects` rỗng; region không khớp / filter loại hết → `UnitRecommendation(units=[])`.
- **`get_payment_plans` / `get_loan_policies` / `get_promotions` / `get_project_fees`** → `None` (escalate).
- **Registry:** `warm()` nạp `nbx_projects` → cache `{projectCode: {code,name,region,type}}` (name/region/type từ doc live). `registry_rows`/`cached_codes`/`code_to_name` từ cache; **fallback `_name_code_map`** (`all_codes`/`code_to_name_map`, roster tĩnh đồng bộ sales_api) khi Mongo down. `warm_if_stale(ttl)` debounce như cũ.

## A.5 Dọn coupling (Phần A)

- `structured_data.py`: gỡ re-export 3 helper private đã biến mất (`_resolve_du_an_id`, `_all_overview_fields_empty`, `resolve_project_ref`); **giữ** các hàm public delegating (test còn dùng, đều gọi method provider vẫn tồn tại). `resolve_project_ref` xoá khỏi `__all__` (không caller thực).
- Không đụng `catalog._REGISTRY`, `_serialize.py`, `dispatcher.py`, config/env.

---

# PHẦN B — Nắn lại `get_project_overview` + `get_project_financial`

Provider-agnostic (cả hai nguồn đã có capability `get_overview` + `get_pricing`). Trên **cả hai** nguồn, 4 nhóm chính sách không có nguồn dữ liệu → luôn `ESCALATE_SIGNAL`.

## B.1 `get_project_overview` hấp thụ khoảng giá

Tool gọi cả `provider.get_overview(code)` + `provider.get_pricing(code)`, rồi thêm **khoảng giá tổng** vào payload:

```
{ ...overview_json fields...,
  "price_from_vnd": <min price_from_vnd toàn bộ UnitTypePricing rows | null>,
  "price_to_vnd":   <max price_to_vnd toàn bộ rows | null> }
```

- Khoảng giá = `min(r.price_from_vnd)` / `max(r.price_to_vnd)` trên tất cả row của `get_pricing` (bỏ `None`).
- `get_overview` = `None` → escalate (như cũ).
- Có overview nhưng `get_pricing` = `None` (dự án chưa có units — 15/41) → trả overview, `price_from_vnd`/`price_to_vnd` = `null` (KHÔNG escalate cả overview chỉ vì thiếu giá).
- Description schema đổi: "tổng quan **+ khoảng giá** của một dự án".
- **KHÔNG** nhúng bảng giá chi tiết theo loại căn (đó là việc của `check_inventory`/`search_units`).

## B.2 `get_project_financial` → `get_financial_policy`

- **Đổi tên** tool + hàm Python → `get_financial_policy`.
- `info_type` enum bỏ `pricing`, còn `{payment_plans, loan_policies, promotions, fees}`.
- **Bỏ param `unit_type`** (chỉ phục vụ lọc pricing — đã chuyển đi).
- Mọi `info_type` → gọi method provider tương ứng → `None` → `ESCALATE_SIGNAL` → auto-escalate tự chuyển chuyên viên. Tool = route sạch cho câu hỏi điều khoản tài chính.
- Description: "chính sách thanh toán / vay ngân hàng / ưu đãi / các loại phí — dùng khi khách hỏi điều khoản tài chính của dự án".

## B.3 Ripple đổi tên (Phần B)

- `agent/tools/schemas.py` — key + `name` + description 2 tool; bỏ `unit_type`, sửa `info_type` enum.
- `agent/tools/project_financial.py` — đổi tên hàm `get_project_financial`→`get_financial_policy`, bỏ nhánh `pricing`; `projects_info.get_project_overview` — gộp pricing range.
- `agent/tools/dispatcher.py` — nhánh dispatch theo tên tool.
- `agent/definitions/config.json` — danh sách tool offered.
- `agent/definitions/RULES.md` — hàng tool-catalog (2 tool).
- `_serialize.overview_json` — **giữ nguyên**; khoảng giá được compose **trong tool** `get_project_overview` (thêm `price_from_vnd`/`price_to_vnd` vào dict sau `overview_json(ov)`), để `_serialize` không phụ thuộc pricing.
- Tool count không đổi (rename, không thêm/bớt).

---

## Testing

**Phần A:**
- Mới `tests/unit/unified/providers/test_mongo_nbx.py` (fake in-memory db với `nbx_projects`/`nbx_units`): resolve theo `projectCode`; unit mapping (price×1e9, status, abbrev→type, bedrooms STU→0/else None, priceTts→early); pricing grouping; discover rank hot-first (dùng isHot/sortHot); inventory; recommend (cross + scoped); registry warm + fallback `_name_code_map`; region district fold-match.
- Mới `tests/unit/unified/providers/test_mapping.py` cho `_mapping.py`.
- Di trú fixtures `project_du_an`/`project_can_ho` → `nbx_projects`/`nbx_units` ở: `test_mongo_provider.py` (viết lại/đổi tên), `test_project_financial_mongo.py`, `test_projects_info_mongo.py`, `test_recommend_units.py`, `test_auto_escalate.py`, `test_catalog_db_codes.py`.
- `test_sales_api_provider.py` phải xanh nguyên trạng sau khi tách `_mapping`.

**Phần B:**
- `test_projects_info_mongo.py` (hoặc test overview riêng): overview có `price_from_vnd`/`price_to_vnd`; dự án không units → range `null`, không escalate.
- `test_project_financial_mongo.py` → đổi theo `get_financial_policy`: mọi info_type → escalate; không còn `pricing`/`unit_type`.
- Test tên tool / `load_agent_def` tool set (đảm bảo `get_financial_policy` present, `get_project_financial` gone, count không đổi).

**Verify:** `make test-unit` (đối chiếu baseline pre-existing failures đã biết), `make lint`, code-level smoke `load_agent_def`. Chạy `SMOKE.md` cho phần chạm turn-loop/prompt (đổi tên tool + description).

## Ngoài phạm vi (YAGNI)

`nbx_articles` (RAG/news — không thuộc DataProvider contract) · `nbx_apartment_types` như collection query runtime (chỉ dùng bảng tĩnh) · re-ingest RAG / Qdrant · đổi `catalog._REGISTRY` · làm sạch chuỗi `direction` bẩn (data-quality upstream) · `media_data`/media (đã sang HTTP service riêng) · thêm nguồn dữ liệu cho 4 nhóm chính sách tài chính.

## Rủi ro & lưu ý

- Test import tên private của `sales_api` sau khi tách `_mapping` → giữ alias hoặc sửa test.
- `description` HTML thô trong overview có thể dài; giữ nguyên (tool/prompt xử lý), không strip ở provider.
- `bedrooms` trên nbx gần như luôn `None` (data không có PN) → filter theo số phòng ngủ trên nguồn mongo yếu; là **giới hạn data**, không phải adapter. `recommend_units(bedrooms=…)` sẽ ít khớp — chấp nhận.
- Đổi tên tool là thay đổi prompt-facing → chạy SMOKE + kiểm model gọi đúng tool mới.
