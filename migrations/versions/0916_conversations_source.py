"""tenant_data.conversations — thêm cột `source`

VẤN ĐỀ NÓ GIẢI: bảng `conversations` (0903) không ghi phiên đến từ kênh nào (web
widget, Zalo, Facebook, điện thoại...). Không có cột này thì không cách nào lọc
hay thống kê hội thoại theo kênh.

VÌ SAO `text` CHỨ KHÔNG PHẢI ENUM/CHECK: tập kênh chưa chốt — agent có thể thêm
kênh mới bất kỳ lúc nào, và một CHECK khoá cứng danh sách sẽ làm đường ghi của
kênh mới VỠ ngay khi nó xuất hiện. Cùng lý lẽ với `role` của
`conversation_messages` (0915): danh sách hôm nay là chú thích, không phải hợp
đồng đã ký.

VÌ SAO NULLABLE, KHÔNG DEFAULT: "chưa biết nguồn" và "nguồn rỗng" là hai sự thật
khác nhau ở đây, không như `full_conversation` (0912). Cho NULL đi đúng nghĩa
"agent phiên bản cũ chưa gửi trường này", không giả vờ là một giá trị đã biết.

KHÔNG REWRITE BẢNG: `ADD COLUMN` không NOT NULL, không DEFAULT là thao tác
metadata thuần — không khoá ACCESS EXCLUSIVE kéo dài trên bảng đang được agent
ghi liên tục.

KHÔNG CẦN GRANT LẠI CHO AGENT: `control.grant_agent_write()` (0905) đã cấp
`GRANT SELECT, INSERT, UPDATE` ở mức BẢNG (0903) — cột mới nằm trong đó sẵn.

Revision ID: 0916_conversations_source
Revises: 0915_convo_messages
"""

from alembic import op

revision = "0916_conversations_source"
down_revision = "0915_convo_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.conversations ADD COLUMN source text")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.conversations DROP COLUMN source")
