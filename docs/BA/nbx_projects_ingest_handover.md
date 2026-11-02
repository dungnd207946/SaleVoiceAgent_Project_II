# Collection Mongo mới: `nbx_*` (mirror NBX Sales API)

> Tab **Dự án** (read-only) + **RAG** đều đọc từ bộ collection này — nguồn sự thật duy nhất.
> Ghi CHỈ qua job ingest (`ingest_projects_api.py` / nút "Đồng bộ dữ liệu dự án (API)").
> `_id` = UUID của API → upsert idempotent, xoá bản không còn (full-sync). DB: `noble_agent`.
> `project_*` cũ giữ nguyên để rollback, không còn dùng. Ngày: 2026-07-23.

## Tổng quan

| Collection              | n (dev) | Nguồn API                                 | Vai trò                                            |
| ----------------------- | ------- | ------------------------------------------ | --------------------------------------------------- |
| `nbx_projects`        | 41      | `/cms/projects` + `/cms/projects/{id}` | dự án (detail đầy đủ, nhúng media/units con) |
| `nbx_units`           | 614     | `/cms/units`                             | căn hộ (API trả 640, dedupe theo`id` còn 614) |
| `nbx_apartment_types` | 10      | `/apartment-types`                       | danh mục loại hình                               |
| `nbx_articles`        | 27      | `/cms/articles`                          | tin tức                                            |

Index: `nbx_projects.slug`, `nbx_projects.projectCode`, `nbx_units.projectId`, `nbx_articles.projectId`.

---

## `nbx_projects` (`_id` = project UUID)

Giữ nguyên field API + thêm `projectCode` (map từ `project_code_map.json`).

| Field                                           | Kiểu     | Ghi chú                                                                       |
| ----------------------------------------------- | --------- | ------------------------------------------------------------------------------ |
| `_id` / `id`                                | str       | UUID (bằng nhau)                                                              |
| `name`                                        | str       | tên dự án                                                                   |
| `slug`                                        | str       | định danh URL (khác mã dự án)                                            |
| `projectCode`                                 | str       | mã dự án (thêm lúc ingest); rỗng nếu chưa có trong map → RAG bỏ qua |
| `type`                                        | str       | `cao_tang` / `thap_tang` / `hon_hop`                                     |
| `areaRegion`                                  | str       | `mien_bac` / `mien_trung` / `mien_nam`                                   |
| `status`                                      | str       | `published` / `draft`                                                      |
| `investor`                                    | str       | chủ đầu tư                                                                 |
| `location`                                    | str       | vị trí                                                                       |
| `description`                                 | str       | tổng quan (HTML)                                                              |
| `coverImage` / `bannerImage`                | str       | path ảnh`/img/real/...`                                                     |
| `gallery`                                     | list[str] | path ảnh                                                                      |
| `locationHighlights`                          | list[str] | điểm nhấn vị trí                                                          |
| `overview`                                    | obj       | xem bảng dưới                                                               |
| `videos`                                      | list[obj] | `{title, videoUrl, thumbnail, category}`                                     |
| `progress`                                    | list[obj] | `{title, description, externalUrl, type}`                                    |
| `documents`                                   | list[obj] | `{title, url}`                                                               |
| `units`                                       | list[obj] | danh sách 1 phần — KHÔNG đủ, dùng`nbx_units`                          |
| `lat` / `lng`                               | float     | toạ độ                                                                      |
| `parentId`                                    | str\|null | dự án cha                                                                    |
| `isFeatured` / `isHot`                      | bool      | cờ                                                                            |
| `sortOrder` / `sortHot`                     | int       | thứ tự                                                                       |
| `seoTitle` / `seoDescription`               | str\|null | SEO                                                                            |
| `publishedAt` / `createdAt` / `updatedAt` | str       | ISO datetime                                                                   |

**`overview{}`:**

| Field            | Kiểu | Ghi chú                        |
| ---------------- | ----- | ------------------------------- |
| `scale`        | str   | quy mô (vd "458 ha")           |
| `density`      | str   | mật độ XD (vd "30%")         |
| `ownership`    | str   | hình thức sở hữu            |
| `product`      | str   | loại sản phẩm                |
| `units_text`   | str   | tổng sản phẩm (text)         |
| `area_summary` | str   | =`location` (thường trùng) |
| `csbh_image`   | str   | ảnh chính sách bán hàng    |
| `link_360`     | str   | URL tour 360                    |

> Ảnh là path tương đối `/img/real/...` → prepend media base (CloudFront) khi hiển thị.

## `nbx_units` (`_id` = unit UUID)

Shape theo endpoint list `/cms/units` (KHÔNG phải detail).

| Field            | Kiểu     | Ghi chú                       |
| ---------------- | --------- | ------------------------------ |
| `_id` / `id` | str       | UUID                           |
| `code`         | str       | mã căn                       |
| `projectId`    | str       | FK → dự án                  |
| `projectName`  | str       | tên dự án                   |
| `price`        | float     | giá — đơn vị**tỷ** |
| `priceTts`     | float     | giá TTS                       |
| `area`         | float     | diện tích thông thuỷ (m²) |
| `areaBuild`    | float     | diện tích xây dựng (m²)   |
| `direction`    | str\|null | hướng                        |
| `status`       | str       | `available`…                |
| `fundType`     | str       | `hot`…                      |
| `unitType`     | obj\|null | `{name, group}`              |
| `image`        | str\|null | ảnh căn                      |
| `investor`     | str       | chủ đầu tư                 |

> Không có `csbhBrief/csbhFull/gift/legal/imageLayout` (chỉ ở detail `/cms/units/{id}`, KHÔNG ingest).

## `nbx_apartment_types` (`_id` = type UUID)

| Field            | Kiểu | Ghi chú                                                 |
| ---------------- | ----- | -------------------------------------------------------- |
| `_id` / `id` | str   | UUID                                                     |
| `name`         | str   | vd Studio / 1PN / Liền kề                              |
| `group`        | str   | `can_ho` / `thap_tang` — lọc theo `project.type` |
| `sortOrder`    | int   | thứ tự                                                 |

## `nbx_articles` (`_id` = article UUID)

| Field                           | Kiểu     | Ghi chú     |
| ------------------------------- | --------- | ------------ |
| `_id` / `id`                | str       | UUID         |
| `slug`                        | str       | định danh  |
| `title`                       | str       | tiêu đề   |
| `coverImage`                  | str       | path ảnh    |
| `categoryName`                | str\|null | danh mục    |
| `status`                      | str       | trạng thái |
| `isFeatured`                  | bool      | cờ          |
| `sortOrder`                   | int       | thứ tự     |
| `publishedAt` / `updatedAt` | str       | ISO datetime |

> ⚠ List `/cms/articles` KHÔNG có `bodyHtml`/`projectId`. Nội dung đầy đủ + gắn dự án lấy qua
> `/projects/{slug}/news` → `/articles/{slug}` (RAG dùng đường này).
