# Thiết kế DB bán lẻ điện thoại (thay domain BĐS)

Ngày: 2026-11-02 · Trạng thái: **ĐÃ CHỐT** · Migration: [`0001_shop`](../../../migrations/versions/0001_shop.py) · DDL: [`_data/0001_shop/schema.sql`](../../../migrations/versions/_data/0001_shop/schema.sql) · Seed: [`scripts/seed_shop.sql`](../../../scripts/seed_shop.sql)

Liên quan: [agent/.../2026-11-02-retail-phone-domain-proposal.md](../../../../agent/docs/superpowers/specs/2026-11-02-retail-phone-domain-proposal.md) (bộ tool agent).

## 1. Nguồn khảo sát

Đã tải và đọc ngày 2026-11-02:

| Trang | Lấy được gì |
|---|---|
| `thegioididong.com/dtdd` (danh sách) | Bộ lọc, thẻ sản phẩm, kiểu sắp xếp |
| `thegioididong.com/dtdd/iphone-16-pro-max` (chi tiết) | Bảng thông số đầy đủ 6 nhóm, giá theo màu × dung lượng, khuyến mãi, cam kết, đánh giá, FAQ, bài viết |
| `/chinh-sach-bao-hanh-san-pham` | Bảo hành cam kết 12 tháng, "Hư gì đổi nấy", phí đổi theo tháng |
| `/tra-gop` | Đối tác tài chính, điều kiện, giấy tờ, phí trễ hạn |

Giá trên trang TGDĐ thay đổi theo khu vực đang chọn ("Giá tại Hồ Chí Minh"). **Hệ thống này không làm như vậy: dùng một giá chung toàn hệ thống** (đã chốt).

## 2. Người mua cần biết gì → lưu ở đâu

### 2.1 Danh sách / bộ lọc

| Trên trang TGDĐ | Bảng.cột |
|---|---|
| Hãng (Samsung, iPhone, OPPO, Xiaomi, vivo, realme, HONOR, Nothing, Tecno, Nubia, Nokia, Masstel, Mobell…) | `brands` |
| Mức giá (dưới 2tr … trên 20tr) | `product_variants.sale_price_vnd` / `list_price_vnd` |
| Loại: Android / iPhone | `phone_specs.os_name` |
| Loại: Điện thoại AI / gập / phổ thông | `products.phone_type`, `tags(kind='segment')` |
| Nhu cầu: chơi game, pin khủng, chụp ảnh, livestream, mỏng nhẹ | `tags(kind='need')` + `product_tags` |
| RAM 3–16 GB · ROM 64 GB–1 TB | `product_variants.ram_gb`, `storage_gb` |
| Độ phân giải (QQVGA … 2K+, Retina) | `phone_specs.resolution_class` |
| Tần số quét 60–185 Hz | `phone_specs.refresh_rate_hz` |
| Sạc nhanh ≥20W / siêu nhanh ≥60W | `phone_specs.max_charge_w` |
| Sạc không dây, Chỉnh ảnh AI | `features` (`is_filterable`) |
| 5G · kháng nước · khuôn mặt 3D · NFC | `has_5g`, `ip_rating`, `has_face_3d`, `has_nfc` |
| Sắp xếp: nổi bật / mới / bán chạy / % giảm / giá | `is_featured`, `release_date`, `sold_count`, `discount_percent` (view), giá |
| Thẻ SP: giá, giá gạch, -x%, sao, "Đã bán 312,5k", "Trả chậm 0%", "Quà 630.000₫" | variant + `rating_avg`, `sold_count`, `installment_plans`, `promotions` |

### 2.2 Trang chi tiết

| Mục | Bảng |
|---|---|
| Tên, phiên bản dung lượng, màu, giá, "TẠM HẾT HÀNG" | `products`, `product_variants`, `product_colors`, `sale_status` |
| Cam kết: máy mới, Hư gì đổi nấy 12 tháng, BH chính hãng 1 năm, **bộ sản phẩm gồm** | `policies`, `products.warranty_*`, `products.in_box` |
| **Thông số kỹ thuật** (dưới đây) | `phone_specs` + `features` |
| Khuyến mãi "Chọn 1 trong các quà", hạn đến 23:59 30/11 | `promotions.choice_group`, `ends_at`, `promotion_targets` |
| Sản phẩm thường mua cùng / liên quan | `product_relations` |
| Bài đánh giá dài, bảng giá các phiên bản | `articles` + `article_products` |
| Câu hỏi thường gặp | `faqs` |
| Đánh giá (4.9/5, 229 lượt, "Đã mua tại…", phản hồi của shop) | `product_reviews` |
| Hỏi đáp | `product_questions` |
| Ảnh, video | `product_media` (theo màu được) |

