"""`control.users.avatar_seed` — seed avatar user TỰ CHỌN, NULL = suy từ `name`.

Màn «Hồ sơ & tuỳ chọn» cho user đổi avatar bằng cách chọn một seed ngẫu nhiên
trong lưới gợi ý (`GET /me/avatar-goi-y`). Chỉ lưu SEED, không lưu SVG: avatar
là hàm tất định của seed (`core/avatar.py`), lưu output là bản sao thứ hai sẽ
ôi khi đổi style — đúng lý do `initials` chưa bao giờ là cột (xem docstring
`UserOut.initials`).

Nullable, KHÔNG DEFAULT: NULL nghĩa là "chưa từng chọn" ⇒ avatar suy từ `name`
như trước migration này — mọi hàng cũ giữ nguyên diện mạo, không cần backfill.

Revision ID: 0952_avatar_seed
Revises: 0952_invites_khong_can_user

NỐI SAU `0952_invites_khong_can_user` (merge develop -> dungnd, 2026-08-24): hai
nhánh cùng mọc từ `0951_hop_nhat_hai_head` nên alembic thấy HAI head và mọi test
dùng fixture migrate đều đỏ ở `MultipleHeads`. Nối chuỗi chứ không thêm một
migration hợp nhất: hai bên chạm hai bảng khác nhau (`users.avatar_seed` ·
`invites`), không có thứ tự nào bắt buộc, và bên kia đã ở develop nên nó là
tổ tiên, không phải nhánh song song.
"""

from alembic import op

revision = "0952_avatar_seed"
down_revision = "0952_invites_khong_can_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.users ADD COLUMN avatar_seed text")


def downgrade() -> None:
    op.execute("ALTER TABLE control.users DROP COLUMN avatar_seed")
