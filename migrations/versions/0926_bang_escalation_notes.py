"""tenant_data.escalation_notes — mỗi lần sale ghi chú là MỘT hàng, không đè

Revision ID: 0926_escalation_notes
Revises: 0925_hop_nhat_0924
"""

from alembic import op

revision = "0926_escalation_notes"
down_revision = "0925_hop_nhat_0924"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.escalations ADD CONSTRAINT escalations_tenant_id_key UNIQUE (tenant_id, id)")
    op.execute(
        """
        CREATE TABLE tenant_data.escalation_notes (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id     text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            escalation_id bigint NOT NULL,
            author        text,
            note          text NOT NULL CONSTRAINT escalation_note_check CHECK (note <> ''),
            created_at    timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, escalation_id)
                REFERENCES tenant_data.escalations (tenant_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX escalation_notes_ca_idx "
        "ON tenant_data.escalation_notes (tenant_id, escalation_id, created_at, id)"
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.escalation_notes')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.escalation_notes")
    op.execute("ALTER TABLE tenant_data.escalations DROP CONSTRAINT escalations_tenant_id_key")