**Bảng thông số kỹ thuật (6 nhóm)**: đơn trị → `phone_specs`, đa trị → `features.feature_group`

- **Cấu hình & bộ nhớ**: HĐH, chip, tốc độ CPU, GPU, RAM\*, dung lượng\*, dung lượng khả dụng\*, thẻ nhớ, danh bạ (\* = theo biến thể)
- **Camera & màn hình**: độ phân giải cam sau/trước, flash · *quay phim cam sau, tính năng cam sau/trước* (đa trị) · công nghệ, độ phân giải, kích thước, tần số quét, độ sáng, mặt kính
- **Pin & sạc**: dung lượng (iPhone chỉ ghi "33 giờ", nên cần cả `battery_mah` lẫn `battery_text`), loại pin, sạc tối đa, sạc kèm máy · *công nghệ pin* (đa trị)
- **Tiện ích**: bảo mật, kháng nước, ghi âm, radio, đèn pin · *tính năng đặc biệt, xem phim, nghe nhạc* (đa trị)
- **Kết nối**: mạng, SIM, Bluetooth, cổng sạc, jack tai nghe · *Wi-Fi, GPS, kết nối khác* (đa trị)
- **Thiết kế**: kiểu thiết kế, chất liệu, kích thước/khối lượng (tách 4 cột số), thời điểm ra mắt (`products.release_date`)

### 2.3 Chính sách bán hàng

| Nội dung | Bảng |
|---|---|
| Bảo hành cam kết 12 tháng, đổi trả, khui hộp Apple, giao hàng, xử lý dữ liệu | `policies` (theo `policy_type`, phạm vi hãng/ngành hàng tuỳ chọn) |
| Gói mua thêm: BH rơi vỡ, BH mở rộng, 1 đổi 1 | `service_packages` |
| Trả chậm: Home Credit, FE Credit, ACS, MAFC, MCredit, thẻ tín dụng; tuổi 18–60, CCCD, trả trước %, kỳ hạn, lãi 0% | `finance_partners`, `installment_plans` (1 dòng = đối tác × kỳ hạn), `installment_plan_targets` |
| Thu cũ đổi mới (+2tr) | `promotions.promo_type='trade_in_bonus'` |
| Hệ thống 3.284 siêu thị, tồn kho theo cửa hàng | `stores`, `provinces`, `inventory` |

## 3. Mô hình (34 bảng + 3 view, schema `shop`)

```
brands ─┬─ series
        └─ products ── categories(cây)
             ├─ product_colors ─┐
             ├─ product_variants (SKU: RAM·ROM·màu·tình trạng·giá) ── price_history
             │      └─ inventory ── stores ── provinces
             ├─ phone_specs (1-1)
             ├─ product_features ── features
             ├─ product_tags ── tags
             ├─ product_media · faqs · product_relations · article_products ── articles
             ├─ product_reviews · product_questions ── customers
promotions ── promotion_targets → (product | variant | brand | category)
finance_partners ── installment_plans ── installment_plan_targets → (…)
policies · service_packages (phạm vi brand/category)
customers ── reservations (giữ hàng / hẹn)
(làm sau: orders · order_items · order_promotions)
jobs (hàng đợi worker) · kb_files (tài liệu tra cứu) · kb_index_state (sổ index Qdrant)
VIEW: agent_products_v · agent_promotions_v · agent_stock_v
```

## 4. Các quyết định thiết kế

