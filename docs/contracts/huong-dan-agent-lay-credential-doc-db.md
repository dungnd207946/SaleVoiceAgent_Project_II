# Lấy credential

```http
POST /api/v1/agent/runtime-credentials HTTP/1.1
Host: localhost
Authorization: Bearer key_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Response `200`:

```jsonc
{
  "tenant_id": "anphu",
  "deployment_id": 12,
  "kind": "chat",

  "postgres_role":     "agent_anphu",
  "postgres_password": "<mật khẩu>",

  "storage": { "endpoint": "...", "bucket": "...", "access_key": "...", "secret_key": "...", "prefix": "tenants/anphu/" },
  "kb": { "url": "...", "collection": "kb_anphu" },

  "expires_at": "2026-08-10T09:00:00Z"
}
```
