# M4a — Kiểm kê trường (bóc từ prototype `Tenant Portal.dc.html`)

> Tài liệu làm việc, không phải spec. Dùng để chốt ranh giới cột / jsonb / bảng con.
> Nguồn: khối `data-s~="pform"` và `data-s~="uform"` của prototype · migration `0004_tenant_data_core.py`

Ký hiệu cột **Đích**: `C` = cột thật · `J` = khoá trong jsonb · `B` = bảng con (1-N) ·
`M4b` = chuyển sang spec media · `—` = đề nghị bỏ

---

## 1. Dự án (`pform`) — 35 ô, 6 nhóm

### 1.1 Thông tin chung (12 ô)

| Ô | Mã | Đã có ở 0004? | Đích | Ghi chú |
|---|---|---|---|---|
| Tên dự án | `name` | ✅ | C | bắt buộc |
| Slug | `slug` | ✅ | C | |
| Loại hình | `type` | ✅ | C | Thấp tầng / Cao tầng — agent lọc |
| Miền | `area_region` | ✅ `region` | C | đổi tên về `region` của 0004 |
| Dự án mẹ | `parent_id` | ❌ | C | self-FK → `parent_code` (xem §3.1) |
| Vị trí | `location` | ✅ | C | |
| Chủ đầu tư | `investor` | ✅ | C | |
| Trạng thái | `status` | ✅ | C | draft / published |
| Thứ tự | `sort_order` | ❌ | C | |
| Thứ tự hot | `sort_hot` | ✅ | C | |
| Dự án nổi bật | `is_featured` | ❌ | C | |
| Đẩy quỹ hot | `is_hot` | ✅ | C | |

*(Mã dự án `code` là khoá, đã có ở 0004, không hiện thành ô riêng trên form.)*

### 1.2 Tổng quan (9 ô) — **prototype tự ghi: "ghi vào `overview` jsonb — 11 khoá"**

| Ô | Mã | Đích |
|---|---|---|
| Quy mô | `scale` | J |
| Số căn / sản phẩm | `units_text` | J |
| Mật độ xây dựng | `density` | J |
| Diện tích (tóm tắt) | `area_summary` | J |
| Loại sản phẩm | `product` | J |
| Hình thức sở hữu | `ownership` | J |
| Pháp lý | `ownership_type` | J |
| Tiêu chuẩn bàn giao | `apartment_standard` | J |
| Mô tả | `description` | J |

Cột `overview jsonb` **đã tồn tại** ở `0004`. Không ô nào trong nhóm này được lọc hay sắp xếp —
chúng là văn bản mô tả agent đọc rồi diễn giải.

### 1.3 Ảnh (6 ô) → **toàn bộ sang M4b**

`cover_image` · `banner_image` · `gallery` · `link_360` · `image_map` · `csbh_image`

Đây chính là "kho media" của DL_02. Giữ lại ở M4a thì M4b phải migrate lần hai.

### 1.4 Vị trí bản đồ (3 ô)

| Ô | Mã | Đích | Ghi chú |
|---|---|---|---|
| Vĩ độ | `lat` | C | đã có |
| Kinh độ | `lng` | C | đã có |
| Điểm nhấn vị trí | `location_highlights[]` | **B** | 1-N, prototype ghi "5 điểm" |

### 1.5 Video · Tiến độ · Tài liệu (3 ô) — prototype ghi "**ba editor dạng list**"

| Ô | Mã | Đích | Số bản ghi prototype |
|---|---|---|---|
| Video | `project_videos` | **B** hoặc M4b | 4 mục · youtube / file |
| Tiến độ | `project_progress` | **B** | 9 mốc · ảnh + link Drive |
| Tài liệu | `project_documents` | **B** | 6 tài liệu · chỉ link |

### 1.6 SEO (2 ô)

