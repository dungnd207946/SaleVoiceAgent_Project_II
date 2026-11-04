-- SP1 KB data plane (real_estate). Applied by `noble-tenant pg-apply-schema` (admin DSN).
-- Shared schema + per-row tenant isolation via RLS. Idempotent. Mirrors odyssey_data_plane.sql
-- RLS shape: tenant_isolation (current_user, Portal) + agent_runtime (app.current_tenant, runtime).
CREATE SCHEMA IF NOT EXISTS tenant_data;

CREATE TABLE IF NOT EXISTS tenant_data.projects (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id            text        NOT NULL,
    project_code         text        NOT NULL,
    name                 text        NOT NULL DEFAULT '',
    category             text[]      NOT NULL DEFAULT '{}',
    region               text,
    address              text,
    investor             text,
    developer            text,
    total_land_area_m2   numeric,
    floor_area_m2        numeric,
    build_density_pct    numeric,
    product_scale        text,
    amenities            text,
    ownership_form       text,
    handover_standard    text,
    total_investment_vnd bigint,
    sale_phase           text,
    overview             text,
    cover_media_id       bigint,   -- soft ref to media.id (no hard FK: media<->project cycle)
    map_media_id         bigint,   -- soft ref to media.id
    link_360             text,
    status               text        NOT NULL DEFAULT 'draft',
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_code)
);
CREATE INDEX IF NOT EXISTS projects_tenant_status_idx ON tenant_data.projects (tenant_id, status);

CREATE TABLE IF NOT EXISTS tenant_data.zones (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     text        NOT NULL,
    project_code  text        NOT NULL,
    zone_code     text        NOT NULL,
    name          text        NOT NULL DEFAULT '',
    category      text,
    product_scale text,
    overview      text,
    cover_media_id bigint,
    map_media_id   bigint,
    status        text        NOT NULL DEFAULT 'draft',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_code, zone_code),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS zones_tenant_project_idx ON tenant_data.zones (tenant_id, project_code);

CREATE TABLE IF NOT EXISTS tenant_data.units (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         text        NOT NULL,
    project_code      text        NOT NULL,
    zone_code         text,
    unit_code         text        NOT NULL DEFAULT '',
    product_type      text,
    bedrooms          smallint,
    block             text,
    floor             smallint,
    num_floors        smallint,
    direction         text,
    area_built_m2     numeric,
    area_wall_m2      numeric,
    area_land_m2      numeric,
    price_vnd         numeric,
    price_per_m2_vnd  numeric,
    sale_status       text        NOT NULL DEFAULT 'available',
    image_url         text,
    status            text        NOT NULL DEFAULT 'draft',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS units_tenant_project_idx ON tenant_data.units (tenant_id, project_code);
CREATE INDEX IF NOT EXISTS units_tenant_project_code_idx ON tenant_data.units (tenant_id, project_code, unit_code);

CREATE TABLE IF NOT EXISTS tenant_data.documents (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    text        NOT NULL,
    project_code text        NOT NULL,
    title        text        NOT NULL DEFAULT '',
    body         text        NOT NULL DEFAULT '',
    file_url     text,
    status       text        NOT NULL DEFAULT 'draft',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS documents_tenant_project_idx ON tenant_data.documents (tenant_id, project_code);

CREATE TABLE IF NOT EXISTS tenant_data.media (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    text        NOT NULL,
    project_code text        NOT NULL,
    zone_code    text,
    unit_code    text,
    content_type text        NOT NULL DEFAULT 'image',
    category     text,
    caption      text,
    media_url    text        NOT NULL DEFAULT '',
    thumb_url    text,
    content_hash text,
    uploaded_by  text,
    status       text        NOT NULL DEFAULT 'draft',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, project_code)
        REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS media_tenant_project_cat_idx ON tenant_data.media (tenant_id, project_code, category);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['projects','zones','units','documents','media'] LOOP
        EXECUTE format('ALTER TABLE tenant_data.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE tenant_data.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON tenant_data.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON tenant_data.%I '
            'USING (tenant_id = current_user) WITH CHECK (tenant_id = current_user)', t);
        EXECUTE format('DROP POLICY IF EXISTS agent_runtime ON tenant_data.%I', t);
        EXECUTE format(
            'CREATE POLICY agent_runtime ON tenant_data.%I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))', t);
    END LOOP;
END $$;

-- ── analyze_projects views (spec 2026-08-26) ────────────────────────────────
-- Bề mặt đọc DUY NHẤT của tool analyze_projects (SQL do LLM sinh). Lọc sẵn
-- status='published' (cả units lẫn project cha) và KHÔNG expose tenant_id/
-- status/created_at/media id/overview. Definer semantics (KHÔNG security_invoker
-- — invoker sẽ bắt role truy vấn có SELECT trên bảng gốc, phá cô lập); owner =
-- agent_kb_view_owner (NOBYPASSRLS, set ở pg-ensure-sql-ro) nên FORCE RLS +
-- policy agent_runtime theo GUC app.current_tenant vẫn siết tenant như thường.
-- CREATE OR REPLACE giữ nguyên owner/grants khi pg-apply-schema chạy lại.
CREATE OR REPLACE VIEW tenant_data.agent_projects_v AS
SELECT project_code, name, region, address, investor, developer,
       category, sale_phase, ownership_form, total_land_area_m2
FROM tenant_data.projects
WHERE status = 'published';

CREATE OR REPLACE VIEW tenant_data.agent_units_v AS
SELECT u.project_code, p.name AS project_name, u.zone_code, u.unit_code,
       u.product_type, u.bedrooms, u.block, u.floor, u.direction,
       u.area_built_m2, u.area_land_m2, u.price_vnd, u.price_per_m2_vnd,
       u.sale_status
FROM tenant_data.units u
JOIN tenant_data.projects p USING (tenant_id, project_code)
WHERE u.status = 'published' AND p.status = 'published';
