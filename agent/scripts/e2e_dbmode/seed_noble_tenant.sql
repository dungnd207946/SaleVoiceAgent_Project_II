-- seed_noble_tenant.sql — provision tenant "noble" trong sim control-plane LOCAL.
-- noble đã có KB data (tenant_data.*) + published config v1, nhưng THIẾU trong
-- control.tenants/agent_keys → gateway auth fail. File này bù nốt.
-- Idempotent. CHỈ áp vào sim LOCAL sp-e-postgres (KHÔNG áp vào Aurora/thbc).
-- Chạy: docker exec -i sp-e-postgres psql -U sp_admin -d odyssey < seed_noble_tenant.sql
--
-- API key plaintext (bearer token dùng khi gọi gateway/worker): noble_local_dev_key_2026
-- Hash = sha256 trần hex (khớp gateway PostgresCredentialRegistry.verify_bearer).
\set ON_ERROR_STOP on
\set TOKEN 'noble_local_dev_key_2026'

-- 1. tenant active
INSERT INTO control.tenants (id, lifecycle) VALUES ('noble', 'active')
  ON CONFLICT (id) DO UPDATE SET lifecycle = EXCLUDED.lifecycle;

-- 2. API key của tenant (không cấp trùng nếu đã có cùng hash).
-- MỘT khoá cho cả chat lẫn voice: `0919` bỏ `kind`, `0941` bỏ hẳn `control.deployments`.
INSERT INTO control.agent_keys (tenant_id, key_sha256)
  SELECT 'noble', encode(sha256((:'TOKEN')::bytea), 'hex')
  WHERE NOT EXISTS (
      SELECT 1 FROM control.agent_keys k
      WHERE k.tenant_id = 'noble'
        AND k.key_sha256 = encode(sha256((:'TOKEN')::bytea), 'hex')
  );

-- 3. config v1 + pointer cho noble đã tồn tại (không đụng).

-- 4. Report
\echo ''
\echo '=== tenant ==='
SELECT * FROM control.tenants WHERE id = 'noble';
\echo '=== key ==='
SELECT encode(sha256((:'TOKEN')::bytea), 'hex') AS expected_sha256;
SELECT k.id, k.tenant_id, left(k.key_sha256, 20) || '…' AS sha, (k.revoked_at IS NULL) AS active
  FROM control.agent_keys k
  WHERE k.tenant_id = 'noble';
\echo '=== published config (đọc qua view như agent, set app.tenant_id=noble) ==='
SELECT set_config('app.tenant_id', 'noble', false);
SELECT set_config('app.current_tenant', 'noble', false);
SELECT tenant_id, version, config->'identity'->>'brand' AS brand,
       config->'identity'->>'agent_name' AS agent_name
  FROM agent_published_config;
\echo '=== agent_api views thấy noble ==='
SELECT * FROM agent_api.tenant_status;
SELECT tenant_id, left(key_sha256,20)||'…' AS sha, active FROM agent_api.tenant_keys;
