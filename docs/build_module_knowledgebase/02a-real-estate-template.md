# 03 · Template lĩnh vực **Bất động sản** (`real_estate`) — PostgreSQL, `tenant_data`

> **Instantiation cụ thể** của khung KB (`02-knowledge-base.md`) cho lĩnh vực BĐS: bảng/field, enum thật, 2 collection Qdrant, luồng CSBH/pháp lý, cleanup vs hệ cũ. Đây là **template `real_estate`** mà provisioning seed khi tenant bật vertical này (cơ chế template chung: `02` §9).
>
> Nguyên tắc chung (anchor, visibility `status`, freshness, cách ly, bộ cột chung, pattern RAG) **không lặp ở đây** — xem `02`.
>
> Chú thích Δ: `🆕` mới vs hệ cũ · `✏️` đổi vs hệ cũ · `📎` khớp Notion/hệ thật · `⚠️` cố ý khác.
> Enum: **[1]** chọn một · **[N]** chọn nhiều. Mọi bảng có bộ cột chung (`02` §6, phase manual-only): `id·tenant_id·status·created_at·updated_at`.

---

## 1. Nguyên tắc thiết kế (áp mọi bảng BĐS)

- **Core columns có kiểu chặt** (agent lọc được, code biết trước) + **`overview` = text thô** cho mô tả tự do. **Không `custom_fields`** — template đã khai đủ schema.
- **Quick-fact tách field riêng** (tổng diện tích, mật độ, quy mô, sở hữu, bàn giao…) để UI render form từng ô; **chỉ tầng RAG mới combine** lại thành đoạn văn để embed.
- **Số về đúng kiểu** `numeric`/`bigint` (giá/diện tích) — `✏️` FIX nợ cũ (hệ cũ lưu **chuỗi** nên không lọc/sort được).
- **Tham chiếu bằng `project_code`/`zone_code`/`unit_code`** (business key, khớp tool agent); `id` surrogate PK vẫn có. FK tổ hợp `(tenant_id, project_code)` chặn tham chiếu chéo tenant.
- **Visibility = `status`** (draft/published/archived) + cascade theo dự án cha; **`sale_phase`** = trạng thái kinh doanh riêng; completeness tính lúc publish (`02` §3).
- **Phase này nhập tay** (manual-only): **bỏ `source` · `external_id` · `synced_at` · `verified_at`** + `UNIQUE(tenant_id, source, external_id)`. Bộ cột chung còn `id·tenant_id·status·created_at·updated_at`. Khi thêm sync (NobleX…) mới đưa lại để upsert idempotent.

---

## 2. Cleanup — GIỮ / BỎ / THÊM (so với hệ cũ)

- **GIỮ:** định danh (`ma_du_an`→`project_code`, tên TM, tên pháp lý), 5 bên tham gia, quant facts (đổi numeric), rich-text mô tả (→ nguồn RAG), core căn (loại/tầng/hướng/PN/diện tích/giá/trạng thái).
- **BỎ:** `phan_khu_id` phẳng (→ bảng `zones`); numeric-as-string; `chiet_khau_toi_da_pct`/giá net/hoa hồng (**nội bộ — bỏ hẳn**); `room_oid` (bỏ — phase nhập tay, chưa sync); `slug`, `name_legal`, `lat/lng`, `seo`, `sort_order/is_featured/is_hot`, `inventory_type`, `view`, `custom_fields`, `total_units` (→ `product_scale`).
- **THÊM:** `zones` (phân khu); `sale_phase`; `address` (vị trí chính xác); quick-fact tách field; `num_floors` (số tầng của căn); `documents.file_url` + `source_file_url` ở payload RAG; collection Qdrant `_documents` + `_media` theo workspace.
- **GỘP:** `faqs`/`finishings`/`materials`/`legal_docs`/`sales_policies` → **1 bảng `documents`** (title+body, không category); tài liệu chung tenant = `project_code="__ALL__"`. CSBH/pháp lý (text+file) cũng vào `documents` → `media` **thuần ảnh/video**.

---

## 3. Enum (khớp `docs/schemas.py` — bộ tool agent)

