-- portal_sim.sql — MÔ PHỎNG mặt Portal control-plane mà agent ĐỌC trong db-mode
-- (AGENT_CONFIG_SOURCE=db), đúng docs/handoff/agent-postgres-read-contract.md.
-- Idempotent. CHỈ áp vào sim LOCAL sp-e-postgres (KHÔNG áp vào thbc shared 5433).
--
-- ⚠️ FILE NÀY CÒN MÔ PHỎNG MỘT PHẦN LƯỢC ĐỒ ĐÃ LỖI THỜI. Mục 2 dựng schema `agent_api`,
-- mà Portal `0917` (2026-08-10) đã `DROP SCHEMA agent_api` — agent thật đọc thẳng
-- `tenant_data.*`, cách ly dựa vào RLS FORCE. Phần đó chưa viết lại vì nó đòi chốt lại
-- sim này còn mô phỏng cái gì; giữ nguyên để không phá luồng e2e đang dùng.
-- Phần `control.deployments` THÌ ĐÃ dọn theo `0940`/`0941` (bảng bỏ hẳn).
-- Chạy: docker exec -i sp-e-postgres psql -U sp_admin -d odyssey < portal_sim.sql
\set ON_ERROR_STOP on

-- 0. portal.current_tenant(): suy tenant từ GUC app.tenant_id mà
--    storage/postgres_client.tenant_conn set mỗi transaction.
CREATE SCHEMA IF NOT EXISTS portal;
CREATE OR REPLACE FUNCTION portal.current_tenant() RETURNS text
  LANGUAGE sql STABLE AS $$ SELECT current_setting('app.tenant_id', true) $$;

-- 1. control.* (Portal sở hữu ở prod).
CREATE SCHEMA IF NOT EXISTS control;

CREATE TABLE IF NOT EXISTS control.tenants (
  id        text PRIMARY KEY,
  lifecycle text NOT NULL DEFAULT 'active'
);

-- control.deployments ĐÃ BỎ (Portal 0941). Khoá treo thẳng vào tenant (0940), nhịp tim
-- khoá theo tenant_id.
CREATE TABLE IF NOT EXISTS control.agent_keys (
  id         bigserial PRIMARY KEY,
  tenant_id  text NOT NULL REFERENCES control.tenants(id),
  key_sha256 text NOT NULL,
  revoked_at timestamptz
);

CREATE TABLE IF NOT EXISTS control.agent_heartbeats (
  tenant_id       text NOT NULL,
  running_version int,
  bundle_sha      text,
  agent_version   text,
  last_error      text,
  last_seen_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id)
);

-- Agent ghi heartbeat bằng role dùng chung odyssey_agent, scope theo app.tenant_id.
ALTER TABLE control.agent_heartbeats ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS agent_runtime ON control.agent_heartbeats;
CREATE POLICY agent_runtime ON control.agent_heartbeats
  USING      (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- 2. agent_api.* view đọc (owner sp_admin ở sim; prod = portal_api). Mỗi view lọc
--    theo portal.current_tenant() → cách ly tenant.
CREATE SCHEMA IF NOT EXISTS agent_api;

CREATE OR REPLACE VIEW agent_api.tenant_status AS
  SELECT id AS tenant_id, (lifecycle = 'active') AS active
  FROM control.tenants
  WHERE id = portal.current_tenant();

-- `0940`: khoá treo thẳng vào tenant, không còn JOIN qua deployments.
CREATE OR REPLACE VIEW agent_api.tenant_keys AS
  SELECT k.tenant_id, k.key_sha256, (k.revoked_at IS NULL) AS active
  FROM control.agent_keys k
  WHERE k.tenant_id = portal.current_tenant();

-- `agent_api.deployments` BỎ cùng bảng nguồn (`0941`). Agent không cần id nào để ghi
-- nhịp tim nữa — `tenant_id` là khoá.

-- 3. GRANT cho role runtime dùng chung.
GRANT USAGE ON SCHEMA portal, agent_api, control TO odyssey_agent;
GRANT EXECUTE ON FUNCTION portal.current_tenant() TO odyssey_agent;
GRANT SELECT ON agent_api.tenant_status, agent_api.tenant_keys TO odyssey_agent;
GRANT SELECT, INSERT, UPDATE ON control.agent_heartbeats TO odyssey_agent;

-- 4. SEED: Portal "tạo" tenant acme → publish config v1 → phát 1 key.
--    (KB của acme đã có sẵn trong tenant_data: 41 dự án/603 căn.)
INSERT INTO control.tenants (id, lifecycle) VALUES ('acme', 'active')
  ON CONFLICT (id) DO UPDATE SET lifecycle = EXCLUDED.lifecycle;

-- token plaintext = 'acme_secret_token_123' (sha256 trần, không salt — khớp gateway).
-- MỘT khoá cho cả chat lẫn voice — `0919` bỏ `kind`, một khoá mở cả hai kênh.
INSERT INTO control.agent_keys (tenant_id, key_sha256)
  SELECT 'acme', encode(sha256('acme_secret_token_123'::bytea), 'hex')
  WHERE NOT EXISTS (
      SELECT 1 FROM control.agent_keys k
      WHERE k.tenant_id = 'acme'
        AND k.key_sha256 = encode(sha256('acme_secret_token_123'::bytea), 'hex')
  );

-- config v1 cho acme = clone của noble, đổi brand/agent_name để thấy rõ per-tenant.
-- (sp_admin superuser → bypass RLS FORCE nên đọc noble + ghi acme trong 1 session OK.)
DELETE FROM agent_config_pointer  WHERE tenant_id = 'acme';
DELETE FROM agent_config_versions WHERE tenant_id = 'acme';
INSERT INTO agent_config_versions (tenant_id, version, status, config)
  SELECT 'acme', 1, 'published',
         jsonb_set(jsonb_set(config, '{identity,brand}', '"Acme Land"'),
                   '{identity,agent_name}', '"Acme Bot"')
  FROM agent_config_versions WHERE tenant_id = 'noble' AND version = 1;
INSERT INTO agent_config_pointer (tenant_id, published_version) VALUES ('acme', 1);

-- 5. Report
\echo ''
\echo '=== tenant ==='
SELECT * FROM control.tenants WHERE id = 'acme';
\echo '=== key (sha256 mong đợi của acme_secret_token_123) ==='
SELECT encode(sha256('acme_secret_token_123'::bytea), 'hex') AS expected_sha256;
SELECT tenant_id, left(key_sha256, 20) || '...' AS key_sha256, revoked_at IS NULL AS active
  FROM control.agent_keys
  WHERE tenant_id = 'acme';
\echo '=== published config ==='
SELECT tenant_id, version,
       config->'identity'->>'brand'      AS brand,
       config->'identity'->>'agent_name' AS agent_name
  FROM agent_config_versions WHERE tenant_id = 'acme';
