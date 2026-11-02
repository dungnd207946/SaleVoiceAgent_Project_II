"""bảng kb_index_state — sổ ghi "đã index cái gì, tới đâu, lỗi gì"

Không doc nào của db-design đặt tên bảng này, nhưng ba chỗ đòi đúng cái nó làm:
`GET /{id}/index-status` (§9), "ghi lại trạng thái index" (§7.1), Phase 6 (§13). Không có
nó thì một event bị mất là dữ liệu âm thầm không lên index, và reconcile mất mốc so sánh.

`doc_type` phải nằm trong khoá UNIQUE: `projects` xuất hiện hai lần trong `embed_sources`
nên một hàng sinh hai dòng trạng thái.

Không có FK tới record: bảng này trỏ tới bốn bảng khác nhau. Row rác chỉ tốn chỗ, reconcile
sẽ xoá.

Revision ID: 0501_kb_index_state
Revises: 0500_kb_documents
"""

from alembic import op

revision = "0501_kb_index_state"
down_revision = "0500_kb_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # entity phải khớp settings.ENTITIES của module kb.
    op.execute(
        """
        CREATE TABLE tenant_data.kb_index_state (
            id           bigserial PRIMARY KEY,
            tenant_id    text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            entity       text NOT NULL
                         CONSTRAINT kb_index_state_entity_check
                         CHECK (entity IN ('projects', 'zones', 'documents', 'media')),
            record_id    bigint NOT NULL,
            doc_type     text NOT NULL DEFAULT '',
            target       text NOT NULL
                         CONSTRAINT kb_index_state_target_check
                         CHECK (target IN ('documents', 'media')),
            state        text NOT NULL DEFAULT 'queued'
                         CONSTRAINT kb_index_state_state_check
                         CHECK (state IN ('queued', 'indexing', 'indexed', 'error', 'deleted')),
            content_hash text NOT NULL DEFAULT '',
            points       integer NOT NULL DEFAULT 0,
            error        text NOT NULL DEFAULT '',
            attempts     smallint NOT NULL DEFAULT 0,
            indexed_at   timestamptz,
            updated_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT kb_index_state_record_key UNIQUE (tenant_id, entity, record_id, doc_type)
        )
        """
    )
    op.execute("CREATE INDEX kb_index_state_tenant_state_idx ON tenant_data.kb_index_state (tenant_id, state)")

    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.kb_index_state')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.kb_index_state")
