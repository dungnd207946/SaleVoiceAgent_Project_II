"""Xoá control.organizations — bước B của việc bỏ tầng tổ chức

Spec: docs/superpowers/specs/2026-08-15-bo-organization-design.md §3, §9
Plan: docs/superpowers/plans/2026-08-15-bo-organization.md Task 2

`created_by` VỪA THAY `org_id` LÀM PHẠM VI CHO RÀNG BUỘC TÊN, VỪA TRẢ LỜI "AI MỞ
WORKSPACE NÀY" — câu mà `org_id` trước đây trả lời mơ hồ. Tên duy nhất theo NGƯỜI
TẠO chứ không toàn cục: sau khi mở tự đăng ký, hai người lạ đặt tên "Test" là
chuyện bình thường, và duy nhất toàn cục sẽ 409 vào mặt người thứ hai.

BACKFILL NỔ NẾU KHÔNG CÓ OWNER: dữ liệu ở trạng thái đó không có câu trả lời
đúng, và im lặng gán bừa là tạo ra một chủ sở hữu sai mà không ai phát hiện.

`audit_log_co_pham_vi_check` = CHECK (tenant_id IS NOT NULL OR org_id IS NOT
NULL) — "mỗi dòng nhật ký phải có ít nhất một phạm vi". Bỏ `org_id` mà giữ CHECK
thì nó rút thành `tenant_id IS NOT NULL`, và MỌI dòng cũ có phạm vi tổ chức
(tenant_id NULL, org_id có) lập tức vi phạm. Chọn DROP CHECK chứ không backfill
`tenant_id`: những dòng đó ghi lại hành động cấp hệ thống (tạo user, sửa vai trò)
vốn KHÔNG thuộc workspace nào, và gán bừa chúng vào một workspace là làm hỏng
nhật ký để chiều một ràng buộc. `tenant_id IS NULL` từ nay đọc là "hành động
không thuộc workspace nào".

⚠ DOWNGRADE KHÔNG PHẢI ĐƯỜNG LÙI CHO PRODUCTION: nó gom MỌI workspace về một tổ
chức `noble`, và `UNIQUE (org_id, id)` cũ dựng lại được nhưng ràng buộc tên theo
tổ chức thì không — sau upgrade, hai người khác nhau có thể đã đặt trùng tên hợp
lệ. Chỉ dùng được ngay sau `upgrade` trên máy dev.

Revision ID: 0106_bo_organizations
Revises: 0105_roles_thoat_org
"""

from alembic import op

revision = "0106_bo_organizations"
down_revision = "0105_roles_thoat_org"
branch_labels = None
depends_on = None

_ORG_MAC_DINH = "noble"


