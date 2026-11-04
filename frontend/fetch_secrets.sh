#!/usr/bin/env bash
# Lấy env của service này từ GitLab CI/CD Variables, ghi ra file docker compose đọc.
#
#   ./fetch_secrets.sh                    # môi trường dev
#   ODYSSEY_ENV=prod ./fetch_secrets.sh   # môi trường prod
#
# ĐỔI 2026-08-19: nguồn secret chuyển từ AWS Secrets Manager → GitLab CI/CD Variables
# (Settings → CI/CD → Variables). Không còn gọi `aws secretsmanager get-secret-value`,
# nên máy deploy KHÔNG cần `aws` cli và instance role KHÔNG cần `GetSecretValue`.
#
# Biến GitLab được đọc (component `frontend-env`), theo thứ tự ưu tiên:
#   1. ODYSSEY_SECRET_DEV_FRONTEND_ENV / ODYSSEY_SECRET_PROD_FRONTEND_ENV
#   2. ODYSSEY_SECRET_FRONTEND_ENV     ← dùng "Environment scope" dev/prod của GitLab
# Cách (2) là cách khuyến nghị: job deploy đã khai `environment: name: dev|prod` nên
# GitLab tự chọn đúng giá trị theo scope, tên biến giữ nguyên một. Đổi tiền tố
# `ODYSSEY_SECRET` bằng biến `SECRET_VAR_PREFIX` nếu cần.
#
# Nội dung biến chấp nhận HAI dạng, tự nhận diện:
#   a) JSON phẳng một tầng  {"KEY":"VALUE",...}  ← y hệt định dạng secret cũ trên
#      Secrets Manager, nên migrate = copy nguyên giá trị cũ dán vào GitLab.
#   b) dotenv               KEY=VALUE mỗi dòng   ← tự nhiên hơn khi gõ tay trên UI.
# Biến kiểu "File" của GitLab cũng dùng được: khi đó biến chứa ĐƯỜNG DẪN, script tự
# đọc nội dung file đó.
#
# ⚠️ GitLab chỉ "mask" được giá trị MỘT DÒNG, không khoảng trắng — cả JSON lẫn dotenv
# nhiều dòng đều KHÔNG mask được. Hãy bật "Protected" (chỉ nhánh protected đọc được)
# và đừng bao giờ `echo` giá trị ra log. Script này chỉ in TÊN biến, không in giá trị.
#
# Repo này ghi ra `.env` ở gốc — compose của frontend không dùng `env_file`, nó nội
# suy `${ODYSSEY_PORTAL_API_UPSTREAM}` / `${PORTAL_FE_PORT}` và compose tự đọc `.env`
# trong thư mục project. `IMAGE_TAG` KHÔNG nằm trong secret: nó là tag của commit,
# export ở shell trước khi `docker compose pull` (xem deploy/README.md).
#
# ── CŨ (AWS Secrets Manager) — giữ lại để tham chiếu, KHÔNG còn hiệu lực ────────────
# # Chạy TRÊN EC2 của workload: credential đến từ instance role, không cần access key.
# # Instance role chỉ được GetSecretValue trên đúng 4 secret của odyssey.
# ───────────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ⚠ ĐỪNG bật `set -x` trong file này — mọi giá trị secret sẽ nằm trong log CI/journal.

# ── CŨ ──
# AWS_REGION="${AWS_REGION:-ap-southeast-1}"
# ODYSSEY_ENV="${ODYSSEY_ENV:-dev}"
# PREFIX="${SECRET_PREFIX:-noblex-${ODYSSEY_ENV}-odyssey-secrets}"
# ── MỚI ──
ODYSSEY_ENV="${ODYSSEY_ENV:-dev}"
VAR_PREFIX="${SECRET_VAR_PREFIX:-ODYSSEY_SECRET}"

cd "$(dirname "$0")"

# ── CŨ: cần `aws` để gọi Secrets Manager ──
# for cmd in aws jq; do
#   command -v "$cmd" >/dev/null || {
#     echo "fetch_secrets: thiếu '$cmd' trên máy này" >&2
#     exit 1
#   }
# done
# ── MỚI: không cần `aws` nữa. `jq` chỉ cần khi giá trị biến ở dạng JSON — nhánh
#    dotenv không đụng tới nó, nên kiểm tra được dời vào trong `render`.

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

# ── CŨ: render đọc từ AWS Secrets Manager ──────────────────────────────────────────
# render() { # render <secret-component> <output-file>
#   local component="$1" out="$2" name json tmp empty
#   name="$PREFIX-$component"
#
#   json="$(aws secretsmanager get-secret-value \
#     --secret-id "$name" --region "$AWS_REGION" \
#     --query SecretString --output text)"
#
#   # Giá trị nhiều dòng làm hỏng file env (compose đọc từng dòng KEY=VALUE) → dừng,
#   # thay vì ghi ra một file sai một cách âm thầm.
#   if jq -e 'to_entries[] | select((.value|tostring) | test("\n"))' >/dev/null <<<"$json"; then
#     echo "fetch_secrets: $name có giá trị chứa newline, env_file không đọc được" >&2
#     exit 1
#   fi
#
#   # Ghi qua file tạm rồi mv: không để lại file nửa vời nếu lệnh chết giữa đường.
#   tmp="$(mktemp)"
#   chmod 600 "$tmp"
#   {
#     echo "# Sinh bởi fetch_secrets.sh từ secret $name — KHÔNG commit, KHÔNG sửa tay."
#     jq -r 'to_entries | sort_by(.key)[] | "\(.key)=\(.value)"' <<<"$json"
#   } >"$tmp"
#   mv "$tmp" "$out"
#   chmod 600 "$out"
#
#   # Chỉ in TÊN biến rỗng, không in giá trị. Rỗng có thể là cố ý (S3/MinIO dùng
#   # instance role) hoặc là chưa điền trên Console — người chạy tự đối chiếu.
#   echo "$out: $(grep -cve '^#' "$out") biến"
#   empty="$(jq -r 'to_entries | map(select(.value == "")) | map(.key) | join(", ")' <<<"$json")"
#   [ -z "$empty" ] || echo "  rỗng: $empty"
# }
# ── MỚI: render đọc từ GitLab CI/CD Variables ──────────────────────────────────────
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
      echo "fetch_secrets: $var có giá trị chứa newline, env_file không đọc được" >&2
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

  # Chỉ in TÊN biến rỗng, không in giá trị. Rỗng có thể là cố ý (S3/MinIO dùng
  # instance role) hoặc là chưa điền trên GitLab — người chạy tự đối chiếu.
  echo "$out: $(grep -cve '^#' "$out") biến  (nguồn: \$$var)"
  [ -z "${empty// /}" ] || echo "  rỗng: $empty"
}

render frontend-env .env
