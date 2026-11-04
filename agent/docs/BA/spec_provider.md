# Data Provider Contract — Spec

**Trạng thái:** Draft v1 · **Ngày:** 2026-07-20 · **Phạm vi:** lớp dữ liệu dự án/căn hộ cho hotline agent (Luna)

Tài liệu này là **quy chuẩn (contract)** cho lớp trung gian "provider" giữa **tool của agent** và **nguồn dữ liệu** (MongoDB, NBX Sales API, hoặc bất kỳ nguồn nào sau này). Mục tiêu: đổi nguồn dữ liệu = **đổi 1 biến env**, KHÔNG đụng tool, schema, hay đối số model.

> Khi cần viết một provider mới, **đọc file này trước** rồi làm theo mục [§8 Checklist thêm provider](#8-checklist-thêm-provider-mới) và [§9 Bảng ánh xạ mẫu](#9-bảng-ánh-xạ-mẫu-sales-api).

---

## 1. Nguyên tắc cốt lõi (bất biến)

1. **Hợp đồng hướng model là canonical và cố định.** Tool schema + đối số LLM luôn dùng thuật ngữ canonical (vd `project_code`, `region`, `budget_max`). Nguồn dữ liệu đổi → các thứ này **không đổi**.
2. **Định danh dự án hướng ra ngoài luôn là `project_code`** (mã ngắn canonical, vd `MCP`, `VGP`). `id` / `slug` / `uuid` / `ma_du_an` của nguồn là **chi tiết nội bộ của provider**, KHÔNG bao giờ lộ ra tool hay model.
3. **Provider tự chịu trách nhiệm 3 việc:** (a) resolve `project_code` → định danh nội bộ của nguồn; (b) map field nguồn → **DTO canonical**; (c) quy đổi đơn vị về canonical (xem §4).
4. **Tool KHÔNG biết nguồn.** Tool chỉ gọi `provider.<method>()` và nhận DTO canonical. Toàn bộ `if mongo / if api` bị cấm ở tầng tool.
5. **In-process, không network hop thừa.** Provider là module Python nạp lazy theo config — không phải service riêng. (Chỉ tách service khi có consumer thứ 2 / cần scale-deploy độc lập — xem §10.)
6. **Never raise qua ranh giới tool.** Provider trả `None` / collection rỗng theo ngữ nghĩa §5; lỗi hạ tầng bất ngờ do dispatcher bắt.

---

## 2. Vị trí trong kiến trúc

```
LLM tool call (đối số canonical: project_code, region, budget_max, …)
  ↓
agent/tools/*.py            # projects_info, project_financial, booking(schedule)…
  ↓  provider = get_provider(settings)
data/providers/base.py      # DataProvider (Protocol) + DTO canonical + Capability
  ├─ data/providers/mongo.py      # impl MongoDB  (structured_data.py cũ dời vào đây)
  ├─ data/providers/sales_api.py  # impl NBX Sales API (httpx)
  └─ data/providers/<new>.py      # provider tương lai
        ↓ chọn bằng NOBLE_DATA_SOURCE
     nguồn dữ liệu thật (Mongo / HTTP API / …)
```

- `noble_search` (RAG/Qdrant) **KHÔNG** thuộc contract này — nó là kho tri thức riêng, có pipeline ingest riêng. Nhưng roster mã dự án của RAG phải **đồng bộ** với `registry_rows()` của provider đang bật (xem §7).
- `booking` ghi vào collection riêng của hotline (`hotline_bookings_flat`) + Redis — **không** đi qua provider (không phải dữ liệu dự án). Chỉ phần validate mã dự án của booking dùng `catalog.normalize()`, mà cái đó được provider nạp (xem §7).

---

## 3. Interface: `DataProvider`

Định nghĩa tại `data/providers/base.py` (dưới đây là bản phác — chữ ký thật chốt ở plan). Tất cả method là `async`. Provider **không cần** hỗ trợ hết — cái không hỗ trợ trả `None` (→ tool escalate). Khai báo năng lực qua `capabilities`.

```python
class DataProvider(Protocol):
    name: str                          # "mongo" | "sales_api" | ...
    capabilities: frozenset[Capability]

    # ── Listing / overview ────────────────────────────────────────────
    async def list_projects(self, *, region: str = "") -> ProjectList | None: ...
    async def get_overview(self, project_code: str) -> ProjectOverview | None: ...

    # ── Financial / inventory ─────────────────────────────────────────
    async def get_pricing(
        self, project_code: str, *, unit_type: str = "", max_price_vnd: int = 0
    ) -> PricingTable | None: ...
    async def search_units(self, query: UnitQuery) -> list[Unit] | None: ...
    async def recommend_units(self, query: RecommendQuery) -> UnitRecommendation: ...
    async def get_inventory_summary(self, project_code: str) -> InventorySummary | None: ...

    # ── Info-types không có nguồn cấu trúc ở đa số provider ───────────
    async def get_payment_plans(self, project_code: str) -> PaymentPlans | None: ...
    async def get_loan_policies(self, project_code: str) -> LoanPolicies | None: ...
    async def get_promotions(self, project_code: str) -> Promotions | None: ...
    async def get_project_fees(self, project_code: str) -> ProjectFees | None: ...

    # ── Registry (cấp mã dự án cho enum tool-schema + prompt table) ────
    async def warm(self) -> None: ...                    # nạp roster từ nguồn
    async def warm_if_stale(self, ttl_sec: float) -> None: ...
    def registry_rows(self) -> list[ProjectRegistryRow]: ...   # sync, đọc cache
    def cached_codes(self) -> list[str]: ...                   # sync
    def code_to_name(self) -> dict[str, str]: ...              # sync
```

### Capability

```python
class Capability(StrEnum):
    LISTING = "listing"; OVERVIEW = "overview"; PRICING = "pricing"
    UNIT_SEARCH = "unit_search"; RECOMMEND = "recommend"
    PAYMENT_PLANS = "payment_plans"; LOAN_POLICIES = "loan_policies"
    PROMOTIONS = "promotions"; FEES = "fees"
    INVENTORY = "inventory"
```

Method thuộc capability KHÔNG khai báo → **phải** trả `None` (đừng raise `NotImplementedError`). Tool nhận `None` → `ESCALATE_SIGNAL`.

---

## 4. Đơn vị & từ vựng canonical (BẮT BUỘC quy đổi)

Provider **phải** chuẩn hóa mọi giá trị về đúng các quy ước sau. Đây là nguồn gốc lỗi phổ biến nhất khi map — kiểm tra kỹ.

| Khái niệm | Canonical | Ghi chú map |
|---|---|---|
| **Giá** | **VND nguyên (int)** — vd `45_740_000_000` | Mongo `gia_vnd`: dùng thẳng. Sales API `price` (đơn vị **tỷ**, vd `45.74`): **× 1e9 → int**. |
| **Giá theo kịch bản thanh toán** | `price_early_vnd` / `price_progress_vnd` / `price_loan_vnd` (VND int) | Sales API `priceTts` (thanh toán sớm) / `priceTttd` (theo tiến độ) / `priceLoan` (vay) — cùng đơn vị tỷ, cùng quy đổi ×1e9. |
| **Diện tích** | **m² (float)** | field `area_m2`. |
| **Ngân sách** (`budget_max`) | **VND nguyên (int)** | Đối số model nhập theo tỷ → tool nhân 1e9 TRƯỚC khi gọi provider; provider luôn nhận VND. |
| **Vùng miền** (`region`) | enum `mien_bac \| mien_trung \| mien_nam` (`""` = tất cả) | Provider map giá trị native (Mongo `khu_vuc` text tự do; API `areaRegion`) → 3 macro-region. Mongo cần bảng map tỉnh/quận → miền. |
| **Loại hình dự án** (`type`) | enum `cao_tang \| thap_tang \| can_ho` | API `type` dùng thẳng; Mongo `loai_hinh_sp` map. |
| **Nhóm loại căn** (`unit_type_group`) | như `type` | API `unitType.group`; Mongo `loai_san_pham` map. |
| **Số phòng ngủ** (`bedrooms`) | int \| None | API: suy từ `unitType.name` (`"2PN"→2`, `"Studio"→0`); nhóm `thap_tang` (Liền kề/Biệt thự) → None. |
| **Trạng thái căn** (`status`) | enum `available \| sold \| booked \| unknown` | Mongo `trang_thai` (text VN) map; Sales API: `/projects/{slug}.units[].status` có enum thật (`available`…), còn `hot-units` có thể thiếu → `unknown`. |
| **Hướng** (`direction`) | text VN giữ nguyên (`"Đông"`, `"Tây Nam"`) | Dùng cho feng-shui matching. |
| **Mã dự án** (`project_code`) | mã ngắn canonical (chữ HOA) | Xem §7 nguồn mã. |

**Field thiếu → `None`, KHÔNG bịa.** DTO khai báo Optional; tool + prompt phải chịu được `None`.

---

## 5. Ngữ nghĩa trả về (phân biệt "trống" vs "không trả lời được")

Đây là hợp đồng quan trọng nhất về hành vi — giữ đúng như code hiện tại:

| Tình huống | Provider trả | Tool xử lý |
|---|---|---|
| Nguồn khỏe, có dữ liệu | DTO / list có phần tử | trả JSON cho LLM |
| Nguồn khỏe, **lọc ra rỗng** (region không khớp, không căn nào thỏa filter) | **collection rỗng có wrapper** (`ProjectList(count=0,…)`, `UnitRecommendation(units=[])`) | mời khách nới tiêu chí — **KHÔNG escalate** |
| **Không trả lời được**: nguồn down, project không tồn tại, capability không hỗ trợ, info-type không có nguồn | **`None`** | trả `ESCALATE_SIGNAL` → auto-escalate CVTV |

Quy tắc phân biệt cho `search_units` / `recommend_units`:
- `recommend_units`: `None` **chỉ** khi nguồn down / roster rỗng (lỗi hệ thống). Region không khớp hay filter loại hết → `units=[]`.
- `search_units` / `get_pricing`: project không resolve được hoặc không có inventory → `None`. Có inventory nhưng filter loại hết → tùy tool (hiện `search_units` trả `None`→escalate; giữ nguyên hành vi cũ để không đổi UX).

`ESCALATE_SIGNAL` = hằng số dùng chung (`"Thông tin đã được chuyển đến chuyên viên tư vấn"`), đặt ở `data/providers/base.py` để tool import.

---

## 6. DTO canonical

Dataclass `frozen=True`, field Optional khi không đảm bảo. Bản phác (chốt field ở plan):

```python
@dataclass(frozen=True)
class ProjectSummary:            # 1 dòng trong list_projects
    code: str; name: str; region: str; type: str

@dataclass(frozen=True)
class ProjectList:
    count: int; projects: list[ProjectSummary]
    region: str = ""; note: str = ""

@dataclass(frozen=True)
class ProjectOverview:
    code: str; name: str
    region: str | None = None; district: str | None = None; type: str | None = None
    investor: str | None = None; total_units: str | None = None
    management: str | None = None; ownership: str | None = None
    handover: str | None = None; land_area: str | None = None
    total_investment_vnd: int | None = None; description: str | None = None
    product: str | None = None       # loại hình sản phẩm (vd "Căn hộ, nhà phố, biệt thự")

@dataclass(frozen=True)
class Unit:
    project_code: str; project_name: str; unit_code: str
    unit_type: str; unit_type_group: str
    bedrooms: int | None
    area_m2: float | None          # diện tích sử dụng chính (thông thủy)
    wall_area_m2: float | None     # diện tích tim tường (None nếu nguồn không tách)
    price_vnd: int | None; price_per_m2_vnd: int | None
    direction: str | None; floor: str | None; view: str | None
    status: str            # available|sold|booked|unknown
    max_discount_pct: float | None
    image_url: str | None
    price_early_vnd: int | None = None       # thanh toán sớm (Sales API priceTts)
    price_progress_vnd: int | None = None    # theo tiến độ (Sales API priceTttd)
    price_loan_vnd: int | None = None        # vay (Sales API priceLoan)

@dataclass(frozen=True)
class UnitTypePricing:
    unit_type: str; group: str
    area_min_m2: float | None; area_max_m2: float | None
    price_from_vnd: int | None; price_to_vnd: int | None
    price_per_m2_from_vnd: int | None; price_per_m2_to_vnd: int | None
    total_units: int; available_units: int | None   # None khi nguồn không có status
    price_early_from_vnd: int | None = None
    price_early_to_vnd: int | None = None

@dataclass(frozen=True)
class PricingTable:
    project_code: str; results: list[UnitTypePricing]

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
    by_unit_type: list[InventoryByType]; by_direction: list[InventoryByDirection]

@dataclass(frozen=True)
class UnitRecommendation:
    units: list[Unit]                # đã sort feng-shui-first ở tool, provider trả raw

@dataclass(frozen=True)
class ProjectRegistryRow:
    code: str; name: str; region: str; type: str
```

Query object (gom filter cho gọn, mọi giá trị đã canonical):

```python
@dataclass(frozen=True)
class UnitQuery:
    project_code: str; unit_type: str = ""; max_price_vnd: int = 0
    direction: str = ""; floor: int = 0; tower: str = ""
    unit_code: str = ""; status: str = "available"; min_area_m2: float = 0

@dataclass(frozen=True)
class RecommendQuery:
    region: str = ""; budget_max_vnd: int = 0; bedrooms: int = 0
    good_directions: frozenset[str] = frozenset(); limit: int = 6
```

> Provider nào không có field cho một filter (vd Sales API không có `floor`/`status`) thì **bỏ qua filter đó** (không loại phần tử vì thiếu field) và set DTO field = `None`/`"unknown"`. Ghi rõ trong docstring provider filter nào bị bỏ.

---

## 7. Roster mã dự án & định danh (quan trọng)

- **Nguồn mã canonical do provider cấp** qua `registry_rows()`/`cached_codes()`/`code_to_name()`. `warm()` nạp từ nguồn, cache in-memory (sync accessor không I/O), `warm_if_stale(ttl)` debounce đầu mỗi cuộc gọi (`NOBLE_PROJECT_REGISTRY_REFRESH_SEC`).
- **Enum `project_code` trong tool-schema** được đóng băng theo session từ `cached_codes()` (cơ chế snapshot hiện có ở `orchestrator`/`runner`). Đổi provider → enum tự đổi theo roster mới, không sửa schema.
- **`catalog.normalize()`** (validate booking) phải chấp nhận mọi mã trong `cached_codes()` của provider đang bật (fallback lazy như hiện tại). Alias hard-code trong `catalog._REGISTRY` là phụ trợ; roster thật đến từ provider.
- **Resolve nội bộ, theo provider:**
  - `mongo`: `project_code` == `ma_du_an` (regex case-insensitive) → `_id`.
  - `sales_api`: `project_code` → `name` (reverse map `docs/api/project_code_map.json`) → tìm trong `GET /projects` theo `name` → `slug`; `id` (uuid) lấy từ `GET /projects/{slug}` khi cần lọc `hot-units?project_id=`, hoặc lọc client-side theo `project.name/slug`.
- **⚠ Đồng bộ RAG:** khi roster đổi (vd Noble/Sunshine → Masteri/Vinhomes), kho `noble_search` (Qdrant `project_id` payload) **phải được ingest lại** theo roster mới, nếu không tri thức trả về sai dự án. Việc này ngoài phạm vi provider nhưng là **điều kiện tiên quyết** khi bật provider có roster khác.

---

## 8. Checklist thêm provider mới

Làm theo đúng thứ tự khi viết `data/providers/<name>.py`:

1. **Đọc §1–§7** của file này. Đọc bảng field-mapping mẫu §9.
2. Implement class theo Protocol `DataProvider`. Đặt `name` + `capabilities` (chỉ khai báo capability THẬT SỰ có nguồn).
3. **Map field nguồn → DTO canonical** cho từng method có capability. Với mỗi field: xác định nguồn, quy đổi đơn vị (§4), thiếu → `None`. Viết một **bảng ánh xạ** trong docstring module (theo mẫu §9).
4. **Resolve định danh** `project_code` → ref nội bộ; không bao giờ trả id/slug ra DTO ngoài `code`.
5. **Giữ ngữ nghĩa §5** (`None` vs rỗng). Không raise cho điều kiện dự kiến.
6. Implement `warm()/warm_if_stale()/registry_rows()/cached_codes()/code_to_name()` (nạp roster + fallback bundled khi nguồn down).
7. **Đăng ký** trong `data/providers/__init__.py::get_provider(settings)` theo giá trị `NOBLE_DATA_SOURCE`.
8. **Config:** thêm giá trị enum vào `NOBLE_DATA_SOURCE` + settings riêng của provider (URL/token/timeout) trong `config.py` + `.env.example`. Public API không cần JWT; nếu cần auth ghi rõ.
9. **Test:** (a) chạy bộ **contract test** dùng chung (mọi provider phải pass — kiểm shape DTO + ngữ nghĩa `None`/rỗng); (b) test map field riêng của provider với fixture response thật (mock HTTP/DB, không gọi mạng); (c) `FakeProvider` cho test tool không cần nguồn thật.
10. **Không** đụng file tool, tool-schema, prompt. Nếu buộc phải đụng → contract chưa đủ, cập nhật file này TRƯỚC (xem §11).

---

## 9. Bảng ánh xạ mẫu (Sales API)

Tham chiếu thật cho provider `sales_api`. Cột **T.thái**: ✓ có · ~ suy ra · ✗ nguồn không có → `None`.

> **Nguồn của bảng này (đọc trước khi tin):** OpenAPI `/docs/json` có `components.schemas` **rỗng** → spec **không** mô tả response; mọi field dưới đây lấy từ **response live** (`nbx-sales-api-dev.noble.vn`, xác minh 2026-07-21), không phải từ spec. Query-param thì lấy từ `/docs/json` (đầy đủ hơn `spec_api.md`).
>
> **Query-param thật của `GET /hot-units`** (nhiều hơn `spec_api.md`): `group(thap_tang|can_ho)`, `region(mien_bac|mien_trung|mien_nam)`, `project_id`, `unit_type_id`, `direction`, `code`, `zone`, `area_min`, `area_max`, **`price_min`**, **`price_max`** (number, **đơn vị tỷ**), `fund_type(hot|quy_hot)`. ⇒ **lọc ngân sách & vùng miền đẩy được server-side** (không cần fetch-all rồi lọc client). `hot-units` **không có `page`** → trả **toàn bộ** căn thỏa filter ⇒ luôn kèm filter để chặn payload.

**`list_projects`** ← `GET /api/v1/projects` (envelope `{items[], page, pageSize, total}`; query `area_region`,`type`,`page`)

| DTO canonical | Field API | T.thái |
|---|---|---|
| `code` | map `name` → code (`project_code_map.json`) | ✓ |
| `name` | `name` | ✓ |
| `region` | `areaRegion` | ✓ |
| `type` | `type` | ✓ |

**`get_overview`** ← `GET /api/v1/projects/{slug}` (có `id`,`investor`,`overview`,`description`,`lat/lng`,`units[]`)

> ⚠️ **`overview` là CHUỖI JSON double-encoded**, không phải object — phải `json.loads(resp["overview"])` trước khi đọc. Keys thật bên trong: `scale, density, product, link_360, ownership, csbh_image, units_text, area_summary`.

| DTO | Field API | T.thái |
|---|---|---|
| code/name/region/district/type/investor | map name / `name` / `areaRegion` / `location` / `type` / `investor` (top-level) | ✓ |
| total_units | `overview.units_text` (vd `"Khoảng 2481 sản phẩm thấp tầng"`) | ~ |
| ownership | `overview.ownership` (vd `"Lâu dài"`) | ✓ |
| land_area | `overview.scale` (vd `"458 ha"`) | ~ |
| management / handover / total_investment_vnd | — (`overview` không có key này) | ✗ |
| description | `description` (HTML thô) | ✓ |
| *(bonus, chưa có field DTO)* loại hình sản phẩm | `overview.product` (vd `"Căn hộ, nhà phố, biệt thự, shophouse"`) → phục vụ câu hỏi "loại hình" | ~ |

**`get_pricing` / `search_units` / `recommend_units`** — **HAI shape unit khác nhau**, tên field KHÁC NHAU, chọn nguồn theo tool:

- **3a. Cross-project** ← `GET /api/v1/hot-units` — **response là envelope `{items:[...]}`** (không phải mảng trần); code đọc `data.get("items", [])`. Mỗi item **nested** `project{slug,name,coverImage}` + `unitType{id,name,group}`. Item list: `id, code, fundType, unitType{}, direction, areaLand, areaBuild, price, priceTts, priceTttd, priceLoan, image, project{}, parent, investor, zone`. Detail `GET /hot-units/{id}` **thêm**: `status, csbhBrief, csbhFull, loanInfo, bankSupport, gift, legal, commission, deliveryStandard, gallery, imageLayout, gated`. **KHÔNG có `area`/`floor`/`building`** kể cả ở detail.
- **3b. Per-project** ← `GET /api/v1/projects/{slug}.units[]` — mảng **giàu nhất** (~46 field): có `area`, `areaBuild`, `status`, `floor`, `floorMin`, `floorMax`, `building`, `axis`, `front`, `priceList`, `unitType`(hay null)/`unitTypeId`, `csbh*`, `loanInfo`, … nhưng **không nested `project`** (suy từ slug ngoài).

| DTO Unit | 3a `hot-units` | 3b `projects/{slug}.units[]` | Ghi chú chốt |
|---|---|---|---|
| `unit_code` | `code` ✓ | `code` ✓ | |
| `price_vnd` | `price` **×1e9** | `price` **×1e9** | đơn vị **tỷ** (`45.74`, `112.43`) |
| `area_m2` (thông thủy) | **✗ không có `area`** → dùng `areaBuild`/`areaLand` | **`area`** ✓ | ⚠️ hot-units KHÔNG có field `area` |
| `wall_area_m2` | `areaBuild` (không chắc tách tim-tường) | `areaBuild` | `None` nếu không chắc |
| `status` | **chỉ ở detail `/hot-units/{id}`**; ở LIST thiếu → `"unknown"` | `status` ✓ (`available`…) | ⚠️ list ≠ detail |
| `floor` / `building` | **✗ KHÔNG có, kể cả detail** | `floor`/`building`/`floorMin`/`floorMax` (thường null) | ⚠️ chỉ 3b |
| `direction` | `direction` (hay null) | `direction` (hay null) | ~ |
| `unit_type` / `unit_type_group` | `unitType.name` / `unitType.group` | `unitType`(**hay null**) / `unitTypeId` | 3a giàu `unitType` hơn |
| `bedrooms` | suy `unitType.name` (`"2PN"→2`,`"Studio"→0`); thấp tầng→None | như 3a; `unitType` hay null | ~ chỉ `can_ho` |
| `price_per_m2_vnd` / `view` | ✗ | ✗ | → `None` |
| `image_url` | `image` (hay null) | `image` (hay null) | ~ |
| `project_code`/`project_name` | map `project.name`→code / `project.name` | (từ slug ngoài) | ✓ |

**4 mốc giá = 4 kịch bản thanh toán** (đều **tỷ**, ×1e9): `price` (niêm yết) · `priceTts` (thanh toán sớm, vd 112.43→90.02) · `priceTttd` (theo tiến độ) · `priceLoan` (vay). Có thể phục vụ câu hỏi chính sách giá cơ bản.

**Chọn nguồn theo tool:**
- `get_pricing`, `search_units` (1 dự án) → **3b** (`/projects/{slug}.units[]`): có `status`/`floor` → **lọc còn/hết, đếm `available_units` chuẩn**.
- `recommend_units` (cross-project) → **3a** (`/hot-units`) + push `region`/`price_min`/`price_max` server-side; `status` chỉ có nếu gọi detail từng căn (đắt) → thường để `"unknown"`.

Lọc theo dự án khi cần uuid: `hot-units?project_id={uuid}` (uuid từ `/projects/{slug}.id`). `unit_type_id` từ `GET /apartment-types` (`{id,name,group}`). Filter `tower`/`view` **bỏ qua** (nguồn không có).

**Hệ quả nghiệp vụ khi dùng Sales API** (ghi để không tưởng nhầm là bug):
- `status`/`available_units`: **có** qua 3b (project-detail units[]); qua 3a `hot-units` list → `unknown` (chỉ detail mới có).
- `floor`/`building`: **chỉ** 3b có; `hot-units` hoàn toàn không có.
- Không có giá/m² (`price_per_m2`), `view`; `unitType` hay null.
- `direction` **được điền tốt** (~76%: 331/437 căn dev có hướng) → hướng + phong thủy khả dụng.
- Số phòng ngủ chỉ suy được cho căn hộ (`can_ho`), không có cho thấp tầng.
- Giá là **tỷ** → ×1e9 thành VND canonical (áp cho cả 4 mốc giá và param `price_min`/`price_max`).
- ✅ **`gated` (đã verify 2026-07-21 bằng token demo):** `gated` là cờ auth — có `Authorization: Bearer` thì `gated:false`. **NHƯNG** field bán hàng (`csbhBrief/Full`, `loanInfo`, `bankSupport`, `legal`, `gift`, `priceList`) **rỗng cả khi authed** — quét 437 căn / 20 dự án dev = **0 căn** có dữ liệu. ⇒ Không phải bị che, mà **chưa có dữ liệu trên dev**. Coi chính sách/CSBH là **không có nguồn** → escalate (verify lại prod trước khi làm tool đọc chúng).
- ⚠️ `floor`/`building` **rỗng hoàn toàn** trên dev (0/437 căn) → tầng/vị-trí-trong-tòa hiện không có dữ liệu (field vẫn tồn tại, chờ prod).
- ⚠️ `GET /projects/{slug}/progress`: authed trả `{items:[]}` (endpoint OK, không lỗi), nhưng gần rỗng — 20 dự án chỉ 1 có 2 mục → **tiến độ/bàn giao chưa dùng được** trên dev.

---

## 10. Khi nào nâng provider lên service riêng

Giữ in-process cho tới khi gặp **một** trigger sau, lúc đó extract từ interface đã có (việc cơ học):
- Có **consumer thứ 2** (agent/hệ thống khác, khác ngôn ngữ) cần dùng chung lớp chuẩn hóa.
- Cần **scale / deploy độc lập** lớp dữ liệu khỏi agent.
- Cần **cache / rate-limit / credential tập trung** chia sẻ nhiều bên.

Lưu ý latency: hotline là voice, foreground retrieval chặn TTFA — mỗi network hop thêm là chi phí thật.

---

## 11. Mở rộng contract (thêm tool / capability mới phía agent)

Khi agent cần một loại dữ liệu mới (vd "chính sách thanh toán" có nguồn thật):
1. Thêm `Capability` + method vào `DataProvider` (base.py) + DTO canonical tương ứng.
2. Cập nhật **file này** (§3/§4/§6) TRƯỚC khi code — contract là nguồn chân lý.
3. Provider chưa hỗ trợ capability đó cứ trả `None` (escalate) — không phá provider cũ.
4. Tool mới đọc DTO, không đọc field nguồn.

---

## Change Log

| Ngày | Thay đổi | Ghi chú |
|---|---|---|
| 2026-07-20 | Draft v1 — contract provider (interface, DTO, đơn vị canonical, ngữ nghĩa None/rỗng, checklist, bảng map Sales API). | Tạo cùng lúc với quyết định dùng provider pattern in-process (`NOBLE_DATA_SOURCE`). |
| 2026-07-21 | §9 đính chính theo response **live** (nbx-sales-api-dev): `hot-units` có `price_min`/`price_max`/`region`/`zone` server-side; `overview` là chuỗi JSON double-encoded; hot-units KHÔNG có `area`/`floor`/`building` (chỉ `areaLand`/`areaBuild`, `floor`/`building` chỉ ở `projects/{slug}.units[]`); `status` chỉ ở `/hot-units/{id}` detail (list thiếu); 4 mốc giá thanh toán; caveat `gated`=true → field CSBH/loanInfo null khi chưa auth; `/progress` lỗi trên dev. | OpenAPI `/docs/json` có `components.schemas` rỗng → response không được spec mô tả; field lấy từ khảo sát live. |