def upgrade() -> None:
    # --- ① tenants.created_by ---------------------------------------------
    op.execute("ALTER TABLE control.tenants ADD COLUMN created_by text REFERENCES control.users(id)")
    # BACKFILL HAI BẬC. Bậc 1 là owner của tổ chức — câu trả lời đúng nhất, vì
    # trước bản này chỉ owner mới tạo được workspace.
    op.execute(
        """
        UPDATE control.tenants t
           SET created_by = (
                 SELECT u.id FROM control.users u
                  WHERE u.org_id = t.org_id AND u.org_role = 'owner'
                  ORDER BY u.created_at, u.id
                  LIMIT 1)
        """
    )
    # Bậc 2: thành viên cũ nhất CỦA CHÍNH WORKSPACE ĐÓ.
    #
    # Bậc này không phải chỗ chữa cháy — nó là câu trả lời đúng cho một trạng thái
    # có thật: `dev_seed` dựng org `havengroup` chỉ có một user `member` (không
    # owner nào), nên bậc 1 để lại NULL cho workspace `haven`. Với một workspace
    # mà không ai trong tổ chức là owner, "người trong chính workspace đó" xấp xỉ
    # "ai mở nó" sát hơn bất kỳ suy đoán nào khác — và nó giữ được bất biến thật
    # sự quan trọng: `created_by` luôn trỏ tới một người CÓ QUYỀN ở workspace đó.
    op.execute(
        """
        UPDATE control.tenants t
           SET created_by = (
                 SELECT m.user_id FROM control.memberships m
                  WHERE m.tenant_id = t.id
                  ORDER BY m.created_at, m.user_id
                  LIMIT 1)
         WHERE t.created_by IS NULL
        """
    )
    # Còn NULL nghĩa là workspace KHÔNG có owner tổ chức VÀ không có thành viên
    # nào — một workspace không ai vào được. Không có câu trả lời đúng cho nó, và
    # im lặng gán bừa là tạo ra một chủ sở hữu sai mà không ai phát hiện.
    op.execute(
        """
        DO $$
        DECLARE n int; ds text;
        BEGIN
          SELECT count(*), string_agg(id, ', ') INTO n, ds
            FROM control.tenants WHERE created_by IS NULL;
          IF n > 0 THEN
            RAISE EXCEPTION '0106: % workspace không suy được người tạo (không owner tổ chức, '
                            'không thành viên nào): %. Gán tay control.tenants.created_by '
                            'rồi chạy lại.', n, ds;
          END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE control.tenants ALTER COLUMN created_by SET NOT NULL")
    op.execute(
        """CREATE UNIQUE INDEX tenants_nguoi_tao_ten_key
             ON control.tenants (created_by, lower(btrim(name)))"""
    )

    # --- ② Gỡ org khỏi bốn bảng -------------------------------------------
    op.execute("DROP INDEX control.tenants_org_idx")
    op.execute("ALTER TABLE control.tenants DROP CONSTRAINT tenants_org_id_key")
    op.execute("ALTER TABLE control.tenants DROP COLUMN org_id")  # kéo theo tenants_org_id_fkey

    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_org_id_key")
    op.execute("ALTER TABLE control.users DROP COLUMN org_id")  # kéo theo users_org_id_fkey
    op.execute("ALTER TABLE control.users DROP COLUMN org_role")  # kéo theo users_org_role_check

    op.execute("ALTER TABLE control.audit_log DROP CONSTRAINT audit_log_co_pham_vi_check")
    op.execute("ALTER TABLE control.audit_log DROP COLUMN org_id")

    op.execute("ALTER TABLE control.memberships DROP COLUMN org_id")

    # --- ③ ------------------------------------------------------------------
    op.execute("DROP TABLE control.organizations")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.organizations (
            id         text PRIMARY KEY,
            name       text NOT NULL,
            lifecycle  text NOT NULL DEFAULT 'active'
                       CONSTRAINT organizations_lifecycle_check
                       CHECK (lifecycle IN ('active', 'suspended', 'closed')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"INSERT INTO control.organizations (id, name) VALUES ('{_ORG_MAC_DINH}', 'NobleX')")

    for bang in ("tenants", "users", "memberships"):
        op.execute(
            f"""ALTER TABLE control.{bang} ADD COLUMN org_id text
                  DEFAULT '{_ORG_MAC_DINH}'
                  REFERENCES control.organizations(id) ON DELETE CASCADE"""
        )
        op.execute(f"ALTER TABLE control.{bang} ALTER COLUMN org_id SET NOT NULL")
        op.execute(f"ALTER TABLE control.{bang} ALTER COLUMN org_id DROP DEFAULT")

    op.execute(
        f"""ALTER TABLE control.audit_log ADD COLUMN org_id text
              DEFAULT '{_ORG_MAC_DINH}' REFERENCES control.organizations(id) ON DELETE CASCADE"""
    )
    op.execute("ALTER TABLE control.audit_log ALTER COLUMN org_id DROP DEFAULT")
    op.execute(
        """ALTER TABLE control.audit_log ADD CONSTRAINT audit_log_co_pham_vi_check
             CHECK (tenant_id IS NOT NULL OR org_id IS NOT NULL)"""
    )

    op.execute("ALTER TABLE control.tenants ADD CONSTRAINT tenants_org_id_key UNIQUE (org_id, id)")
    op.execute("CREATE INDEX tenants_org_idx ON control.tenants (org_id)")
    op.execute("ALTER TABLE control.users ADD CONSTRAINT users_org_id_key UNIQUE (org_id, id)")
    op.execute(
        """ALTER TABLE control.users ADD COLUMN org_role text NOT NULL DEFAULT 'member'
             CONSTRAINT users_org_role_check CHECK (org_role IN ('owner', 'member'))"""
    )

    op.execute("DROP INDEX control.tenants_nguoi_tao_ten_key")
    op.execute("ALTER TABLE control.tenants DROP COLUMN created_by")
