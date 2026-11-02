# Image của `odyssey-portal-backend`. MỘT image, BA vai: `serve` (FastAPI, mặc
# định), `migrate` (alembic) và `seed-owner` (owner đầu tiên) — hai vai sau chạy
# một lần rồi thoát. Vai chọn bằng đối số:
#
#   docker run --rm  --env-file <env> odyssey-portal-backend:<tag> migrate
#   docker run --rm  --env-file <env> odyssey-portal-backend:<tag> seed-owner
#   docker run -d -p 8100:8100 --env-file <env> odyssey-portal-backend:<tag>
#
# Vì sao một image chứ không hai: migration và runtime phải dùng ĐÚNG một bản
# code. Hai image build riêng là hai thứ trôi ra khỏi nhau, và cái trôi lệch chỉ
# lộ ra lúc migration tạo cột mà code chưa biết — trên production.
#
# Hai vai KHÔNG dùng chung credential; luật đó cưỡng chế ở deploy/entrypoint.sh.
# Xem deploy/README.md §1–§2 để biết vì sao, và §8 để biết cách chạy.

# ─── Tầng build ───────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

# UV_COMPILE_BYTECODE: trả tiền biên dịch .pyc lúc build thay vì lúc container
# khởi động. UV_PYTHON_DOWNLOADS=never: dùng python của image, không để uv âm
# thầm tải bản khác — bản khác thì venv không chạy được ở tầng runtime.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Hai bước sync, có chủ đích: bước này chỉ cài THƯ VIỆN và chỉ vỡ cache khi
# pyproject.toml/uv.lock đổi. Sửa một dòng trong src/ không phải cài lại toàn bộ
# dependency.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --no-editable: cài `portal` thành wheel thật trong venv, không phải link về
# /app/src. Nhờ vậy tầng runtime KHÔNG cần mang src/ theo — image cuối chỉ có
# thư viện đã cài, không có mã nguồn nằm rời.
COPY src ./src
# Gói python `playwright` (nhỏ) nằm trong venv của MỌI vai; Chromium (nặng) chỉ
# cài ở tầng `crawl` bên dưới. Vai serve/worker không bao giờ import nó.
RUN uv sync --frozen --no-dev --no-editable

# ─── Tầng crawl (image RIÊNG cho vai crawl-worker/crawl) ──────────────────────
# `docker build --target crawl` → tag `<tag>-crawl`. Chỉ khác tầng runtime ở Chromium
# + thư viện hệ thống cho Playwright (~400 MB) — image serve/worker không mang nó.
FROM python:3.13-slim-bookworm AS crawl

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN groupadd --gid 10001 odyssey \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin odyssey

WORKDIR /app
COPY --from=build --chown=root:root /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY deploy/entrypoint.sh /usr/local/bin/odyssey-entrypoint
RUN chmod 0755 /usr/local/bin/odyssey-entrypoint \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/* \
 && chmod -R a+rX /ms-playwright

USER odyssey
ENTRYPOINT ["/usr/local/bin/odyssey-entrypoint"]
CMD ["crawl-worker"]

# ─── Tầng runtime ─────────────────────────────────────────────────────────────
# python:3.13-slim-bookworm phải khớp python3.13-bookworm-slim ở trên: venv trỏ
# tới interpreter bằng đường dẫn tuyệt đối, lệch minor version là venv chết.
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Không chạy bằng root. uid cố định để devops mount volume (nếu cần) biết chủ sở
# hữu là ai mà không phải đoán.
RUN groupadd --gid 10001 odyssey \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin odyssey

WORKDIR /app

COPY --from=build --chown=root:root /app/.venv /app/.venv

# alembic.ini + migrations/ chỉ vai `migrate` dùng, nhưng vẫn nằm trong image vì
# cùng một image phục vụ cả hai vai — xem đầu file.
COPY alembic.ini ./
COPY migrations ./migrations
COPY deploy/entrypoint.sh /usr/local/bin/odyssey-entrypoint
RUN chmod 0755 /usr/local/bin/odyssey-entrypoint

USER odyssey

# 8100, không phải 8000/8080 — xem src/portal/core/config.py. Đây là cổng BÊN
# TRONG container; devops ánh xạ ra ngoài bằng gì cũng được.
EXPOSE 8100

# Dùng urllib của stdlib chứ không curl: image slim không có curl, và cài thêm
# một gói chỉ để healthcheck là mở rộng bề mặt tấn công không cần thiết.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORTAL_API_PORT','8100')+'/healthz',timeout=4).status==200 else sys.exit(1)"

ENTRYPOINT ["/usr/local/bin/odyssey-entrypoint"]
CMD ["serve"]
