"""`tenant_data.kich_ban` — bản kịch bản sale riêng của workspace (playbook template đợt 2).

Spec: odyssey-agent docs/superpowers/specs/2026-10-06-playbook-template-dot-2-design.md §1.
Một hàng / workspace. `nut` NULL = chưa áp dụng (agent chạy template NobleX); `role_dung` = role dùng kịch bản
(không hàng ⇒ chỉ `customer`). Không seed: không hàng là trạng thái mặc định. Agent đọc (`GRANT SELECT TO PUBLIC`,
RLS lọc theo tenant như `role_config`).

Revision ID: 0976_kich_ban
Revises: 0975_bang_gia_tra_google
"""

from alembic import op

revision = "0976_kich_ban"
down_revision = "0975_bang_gia_tra_google"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_data.kich_ban (
            tenant_id   text PRIMARY KEY REFERENCES control.tenants(id) ON DELETE CASCADE,
            nut         jsonb,
            tu_template text,
            role_dung   text[] NOT NULL DEFAULT '{customer}',
            version     integer NOT NULL DEFAULT 0,
            updated_at  timestamptz NOT NULL DEFAULT now(),
            updated_by  text,
            CONSTRAINT kich_ban_nut_la_mang CHECK (nut IS NULL OR jsonb_typeof(nut) = 'array')
        )
        """
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.kich_ban')")
    op.execute("GRANT SELECT ON tenant_data.kich_ban TO PUBLIC")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.kich_ban")
