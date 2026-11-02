"""`kb_files.loai` nhận thêm `md`

Sổ tay khách soạn sẵn dạng Markdown, ảnh là URL tuyệt đối trên S3 của họ. Route upload
và `TextExtractor` đã cho `.md` qua từ commit trước, nhưng CHECK của bảng vẫn chỉ nhận
ba đuôi cũ — nên nếu thiếu migration này thì mọi lượt tải `.md` lên sẽ đi qua đúng phép
kiểm ở tầng app rồi chết ở `INSERT`, và người dùng nhận 500 thay vì một câu nói họ sai
chỗ nào.

⚠️ `downgrade` CÓ MẤT MÁT: hàng `loai='md'` phải bị xoá thì CHECK cũ mới dựng lại được.
Point Qdrant của những hàng đó KHÔNG được dọn theo — chúng thành mồ côi trong
`<slug>_documents` với `doc_type='kb_file'`. Chấp nhận: `downgrade` ở đây là đường thoát
hiểm khi triển khai hỏng, không phải một thao tác thường ngày, và giữ hàng lại thì
`downgrade` đơn giản là không chạy được.
"""

from alembic import op

revision = "0958_kb_files_nhan_md"
down_revision = "0957_hop_nhat_hai_head"
branch_labels = None
depends_on = None

_BANG = "tenant_data.kb_files"
_TEN = "kb_files_loai_check"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_BANG} DROP CONSTRAINT IF EXISTS {_TEN}")
    op.execute(f"ALTER TABLE {_BANG} ADD CONSTRAINT {_TEN} CHECK (loai = ANY (ARRAY['pdf', 'docx', 'xlsx', 'md']))")


def downgrade() -> None:
    # Xem cảnh báo mất mát ở docstring.
    op.execute(f"DELETE FROM {_BANG} WHERE loai = 'md'")
    op.execute(f"ALTER TABLE {_BANG} DROP CONSTRAINT IF EXISTS {_TEN}")
    op.execute(f"ALTER TABLE {_BANG} ADD CONSTRAINT {_TEN} CHECK (loai = ANY (ARRAY['pdf', 'docx', 'xlsx']))")
