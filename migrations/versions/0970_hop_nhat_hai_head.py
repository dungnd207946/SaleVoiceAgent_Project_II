"""hợp nhất hai head — `0969_billing_purpose_playbook` và `0969_public_data_web_pages`

Hai migration viết song song, cùng nhận `0968_escalations_lead` làm cha. Git merge sạch
(tên tệp khác nhau) nên chỉ alembic thấy: deploy develop `faaf4a9` gãy ở `alembic upgrade
head` với "Multiple head revisions". Đã đối chiếu: `0969_billing_purpose_playbook` chỉ
INSERT một dòng vào `billing.purpose`; `0969_public_data_web_pages` chỉ tạo schema mới
`public_data` — trực giao, không đối tượng nào chung. Thân rỗng, tuple hai cha, KHÔNG đổi
`down_revision` của nhánh nào (luật ở `0965_hop_nhat_hai_head`/`0951_hop_nhat_hai_head`).

Revision ID: 0970_hop_nhat_hai_head
Revises: 0969_billing_purpose_playbook, 0969_public_data_web_pages
"""

revision = "0970_hop_nhat_hai_head"
down_revision = ("0969_billing_purpose_playbook", "0969_public_data_web_pages")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
