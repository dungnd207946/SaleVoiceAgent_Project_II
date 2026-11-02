"""Ảnh thu nhỏ cho tài liệu — hai cột `thumb_url` / `public_thumb_url` trên `documents`

Payload point của collection `documents` khai một khoá `thumb_url` (hợp đồng
`docs/contracts/payload-qdrant.md`), nhưng đường dựng chỉ thị đọc nó từ `row["thumb_url"]`
và bảng `documents` KHÔNG CÓ cột đó — nên khoá này luôn rỗng và tệp gửi kèm câu trả lời chỉ
là một link trần, không có gì nhìn thấy được. Đây là nửa còn thiếu của D14.

Cùng hình dạng hai cột của `media` (`0921`): cột thứ nhất giữ KHOÁ kho, cột thứ hai giữ URL
công khai suy từ khoá. Lưu khoá vì khoá bền còn URL phụ thuộc cấu hình miền.

Idempotent (`IF NOT EXISTS`) — cùng nếp `0927`.
"""

from alembic import op

revision = "0928_thumb_tai_lieu"
down_revision = "0927_tu_dong_nap_kien_thuc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.documents ADD COLUMN IF NOT EXISTS thumb_url text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE tenant_data.documents ADD COLUMN IF NOT EXISTS public_thumb_url text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.documents DROP COLUMN IF EXISTS public_thumb_url")
    op.execute("ALTER TABLE tenant_data.documents DROP COLUMN IF EXISTS thumb_url")
