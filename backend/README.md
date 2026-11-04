# Phone Shop — Backend

Backend cho cửa hàng bán lẻ điện thoại (kiểu thegioididong.com) và agent tư vấn mua điện thoại. Có ba phần:

- **API quản trị và trang bán hàng**: sản phẩm, giá, khuyến mãi, trả góp, chính sách, cửa hàng/tồn kho, khách hàng/giữ hàng, đánh giá.
- **Kho tri thức (Qdrant)**: tài liệu upload và dữ liệu DB được nhúng vector để agent `kb_search`.
- **View cho agent**: `shop.agent_*_v`, agent đọc trực tiếp qua text-to-SQL.

Stack: FastAPI · asyncpg (SQL thuần, không ORM) · Postgres 18 · Alembic · Qdrant · MinIO/S3 · uv.

> ⚠️ **Chưa có đăng nhập.** Mọi route quản trị đang mở. Chỉ chạy ở dev, không expose ra Internet.

## Chạy local

```bash
cp .env.example .env          # cổng riêng của dự án này: Postgres 5452, API 8110…
docker network create pj2-network   # một lần
make up                       # dựng hạ tầng → migrate → cấp login portal_api → seed mẫu
make api                      # http://localhost:8110/docs
make worker                   # hàng đợi shop.jobs (index Qdrant) — cần KB_EMBED_URL
make check                    # ruff + toàn bộ test (Postgres testcontainers riêng)
```

`make reset` xoá sạch hạ tầng của dự án này (`pj2-backend`), không đụng container của dự án khác.

## Cấu trúc

```
migrations/versions/0001_shop.py          baseline duy nhất
migrations/versions/_data/0001_shop/      DDL schema `shop` (bảng, view agent, trigger KB)
scripts/seed_shop.sql                     dữ liệu mẫu (make seed-shop)
src/portal/
├─ api/        create_app() · ROUTERS · handler lỗi (lỗi ràng buộc DB → 409/422)
├─ core/       config · db (pool, tx) · crud (CRUD dùng chung) · ban_hang · jobs · storage · public_url
├─ modules/    catalog · products · promotions · finance · policies · content
│              stores · customers · reviews · kb
└─ worker/     tiêu hoá shop.jobs
```

## API (`/api/v1`, xem đầy đủ ở `/docs`)

| Module | Nội dung |
|---|---|
| catalog | hãng, ngành hàng, dòng máy, nhãn nhu cầu, từ điển tính năng |
| products | sản phẩm, màu, biến thể/SKU (lịch sử giá), thông số, media, FAQ, sản phẩm liên quan. Trang bán hàng: `GET /catalog/products` (lọc kiểu TGDĐ), `/catalog/products/{slug}` (chi tiết gộp), `/catalog/compare` |
| promotions | khuyến mãi + đối tượng áp dụng; `/promotions/applicable` |
| finance | đối tác tài chính, gói trả góp + đối tượng áp dụng; `/installment-plans/quote(s)` tính tiền góp |
| policies | chính sách, gói bảo hành mua thêm; `/service-packages/quote` |
| content | bài viết + sản phẩm liên kết |
| stores | tỉnh/thành, cửa hàng, tồn kho; `/variants/{id}/availability` |
| customers | khách hàng (chuẩn hoá SĐT), giữ hàng/hẹn (trừ tồn kho trong giao dịch) |
| reviews | đánh giá (tự tính lại điểm sản phẩm), hỏi đáp |
| kb | tài liệu tra cứu (`/kb/files`), `/kb/reindex`, `/kb/status`, `/public/files/{key}` |

Thiết kế DB: [docs/superpowers/specs/2026-11-02-phone-shop-db-design.md](docs/superpowers/specs/2026-11-02-phone-shop-db-design.md). Triển khai: [deploy/README.md](deploy/README.md).
