"""action `audit.read` vào control.actions + role_actions

Vai trò là DỮ LIỆU (0104), không phải enum — nên thêm action là một migration, và
danh sách vai trò được cấp phải khai TRONG file này chứ không import từ portal.*
(cùng lý lẽ `0945_billing_action`).

⚠ CẤP THEO TÊN, KHÔNG THEO ID: `control.roles.id` là `r_<md5>`; `roles.name` UNIQUE
toàn cục từ `0105_roles_thoat_org`, nên câu SELECT dưới đây trả đúng 0 hoặc 1 hàng.

CHỈ CẤP CHO Quản trị — nhật ký là «ai đổi cái gì» của cả workspace; Biên tập/CSKH/
Người xem không có trách nhiệm giám sát. Đóng băng theo thời điểm 2026-08-25;
nới thêm là một migration một dòng.

`group_name = 'configure'` (CHECK của 0104 chỉ cho 'operate'|'knowledge'|'configure'):
~90% nội dung nhật ký là sự kiện nhóm configure (publish, khoá, thành viên, vai
trò) và PQ_01 §3.1 đặt «Quản trị xem toàn workspace» — người đi tìm «Xem nhật ký»
tìm ở khu quản trị. Khác 0945 (xếp `billing.read` vào `operate` vì chỉ-đọc):
ở đây chỗ NGƯỜI TÌM thắng chỗ đọc/ghi.

`sort_order = 15`: NỐI CUỐI. 0945 chen số 7 và phải đánh số lại 7 hàng qua bước
âm; ở đây 14 hàng đang là 1..14 liền, 15 là ô trống kế tiếp — không đụng hàng nào.
`tests/modules/auth/test_vai_tro.py` canh dãy `1..15` liền.

Revision ID: 0956_audit_action
Revises: 0955_hop_nhat_hai_head
"""

from alembic import op

revision = "0956_audit_action"
down_revision = "0955_hop_nhat_hai_head"
branch_labels = None
depends_on = None

_TEN_VAI_TRO_DUOC_CAP = ("Quản trị",)
"""Đóng băng theo thời điểm 2026-08-25."""

_SORT_ORDER_AUDIT_READ = 15
"""Ô trống kế tiếp sau 14 hàng hiện có (13 gốc + billing.read)."""


def upgrade() -> None:
    op.execute(
        f"""INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)
           VALUES ('audit.read', 'configure', 'Xem Nhật ký hoạt động',
                   'View audit log', {_SORT_ORDER_AUDIT_READ})
           ON CONFLICT (code) DO NOTHING"""
    )
    for ten_vai_tro in _TEN_VAI_TRO_DUOC_CAP:
        op.execute(
            f"""INSERT INTO control.role_actions (role_id, action_code)
                SELECT id, 'audit.read' FROM control.roles WHERE name = '{ten_vai_tro}'
                ON CONFLICT DO NOTHING"""
        )


def downgrade() -> None:
    op.execute("DELETE FROM control.role_actions WHERE action_code = 'audit.read'")
    op.execute("DELETE FROM control.actions WHERE code = 'audit.read'")