| Enum | Giá trị | Chọn |
|---|---|---|
| `projects.category` | `chung_cu·biet_thu·lien_ke·shophouse·dat_nen·van_phong` | **[N]** (đại đô thị nhiều loại) |
| `zones.category` | (như projects.category) | **[1]** |
| `units.product_type` | `chung_cu·studio·duplex·penthouse·officetel·condotel·biet_thu·lien_ke·shophouse·nha_pho·dat_nen·van_phong` | **[1]** |
| `units.direction` | `dong·tay·nam·bac·dong_bac·dong_nam·tay_bac·tay_nam` | **[1]** |
| `units.sale_status` | `available·booked·sold` | **[1]** |
| `projects.sale_phase` | `sap_mo_ban·dang_ban·ban_giao·dong_gio_hang` | **[1]** |
| `media.content_type` | `image·video` | **[1]** (media chỉ ảnh/video; tour_360 → cột `link_360`; CSBH/pháp lý → `documents`) |
| `media.category` | `tong_quan·ngoai_that·noi_that·tien_ich·mat_bang·vi_tri·tien_do` | **[1]** |
| `status` (mọi bảng) | `draft·published·archived` | **[1]** |

> Template khai enum mặc định; tenant mở rộng thêm giá trị được (§7).

---

## 4. Bảng

### 4.1 `projects` — *Thông tin 1 dự án BĐS; neo toàn KB. Mỗi quick-fact 1 field để UI điền.*
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `id` / `tenant_id` | PK / FK | khóa chính + RLS | `4501` / `12` |
| `project_code` | text | mã dự án, `UNIQUE(tenant_id, project_code)`; dùng ở mọi tool agent | `"NPLB"` |
| `name` | text | tên thương mại | `"Noble Palace Long Biên"` |
| `category` | text[] **[N]** | loại hình: chung_cu·biet_thu·lien_ke·shophouse·dat_nen·van_phong | `["biet_thu","lien_ke"]` |
| `region` | text | khu vực (agent lọc) | `"Long Biên, Hà Nội"` |
| `address` | text | vị trí chính xác | `"Số 1 đường X, P.Y"` |
| `investor` | text | chủ đầu tư (agent lọc) | `"Tập đoàn Noble"` |
| `developer` | text | đơn vị phát triển | `"Noble Developer"` |
| `total_land_area_m2` | numeric | tổng diện tích đất | `120000` |
| `floor_area_m2` | numeric | tổng diện tích sàn | `450000` |
| `build_density_pct` | numeric | mật độ xây dựng % | `21` |
| `product_scale` | text | quy mô sản phẩm | `"2.400 sản phẩm thấp tầng"` |
| `amenities` | text | mô tả tiện ích (raw text); ảnh tiện ích = `media` category=`tien_ich` | `"Bể bơi, công viên, TTTM…"` |
| `ownership_form` | text | hình thức sở hữu | `"Lâu dài / Sổ hồng"` |
| `handover_standard` | text | tiêu chuẩn bàn giao | `"Thô, giãn xây"` |
| `total_investment_vnd` | bigint | tổng mức đầu tư | `35000000000000` |
| `sale_phase` | text enum **[1]** | trạng thái KD: sap_mo_ban·dang_ban·ban_giao·dong_gio_hang | `"dang_ban"` |
| `overview` | text | mô tả tổng quan raw text (tự do) → nguồn RAG | `"Đại đô thị ven sông…"` |
| `cover_media_id` | FK → media | ảnh cover | `9001` |
| `map_media_id` | FK → media | ảnh mặt bằng tổng | `9002` |
| `link_360` | text | link tham quan 360 | `"kuula.co/share/…"` |
| *(bộ cột chung)* | — | `status·created_at·updated_at` | — |

