"""kb_index_state: state nhận 'skipped', và thêm project_code

`project_code` ở SỔ chứ không suy từ bảng nguồn: FK `projects → con` là ON DELETE
CASCADE, nên job cascade chạy sau request sẽ thấy rỗng và point sống mãi.

Dòng sổ có record nguồn đã xoá TRƯỚC migration này giữ `project_code = ''`.

Revision ID: 0920_kb_state_skipped
Revises: 0919_hop_nhat_hai_head_0918
"""

from alembic import op

revision = "0920_kb_state_skipped"
down_revision = "0919_hop_nhat_hai_head_0918"
branch_labels = None
depends_on = None

_STATE_CU = "('queued', 'indexing', 'indexed', 'error', 'deleted')"
_STATE_MOI = "('queued', 'indexing', 'indexed', 'error', 'deleted', 'skipped')"


def _dat_check(mien: str) -> None:
    op.execute("ALTER TABLE tenant_data.kb_index_state DROP CONSTRAINT kb_index_state_state_check")
    op.execute(
        f"ALTER TABLE tenant_data.kb_index_state ADD CONSTRAINT kb_index_state_state_check CHECK (state IN {mien})"
    )


def upgrade() -> None:
    _dat_check(_STATE_MOI)

    op.execute("ALTER TABLE tenant_data.kb_index_state ADD COLUMN project_code text NOT NULL DEFAULT ''")
    op.execute("CREATE INDEX kb_index_state_tenant_project_idx ON tenant_data.kb_index_state (tenant_id, project_code)")

    # Chạy bằng portal_migrator (owner) nên không bị RLS — không cần set app.tenant_id.
    op.execute(
        """
        UPDATE tenant_data.kb_index_state s SET project_code = p.project_code
          FROM tenant_data.projects p
         WHERE s.entity = 'projects' AND s.record_id = p.id AND s.tenant_id = p.tenant_id
        """
    )
    for bang in ("zones", "documents", "media"):
        op.execute(
            f"""
            UPDATE tenant_data.kb_index_state s SET project_code = c.project_code
              FROM tenant_data.{bang} c
             WHERE s.entity = '{bang}' AND s.record_id = c.id AND s.tenant_id = c.tenant_id
            """
        )


def downgrade() -> None:
    # Hàng đang ở 'skipped' phải về 'indexed' trước khi siết CHECK, nếu không
    # ALTER từ chối và downgrade gãy giữa đường.
    op.execute("UPDATE tenant_data.kb_index_state SET state = 'indexed' WHERE state = 'skipped'")
    op.execute("DROP INDEX tenant_data.kb_index_state_tenant_project_idx")
    op.execute("ALTER TABLE tenant_data.kb_index_state DROP COLUMN project_code")
    _dat_check(_STATE_CU)
