"""billing.purpose — khai nhãn `playbook` là KHÔNG tính khách

Agent (nhánh playbook G1, cờ `NOBLE_PLAYBOOK_ENABLED`) gọi thêm một LLM phụ sau mỗi
lượt để gán nút kịch bản sale + chấm tuân thủ, ghi `usage_events` với
`purpose='playbook'`. Đây là đo chất lượng nội bộ (~8–10k token vào/lượt), cùng loại
với `warm_cache` / `addressee_gate` — giá vốn, không phải dịch vụ bán cho khách.

Nhãn chưa khai trong `billing.purpose` bị coi là TÍNH TIỀN (xem `0943` §3c), nên phải
khai trước khi bật cờ ở bất kỳ môi trường nào.

`ON CONFLICT DO NOTHING`: admin có thể đã phân loại tay qua
`billing.purpose_unclassified` — không đè quyết định đó.

Revision ID: 0969_billing_purpose_playbook
Revises: 0968_escalations_lead
"""

from alembic import op

revision = "0969_billing_purpose_playbook"
down_revision = "0968_escalations_lead"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO billing.purpose (code, billable, note) VALUES
          ('playbook', false, 'chấm nút kịch bản sale sau mỗi lượt — đo chất lượng nội bộ, giá vốn')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM billing.purpose WHERE code = 'playbook'")
