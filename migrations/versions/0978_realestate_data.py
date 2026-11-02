"""Thêm trường mua nhà hay hỏi: cột mới cho projects/zones/units, bảng buildings, bàn giao thành danh sách.

- `projects.handover_standard` đổi text → jsonb (mảng hạng mục `{item, material, brand, origin, note}`);
  nội dung cũ thành một hạng mục «Tiêu chuẩn chung», chuỗi rỗng thành NULL.
- `buildings` khởi tạo từ `units.block`; `zone_code` chỉ điền khi cả block thuộc một phân khu.
  Trigger trên `units` tự thêm toà khi gặp block mới (nhập tay hay qua cổng nạp).
- Hai view của agent chỉ THÊM cột ở cuối.

Revision ID: 0978_realestate_data
Revises: 0977_jobs_heartbeat
"""

from alembic import op

revision = "0978_realestate_data"
down_revision = "0977_jobs_heartbeat"
branch_labels = None
depends_on = None

DIRECTIONS = ("dong", "tay", "nam", "bac", "dong_bac", "dong_nam", "tay_bac", "tay_nam")
SALE_PHASES = ("sap_mo_ban", "dang_ban", "ban_giao", "dong_gio_hang")
UNIT_VIEWS = (
    "song",
    "ho",
    "bien",
    "cong_vien",
    "san_golf",
    "noi_khu",
    "be_boi",
    "duong",
    "thanh_pho",
    "toa_doi_dien",
)
HANDOVER_CONDITIONS = ("tho", "co_ban", "hoan_thien", "full_noi_that")


