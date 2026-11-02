"""documents — khớp bảng của M4 với hợp đồng KB ingest

BẢN GỐC CỦA MIGRATION NÀY `CREATE TABLE tenant_data.documents`. Nó không còn làm thế.

Vì sao: `0500` được viết trên nhánh `develop` khi `tenant_data.documents` chưa ai dựng,
FK còn trỏ `projects (tenant_id, code)` — tên cột của migration 0004. Trong lúc đó nhánh
`dungnd` đã đưa M4 vào bằng `0400_kb_real_estate`, và **0400 dựng `documents` với đúng
hình dạng 02a**: cùng 9 cột, cùng CHECK `status`, FK đã trỏ `projects (tenant_id,
project_code)`. Hai migration cùng `CREATE TABLE` một bảng → cái chạy sau chết vì
`relation already exists`.

Chọn 0400 làm nơi sở hữu bảng, không phải 0500: `documents` có FK tổ hợp vào
`projects (tenant_id, project_code)`, mà cột `project_code` chỉ tồn tại SAU 0400. Để 0500
dựng bảng thì nó buộc phải chạy sau 0400 và lặp lại y nguyên định nghĩa ở đó — hai bản
sao của một schema là hai chỗ để quên sửa.

Còn lại đúng một khác biệt thật giữa hai bản, và nó được bù ở đây:
`documents_tenant_status_idx`. `source/query.py` lọc `status = 'published'` trên MỌI lần
đọc, nên thiếu index này là seq scan toàn bảng mỗi job ingest.

KHÔNG bù `file_url NOT NULL DEFAULT ''` (0400 để nullable): `service.py:44` đọc bằng
`row.get("file_url")` và nhánh presign chỉ chạy khi giá trị truthy — `NULL` và `''` đi
cùng một đường. Siết NOT NULL chỉ để hai bản giống nhau là sửa schema của M4 vì lý do
thẩm mỹ, trong khi code hai bên đều đã đúng.

Revision ID: 0500_kb_documents
Revises: 0103_user_ho_so_invite
"""

from alembic import op

revision = "0500_kb_documents"
# Nối vào head THẬT của nhánh này. Bản gốc ghi "0101_memberships" vì trên `develop` đó là
# head; sau merge, giữ nguyên là fork chuỗi revision thành hai head và `alembic upgrade
# head` chết với "Multiple head revisions are present" — một lỗi git merge không hề báo.
down_revision = "0103_user_ho_so_invite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS: DB nào đã chạy bản 0500 cũ (dựng bảng + cả hai index) vẫn nâng cấp
    # được, không phải sửa tay bảng alembic_version.
    op.execute("CREATE INDEX IF NOT EXISTS documents_tenant_status_idx ON tenant_data.documents (tenant_id, status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tenant_data.documents_tenant_status_idx")
