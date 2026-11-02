"""control.users hồ sơ tuỳ chọn · lifecycle 'pending' · control.invites

Spec: docs/superpowers/specs/2026-08-03-m2b-tao-sua-user-design.md

BỐN THỨ, MỘT MIGRATION — chúng là một thay đổi nghiệp vụ duy nhất ("admin tạo
user, người đó tự đặt mật khẩu"), và tách ra thành bốn revision thì có ba trạng
thái trung gian mà không trạng thái nào chạy được: `pending` không có bảng invite
là một user không đường nào vào, còn bảng invite không có `pending` thì không có
gì để mời.

VÌ SAO `password_hash` ĐƯỢC PHÉP NULL: M2a viết nó NOT NULL vì lúc đó user chỉ
sinh ra từ seed script, và seed thì luôn có mật khẩu. Thư mời đảo điều đó —
hàng users tồn tại TRƯỚC khi có mật khẩu. Nới NOT NULL mà không thêm gì là mở
đường cho một user `active` không mật khẩu; xem CHECK song điều kiện ở dưới.
"""

from alembic import op

revision = "0103_user_ho_so_invite"
down_revision = "0900_enrollment"
branch_labels = None
depends_on = None

# 7 ngày. Đủ dài để qua một kỳ nghỉ, đủ ngắn để một link rơi ra ngoài không sống
# mãi. Hằng số ở đây CHỈ để đọc — service.py giữ bản dùng thật (không có đường
# nào cho code đọc hằng số của một migration).
_HAN_MOI_NGAY = 7


def upgrade() -> None:
    # --- ① Hồ sơ tuỳ chọn -------------------------------------------------
    # Nullable, không DEFAULT '': '' và NULL cùng nghĩa "không có" thì có hai
    # cách viết cho một sự thật, và mọi truy vấn sau phải kiểm cả hai.
    op.execute("ALTER TABLE control.users ADD COLUMN phone text")
    op.execute("ALTER TABLE control.users ADD COLUMN job_title text")

    # --- ② lifecycle thêm 'pending' ---------------------------------------
    # Từ vựng vẫn khớp tenants.lifecycle ở những giá trị chung (0100 đã ghi lý
    # lẽ đó). 'pending' là giá trị RIÊNG của users: một tổ chức không "chờ được
    # tạo" — nó được enrollment tạo xong mới tồn tại.
    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_lifecycle_check")
    op.execute(
        """ALTER TABLE control.users ADD CONSTRAINT users_lifecycle_check
             CHECK (lifecycle IN ('pending', 'active', 'suspended'))"""
    )

    # --- ③ password_hash NULL ĐÚNG KHI VÀ CHỈ KHI pending -----------------
    # SONG ĐIỀU KIỆN, không phải một chiều. Nó chặn hai trạng thái vô nghĩa cùng
    # lúc:
    #   - pending mà đã có hash  -> thư mời còn sống sau khi mật khẩu đã đặt
    #   - active  mà chưa có hash -> tài khoản đăng nhập được không cần mật khẩu
    # Cái thứ hai là một cửa hậu, và một CHECK một chiều sẽ để nó lọt.
    op.execute("ALTER TABLE control.users ALTER COLUMN password_hash DROP NOT NULL")
    op.execute(
        """ALTER TABLE control.users ADD CONSTRAINT users_password_theo_lifecycle_check
             CHECK ((lifecycle = 'pending') = (password_hash IS NULL))"""
    )

    # --- ④ Thư mời --------------------------------------------------------
    # token_hash là PK: chỉ lưu sha256, không lưu token thô. Cùng lý lẽ với
    # password_hash — người đọc được DB không dùng được thư mời.
    #
    # user_id UNIQUE: mỗi user tối đa MỘT thư mời còn sống. «Mời lại» ghi đè bằng
    # ON CONFLICT (user_id) DO UPDATE, nên token trước chết ngay. Không UNIQUE thì
    # mỗi lần bấm «Mời lại» sinh thêm một token dùng được, và thu hồi thành việc
    # phải xoá n hàng mà không ai biết n bằng mấy.
    #
    # COMPOSITE FK (org_id, user_id) chứ không FK đơn cột: cùng lý lẽ 0102 đã ghi
    # cho memberships. org_id trên hàng invite phải khớp org của user, và ràng
    # buộc đó chỉ thật khi nằm ở FK — trong service thì psql tay đi vòng được.
    #
    # created_by NULLABLE + ON DELETE SET NULL: xoá người mời KHÔNG được xoá thư
    # mời của người được mời. Hai chuyện khác nhau, và CASCADE gộp chúng lại.
    op.execute(
        """
        CREATE TABLE control.invites (
            token_hash text PRIMARY KEY
                       CONSTRAINT invites_token_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            user_id    text NOT NULL UNIQUE,
            org_id     text NOT NULL,
            expires_at timestamptz NOT NULL,
            used_at    timestamptz,
            created_by text REFERENCES control.users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT invites_org_user_fkey
                FOREIGN KEY (org_id, user_id) REFERENCES control.users (org_id, id) ON DELETE CASCADE
        )
        """
    )

    # --- ⑤ audit_log ghi được hành động cấp tổ chức -----------------------
    # 0201 viết tenant_id NOT NULL vì mọi thứ ghi nhật ký lúc đó đều thuộc một
    # workspace. «Tạo một user org_role='owner'» thì KHÔNG — nó không có tenant
    # nào, và không có giá trị nào hợp lệ để điền. Chèn '' thì vỡ FK.
    #
    # CHECK giữ lời hứa còn lại: nới NOT NULL mà không thêm gì là mở đường cho
    # một hàng nhật ký không thuộc phạm vi nào — tức một hàng mà không màn hình
    # nào của M8 tìm thấy.
    op.execute("ALTER TABLE control.audit_log ALTER COLUMN tenant_id DROP NOT NULL")
    op.execute(
        """ALTER TABLE control.audit_log ADD COLUMN org_id text
             REFERENCES control.organizations(id) ON DELETE CASCADE"""
    )
    op.execute(
        """ALTER TABLE control.audit_log ADD CONSTRAINT audit_log_co_pham_vi_check
             CHECK (tenant_id IS NOT NULL OR org_id IS NOT NULL)"""
    )
    # 0201 đã REVOKE UPDATE/DELETE của portal_api trên audit_log — ADD COLUMN
    # không cấp lại quyền nào, nên bảng vẫn CHỈ-GHI-THÊM. Không phải revoke lại.


