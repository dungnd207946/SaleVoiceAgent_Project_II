#!/bin/sh
# Entrypoint của image backend. Chọn vai bằng đối số:
#
#   serve      (mặc định)  FastAPI/uvicorn — tiến trình chạy mãi
#   worker                 hàng đợi shop.jobs (index Qdrant, bóc chữ) — tiến trình chạy mãi
#   migrate                alembic upgrade head — chạy một lần rồi thoát
#
# Các lệnh `chet` dưới đây KHÔNG phải kiểm tra thừa: cấu hình mặc định trong
# src/portal/core/config.py trỏ về localhost của máy dev. Thiếu biến ở production thì
# tiến trình vẫn khởi động rồi nối vào hư không — lỗi hiện ra ở request đầu tiên dưới
# dạng timeout. Fail-closed ở đây biến nó thành một dòng lỗi đọc là hiểu.
set -eu

chet() {
  echo "backend: LỖI CẤU HÌNH — $1" >&2
  exit 1
}

VAI="${1:-serve}"

case "$VAI" in

  serve | worker)
    # MIGRATOR_URL là credential của `portal_migrator` — chủ mọi schema, toàn quyền DDL.
    # Tiến trình runtime cầm nó thì một bug là sửa được lược đồ. Cách hỏng thường gặp
    # nhất là devops dùng CHUNG một file env cho cả hai vai — nên chặn tại đây.
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai '$VAI' KHÔNG được nhận MIGRATOR_URL.
  MIGRATOR_URL chỉ dành cho vai 'migrate'. Dùng hai file env riêng: file của backend/worker
  chỉ có DATABASE_URL (role portal_api), file của migrate chỉ có MIGRATOR_URL."

    [ -n "${DATABASE_URL:-}" ] || chet "vai '$VAI' cần DATABASE_URL (DSN của role portal_api)."

    # exec: tiến trình thành PID 1 để nhận thẳng SIGTERM lúc dừng container — không thì
    # mọi lần deploy kết thúc bằng SIGKILL sau 10 giây, request/job đang chạy bị cắt ngang.
    if [ "$VAI" = serve ]; then
      exec uvicorn portal.api.app:create_app \
        --factory \
        --host 0.0.0.0 \
        --port "${PORTAL_API_PORT:-8100}"
    fi
    exec python -m portal.worker
    ;;

  migrate)
    [ -n "${MIGRATOR_URL:-}" ] || chet "vai 'migrate' cần MIGRATOR_URL (DSN của role portal_migrator).
  Không có nó, alembic dùng DSN mặc định trỏ localhost của máy dev.
  Chi tiết: deploy/odyssey-portal-migrate.env.example."

    echo "backend: alembic upgrade head"
    exec alembic upgrade head
    ;;

  *)
    chet "vai không hợp lệ: '$VAI'. Chỉ có 'serve' (mặc định), 'worker' hoặc 'migrate'."
    ;;

esac
