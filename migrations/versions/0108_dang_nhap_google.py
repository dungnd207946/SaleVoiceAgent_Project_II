"""control.identities · nới bất biến mật khẩu của users

Spec: docs/superpowers/specs/2026-08-18-dang-nhap-google-oauth-design.md

HAI THỨ, MỘT MIGRATION — chúng là một thay đổi nghiệp vụ duy nhất ("người dùng
vào bằng tài khoản Google"). Tách ra thì có một trạng thái trung gian không chạy
được: bảng identities mà CHECK cũ còn nguyên nghĩa là không hàng users nào của
nhánh Google INSERT nổi.

VÌ SAO KHÔNG PHẢI MỘT CỘT `gmail` TRONG users (spec §2): `email` không phải khoá
của Google — `sub` mới là, và nó bất biến khi người dùng đổi email. Một cột email
thứ hai còn trùng lặp với `users.email` vốn đã UNIQUE; hai cột cho một sự thật là
một bug đang chờ lệch (cùng lý lẽ 0100 đã ghi khi từ chối cột `initials`).

Revision ID: 0108_dang_nhap_google
Revises: 0935_hop_nhat_hai_head
"""

from alembic import op

revision = "0108_dang_nhap_google"
down_revision = "0935_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ① Danh tính ngoài -------------------------------------------------
    # PRIMARY KEY (provider, subject) KHÔNG phải một UNIQUE thêm vào sau — nó LÀ
    # danh tính của hàng này, và nó là thứ duy nhất chặn hai user cùng chiếm một
    # tài khoản Google.
    #
    # `email_tai_provider` CHỈ để hiển thị và audit. KHÔNG đường nào được khớp
    # user bằng cột này: Google cho đổi email của tài khoản, nên khớp theo email
    # là để người đổi email mất sạch workspace. Cột tồn tại để trả lời "tài khoản
    # Google nào đang gắn vào đây" mà không phải gọi Google.
    #
    # UNIQUE (user_id, provider) chặn một user gắn hai tài khoản Google khác nhau
    # — nếu không, nhánh «liên kết» chạy hai lần là hai đường vào cùng một tài
    # khoản mà chỉ một cái bị thu hồi khi gỡ.
    op.execute(
        """
        CREATE TABLE control.identities (
            provider    text NOT NULL
                        CONSTRAINT identities_provider_check CHECK (provider IN ('google')),
            subject     text NOT NULL
                        CONSTRAINT identities_subject_check CHECK (subject <> ''),
            user_id     text NOT NULL REFERENCES control.users(id) ON DELETE CASCADE,
            email_tai_provider text NOT NULL
                        CONSTRAINT identities_email_lower_check
                        CHECK (email_tai_provider = lower(email_tai_provider)),
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_login_at timestamptz,
            PRIMARY KEY (provider, subject)
        )
        """
    )
    op.execute("CREATE INDEX identities_user_id_idx ON control.identities(user_id)")
    op.execute("CREATE UNIQUE INDEX identities_mot_provider_moi_user ON control.identities(user_id, provider)")
    # portal_api chỉ cần bốn quyền này — cùng khuôn mọi bảng control khác.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON control.identities TO portal_api")

    # --- ② Nới bất biến mật khẩu ------------------------------------------
    # CHECK cũ là SONG ĐIỀU KIỆN và giữ HAI lời hứa cùng lúc (0103 ghi rõ):
    #   ① pending mà đã có hash  -> thư mời còn sống sau khi mật khẩu đã đặt
    #   ② active  mà chưa có hash -> tài khoản đăng nhập được không cần mật khẩu
    #
    # Ràng buộc mới giữ ①. Lời hứa ② KHÔNG đặt được bằng CHECK vì nó phải nhìn
    # sang control.identities, và CHECK của Postgres không làm được điều đó.
    #
    # ⚠ ĐÂY LÀ MỘT SỰ NỚI THẬT, không phải viết lại cho gọn: sau migration này DB
    # cho phép một hàng `active` không mật khẩu và không identity — một tài khoản
    # không đường nào vào. Vô hại (không ai đăng nhập được) nhưng là rác. Lời hứa
    # ② từ nay do `tests/modules/auth/test_migration_google.py` giữ, KHÔNG do DB.
    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_password_theo_lifecycle_check")
    op.execute(
        """ALTER TABLE control.users ADD CONSTRAINT users_co_duong_dang_nhap_check
             CHECK (lifecycle <> 'pending' OR password_hash IS NULL)"""
    )


def downgrade() -> None:
    """Ngược đúng thứ tự upgrade().

    XOÁ user không mật khẩu TRƯỚC khi đặt lại CHECK cũ: họ là hợp lệ dưới ràng
    buộc mới và vi phạm ràng buộc cũ, nên ALTER sẽ nổ và downgrade dừng giữa
    đường. Cùng lỗi mà 0103 đã xử ở nhánh `pending`.

    Lọc `lifecycle <> 'pending'`, KHÔNG `lifecycle = 'active'`: CHECK mới
    `users_co_duong_dang_nhap_check` cho `suspended` + NULL đi qua cùng lúc với
    `active` + NULL (nó chỉ chặn đúng một trường hợp — `pending` mà không mật
    khẩu). Một user Google bị admin đình chỉ (spec §7b) chính là hàng
    `suspended` + NULL đó, và nó CÓ THẬT — lọc theo `active` để sót nó lại, rồi
    ALTER ADD CONSTRAINT ngay dưới nổ `CheckViolationError` trên đúng hàng đó.

    ⚠ NÓI THẲNG câu DELETE này xoá gì: nó xoá VĨNH VIỄN mọi user CHỈ-ĐĂNG-NHẬP-
    BẰNG-GOOGLE (`active`/`suspended` mà `password_hash IS NULL` — đúng và duy
    nhất tập hợp tài khoản mà tính năng này tạo ra), CASCADE luôn hàng
    `control.identities` của họ. Không có mật khẩu để "cứu lại" bằng cách khác
    — sau downgrade này họ mất quyền truy cập, không cách nào tự phục hồi mà
    không tạo lại tài khoản. Ai chạy `alembic downgrade` trên production nên
    biết điều này TRƯỚC khi bấm, không phải sau khi phát hiện người dùng biến mất.
    """
    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_co_duong_dang_nhap_check")
    op.execute("DELETE FROM control.users WHERE lifecycle <> 'pending' AND password_hash IS NULL")
    op.execute(
        """ALTER TABLE control.users ADD CONSTRAINT users_password_theo_lifecycle_check
             CHECK ((lifecycle = 'pending') = (password_hash IS NULL))"""
    )
    op.execute("DROP TABLE control.identities")