1. **Product → Variant (SKU).** Giá, RAM/ROM, màu, tồn kho, tình trạng hàng nằm ở biến thể, vì TGDĐ định giá theo từng cặp dung lượng × màu (256GB Titan đen 31,59tr ≠ 1TB). Thông số chung nằm ở product.
2. **Thông số: cột có kiểu + bảng từ điển, không dùng EAV/JSONB.** Mỗi trường đơn trị là một cột có kiểu, nên lọc/so sánh/text-to-SQL đều dễ, và CHECK bắt được dữ liệu sai. Trường đa trị (khoảng 12 nhóm, mỗi máy hàng chục giá trị) đi qua `features` + `product_features`, chuẩn 3NF và lọc bằng `EXISTS`. Cột `*_text` giữ nguyên văn để hiển thị cạnh cột số dùng để lọc.
3. **Enum = `text + CHECK`**, cùng lệ với repo (vd `0978`). Thêm giá trị chỉ cần đổi CHECK, không phải `ALTER TYPE`.
4. **"Áp dụng cho ai" = bảng targets với ràng buộc `num_nonnulls(...) = 1`**: một dòng nhắm đúng một cấp product, variant, brand hoặc category. Dùng FK thật, không dùng khoá đa hình.
5. **"Chọn 1 trong các quà"** dùng `promotions.choice_group`: các KM cùng nhóm thì khách chọn một.
6. **Giá:** dùng `bigint` VND. `sale_price_vnd ≤ list_price_vnd`. `% giảm` tính trong view, không lưu. Trigger ghi `price_history`.
7. **Số liệu tổng hợp** (`rating_avg`, `rating_count`, `sold_count`) là cache trên `products`, có chủ đích để danh sách không phải aggregate mỗi lần. Job hoặc trigger cập nhật từ `product_reviews`/`orders`. Đây là ngoại lệ duy nhất với 3NF.
8. **Máy cũ** dùng `condition='used'` và có thể nhiều SKU cho cùng cấu hình. Ràng buộc "1 SKU / cấu hình × màu" chỉ áp cho máy mới (unique index một phần, `NULLS NOT DISTINCT`).
9. **Agent đọc view phẳng**, không đọc bảng. View có `COMMENT ON` để sinh mô tả tool, và `search_text` đã bỏ dấu cho `ILIKE`. Đơn hàng/khách **không** vào view.
10. **Không tenant, không RLS**. Toàn bộ nằm trong một schema `shop`.

## 4b. Kho tri thức (thêm khi refactor BE)

- `jobs`: hàng đợi của worker. `shop.enqueue_once()` chống xếp trùng một việc đang chờ.
- Trigger `kb_enqueue` trên products, phone_specs, variants, colors, features, tags, faqs, policies, articles, article_products, service_packages và product_media; trigger `kb_enqueue_products_of` khi đổi tên brand/category/series. Hai trigger này tự xếp job `kb_index`/`kb_delete`, nên code CRUD không phải báo cho KB.
- `kb_files`: tệp upload (pdf/docx/xlsx/md), có thể gắn với sản phẩm hoặc hãng. `kb_index_state` giữ content hash, trạng thái và số point của từng bản ghi DB đã index.

## 5. Role & quyền

| Role (NOLOGIN) | Quyền |
|---|---|
| `portal_api` | CRUD mọi bảng `shop` (`make grant-api-dev` cấp LOGIN ở dev) |
| `shop_agent_ro` | CHỈ `SELECT` 3 view `agent_*`, không đọc được bảng gốc (dùng cho text-to-SQL) |
| `shop_agent_rw` | `shop_agent_ro` + ghi `customers`, `reservations` |

## 6. Đã kiểm chứng

Trên database tạm của Postgres 18 dev, không đụng DB thật:

- `alembic upgrade head`, rồi `downgrade base`, rồi `upgrade` lại đều sạch.
- `seed_shop.sql` nạp đủ: 12 SKU, 83 tính năng, 33 dòng tồn kho, 12 dòng lịch sử giá.
- Chạy với quyền `shop_agent_ro`: view trả `iPhone 16 Pro Max 8GB/256GB Titan sa mạc | 31.590.000 | -7% | còn 9 | trả chậm 0%`; đọc `shop.products` bị `permission denied`.
- `shop_agent_rw` ghi được `customers`.

## 7. Quyết định đã chốt (2026-11-02)

1. **Giá chung toàn hệ thống**, không theo khu vực.
2. **Baseline mới**: 126 migration BĐS đã gỡ (lấy lại từ git), thay bằng `0001_shop`.
3. **Làm sau**: phụ kiện (schema đã sẵn `categories`/`product_relations`), đơn hàng, tài khoản admin.

## 8. Hệ quả cần xử lý tiếp

- Code `src/portal/modules/*`, tests, `scripts/*` cũ vẫn trỏ `control`/`tenant_data` nên sẽ hỏng khi chạy trên DB mới. Cần refactor BE theo schema `shop`.
- DB dev đang chạy còn ở head cũ `0981_data_conflicts`. Phải `make reset up` mới lên `0001_shop` (xoá dữ liệu dev).
