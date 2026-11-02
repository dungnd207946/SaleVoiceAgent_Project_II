"""control.memberships — người × workspace × vai trò

ĐÂY LÀ NGUỒN DUY NHẤT CỦA tenant_id. core/db/session.py nói rõ: "tenant_id PHẢI
đến từ membership đã xác thực, KHÔNG BAO GIỜ từ path param, query string, hay
body." Bảng này là cái "membership đã xác thực" đó.

VÌ SAO expires_at CÓ TỪ NGÀY ĐẦU dù luồng quyền hỗ trợ là M2b: PQ_01 §BR-Q08
buộc quyền hỗ trợ của NobleX là "một hàng memberships có hạn, KHÔNG phải cờ bỏ
qua kiểm tra" — vì cờ bỏ qua tạo một nhánh code mà lời hứa BR10 không áp dụng.
Có cột từ đây thì M2b là chèn một hàng; không có thì M2b là một migration cộng
sửa require(), và cộng một cám dỗ đi đường cờ.

VÌ SAO PK (user_id, tenant_id): một người MỘT vai trò trong một workspace. Vé hỗ
trợ xin lần hai vào cùng workspace là UPDATE expires_at, không phải hàng thứ hai.

VÌ SAO BẢNG NÀY KHÔNG DƯỚI RLS dù mang tenant_id: nó CHÍNH LÀ thứ quyết định
phạm vi tenant của một request. Đặt nó dưới RLS của tenant_data là vòng tròn —
muốn đọc membership để biết tenant thì đã phải biết tenant trước. Khai tường minh
ở tests/isolation/test_isolation_catalog.py, cùng dạng với `jobs`.

Bốn giá trị role là tên kỹ thuật đã chốt ở PQ_01 §2.4:
    Quản trị -> admin · CSKH -> care · Biên tập -> editor · Người xem -> viewer

Revision ID: 0101_memberships
Revises: 0100_users
"""

from alembic import op

revision = "0101_memberships"
down_revision = "0100_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.memberships (
            user_id    text NOT NULL REFERENCES control.users(id)   ON DELETE CASCADE,
            tenant_id  text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            role       text NOT NULL
                       CONSTRAINT memberships_role_check
                       CHECK (role IN ('admin', 'care', 'editor', 'viewer')),
            expires_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, tenant_id)
        )
        """
    )
    # Truy vấn "ai là thành viên workspace này" (màn Users) quét theo tenant_id;
    # PK dẫn đầu bởi user_id nên không phục vụ được chiều đó.
    op.execute("CREATE INDEX memberships_tenant_idx ON control.memberships (tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE control.memberships")
