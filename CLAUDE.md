# CLAUDE.md

Hướng dẫn cho phiên Claude Code làm việc trong repo này.

## Project

**Phone Shop — Backend.** Cửa hàng bán lẻ điện thoại (kiểu thegioididong.com) + nguồn dữ liệu cho agent tư vấn mua điện thoại (repo `../agent`). Một cửa hàng, **không tenant**, một schema Postgres `shop`. Đọc: [README.md](README.md) → [thiết kế DB](docs/superpowers/specs/2026-11-02-phone-shop-db-design.md).

Repo này copy từ `odyssey-portal-backend` (portal BĐS đa tenant) và đã viết lại 2026-11-02. Code/tài liệu cũ chỉ còn trong lịch sử git — đừng làm theo khái niệm cũ (tenant, RLS, `tenant_conn`, `control.*`, `tenant_data.*`, dự án/phân khu/căn).

## ⚠️ Máy dev dùng chung — đọc trước khi chạm Docker/Postgres

Dự án KHÁC (`/home/dungnd/Dungnd/dev/odyssey-project/odyssey-portal-backend`) đang chạy containers `odyssey-portal-backend-*` ở 5442/6382/6343/9002, network `odyssey-network`. Dự án NÀY là compose project **`pj2-backend`**: Postgres **5452**, Redis 6392, Qdrant 6353/6354, MinIO 9012/9013, API 8110 (host) / 8111 (container), network `pj2-network` — tất cả khai trong `.env`. Trước khi chạy gì vào Postgres/Docker, xác nhận đúng container (`docker inspect … com.docker.compose.project.working_dir`). Test dùng Postgres testcontainers riêng, không bao giờ nối DB dev.

## Commands

```bash
make up            # dev (hạ tầng) → migrate → grant-api-dev → seed-shop
make api           # uvicorn --reload, cổng PORTAL_API_PORT
make worker        # hàng đợi shop.jobs
make check         # ruff check + format --check + pytest
make test-module M=products
make reset         # down -v — xoá sạch hạ tầng pj2-backend
```

## Kiến trúc

```
src/portal/
├─ api/      app.py (create_app, ROUTERS — thêm module = 1 import + 1 dòng) · loi.py
├─ core/     config · db/pool (get_pool) · db/session (tx) · crud · ban_hang · dto · jobs · storage · public_url · redis
├─ modules/  catalog · products · promotions · finance · policies · content · stores · customers · reviews · kb
└─ worker/   load_handlers() → modules/kb/jobs.py
```

- **Module** = `contracts.py` (DTO `CamelIn`/`CamelOut`, camelCase trên dây) + `router.py` (`ROUTER`). Bảng phẳng dùng `core.crud.dang_ky_crud(...)`; route phức tạp dùng `chen/sua/lay/xoa/liet_ke` của `core.crud`.
- **Mọi ghi đi qua `tx(pool)`** (một giao dịch). Đọc đơn: `pool.acquire()`.
- **Lỗi**: raise `LoiPortal`/`khong_tim_thay`. Lỗi ràng buộc DB (UNIQUE/FK/CHECK/NOT NULL) KHÔNG bắt — `api/loi.py` dịch sang 409/422 ở một chỗ. Ràng buộc DB là nguồn sự thật cuối cùng.
- **Ranh giới**: module chỉ import `portal.core`, `portal.api` và chính nó (`tests/test_ranh_gioi_module.py`). Logic dùng chung → `core/` (vd `core/ban_hang.py`: đối tượng áp dụng KM/trả góp, giá hiện hành, làm tròn tiền).
- **numeric DB → `float` trong Out** (Decimal ra JSON thành chuỗi). Tiền = `int` VND. Alias tay khi `to_camel` sai (`has_5g` → `has5g`, không phải `has5G`).
- FastAPI 0.141: router đã include không nằm phẳng trong `app.routes` — liệt kê route qua `app.openapi()["paths"]`.

## DB

- Một migration `0001_shop`; DDL ở `migrations/versions/_data/0001_shop/schema.sql`. Đã áp lên môi trường nào thì **đóng băng** — thay đổi sau viết migration mới.
- Role: `portal_migrator` (chủ, chỉ alembic — `MIGRATOR_URL`), `portal_api` (CRUD, API+worker — `DATABASE_URL`), `shop_agent_ro` (CHỈ 3 view `agent_*`), `shop_agent_rw` (+ ghi customers/reservations). Role tạo NOLOGIN; login cấp tay (`make grant-api-dev` ở dev).
- **View agent** (`agent_products_v`, `agent_promotions_v`, `agent_stock_v`) có `COMMENT ON` — agent sinh mô tả tool từ đó. `CREATE OR REPLACE VIEW` chỉ thêm cột ở CUỐI.
- **Trigger KB**: ghi vào products/specs/variants/colors/features/tags/faqs/policies/articles/service_packages/product_media, đổi tên brand/category/series ⇒ tự xếp job `kb_index`/`kb_delete` (`shop.enqueue_once`, chống trùng). Code CRUD không phải báo KB. Seed cũng sinh job.
- Schema đổi ⇒ sửa cả `scripts/seed_shop.sql` (`tests/test_schema_va_seed.py` chạy đúng tệp đó).

## KB (modules/kb)

- Collections `{KB_COLLECTION_PREFIX}_documents` / `_media`; khoá S3 dưới `kb/`. Payload lọc: entity, record_id, doc_type, product_id, brand_id, brand, category (+ file_id cho tài liệu upload).
- Text dữ liệu DB **không chứa giá/tồn kho** (đổi liên tục — agent đọc qua view SQL). Bỏ qua khi `content_hash` không đổi (`shop.kb_index_state`). Bản ghi mất/ẩn ⇒ xoá point.
- Job: `kb_index`, `kb_delete`, `kb_file_index`, `kb_reindex_all` (`force` bỏ qua hash).
- `/public/files/{key}` chỉ phát tiền tố trong `PUBLIC_PREFIXES` (`kb/router.py`); tệp gốc upload (`kb/files/`) giữ kín.
- Test fake embed/Qdrant/S3 (`kb/deps.py` là chỗ nối dây thật duy nhất).

## Chưa có (cố ý)

Đăng nhập/phân quyền admin (mọi route đang mở) · đơn hàng · giá theo khu vực (giá chung toàn hệ thống — đã chốt).

## Tự bảo trì file này

Cập nhật cùng commit khi đổi kiến trúc, luật, lệnh Make, cổng, schema hoặc hợp đồng với agent.
