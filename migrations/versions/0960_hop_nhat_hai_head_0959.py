"""hợp nhất hai head `0959` — dọn bảng mồ côi × merge 0958 (analyze_projects × kb_files md)

`0959_don_bang_mo_coi` (xoá control.field_policy_live + billing.invoice/invoice_line
+ hai hàm portal.pol()/gated_extras()) và `0959_hop_nhat_hai_head` (merge node của
`0958_analyze_projects_sql_ro` × `0958_kb_files_nhan_md`) cùng nhận
`0958_analyze_projects_sql_ro` làm một trong hai cha — viết song song trên hai
nhánh (`dungnd` × `feat/kb-md-anh-ngoai`), cả hai merge sạch vào `develop` (tên
tệp khác nhau) nên chỉ `alembic upgrade head` thấy, đúng kịch bản đã ghi ở
`0920`: `docker compose run --rm migrate` chết ngay ở bước phân giải mục tiêu
với "Multiple head revisions", TRƯỚC khi chạy một dòng DDL nào — vỡ ở lần
deploy `develop` ngày 2026-09-08.

Giao của hai tập đối tượng là rỗng: một bên DROP ba bảng + hai hàm côi của M1,
bên kia chỉ là một merge node thân rỗng (đã tự merge xong `0958_kb_files_nhan_md`
— đổi CHECK trên `tenant_data.kb_files`, không chạm gì tới `control`/`billing`).
Thứ tự áp nào cũng ra cùng lược đồ.

Thân rỗng là chủ ý, và KHÔNG đổi `down_revision` của nhánh nào (luật `0920`).

Revision ID: 0960_hop_nhat_hai_head
Revises: 0959_don_bang_mo_coi, 0959_hop_nhat_hai_head
"""

revision = "0960_hop_nhat_hai_head"
down_revision = ("0959_don_bang_mo_coi", "0959_hop_nhat_hai_head")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
