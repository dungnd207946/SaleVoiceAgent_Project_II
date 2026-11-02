"""tenant_data.escalations — mỗi lần agent chuyển khách cho sale là MỘT hàng

Hình dạng bảng do phía agent đưa (`storage/sql/odyssey_data_plane.sql`), Portal
mirror lại chứ không thiết kế. Bảng thứ 5 agent ghi vào `tenant_data`.

EVENT LOG, KHÔNG PHẢI HỒ SƠ: một cuộc gọi hỏi ba câu hệ thống không trả lời được
sinh ba hàng. Gom theo `session_id` là việc của truy vấn.

`missing_data_tool` rỗng = agent chủ động chuyển; có giá trị = tool đó bí dữ liệu
nên code tự chuyển. `summary_at` NULL = `summary` còn là bản tạm agent ghép lúc
INSERT, bản LLM về sau vài giây thì UPDATE cả hai cột.

Bốn cột Portal sở hữu: `status` · `handled_by` · `handled_at` · `handled_note` —
agent không đọc, không ghi. Đây là đường GHI đầu tiên của M7.

KHÔNG `CHECK (status IN ...)` và KHÔNG FK `session_id`: cùng lý lẽ `role` và
`conversations` của `0915`.

⚠️ `0913` KHÔNG với tới bảng này (nó quét `pg_class` lúc nó chạy). Xoá dòng
`enforce_tenant_isolation` bên dưới là tạo một bảng không RLS giữa schema có RLS.

Revision ID: 0924_escalations
Revises: 0923_hop_nhat_0920
"""

from alembic import op

revision = "0924_escalations"
down_revision = "0923_hop_nhat_0920"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE tenant_data.escalations (
            id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id         {_TENANT_FK},
            -- KHÔNG FK về conversations — xem docstring.
            session_id        text NOT NULL
                              CONSTRAINT escalation_session_check CHECK (session_id <> ''),
            -- Ảnh chụp lúc chuyển; đường đọc COALESCE với `conversations` (repo.py).
            phone             text,
            customer_name     text,
            project           text,
            missing_data_tool text,
            summary           text,
            summary_at        timestamptz,
            message_seq       integer,
            status            text NOT NULL DEFAULT 'new',
            handled_by        text,
            handled_at        timestamptz,
            handled_note      text,
            created_at        timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # Ba truy vấn của hộp thư: mới nhất trước, lọc trạng thái, gom theo cuộc gọi.
    op.execute("CREATE INDEX escalations_tenant_created_idx ON tenant_data.escalations (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX escalations_tenant_status_idx ON tenant_data.escalations (tenant_id, status)")
    op.execute("CREATE INDEX escalations_tenant_session_idx ON tenant_data.escalations (tenant_id, session_id)")

    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.escalations')")
    op.execute("SELECT control.grant_agent_write('tenant_data.escalations')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.escalations")