### 4.2 `zones` — *Phân khu trong dự án (River Villas…). Dự án không phân khu → 1 zone mặc định.*
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `id` / `tenant_id` | PK / FK | — | — |
| `project_code` | FK `(tenant_id, project_code)` | thuộc dự án | `"NPLB"` |
| `zone_code` | text | mã phân khu, `UNIQUE(tenant_id, project_code, zone_code)` | `"RIVER"` |
| `name` | text | tên phân khu | `"Phân khu River Villas"` |
| `category` | text enum **[1]** | loại hình phân khu (override project) | `"biet_thu"` |
| `product_scale` | text | quy mô phân khu | `"120 căn đơn lập"` |
| `overview` | text | mô tả phân khu raw text → RAG | `"Phân khu ven sông…"` |
| `cover_media_id` | FK → media | ảnh cover phân khu | `9010` |
| `map_media_id` | FK → media | mặt bằng phân khu | `9011` |
| *(bộ cột chung)* | — | — | — |

### 4.3 `units` — *Từng căn/sản phẩm bán. Cao tầng: `block`+`floor`; thấp tầng để trống, dùng `unit_code`+`area_land_m2`.*
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `id` / `tenant_id` | PK / FK | — | — |
| `project_code` | FK | thuộc dự án | `"NPLB"` |
| `zone_code` | FK | thuộc phân khu | `"RIVER"` |
| `unit_code` | text | mã căn hiển thị (roomCode); index, **không** unique | `"S3.06.08"` |
| `product_type` | text enum **[1]** | chung_cu·studio·duplex·penthouse·officetel·condotel·biet_thu·lien_ke·shophouse·nha_pho·dat_nen·van_phong | `"chung_cu"` |
| `bedrooms` | smallint? | số phòng ngủ (đất nền/shophouse null) | `3` |
| `block` | text? | tòa/block (cao tầng); thấp tầng null | `"S3"` |
| `floor` | smallint? | căn ở **tầng số mấy** (cao tầng); thấp tầng null | `6` |
| `num_floors` | smallint? | **số tầng của căn** (biệt thự/duplex nhiều tầng) | `3` |
| `direction` | text enum? **[1]** | dong·tay·nam·bac·dong_bac·dong_nam·tay_bac·tay_nam | `"dong_nam"` |
| `area_built_m2` | numeric | DT thông thuỷ / xây dựng | `78.4` |
| `area_wall_m2` | numeric? | DT tim tường | `85.2` |
| `area_land_m2` | numeric? | DT đất (thấp tầng) | `96.0` |
| `price_vnd` | numeric | giá (numeric thật) | `5620000000` |
| `price_per_m2_vnd` | numeric | đơn giá/m² | `71000000` |
| `sale_status` | text enum **[1]** | available·booked·sold | `"available"` |
| `image_url` | text? | ảnh căn (từ NobleX) | `"https://…"` |
| *(bộ cột chung)* | — | `status·created_at·updated_at` (phase nhập tay) | — |

### 4.4 `documents` — *MỌI tri thức văn bản (thay `faqs`/`finishings`/`materials`/`legal_docs`/`sales_policies`): FAQ · hoàn thiện · vật liệu · pháp lý · CSBH · hướng dẫn · giới thiệu… → chunk + embed `<slug>_documents`.*
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `id` / `tenant_id` | — | PK + RLS | — |
| `project_code` | FK | thuộc dự án; **`"__ALL__"`** = tài liệu chung tenant (§4b) | `"NPLB"` / `"__ALL__"` |
| `title` | text | tiêu đề (dùng làm breadcrumb `section`) | `"Chính sách bán hàng Q3 2026"` |
| `body` | text | nội dung raw text (markdown; trích từ file nếu có) → embed | `"## Tiến độ thanh toán\n| Đợt |…"` |
| `file_url` | text? | link file gốc (PDF) trên MinIO nếu có → trả cho khách khi xin file | `"acme/docs/csbh-q3.pdf"` |
| *(bộ cột chung)* | — | `status·created_at·updated_at` | — |

> `⚠️` **Không có `category`** — `_documents` không lọc theo category (chỉ theo `project_id`); breadcrumb dùng `title`. Chunk 1 strategy chung (`structured_md`, markdown-aware, giữ bảng).
> `⚠️` **Bỏ `sales_policies` structured** (pricing/payment_plans jsonb) + tool `get_project_financial` → CSBH là 1 `documents` (text), agent trả lời bằng `kb_search`. Field nội bộ nhạy cảm (chiết khấu/giá net/hoa hồng) **không lưu**.

