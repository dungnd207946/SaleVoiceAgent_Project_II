"""schema tenant_data + 2 bảng lõi để CHỨNG MINH cách ly

M1 chỉ tạo cột LÕI — vừa đủ để 6 cổng test chứng minh cách ly hàng và gate cột.
M4 ALTER thêm ~40 cột cho projects và ~45 cột cho units. Đó là NGOẠI LỆ đã hẹn
trước của luật "module không sửa bảng của module khác" (spec tổng §4④).

BA ĐIỀU BẮT BUỘC:
  1. Giá là bigint VND, không phải tỷ. Không cột nào tên *_ty. Đổi đơn vị làm
     ở biên NHẬP (M4). Đây chính là bug tỷ -> x1e9 mà agent đã phải sửa một lần.
  2. UNIQUE (tenant_id, code), KHÔNG phải UNIQUE(code). Hai tenant được dùng
     cùng mã căn. `code`/`phone` unique TOÀN CỤC là đúng chỗ đơn-tenant của CMS
     cũ lộ ra.
  3. KHÔNG tạo cột `tower`, và `floor` có cột nhưng KHÔNG được seed filterable.
     Quyết định #17 gỡ hai FILTER floor/tower khỏi tool schema, không gỡ cột:
     nbx_mongo khai hai filter đó cho LLM nhưng không đọc chúng, nên khách hỏi
     "căn tầng 14" thì trả căn tầng bất kỳ và agent đọc như thể đúng tầng.
     Sai âm thầm tệ hơn trả rỗng. `tower` thì vốn hardcode "" nên không tạo.

BA CỘT GATED: commission · bank_support · csbh_full. Chúng nhạy cảm thương mại
— hoa hồng lộ ra cho khách là sự cố thật. Chỉ lộ qua view agent_api khi
field_policy_live cho phép (migration 0005).

Revision ID: 0004_tenant_data
Revises: 0003_role_isolation
"""

from alembic import op

revision = "0004_tenant_data"
down_revision = "0003_role_isolation"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS tenant_data")
    op.execute("GRANT USAGE ON SCHEMA tenant_data TO portal_api")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_data GRANT USAGE ON SEQUENCES TO portal_api")

    op.execute(
        f"""
        CREATE TABLE tenant_data.projects (
            id         bigserial PRIMARY KEY,
            tenant_id  {_TENANT_FK},
            code       text NOT NULL,
            name       text NOT NULL DEFAULT '',
            slug       text NOT NULL DEFAULT '',
            type       text NOT NULL DEFAULT '',
            region     text NOT NULL DEFAULT '',
            location   text NOT NULL DEFAULT '',
            investor   text NOT NULL DEFAULT '',
            status     text NOT NULL DEFAULT 'draft',
            is_hot     boolean NOT NULL DEFAULT false,
            sort_hot   integer NOT NULL DEFAULT 0,
            overview   jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            lat        double precision,
            lng        double precision,
            extras     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT projects_tenant_code_key UNIQUE (tenant_id, code)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE tenant_data.units (
            id             bigserial PRIMARY KEY,
            tenant_id      {_TENANT_FK},
            code           text NOT NULL,
            project_code   text NOT NULL DEFAULT '',
            unit_type      text NOT NULL DEFAULT '',
            status         text NOT NULL DEFAULT 'unknown'
                           CHECK (status IN ('available', 'sold', 'booked', 'unknown')),
            direction      text NOT NULL DEFAULT '',
            price_vnd      bigint,
            price_tts_vnd  bigint,
            area_m2        numeric(10, 2),
            area_build_m2  numeric(10, 2),
            bedrooms       smallint,
            floor          smallint,
            fund_type      text NOT NULL DEFAULT '',
            commission     text NOT NULL DEFAULT '',
            bank_support   text NOT NULL DEFAULT '',
            csbh_full      text NOT NULL DEFAULT '',
            csbh_brief     text NOT NULL DEFAULT '',
            gift           text NOT NULL DEFAULT '',
            legal          text NOT NULL DEFAULT '',
            extras         jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            updated_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT units_tenant_code_key UNIQUE (tenant_id, code)
        )
        """
    )
    op.execute("CREATE INDEX units_tenant_project_idx ON tenant_data.units (tenant_id, project_code)")
    op.execute("CREATE INDEX units_tenant_status_idx ON tenant_data.units (tenant_id, status)")

    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.projects')")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.units')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.units")
    op.execute("DROP TABLE tenant_data.projects")
    op.execute("DROP SCHEMA tenant_data CASCADE")
