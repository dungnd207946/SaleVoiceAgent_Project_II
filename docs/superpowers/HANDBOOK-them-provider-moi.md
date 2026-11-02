# Handbook: Thêm một Provider / Tenant mới

> Cẩm nang end-to-end cho việc onboard một nguồn dữ liệu (data provider) mới —
> và, nếu là một khách hàng SaaS mới, cả một tenant mới. Bám sát code trên
> branch `feat/refactor2` (Phase 1–3 đã xong).
>
> **Mục tiêu kiến trúc:** thêm 1 provider = **1 adapter** + (tuỳ chọn) khai báo
> field/param/tool riêng + 1 tenant manifest. **KHÔNG sửa** core tool schema,
> dispatcher, hay các provider khác.

---

## 0. Phân biệt 2 khái niệm trước khi bắt đầu

| Khái niệm | Là gì | File gốc |
|---|---|---|
| **Data provider** | Nguồn dữ liệu dự án/căn hộ (Mongo, HTTP API, …). Chuyển field gốc → **DTO chuẩn**. Chọn bằng `NOBLE_DATA_SOURCE`. | `data/providers/` |
| **Tenant** | Một "khách hàng SaaS" = 1 bundle (persona + tool được bật + brand + data_source). Chọn bằng `TENANT_ID`. | `tenants/<id>/` |

Hai cái **độc lập**. Bạn có thể:
- Chỉ thêm **data provider** mới (vẫn dùng persona/brand Noble) → làm Phần A.
- Thêm **cả tenant** mới (brand khác, persona khác, tool khác) → làm Phần A + Phần C.

Hiện tại việc chọn provider vẫn đi qua `settings.noble_data_source` (chưa cutover
qua `TenantContext` — đó là slice sau). `manifest.data_source` chỉ **mirror** giá
trị đó và được test guard, chưa phải nguồn điều khiển.

---

## Phần A — Thêm một DATA PROVIDER mới

### A0. Checklist nhanh

- [ ] `data/providers/<ten>.py` — class implement `DataProvider` Protocol.
- [ ] `data/providers/__init__.py::get_provider` — thêm nhánh `elif source == "<ten>"`.
- [ ] `config.py` — (nếu cần) thêm env cho endpoint/credentials của provider.
- [ ] `.env.example` — document env mới + giá trị `NOBLE_DATA_SOURCE` mới.
- [ ] (Tuỳ chọn) `extra_specs` — field ngoài core, hiển thị cho LLM (Tier-1).
- [ ] (Tuỳ chọn) `tool_params` — param lọc mới trên tool chuẩn (Tier-2).
- [ ] `tests/unit/unified/providers/test_<ten>_provider.py` — test mapping DTO.
- [ ] `tests/unit/unified/providers/test_factory.py` — test factory trả đúng class.
- [ ] Chạy gate: `make test-unit` + `make lint`.

### A1. Hợp đồng bất biến (đọc kỹ — sai là hỏng ngầm)

Nguồn chuẩn: `data/providers/base.py` và `docs/BA/spec_provider.md`.

1. **Đơn vị canonical (BẮT BUỘC):**
   - `price_*_vnd` = **VND integer** (không phải tỷ, không phải string). Nguồn để
     tỷ → nhân `1e9`. Xem `nbx_mongo._to_vnd`.
   - `area_m2` / `wall_area_m2` = **float m²**.
   - `region` / `type` / `status` = **enum canonical** (không phải text thô của nguồn).
2. **`status` chỉ 4 giá trị:** `available | sold | booked | unknown`. Map field
   gốc qua một `_STATUS_MAP` (xem `nbx_mongo`).
3. **Thiếu field → `None`, KHÔNG bịa.** DTO đã `Optional` đúng chỗ. Không suy đoán
   giá/hướng/tầng khi nguồn không có.
4. **`project_code` là canonical code**, không bao giờ để lộ `id`/`slug`/`uuid` ra
   ngoài. Resolve qua `catalog.normalize(...)` trước khi tin.
5. **DTO là frozen** — build một lần, không mutate.
6. **`None` (không có capability / lỗi) vs `[]` (có nhưng rỗng):** tool layer biến
   `None` thành `ESCALATE_SIGNAL` (chuyển chuyên viên). Trả `[]`/`ProjectList(0,...)`
   khi thực sự "không có kết quả nhưng nguồn OK". Đừng nhầm hai cái.
7. **Boot phải sống sót:** `warm()` bắt mọi exception, log rồi tiếp tục (dùng
   fallback code). Không được để một nguồn chết làm sập boot.

