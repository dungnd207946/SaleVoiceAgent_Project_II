"""schema portal + control, và hàm xác định tenant hiệu lực

VÌ SAO CÓ FILE NÀY: cách ly đa-tenant của cả hệ đứng trên đúng một hàm —
portal.current_tenant(). Mọi policy RLS và mọi view agent_api gọi nó.

HAI NGUỒN, VÌ HAI BẢN CHẤT KHÁC NHAU:
  - Pod agent phục vụ ĐÚNG MỘT tenant suốt đời tiến trình -> tenant là thuộc
    tính của DANH TÍNH KẾT NỐI, gói vào tên role `agent_<slug>`. Agent KHÔNG
    tự đổi được (đổi session_user cần SET SESSION AUTHORIZATION = superuser).
  - Portal API phục vụ MỌI tenant, đổi theo từng request -> tenant là thuộc
    tính của ĐƠN VỊ CÔNG VIỆC, đặt bằng SET LOCAL app.tenant_id trong giao dịch.

THỨ TỰ COALESCE CÓ Ý NGHĨA AN NINH: nguồn KHÔNG đổi được (tên role) đứng
TRƯỚC nguồn đổi được (GUC). Đảo lại thì một kết nối agent có GUC bị đặt sẽ
leo thang sang tenant khác.

DÙNG session_user, KHÔNG dùng current_user: trong view definer (migration
0005) current_user trả về OWNER của view, không phải role đang gọi.

Trả NULL khi không xác định được -> mọi so sánh `tenant_id = NULL` ra false
-> 0 hàng. Hỏng thì trả rỗng, không trả nhầm của người khác.

Revision ID: 0001_schemas
Revises: None
"""

from alembic import op

revision = "0001_schemas"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA portal")
    op.execute("CREATE SCHEMA control")

    op.execute(
        """
        CREATE FUNCTION portal.current_tenant() RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT coalesce(
                substring(session_user::text from '^agent_(.+)$'),
                nullif(current_setting('app.tenant_id', true), '')
            )
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA control CASCADE")
    op.execute("DROP SCHEMA portal CASCADE")
