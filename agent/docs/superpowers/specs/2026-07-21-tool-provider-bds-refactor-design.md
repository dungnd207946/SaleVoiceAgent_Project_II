# Tool + Provider Refactor cho BĐS coverage — Design

**Trạng thái:** Draft v1 · **Ngày:** 2026-07-21 · **Branch:** `feat/refactor2`

Refactor tầng **tool** + **provider** để agent (Luna) phủ được các nhóm câu hỏi BĐS thực tế
và **chuyển nguồn dữ liệu mặc định sang `sales_api`**. Design này KHÔNG viết lại contract —
nó bám theo và (ở đúng 1 chỗ) **mở rộng** hai spec BA:

- Contract dữ liệu: [`docs/BA/spec_provider.md`](../../BA/spec_provider.md)
- Bản đồ câu hỏi ↔ tool: [`docs/BA/spec_tool.md`](../../BA/spec_tool.md)

## Bối cảnh (đã có sẵn)

- `data/providers/{base,mongo,sales_api}.py` + factory `__init__.get_provider` đã tồn tại và
  bám contract. 10 tool core đã chạy. `db_project_registry` là facade delegate về provider.
- RAG (`noble_search`) đã được re-ingest theo roster mới (user xác nhận 2026-07-21) → điều kiện
  tiên quyết để bật `sales_api` đã thỏa. **RAG re-ingest OUT OF SCOPE** của design này.

## Quyết định phạm vi (đã chốt với user)

1. **Mục tiêu = hoàn thiện `sales_api` VÀ flip `NOBLE_DATA_SOURCE` sang `sales_api`.**
2. **Thêm tool thứ 11 `check_inventory`** (spec_tool §4.1), implement trên **cả** `sales_api` và `mongo`.
3. **Thêm 4 mốc giá thanh toán** (`price`/`priceTts`/`priceTttd`/`priceLoan`) vào dữ liệu giá.
4. Deferred: floor/building, CSBH/loanInfo/promotions/progress (rỗng 0/437 trên dev → escalate/RAG).

---

## Part 1 — Hoàn thiện provider `sales_api`

Tất cả thay đổi nằm trong `data/providers/sales_api.py` (+ DTO ở `base.py`, serialize ở `_serialize.py`).

### 1.1 Fix `get_overview` — `overview` là chuỗi JSON double-encoded (BUG)

spec_provider §9: field `overview` của `GET /projects/{slug}` là **CHUỖI JSON**, không phải object.
Code hiện tại `ov = doc.get("overview") or {}` → luôn ra `{}` (vì value là `str`) → `total_units`,
`ownership`, `land_area` **âm thầm rỗng**. Lỗi này chỉ lộ khi flip sang sales_api.

**Fix:** decode có phòng vệ:
```python
raw_ov = doc.get("overview")
ov = raw_ov if isinstance(raw_ov, dict) else _safe_json_obj(raw_ov)  # str → json.loads, lỗi → {}
```
`_safe_json_obj` trả `{}` khi parse fail (không raise). Keys dùng: `units_text`, `ownership`,
`scale`, `product`.

### 1.2 Field mới `product` cho overview (loại hình sản phẩm) — MỞ RỘNG CONTRACT

`overview.product` (vd `"Căn hộ, nhà phố, biệt thự, shophouse"`) phục vụ câu hỏi #2. Thêm field
canonical:
- `base.ProjectOverview.product: str | None = None`
- sales_api map `overview.product`; mongo map `None` (chưa có nguồn — Optional, không bịa).
- `_serialize.overview_json` thêm key `"product": ov.product or ""`.
- **Cập nhật `docs/BA/spec_provider.md` §6** (thêm field vào DTO `ProjectOverview`) TRƯỚC khi code.

### 1.3 Đẩy filter về server trong `recommend_units`

Hiện `recommend_units` fetch **toàn bộ** `/hot-units` rồi lọc client-side, và gọi thêm
`list_projects(region)` (N+1) để lọc theo vùng. spec_provider §9 + spec_tool §3 yêu cầu push
server-side (hot-units có sẵn param `region`, `price_min`, `price_max`, `area_min`, `area_max`,
`direction`, `group`; đơn vị giá = **tỷ**).

