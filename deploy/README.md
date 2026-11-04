# Triển khai

Một image, ba vai (`deploy/entrypoint.sh`): `serve` (API), `worker` (hàng đợi `shop.jobs`), `migrate`.

## 1. Hai credential, hai file env

| Vai | File env | Biến DB | Role Postgres |
|---|---|---|---|
| `migrate` | `odyssey-portal-migrate.env` | `MIGRATOR_URL` | `portal_migrator` (chủ schema, DDL) |
| `serve`, `worker` | `odyssey-portal-backend.env` | `DATABASE_URL` | `portal_api` (CRUD bảng `shop`) |

Entrypoint **từ chối** chạy `serve`/`worker` nếu thấy `MIGRATOR_URL`, để tránh dùng chung một file env cho cả hai.

## 2. Lần đầu trên một môi trường

1. Chạy `migrate`. Migration `0001_shop` tạo các role `portal_api`, `shop_agent_ro` và `shop_agent_rw`, đều ở dạng **NOLOGIN, không mật khẩu**, để không có mật khẩu nào nằm trong git.
2. Cấp login bằng tay:
   ```sql
   ALTER ROLE portal_api LOGIN PASSWORD '<mật khẩu>';
   -- agent (text-to-SQL chỉ đọc view, ghi customers/reservations):
   CREATE ROLE agent_login LOGIN PASSWORD '<mật khẩu>' IN ROLE shop_agent_rw;
   ```
3. Chạy `serve` và `worker`.

## 3. Dịch vụ ngoài

- Postgres ≥ 15 (dùng `NULLS NOT DISTINCT`), cần extension `pg_trgm` và `unaccent`. Migration tự tạo chúng, nên role chạy migrate phải có quyền tạo extension.
- Qdrant: dùng hai collection `{KB_COLLECTION_PREFIX}_documents` / `_media`.
- S3/MinIO: dùng một bucket, khoá tệp KB nằm dưới tiền tố `kb/`.
- Embed service (`KB_EMBED_URL`): worker cần nó để nhúng vector.

## 4. Chưa có

- Đăng nhập admin: mọi route quản trị đang **mở**. Không expose API ra Internet cho tới khi có auth.
