# NBX Sales API — Đặc tả API

- **Nguồn**: `https://nbx-sales-api-dev.noble.vn` (Swagger UI: `/docs`, OpenAPI JSON: `/docs/json`)
- **Title / Version**: NBX Sales API — `1.0.0` (OpenAPI 3.0.3)
- **Xác thực**: JWT Bearer — gửi header `Authorization: Bearer <token>` (security scheme `bearerAuth`). Token lấy từ `POST /api/v1/auth/login`.
- **Tổng số**: 68 đường dẫn / 83 operation.

> Ghi chú: spec gốc **không có** summary/description/tags cho từng endpoint. Cột "Chức năng" và cột "Auth" dưới đây được **suy ra theo quy ước REST + tiền tố đường dẫn**:
> - Nhóm `/api/v1/cms/*` = API dành cho **CMS / nhân viên (staff)** → yêu cầu đăng nhập + quyền quản trị.
> - Nhóm `/my-*`, `/favorites`, `/orders`, `/lock-requests` = API **người dùng đã đăng nhập**.
> - Các endpoint đọc nội dung công khai (projects, articles, events, pages…) coi như **public**.
> - `*` sau tên tham số/field = **bắt buộc (required)**.

---

## 1. Xác thực & Tài khoản (Auth / Me)

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| POST | `/api/v1/auth/login` | Đăng nhập bằng SĐT + mật khẩu, trả JWT | Public | Body: `phone*`, `password*` |
| GET | `/api/v1/auth/me` | Lấy thông tin tài khoản đang đăng nhập | User | — |
| POST | `/api/v1/auth/change-password` | Đổi mật khẩu | User | Body: `oldPassword*`, `newPassword*` |
| PATCH | `/api/v1/me` | Cập nhật hồ sơ cá nhân | User | Body: `fullName`, `email`, `birthday`, `referrerPhone`, `avatarUrl` |

## 2. Người dùng CMS

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| GET | `/api/v1/cms/users-lite` | Danh sách người dùng rút gọn (để gán/lọc trong CMS) | CMS | — |

## 3. Trang tĩnh (Pages)

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| GET | `/api/v1/pages/{slug}` | Lấy nội dung trang tĩnh theo slug (public) | Public | Path `slug*`; Query `locale` |
| GET | `/api/v1/cms/pages/{slug}` | Lấy trang tĩnh (bản CMS, kể cả nháp) | CMS | Path `slug*`; Query `locale` |
| PUT | `/api/v1/cms/pages/{slug}` | Cập nhật nội dung trang tĩnh | CMS | Path `slug*`; Query `locale`; Body: `content*`, `status`, `seoTitle`, `seoDescription` |

## 4. Dự án (Projects) — công khai

| Method | Endpoint | Chức năng | Auth | Tham số |
|---|---|---|---|---|
| GET | `/api/v1/projects` | Danh sách dự án (lọc + phân trang) | Public | Query `keyword`, `area_region`, `type`, `page` |
| GET | `/api/v1/projects/{slug}` | Chi tiết một dự án theo slug | Public | Path `slug*` |
| GET | `/api/v1/projects/{slug}/news` | Tin tức của dự án | Public | Path `slug*` |
| GET | `/api/v1/projects/{slug}/videos` | Video của dự án | Public | Path `slug*` |
| GET | `/api/v1/projects/{slug}/progress` | Tiến độ xây dựng của dự án | Public | Path `slug*` |
| GET | `/api/v1/projects/{slug}/documents` | Tài liệu của dự án | Public | Path `slug*` |

## 5. Dự án (Projects) — CMS

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| GET | `/api/v1/cms/projects` | Danh sách dự án cho CMS (lọc theo trạng thái, dự án cha) | CMS | Query `keyword`, `area_region`, `type`, `status`, `parent_id`, `page` |
| POST | `/api/v1/cms/projects` | Tạo dự án mới | CMS | Body: `name*`, `slug*`, `type*`, `areaRegion*`, `location`, `investor`, `lat`, `lng`, `coverImage`, `bannerImage`, `gallery[]`, `overview`, `description`, `locationHighlights[]`, `status`, `isFeatured`, `sortOrder`, `parentId`, `isHot`, `sortHot`, `seoTitle`, `seoDescription`, `units[]` |
| GET | `/api/v1/cms/projects/{id}` | Chi tiết dự án theo id (CMS) | CMS | Path `id*` |
| PUT | `/api/v1/cms/projects/{id}` | Cập nhật dự án | CMS | Path `id*`; Body: các field như POST (không gồm `units`) |
| DELETE | `/api/v1/cms/projects/{id}` | Xóa dự án | CMS | Path `id*` |
| PUT | `/api/v1/cms/projects/{id}/units` | Thay/cập nhật danh sách căn hộ của dự án | CMS | Path `id*`; Body: `units*[]` |
| PUT | `/api/v1/cms/projects/{id}/videos` | Cập nhật danh sách video của dự án | CMS | Path `id*`; Body: `videos*[]` |
| PUT | `/api/v1/cms/projects/{id}/progress` | Cập nhật tiến độ xây dựng | CMS | Path `id*`; Body: `progress*[]` |
| PUT | `/api/v1/cms/projects/{id}/documents` | Cập nhật tài liệu dự án | CMS | Path `id*`; Body: `documents*[]` |

