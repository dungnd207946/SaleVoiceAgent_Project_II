"""media: thêm file_name — tên người đọc thấy trong kho ảnh

Khoá S3 mang tên tệp đã bị `_ten_an_toan` rút về ASCII (`nh-ch-p-m-n-h-nh.png`), nên
không dùng làm nhãn được. Cột này giữ tên gốc do trình duyệt gửi lên, và người dùng
sửa được sau.

Revision ID: 0922_media_file_name
Revises: 0921_media_public_url
"""

from alembic import op

revision = "0922_media_file_name"
down_revision = "0921_media_public_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.media ADD COLUMN file_name text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.media DROP COLUMN file_name")