### A2. Các capability & method của Protocol

`DataProvider` (base.py:230) yêu cầu các attribute + async method sau. Nếu nguồn
**không có** một capability, **vẫn phải implement method** nhưng trả `None`
(đúng như 4 method `get_payment_plans/loan_policies/promotions/fees` trong nbx).

```python
name: str                              # "nbx", "sales_api", … — trùng NOBLE_DATA_SOURCE
capabilities: frozenset[Capability]    # khai báo cái nào thật sự có
extra_specs: tuple[ExtraFieldSpec, ...]   # Tier-1 (mặc định ())
tool_params: tuple[ToolParamSpec, ...]    # Tier-2 (mặc định ())

async list_projects(*, region="") -> ProjectList | None
async get_overview(project_code)  -> ProjectOverview | None
async get_pricing(project_code, *, unit_type="", max_price_vnd=0) -> PricingTable | None
async search_units(query: UnitQuery)          -> list[Unit] | None
async recommend_units(query: RecommendQuery)  -> UnitRecommendation | None   # RAW: không sort/không cap
async discover_projects(query: DiscoverQuery) -> ProjectDiscovery | None     # đã rank + slice [offset, offset+limit)
async get_inventory_summary(project_code)     -> InventorySummary | None

async get_payment_plans(project_code)  -> None   # trả None nếu nguồn không có
async get_loan_policies(project_code)  -> None
async get_promotions(project_code)     -> None
async get_project_fees(project_code)   -> None

async warm()                       -> None       # nạp registry cache; nuốt exception
async warm_if_stale(ttl_sec)       -> None       # debounce theo TTL
registry_rows() -> list[ProjectRegistryRow]      # sync; cache-hoặc-fallback
cached_codes()  -> list[str]                     # sync
code_to_name()  -> dict[str, str]                # sync
```

**Lưu ý phân công trách nhiệm** (tránh nhét logic sai lớp):
- `recommend_units` trả units **RAW** — feng-shui rank + cap `[:6]` là việc của
  **tool layer**, không phải provider.
- `discover_projects` provider **tự rank + slice** một trang; còn envelope
  (`suggested_narrow`, `instruction`, `has_more`) là việc của tool layer.

### A3. Template adapter

Sao chép `data/providers/nbx_mongo.py` làm khung (provider Mongo, self-contained,
không kéo httpx). Nếu là HTTP API, xem `sales_api.py` (có DNS cache + httpx). Khung
tối thiểu:

```python
# data/providers/<ten>.py
from __future__ import annotations
import logging, time
from noble_agent.agent import catalog
from noble_agent.data.providers import base

logger = logging.getLogger("noble_agent.data.providers.<ten>")

_STATUS_MAP = {"con_hang": "available", "da_ban": "sold", "giu_cho": "booked"}

class MyProvider:
    name = "<ten>"
    capabilities = frozenset({
        base.Capability.LISTING, base.Capability.OVERVIEW,
        base.Capability.PRICING, base.Capability.UNIT_SEARCH,
        base.Capability.RECOMMEND, base.Capability.INVENTORY,
    })
    extra_specs = ()      # điền ở A4 nếu cần
    tool_params = ()      # điền ở A5 nếu cần

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}
        self._last_warm_ts = 0.0

    def _unit_from(self, raw) -> base.Unit:
        return base.Unit(
            project_code=catalog.normalize(raw["ma_du_an"]) or raw["ma_du_an"],
            project_name=raw.get("ten") or "",
            unit_code=raw.get("ma_can") or "",
            unit_type=raw.get("loai") or "",
            unit_type_group=raw.get("nhom") or "",
            bedrooms=raw.get("so_pn"),
            area_m2=float(raw["dt"]) if raw.get("dt") else None,
            wall_area_m2=None,
            price_vnd=int(round(float(raw["gia_ty"]) * 1e9)) if raw.get("gia_ty") else None,
            price_per_m2_vnd=None,
            direction=raw.get("huong") or None,
            floor=None, view=None,
            status=_STATUS_MAP.get(raw.get("trang_thai", ""), "unknown"),
            max_discount_pct=None,
            image_url=raw.get("anh") or None,
            extras={},   # xem A4
        )

    # … implement tất cả method Protocol; capability không có → trả None …

    async def warm(self) -> None:
        self._last_warm_ts = time.monotonic()
        try:
            ...  # nạp self._cache = {code: {code,name,region,type}}
        except Exception as exc:   # noqa: BLE001 — boot phải sống
            logger.warning("<ten> warm failed: %s", exc)

    async def warm_if_stale(self, ttl_sec: float) -> None:
        if ttl_sec <= 0 or (time.monotonic() - self._last_warm_ts) < ttl_sec:
            return
        await self.warm()

    def registry_rows(self): return [base.ProjectRegistryRow(**v) for v in self._cache.values()]
    def cached_codes(self):  return list(self._cache)
    def code_to_name(self):  return {c: v["name"] for c, v in self._cache.items()}
```

