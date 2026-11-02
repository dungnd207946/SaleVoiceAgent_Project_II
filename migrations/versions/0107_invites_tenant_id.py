"""control.invites thêm tenant_id — phân biệt token ĐĂNG KÝ với token MỜI

NULL = người đó tự đăng ký (`POST /auth/register`), chưa thuộc workspace nào.
Có giá trị = một Quản trị mời họ vào ĐÚNG workspace đó.

VÌ SAO KHÔNG LƯU THÊM CỘT `kind`: `kind` của `LoiMoiOut` suy từ
`tenant_id IS NULL`. Hai cột nói cùng một sự thật là hai cột sẽ lệch nhau, và
cột suy được thì không phải cột.

VÌ SAO KHÔNG BACKFILL: mọi hàng đang sống lúc chạy migration đều là token mời,
nhưng để NULL là ĐÚNG — chúng sinh ra ở thời kỳ chưa có khái niệm này, và đoán
ngược `tenant_id` từ `memberships` sẽ sai với người thuộc nhiều workspace. Token
hạn 7 ngày; hàng cũ tự hết.

Revision ID: 0107_invites_tenant_id
Revises: 0106_bo_organizations
"""

from alembic import op

revision = "0107_invites_tenant_id"
down_revision = "0106_bo_organizations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """ALTER TABLE control.invites
             ADD COLUMN tenant_id text
               REFERENCES control.tenants(id) ON DELETE CASCADE"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE control.invites DROP COLUMN tenant_id")
