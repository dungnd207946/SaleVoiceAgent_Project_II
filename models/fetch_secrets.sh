#!/usr/bin/env bash
# Lấy env của repo này từ GitLab CI/CD Variables, ghi ra `.env` mà compose đọc.
#
#   ./fetch_secrets.sh                    # môi trường dev
#   ODYSSEY_ENV=prod ./fetch_secrets.sh   # môi trường prod
#
# Cùng cơ chế với odyssey-agent / odyssey-portal-* (chuyển khỏi AWS Secrets Manager
# 2026-08-19): secret nằm trong GitLab CI/CD Variables, không gọi AWS, máy deploy
# không cần `aws` cli.
#
# Biến GitLab được đọc (component `models-env`), theo thứ tự ưu tiên:
#   1. ODYSSEY_SECRET_DEV_MODELS_ENV / ODYSSEY_SECRET_PROD_MODELS_ENV
#   2. ODYSSEY_SECRET_MODELS_ENV     ← dùng "Environment scope" dev/prod của GitLab
# Cách (2) là cách khuyến nghị: job deploy đã khai `environment: name: dev|prod` nên
# GitLab tự chọn đúng giá trị theo scope. Đổi tiền tố bằng biến `SECRET_VAR_PREFIX`.
#
# Nội dung biến chấp nhận HAI dạng, tự nhận diện:
#   a) JSON phẳng một tầng  {"KEY":"VALUE",...}
#   b) dotenv               KEY=VALUE mỗi dòng
# Biến kiểu "File" của GitLab cũng dùng được (biến chứa ĐƯỜNG DẪN, script tự đọc file).
#
# ⚠️ GitLab chỉ "mask" được giá trị MỘT DÒNG, không khoảng trắng — nội dung nhiều dòng
# KHÔNG mask được. Bật "Protected" và đừng echo giá trị ra log. Script chỉ in TÊN biến.
#
# Compose của repo này nội suy `${...}` từ `.env` trong thư mục project (không dùng
# `env_file:`), nên `.env` phải nằm ở GỐC repo — đúng chỗ script này ghi ra.
#
# Tối thiểu phải có trong biến: ODYSSEY_MODELS_TOKEN (xem guard cuối file).
# Nên có: HF_TOKEN (bắt buộc nếu repo HF của TTS backbone là private), và các
# EMBED_* / TTS_* muốn đè default trong docker-compose.yml.
set -euo pipefail

# ⚠ ĐỪNG bật `set -x` trong file này — mọi giá trị secret sẽ nằm trong log CI/journal.

ODYSSEY_ENV="${ODYSSEY_ENV:-dev}"
VAR_PREFIX="${SECRET_VAR_PREFIX:-ODYSSEY_SECRET}"

cd "$(dirname "$0")"

# `jq` chỉ cần khi giá trị biến ở dạng JSON — nhánh dotenv không đụng tới nó, nên
# kiểm tra nằm trong `render` chứ không phải ở đây.

upper() { printf '%s' "$1" | tr 'a-z-' 'A-Z_'; }

resolve_var() { # resolve_var <secret-component> -> in ra TÊN biến GitLab đang có giá trị
  local comp scoped plain
  comp="$(upper "$1")"
  scoped="${VAR_PREFIX}_$(upper "$ODYSSEY_ENV")_${comp}"
  plain="${VAR_PREFIX}_${comp}"
  if [ -n "${!scoped-}" ]; then
    printf '%s' "$scoped"
  elif [ -n "${!plain-}" ]; then
    printf '%s' "$plain"
  fi
}

read_var() { # read_var <TÊN biến> -> in ra NỘI DUNG secret
  local val="${!1-}"
  # Biến kiểu "File" của GitLab: giá trị là đường dẫn tới file chứa nội dung thật.
  if [ -n "$val" ] && [ -f "$val" ]; then
    cat "$val"
  else
    printf '%s' "$val"
  fi
}

