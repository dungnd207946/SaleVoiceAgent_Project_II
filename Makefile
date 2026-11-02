.PHONY: dev down reset ps migrate grant-api-dev dev-seed seed-bds up contracts \
        test test-unit test-isolation test-module lint api worker check

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

# Migration 0003 tạo portal_api ở dạng NOLOGIN không mật khẩu — fail-closed, để
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

# Script tự TỪ CHỐI chạy nếu DSN không trỏ localhost — nó ghi mật khẩu dev vào
# control.users, và chạy nhầm trên DB thật là tạo một tài khoản mà mật khẩu nằm
# trong repo. Xem scripts/dev_seed.py.
dev-seed:       ## seed 1 user · 3 workspace · 2 membership (CHỈ localhost)
	uv run python -m scripts.dev_seed

seed-kho-tep:   ## bucket + 1 access key CHỈ-tiền-tố mỗi workspace (CHỈ localhost)
	uv run python -m scripts.seed_kho_tep

seed-bds:       ## bộ trường mẫu Bất động sản cho mọi workspace (CHỈ localhost)
	uv run python -m scripts.seed_bds

# Năm bước theo ĐÚNG thứ tự này. Chạy lệch là lỗi khó đọc: grant-api-dev trước
# migrate thì role portal_api chưa tồn tại; dev-seed trước migrate thì chưa có bảng;
# seed-bds trước dev-seed thì chưa có tenant nào để seed chính sách trường.
up: dev migrate grant-api-dev dev-seed seed-kho-tep seed-bds   ## dựng tất cả từ số 0
	@echo ""
	@echo "xong. Hai terminal:"
	@echo "  repo này          : make api      -> http://localhost:$${PORTAL_API_PORT:-8100}"
	@echo "  repo frontend     : make dev      -> http://localhost:5273"

# ─── Hợp đồng BE → FE ───────────────────────────────────────────────────────
# Sinh lại contracts/ từ src/portal. Chạy sau khi đổi actions.py, rồi copy sang
# repo frontend — xem contracts/README.md. Quên chạy thì tests/api/test_contracts.py đỏ.
contracts:      ## sinh lại contracts/ từ nguồn
	uv run python -m scripts.gen_contracts

# ─── Test ───────────────────────────────────────────────────────────────────
test:
	uv run pytest -v

test-unit:      ## không cần Docker
	uv run pytest tests/unit -v

test-isolation: ## 6 cổng cách ly — chạy cho MỌI merge request
	uv run pytest tests/isolation -v

# Chạy test của một module: make test-module M=m4
test-module:
	uv run pytest tests/modules/$(M) -v

# ─── Chất lượng ─────────────────────────────────────────────────────────────
lint:
	uv run ruff check . && uv run ruff format --check .

# 8100 chứ không 8080: icr-keycloak giữ 8080, credit-scoring-api giữ 8000. Số này
# phải khớp PORTAL_API_PORT trong .env và proxy '^/api/' trong
# vite.config.ts của repo frontend — hai chỗ, một số.
api:            ## chạy Portal API (cần: make dev && make migrate && make grant-api-dev)
	uv run uvicorn portal.api.app:create_app --factory --reload --host 0.0.0.0 --port $${PORTAL_API_PORT:-8100}

seed-agent:     ## cấp phát 1 deployment + in api_key cho workspace demo (CHỈ localhost)
	uv run python -m scripts.seed_agent

worker:
	uv run python -m portal.worker

check: lint test   ## chạy trước khi mở merge request
