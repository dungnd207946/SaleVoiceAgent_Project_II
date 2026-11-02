"""tenant_data.conversations — thêm cột `full_conversation`

VẤN ĐỀ NÓ GIẢI: bảng `conversations` (0903) chỉ giữ `summary` — bản rút gọn agent tự
viết ra. Khi cần đối chiếu "agent đã thực sự nói gì ở phiên này" (khiếu nại của khách,
dò lỗi prompt, chấm chất lượng hội thoại) thì không còn nguồn nào để đọc: `summary` là
diễn giải, không phải bằng chứng.

VÌ SAO `jsonb` CHỨ KHÔNG PHẢI `text`: transcript là một DÃY lượt nói có vai
(`[{"role": ..., "content": ..., "at": ...}, ...]`), không phải một khối chữ. Lưu `text`
thì mọi câu hỏi dạng "lượt cuối của khách là gì", "có lượt nào gọi skill X không" đều
phải parse lại ở tầng ứng dụng, và mỗi nơi parse một kiểu. `skill_calls` cùng bảng đã
là `jsonb` cho đúng lý do đó — cột này đi theo cùng hình dạng, không mở hình dạng thứ ba.

VÌ SAO `NOT NULL DEFAULT '[]'` CHỨ KHÔNG NULLABLE: "chưa có transcript" và "transcript
rỗng" là cùng một sự thật ở đây — không có lượt nói nào được ghi. Cho NULL vào là bắt
mọi chỗ đọc phải viết `COALESCE(full_conversation, '[]'::jsonb)`, và chỗ nào quên thì
lỗi chỉ lộ ra trên đúng những hàng cũ. Giống hệt lựa chọn của `skill_calls` (0903).

KHÔNG REWRITE BẢNG: Postgres 11+ ghi DEFAULT hằng vào catalog, `ADD COLUMN ... NOT NULL
DEFAULT` là thao tác metadata — 11 hàng hiện có không bị viết lại và không có
ACCESS EXCLUSIVE kéo dài.

KHÔNG CẦN GRANT LẠI CHO AGENT: `control.grant_agent_write()` (0005/0905) cấp
`GRANT SELECT, INSERT, UPDATE ON <bảng>` — quyền mức BẢNG, nên cột mới nằm trong đó
sẵn. Nếu ngày nào đó hàm ấy đổi sang grant mức CỘT thì migration thêm cột phải cấp lại
tay; ghi ở đây để lần sau ai đổi hàm biết chỗ này phụ thuộc vào nó.

Revision ID: 0912_full_conversation
Revises: 0911_tenant_id_gach_ngang
"""

from alembic import op

revision = "0912_full_conversation"
down_revision = "0911_tenant_id_gach_ngang"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_data.conversations
            ADD COLUMN full_conversation jsonb NOT NULL DEFAULT '[]'::jsonb
        """
    )


def downgrade() -> None:
    # DROP COLUMN xoá luôn transcript đã ghi — không có đường khôi phục từ `summary`.
    # Vẫn để nguyên như vậy: một downgrade "giữ lại dữ liệu" ở đây nghĩa là bỏ cột ra
    # khỏi schema nhưng vẫn chiếm chỗ, và đó là trạng thái không ai kiểm được.
    op.execute("ALTER TABLE tenant_data.conversations DROP COLUMN full_conversation")
