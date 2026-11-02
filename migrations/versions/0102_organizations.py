"""control.organizations — tầng tổ chức trên tenants

Spec: docs/superpowers/specs/2026-08-03-organization-layer-design.md

VÌ SAO THÊM BẢNG MỚI CHỨ KHÔNG SỬA `tenants.id`: `tenants.id` đang gánh bốn vai
cùng lúc — policy RLS, TENANT_ID của agent pod, đường dẫn `tenants/<id>/` trên
kho tệp, tên collection `kb_<id>`. Đây đúng là đường lùi mà 0002 đã ghi sẵn
trong header ("thêm bảng PHÍA TRÊN tenants, không sửa tenants").

`org_id` DỪNG Ở SCHEMA control. Nó không xuống tenant_data và không vào
portal.current_tenant(): khoá cách ly vẫn là tenant_id, đúng một khoá. Nhờ vậy
migration này không phải sửa một policy RLS nào, và agent pod không biết tổ chức
tồn tại.

COMPOSITE FK trên memberships là điểm chính của migration. Ràng buộc "user và
tenant phải cùng tổ chức" nếu chỉ cài trong service thì psql tay, seed script và
chính các migration sau đều đi vòng qua được. Đặt vào FK thì dòng sai KHÔNG CHÈN
ĐƯỢC, không cần trigger, không cần ai nhớ.

`UNIQUE (org_id, id)` trên tenants/users KHÔNG thêm ràng buộc duy nhất nào mới
(id đã là PK) — nó tồn tại chỉ để làm đích hợp lệ cho hai FK ghép đôi đó.

BACKFILL: mọi tenant/user đang có được gán vào org `noble` (NobleX vận hành hệ
thống, nên đây là câu trả lời đúng cho dữ liệu đã tồn tại). Bức tranh đầy đủ —
tenant nào thuộc org nào, ai là owner — do scripts/dev_seed.py khai, không phải
migration.
"""

from alembic import op

revision = "0102_organizations"
down_revision = "0401_agent_api_bds"
branch_labels = None
depends_on = None

# Cùng biểu thức với tenants_id_check ở 0002. Không nới lỏng: org_id chưa đi vào
# tên role hay đường dẫn nào, nhưng giữ một hình dạng định danh cho cả hệ thống
# rẻ hơn nhiều so với việc sau này phát hiện ra nó cần.
_ID_CHECK = "^[a-z][a-z0-9_]{1,30}$"

# Org nhận toàn bộ dữ liệu đã tồn tại. Xem docstring.
_ORG_MAC_DINH = "noble"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE control.organizations (
            id         text PRIMARY KEY
                       CONSTRAINT organizations_id_check CHECK (id ~ '{_ID_CHECK}'),
            name       text NOT NULL,
            lifecycle  text NOT NULL DEFAULT 'active'
                       CONSTRAINT organizations_lifecycle_check
                       CHECK (lifecycle IN ('active', 'suspended', 'closed')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"INSERT INTO control.organizations (id, name) VALUES ('{_ORG_MAC_DINH}', 'NobleX')")

    # --- tenants ---------------------------------------------------------
    # ON DELETE CASCADE: xoá tổ chức là xoá cả workspace lẫn người của nó. Không
    # có nghĩa nào khác — một tenant mồ côi org thì NOT NULL cũng không cho tồn tại.
    op.execute(
        """ALTER TABLE control.tenants ADD COLUMN org_id text
             REFERENCES control.organizations(id) ON DELETE CASCADE"""
    )
    op.execute(f"UPDATE control.tenants SET org_id = '{_ORG_MAC_DINH}' WHERE org_id IS NULL")
    op.execute("ALTER TABLE control.tenants ALTER COLUMN org_id SET NOT NULL")
    op.execute("ALTER TABLE control.tenants ADD CONSTRAINT tenants_org_id_key UNIQUE (org_id, id)")
    # "Mọi workspace của tổ chức này" là truy vấn của owner ở mỗi lần dựng session.
    op.execute("CREATE INDEX tenants_org_idx ON control.tenants (org_id)")

    # --- users -----------------------------------------------------------
    # org_role là quyền TRÊN tổ chức, tách hẳn memberships.role (quyền TRONG một
    # workspace). Không suy ra nhau: admin của một workspace không vì thế mà
    # quản được workspace khác.
    op.execute(
        """ALTER TABLE control.users ADD COLUMN org_id text
             REFERENCES control.organizations(id) ON DELETE CASCADE"""
    )
    op.execute(
        """ALTER TABLE control.users ADD COLUMN org_role text NOT NULL DEFAULT 'member'
           CONSTRAINT users_org_role_check CHECK (org_role IN ('owner', 'member'))"""
    )
    op.execute(f"UPDATE control.users SET org_id = '{_ORG_MAC_DINH}' WHERE org_id IS NULL")
    op.execute("ALTER TABLE control.users ALTER COLUMN org_id SET NOT NULL")
    op.execute("ALTER TABLE control.users ADD CONSTRAINT users_org_id_key UNIQUE (org_id, id)")

    # --- memberships -----------------------------------------------------
    op.execute("ALTER TABLE control.memberships ADD COLUMN org_id text")
    op.execute(
        """UPDATE control.memberships m SET org_id = u.org_id
             FROM control.users u WHERE u.id = m.user_id"""
    )
    op.execute("ALTER TABLE control.memberships ALTER COLUMN org_id SET NOT NULL")
    # FK đơn cột cũ bị thay, không phải bị bỏ: composite FK bao trùm chúng (vẫn
    # tham chiếu users.id / tenants.id, vẫn ON DELETE CASCADE) và còn chặn thêm
    # trường hợp lệch tổ chức. Giữ cả hai là hai FK trùng nghĩa trên cùng một cột.
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_user_id_fkey")
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_tenant_id_fkey")
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_org_user_fkey
             FOREIGN KEY (org_id, user_id) REFERENCES control.users (org_id, id) ON DELETE CASCADE"""
    )
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_org_tenant_fkey
             FOREIGN KEY (org_id, tenant_id) REFERENCES control.tenants (org_id, id) ON DELETE CASCADE"""
    )


def downgrade() -> None:
    """Ngược đúng thứ tự upgrade(). Dữ liệu org bị mất — không có chỗ nào giữ nó."""
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_org_tenant_fkey")
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_org_user_fkey")
    op.execute(
        """ALTER TABLE control.memberships ADD CONSTRAINT memberships_user_id_fkey
             FOREIGN KEY (user_id) REFERENCES control.users(id) ON DELETE CASCADE"""
    )
    op.execute(
        """ALTER TABLE control.memberships ADD CONSTRAINT memberships_tenant_id_fkey
             FOREIGN KEY (tenant_id) REFERENCES control.tenants(id) ON DELETE CASCADE"""
    )
    op.execute("ALTER TABLE control.memberships DROP COLUMN org_id")

    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_org_id_key")
    op.execute("ALTER TABLE control.users DROP COLUMN org_role")
    op.execute("ALTER TABLE control.users DROP COLUMN org_id")

    op.execute("DROP INDEX control.tenants_org_idx")
    op.execute("ALTER TABLE control.tenants DROP CONSTRAINT tenants_org_id_key")
    op.execute("ALTER TABLE control.tenants DROP COLUMN org_id")

    op.execute("DROP TABLE control.organizations")