def _list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_data.projects
          ADD COLUMN total_units integer CHECK (total_units >= 0),
          ADD COLUMN num_buildings smallint CHECK (num_buildings >= 0),
          ADD COLUMN management_fee_vnd_m2 numeric CHECK (management_fee_vnd_m2 >= 0),
          ADD COLUMN parking_car_fee_vnd numeric CHECK (parking_car_fee_vnd >= 0),
          ADD COLUMN parking_moto_fee_vnd numeric CHECK (parking_moto_fee_vnd >= 0)
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_data.projects
          ALTER COLUMN handover_standard DROP DEFAULT,
          ALTER COLUMN handover_standard DROP NOT NULL,
          ALTER COLUMN handover_standard TYPE jsonb USING
            CASE WHEN nullif(btrim(handover_standard), '') IS NULL THEN NULL
                 ELSE jsonb_build_array(jsonb_build_object('item', 'Tiêu chuẩn chung', 'note', handover_standard))
            END,
          ADD CONSTRAINT projects_handover_standard_mang
            CHECK (handover_standard IS NULL OR jsonb_typeof(handover_standard) = 'array')
        """
    )

    op.execute(
        f"""
        ALTER TABLE tenant_data.zones
          ADD COLUMN sale_phase text CHECK (sale_phase IS NULL OR sale_phase IN ({_list(SALE_PHASES)})),
          ADD COLUMN note text NOT NULL DEFAULT '',
          ADD COLUMN amenities text NOT NULL DEFAULT '',
          ADD COLUMN num_buildings smallint CHECK (num_buildings >= 0),
          ADD COLUMN total_units integer CHECK (total_units >= 0)
        """
    )

    # SET NULL theo MỘT cột: dạng không kèm cột đặt NULL cả tenant_id và nổ NOT NULL.
    op.execute(
        f"""
        ALTER TABLE tenant_data.units
          ADD COLUMN views text[] NOT NULL DEFAULT '{{}}' CHECK (views <@ ARRAY[{_list(UNIT_VIEWS)}]),
          ADD COLUMN is_corner boolean,
          ADD COLUMN open_sides smallint CHECK (open_sides BETWEEN 1 AND 4),
          ADD COLUMN bathrooms smallint CHECK (bathrooms >= 0),
          ADD COLUMN handover_condition text
            CHECK (handover_condition IS NULL OR handover_condition IN ({_list(HANDOVER_CONDITIONS)})),
          ADD COLUMN layout_media_id bigint,
          ADD COLUMN hr_balcony_m2 numeric CHECK (hr_balcony_m2 >= 0),
          ADD COLUMN hr_loggia_m2 numeric CHECK (hr_loggia_m2 >= 0),
          ADD COLUMN lr_frontage_m numeric CHECK (lr_frontage_m >= 0),
          ADD COLUMN lr_depth_m numeric CHECK (lr_depth_m >= 0),
          ADD COLUMN lr_road_width_m numeric CHECK (lr_road_width_m >= 0),
          ADD CONSTRAINT units_layout_media_fk FOREIGN KEY (tenant_id, layout_media_id)
            REFERENCES tenant_data.media (tenant_id, id) ON DELETE SET NULL (layout_media_id)
        """
    )

    op.execute(
        f"""
        CREATE TABLE tenant_data.buildings (
          id bigserial PRIMARY KEY,
          tenant_id text NOT NULL REFERENCES control.tenants (id) ON DELETE CASCADE,
          project_code text NOT NULL,
          zone_code text,
          building_code text NOT NULL CHECK (building_code <> ''),
          name text NOT NULL DEFAULT '',
          num_floors smallint CHECK (num_floors >= 0),
          num_basements smallint CHECK (num_basements >= 0),
          units_per_floor smallint CHECK (units_per_floor >= 0),
          elevators_passenger smallint CHECK (elevators_passenger >= 0),
          elevators_service smallint CHECK (elevators_service >= 0),
          car_slots integer CHECK (car_slots >= 0),
          moto_slots integer CHECK (moto_slots >= 0),
          ceiling_height_m numeric CHECK (ceiling_height_m > 0),
          facing text CHECK (facing IS NULL OR facing IN ({_list(DIRECTIONS)})),
          sale_phase text CHECK (sale_phase IS NULL OR sale_phase IN ({_list(SALE_PHASES)})),
          amenities text NOT NULL DEFAULT '',
          overview text NOT NULL DEFAULT '',
          status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
          external_id text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT buildings_tenant_project_code_key UNIQUE (tenant_id, project_code, building_code),
          CONSTRAINT buildings_tenant_external_id_key UNIQUE (tenant_id, external_id),
          CONSTRAINT buildings_tenant_project_fk FOREIGN KEY (tenant_id, project_code)
            REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE,
          CONSTRAINT buildings_tenant_zone_fk FOREIGN KEY (tenant_id, project_code, zone_code)
            REFERENCES tenant_data.zones (tenant_id, project_code, zone_code) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX buildings_zone_idx ON tenant_data.buildings (tenant_id, project_code, zone_code)")

    op.execute("ALTER TABLE tenant_data.units NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        INSERT INTO tenant_data.buildings (tenant_id, project_code, zone_code, building_code, name, status)
        SELECT tenant_id, project_code,
               CASE WHEN count(DISTINCT zone_code) = 1 AND bool_and(zone_code IS NOT NULL) THEN min(zone_code) END,
               btrim(block), btrim(block), 'published'
          FROM tenant_data.units
         WHERE nullif(btrim(block), '') IS NOT NULL
         GROUP BY tenant_id, project_code, btrim(block)
        """
    )
    op.execute("ALTER TABLE tenant_data.units FORCE ROW LEVEL SECURITY")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.buildings')")
    op.execute("GRANT SELECT ON tenant_data.buildings TO PUBLIC")

    op.execute(
        """
        CREATE FUNCTION tenant_data.units_tao_toa() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF nullif(btrim(NEW.block), '') IS NOT NULL THEN
            INSERT INTO tenant_data.buildings (tenant_id, project_code, zone_code, building_code, name, status)
            VALUES (NEW.tenant_id, NEW.project_code, NEW.zone_code, btrim(NEW.block), btrim(NEW.block), 'published')
            ON CONFLICT (tenant_id, project_code, building_code) DO NOTHING;
          END IF;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER units_tao_toa AFTER INSERT OR UPDATE OF block ON tenant_data.units
          FOR EACH ROW EXECUTE FUNCTION tenant_data.units_tao_toa()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW tenant_data.agent_projects_v AS
        SELECT project_code, name, region, address, investor, developer,
               category, sale_phase, ownership_form, total_land_area_m2,
               total_units, num_buildings, management_fee_vnd_m2, parking_car_fee_vnd, parking_moto_fee_vnd
        FROM tenant_data.projects
        WHERE status = 'published'
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW tenant_data.agent_units_v AS
        SELECT u.project_code, p.name AS project_name, u.zone_code, u.unit_code,
               u.product_type, u.bedrooms, u.block, u.floor, u.direction,
               u.area_built_m2, u.area_land_m2, u.price_vnd, u.price_per_m2_vnd,
               u.sale_status,
               u.views, u.is_corner, u.open_sides, u.bathrooms, u.handover_condition,
               u.hr_balcony_m2, u.hr_loggia_m2, u.lr_frontage_m, u.lr_depth_m, u.lr_road_width_m
        FROM tenant_data.units u
        JOIN tenant_data.projects p USING (tenant_id, project_code)
        WHERE u.status = 'published' AND p.status = 'published'
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW tenant_data.agent_units_v")
    op.execute("DROP VIEW tenant_data.agent_projects_v")
    op.execute(
        """
        CREATE VIEW tenant_data.agent_projects_v AS
        SELECT project_code, name, region, address, investor, developer,
               category, sale_phase, ownership_form, total_land_area_m2
        FROM tenant_data.projects
        WHERE status = 'published'
        """
    )
    op.execute(
        """
        CREATE VIEW tenant_data.agent_units_v AS
        SELECT u.project_code, p.name AS project_name, u.zone_code, u.unit_code,
               u.product_type, u.bedrooms, u.block, u.floor, u.direction,
               u.area_built_m2, u.area_land_m2, u.price_vnd, u.price_per_m2_vnd,
               u.sale_status
        FROM tenant_data.units u
        JOIN tenant_data.projects p USING (tenant_id, project_code)
        WHERE u.status = 'published' AND p.status = 'published'
        """
    )
    op.execute("ALTER VIEW tenant_data.agent_projects_v OWNER TO agent_kb_view_owner")
    op.execute("ALTER VIEW tenant_data.agent_units_v OWNER TO agent_kb_view_owner")
    op.execute("GRANT SELECT ON tenant_data.agent_projects_v, tenant_data.agent_units_v TO agent_sql_ro")

    op.execute("DROP TRIGGER units_tao_toa ON tenant_data.units")
    op.execute("DROP FUNCTION tenant_data.units_tao_toa()")
    op.execute("DROP TABLE tenant_data.buildings")

    op.execute(
        """
        ALTER TABLE tenant_data.units
          DROP CONSTRAINT units_layout_media_fk,
          DROP COLUMN views, DROP COLUMN is_corner, DROP COLUMN open_sides, DROP COLUMN bathrooms,
          DROP COLUMN handover_condition, DROP COLUMN layout_media_id,
          DROP COLUMN hr_balcony_m2, DROP COLUMN hr_loggia_m2,
          DROP COLUMN lr_frontage_m, DROP COLUMN lr_depth_m, DROP COLUMN lr_road_width_m
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_data.zones
          DROP COLUMN sale_phase, DROP COLUMN note, DROP COLUMN amenities,
          DROP COLUMN num_buildings, DROP COLUMN total_units
        """
    )
    # Hạng mục gộp lại thành một dòng chữ; mất cấu trúc là chủ ý của downgrade.
    op.execute(
        """
        CREATE FUNCTION pg_temp.handover_text(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE AS $$
          SELECT coalesce(string_agg(concat_ws(' · ', nullif(h->>'item', 'Tiêu chuẩn chung'),
                   h->>'material', h->>'brand', h->>'origin', h->>'note'), '; '), '')
            FROM jsonb_array_elements(coalesce(v, '[]')) h
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_data.projects
          DROP CONSTRAINT projects_handover_standard_mang,
          ALTER COLUMN handover_standard TYPE text USING pg_temp.handover_text(handover_standard),
          ALTER COLUMN handover_standard SET DEFAULT '',
          ALTER COLUMN handover_standard SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_data.projects
          DROP COLUMN total_units, DROP COLUMN num_buildings, DROP COLUMN management_fee_vnd_m2,
          DROP COLUMN parking_car_fee_vnd, DROP COLUMN parking_moto_fee_vnd
        """
    )
