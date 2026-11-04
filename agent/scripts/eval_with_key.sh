#!/usr/bin/env bash
# Chạy evals quality cho MỘT tenant bằng API key (Portal) — dùng khi tenant chạy
# AGENT_CONFIG_SOURCE=db: config/agent_config nằm sau RLS, chỉ đọc được bằng PG role
# per-tenant. Script này làm đúng việc gateway làm: POST key lên runtime-credentials
# API lấy role+password, dựng POSTGRES_DSN per-tenant (host/port/db lấy từ
# POSTGRES_SERVER_DSN), rồi chạy `python -m evals run --tenant <tenant>`.
#
# Cách dùng:
#   scripts/eval_with_key.sh <API_KEY> [args cho evals run...]
#   scripts/eval_with_key.sh ody_ag_xxx --case POL-001,TOOL-001,TOOL-002,TOOL-004
#
# Credential có expires_at (~1h) — script fetch MỚI mỗi lần chạy, không cache.
set -euo pipefail
cd "$(dirname "$0")/.."

API_KEY="${1:?usage: eval_with_key.sh <API_KEY> [evals run args...]}"
shift

read -r TENANT DSN < <(API_KEY="$API_KEY" python - <<'PY'
import os
from urllib.parse import quote, urlparse

import httpx
from dotenv import dotenv_values

env = dotenv_values(".env")
resp = httpx.post(
    env["GATEWAY_CREDENTIALS_API_URL"],
    headers={"Authorization": "Bearer " + os.environ["API_KEY"]},
    timeout=10,
)
resp.raise_for_status()
cred = resp.json()
u = urlparse(env["POSTGRES_SERVER_DSN"])  # DSN không userinfo
dsn = f"postgresql://{cred['postgres_role']}:{quote(cred['postgres_password'], safe='')}@{u.hostname}:{u.port}{u.path}"
print(cred["tenant_id"], dsn)
PY
)

echo "tenant: $TENANT (credential OK, role per-tenant)"
exec env -u AGENT_CONFIG_SOURCE POSTGRES_DSN="$DSN" python -m evals run --tenant "$TENANT" "$@"
