#!/bin/sh
# Entrypoint của image `odyssey-portal-backend`. Chọn vai bằng đối số:
#
#   serve      (mặc định)  FastAPI/uvicorn — tiến trình chạy mãi
#   worker                 hàng đợi control.jobs — tiến trình chạy mãi
#   migrate                alembic upgrade head — chạy một lần rồi thoát
#   seed-owner             tạo owner đầu tiên + in link mời — một lần MỖI MÔI TRƯỜNG
#   dinh-gia               định giá billing.usage_events — chạy một lần rồi thoát
#                          (gọi từ systemd timer, xem deploy/systemd/)
#   crawl                  chuỗi đêm/tuần/quý kb/web — chạy một lần rồi thoát
#                          (gọi từ systemd timer, xem deploy/systemd/)
#   crawl-worker           hàng đợi kbweb_project — tiến trình chạy mãi
#
# Ba lệnh `chet` dưới đây KHÔNG phải kiểm tra thừa. Cấu hình mặc định trong
# src/portal/core/config.py trỏ về localhost:5442 của máy dev. Thiếu biến ở
# production thì tiến trình vẫn KHỞI ĐỘNG BÌNH THƯỜNG rồi nối vào hư không —
# lỗi hiện ra lúc request đầu tiên, dưới dạng timeout khó truy. Fail-closed ở
# đây biến nó thành một dòng lỗi đọc là hiểu, trước khi container lên xanh.
set -eu

chet() {
  echo "odyssey-portal-backend: LỖI CẤU HÌNH — $1" >&2
  exit 1
}

VAI="${1:-serve}"

