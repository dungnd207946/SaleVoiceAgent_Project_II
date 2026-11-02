"""Cột `documents.body_auto` — chữ bóc từ tệp, TÁCH khỏi `body` của khách

CÙNG MỘT LỖI VỚI `media.caption` (xem `0936`), ở một cột đắt hơn nhiều. `body` là **cột
hợp đồng** của cổng nạp, và cổng nạp là latest-wins THAY-THẾ-TRỌN-BẢN-GHI: trường vắng
trong payload bị `_upsert` đưa `= DEFAULT`, tức `''`. Tài liệu khách đẩy sang chỉ có
`fileUrl` và không có `body`, nên chữ ta bóc ra bị xoá ở lần đồng bộ kế tiếp của chính
bản ghi đó — rồi bóc lại. Một PDF scan nhiều trang phải trả tiền OCR mỗi vòng đồng bộ,
và không ai nhìn thấy chuyện đó vì kết quả cuối vẫn "có chữ".

TÁCH THEO QUYỀN SỞ HỮU BẢN GHI, không theo nguồn chữ: `cache_extracted_text` vẫn ghi vào
`body` cho tài liệu nhập tay (`external_id IS NULL`) — ở đó `body` là ô người dùng sửa,
và màn CHỜ DUYỆT đọc đúng cột đó, nên chuyển sang cột phụ là làm màn ấy trống trơn. Chỉ
bản ghi do hệ ngoài sở hữu (`external_id` khác NULL) mới ghi sang `body_auto`.

Đường đọc `coalesce(nullif(body,''), body_auto)` nên thứ tự ưu tiên giống `caption`:
chữ của khách thắng chữ ta bóc.

Revision ID: 0937_documents_body_auto
Revises: 0936_media_caption_auto
"""

from alembic import op

revision = "0937_documents_body_auto"
down_revision = "0936_media_caption_auto"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.documents ADD COLUMN IF NOT EXISTS body_auto text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.documents DROP COLUMN IF EXISTS body_auto")