| Ô | Mã | Đích | Ghi chú |
|---|---|---|---|
| SEO title | `seo_title` | **—** | Odyssey không xuất bản web công khai |
| SEO description | `seo_description` | **—** | di sản CMS website cũ |

---

## 2. Quỹ căn (`uform`) — 49 ô, 7 nhóm

### 2.1 Thông tin căn (11 ô)

| Ô | Mã | Đã có ở 0004? | Đích | Ghi chú |
|---|---|---|---|---|
| Dự án | `project_id` | ✅ `project_code` | C | dùng `project_code` của 0004 |
| Mã căn | `code` | ✅ | C | định danh — BR10 |
| Loại hình | `unit_type_id` | ✅ `unit_type` text | C | xem §3.2 |
| Trạng thái | `status` | ✅ | C | CHECK 4 giá trị |
| Đại lý | `investor` | ❌ | C | |
| Hướng | `direction` | ✅ | C | agent lọc |
| Phân khu | `zone` | ❌ | C | |
| Toà | `building` | ❌ | C? | **xung đột QĐ #17 — xem §3.3** |
| Tầng | `floor` | ✅ | C | có cột, **không** lên view |
| Số phòng ngủ | `bedrooms` | ✅ | C | agent lọc |
| Số WC | `bathrooms` | ❌ | C | |

### 2.2 Giá & Diện tích (8 ô) — prototype ghi "**đơn vị giá: tỷ đồng**"

| Ô | Mã | Đã có? | Đích | Ghi chú |
|---|---|---|---|---|
| Giá Full VAT | `price` | ✅ `price_vnd` | C | **bigint VND** — đổi ở biên nhập, BR05 |
| Nhãn giá | `price_label` | ❌ | C | chuỗi hiển thị "5,62 tỷ" |
| Giá TTS | `price_tts` | ✅ `price_tts_vnd` | C | bigint VND |
| Giá TTTĐ | `price_tttd` | ❌ | C | bigint VND |
| Giá vay | `price_loan` | ❌ | C | bigint VND · **luôn rỗng trên nguồn hiện tại** |
| Thông tin vay | `loan_info` | ❌ | C | |
| Diện tích đất | `area` | ✅ `area_m2` | C | agent lọc |
| Diện tích xây | `area_build` | ✅ `area_build_m2` | C | |

### 2.3 Quỹ hot & chính sách (10 ô)

| Ô | Mã | Đã có? | Đích | Ghi chú |
|---|---|---|---|---|
| Căn hot | `is_hot` | ❌ | C | |
| Loại quỹ | `fund_type` | ✅ | C | |
| Thứ tự hot | `hot_sort` | ❌ | C | |
| Hoa hồng | `commission` | ✅ | C | **GATED** — BR09 |
| Hỗ trợ ngân hàng | `bank_support` | ✅ | C | **GATED** |
| CSBH đầy đủ | `csbh_full` | ✅ | C | **GATED** |
| CSBH tóm tắt | `csbh_brief` | ✅ | C | |
| Tiêu chuẩn bàn giao | `delivery_standard` | ❌ | C | |
| Quà tặng | `gift` | ✅ | C | |
| Pháp lý | `legal` | ✅ | C | |

### 2.4 Ảnh (5 ô) → **toàn bộ sang M4b**

`image` · `image_layout` · `image_roof` · `image2` · `gallery`

### 2.5 Thông tin bổ sung (8 ô)

| Ô | Mã | Đích | Ghi chú |
|---|---|---|---|
| Tầng nhỏ nhất | `floor_min` | C | |
| Tầng lớn nhất | `floor_max` | C | |
| Trục căn | `axis` | C | |
| Mặt tiền | `front` | C | |
| Link Youtube | `link_youtube` | M4b | video là media |
| Phiếu tính giá | `price_list` | M4b | PDF · là tệp |
| Thời điểm check | `check_time` | C | **timestamptz** — đầu vào BR06 |
| Mô tả căn | `description` | C | |