case "$VAI" in

  serve)
    # MIGRATOR_URL là credential của `portal_migrator` — chủ sở hữu mọi schema,
    # toàn quyền DDL. Postgres FORCE RLS KHÔNG áp cho chủ bảng, nên một tiến
    # trình runtime cầm nó là một tiến trình chạy NGOÀI lớp cách ly tenant: một
    # câu truy vấn quên WHERE đọc và ghi xuyên mọi khách hàng, âm thầm, không
    # một lỗi nào. Xem deploy/README.md §1–§2.
    #
    # Chặn ở đây vì cách hỏng thường gặp nhất là devops dùng CHUNG một file env
    # cho cả hai vai — hoàn toàn hợp lý nếu không ai nói, và không có gì báo sai.
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai 'serve' KHÔNG được nhận MIGRATOR_URL.
  MIGRATOR_URL là credential toàn quyền DDL, chỉ dành cho vai 'migrate'.
  Cách sửa: dùng hai file env riêng — file của backend chỉ có DATABASE_URL
  (role portal_api), file của migrate chỉ có MIGRATOR_URL (role portal_migrator).
  Chi tiết: deploy/README.md §1–§2, deploy/odyssey-portal-backend.env.example."

    [ -n "${DATABASE_URL:-}" ] || chet "thiếu DATABASE_URL (DSN của role portal_api)."
    [ -n "${REDIS_URL:-}" ]    || chet "thiếu REDIS_URL (Redis giữ phiên đăng nhập)."

    # exec: uvicorn thành PID 1 để nhận thẳng SIGTERM lúc dừng container. Không
    # có exec thì sh giữ PID 1, nuốt tín hiệu, và mọi lần deploy đều kết thúc
    # bằng SIGKILL sau 10 giây — kết nối đang phục vụ bị cắt ngang.
    exec uvicorn portal.api.app:create_app \
      --factory \
      --host 0.0.0.0 \
      --port "${PORTAL_API_PORT:-8100}"
    ;;

  migrate)
    [ -n "${MIGRATOR_URL:-}" ] || chet "vai 'migrate' cần MIGRATOR_URL (DSN của role portal_migrator).
  Không có nó, alembic dùng DSN mặc định trỏ localhost:5442 của máy dev.
  Chi tiết: deploy/odyssey-portal-migrate.env.example."

    echo "odyssey-portal-backend: alembic upgrade head"
    exec alembic upgrade head
    ;;

  seed-owner)
    # DATABASE_URL, KHÔNG MIGRATOR_URL: script chỉ INSERT vào schema `control`, mà
    # 0003 đã GRANT đủ cho role runtime. Nên vai này dùng ĐÚNG file env của backend
    # — devops không phải cấp credential mới, và cũng không được cấp: chặn
    # MIGRATOR_URL ở đây cùng lý lẽ với vai `serve`.
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai 'seed-owner' KHÔNG được nhận MIGRATOR_URL.
  Việc ở đây là DML trên schema control, không cần quyền DDL. Dùng
  deploy/odyssey-portal-backend.env (role runtime), không phải file của migrate."

    [ -n "${DATABASE_URL:-}" ] || chet "vai 'seed-owner' cần DATABASE_URL (DSN của role runtime)."
    [ -n "${SEED_OWNER_EMAIL:-}" ] || chet "vai 'seed-owner' cần SEED_OWNER_EMAIL — email của người sẽ làm owner.
  Đây là hộp thư nhận link mời, nên nó phải là hộp thư người đó mở được."
    [ -n "${SEED_ORG_ID:-}" ] || chet "vai 'seed-owner' cần SEED_ORG_ID — id tổ chức, ^[a-z][a-z0-9_]{1,30}\$.
  Id này KHÔNG đổi được về sau: nó nằm trong mọi hàng users và tenants."

    # `python -m portal.cli.seed_owner`, KHÔNG `uv run`: tầng runtime của image
    # không có uv, và `portal` đã được cài thành wheel trong /app/.venv (PATH).
    # Cùng khuôn với `exec alembic upgrade head` ở vai `migrate`.
    #
    # KHÔNG `| tee`: link mời chỉ đi ra stdout của job deploy, không ghi xuống file
    # nào trên máy deploy. Nó là chứng cứ duy nhất đặt được mật khẩu owner.
    exec python -m portal.cli.seed_owner
    ;;

  worker)
    # Thêm 2026-08-05. Điều kiện mà README §8.4 đặt ra — "thêm nhánh này CÙNG LÚC
    # với `jobs.py` đầu tiên" — đã tới: `modules/kb/jobs.py` register `kb_index` ·
    # `kb_delete` · `kb_reconcile`, và `POST /kb/{entity}/{id}/reindex` trả 202 vì
    # việc thật (embedding qua Qwen-VL, ~30 giây) KHÔNG nhét được vào một request.
    #
    # Không có vai này thì reindex trả 202 rồi im lặng vĩnh viễn — đúng cách hỏng mà
    # publish vừa mắc và vừa được chữa bằng cách bỏ job. Với `kb` thì không bỏ được:
    # 30 giây trong một HTTP request là một cách hỏng khác, không phải một cách sửa.
    #
    # `config/jobs.py` cũng còn register `publish`/`rollback`, nhưng CHỈ để tiêu hoá
    # những hàng `queued` còn tồn từ trước lần deploy này — xem file đó.

    # Cùng ba phép kiểm với vai `serve`, và MIGRATOR_URL bị chặn ở đây vì lý do MẠNH
    # HƠN: một job handler quên `WHERE` chạy trên mọi tenant mà không một request nào
    # ghi lại, không một người dùng nào nhìn thấy (deploy/README.md §8.4).
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai 'worker' KHÔNG được nhận MIGRATOR_URL.
  Worker chạy job handler bằng role runtime để RLS còn hiệu lực. Cầm credential
  của portal_migrator là chạy NGOÀI lớp cách ly tenant — và ở worker thì không có
  ai nhìn thấy hậu quả. Dùng deploy/odyssey-portal-backend.env, chung file với 'serve'."

    [ -n "${DATABASE_URL:-}" ] || chet "vai 'worker' cần DATABASE_URL (DSN của role portal_api)."

    # REDIS_URL: worker KHÔNG phục vụ phiên đăng nhập nên không cần Redis. Không kiểm
    # ở đây — thêm một phép kiểm không có thật là dạy devops bỏ qua các phép kiểm.

    # exec: cùng lý lẽ với `serve` — worker thành PID 1 để nhận thẳng SIGTERM. Nó đang
    # ngủ 2 giây giữa hai lượt poll, nên không exec là mọi lần deploy đợi hết 10 giây
    # grace rồi ăn SIGKILL, và một job đang chạy giữa đường bị cắt.
    exec python -m portal.worker
    ;;

  dinh-gia)
    # Thêm 2026-08-21. Không có vai này thì `billing.rated_usage` KHÔNG BAO GIỜ
    # được ghi, và portal hiện `0 ₫` ở mọi màn chi phí dù migration `0949` đã seed
    # bảng giá — hỏng im lặng nhất của cả module billing: mọi con số vẫn render,
    # chỉ toàn là 0, và không một lỗi nào phát ra ở đâu.
    #
    # MIGRATOR_URL, KHÔNG DATABASE_URL: `billing.rate_usage()` là SECURITY DEFINER
    # nên `portal_api` gọi được, nhưng job này định giá cho MỌI tenant
    # (`p_tenant = NULL`) — thao tác cấp NỀN TẢNG, không thuộc phạm vi cách ly của
    # một request. Xem docstring `portal/cli/dinh_gia_usage.py`. Đây là lý do vai
    # này dùng deploy/odyssey-portal-migrate.env, KHÔNG dùng file của backend.
    [ -n "${MIGRATOR_URL:-}" ] || chet "vai 'dinh-gia' cần MIGRATOR_URL (DSN của role portal_migrator).
  Không có nó, CLI dùng DSN mặc định trỏ localhost:5442 của máy dev và job đêm
  'thành công' mà không định giá gì. Dùng deploy/odyssey-portal-migrate.env."

    # Mọi đối số sau tên vai đi thẳng vào CLI (`--gio 1`, `--tu/--den`, `--thu-kho`)
    # — đó là cách MỘT vai phục vụ cả lượt nóng 2 phút và lượt nguội hằng đêm mà
    # không sinh ra hai vai gần-giống-nhau để lệch nhau về sau.
    shift
    exec python -m portal.cli.dinh_gia_usage "$@"
    ;;

  crawl-worker)
    # Thêm 2026-09-30. Worker RIÊNG của gói kb/web (`kbweb_project`) — không dùng
    # chung `worker` ở trên vì crawl chạy trafilatura/LLM/Gemini, tải rất khác nhịp
    # với các job kb_index/kb_delete hiện có; tách để nhân bản/giới hạn tài nguyên
    # độc lập (xem docker-compose.dev.yml).
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai 'crawl-worker' KHÔNG được nhận MIGRATOR_URL.
  Cùng lý lẽ vai 'worker': job handler chạy bằng role runtime để RLS còn hiệu lực."

    [ -n "${DATABASE_URL:-}" ] || chet "vai 'crawl-worker' cần DATABASE_URL (DSN của role portal_api)."

    exec python -m portal.cli.kb_web_worker
    ;;

  crawl)
    # Thêm 2026-09-30. Chuỗi đêm/tuần/dựng lại của kb/web cho MỘT tenant, chạy TAY — xem
    # src/portal/cli/kb_web_night.py. Lịch thật nằm trong crawl-worker (scheduler đọc DB).
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai 'crawl' KHÔNG được nhận MIGRATOR_URL.
  Chuỗi đêm chạy bằng role runtime, không cần quyền DDL."

    [ -n "${DATABASE_URL:-}" ] || chet "vai 'crawl' cần DATABASE_URL (DSN của role portal_api)."

    # Mọi đối số sau tên vai đi thẳng vào CLI (`--tenant T` bắt buộc; `--weekly`, `--rebuild`,
    # `--backfill FROM TO`, `--discover-only --day D`) — cùng khuôn với vai `dinh-gia`.
    shift
    exec python -m portal.cli.kb_web_night "$@"
    ;;

  *)
    chet "vai không hợp lệ: '$VAI'. Chỉ có 'serve' (mặc định), 'worker', 'migrate', 'seed-owner', 'dinh-gia', 'crawl' hoặc 'crawl-worker'."
    ;;

esac
