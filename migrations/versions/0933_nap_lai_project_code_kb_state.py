"""Chạy lại backfill `kb_index_state.project_code` của `0920` — bản đó xoá trắng vì RLS

`0920` thêm cột rồi backfill từ 4 bảng nguồn, kèm một comment nói rằng không cần set
`app.tenant_id` vì "chạy bằng portal_migrator (owner) nên không bị RLS". Comment đó SAI:
`control.enforce_tenant_isolation` bật `FORCE ROW LEVEL SECURITY`, và FORCE tồn tại đúng
để RLS áp CẢ cho chủ bảng (xem header `0003`). Nên trên môi trường thật — nơi migrator là
owner-KHÔNG-superuser — bốn câu UPDATE đó chạm 0 hàng và báo thành công. Local không lộ:
testcontainer đặt `portal_migrator` làm bootstrap superuser, mà superuser bỏ qua RLS bất kể
FORCE.

Hệ quả đang sống: mọi hàng `kb_index_state` có trước `0920` mang `project_code = ''`, nên
chỉ báo của tab kiến thức — lọc theo `(tenant_id, project_code)` — không thấy chúng.

Sửa `0920` tại chỗ không có tác dụng: alembic đã ghi nó là đã áp. Phải là một migration
mới. Idempotent: nơi nào backfill cũ đã đúng thì UPDATE ghi lại đúng giá trị đó.

Revision ID: 0933_nap_lai_project_code
Revises: 0932_hop_nhat_hai_head
"""

from alembic import op

revision = "0933_nap_lai_project_code"
down_revision = "0932_hop_nhat_hai_head"
branch_labels = None
depends_on = None

_BANG = (
    "tenant_data.kb_index_state",
    "tenant_data.projects",
    "tenant_data.zones",
    "tenant_data.documents",
    "tenant_data.media",
)


def _force_rls(bat: bool) -> None:
    for bang in _BANG:
        op.execute(f"ALTER TABLE {bang} {'FORCE' if bat else 'NO FORCE'} ROW LEVEL SECURITY")


def upgrade() -> None:
    _force_rls(False)
    # Chỉ chạm hàng còn rỗng: hàng đã có project_code là hàng ghi sau `0920` bởi chính app,
    # không việc gì phải viết lại.
    op.execute(
        """
        UPDATE tenant_data.kb_index_state s SET project_code = p.project_code
          FROM tenant_data.projects p
         WHERE s.entity = 'projects' AND s.record_id = p.id AND s.tenant_id = p.tenant_id
           AND s.project_code = ''
        """
    )
    for bang in ("zones", "documents", "media"):
        op.execute(
            f"""
            UPDATE tenant_data.kb_index_state s SET project_code = c.project_code
              FROM tenant_data.{bang} c
             WHERE s.entity = '{bang}' AND s.record_id = c.id AND s.tenant_id = c.tenant_id
               AND s.project_code = ''
            """
        )
    _force_rls(True)


def downgrade() -> None:
    """Không hoàn: giá trị trước đó là chuỗi rỗng do một backfill hỏng, không phải dữ liệu."""