## 6. Căn hộ / Sản phẩm (Units) — công khai

| Method | Endpoint | Chức năng | Auth | Tham số |
|---|---|---|---|---|
| GET | `/api/v1/hot-units` | Danh sách căn hot (bộ lọc bán hàng) | Public | Query `group`, `project_id`, `unit_type_id`, `direction`, `code`, `area_min`, `area_max`, `fund_type` |
| GET | `/api/v1/hot-units/{id}` | Chi tiết một căn hot | Public | Path `id*` |
| GET | `/api/v1/apartment-types` | Danh sách loại căn hộ | Public | — |

## 7. Căn hộ / Units — CMS

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| GET | `/api/v1/cms/hot-units` | Danh sách căn hot cho CMS | CMS | Query `keyword`, `fund_type`, `project_id` |
| PATCH | `/api/v1/cms/units/{id}/hot` | Bật/tắt cờ hot + xếp hạng cho một căn | CMS | Path `id*`; Body: `isHot`, `fundType`, `hotSort` |
| GET | `/api/v1/cms/units` | Danh sách căn hộ (lọc + phân trang) | CMS | Query `page`, `pageSize`, `code`, `project_id`, `agency`, `status`, `fund_type`, `direction` |
| POST | `/api/v1/cms/units` | Tạo căn hộ mới | CMS | Body: `projectId*`, `code*`, + `price*`, `priceTts`, `priceTttd`, `priceLoan`, `priceLabel`, `loanInfo`, `direction`, `zone`, `area`, `areaBuild`, `status`, `isHot`, `fundType`, `hotSort`, `unitTypeId`, `unitType`, `floor`, `building`, `investor`, `commission`, `bankSupport`, `csbhBrief`, `csbhFull`, `deliveryStandard`, `gift`, `legal`, `image`, `imageLayout`, `gallery[]`, `lat`, `lng`, `saleId`, `imageRoof`, `floorMin`, `floorMax`, `image2`, `priceList`, `linkYoutube`, `axis`, `front`, `checkTime`, `latP`, `lngP`, `isActive`, `description` |
| GET | `/api/v1/cms/units/{id}` | Chi tiết căn hộ (CMS) | CMS | Path `id*` |
| PUT | `/api/v1/cms/units/{id}` | Cập nhật căn hộ | CMS | Path `id*`; Body: như POST (trừ `projectId`) |
| DELETE | `/api/v1/cms/units/{id}` | Xóa một căn hộ | CMS | Path `id*` |
| POST | `/api/v1/cms/units/bulk-delete` | Xóa hàng loạt căn hộ | CMS | Body: `ids*[]` |

## 8. Yêu thích & Tương tác

| Method | Endpoint | Chức năng | Auth | Tham số |
|---|---|---|---|---|
| GET | `/api/v1/favorites` | Danh sách căn đã yêu thích | User | — |
| POST | `/api/v1/favorites/{unitId}` | Thêm căn vào yêu thích | User | Path `unitId*` |
| DELETE | `/api/v1/favorites/{unitId}` | Bỏ yêu thích một căn | User | Path `unitId*` |
| GET | `/api/v1/my-interactions` | Lịch sử tương tác của tôi (theo khoảng thời gian) | User | Query `from`, `to` |

## 9. Sự kiện (Events)

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| GET | `/api/v1/events` | Danh sách sự kiện (public) | Public | — |
| POST | `/api/v1/events/{slug}/register` | Đăng ký tham gia sự kiện | Public | Path `slug*`; Body: `name*`, `email`, `phone` |
| GET | `/api/v1/cms/events` | Danh sách sự kiện cho CMS | CMS | Query `status`, `q` |
| GET | `/api/v1/cms/events/{id}/participants` | Danh sách người đăng ký của sự kiện | CMS | Path `id*` |
| PATCH | `/api/v1/cms/events/participants/{id}/checkin` | Check-in / bỏ check-in người tham gia | CMS | Path `id*`; Body: `checkedIn*` |

