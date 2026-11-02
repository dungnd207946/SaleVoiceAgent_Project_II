"""Hợp nhất hai head 0920 — lần thứ tư

    $ alembic heads
    0920_hop_nhat_hai_head_0919
    0922_media_file_name

Nhánh media (`0920_kb_state_skipped` → `0921` → `0922`) nhận
`0919_hop_nhat_hai_head_0918` làm cha, hợp lệ lúc viết; cùng lúc
`0919_bo_cot_kind_deployments` merge vào develop và sinh mergepoint `0920` riêng:

    0919_hop_nhat_hai_head_0918
    ├── 0920_hop_nhat_hai_head_0919  (mergepoint của 0919_bo_cot_kind)
    └── 0920_kb_state_skipped → 0921_media_public_url → 0922_media_file_name

Không đổi `down_revision` của nhánh nào — đổi cha làm alembic coi tổ tiên mới là
đã áp trên DB thật ra chưa áp, và không lệnh nào báo.

Revision ID: 0923_hop_nhat_hai_head_0920
Revises: 0920_hop_nhat_hai_head_0919, 0922_media_file_name
"""

revision = "0923_hop_nhat_0920"
down_revision = ("0920_hop_nhat_hai_head_0919", "0922_media_file_name")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rỗng có chủ ý: hai nhánh chạm bảng khác nhau, không có gì phải hoà giải."""


def downgrade() -> None:
    """Rỗng — `alembic downgrade` qua điểm hợp nhất tự tách lại hai nhánh."""
