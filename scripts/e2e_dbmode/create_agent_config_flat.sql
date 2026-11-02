-- create_agent_config_flat.sql — bảng phẳng tenant_data.agent_config (migration
-- 0910_agent_config, docs/handoff/agent-config-bang-phang.md). Code hiện tại
-- (storage/agent_config_store.py) ĐỌC bảng này, KHÔNG còn agent_published_config.
-- Sim local trước đây thiếu → db-mode config load rơi về last-good cache. File này bù.
-- Idempotent. CHỈ áp vào sim LOCAL sp-e-postgres.
-- Chạy: docker exec -i sp-e-postgres psql -U sp_admin -d odyssey < create_agent_config_flat.sql
\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS tenant_data.agent_config (
    id               bigserial PRIMARY KEY,
    tenant_id        text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    name             text NOT NULL CHECK (name <> ''),
    brand_name       text NOT NULL CHECK (brand_name <> ''),
    self_pronoun     text NOT NULL DEFAULT '',
    customer_pronoun text NOT NULL DEFAULT '',
    greeting         text NOT NULL DEFAULT '',
    scope_does       text NOT NULL DEFAULT '',
    scope_does_not   text NOT NULL DEFAULT '',
    refusal_line     text NOT NULL DEFAULT '',
    departments      jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(departments) = 'array'),
    tone             text NOT NULL CHECK (tone IN ('lich_su', 'than_thien', 'ngan_gon')),
    reply_length     text NOT NULL CHECK (reply_length IN ('ngan', 'trung_binh', 'chi_tiet')),
    skills           jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(skills) = 'array'),
    version          integer NOT NULL CHECK (version > 0),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_config_tenant_key UNIQUE (tenant_id)
);
CREATE INDEX IF NOT EXISTS agent_config_skills_idx ON tenant_data.agent_config USING gin (skills);

-- Doc: bảng KHÔNG RLS (agent tự lọc WHERE tenant_id). Runtime role chỉ cần SELECT.
GRANT SELECT ON tenant_data.agent_config TO odyssey_agent;

-- SEED noble (An Phú Land) + acme (Acme Land) — 1 row/tenant.
INSERT INTO tenant_data.agent_config
  (tenant_id, name, brand_name, self_pronoun, customer_pronoun, greeting,
   scope_does, scope_does_not, refusal_line, departments, tone, reply_length, skills, version)
VALUES
  ('noble', 'Luna', 'An Phú Land', 'em', 'anh/chị',
   'Dạ em Luna bên An Phú Land nghe ạ.',
   'Tư vấn dự án bất động sản và đặt lịch tham quan.',
   'Hậu mãi (hợp đồng/thanh toán/sổ hồng/bảo hành) và giá riêng — chuyển người thật.',
   'Dạ việc này em xin phép chuyển anh/chị tới bộ phận phụ trách ạ.',
   '[{"ten":"CSKH","khi_nao":"khách hỏi hợp đồng đã ký, thanh toán, sổ hồng, bảo hành"},{"ten":"Kinh doanh","khi_nao":"khách hỏi giá riêng"}]'::jsonb,
   'than_thien', 'trung_binh',
   '["find_project","discover_projects","get_project_overview","search_units","recommend_units","kb_search","send_media","booking","update_customer","escalate"]'::jsonb,
   1),
  ('acme', 'Acme Bot', 'Acme Land', 'em', 'anh/chị',
   'Dạ em Acme Bot bên Acme Land nghe ạ.',
   'Tư vấn dự án và đặt lịch tham quan.',
   'Hậu mãi và giá riêng — chuyển người thật.',
   'Dạ việc này em xin phép chuyển tới bộ phận phụ trách ạ.',
   '[{"ten":"CSKH","khi_nao":"khách hỏi hợp đồng đã ký"}]'::jsonb,
   'than_thien', 'trung_binh',
   '["find_project","discover_projects","get_project_overview","search_units","recommend_units","kb_search","send_media","escalate"]'::jsonb,
   1)
ON CONFLICT (tenant_id) DO UPDATE SET
  name=EXCLUDED.name, brand_name=EXCLUDED.brand_name, self_pronoun=EXCLUDED.self_pronoun,
  customer_pronoun=EXCLUDED.customer_pronoun, greeting=EXCLUDED.greeting,
  scope_does=EXCLUDED.scope_does, scope_does_not=EXCLUDED.scope_does_not,
  refusal_line=EXCLUDED.refusal_line, departments=EXCLUDED.departments,
  tone=EXCLUDED.tone, reply_length=EXCLUDED.reply_length, skills=EXCLUDED.skills,
  version=EXCLUDED.version, updated_at=now();

\echo ''
\echo '=== tenant_data.agent_config ==='
SELECT tenant_id, name, brand_name, tone, reply_length, version,
       jsonb_array_length(departments) AS n_dept, jsonb_array_length(skills) AS n_skill
  FROM tenant_data.agent_config ORDER BY tenant_id;