### 4b. Tài liệu cấp tenant — sentinel `project_code = "__ALL__"`
**Chỉ `documents` + `media`** có bản cấp-tenant (giới thiệu công ty, quy trình mua, brochure…); đặt **`project_code = "__ALL__"`**. `projects`/`zones`/`units` **không** dùng (chúng là chính cây dự án).
- `__ALL__` là **1 row `projects` hệ thống** seed sẵn mỗi tenant khi provisioning: `project_code="__ALL__"`, `name="Chung / toàn tenant"`, `status=published` → **FK `(tenant_id, project_code)` vẫn hợp lệ**, cascade an toàn (luôn published). Không có zones/units con.
- Truy hồi luôn gộp: `project_id IN {dự_án_active, "__ALL__"}`. Không cần cột `scope`/nullable.

### 4.5 `media` — *Nguồn sự thật CMS cho ảnh + video. Đều → sync `<slug>_media`. Field khớp `media_v3`. ≤6 ảnh / (project|zone|unit).*
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `id`/`tenant_id`/`project_code` | — | RLS + dự án | — |
| `zone_code` / `unit_code` | FK? | gắn phân khu / căn (nullable) | `"RIVER"` / `"S3.06.08"` |
| `content_type` | text enum **[1]** | image·video | `"image"` |
| `category` | text enum **[1]** | tong_quan·ngoai_that·noi_that·tien_ich·mat_bang·vi_tri·tien_do | `"mat_bang"` |
| `caption` | text | mô tả (VLM tự sinh / nhập tay) → nguồn embed vector | `"Mặt bằng tầng điển hình…"` |
| `media_url` | text | URL file (MinIO/YouTube/kuula/Drive) | `"https://…/mb.webp"` |
| `thumb_url` | text? | URL thumbnail (MinIO WebP; document có thể rỗng) | `"https://…/thumb.webp"` |
| `content_hash` | text | sha1 để sync incremental | `"a1b2…"` |
| `uploaded_by` | text? | người tải lên | `"an.nguyen"` |
| *(bộ cột chung)* | — | — | — |

`✏️` **Bỏ** so với hệ cũ (+ khớp media_v3): `mime`, `size_bytes`, `checksum`, `related_unit_codes`, `width/height/duration`, `thumbnail_key/medium_key`, `title` (→ `caption`), `storage_key` (→ `media_url`). Ràng buộc ≤6 ảnh/entity cưỡng chế ở **app**.

---

## 5. Qdrant setup (theo workspace lá)

**2 collection / workspace** (org cha không có; xoá workspace = drop cả 2). Key `project_id` **giữ tên** (giá trị = `project_code`). Cơ chế embed/sync do **RAG service** (`02b`) đảm nhiệm; đây chỉ mô tả collection.

### 5.1 Collection `<slug>_documents` — tri thức văn bản
`📎` **HYBRID 2 named vectors**: `dense`(e5-large 1024, cosine) + `sparse`(BM25), hợp nhất **RRF**. Index payload: `project_id`. Payload:

| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `project_id` | keyword (index) | mã dự án — giữ tên key cho agent (giá trị = `project_code`) | `"NPLB"` |
| `project_name` | text | tên thương mại | `"Noble Palace Long Biên"` |
| `section` | text | breadcrumb tiêu đề (dòng đầu chunk) | `"Noble Palace > Pháp lý > Sổ hồng"` |
| `chunk_index` | int | thứ tự chunk trong 1 nguồn | `2` |
| `text` | text | nội dung chunk (đã prepend breadcrumb) | `"Dự án có sổ hồng lâu dài…"` |
| `content_hash` | keyword | sha1 chunk → incremental/drift | `"a1b2c3…"` |
| `source_file_url` | keyword? | `🆕` link file gốc (documents.file_url) nếu chunk trích từ tài liệu → trả đúng file | `"acme/docs/csbh-q3.pdf"` / `null` |

