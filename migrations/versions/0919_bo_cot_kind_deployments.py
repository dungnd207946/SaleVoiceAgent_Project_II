"""control.deployments bỏ cột kind — một khoá dùng chung cho cả chat lẫn voice

VÌ SAO BỎ: `kind` (CHECK IN ('chat', 'voice'), từ `0200`) mô hình hoá sai thực tế
— nó gợi ý một tenant có hai deployment tách biệt theo kênh, mỗi cái một khoá
riêng. Nhưng khoá phát ra ở `POST /agent/keys` (router_tenant.py) mở được CẢ
HAI `ENDPOINT_CHAT_URL` lẫn `ENDPOINT_VOICE_URL` — cùng một `postgres_role`,
cùng một bộ credential trả về từ `/runtime-credentials`. `kind` trên hàng
`deployments` chỉ còn lại là một giá trị hardcode `'chat'` (từ đường tự phát
khoá) không phản ánh gì thật, và response `/runtime-credentials` lộ nó ra
ngoài như thể có ý nghĩa.

CỘT `kind` VẪN GIỮ Ở `KIND_CHAT`/`KIND_VOICE` (`endpoint.py`) và ở
`ENDPOINT_CHAT_URL`/`ENDPOINT_VOICE_URL` — hai công thức URL đó KHÔNG đọc từ
DB, chúng thuần suy từ `tenant_id` + domain. Xoá ở đây chỉ bỏ cột lưu trữ dư
thừa, không đụng tới hai URL đó.

Revision ID: 0919_bo_cot_kind
Revises: 0918_agent_keys_kho_tho
"""

from alembic import op

revision = "0919_bo_cot_kind"
down_revision = "0918_agent_keys_kho_tho"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.deployments DROP COLUMN kind")


def downgrade() -> None:
    op.execute("ALTER TABLE control.deployments ADD COLUMN kind text")
    op.execute("UPDATE control.deployments SET kind = 'chat' WHERE kind IS NULL")
    op.execute(
        """
        ALTER TABLE control.deployments
            ALTER COLUMN kind SET NOT NULL,
            ADD CONSTRAINT deployments_kind_check CHECK (kind IN ('chat', 'voice'))
        """
    )
