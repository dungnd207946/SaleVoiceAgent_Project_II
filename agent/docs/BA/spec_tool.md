# Spec Tool — Bộ câu hỏi BĐS ↔ Nguồn dữ liệu ↔ Tool

Spec định hướng **thiết kế lại bộ tool** cho agent sale bất động sản (Luna), sao cho phủ được các nhóm câu hỏi thực tế của người mua. Mỗi nhóm câu hỏi được ánh xạ tới **nguồn dữ liệu** (Sales API endpoint / RAG / code / nội bộ) và **tool** đảm nhiệm.

- **Đối tượng đọc:** người thiết kế tool + adapter provider.
- **Contract dữ liệu nền:** [`docs/BA/spec_provider.md`](./spec_provider.md) (DTO canonical, đơn vị, ngữ nghĩa `None`/rỗng). Bảng field-mapping thật ở §9 của file đó.
- **Nguồn API:** [`docs/api/spec_api.md`](../api/spec_api.md) + response live `nbx-sales-api-dev.noble.vn` (xác minh 2026-07-21).
- **Phạm vi agent:** pre-sale (tư vấn + đặt lịch xem). Post-sale, giá private, chính sách chiết khấu sâu → `escalate` người thật.

---

## 1. Bốn nguồn dữ liệu khả dụng

| Nguồn | Là gì | Dùng cho |
|---|---|---|
| **A. Sales API provider** (`data/providers/sales_api.py`) | Dữ liệu **cấu trúc** thật: dự án, căn, giá, diện tích, hướng, trạng thái | Danh mục, tra căn, bảng giá, tồn kho, gợi ý |
| **B. RAG** (`noble_search` → `noble_kb`) | Tri thức **văn bản**: tiện ích, vị trí, pháp lý, mô tả, so sánh, "để ở hay đầu tư" | Câu hỏi định tính, tư vấn, không có field cấu trúc |
| **C. Code tất định** (`agent/feng_shui.py`) | Tính mệnh/cung/hướng hợp từ năm sinh + giới tính | Phong thủy — KHÔNG để LLM bịa hướng |
| **D. Nội bộ** (`booking`, `escalate`, `send_media`, `update_customer`) | Hành động: đặt lịch, chuyển người thật, gửi media, lưu hồ sơ | Chốt cuộc, handoff, minh họa |

**Bảng năng lực nhanh của Sales API** (chi tiết field ở spec_provider §9):

| Khả năng | Server-side filter? | Ghi chú |
|---|---|---|
| Lọc dự án theo vùng/loại hình | ✅ `area_region`, `type` | |
| Lọc căn theo **ngân sách** | ✅ `price_min`/`price_max` (đơn vị **tỷ**) | trên `hot-units` |
| Lọc căn theo **vùng miền** (cross-project) | ✅ `region` | trên `hot-units` |
| Lọc căn theo **diện tích** | ✅ `area_min`/`area_max` | |
| Lọc căn theo **hướng** | ✅ `direction` (**điền tốt: ~76% căn dev**) | phục vụ phong thủy |
| Lọc theo **loại căn** | ✅ `unit_type_id`, `group`, `zone` | |
| **Trạng thái** còn/hết | ⚠️ chỉ per-project (`/projects/{slug}.units[].status`) | `hot-units` list không có |
| **Tầng / vị trí** trong tòa | 🔴 field tồn tại nhưng **rỗng 0/437 căn dev** | chờ prod |
| **View, số PN (chuẩn), giá/m²** | ✗ | suy hoặc `None` |
| **Chính sách / CSBH / ưu đãi** | 🔴 field tồn tại, **rỗng 0/437 căn** cả khi authed (`gated` chỉ là cờ auth) | → RAG / escalate |
| **Tiến độ / bàn giao** | 🔴 `/progress` OK khi authed nhưng gần rỗng (1/20 dự án) | → RAG / escalate |

---

## 2. Nguyên tắc chung khi thiết kế tool