**Nguồn embed:** `projects`(quick-facts+overview+amenities) · `zones`(overview) · `documents`(title+body — gồm FAQ/hoàn thiện/vật liệu/pháp lý/CSBH/hướng dẫn).

### 5.2 Collection `<slug>_media` — ảnh + video cho `send_media`
`📎` **HYBRID 2 named vectors**: `text`(e5-large 1024, cosine) + `visual`(SigLIP2 `google/siglip2-base-patch16-256`, 768, cosine), hợp nhất **RRF**. `content_type` ∈ image/video. Index payload: `project_id, category, content_type`. Payload = khớp `media_v3`:

| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `project_id` | keyword (index) | mã dự án (giá trị = `project_code`) | `"NPLB"` |
| `content_type` | keyword (index) | image·video | `"image"` |
| `category` | keyword (index) | tong_quan·…·mat_bang·… | `"mat_bang"` |
| `caption` | text | mô tả → nguồn embed vector `text` | `"Mặt bằng tầng điển hình…"` |
| `media_url` | text | URL file | `"https://…/mb.webp"` |
| `thumb_url` | text | URL thumbnail WebP | `"https://…/thumb.webp"` |
| `content_hash` | keyword | sha1 → sync | `"d4e5…"` |

**Cơ chế giữ (hệ cũ):** chunk markdown-aware 800/150 + breadcrumb (`section`), point-id `uuid5`, `content_hash` incremental/drift. Media point-id = `uuid5(media:{project_id}:{sha1(media_url)})`. Chỉ sync bản `published` (unpublish = xoá point).

---

## 6. CSBH & pháp lý — thuộc hoàn toàn `documents`

CSBH/pháp lý **không** vào `media`. Mỗi cái = **1 `documents`**: text ở `body`, file gốc ở `file_url`. Không còn bảng riêng, không còn structured financial.

| Mặt | Ở đâu | Tool agent |
|---|---|---|
| **Nội dung text** (chunk đầy đủ) | `<slug>_documents` (từ `documents.body`), chunk mang `source_file_url` | `kb_search` |
| **File PDF** | `documents.file_url` (link MinIO) — **KHÔNG** vào `media`/`_media` | `get_document` |

**Luồng query:**
1. *"CSBH/pháp lý dự án X thế nào?" / "Giá bao nhiêu, trả góp sao?"* → `kb_search` → `_documents` → trả lời; nếu cần gửi file → dùng `source_file_url`.
2. *"Cho em xin file CSBH / sổ hồng"* → tool `get_document(project_code, ...)` query bảng `documents` → trả `file_url`.

> `⚠️` Không còn `get_project_financial` (số tài chính trả qua `kb_search` từ nội dung CSBH). `media` giờ **thuần ảnh/video**.

---

## 7. Template `real_estate` — giá trị cụ thể

Cơ chế template chung (provisioning seed schema/enum/RAG/MinIO khi bật vertical) ở **`02` §9**. Ở đây chỉ liệt kê **giá trị cụ thể** của lĩnh vực BĐS:

| Mục | Giá trị (real_estate) |
|---|---|
| **Bảng** | projects · zones · units · **documents** (gộp faq/hoàn thiện/vật liệu/pháp lý/CSBH) · media (§4) |
| **Enum** | §3 (category [N] ở project, [1] ở zone/unit; direction; sale_status; sale_phase; media content_type/category) |
| **Quick-fact field** (UI form) | projects: total_land_area_m2·floor_area_m2·build_density_pct·product_scale·ownership_form·handover_standard·total_investment_vnd |
| **Danh mục media** | 9 category (§3) |
| **RAG config** | `rag_config["real_estate"]` — xem §7.1 (schema ở `02b` §3) |
| **Field CORE agent lọc** | product_type · price · area · direction · unit_code · sale_status · bedrooms · region · investor · category |
| **Luật completeness** | project cần `name`+`region`+`overview`; unit cần `price_vnd`+`area_built_m2`+`sale_status` |
| **Tool riêng** | `get_document(project_code, category)` — lấy file PDF (§6) |