## 10. Bài viết & Phân loại (Articles)

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| GET | `/api/v1/articles` | Danh sách bài viết (public, lọc + phân trang) | Public | Query `keyword`, `category`, `tag`, `type`, `page` |
| GET | `/api/v1/articles/{slug}` | Chi tiết bài viết theo slug | Public | Path `slug*` |
| GET | `/api/v1/article-categories` | Danh mục bài viết (public) | Public | — |
| GET | `/api/v1/article-tags` | Tag bài viết (public) | Public | — |
| GET | `/api/v1/cms/articles` | Danh sách bài viết (CMS) | CMS | Query `keyword`, `category`, `status`, `page` |
| POST | `/api/v1/cms/articles` | Tạo bài viết | CMS | Body: `title*`, `slug*`, `categoryId`, `projectId`, `coverImage`, `excerpt`, `bodyHtml`, `status`, `isFeatured`, `sortOrder`, `seoTitle`, `metaDescription`, `metaKeywords`, `ogImage`, `sourceUrl`, `publishedAt`, `tagIds[]`, `typeCode`, `startTime`, `endTime` |
| GET | `/api/v1/cms/articles/{id}` | Chi tiết bài viết (CMS) | CMS | Path `id*` |
| PUT | `/api/v1/cms/articles/{id}` | Cập nhật bài viết | CMS | Path `id*`; Body như POST |
| DELETE | `/api/v1/cms/articles/{id}` | Xóa bài viết | CMS | Path `id*` |
| GET | `/api/v1/cms/article-categories` | Danh sách danh mục (CMS) | CMS | — |
| POST | `/api/v1/cms/article-categories` | Tạo danh mục | CMS | Body: `name*`, `slug*`, `typeCode`, `sortOrder`, `status` |
| PUT | `/api/v1/cms/article-categories/{id}` | Cập nhật danh mục | CMS | Path `id*`; Body: `name`, `slug`, `typeCode`, `sortOrder`, `status` |
| DELETE | `/api/v1/cms/article-categories/{id}` | Xóa danh mục | CMS | Path `id*` |
| GET | `/api/v1/cms/article-tags` | Danh sách tag (CMS) | CMS | — |
| POST | `/api/v1/cms/article-tags` | Tạo tag | CMS | Body: `name*`, `slug*`, `status` |
| PUT | `/api/v1/cms/article-tags/{id}` | Cập nhật tag | CMS | Path `id*`; Body: `name`, `slug`, `status` |
| DELETE | `/api/v1/cms/article-tags/{id}` | Xóa tag | CMS | Path `id*` |

## 11. Đơn hàng (Orders)

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| POST | `/api/v1/orders` | Tạo đơn / thao tác trên một căn | User | Body: `unitId*`, `action`, `note` |
| GET | `/api/v1/my-orders` | Danh sách đơn của tôi | User | — |
| GET | `/api/v1/cms/orders` | Danh sách đơn (CMS) | CMS | Query `status`, `q` |
| PATCH | `/api/v1/cms/orders/{id}/status` | Cập nhật trạng thái đơn (duyệt/từ chối) | CMS | Path `id*`; Body: `status*`, `rejectReason` |

