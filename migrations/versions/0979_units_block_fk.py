"""Căn trỏ toà bằng khoá ngoại: `units (tenant_id, project_code, block)` → `buildings`.

- `block` chuẩn hoá (cắt khoảng trắng, chuỗi rỗng thành NULL); block chưa có toà thì thêm toà như `0978`.
- Trigger `units_tao_toa` chuyển sang BEFORE: chuẩn hoá `block` và thêm toà trước khi ghi hàng — bản AFTER
  của `0978` chạy sau phép kiểm khoá ngoại nên căn mang mã toà mới sẽ bị từ chối.
- Xoá toà còn căn bị chặn; xoá phân khu hay dự án vẫn kéo theo cả toà lẫn căn trong cùng câu lệnh.

Revision ID: 0979_units_block_fk
Revises: 0978_realestate_data
"""

from alembic import op

revision = "0979_units_block_fk"
down_revision = "0978_realestate_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.units NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_data.buildings NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE tenant_data.units SET block = nullif(btrim(block), '') "
        "WHERE block IS DISTINCT FROM nullif(btrim(block), '')"
    )
    op.execute(
        """
        INSERT INTO tenant_data.buildings (tenant_id, project_code, zone_code, building_code, name, status)
        SELECT tenant_id, project_code,
               CASE WHEN count(DISTINCT zone_code) = 1 AND bool_and(zone_code IS NOT NULL) THEN min(zone_code) END,
               block, block, 'published'
          FROM tenant_data.units
         WHERE block IS NOT NULL
         GROUP BY tenant_id, project_code, block
        ON CONFLICT (tenant_id, project_code, building_code) DO NOTHING
        """
    )
    op.execute("ALTER TABLE tenant_data.buildings FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_data.units FORCE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER units_tao_toa ON tenant_data.units")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tenant_data.units_tao_toa() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          NEW.block := nullif(btrim(NEW.block), '');
          IF NEW.block IS NOT NULL THEN
            INSERT INTO tenant_data.buildings (tenant_id, project_code, zone_code, building_code, name, status)
            VALUES (NEW.tenant_id, NEW.project_code, NEW.zone_code, NEW.block, NEW.block, 'published')
            ON CONFLICT (tenant_id, project_code, building_code) DO NOTHING;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER units_tao_toa BEFORE INSERT OR UPDATE OF block ON tenant_data.units
          FOR EACH ROW EXECUTE FUNCTION tenant_data.units_tao_toa()
        """
    )
    op.execute(
        "CREATE INDEX units_block_idx ON tenant_data.units (tenant_id, project_code, block) WHERE block IS NOT NULL"
    )
    op.execute(
        """
        ALTER TABLE tenant_data.units ADD CONSTRAINT units_block_fk FOREIGN KEY (tenant_id, project_code, block)
          REFERENCES tenant_data.buildings (tenant_id, project_code, building_code)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.units DROP CONSTRAINT units_block_fk")
    op.execute("DROP INDEX tenant_data.units_block_idx")
    op.execute("DROP TRIGGER units_tao_toa ON tenant_data.units")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tenant_data.units_tao_toa() RETURNS trigger LANGUAGE plpgsql AS $$
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
