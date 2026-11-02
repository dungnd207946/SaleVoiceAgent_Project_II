"""ingest_records: bỏ `projected_at`, thêm cặp `cho_cha_*` — chiếu đồng bộ per-record

Revision ID: 0931_cho_cha
Revises: 0930_bo_last_used_at

`projected_at` là state machine của một HÀNG ĐỢI chiếu trễ, và hàng đợi đó là
nguồn của bốn lớp bug đo được (review 2026-08-15 finding #1 #3 #7 #8): hàng kẹt
vĩnh viễn, đánh-dấu-đã-chiếu-dù-hỏng, starvation ở LIMIT 2000, và stamp của lô
này đè reset của lô kia. Lý do DUY NHẤT cần trạng thái chờ là «con tới trước
cha» — nên trạng thái mới nói ĐÚNG điều đó và không nói gì khác: `cho_cha_entity`
/`cho_cha_ma` = bản ghi này đang chờ đúng bản ghi cha nào. NULL cả cặp = đã chiếu
xong. Chiếu hỏng thì KHÔNG có trạng thái — savepoint rollback cả bản thô, khách
nhận `rejected` và đẩy lại được nguyên văn (bản đang có giữ occurred_at cũ).
"""

from alembic import op

revision = "0931_cho_cha"
down_revision = "0930_bo_last_used_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tenant_data.ingest_records_cho_chieu_idx")
    op.execute("ALTER TABLE tenant_data.ingest_records NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM tenant_data.ingest_records WHERE projected_at IS NULL")
    op.execute("ALTER TABLE tenant_data.ingest_records FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_data.ingest_records DROP COLUMN projected_at")
    op.execute("ALTER TABLE tenant_data.ingest_records ADD COLUMN cho_cha_entity text")
    op.execute("ALTER TABLE tenant_data.ingest_records ADD COLUMN cho_cha_ma text")
    op.execute(
        """ALTER TABLE tenant_data.ingest_records
           ADD CONSTRAINT ingest_records_cho_cha_du_cap
           CHECK ((cho_cha_entity IS NULL) = (cho_cha_ma IS NULL))"""
    )
    # Tập chờ NHỎ theo thiết kế — index một phần, tra theo đúng cha vừa chiếu xong.
    op.execute(
        """CREATE INDEX ingest_records_cho_cha_idx
              ON tenant_data.ingest_records (tenant_id, cho_cha_entity, cho_cha_ma)
           WHERE cho_cha_ma IS NOT NULL"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tenant_data.ingest_records_cho_cha_idx")
    op.execute("ALTER TABLE tenant_data.ingest_records DROP CONSTRAINT ingest_records_cho_cha_du_cap")
    op.execute("ALTER TABLE tenant_data.ingest_records DROP COLUMN cho_cha_ma")
    op.execute("ALTER TABLE tenant_data.ingest_records DROP COLUMN cho_cha_entity")
    op.execute("ALTER TABLE tenant_data.ingest_records ADD COLUMN projected_at timestamptz")
    # Hàng không chờ gì coi như đã chiếu — downgrade là đường lùi dev, không cần chính xác từng mốc.
    op.execute("UPDATE tenant_data.ingest_records SET projected_at = received_at")
    op.execute(
        """CREATE INDEX ingest_records_cho_chieu_idx
              ON tenant_data.ingest_records (tenant_id, entity)
           WHERE projected_at IS NULL"""
    )