1. **Model chỉ nói ngôn ngữ canonical**: `project_code` (chữ HOA), ngân sách theo **tỷ** (tool ×1e9 trước khi vào provider), region enum. Không bao giờ để `id`/`slug`/`uuid` lọt ra tham số model.
2. **`None` → escalate, rỗng → mời nới tiêu chí**: nguồn down / không có nguồn / dự án không tồn tại ⇒ provider trả `None` ⇒ tool trả `ESCALATE_SIGNAL` ⇒ auto-escalate CVTV. Lọc ra 0 kết quả ⇒ trả list rỗng ⇒ mời khách đổi tiêu chí, **không** escalate.
3. **Đẩy filter về server khi có thể** (ngân sách/vùng/diện tích/hướng) để bó payload — `hot-units` không phân trang.
4. **Định tính → RAG, định lượng → API.** Đừng ép API trả lời "để ở hay đầu tư", "phân khúc", "gần trường" — đó là RAG.
5. **Phong thủy tính bằng code**, chỉ dùng kết quả (danh sách hướng hợp) làm filter `direction`.
6. **Gated/không có nguồn thì escalate thẳng** — không hứa suông (xem invariant auto-escalate trong CLAUDE.md).

---

## 3. 14 nhóm câu hỏi → nguồn → tool

Cột **Độ phủ**: 🟢 đủ · 🟡 một phần · 🔴 gap (RAG/escalate).

### 1. Tổng quan danh mục dự án
> *"Bên em đang mở bán những dự án nào, ở khu vực nào, phân khúc gì?"* · *"Dự án nào bàn giao/ở ngay, dự án nào còn xây?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Danh sách dự án + vùng + loại hình | `GET /projects` (`area_region`,`type`) | **`list_projects`** | 🟢 |
| Phân khúc (bình dân→hạng sang) | Không có field → suy từ giá / RAG `overview` | `noble_search` | 🟡 |
| Bàn giao/ở ngay vs đang xây | `/progress` lỗi trên dev → RAG / escalate | `noble_search` / `escalate` | 🔴 |

### 2. Loại hình sản phẩm
> *"Có căn hộ, nhà phố, biệt thự, shophouse, đất nền, condotel…?"* · *"Trong ngân sách của tôi thì loại nào hợp?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Loại hình mỗi dự án | `overview.product` (chuỗi vd `"Căn hộ, nhà phố, biệt thự, shophouse"`) + `type`/`unitType.group` | **`get_project_overview`** | 🟡 |
| Danh mục loại căn hộ | `GET /apartment-types` (`{id,name,group}`) | **`list_projects`/`recommend_units`** (nội bộ dùng để map) | 🟢 |
| Loại nào hợp ngân sách | filter giá + gợi ý | **`recommend_units`** | 🟢 |

### 3. Ngân sách & tầm giá
> *"Khoảng X tỷ mua được gì, dự án nào?"* · *"Giá dao động thấp→cao mỗi dự án?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Căn trong tầm tiền (cross-project) | `hot-units?price_min&price_max&region` (**server-side**, đơn vị tỷ) | **`recommend_units`** | 🟢 |
| Dải giá theo loại căn trong 1 dự án | aggregate `/projects/{slug}.units[].price` | **`get_project_financial`** (pricing) | 🟢 |
| 4 mốc giá thanh toán | `price`/`priceTts`/`priceTttd`/`priceLoan` (×1e9) | `get_project_financial` | 🟡 |

### 4. Diện tích & số phòng ngủ
> *"Có loại mấy PN, diện tích bao nhiêu m²?"* · *"Cần căn 3PN, có loại nào, giá bao nhiêu?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Lọc theo diện tích | `hot-units?area_min&area_max` (server-side) | **`search_units`/`recommend_units`** | 🟢 |
| Số phòng ngủ | suy từ `unitType.name` (`"2PN"→2`,`"Studio"→0`); thấp tầng→None | `search_units` (filter client-side sau suy) | 🟡 |

### 5. Hướng nhà & view
> *"Còn căn hướng Bắc / view sông không?"* · *"Hướng nào còn nhiều, hướng nào gần hết?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Lọc theo hướng | `hot-units?direction` / `units[].direction` (**điền ~76%**) | **`search_units`** | 🟢 |
| View (sông/công viên) | ✗ field → RAG mô tả dự án | `noble_search` | 🔴 |
| "Hướng nào còn nhiều/hết" | aggregate `units[].direction`×`status` (chỉ 3b có status) | **`check_inventory`** (đã thêm §4) | 🟡 |

