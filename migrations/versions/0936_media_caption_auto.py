"""Cột `media.caption_auto` — mô tả ảnh do model sinh, TÁCH khỏi `caption` của khách

VÌ SAO KHÔNG GHI THẲNG VÀO `caption`: `caption` là **cột hợp đồng** của cổng nạp
(`ingest/hop_dong.py`), và cổng nạp là latest-wins THAY-THẾ-TRỌN-BẢN-GHI — trường vắng
mặt trong payload bị `_upsert` đưa `= DEFAULT`, tức `''`. Adapter khách hiện gửi `caption`
cho video và tour_360 nhưng KHÔNG gửi cho ảnh, nên mô tả ta sinh ra sẽ bị xoá trắng ở
lần đồng bộ kế tiếp của chính bản ghi đó, rồi sinh lại, rồi lại bị xoá — vừa mất tiền
VLM vừa làm nhãn dưới ảnh nhấp nháy.

Cột này KHÔNG có trong `HOP_DONG["media"]` nên `_upsert` không bao giờ chạm tới nó.

AI THẮNG: `caption` (người/khách nhập) > `caption_auto` (model sinh) — `resolve_media`
đọc theo đúng thứ tự đó. Khách bắt đầu gửi mô tả ảnh thật thì bản của họ tự động lên
trên, không cần dọn cột này.

`text NOT NULL DEFAULT ''` cùng khuôn `caption`: một cột nullable thêm một hình dạng
"không có" thứ hai mà mọi chỗ đọc phải nhớ.

Revision ID: 0936_media_caption_auto
Revises: 0935_hop_nhat_hai_head
"""

from alembic import op

revision = "0936_media_caption_auto"
down_revision = "0935_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.media ADD COLUMN IF NOT EXISTS caption_auto text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.media DROP COLUMN IF EXISTS caption_auto")
