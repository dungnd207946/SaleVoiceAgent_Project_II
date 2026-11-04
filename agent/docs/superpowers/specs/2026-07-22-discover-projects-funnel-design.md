# Discovery theo funnel: `list_projects` → `discover_projects` (thu hẹp + phân trang)

**Ngày:** 2026-07-22
**Nhánh:** `feat/refactor2`
**Trạng thái:** Design — chờ implement

## 1. Vấn đề

`list_projects` mang ngữ nghĩa **"liệt kê"**: nó fetch mọi dự án khớp (region filter
server-side + phân trang toàn bộ) rồi trả về danh sách đầy đủ `{code, name, type,
region}`. Ở quy mô hàng nghìn dự án:

- Tìm theo khu vực hoặc theo chủ đầu tư vẫn trả ra hàng trăm dự án → **bẩn context**
  của agent cho một câu hỏi vốn chỉ mang tính overview.
- Vô nghĩa qua **voice**: Luna không thể đọc 300 tên dự án qua điện thoại.

Đây là câu hỏi discovery ("bên mình có dự án gì?", "dự án ở khu A?", "dự án của CĐT
X?") — khách hàng mới chưa biết chọn gì. Một chuyên viên sale thật **không** đọc
catalog; họ khai thác tiêu chí và thu hẹp về vài lựa chọn phù hợp.

Ba tool cấp-dự-án/căn hiện có và khoảng trống:

- `find_project` — giải tên nói → mã canonical (khách **đã biết** tên dự án).
- `recommend_units` — gợi ý **căn hộ** cụ thể xuyên dự án + overlay phong thủy.
- `list_projects` — liệt kê dự án (khoảng trống: discovery ở quy mô lớn).

## 2. Nguyên tắc kiến trúc

Agent là sản phẩm **SaaS production**. Ranh giới cứng:

- **Tool (agent-facing, provider-agnostic):** định nghĩa **tham số & enum chuẩn hoá**,
  validate, tính toán logic agent (gợi ý thu hẹp, câu instruction, phân trang), cap
  top-N, serialize wire shape. Tool **không biết gì** về API cụ thể.
- **Adapter / provider (`sales_api` / `mongo`):** map tham số chuẩn → field/param
  riêng của nguồn, lọc server-side phần nào nguồn hỗ trợ + lọc/xếp-hạng/đếm in-process
  phần còn lại, trả về **DTO canonical**. Việc đấu nối API thuộc adapter.

Khớp sẵn với tầng `DataProvider` Protocol + DTO canonical trong
`data/providers/base.py`.

## 3. Quyết định hành vi (đã chốt với user)

1. **Funnel (tư vấn thu hẹp):** Luna **không bao giờ** đọc danh sách. Câu quá mở →
   hỏi 1 tiêu chí trước, rồi gọi tool trả về top-K dự án phù hợp.
2. **Trục thu hẹp:** khu vực, ngân sách, loại hình sản phẩm, mục đích + chủ đầu tư.
3. **Tín hiệu thu hẹp:** tool trả **top-K + tổng số (`total`) + gợi ý trục hỏi tiếp**
   để Luna biết còn bao nhiêu và nên hỏi gì.
4. **Xếp hạng:** **hot/nổi bật trước** (dùng `isHot`/`isFeatured`/`sortHot`/`sortOrder`
   trên dữ liệu dự án), rồi tie-break để tạo thứ tự toàn phần ổn định.

## 4. Contract `discover_projects` (agent-facing)

Đổi tên `list_projects` → `discover_projects`. Ngữ nghĩa đổi từ "liệt kê" →
"gợi ý top phù hợp + báo còn bao nhiêu + phân trang".

### 4.1 Tham số (chuẩn hoá, độc lập nguồn)

```
discover_projects(
  region?:       string   # free-text địa danh khách nói; adapter map sang area_region
  budget_max?:   number   # tỷ VND (giống recommend_units); adapter × 1e9 → VND
  product_type?: enum[chung_cu | biet_thu | lien_ke | shophouse | dat_nen | van_phong]
                          # token romanized VN (khớp precedent menh/zodiac); adapter map sang API `type`
  purpose?:      enum[live | invest]
  investor?:     string   # free-text thương hiệu CĐT
  index?:        integer  # offset phân trang, default 0
)
```

- `product_type` / `purpose` là **enum cứng** — adapter chịu trách nhiệm ánh xạ sang
  token nội bộ của nguồn.
- `region` / `investor` để **free-text** vì giá trị động theo dữ liệu.

### 4.2 Kết quả trả về

```json
{
  "total": 213,
  "index": 0,
  "count": 5,
  "projects": [
    {"code": "...", "name": "...", "region": "...", "type": "...",
     "investor": "...", "price_from_vnd": 0, "hot": true}
  ],
  "has_more": true,
  "next_index": 5,
  "suggested_narrow": ["budget_max", "product_type"],
  "instruction": "Giới thiệu 5 dự án nổi bật này, rồi hỏi khách muốn thêm tiêu chí (ngân sách/loại hình) hay nghe thêm 208 dự án còn lại."
}
```

- `total` (N): tổng dự án khớp trước khi cắt trang.
- `count` (K): số trả về trang này = `NOBLE_DISCOVER_PAGE_SIZE` (config, default 5).
- `has_more` = `index + count < total`; `next_index` = `index + count` (chỉ có ý nghĩa khi `has_more`).
- `suggested_narrow`: **tool tính** — danh sách trục canonical mà khách **chưa** cung
  cấp (trong {`budget_max`, `product_type`, `purpose`, `investor`, `region`}), để Luna
  chọn câu hỏi thu hẹp. Không phải việc của adapter.
- `instruction`: **tool sinh** — câu hướng dẫn Luna, tuỳ theo `total`/`has_more`.

### 4.3 Luồng phân trang

- `index=0` → trả `[0, K)`. Luna đọc ≤3 tên nổi bật + gợi ý *thêm tiêu chí* **hoặc**
  *xem thêm N−K dự án còn lại*.
- Khách muốn xem thêm → gọi lại **cùng tham số**, `index = K` → trả `[K, 2K)`.
- Khách cho thêm tiêu chí → gọi lại **tiêu chí mới**, `index = 0`.

**Invariant (then chốt):** adapter phải xếp hạng theo một **thứ tự toàn phần ổn
định** (hot desc → `sortHot`/`sortOrder` asc → tie-break theo `code`) để trang 2
không lặp lại hoặc nhảy sót phần tử so với trang 1 giữa các lần gọi cùng tham số.

## 5. Tầng provider (DTO canonical mới)

Thêm vào `data/providers/base.py`:

```python
@dataclass(frozen=True)
class DiscoverQuery:
    region: str = ""
    budget_max_vnd: int = 0
    product_type: str = ""      # canonical enum value
    purpose: str = ""           # canonical enum value
    investor: str = ""
    offset: int = 0
    limit: int = 5              # = K (config)

@dataclass(frozen=True)
class ProjectDiscovery:
    total: int                  # N — tổng khớp trước cắt trang
    projects: list[ProjectSummary]   # slice [offset, offset+limit), ĐÃ ranked
```

Thêm vào `DataProvider` Protocol:

```python
async def discover_projects(self, query: DiscoverQuery) -> ProjectDiscovery | None: ...
```

Trách nhiệm adapter:

1. Dịch `DiscoverQuery` → param/field riêng của nguồn.
2. Lọc server-side phần nguồn hỗ trợ; phần còn lại lọc in-process (bounded, như
   pattern `_fetch_all_projects` hiện tại).
3. Xếp hạng hot-first theo **thứ tự toàn phần ổn định**.
4. Đếm `total` (tổng khớp), cắt `[offset : offset+limit]`.
5. `None` khi nguồn lỗi/gap (giống các method khác) → tool trả `ESCALATE_SIGNAL`.

### 5.1 `sales_api`

- `region` → `area_region` (server-side, đã có).
- `budget_max_vnd` → `price_max` (tỷ) nếu `/api/v1/projects` hỗ trợ; nếu không → lọc
  in-process.
- `product_type` (canonical) → ánh xạ sang token API `type`; `investor` → so khớp field
  `investor`. **Cần xác minh** endpoint list hỗ trợ các filter/sort/offset này tới đâu;
  phần không hỗ trợ → fetch-all rồi lọc/xếp/cắt in-process.
- Ranking: `isHot`/`isFeatured` desc → `sortHot`/`sortOrder` asc → `code`.

### 5.2 `mongo`

- Map các trục sang field tương đương trong `project_du_an`.
- Ranking hot-first bằng field tương đương của mongo (hoặc tie-break theo `code` nếu
  không có cờ hot) — vẫn phải là thứ tự toàn phần ổn định.

## 6. `recommend_units`: thêm `project_code`

Thêm tham số **optional** `project_code` vào `recommend_units`:

- Không truyền → xuyên tất cả dự án (hành vi hiện tại, không đổi).
- Truyền → gợi ý căn **hợp phong thủy trong riêng dự án đó**.

Đây là rung cuối của funnel: `discover_projects` (chọn dự án X) →
`get_project_overview` → `recommend_units(project_code=X)`.

Khác `search_units` (tra cứu căn trong 1 dự án đã nêu rõ, không có ranking phong
thủy): `recommend_units(project_code=X)` **có** lớp xếp hạng hợp phong thủy.

Chạm: `schemas.py` (thêm param + mô tả phân biệt search_units), `RecommendQuery`
(thêm `project_code`), adapter `recommend_units` (khi có `project_code` → scope về 1
dự án). Không đổi lớp feng-shui/guard.

## 7. Prompt (RULES.md)

- Viết lại rule discovery: câu quá mở ("bên mình có dự án gì?") → Luna **hỏi 1 tiêu
  chí trước** (khu vực/ngân sách/nhu cầu) rồi mới gọi `discover_projects`; **không
  đọc quá ~3 tên/lượt** qua voice.
- Dạy Luna:
  - Dùng `total` + `suggested_narrow` để quyết định hỏi thêm tiêu chí nào.
  - Dùng `has_more`/`next_index` khi khách muốn "xem thêm" (gọi lại cùng tham số +
    `index = next_index`).
  - Cho thêm tiêu chí → gọi lại tiêu chí mới với `index = 0`.
- Cập nhật tool-catalog: đổi `list_projects` → `discover_projects` (khi nào + làm gì +
  1 ví dụ), cập nhật `recommend_units` cho `project_code`.

## 8. Điểm chạm (implementation surface)

| File | Thay đổi |
|---|---|
| `agent/tools/schemas.py` | rename `list_projects`→`discover_projects` + schema mới (enum, index); thêm `project_code` vào `recommend_units` |
| `agent/tools/projects_info.py` | rename hàm; shape kết quả (has_more/next_index/suggested_narrow/instruction); tính suggested_narrow; forward `project_code` cho recommend_units |
| `agent/tools/dispatcher.py` | đổi nhánh dispatch `list_projects`→`discover_projects` |
| `agent/definitions/config.json` | offered tools: `list_projects`→`discover_projects` |
| `agent/definitions/RULES.md` | rule discovery + tool-catalog |
| `data/providers/base.py` | `DiscoverQuery` + `ProjectDiscovery` DTO + Protocol method; `project_code` trong `RecommendQuery` |
| `data/providers/sales_api.py` | implement `discover_projects`; scope `recommend_units` theo `project_code` |
| `data/providers/mongo.py` | implement `discover_projects`; scope `recommend_units` theo `project_code` |
| `config.py` | `NOBLE_DISCOVER_PAGE_SIZE` (default 5) |
| `.env.example` | tài liệu setting mới |
| tests | unit cho `discover_projects` (tool + cả 2 provider), phân trang, suggested_narrow, `recommend_units(project_code=)` |

## 9. Rủi ro / ngoài phạm vi

- **Roster tĩnh** (`docs/api/project_code_map.json`, `find_project` build
  `ProjectNameIndex` lúc bootstrap từ `registry_rows()`, `name_to_code` lọc trong
  `list_projects`) vẫn giả định roster **đếm được, enumerable**. Ở quy mô vài nghìn
  vẫn tạm ổn; ở chục nghìn cần chuyển việc resolve/registry sang server-side. **Ghi
  chú — ngoài phạm vi lần này.**
- **Năng lực API:** cần xác minh `/api/v1/projects` hỗ trợ filter `type`/`investor`,
  sort hot, offset server-side tới đâu. Phần không hỗ trợ → adapter fetch-all rồi
  lọc/xếp/cắt in-process (bounded, chấp nhận ở quy mô hàng trăm; ở hàng nghìn nên đẩy
  server-side — theo dõi khi có endpoint search phù hợp).
- **Ổn định phân trang** phụ thuộc thứ tự toàn phần ổn định ở adapter; nếu dữ liệu hot
  đổi giữa 2 lần gọi, trang có thể lệch nhẹ (chấp nhận — best-effort cho voice).

## 10. Tiêu chí hoàn thành

- `discover_projects` trả ≤K dự án + `total` + `has_more`/`next_index` +
  `suggested_narrow` + `instruction`; phân trang lặp lại đúng bằng `index`.
- Ranking hot-first, thứ tự toàn phần ổn định (test phân trang không lặp/sót).
- `recommend_units(project_code=X)` scope đúng 1 dự án, giữ nguyên lớp phong thủy.
- Cả 2 provider (`sales_api`, `mongo`) implement `discover_projects`.
- RULES.md dạy đúng luồng funnel + xem-thêm + thu-hẹp.
- Unit tests xanh; `make test-unit` không thêm regression.
