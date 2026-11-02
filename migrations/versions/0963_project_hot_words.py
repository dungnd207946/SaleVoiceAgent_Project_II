"""bảng tenant_data.project_hot_words — hot word tách từ tên dự án

Lưu các từ KHÔNG PHẢI tiếng Việt (tiếng Anh, tiếng Pháp, hoặc thương hiệu tự
đặt bất kỳ) xuất hiện trong `projects.name`, để tìm kiếm/gợi ý theo từ khoá
thương hiệu — vd "THE MAGNOLIA - KHAI SƠN" tách ra "THE"/"MAGNOLIA" ("KHAI"/
"SƠN" là tiếng Việt, không lưu). Thuật toán tách ở
`portal.modules.realestate.hot_words.extract_hot_words` (thuần Python, không
đụng DB); ghi/đồng bộ ở `repo.dong_bo_hot_word`, gọi từ `router.py` mỗi khi
tạo dự án hoặc đổi tên dự án.

`UNIQUE (tenant_id, hot_word)`: một hot word chỉ thuộc về ĐÚNG MỘT project mỗi
tenant — quyết định người dùng chốt khi hai project cùng tenant trùng từ:
project tạo/đổi tên TRƯỚC giữ quyền sở hữu, project sau `ON CONFLICT DO
NOTHING` (xem `repo.dong_bo_hot_word`), không giành lại được từ đó cho tới khi
project trước đổi tên hoặc bị xoá.

`project_id` trỏ thẳng `tenant_data.projects(id)` (không theo quy ước
composite-FK-qua-`project_code`` của `zones`/`media` ở `0400`) — người dùng
chốt tên cột `project_id`, và bảng này không cần join theo mã dự án ở đâu cả.

Revision ID: 0963_project_hot_words
Revises: 0962_rls_agent_heartbeats
"""

from alembic import op

revision = "0963_project_hot_words"
down_revision = "0962_rls_agent_heartbeats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_data.project_hot_words (
            id bigserial PRIMARY KEY,
            tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            project_id bigint NOT NULL REFERENCES tenant_data.projects(id) ON DELETE CASCADE,
            hot_word text NOT NULL CHECK (hot_word <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT project_hot_words_tenant_word_key UNIQUE (tenant_id, hot_word)
        )
        """
    )
    op.execute(
        "CREATE INDEX project_hot_words_tenant_project_idx ON tenant_data.project_hot_words (tenant_id, project_id)"
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.project_hot_words')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.project_hot_words")
