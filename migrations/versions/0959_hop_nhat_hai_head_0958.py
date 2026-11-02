"""hợp nhất hai head `0958` — analyze_projects SQL-RO × kb_files nhận `md`

Hai migration cùng nhận `0957_hop_nhat_hai_head` làm cha, viết song song trên
hai nhánh:
  * `0958_analyze_projects_sql_ro` — 2 view + 2 role sandbox cho tool SQL của agent
  * `0958_kb_files_nhan_md`        — nới CHECK `kb_files.loai` để nhận `md`

Tên tệp khác nhau nên git merge sạch; chỉ `alembic upgrade head` thấy, và nó
chết ngay ở bước phân giải mục tiêu trước khi chạy một dòng DDL nào.

Giao của hai tập đối tượng là rỗng — một bên dựng view trên
`tenant_data.projects`/`units` cùng hai role cluster, bên kia đổi đúng một CHECK
constraint trên `tenant_data.kb_files`. Thứ tự áp nào cũng ra cùng lược đồ.

Thân rỗng là chủ ý, và KHÔNG đổi `down_revision` của nhánh nào (luật `0920`).

Revision ID: 0959_hop_nhat_hai_head
Revises: 0958_analyze_projects_sql_ro, 0958_kb_files_nhan_md
"""

revision = "0959_hop_nhat_hai_head"
down_revision = ("0958_analyze_projects_sql_ro", "0958_kb_files_nhan_md")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
