"""media: thêm public_url và public_thumb_url — URL agent gửi cho khách

KHÔNG backfill ở đây: giá trị mang domain, mà dev và prod khác domain. Chạy
`scripts/backfill_public_url.py` sau khi migrate.

Revision ID: 0921_media_public_url
Revises: 0920_kb_state_skipped
"""

from alembic import op

revision = "0921_media_public_url"
down_revision = "0920_kb_state_skipped"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.media ADD COLUMN public_url text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE tenant_data.media ADD COLUMN public_thumb_url text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.media DROP COLUMN public_thumb_url")
    op.execute("ALTER TABLE tenant_data.media DROP COLUMN public_url")