render() { # render <secret-component> <output-file>
  local component="$1" out="$2" var payload head first body empty bad tmp

  var="$(resolve_var "$component")"
  if [ -z "$var" ]; then
    echo "fetch_secrets: không thấy biến GitLab cho '$component'." >&2
    echo "  Đặt ${VAR_PREFIX}_$(upper "$component") (Settings → CI/CD → Variables," >&2
    echo "  Environment scope = ${ODYSSEY_ENV}), hoặc ${VAR_PREFIX}_$(upper "$ODYSSEY_ENV")_$(upper "$component")." >&2
    exit 1
  fi

  payload="$(read_var "$var")"
  if [ -z "$payload" ]; then
    echo "fetch_secrets: biến $var rỗng" >&2
    exit 1
  fi

  # Nhận diện dạng nội dung bằng ký tự KHÔNG-khoảng-trắng đầu tiên: '{' → JSON.
  head="${payload#"${payload%%[![:space:]]*}"}"
  first="${head:0:1}"

  if [ "$first" = "{" ]; then
    command -v jq >/dev/null || {
      echo "fetch_secrets: thiếu 'jq' trên máy này (biến $var ở dạng JSON)" >&2
      exit 1
    }
    jq -e 'type == "object"' >/dev/null 2>&1 <<<"$payload" || {
      echo "fetch_secrets: $var không phải JSON object phẳng hợp lệ" >&2
      exit 1
    }
    # Giá trị nhiều dòng làm hỏng file env (compose đọc từng dòng KEY=VALUE) → dừng,
    # thay vì ghi ra một file sai một cách âm thầm.
    if jq -e 'to_entries[] | select((.value|tostring) | test("\n"))' >/dev/null <<<"$payload"; then
      echo "fetch_secrets: $var có giá trị chứa newline, compose không đọc được" >&2
      exit 1
    fi
    body="$(jq -r 'to_entries | sort_by(.key)[] | "\(.key)=\(.value)"' <<<"$payload")"
    empty="$(jq -r 'to_entries | map(select(.value == "")) | map(.key) | join(", ")' <<<"$payload")"
  else
    # Dạng dotenv: bỏ dòng trống + dòng chú thích, còn lại PHẢI là KEY=VALUE.
    body="$(grep -v -e '^[[:space:]]*$' -e '^[[:space:]]*#' <<<"$payload" || true)"
    bad="$(grep -vc '^[A-Za-z_][A-Za-z0-9_]*=' <<<"$body" || true)"
    if [ "${bad:-0}" -gt 0 ]; then
      echo "fetch_secrets: $var có $bad dòng không đúng dạng KEY=VALUE (không in nội dung)" >&2
      exit 1
    fi
    empty="$(grep -E '^[A-Za-z_][A-Za-z0-9_]*=[[:space:]]*$' <<<"$body" | cut -d= -f1 | tr '\n' ' ' || true)"
  fi

  # Ghi qua file tạm rồi mv: không để lại file nửa vời nếu lệnh chết giữa đường.
  tmp="$(mktemp)"
  chmod 600 "$tmp"
  {
    echo "# Sinh bởi fetch_secrets.sh từ biến GitLab $var — KHÔNG commit, KHÔNG sửa tay."
    printf '%s\n' "$body"
  } >"$tmp"
  mv "$tmp" "$out"
  chmod 600 "$out"

  # Chỉ in TÊN khoá, KHÔNG in giá trị. Đếm theo dòng `KEY=` thật: `grep -cve '^#'`
  # đếm cả dòng trống mà `printf` sinh ra khi payload rỗng, nên `{}` cũng báo "1 biến"
  # — đúng một con số khiến người trực nghĩ là đã ghi được biến.
  keys="$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$out" | tr -d '=' | tr '\n' ' ' || true)"
  echo "$out: $(printf '%s' "$keys" | wc -w | tr -d ' ') biến  (nguồn: \$$var)"
  [ -z "${keys// /}" ] || echo "  khoá: $keys"
  [ -z "${empty// /}" ] || echo "  rỗng: $empty"
}

render models-env .env

# Guard fail-closed. `embed/auth.py::require_token` mở cửa khi token rỗng:
#     def dependency(...):
#         if not token:
#             return        ← KHÔNG kiểm gì cả
# mà cả 4 service đều bind 0.0.0.0 (LAN-visible, xem README §Run). Nên token rỗng
# không phải "chưa cấu hình" — nó là embed/stt/speaker/tts mở toang cho cả mạng nội
# bộ, và không có dòng log nào báo động ngoài chữ `auth=off` lúc khởi động.
grep -q '^ODYSSEY_MODELS_TOKEN=.\+' .env || {
  echo "fetch_secrets: LỖI — ODYSSEY_MODELS_TOKEN rỗng/thiếu trong .env." >&2
  echo "  Token rỗng = TẮT xác thực trên cả 4 service đang nghe 0.0.0.0. Từ chối deploy." >&2
  exit 1
}
