"""Bù DDL của 0952_invites_khong_can_user cho DB đã áp 0952_avatar_seed trước khi chuỗi bị viết lại

VÌ SAO CẦN MIGRATION NÀY. `0952_avatar_seed` ra đời với `down_revision =
"0951_hop_nhat_hai_head"` (commit 6e822f0) và ĐÃ ĐƯỢC ÁP ở dạng đó trên UAT. Commit
b585139 ("fix conflict") sau đó nhét `0952_invites_khong_can_user` vào GIỮA 0951 và
0952_avatar_seed. Alembic coi MỌI tổ tiên của revision hiện tại là đã áp, nên trên những
DB đó `alembic upgrade head` là NO-OP vĩnh viễn: `version_num` đã là `0952_avatar_seed`
trong khi `control.invites` vẫn ở hình dạng TRƯỚC 0952 — không `email`, không `role_id`.
Triệu chứng thấy ở UAT 2026-08-24: `GET /api/v1/members` trả 500 với
`asyncpg.exceptions.UndefinedColumnError: column i.role_id does not exist`.

`tests/unit/test_alembic_mot_head.py` đã ghi đúng luật bị vi phạm — hợp nhất hai head bằng
MERGE REVISION, "KHÔNG bằng cách đổi `down_revision`". Đổi `down_revision` của một revision
ĐÃ PHÁT HÀNH là hỏng im lặng: không lỗi, không cảnh báo, chỉ một migration lặng lẽ không
bao giờ chạy, và chỉ ở những env đã kịp áp revision cũ. Máy dev dựng DB từ base sau b585139
chạy trọn chuỗi đúng thứ tự nên KHÔNG ai thấy gì.

VÌ SAO CÓ CỔNG CHỨ KHÔNG CHẠY THẲNG. Cùng một commit phải đúng cho HAI hình dạng DB:

  · DB dựng sau b585139 (mọi máy dev, mọi env dựng lại từ base) — 0952 đã chạy tử tế, cột
    đã có ⇒ migration này phải KHÔNG làm gì. Chạy thẳng sẽ nổ ngay dòng đầu
    ("column email of relation invites already exists") và làm đỏ cả lần deploy.
  · DB đã áp 0952_avatar_seed trước b585139 (UAT, và PHẢI KIỂM cả production) — cột chưa
    có ⇒ chạy đúng DDL của 0952.

Cổng đọc `information_schema` chứ KHÔNG đọc `alembic_version`: câu hỏi thật là "cột có
chưa", và chỉ schema trả lời được. Bảng version ở đúng những DB cần vá đang NÓI SAI — tin
nó là cách đã dẫn tới lỗi này ngay từ đầu.

DDL bên dưới sao Y NGUYÊN `0952_invites_khong_can_user.upgrade()`, kể cả `DELETE` cuối và
`lower()` phòng thủ dư. Trùng lặp là CỐ Ý: hai đường phải hạ cánh xuống CÙNG một schema,
và một bản sao đọc được tại chỗ rẻ hơn một lần import động qua tên module mở đầu bằng số.
Sửa một bên mà quên bên kia là hai env lệch schema — nên đừng sửa bên nào: cả hai là bản
ghi lịch sử, thay đổi hành vi thì viết revision mới.

Revision ID: 0953_bu_invites_role_id
Revises: 0952_avatar_seed
"""

from alembic import op

revision = "0953_bu_invites_role_id"
down_revision = "0952_avatar_seed"
branch_labels = None
depends_on = None


def _da_co_role_id() -> bool:
    """Đọc SCHEMA, không đọc `alembic_version` — xem docstring module."""
    return bool(
        op.get_bind()
        .exec_driver_sql(
            """SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'control'
                  AND table_name = 'invites'
                  AND column_name = 'role_id'"""
        )
        .scalar()
    )


def upgrade() -> None:
    if _da_co_role_id():
        return

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
    """Cố ý KHÔNG làm gì.

    Hai cột thuộc `0952_invites_khong_can_user`; `downgrade()` của NÓ mới là chỗ gỡ chúng,
    và nó vẫn nằm dưới revision này trong chuỗi nên vẫn chạy tới. Gỡ ở đây là xoá cột mà
    một revision khác đang khai sở hữu — và với DB đã chạy 0952 tử tế thì `upgrade()` ở
    trên chưa chạm gì để mà hoàn tác.
    """
