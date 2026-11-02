# source this before launching worker/gateway for the db-mode E2E test.
# Exported shell env OVERRIDES .env (pydantic-settings) — your .env stays untouched.
export AGENT_CONFIG_SOURCE=db          # <- the switch: read Postgres control-plane, not MinIO
export POSTGRES_ENABLED=true
export POSTGRES_DSN=postgresql://odyssey_agent:odyssey_agent_pw@localhost:5432/odyssey   # local sim (has control.*/agent_api.*)
export POSTGRES_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey
export TENANT_STORE_ENABLED=false      # prove MinIO is NOT on the serving path
# gateway-only (harmless for the worker). Single-domain auth: tenant comes from the
# Bearer API key via this API, not from the Host header. Empty ⇒ WS closed 4001.
export GATEWAY_CREDENTIALS_API_URL=${GATEWAY_CREDENTIALS_API_URL:-}
export WORKER_CHAT_INTERNAL_URL_TEMPLATE=ws://127.0.0.1:8766/chat
