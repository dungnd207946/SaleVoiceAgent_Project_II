.PHONY: dev down reset ps migrate grant-api-dev seed-shop up \
        test test-module lint api worker check

# `local` chứ không `dev`: docker-compose.dev.yml là file DEPLOY, không có postgres/minio.
DC := docker compose -f docker-compose.local.yml

# ─── Hạ tầng ────────────────────────────────────────────────────────────────
# `--wait` chứ không phải `up -d` trần: `up -d` trả về ngay khi container ĐÃ CHẠY,
# không phải khi postgres SẴN SÀNG NHẬN KẾT NỐI. Thiếu nó thì `make up` chạy
# `migrate` vào một server còn đang khởi động và chết với "server closed the
# connection unexpectedly" — một lỗi trông như hỏng cấu hình chứ không như đua tốc độ.
# Compose đọc healthcheck của postgres (pg_isready) để biết lúc nào là sẵn sàng.
dev:            ## dựng postgres + redis + qdrant + minio, chờ tới khi sẵn sàng
	$(DC) up -d --wait

down:           ## dừng container, GIỮ dữ liệu
	$(DC) down

# `down -v` xoá cả volume ẩn danh chứa /var/lib/postgresql/data. Compose file này
# không khai volume có tên, nên đây là cách duy nhất dựng lại DB từ số 0.
reset:          ## dừng + XOÁ dữ liệu — dựng lại DB từ đầu
	$(DC) down -v

ps:
	$(DC) ps

migrate:
	uv run alembic upgrade head

# Migration 0001_shop tạo portal_api ở dạng NOLOGIN không mật khẩu — fail-closed, để
# không có mật khẩu nào nằm trong git. Nên sau `make migrate` lần đầu, DSN runtime
# trong .env chưa nối được. Đây là bước đó, CHỈ dùng cho container dev.
# Mật khẩu production: xem deploy/README.md §3.
# Bốn tên/mật khẩu lấy từ `.env` (PORTAL_PG_* / PORTAL_API_DB_*) — cùng nguồn với
# docker-compose.local.yml. Hardcode ở đây là cái bẫy: đổi mật khẩu trong `.env` mà
# recipe này vẫn `ALTER ROLE ... 'apidev'` thì API chết với "password authentication
# failed" trong khi cả hai file đều "trông đúng".
grant-api-dev:  ## cho portal_api login bằng mật khẩu dev (chạy SAU make migrate)
	@set -a; [ -f .env ] && . ./.env; set +a; \
	$(DC) exec -T postgres psql -U "$${PORTAL_PG_USER:-portal_migrator}" -d "$${PORTAL_PG_DB:-portal}" \
		-c "ALTER ROLE $${PORTAL_API_DB_USER:-portal_api} LOGIN PASSWORD '$${PORTAL_API_DB_PASSWORD:-apidev}';"

# Chạy TRONG container postgres dev (không qua DSN) nên không thể lỡ tay seed DB thật.
# Một giao dịch (-1): lỗi giữa chừng thì không để lại dữ liệu nửa vời. Chạy trên DB đã
# có dữ liệu sẽ trùng khoá và dừng — muốn seed lại thì `make reset up`.
seed-shop:      ## dữ liệu mẫu schema shop: tham chiếu + iPhone 16 Pro Max (CHỈ dev)
	@set -a; [ -f .env ] && . ./.env; set +a; \
	$(DC) exec -T postgres psql -U "$${PORTAL_PG_USER:-portal_migrator}" -d "$${PORTAL_PG_DB:-portal}" \
		-v ON_ERROR_STOP=1 -q -1 < scripts/seed_shop.sql

# Bốn bước theo ĐÚNG thứ tự: grant-api-dev trước migrate thì role portal_api chưa tồn tại.
up: dev migrate grant-api-dev seed-shop   ## dựng tất cả từ số 0
	@set -a; [ -f .env ] && . ./.env; set +a; \
	echo ""; echo "xong. make api -> http://localhost:$${PORTAL_API_PORT:-8110}/docs · make worker cho KB"

# ─── Test ───────────────────────────────────────────────────────────────────
test:
	uv run pytest -v

# Test chạy trên Postgres testcontainers RIÊNG — không đụng DB dev. Một module: make test-module M=products
test-module:
	uv run pytest tests/modules/$(M) -v

# ─── Chất lượng ─────────────────────────────────────────────────────────────
lint:
	uv run ruff check . && uv run ruff format --check .

# Cổng lấy từ PORTAL_API_PORT trong .env (máy dev dùng chung — đừng dùng cổng mặc định).
api:            ## chạy API (cần: make dev && make migrate && make grant-api-dev)
	@set -a; [ -f .env ] && . ./.env; set +a; \
	uv run uvicorn portal.api.app:create_app --factory --reload --host 0.0.0.0 --port $${PORTAL_API_PORT:-8110}

worker:         ## hàng đợi shop.jobs (index Qdrant, bóc chữ tài liệu)
	uv run python -m portal.worker

check: lint test   ## chạy trước khi mở merge request