### 6. Phong thủy & mệnh
> *"Tôi mệnh Mộc (tuổi…), căn nào hợp hướng, hợp tầng?"* · *"Có bảng tra theo tuổi/mệnh/hướng không?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Tra mệnh/cung/hướng hợp (chưa cần căn) | **code** `agent/feng_shui.py` (qua overlay của recommend_units, trả kèm phần "đọc phong thủy") | **`recommend_units`** | 🟢 |
| Mệnh → lọc căn hợp hướng | đổ hướng hợp vào `direction` filter (`direction` điền ~76%) | **`recommend_units`** (feng-shui overlay, sort hợp lên đầu) | 🟢 |
| Hợp **tầng** | ✗ (tầng rỗng 0/437 dev) → tư vấn định tính | `noble_search`/escalate | 🔴 |

### 7. Tầng & vị trí trong tòa
> *"Còn căn tầng trung/cao yên tĩnh không?"* · *"Căn góc, thông tầng, gần thang máy còn không?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Tầng | field `floor`/`floorMin`/`floorMax` (chỉ 3b) **rỗng 0/437 dev** → chờ prod | **`search_units`** (khi prod có data) | 🔴 |
| Căn góc / thông tầng / gần thang máy | ✗ field (có `axis`/`front` nhưng không chuẩn hóa) → RAG | `noble_search` | 🔴 |

### 8. Mục đích mua (ở hay đầu tư)
> *"Mua để ở thì dự án nào, đầu tư cho thuê thì dự án nào tốt hơn?"* · *"Dự án nào tiềm năng tăng giá?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Tư vấn ở/đầu tư, tiềm năng | ✗ định tính → RAG (mô tả, vị trí, tiện ích) | **`noble_search`** | 🔴 |
| Chốt sâu | nếu khách nghiêng đầu tư lớn / cần số liệu → escalate | `escalate` | — |

### 9. Tiến độ & thời điểm nhận nhà
> *"Muốn ở trong 1 năm tới, dự án nào kịp bàn giao?"* · *"Có sản phẩm đã có sổ, ở ngay không?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Tiến độ xây/bàn giao | `/progress` gần rỗng dev (1/20 dự án) → RAG / escalate | `noble_search`/`escalate` | 🔴 |
| Sở hữu (sổ) | `overview.ownership` (vd `"Lâu dài"`); `units[].legal` (rỗng dev) | `get_project_overview` | 🟡 |

### 10. Chính sách & ưu đãi
> *"Đang có chương trình ưu đãi/chiết khấu nào?"* · *"Hỗ trợ vay, ân hạn gốc/lãi, quà tặng?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| CSBH / vay / quà | `units[].csbhBrief/Full`,`loanInfo`,`bankSupport`,`gift` — **rỗng 0/437 cả khi authed** (`gated` chỉ là cờ auth, không phải nguyên nhân) | `get_project_financial` → null **escalate** | 🔴 |
| Tin ưu đãi công khai | `GET /articles` (nếu có category ưu đãi) | `noble_search`/`escalate` | 🟡 |
| Chiết khấu sâu / giá private | luôn người thật | **`escalate`** (CVTV) | — |

### 11. Mua số lượng nhiều (sỉ)
> *"Mua 2–3 căn có chính sách giá đặc biệt không?"* · *"Gói cho nhà đầu tư mua nhiều căn?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Chính sách mua sỉ | ✗ không có nguồn → người thật | **`escalate`** (CVTV) | 🔴 |

### 12. Vị trí & tiện ích khu vực
> *"Dự án nào gần trung tâm/trường/chỗ làm khu X?"* · *"Dự án nào nhiều tiện ích nội khu, giao thông thuận tiện?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Vị trí, điểm nhấn, tọa độ | `GET /projects/{slug}` (`location`,`locationHighlights[]`,`lat/lng`,`overview`) | **`get_project_overview`** | 🟡 |
| "gần X" / so sánh tiện ích | ✗ filter → RAG | **`noble_search`** | 🔴 |

### 13. Tình trạng hàng còn lại
> *"Dự án tôi quan tâm còn bao nhiêu căn, còn loại nào?"* · *"Loại tôi thích hết chưa, nếu hết thì dự án tương tự?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Còn/hết + đếm | `/projects/{slug}.units[].status` (**3b**, `available`…) | **`search_units`** (đếm `available_units`) | 🟡 |
| "Tương tự nếu hết" | suy từ `unitType`/`area`/giá + gợi ý | **`recommend_units`** | 🟢 |
| ⚠️ Chỉ trong **quỹ hot** | qua `hot-units` là quỹ hot, không phải toàn inventory | (nói rõ với khách) | 🟡 |