def downgrade() -> None:
    """Ngược đúng thứ tự upgrade().

    User `pending` bị XOÁ, không phải chuyển thành `active`: họ chưa có mật khẩu,
    nên `active` sẽ vi phạm chính CHECK mà 0100 đặt lại ở đây (password_hash NOT
    NULL). Xoá là câu trả lời duy nhất không tạo ra một hàng không đăng nhập được.
    """
    op.execute("ALTER TABLE control.audit_log DROP CONSTRAINT audit_log_co_pham_vi_check")
    # Hàng nhật ký cấp org không có tenant_id để điền — xoá trước khi đặt lại
    # NOT NULL, nếu không ALTER nổ và downgrade dừng giữa đường.
    op.execute("DELETE FROM control.audit_log WHERE tenant_id IS NULL")
    op.execute("ALTER TABLE control.audit_log DROP COLUMN org_id")
    op.execute("ALTER TABLE control.audit_log ALTER COLUMN tenant_id SET NOT NULL")

    op.execute("DROP TABLE control.invites")

    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_password_theo_lifecycle_check")
    op.execute("DELETE FROM control.users WHERE lifecycle = 'pending'")
    op.execute("ALTER TABLE control.users ALTER COLUMN password_hash SET NOT NULL")

    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_lifecycle_check")
    op.execute(
        """ALTER TABLE control.users ADD CONSTRAINT users_lifecycle_check
             CHECK (lifecycle IN ('active', 'suspended'))"""
    )

    op.execute("ALTER TABLE control.users DROP COLUMN job_title")
    op.execute("ALTER TABLE control.users DROP COLUMN phone")
