"""Hai action màn «Dữ liệu ngoài»: `kb_web.read` (xem) · `kb_web.write` (sửa nguồn/chủ đề/lịch, chạy ngay).

Cùng khuôn `0956_audit_action`: vai trò là dữ liệu (0104), danh sách vai được cấp đóng băng
trong file. `group_name = 'knowledge'` — mục nav nằm trong khối Kiến thức. `sort_order` 16/17
nối cuối dãy 1..15 hiện có (`tests/modules/auth/test_vai_tro.py` canh dãy liền).

Cấp: đọc cho Quản trị · Biên tập · Người xem; ghi cho Quản trị · Biên tập (người làm nội dung
tự chỉnh nguồn/chủ đề). CSKH không có — màn không liên quan việc trực hội thoại.

Revision ID: 0972_kb_web_actions
Revises: 0971_kbweb_theo_tenant
"""

from alembic import op

revision = "0972_kb_web_actions"
down_revision = "0971_kbweb_theo_tenant"
branch_labels = None
depends_on = None

_ACTIONS = (
    ("kb_web.read", "Xem Dữ liệu ngoài", "View external data", 16, ("Quản trị", "Biên tập", "Người xem")),
    ("kb_web.write", "Cấu hình · chạy Dữ liệu ngoài", "Configure and run external data", 17, ("Quản trị", "Biên tập")),
)


def upgrade() -> None:
    for code, vi, en, order, roles in _ACTIONS:
        op.execute(
            f"""INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)
               VALUES ('{code}', 'knowledge', '{vi}', '{en}', {order})
               ON CONFLICT (code) DO NOTHING"""
        )
        for ten in roles:
            op.execute(
                f"""INSERT INTO control.role_actions (role_id, action_code)
                    SELECT id, '{code}' FROM control.roles WHERE name = '{ten}'
                    ON CONFLICT DO NOTHING"""
            )


def downgrade() -> None:
    for code, *_ in _ACTIONS:
        op.execute(f"DELETE FROM control.role_actions WHERE action_code = '{code}'")
        op.execute(f"DELETE FROM control.actions WHERE code = '{code}'")