### 14. Đi xem thực tế & bảng hàng tổng hợp
> *"Khi nào đi xem nhà mẫu/căn thực tế?"* · *"Gửi giúp bảng hàng tổng hợp giá/diện tích/hướng để tôi lọc trước?"*

| Dữ liệu cần | Nguồn | Tool | Độ phủ |
|---|---|---|---|
| Đặt lịch xem | nội bộ (dự án + ngày + giờ) | **`booking`** (`check_availability`/`schedule`/`list`/`modify`) | 🟢 |
| Bảng hàng tổng hợp | compose `hot-units`/`units[]` (giá/diện tích/hướng) → gửi | **`search_units`/`recommend_units`** + **`send_media`** | 🟡 |
| Gửi ảnh/video/brochure | CMS media | **`send_media`** | 🟢 |

---

## 4. Bộ tool đề xuất (catalog thiết kế lại)

Kết luận: **10 tool core hiện có là hợp lý, không xé nhỏ**; đã thêm **1 tool chuyên biệt** `check_inventory` (§4.1) → tổng **11 tool** (2026-07-21). Phong thủy **giữ trong `recommend_units`** (không tách tool riêng). §4.2 liệt kê những tool cố ý KHÔNG thêm, §4.3 là nguyên tắc phân mảnh.

Bảng dưới là **10 tool core**: mục đích, nguồn, tham số canonical, khi nào escalate. Cột "Đổi so với hiện tại" nêu điều chỉnh nên làm.

