"""control.invites sống được KHÔNG cần một hàng control.users

VÌ SAO. `user_id NOT NULL` là ràng buộc buộc "muốn có lời mời thì phải có sẵn một
tài khoản" — chính nó khiến `thanh_vien.moi` phải `tao_user` NGAY lúc mời, tức tạo
một tài khoản mang tên người chưa đồng ý gì. Yêu cầu "chỉ tạo tài khoản khi người
nhận bấm Tham gia" không sửa được mà không phá ràng buộc này.

`user_id UNIQUE` cũng đi: nó nghĩa "một người tối đa MỘT lời mời sống trong toàn hệ
thống", còn luồng mời người-đã-có-tài-khoản cần họ nhận mời từ nhiều workspace cùng lúc.

HAI CHỈ MỤC BỘ PHẬN CHỨ KHÔNG MỘT `UNIQUE (email, tenant_id)`. Postgres coi hai NULL
là KHÁC nhau trong chỉ mục UNIQUE, nên một chỉ mục duy nhất cho lọt hai token ĐĂNG KÝ
(tenant_id NULL) cho cùng một email — đúng cái `user_id UNIQUE` đang chặn. Chỉ mục bộ
phận thứ hai giữ lại lời hứa đó.

BACKFILL CHỨ KHÔNG XOÁ. 0107 nêu tiền lệ "hàng cũ tự hết" cho một tình huống KHÁC —
ở đó không có gì để backfill. Ở đây có: nhánh cũ của `thanh_vien.moi` gọi
`them_membership` TRƯỚC `ghi_loi_moi` trong CÙNG giao dịch, nên `role_id` luôn tra
được qua `memberships`. Xoá sạch hàng chưa dùng là giết link đang nằm trong hộp thư
người ta. `DELETE` cuối chỉ là lưới cho hàng mà membership đã bị gỡ tay.

Revision ID: 0952_invites_khong_can_user
Revises: 0951_hop_nhat_hai_head
"""

from alembic import op

revision = "0952_invites_khong_can_user"
down_revision = "0951_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.invites ADD COLUMN email text")
    op.execute("ALTER TABLE control.invites ADD COLUMN role_id text REFERENCES control.roles(id)")

    # `lower()` chứ không chép thẳng: CHECK bên dưới đòi chữ thường. `control.users.email`
    # ĐÃ có CHECK ép điều đó từ `0100` (`users_email_lower_check`) nên nguồn thật ra luôn
    # thường sẵn — `lower()` ở đây là PHÒNG THỦ DƯ, vô hại, và giữ lại: rẻ hơn tin một CHECK
    # ở bảng khác không bao giờ bị gỡ, và một hàng `users` lọt qua sai (di sản, import tay…)
    # không kéo theo một hàng `invites` sai lệch theo.
    op.execute(
        """UPDATE control.invites i SET email = lower(u.email)
             FROM control.users u WHERE u.id = i.user_id"""
    )
    op.execute(
        """UPDATE control.invites i SET role_id = m.role_id
             FROM control.memberships m
            WHERE m.user_id = i.user_id AND m.tenant_id = i.tenant_id"""
    )
    op.execute("DELETE FROM control.invites WHERE tenant_id IS NOT NULL AND role_id IS NULL")

    op.execute("ALTER TABLE control.invites ALTER COLUMN email SET NOT NULL")
    op.execute("ALTER TABLE control.invites ALTER COLUMN user_id DROP NOT NULL")
    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_user_id_key")

    op.execute(
        """CREATE UNIQUE INDEX invites_moi_ws_key ON control.invites (email, tenant_id)
             WHERE tenant_id IS NOT NULL"""
    )
    op.execute(
        """CREATE UNIQUE INDEX invites_dang_ky_key ON control.invites (email)
             WHERE tenant_id IS NULL"""
    )

    op.execute(
        """ALTER TABLE control.invites ADD CONSTRAINT invites_email_thuong
             CHECK (email = lower(email))"""
    )
    op.execute(
        """ALTER TABLE control.invites ADD CONSTRAINT invites_vai_tro_theo_pham_vi
             CHECK ((tenant_id IS NULL) = (role_id IS NULL))"""
    )
    op.execute(
        """ALTER TABLE control.invites ADD CONSTRAINT invites_dang_ky_co_user
             CHECK (tenant_id IS NOT NULL OR user_id IS NOT NULL)"""
    )


def downgrade() -> None:
    # Hàng `user_id IS NULL` không tồn tại được ở hình dạng cũ — xoá, không đoán.
    op.execute("DELETE FROM control.invites WHERE user_id IS NULL")
    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_dang_ky_co_user")
    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_vai_tro_theo_pham_vi")
    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_email_thuong")
    op.execute("DROP INDEX control.invites_dang_ky_key")
    op.execute("DROP INDEX control.invites_moi_ws_key")
    # Hai lời mời cho cùng một user không tồn tại được ở hình dạng cũ — giữ hàng mới nhất.
    op.execute(
        """DELETE FROM control.invites a USING control.invites b
            WHERE a.user_id = b.user_id AND a.created_at < b.created_at"""
    )
    op.execute("ALTER TABLE control.invites ADD CONSTRAINT invites_user_id_key UNIQUE (user_id)")
    op.execute("ALTER TABLE control.invites ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE control.invites DROP COLUMN role_id")
    op.execute("ALTER TABLE control.invites DROP COLUMN email")