**Đổi:** build params từ `RecommendQuery`:
- `region` → `region` (bỏ hẳn N+1 `list_projects`)
- `budget_max_vnd` → `price_max` = `budget_max_vnd / 1e9`
- (nếu thêm `min_budget` sau) → `price_min`
- Lọc còn lại giữ client-side: `bedrooms` (suy từ `unitType.name`), feng-shui (sort ở tool).

`RecommendQuery` giữ nguyên field hiện có; không cần field mới cho lần này.

### 1.4 `warm()` nạp `region`+`type` từ `/api/v1/projects`

Sau khi flip, prompt project table (`registry_rows()`) sẽ dùng roster của sales_api — hiện
`region`/`type` = `""` (chỉ có từ `project_code_map.json`). Điều đó làm bảng dự án trong system
prompt mất cột vùng/loại.

**Đổi:** `warm()` gọi `_fetch_all_projects({})`, build cache `{code: (name, region, type)}`
từ `name`/`areaRegion`/`type`; `registry_rows()`/`code_to_name()`/`cached_codes()` đọc cache đó,
**fallback** về `project_code_map.json` khi nguồn down (giữ ngữ nghĩa "roster luôn có").
`warm_if_stale(ttl)` debounce như hiện tại. `cached_codes()` vẫn ưu tiên roster map (ổn định
cho enum tool-schema), region/type lấy từ cache warm.

---

## Part 2 — Tool mới `check_inventory` (thứ 11) + Capability mới

Đây là **mở rộng contract** → theo spec_provider §11, cập nhật `docs/BA/spec_provider.md` TRƯỚC.

### 2.1 Contract additions (`base.py` + spec_provider §3/§6)

```python
class Capability(StrEnum):
    ...
    INVENTORY = "inventory"

@dataclass(frozen=True)
class InventoryByType:
    unit_type: str; total: int; available: int
    price_from_vnd: int | None; price_to_vnd: int | None

@dataclass(frozen=True)
class InventoryByDirection:
    direction: str; available: int

@dataclass(frozen=True)
class InventorySummary:
    project_code: str; total: int; available: int
    by_unit_type: list[InventoryByType]
    by_direction: list[InventoryByDirection]

# DataProvider:
    async def get_inventory_summary(self, project_code: str) -> InventorySummary | None: ...
```

Ngữ nghĩa §5 giữ nguyên: `None` khi dự án không resolve / không inventory / nguồn down → tool
trả `ESCALATE_SIGNAL`. Có inventory → summary (kể cả `available=0`).

### 2.2 Implement provider

- **sales_api**: đọc `/projects/{slug}.units[]` (3b — có `status` thật), aggregate theo
  `unitType.name` và `direction`, đếm `available` (status canonical == `"available"`).
- **mongo**: aggregate `project_can_ho` theo loại + `trang_thai` (tái dùng đúng logic đếm
  `available_units` đã có trong `get_pricing`; extract helper chung nếu gọn).
- Cả hai khai báo `Capability.INVENTORY`.

### 2.3 Tool + wiring

- `agent/tools/check_inventory.py`: `run(args) -> str` → `provider.get_inventory_summary(code)`;
  `None` → `ESCALATE_SIGNAL`; else `json.dumps(ser.inventory_json(...))`.
- `_serialize.inventory_json(InventorySummary) -> dict` theo shape spec_tool §4.1:
  `{project_code, total, available, by_unit_type:[{type,total,available,price_from,price_to}],
  by_direction:[{direction,available}]}`.
- `schemas.py`: schema `check_inventory` (param **chỉ** `project_code`, required), thêm vào
  `_PROJECT_CODE_TOOLS` để enum mã dự án được bơm động.
- `dispatcher.py`: import + nhánh `if name == "check_inventory"`.
- `agent/definitions/config.json`: thêm `"check_inventory"` → **11 tool**.
- `agent/definitions/RULES.md`: thêm dòng tool-catalog, nhấn **≠ `booking.check_availability`**
  (một cái là tồn kho căn, một cái là lịch xem).

---

## Part 3 — 4 mốc giá thanh toán

spec_tool §3: 4 mốc `price`(niêm yết)/`priceTts`(sớm)/`priceTttd`(tiến độ)/`priceLoan`(vay), đều
**tỷ → ×1e9**. Đưa vào ở **cấp Unit** (nơi khách hỏi "căn này thanh toán sớm bao nhiêu"), chảy
qua `search_units`/`recommend_units`, và **per-type range** trong `get_project_financial` pricing.