| Tool | Mục đích (nhóm câu hỏi) | Nguồn | Tham số canonical | Escalate khi | Đổi so với hiện tại |
|---|---|---|---|---|---|
| **`list_projects`** | Danh mục dự án (#1) | `GET /projects` | `region?`, `type?` | nguồn down (`None`) | — |
| **`get_project_overview`** | Tổng quan 1 dự án: loại hình, sở hữu, vị trí, tiện ích top (#1,#2,#9,#12) | `GET /projects/{slug}` | `project_code` | dự án không tồn tại | **decode `overview` JSON**; expose `product`/`ownership`/`units_text` |
| **`get_project_financial`** | Bảng giá theo loại căn + 4 mốc thanh toán (#3,#10) | aggregate `/projects/{slug}.units[]` | `project_code`, `info_type` | info-type không có nguồn / CSBH gated null | pricing 🟢; payment/loan/promo → escalate |
| **`search_units`** | Tra căn trong **1 dự án**: diện tích/hướng/tầng/còn-hết (#4,#5,#7,#13) | `GET /projects/{slug}.units[]` | `project_code`, `unit_type?`, `min_area?`, `direction?`, `status?` | project không resolve / không inventory | dùng **3b** để có `status`/`floor`; bỏ filter `tower`/`view` |
| **`recommend_units`** | Gợi ý **cross-project** theo ngân sách/vùng/PN + phong thủy (#3,#4,#6,#13) | `GET /hot-units` + `feng_shui.py` | `region?`, `budget_max?`(tỷ), `bedrooms?`, `good_directions?` | roster rỗng / nguồn down | **push `price_min`/`price_max`/`region` server-side**; feng-shui sort giữ nguyên |
| **`noble_search`** | Định tính: phân khúc, view, "để ở/đầu tư", tiện ích, so sánh, tiến độ (#1,#2,#5,#8,#9,#12) | RAG `noble_kb` | `query`, `project_filter?` | — (RAG rỗng → nói không có) | roster RAG phải **re-ingest** theo dự án Sales API |
| **`booking`** | Đặt lịch đi xem (#14) | nội bộ (Mongo) | `action`, `project_code`, `date`, `time` | — | — |
| **`send_media`** | Gửi ảnh/video/bảng hàng (#14 + minh họa #1) | CMS `project_media` | `project_code`, `category?`, `query?` | — | — |
| **`escalate`** | CSBH gated, chính sách/chiết khấu, mua sỉ, giá private, post-sale (#10,#11) | người thật | `department`, `reason` | (chính nó) | — |
| **`update_customer`** | Lưu nhu cầu khách (ngân sách/PN/vùng/mục đích) để cá nhân hóa gợi ý | Redis `Customer` | các field hồ sơ | — | không dùng để lưu tên/SĐT booking |

### 4.1 Đã thêm — 1 tool chuyên biệt `check_inventory` (11 tool, 2026-07-21)

Intent "còn hàng không" trước đây bị "nhồi" vào `search_units` nhưng có **shape trả về khác** (tóm tắt đếm ≠ danh sách căn); tách ra giúp model yếu (gemini-flash/qwen) chọn đúng và hợp kênh voice. Đã implement trên **cả hai** provider (`sales_api` + `mongo`) qua capability `get_inventory_summary`:

**`check_inventory(project_code)` — "còn hàng không / còn bao nhiêu" (#13, #5-phụ)**
- **Vì sao tách khỏi `search_units`:** `search_units` trả **danh sách căn** (đọc 50 căn qua voice là thảm họa); còn câu "dự án này còn nhiều căn không, còn loại nào, hướng nào" cần một **bản tóm tắt đếm được**, không phải list.
- **Nguồn:** aggregate `GET /projects/{slug}.units[]` (3b — có `status`).
- **Trả về (summary, không phải list):** `{ project_code, total, available, by_unit_type:[{type, total, available, price_from, price_to}], by_direction:[{direction, available}] }`.
- **Escalate khi:** dự án không resolve / không inventory (`None`).
- **Lưu ý:** đặt tên **KHÁC** `booking.check_availability` (cái kia là lịch xem, không phải tồn kho căn).

**Phong thủy — GIỮ TRONG `recommend_units`, KHÔNG tách tool riêng** (quyết định 2026-07-21).
- Cả hai kiểu hỏi đều do `recommend_units` đảm nhiệm: *"tôi mệnh Mộc hợp hướng nào"* (chỉ tư vấn) **và** *"tìm căn hợp tuổi tôi"* (tư vấn + gợi ý căn).
- Hướng tính bằng code `agent/feng_shui.py` (từ `birth_year`+`gender`/`menh`/`zodiac`) → overlay sort căn hợp hướng lên đầu.
- **Yêu cầu thiết kế:** `recommend_units` phải **trả kèm phần "đọc phong thủy"** trong kết quả (`menh`, `cung_phi`, `good_directions`, `bad_directions`) để model **narrate được lời tư vấn ngay cả khi chưa/không có căn nào khớp** — tránh việc khách chỉ hỏi bản tra mà tool trả rỗng thì không có gì để nói. Con-giáp-only vẫn giữ guard hỏi năm sinh thật (cap 2 lần) như hiện tại.

### 4.2 Cố ý KHÔNG thêm (tránh rác context)

| Ý tưởng bị loại | Lý do |
|---|---|
| `get_segment` / `get_view` / `get_utilities` / `investment_advice` (mỗi câu định tính 1 tool) | Đều là **RAG trên cùng `noble_kb`** — tách ra chỉ nhân bản `noble_search` với khác tên → rác. Giữ **1 RAG tool duy nhất**, phân biệt bằng `query`. |
| `compare_projects([codes])` | So sánh = model tự gọi `get_project_overview` 2 lần + `noble_search` rồi tổng hợp. Thêm tool riêng không mở thêm dữ liệu nào. |
| `price_range(region/type)` tách riêng | Dải giá đã nằm trong `get_project_financial` (per-type min/max) + `recommend_units` (theo ngân sách). Không cần tool thứ 3. |
| Tách `booking` thành 4 tool | Giữ 1 tool `booking` với `action` — 4 action cùng domain lịch hẹn, tách ra là xé vụn. |
| `get_project_media` riêng | `send_media` đã phủ; media là hành động gửi, không phải truy vấn. |

### 4.3 Nguyên tắc phân mảnh (dùng khi cân nhắc tool mới về sau)

1. **1 tool = 1 ý định + 1 shape trả về.** Nếu shape trả về trùng tool cũ (list unit, RAG text) → không tách.
2. **RAG luôn là 1 tool.** Mọi câu định tính đi qua `noble_search`; đừng nhân bản theo chủ đề.
3. **Không tạo tool cho dữ liệu chưa tồn tại** (chính sách/tầng/tiến độ đang rỗng) — để `escalate`/RAG gánh; thêm tool khi prod có nguồn thật.
4. **Trần ~12 tool.** Vượt thì gộp theo `action` param thay vì thêm tool.
5. **Tên tool không đụng nhau về nghĩa** (`check_inventory` ≠ `booking.check_availability`).

---

## 5. Luồng hội thoại điển hình (phễu mua) → chuỗi tool

Người mua thường đi: **nhu cầu → ngân sách → loại hình & PN → khu vực → hướng/phong thủy → tiến độ → chính sách → chốt 1–2 dự án**.

```
Khai thác nhu cầu (ở/đầu tư)            → noble_search (#8) + update_customer
Ngân sách + vùng                        → recommend_units(budget_max, region)        [server-side price/region]
   → giới thiệu 2–3 dự án/căn có điểm nhấn → get_project_overview + send_media
Phong thủy (tư vấn hướng HOẶC tìm căn)  → recommend_units (overlay feng-shui, trả kèm bản đọc) (#6)
Loại/PN/diện tích/hướng cụ thể          → search_units(project_code, filters)         (#4,#5)
Còn/hết + đếm                           → check_inventory(project_code)               (#13)
Tiến độ/sổ                              → get_project_overview.ownership / noble_search (#9)
Chính sách/ưu đãi/mua sỉ                → escalate (CVTV)                             (#10,#11)
Chốt happy case                         → booking (đặt lịch xem) HOẶC escalate (xin CVTV gọi lại) (#14)
```

---

## 6. Gaps & phụ thuộc (phải theo dõi)

1. **Tiến độ/bàn giao (#1,#9) chưa có dữ liệu** — `/progress` OK khi authed nhưng gần rỗng (1/20 dự án dev). Verify prod trước khi hứa mốc bàn giao.
2. **Chính sách/CSBH/vay/quà (#10) chưa có dữ liệu** — đã verify bằng token demo (2026-07-21): `gated` chỉ là cờ auth (có token → `false`), nhưng `csbhFull`/`loanInfo`/`bankSupport`/`gift`/`priceList` **rỗng 0/437 căn cả khi authed**. ⇒ #10 dứt khoát `escalate` cho tới khi prod điền dữ liệu → khi đó mới cân nhắc tool đọc CSBH.
3. **Tầng/vị-trí (#7) chưa có dữ liệu** — `floor`/`building` rỗng 0/437 dev; `search_units` sẵn sàng đọc khi prod có.
4. **`hot-units` = quỹ hot, không phải toàn inventory** → câu "còn bao nhiêu căn" (#13) cross-project chỉ đúng trong quỹ hot; per-project `units[]` đầy đủ hơn.
5. **RAG roster re-ingest** — khi bật `NOBLE_DATA_SOURCE=sales_api` (dự án Masteri/Vinhomes/… trong `project_code_map.json`), kho `noble_search` **phải ingest lại** theo roster mới, nếu không tri thức trả sai dự án (điều kiện tiên quyết, xem spec_provider §7).
6. **Trạng thái căn** chỉ có ở per-project (3b) và ở `/hot-units/{id}` detail — không có ở `hot-units` list. Đừng dựa vào list để nói còn/hết.

---

## Change Log

| Ngày | Thay đổi | Ghi chú |
|---|---|---|
| 2026-07-21 | Draft v1 — map 14 nhóm câu hỏi BĐS ↔ nguồn (API/RAG/code/nội bộ) ↔ tool; catalog 10 tool core + đề xuất 1 tool chuyên biệt `check_inventory` (tổng 11) + danh sách cố ý KHÔNG thêm + nguyên tắc phân mảnh; luồng phễu mua; gaps. Độ phủ dựa trên khảo sát live authed (token demo) 437 căn/20 dự án: `direction` ~76%; CSBH/loanInfo/floor/progress rỗng trên dev. | Dựa trên spec_provider §9 (đã đính chính theo response live) + khảo sát `nbx-sales-api-dev` 2026-07-21. |
| 2026-07-21 | Quyết định: phong thủy **giữ trong `recommend_units`** (không tách `feng_shui_advice`); recommend_units phải trả kèm phần "đọc phong thủy" để narrate được cả khi không có căn khớp. | Theo yêu cầu user — tránh model phải chọn giữa 2 tool phong thủy. |
| 2026-07-21 | `check_inventory` triển khai xong trên cả `sales_api` + `mongo` (capability `get_inventory_summary`) → đổi trạng thái §4/§4.1 từ "đề xuất" sang "đã thêm (11 tool)"; đồng thời `NOBLE_DATA_SOURCE` default flip `mongo`→`sales_api` (điều kiện tiên quyết RAG re-ingest đã thỏa, user xác nhận 2026-07-21). | Theo `docs/superpowers/specs/2026-07-21-tool-provider-bds-refactor-design.md` Part 2 + Part 4. |
