"""data_conflicts — cảnh báo mâu thuẫn dữ liệu dự án + nhãn billing `conflict_check`

Một bảng cho cả hai việc: cảnh báo (`open`/`dismissed`/`resolved`) và bộ nhớ cặp đã phán
(`none`). UNIQUE theo cặp dấu tay nên một cặp không bao giờ được phán hai lần, và
`dismissed` không bị lượt dò sau mở lại. Spec: docs/superpowers/specs/2026-10-14-canh-bao-mau-thuan-du-lieu-design.md

`conflict_check` tính tiền khách (tính năng khách dùng trực tiếp).

Revision ID: 0981_data_conflicts
Revises: 0980_hop_nhat_hai_head
"""

from alembic import op

revision = "0981_data_conflicts"
down_revision = "0980_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_data.data_conflicts (
          id              bigserial PRIMARY KEY,
          tenant_id       text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
          project_code    text NOT NULL,
          left_hash       text NOT NULL,
          right_hash      text NOT NULL,
          status          text NOT NULL CHECK (status IN ('open', 'dismissed', 'resolved', 'none')),
          summary         text NOT NULL DEFAULT '',
          left_entity     text,
          left_record_id  bigint,
          left_field      text,
          left_label      text,
          left_quote      text,
          right_entity    text,
          right_record_id bigint,
          right_field     text,
          right_label     text,
          right_quote     text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          resolved_at     timestamptz,
          dismissed_at    timestamptz,
          dismissed_by    text,
          UNIQUE (tenant_id, left_hash, right_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX data_conflicts_project_status ON tenant_data.data_conflicts (tenant_id, project_code, status)"
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.data_conflicts')")
    op.execute(
        """
        INSERT INTO billing.purpose (code, billable, note) VALUES
          ('conflict_check', true, 'dò mâu thuẫn dữ liệu dự án — tính năng khách dùng')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM billing.purpose WHERE code = 'conflict_check'")
    op.execute("DROP TABLE tenant_data.data_conflicts")