Serializer (`_serialize.py`) **không cần sửa** — nó nhận DTO chuẩn và tự render.
Extras được render tự động qua `active_extra_specs()`.

### A4. (Tuỳ chọn) Tier-1 — `extras` bag: field ngoài core, cho LLM ĐỌC

Khi nguồn có một field mà DTO core không mô hình hoá, và bạn muốn nó **hiển thị**
cho LLM (không lọc). Ví dụ thật: `nbx.fundType`.

1. Khai báo trong provider:

```python
extra_specs = (
    base.ExtraFieldSpec(
        key="fund_type",           # key trong Unit.extras
        label="Loại quỹ căn",      # nhãn VN LLM/người đọc
        entity="unit",             # "unit" | "project" | "pricing"
        type="string",
        unit="",                   # "vnd" | "m2" | "pct" | ""  → tự thêm hậu tố
        description="Nhóm quỹ căn (vd 'hot').",
    ),
)
```

2. Nhét value vào `extras` khi build DTO:

```python
extras = {}
if (fund := (raw.get("fundType") or "").strip()):
    extras["fund_type"] = fund
# … base.Unit(..., extras=extras)
```

Serializer tự render `{"Loại quỹ căn": "hot"}` vào JSON tool trả về, và
`builder.render_extras_appendix()` fold vào system prompt. **Không sửa gì thêm.**

### A5. (Tuỳ chọn) Tier-2 — `tool_params`: param LỌC mới trên tool chuẩn

Khi bạn muốn LLM **truyền được một tham số lọc mới** (nguồn có, core không). Ví dụ
thật: nbx khai báo `fund_type` là filter param trên `search_units`.

```python
tool_params = (
    base.ToolParamSpec(
        tool="search_units",       # tool đích
        name="fund_type",          # tên param LLM điền
        type="string",
        description="Lọc căn theo nhóm quỹ căn. Chỉ truyền khi khách nêu rõ.",
        maps_to="fund_type",       # key trong Unit.extras để so khớp
        match="eq",                # eq | substring | gte | lte | exists | contains
    ),
)
```

Cơ chế tự động (không cần viết code lọc):
- `schemas.build_schemas(names)` **inject** param này vào JSON schema của tool đích.
- Dispatch **collect** giá trị param (`collect_custom_params`).
- Framework **lọc** kết quả theo `item.extras[maps_to]` bằng `match`
  (`filter_by_custom_params`) — như một safety net kể cả khi adapter không tự lọc.
- 6 toán tử `match`: `eq`, `substring` (case-insensitive), `gte`/`lte` (float),
  `exists`, `contains`. Thiếu `extras[maps_to]` → loại, TRỪ `exists`-falsy.

> Muốn tối ưu server-side: adapter đọc `query.custom_params` trong `search_units`
> và lọc ngay ở DB/API. Framework vẫn re-apply filter sau đó (idempotent).

### A6. Đăng ký factory + config

`data/providers/__init__.py::get_provider` — thêm nhánh (lazy-import để không kéo
dependency khi không dùng):

```python
elif source == "<ten>":
    from noble_agent.data.providers.<ten> import MyProvider
    provider = MyProvider()
```

Nếu có endpoint/credentials → thêm field vào `config.py` (`UnifiedSettings`) và
truyền vào constructor như `sales_api` đang làm (`base_url`/`timeout`/`token`).
Document trong `.env.example`.

Đổi nguồn khi chạy: `NOBLE_DATA_SOURCE=<ten>` trong `.env`.

### A7. Test provider

Bắt buộc: test **mapping DTO** với fake DB/response (không cần Mongo thật) — mẫu
`tests/unit/unified/providers/test_nbx_mongo_provider.py`. Kiểm:
- price tỷ → VND int đúng, area float đúng, `status` map đúng enum.
- field thiếu → `None`.
- `search_units`/`recommend_units`/`discover_projects` filter đúng.
- `extras`/`tool_params` (nếu có) chảy qua serializer + `build_schemas`.