### 7.1 `rag_config["real_estate"]` (data cho RAG engine `02b`)
```python
RAG_CONFIG["real_estate"] = {
  "anchor": {"table": "projects", "code_field": "project_code", "name_field": "name"},

  # nguồn text → <slug>_documents (table, doc_type, fields, chiến lược chunk)
  "embed_sources": [
    {"table":"projects",  "doc_type":"thong_tin", "chunk":"facts",
     "fields":["region","investor","total_land_area_m2","floor_area_m2","build_density_pct",
               "product_scale","ownership_form","handover_standard","total_investment_vnd"]},
    {"table":"projects",  "doc_type":"tong_quan", "chunk":"markdown",      "fields":["overview","amenities"]},
    {"table":"zones",     "doc_type":"phan_khu",  "chunk":"markdown",      "fields":["overview"]},
    {"table":"documents", "doc_type":"tai_lieu",  "chunk":"structured_md", "fields":["title","body"]},
  ],

  # media: chỉ ảnh/video để GỬI (→ _media). CSBH/pháp lý KHÔNG ở media (→ documents, §6)
  "media": {"visual": ["tong_quan","ngoai_that","noi_that","tien_ich","mat_bang","vi_tri","tien_do"]},

  # documents có file_url (PDF) → trích text vào body trước khi embed
  "document_extract": {"pdf_text": "pdf2text", "pdf_scan": "ocr_markdown"},

  # category ảnh → profile của VisionExtractor (PROFILES ở 02b §3.D)
  "caption_profiles": {"default":"caption_full",
                       "vi_tri":"caption_subject","tien_do":"caption_subject","mat_bang":"caption_subject"},

  "chunk_defaults": {"max_chars": 800, "overlap": 150},
}
```
Profile dùng: `caption_full` (chủ thể+điểm nhấn) · `caption_subject` (chỉ chủ thể) · `ocr_markdown` (đọc PDF scan → markdown `##`+bảng, max_tokens 4096, resize 1600).

---

## 8. Δ tổng hợp

**So với hệ cũ (`project_*` Mongo):**
- `✏️` Mongo `project_*` → bảng Postgres RLS; tham chiếu `*_code`; số về `numeric`.
- `🆕` `zones` (phân khu) thay `phan_khu_id` phẳng; `sale_phase`; `address`; quick-fact tách field; `num_floors`.
- `✏️` **Gộp `faqs`/`finishings`/`materials`/`legal_docs`/`sales_policies` → 1 bảng `documents`** (title+body, **không category**); CSBH nội bộ bỏ hẳn.
- `✏️` **Bỏ tool `get_project_financial`** (structured jsonb) → CSBH trả lời qua `kb_search`.
- `🆕` Tài liệu/media chung tenant = **`project_code="__ALL__"`** (sentinel), truy hồi gộp `IN {active, "__ALL__"}`.
- `✏️` `media` **thuần ảnh/video** (content_type `image·video`); tour_360 → `link_360`; CSBH/pháp lý → `documents`. Field gọn theo `media_v3` (caption/media_url/thumb_url), bỏ mime/size/checksum/related_unit_codes…
- `✏️` bỏ `custom_fields` (template khai đủ).

**So với Notion / hệ thật:**
- `⚠️` bỏ gate đọc (không lưu trường nhạy cảm) thay `VIEW agent_*`.
- `📎` `_documents` **hybrid** (dense e5 + sparse BM25, RRF); `_media` **hybrid text+visual RRF**.
- `📎` enum khớp `docs/schemas.py`; field `units` khớp mapping NobleX open-list API.

---

## 9. Quyết định còn mở

1. Ngưỡng freshness cụ thể (bao lâu coi là "cũ").
2. Pipeline trích text PDF (CSBH/pháp lý) → `content` (extract cụ thể) — chốt khi code.
3. Có cần `get_document` là tool riêng hay mở rộng `send_media` — chốt khi làm agent.
4. `caption` media do VLM tự sinh (Qwen-VL/Gemini như noble-cms) hay người nhập — mặc định: tự sinh + cho sửa.
