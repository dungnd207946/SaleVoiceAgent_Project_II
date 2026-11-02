"""`media.content_type` nhận thêm `tour_360`

Tour 360 đang nằm ở collection `documents` với link TRONG text, nên để trả link cho khách
LLM phải chép lại một URL dài nhiều tham số (`https://kuula.co/share/collection/7l8Rt?logo=
…&info=…&fs=1&vr=0&…`) — chép sai là chuyện sẽ xảy ra. Ở collection `media` link đi trong
payload và client tự render, LLM không chạm vào chuỗi (D16).

Phía agent đã nhận `tour_360` (thẻ `tour`); đây là nửa còn thiếu ở đầu ghi.
"""

from alembic import op

revision = "0929_media_tour_360"
down_revision = "0928_thumb_tai_lieu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.media DROP CONSTRAINT IF EXISTS media_content_type_hop_le")
    op.execute(
        "ALTER TABLE tenant_data.media ADD CONSTRAINT media_content_type_hop_le "
        "CHECK (content_type IN ('image', 'video', 'tour_360'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM tenant_data.media WHERE content_type = 'tour_360'")
    op.execute("ALTER TABLE tenant_data.media DROP CONSTRAINT IF EXISTS media_content_type_hop_le")
    op.execute(
        "ALTER TABLE tenant_data.media ADD CONSTRAINT media_content_type_hop_le "
        "CHECK (content_type IN ('image', 'video'))"
    )