Và `test_factory.py`: `get_provider(settings)` trả đúng class cho `NOBLE_DATA_SOURCE=<ten>`
(nhớ `UnifiedSettings(_env_file=None)` để bỏ qua `.env` local nếu cần).

---

## Phần B — Provider dùng chung persona/brand Noble

Nếu chỉ đổi nguồn dữ liệu (vẫn là Noble về persona/brand/tool), bạn **dừng ở Phần A**.
Chạy với `TENANT_ID=noble` (mặc định) + `NOBLE_DATA_SOURCE=<ten>`. Xong.

---

## Phần C — Thêm một TENANT SaaS mới (brand/persona/tool khác)

Đây là khi bạn onboard một **khách hàng khác** (brand khác, giọng khác, bộ tool khác).

### C1. Tạo bundle trong package

```
src/noble_agent/tenants/<id>/
├── manifest.toml
├── persona/
│   ├── SOUL.md              # tính cách agent
│   ├── RULES.md             # protocol vận hành + tool catalog + guardrail
│   ├── PROMPT_TEMPLATE.md   # khung jinja2
│   ├── CUSTOMER_PROFILE.md  # block hồ sơ khách
│   └── config.json          # name/model/temperature/max_tokens (KHÔNG có "tools")
└── tools/                   # (tuỳ chọn) custom tool riêng tenant
    ├── __init__.py          # để trống — pkgutil sẽ tự walk submodule
    └── <ten_tool>.py
```

> Đặt **trong package** (không phải `tenants/` ở root) để nó ship trong wheel —
> giống `agent/definitions/` cũ. Đây là deviation có chủ đích so với sơ đồ spec.

### C2. `manifest.toml`

Nguồn chân lý runtime cho tenant. Mẫu (bám `tenants/noble/manifest.toml`):

```toml
tenant_id = "acme"
data_source = "<ten>"        # PHẢI mirror NOBLE_DATA_SOURCE đang chạy (test guard)
persona_dir = "persona"

[tools]
enabled = [                  # danh sách tool ĐƯỢC OFFER cho agent này
    "find_project", "update_customer", "kb_search",
    "discover_projects", "get_project_overview", "search_units",
    "booking", "escalate",
    "check_loan",            # ← custom tool riêng tenant (nếu có)
]
rankers = []                 # bỏ "feng_shui" nếu tenant không cần → param + overlay tự strip
media_channel = "acme_app"

[brand]
company = "Acme"             # thay {{ brand.company }} trong tool desc + persona
app_name = "AcmeApp"         # thay {{ brand.app_name }}
```

Loader (`tenant/loader.py::get_tenant_context`) **fail-loud** nếu thiếu thư mục /
TOML hỏng / thiếu `data_source`/`persona_dir`/`[tools].enabled`.

### C3. `rankers` — bật/tắt overlay (vd feng-shui)

- `rankers=["feng_shui"]` → `recommend_units` giữ param `birth_year/gender/menh/zodiac`
  + overlay bát-trạch/ngũ-hành (mặc định của Noble).
- `rankers=[]` (hoặc bỏ) → `build_schemas` **strip** 4 param đó + executor **bỏ** overlay.

Đây là plugin gate thuần khai báo — không sửa code tool.

### C4. Brand templating

Trong persona (SOUL/RULES) và mô tả tool chuẩn, dùng token `{{ brand.company }}` /
`{{ brand.app_name }}`. `build_schemas` (pass render brand, chạy CUỐI cùng sau khi
inject custom param) và `load_agent_def(..., brand=...)` sẽ thay bằng giá trị
manifest. Có fallback `_BRAND_DEFAULTS` (Noble/NobleX) + log guard nên **không token
thô nào lọt ra**.

> ⚠️ **Bẫy:** tên dự án như "Noble Crystal" phải giữ nguyên — KHÔNG token hoá. Chỉ
> token hoá chỗ nói về công ty/app. Xem test `test_project_name_examples_not_templated`.

### C5. (Tuỳ chọn) Custom tool riêng tenant

Thả **1 file** vào `tenants/<id>/tools/<ten_tool>.py`, decorate `@tool`:

```python
# tenants/acme/tools/loan.py
from noble_agent.agent.tools.registry import tool
from noble_agent.agent.tools import schemas  # nếu cần schema helper

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_loan",
        "description": "Tính khoản vay cho khách Acme.",
        "parameters": {"type": "object", "properties": {
            "amount_vnd": {"type": "integer"}}, "required": ["amount_vnd"]},
    },
}

@tool(name="check_loan", schema=_SCHEMA, tenant="acme",
      read_only=True, dirties_customer=False)
async def check_loan(args, *, provider, tenant, **_) -> str:
    ...
    return "…"   # string trả về LLM
```

