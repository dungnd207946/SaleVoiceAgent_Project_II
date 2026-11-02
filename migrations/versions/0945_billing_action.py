"""action `billing.read` vào control.actions + role_actions

Vai trò là DỮ LIỆU (0104), không phải enum — nên thêm action là một migration, và
danh sách vai trò được cấp phải khai TRONG file này chứ không import từ portal.*
(migration cũ đổi nghĩa mỗi lần sổ đổi).

⚠ CẤP THEO TÊN, KHÔNG THEO ID: `control.roles.id` là chuỗi md5 (`r_<md5>`), không
phải hằng ổn định như `'owner'`/`'admin'` — hai id đó không tồn tại trong bảng
này. Tra theo `name = 'Quản trị'` rồi INSERT theo id thật tìm được, tránh việc
hardcode một md5 dễ vỡ nếu seed đổi. `roles.name` có UNIQUE toàn cục từ
`0105_roles_thoat_org` (tổ chức đã bỏ), nên câu SELECT dưới đây trả đúng 0 hoặc
1 hàng.

CHỈ CẤP CHO Quản trị — dữ liệu chi phí là dữ liệu nhạy cảm. Biên tập (soạn nội
dung), CSKH (chăm sóc khách hàng) và Người xem (chỉ đọc số liệu vận hành) đều
KHÔNG có lý do nghiệp vụ để xem hoá đơn. Đóng băng theo thời điểm 2026-08-20;
nới thêm vai trò sau là một migration một dòng, còn thu hẹp lại sau khi đã rò
rỉ thì không.

⚠ `group_name = 'operate'`, KHÔNG phải `'configure'`: `billing.read` là xem
CHỈ-ĐỌC (theo dõi chi phí), cùng loại với `overview.read`/`convos.read` —
`configure` là NHÓM ĐỔI CÀI ĐẶT (`agent_config.*`, `workspace.admin`), người đi
tìm "Xem chi phí" sẽ tìm ở đúng khu vực với "Xem Tổng quan", không ở khu cấu
hình. `sort_order` = 7, XẾP LIỀN SAU `appts.write` (6) — 13 hàng gốc của 0104
đánh số LIỀN 1..13 không có khe hở, nên chèn số 7 buộc phải NÂNG sort_order của
7 hàng còn lại (`catalog.*`, `agent_config.*`, `workspace.admin`, hiện 7..13)
lên 8..14. Làm việc nâng đó qua HAI bước phủ định (`-sort_order` rồi
`-sort_order + 1`) chứ không một `UPDATE ... SET sort_order = sort_order + 1`
trực tiếp: `sort_order` có `UNIQUE`, và Postgres kiểm ràng buộc UNIQUE theo
từng dòng ngay trong lúc thực thi UPDATE hàng loạt — tăng dần trực tiếp có thể
đụng độ tạm thời với dòng kế bên chưa kịp cập nhật (ví dụ dòng đang có 8 chưa
kịp thành 9 thì dòng 7 đã muốn thành 8). Đưa qua miền ÂM trước (âm của một tập
số nguyên khác nhau vẫn khác nhau — không đụng độ với nhau, và không đụng độ
với mọi giá trị dương hiện có) rồi đổi dấu lại là cách an toàn, không có trạng
thái trung gian trùng lặp.

Revision ID: 0945_billing_action
Revises: 0944_usage_events_portal_api
"""

from alembic import op

revision = "0945_billing_action"
down_revision = "0944_usage_events_portal_api"
branch_labels = None
depends_on = None

_TEN_VAI_TRO_DUOC_CAP = ("Quản trị",)
"""Đóng băng theo thời điểm 2026-08-20. Biên tập/CSKH/Người xem KHÔNG có — họ
không xem chi phí."""

_SORT_ORDER_BILLING_READ = 7
"""Ngay sau `appts.write` (6) — cùng nhóm `operate`. Đẩy 7..13 lên 8..14."""


def upgrade() -> None:
    # Nhường chỗ sort_order=7 cho billing.read: nâng 7..13 lên 8..14 an toàn
    # qua bước trung gian âm (xem lý giải ở docstring module).
    op.execute(
        f"UPDATE control.actions SET sort_order = -sort_order "
        f"WHERE sort_order >= {_SORT_ORDER_BILLING_READ} AND code <> 'billing.read'"
    )
    op.execute("UPDATE control.actions SET sort_order = -sort_order + 1 WHERE sort_order < 0")

    # group_name PHẢI thuộc {'operate','knowledge','configure'} — CHECK của
    # `0104_vai_tro_dong` chưa từng được nới, và không migration nào khác thêm
    # 'billing' vào tập đó. Dùng 'operate' — billing.read là xem chỉ-đọc, cùng
    # nhóm overview/convos/appts (brief gốc ghi 'billing' sẽ vỡ CHECK).
    op.execute(
        f"""INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)
           VALUES ('billing.read', 'operate', 'Xem Usage & Billing · chi phí',
                   'View usage & billing', {_SORT_ORDER_BILLING_READ})
           ON CONFLICT (code) DO NOTHING"""
    )
    for ten_vai_tro in _TEN_VAI_TRO_DUOC_CAP:
        op.execute(
            f"""INSERT INTO control.role_actions (role_id, action_code)
                SELECT id, 'billing.read' FROM control.roles WHERE name = '{ten_vai_tro}'
                ON CONFLICT DO NOTHING"""
        )


def downgrade() -> None:
    op.execute("DELETE FROM control.role_actions WHERE action_code = 'billing.read'")
    op.execute("DELETE FROM control.actions WHERE code = 'billing.read'")
    # Đưa 8..14 (13 hàng gốc bị đẩy lên lúc upgrade) về lại 7..13 — cùng kỹ
    # thuật hai bước phủ định, chiều ngược lại.
    op.execute(
        f"UPDATE control.actions SET sort_order = -sort_order WHERE sort_order >= {_SORT_ORDER_BILLING_READ + 1}"
    )
    op.execute("UPDATE control.actions SET sort_order = -sort_order - 1 WHERE sort_order < 0")
