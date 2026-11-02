"""hợp nhất hai head — `0964_backfill_hot_words` và `0964_don_ky_nang_da_khai_tu_2`

Hai migration viết song song, cùng nhận `0963_project_hot_words` làm cha (mỗi
bên không thấy migration của bên kia lúc viết) — cùng lớp việc đã xảy ra nhiều
lần trong repo này (xem Change Log `CLAUDE.md`, ví dụ `0955`/`0951`/`0932`...).
Đã đối chiếu DDL/DML của cả hai: `0964_backfill_hot_words` chỉ chạm
`tenant_data.projects`/`tenant_data.project_hot_words`; `0964_don_ky_nang_da_khai_tu_2`
chỉ chạm `control.config_drafts.payload` — hoàn toàn trực giao, không bảng nào
chung. Thân rỗng, tuple hai cha, KHÔNG đổi `down_revision` của nhánh nào (luật
đã ghi ở nhiều migration hợp nhất trước, ví dụ `0951_hop_nhat_hai_head`).

Revision ID: 0965_hop_nhat_hai_head
Revises: 0964_backfill_hot_words, 0964_don_ky_nang_da_khai_tu_2
"""

revision = "0965_hop_nhat_hai_head"
down_revision = ("0964_backfill_hot_words", "0964_don_ky_nang_da_khai_tu_2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