- `tools/__init__.py` **để trống** — `_import_tenant_tools` dùng `pkgutil.iter_modules`
  walk mọi submodule để decorator tự-register lúc boot.
- Custom tool **chỉ thấy bởi tenant đó**; shadow được built-in cùng tên (chỉ cho
  tenant đó). Thêm tên vào `manifest.enabled` để được offer.
- Mẫu isolation có sẵn: `tenants/demo_acme/tools/loan.py` (`check_loan`, tenant
  `demo_acme` — inert trừ khi `TENANT_ID=demo_acme`).

### C6. Chạy tenant

```bash
TENANT_ID=acme NOBLE_DATA_SOURCE=<ten> USE_UNIFIED_AGENT=true scripts/run.sh
```

### C7. Test tenant

- `test_context.py` / `test_loader.py` — manifest parse + fail-loud.
- `test_custom_tool_loading.py` — custom tool self-register + isolation (thấy ở
  tenant mình, không thấy ở tenant khác).
- `test_brand_and_rankers.py` — brand render + no-token-leak + ranker strip on/off.

---

## D. Gate cuối (bắt buộc trước khi coi là xong)

```bash
make test-unit      # phải ZERO new failures so với baseline
make lint           # ruff clean trên file bạn đụng
```

**Baseline 8 fail đã biết** (KHÔNG phải do bạn) tính đến Phase 3d: 2 USD-normalize,
2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:', 1
local-.env media. Nếu con số fail = baseline → pass.

Sau đó chạy **live `/chat` smoke** theo `src/noble_agent/SMOKE.md` (bất kỳ thay đổi
turn loop/prompt/transport). Với provider mới: hỏi tổng quan 1 dự án, discover, giá,
search unit — kiểm số liệu THẬT và escalate đúng khi nguồn thiếu.

---

## E. Cạm bẫy thường gặp (đã dính trong lịch sử repo)

1. **Quên nhân `1e9`** khi nguồn để giá theo tỷ → LLM báo giá sai 1 tỷ lần.
2. **Trả `[]` thay vì `None`** (hoặc ngược lại) → escalate sai / không escalate.
3. **Để lộ `id`/`uuid`/`slug`** ra DTO thay vì canonical code → filter Qdrant
   0-hit, Redis lưu code rác.
4. **`warm()` không nuốt exception** → nguồn chết làm sập boot (nhất là LiveKit
   prewarm chạy trong loop throwaway — xem row 2026-07-02 trong CLAUDE.md).
5. **Motor client bound sai event loop** nếu warm dưới `asyncio.run()` mà không
   `close_mongo()` — xem cùng row.
6. **Token brand hoá tên dự án** → "Noble Crystal" biến mất.
7. **`manifest.data_source` không mirror `NOBLE_DATA_SOURCE`** → test guard fail.
8. **Custom tool không self-register** vì `tools/__init__.py` import tay thay vì để
   `pkgutil` walk — để trống `__init__.py`.
9. Quên cập nhật **`RULES.md` tool catalog** khi thêm tool → LLM không biết khi nào gọi.

---

## F. Bản đồ file tham chiếu

| Việc | File |
|---|---|
| Contract + DTO + Protocol | `data/providers/base.py`, `docs/BA/spec_provider.md` |
| Factory | `data/providers/__init__.py` |
| Provider Mongo mẫu | `data/providers/nbx_mongo.py` |
| Provider HTTP mẫu (có DNS cache) | `data/providers/sales_api.py` |
| Serializer DTO→JSON | `data/providers/_serialize.py` |
| Tier-2 engine | `agent/tools/custom_params.py` |
| Build schema (inject param + strip ranker + render brand) | `agent/tools/schemas.py::build_schemas` |
| Registry ToolSpec + `@tool` | `agent/tools/registry.py` |
| Built-in 15 tool | `agent/tools/builtins.py` |
| Dispatcher | `agent/tools/dispatcher.py` |
| Tenant context + loader | `tenant/context.py`, `tenant/loader.py` |
| Tenant mẫu | `tenants/noble/`, `tenants/demo_acme/` |
| Spec tổng | `docs/superpowers/specs/2026-07-23-saas-multi-tenant-provider-tools-design.md` |
| Handoff Phase 1–3 | `docs/superpowers/HANDOFF-saas-refactor.md` |