## 12. Yêu cầu khóa căn (Lock Requests)

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| POST | `/api/v1/lock-requests` | Tạo yêu cầu khóa một căn | User | Body: `unitId*` |
| GET | `/api/v1/my-lock-requests` | Yêu cầu khóa của tôi | User | — |
| GET | `/api/v1/lock-requests/{id}` | Chi tiết một yêu cầu khóa | User | Path `id*` |
| POST | `/api/v1/lock-requests/{id}/upload-unc` | Upload ủy nhiệm chi (UNC) cho yêu cầu | User | Path `id*`; Body: `imageUrl*` |
| POST | `/api/v1/lock-requests/{id}/cancel` | Hủy yêu cầu khóa | User | Path `id*` |
| GET | `/api/v1/lock-request-reasons` | Danh sách lý do khóa/từ chối | User | — |
| GET | `/api/v1/cms/lock-requests` | Danh sách yêu cầu khóa (CMS) | CMS | Query `status`, `apartmentCode`, `phone`, `parentProjectId`, `reasonId`, `dateFrom`, `dateTo`, `page` |
| GET | `/api/v1/cms/lock-requests/{id}` | Chi tiết yêu cầu khóa (CMS) | CMS | Path `id*` |
| POST | `/api/v1/cms/lock-requests/{id}/approve` | Duyệt yêu cầu khóa | CMS | Path `id*` |
| POST | `/api/v1/cms/lock-requests/{id}/confirm-sale` | Xác nhận bán (sau khi khóa) | CMS | Path `id*` |
| POST | `/api/v1/cms/lock-requests/{id}/complete` | Hoàn tất yêu cầu khóa | CMS | Path `id*` |
| POST | `/api/v1/cms/lock-requests/{id}/reject` | Từ chối yêu cầu khóa | CMS | Path `id*`; Body: `reasonId*`, `note*`, `kind*` (`lock` \| `unc`) |

## 13. Upload Media

| Method | Endpoint | Chức năng | Auth | Ghi chú |
|---|---|---|---|---|
| POST | `/api/v1/media/upload` | Upload media (người dùng) | User | Không mô tả body trong spec (thường `multipart/form-data`) |
| POST | `/api/v1/cms/media/upload` | Upload media (CMS) | CMS | Không mô tả body trong spec (thường `multipart/form-data`) |

## 14. Xem căn & Nhật ký (Apartment Views / Logs)

| Method | Endpoint | Chức năng | Auth | Tham số / Body |
|---|---|---|---|---|
| POST | `/api/v1/apartment-views` | Ghi nhận một lượt xem căn | User | Body: `unitId*`, `location`, `note` |
| GET | `/api/v1/cms/apartment-view-logs` | Nhật ký lượt xem căn (chi tiết) | CMS | Query `text`, `code`, `projectId`, `projectChild`, `userId`, `dateFrom`, `dateTo`, `page`, `pageSize` |
| GET | `/api/v1/cms/apartment-view-counts` | Thống kê số lượt xem căn | CMS | Query như trên |
| GET | `/api/v1/cms/data-change-logs` | Nhật ký thay đổi dữ liệu (audit) | CMS | Query `loggableType` (`project`\|`project_unit`), `action` (`created`\|`updated`\|`deleted`\|`imported`), `userId`, `projectName`, `apartmentCode`, `dateFrom`, `dateTo`, `page`, `pageSize` |

## 15. Hệ thống

| Method | Endpoint | Chức năng | Auth | Tham số |
|---|---|---|---|---|
| GET | `/health` | Kiểm tra tình trạng hoạt động của service | Public | — |

---

## 16. Bảng giá trị enum tham chiếu

Các giá trị enum xuất hiện trong tham số query & body (gom nhóm theo ngữ nghĩa):

| Nhóm | Áp dụng cho | Giá trị hợp lệ |
|---|---|---|
| **Vùng miền** (`area_region` / `areaRegion`) | Dự án | `mien_bac`, `mien_trung`, `mien_nam` |
| **Loại dự án / sản phẩm** (`type`) | Dự án | `cao_tang`, `thap_tang`, `can_ho` |
| **Loại quỹ hot** (`fund_type` / `fundType`) | Căn hộ | `hot`, `quy_hot` |
| **Trạng thái nội dung** (`status`) | Dự án / bài viết / trang / danh mục | `published`, `draft`, `hidden`, `active` |
| **Trạng thái căn hộ** (`status`) | Unit | `available`, `ready`, `sold`, `locked`, `hidden` |
| **Trạng thái sự kiện** (`status`) | Event | `upcoming`, `ongoing`, `ended`, `all` |
| **Trạng thái yêu cầu khóa / đơn** (`status`) | Order / Lock-request | `pending`, `pending_review`, `awaiting_unc`, `awaiting_payment`, `awaiting_sale_confirm`, `completed`, `recorded`, `rejected`, `rejected_lock`, `rejected_unc`, `expired` |
| **Loại từ chối** (`kind`) | Lock-request reject | `lock`, `unc` |
| **Loại media** | Video/tài liệu dự án | `youtube`, `file` |
| **Loại đối tượng log** (`loggableType`) | Data-change-log | `project`, `project_unit` |
| **Hành động log** (`action`) | Data-change-log | `created`, `updated`, `deleted`, `imported` |
| **pageSize** | Danh sách phân trang | `10`, `20`, `50`, `100`, `200`, `500` |