### 3.1 DTO (`base.py`, cập nhật spec_provider §6)

`Unit` thêm (Optional, VND int):
- `price_early_vnd` (priceTts) · `price_progress_vnd` (priceTttd) · `price_loan_vnd` (priceLoan).
- `price_vnd` giữ nguyên = giá niêm yết (`price`).

`UnitTypePricing` thêm range cho giá ưu đãi sớm (mốc hữu ích nhất, tránh phình field):
- `price_early_from_vnd` · `price_early_to_vnd` (None khi nguồn không có).

> Quyết định: chỉ aggregate thêm 1 track (early/`priceTts`) ở bảng pricing per-type; đủ để nói
> "giá gốc X–Y, thanh toán sớm còn A–B". 3 track còn lại vẫn đầy đủ ở **cấp Unit** (search_units).
> Nếu review muốn cả 3 track ở bảng pricing sẽ bổ sung — flag ở plan.

### 3.2 Map

- **sales_api**: `_unit_from` set 3 field từ `priceTts`/`priceTttd`/`priceLoan` (×1e9, None nếu vắng).
  ⚠️ **Cần verify live**: 4 mốc chắc chắn có ở `/hot-units` (3a); `/projects/{slug}.units[]` (3b)
  có thể chỉ có `price`+`priceList` → 3 field kia = None trên đường per-project. Xác minh khi
  implement + live smoke; None-safe nên không vỡ.
- **mongo**: chỉ có `gia_vnd` → `price_vnd`; 3 field mới = None.
- `_serialize.unit_json` + `_unit_type_pricing_json` thêm key tương ứng (giá trị None-safe).

---

## Part 4 — Flip default + docs

- `config.py`: `noble_data_source` default `"mongo"` → `"sales_api"`. `.env.example` cập nhật + note.
- `CLAUDE.md`: bảng config (`NOBLE_DATA_SOURCE` default = `sales_api`), tool count 10 → **11**,
  layout row `agent/tools/` (+`check_inventory`), append 1 dòng Change Log.
- Cập nhật `docs/BA/spec_provider.md` (§3 method, §6 DTO fields cho `product` + 4 giá + Inventory\*,
  §9 nếu cần) và `docs/BA/spec_tool.md` (đổi trạng thái `check_inventory` từ "đề xuất" → đã thêm).

---

## Testing (TDD)

- **Contract test dùng chung** (mọi provider): shape DTO + ngữ nghĩa `None`/rỗng cho
  `get_inventory_summary`; overview có `product`; unit có 4 mốc giá.
- **sales_api map test** (mock httpx, fixture response live): overview JSON double-decode;
  recommend_units build đúng server-side params (assert params gửi đi, không assert mạng);
  inventory aggregate; 4 mốc giá ×1e9.
- **mongo map test**: inventory aggregate theo `trang_thai`; product=None; 3 giá mới=None.
- **tool test**: `check_inventory` → serialize shape §4.1; `None`→`ESCALATE_SIGNAL`.
- **schema test**: 11 tool offered; `check_inventory.project_code` có enum động; agent_def load 11.
- **`make test-unit`** xanh (delta 0 so với baseline; các fail catalog/mongo drift pre-existing
  không đụng tới file này).

## Ngoài phạm vi (không làm)

- RAG re-ingest (đã xong). Payment-plans/loan/promotions/fees tool đọc (rỗng dev → escalate).
- floor/building filtering (rỗng dev). Tách service provider (§10 spec_provider — chưa có trigger).
- 3/4 track giá ở bảng pricing per-type (chỉ early track; xem 3.1).

## Rủi ro

- **Flip sang sales_api = đổi hành vi runtime cho MỌI transport.** Bắt buộc chạy `SMOKE.md` +
  live smoke (list_projects → overview → recommend → search → check_inventory → booking) trước khi
  coi là xong. Sales-API dev có thể thiếu field (status ở hot-units, floor…) — đã bọc None-safe.
- Nếu roster sales_api ≠ roster RAG đã ingest → `noble_search` trả sai dự án. User xác nhận RAG
  mới nhất; vẫn verify 1 truy vấn RAG trong smoke.
