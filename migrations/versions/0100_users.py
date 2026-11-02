"""control.users — neo danh tính người

Dải revision của M2a là 0100-0149 (xem plan M1 §migration). M1 cố ý KHÔNG tạo
bảng này: "Module sau tự sở hữu bảng của nó."

VÌ SAO id là text-slug chứ không uuid: control.tenants.id đã là text-slug (nó đi
vào tên role agent_<id>). Hai loại khoá trong cùng một schema là một nguồn nhầm
lẫn thường trực mà không đổi được gì.

VÌ SAO KHÔNG có cột `initials`: FE cần hai chữ trên avatar, suy từ `name` trong
service. Một cột chứa thông tin đã có trong cột khác là một bug đang chờ lệch.

VÌ SAO CHECK email = lower(email): UNIQUE trên email chỉ có nghĩa nếu mọi đường
ghi đều chuẩn hoá. Đặt CHECK ở DB biến "quên chuẩn hoá" thành lỗi to lúc INSERT.
Không dùng citext: thêm một extension cho một cột là chi phí vận hành không cần.

VÌ SAO lifecycle KHÔNG có 'closed' dù tenants.lifecycle có: người không bị "đóng",
chỉ bị đình chỉ. Dùng chung từ vựng với tenants để đọc hai bảng không phải học hai
bộ từ, nhưng chỉ chung phần có nghĩa chung.

Revision ID: 0100_users
Revises: 0007_heartbeats
"""

from alembic import op

revision = "0100_users"
down_revision = "0007_heartbeats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.users (
            id            text PRIMARY KEY
                          CONSTRAINT users_id_check CHECK (id ~ '^u_[a-z0-9_]{1,40}$'),
            email         text NOT NULL UNIQUE
                          CONSTRAINT users_email_lower_check CHECK (email = lower(email)),
            password_hash text NOT NULL,
            name          text NOT NULL,
            lifecycle     text NOT NULL DEFAULT 'active'
                          CONSTRAINT users_lifecycle_check CHECK (lifecycle IN ('active', 'suspended')),
            created_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE control.users")