### 2.6 Vị trí bản đồ (4 ô)

| Ô | Mã | Đích | Ghi chú |
|---|---|---|---|
| Vĩ độ căn | `lat` | C | **cột mới** — `0004` chỉ tạo `lat` cho `projects` |
| Kinh độ căn | `lng` | C | **cột mới** |
| Vĩ độ dự án | `lat_p` | **—** | trùng `projects.lat`, suy được bằng join |
| Kinh độ dự án | `lng_p` | **—** | trùng `projects.lng` |

### 2.7 Hiển thị (3 ô)

| Ô | Mã | Đích | Ghi chú |
|---|---|---|---|
| Hiển thị public | `is_active` | C | |
| Thứ tự | `sort_order` | C | |
| Người phụ trách | `sale_id` | C | FK → `control.users` (M2a) — xem §3.4 |

---

## 3. Bốn chỗ phải quyết trước khi viết migration

### 3.1 `parent_id` → `parent_code`
`0004` khoá tự nhiên là `(tenant_id, code)`, không phải `id`. Dự án mẹ nên là
`parent_code text` + FK `(tenant_id, parent_code)`, để import CSV tham chiếu được bằng mã
thay vì bằng số nội bộ.

### 3.2 `unit_type_id` — lookup table hay `text`?
Prototype dùng id ⇒ ngụ ý bảng `unit_types`. `0004` đang là `unit_type text`.
Bảng lookup cho phép đổi tên loại một chỗ; `text` giữ import CSV đơn giản.

### 3.3 `building` (Toà) xung đột với quyết định #17
`0004` ghi thẳng trong header: *"KHÔNG tạo cột `tower`"* — vì `tower` bị hardcode `""` và bộ lọc
theo toà trả sai âm thầm. Prototype lại có ô **Toà** `building`.
Hai cái này không mâu thuẫn nếu tách đúng: **tạo cột để tenant nhập, không mở bộ lọc** (BR04:
*"bộ lọc chỉ được mở khi dữ liệu thật có trường đó"*). Nhưng phải ghi rõ, nếu không người sau
đọc `0004` sẽ tưởng M4 vi phạm.

### 3.4 `sale_id` — FK sang `control.users`
`tenant_data` trỏ sang `control` là hướng phụ thuộc mới. RLS của `units` không phủ được
`users`; cần quyết đây là FK thật hay chỉ lưu tên hiển thị.

---

## 4. Tổng kết số lượng

| | Ô form | → M4b | → jsonb | → bảng con | bỏ | Ô còn lại | + không phải ô form | **Cột thật** |
|---|---|---|---|---|---|---|---|---|
| **Dự án** | 35 | 6 | 9 | 4 | 2 | 14 | 4 — `code` `overview` `extras` `agent_enabled` | **18** |
| **Quỹ căn** | 49 | 7 | 0 | 0 | 2 | 40 | 1 — `extras` | **41** |

`0004` đã có **14 cột** ở `projects` và **19 cột** ở `units` ⇒ migration `0400` `ALTER ADD`:

- **`projects` +4**: `parent_code` · `sort_order` · `is_featured` · `agent_enabled`
- **`units` +22**: `investor` · `zone` · `building` · `bathrooms` · `price_label` ·
  `price_tttd_vnd` · `price_loan_vnd` · `loan_info` · `is_hot` · `hot_sort` ·
  `delivery_standard` · `floor_min` · `floor_max` · `axis` · `front` · `check_time` ·
  `description` · `is_active` · `sort_order` · `sale_email` · `lat` · `lng`

> ⚠️ `0004` **không tạo `lat`/`lng` cho `units`** (chỉ `projects` có). Hai cột đó là mới,
> dễ sót khi đếm vì `projects` đã có tên trùng.

Cộng 4 bảng mới: `project_highlights` · `project_progress` · `project_documents` · `import_jobs`.
