"""hợp nhất hai head `0956` — audit.read action × đồng bộ lại RLS tenant_data

VÌ SAO CÓ TỆP NÀY: hai migration cùng gắn vào `0955_hop_nhat_hai_head` rồi cùng
được merge vào `develop`:
  * `0956_audit_action`               — action `audit.read`, chỉ chạm
    `control.actions`/`control.role_actions`
  * `0956_dong_bo_lai_rls_tenant_data` — dọn 2 policy RLS legacy còn sót trên
    9 bảng `tenant_data`, chỉ chạm `pg_policy` của schema `tenant_data`
Alembic không tự chọn giữa hai head, nên `alembic upgrade head` ở bước deploy
chết ngay từ lúc phân giải mục tiêu, TRƯỚC khi chạy bất kỳ DDL nào:
    FAILED: Multiple head revisions are present for given argument 'head'
Đúng lỗi đã làm job `migrate` của pipeline deploy đỏ (container
`odyssey-portal-backend-migrate-run-*`, exit ngay ở dòng `alembic upgrade head`,
không phải nội dung của một trong hai migration).

GIAO CỦA HAI TẬP ĐỐI TƯỢNG LÀ RỖNG, nên thứ tự áp nào cũng ra cùng một lược đồ
— đã đối chiếu DDL của cả hai: một bên chỉ INSERT vào `control.actions`/
`control.role_actions`, bên kia chỉ DROP/CREATE POLICY trên các bảng
`tenant_data.*`. Không bảng/cột/policy nào chung.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — cùng khuôn với
`0955_hop_nhat_hai_head_0954.py`, `0951_hop_nhat_hai_head_0950.py`,
`0943_hop_nhat_hai_head` và các bản trước. Không đổi `down_revision` của bất
kỳ nhánh nào (luật `0920`).

Revision ID: 0957_hop_nhat_hai_head
Revises: 0956_audit_action, 0956_dong_bo_lai_rls_tenant_data
"""

revision = "0957_hop_nhat_hai_head"
down_revision = ("0956_audit_action", "0956_dong_bo_lai_rls_tenant_data")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
