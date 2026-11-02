"""hợp nhất hai head — `0970_nhan_vat` và `0979_units_block_fk`

`0970_nhan_vat` (nhánh người dẫn tự tạo) nhận `0969_billing_purpose_playbook` làm cha, viết
song song với chuỗi `0970_hop_nhat_hai_head` → `0979_units_block_fk` của develop. Git merge sạch
(tên tệp khác nhau) nên chỉ alembic thấy: "Multiple head revisions". Đã đối chiếu:
`0970_nhan_vat` chỉ tạo bảng `tenant_data.nhan_vat` + hai index; không migration nào từ
`0971` tới `0979` chạm bảng đó — trực giao. Thân rỗng, tuple hai cha, KHÔNG đổi
`down_revision` của nhánh nào (luật ở `0965_hop_nhat_hai_head`/`0951_hop_nhat_hai_head`).

Revision ID: 0980_hop_nhat_hai_head
Revises: 0970_nhan_vat, 0979_units_block_fk
"""

revision = "0980_hop_nhat_hai_head"
down_revision = ("0970_nhan_vat", "0979_units_block_fk")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
