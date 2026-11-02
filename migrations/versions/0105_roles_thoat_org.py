"""control.roles thoát khỏi organization — bước A của việc bỏ tầng tổ chức

Spec: docs/superpowers/specs/2026-08-15-bo-organization-design.md §3, §9
Plan: docs/superpowers/plans/2026-08-15-bo-organization.md Task 1

VÌ SAO DEDUP LÀ BẮT BUỘC, KHÔNG PHẢI PHÒNG THỦ: production chỉ có org `noble`
(4 hàng roles), nhưng `scripts/dev_seed.py` dựng HAI tổ chức — trên mọi máy dev
là 8 hàng, 4 cặp trùng tên. Bỏ `org_id` mà không dedup thì `UNIQUE (name)` nổ
ngay ở `make migrate`.

DEDUP GIỮ MA TRẬN ACTION CỦA HÀNG ĐƯỢC GIỮ VÀ VỨT CỦA HÀNG BỊ LOẠI. Hai org có
thể đã sửa vai trò cùng tên theo hai hướng khác nhau; ở dev cả hai là bản seed y
hệt nên không mất gì. RAISE NOTICE số hàng đã gộp để việc này hiện ra trong log,
không đi im lặng.

BA FK GHÉP TRÊN `memberships`, KHÔNG PHẢI MỘT (đo bằng pg_constraint trên DB
thật 2026-08-15): `memberships_role_cung_to_chuc_fkey`, `memberships_org_tenant_fkey`,
`memberships_org_user_fkey`. Bỏ sót hai cái sau thì `DROP COLUMN org_id` ở
migration B nổ — và nổ ở một file khác file gây ra lỗi.

FK VAI TRÒ LÀ `ON DELETE RESTRICT`, KHÔNG PHẢI CASCADE. Xoá một vai trò đang có
người giữ bị chặn ở tầng DB; đó là lưới thứ hai sau `dem_nguoi_dung_vai_tro()`
trong `quan_tri_vai_tro.xoa()`. FK thay thế giữ nguyên RESTRICT.

⚠ DOWNGRADE KHÔNG PHẢI ĐƯỜNG LÙI CHO PRODUCTION: hàng `roles` bị dedup không
dựng lại được, và hàm + trigger seed cũng không (thân hàm sinh từ dict `_MAU`
của 0104; sao chép nó vào đây là tạo bản thứ hai của ma trận PQ_01 §3.1).
`downgrade()` ở file này chỉ dùng được ngay sau `upgrade` trên máy dev.

Revision ID: 0105_roles_thoat_org
Revises: 0926_escalation_notes
"""

from alembic import op

revision = "0105_roles_thoat_org"
down_revision = "0926_escalation_notes"
branch_labels = None
depends_on = None

_ORG_MAC_DINH = "noble"


def upgrade() -> None:
    # --- ① GỠ FK GHÉP TRƯỚC, DEDUP SAU ------------------------------------
    # THỨ TỰ NÀY LÀ BẮT BUỘC và đã sai một lần: dedup remap `memberships.role_id`
    # sang hàng được giữ (thuộc org `noble`), nhưng hàng membership đó vẫn mang
    # `org_id = 'havengroup'` — và FK ghép `(org_id, role_id) -> roles(org_id, id)`
    # từ chối đúng lúc UPDATE chạy:
    #
    #   ForeignKeyViolation: Key (org_id, role_id)=(havengroup, r_c82bba…)
    #   is not present in table "roles"
    #
    # Gỡ ràng buộc ghép trước thì phép remap mới nói được điều nó muốn nói: vai
    # trò không còn thuộc tổ chức nào.
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_role_cung_to_chuc_fkey")
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_org_tenant_fkey")
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_org_user_fkey")
    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_org_user_fkey")

    # --- ② Dedup roles theo name ------------------------------------------
    # `created_at` đồng hạng (cùng một lượt seed, bằng nhau tới micro giây) thì
    # phân giải bằng `id` — nếu không, DISTINCT ON chọn tuỳ hứng và hai lần chạy
    # trên hai máy cho ra hai kết quả khác nhau.
    op.execute(
        """
        CREATE TEMP TABLE _giu AS
             SELECT DISTINCT ON (name) name, id
               FROM control.roles
              ORDER BY name, created_at, id
        """
    )
    op.execute(
        """
        UPDATE control.memberships m
           SET role_id = g.id
          FROM control.roles r
          JOIN _giu g ON g.name = r.name
         WHERE m.role_id = r.id AND m.role_id <> g.id
        """
    )
    op.execute(
        """
        DO $$
        DECLARE n int;
        BEGIN
          SELECT count(*) INTO n
            FROM control.roles r
           WHERE r.id NOT IN (SELECT id FROM _giu);
          IF n > 0 THEN
            RAISE NOTICE '0105: gộp % hàng roles trùng tên (dedup theo name)', n;
          END IF;
        END $$
        """
    )
    # `role_actions` rụng theo ON DELETE CASCADE của FK role_actions.role_id.
    op.execute("DELETE FROM control.roles WHERE id NOT IN (SELECT id FROM _giu)")
    op.execute("DROP TABLE _giu")

    # --- ③ Dựng lại thành FK đơn cột --------------------------------------
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_role_id_fkey
             FOREIGN KEY (role_id) REFERENCES control.roles (id) ON DELETE RESTRICT"""
    )
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_tenant_id_fkey
             FOREIGN KEY (tenant_id) REFERENCES control.tenants (id) ON DELETE CASCADE"""
    )
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_user_id_fkey
             FOREIGN KEY (user_id) REFERENCES control.users (id) ON DELETE CASCADE"""
    )
    op.execute(
        """ALTER TABLE control.invites
             ADD CONSTRAINT invites_user_id_fkey
             FOREIGN KEY (user_id) REFERENCES control.users (id) ON DELETE CASCADE"""
    )
    op.execute("ALTER TABLE control.invites DROP COLUMN org_id")

    # --- ④ roles bỏ org_id -------------------------------------------------
    op.execute("DROP INDEX control.roles_org_idx")
    op.execute("ALTER TABLE control.roles DROP CONSTRAINT roles_org_id_name_key")
    op.execute("ALTER TABLE control.roles DROP CONSTRAINT roles_org_id_id_key")
    op.execute("ALTER TABLE control.roles DROP COLUMN org_id")  # kéo theo roles_org_id_fkey
    op.execute("ALTER TABLE control.roles ADD CONSTRAINT roles_name_key UNIQUE (name)")

    # --- ⑤ Trigger seed theo org -------------------------------------------
    # Bốn vai trò đã tồn tại (backfill của 0104 + dedup ở ①); không seed lại.
    op.execute("DROP TRIGGER organizations_seed_vai_tro ON control.organizations")
    op.execute("DROP FUNCTION control.seed_vai_tro_mau(text)")


def downgrade() -> None:
    op.execute("ALTER TABLE control.roles DROP CONSTRAINT roles_name_key")
    op.execute(f"ALTER TABLE control.roles ADD COLUMN org_id text DEFAULT '{_ORG_MAC_DINH}'")
    op.execute("ALTER TABLE control.roles ALTER COLUMN org_id SET NOT NULL")
    op.execute("ALTER TABLE control.roles ALTER COLUMN org_id DROP DEFAULT")
    op.execute(
        """ALTER TABLE control.roles ADD CONSTRAINT roles_org_id_fkey
             FOREIGN KEY (org_id) REFERENCES control.organizations(id) ON DELETE CASCADE"""
    )
    op.execute("ALTER TABLE control.roles ADD CONSTRAINT roles_org_id_name_key UNIQUE (org_id, name)")
    op.execute("ALTER TABLE control.roles ADD CONSTRAINT roles_org_id_id_key UNIQUE (org_id, id)")
    op.execute("CREATE INDEX roles_org_idx ON control.roles (org_id)")

    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_user_id_fkey")
    op.execute(f"ALTER TABLE control.invites ADD COLUMN org_id text NOT NULL DEFAULT '{_ORG_MAC_DINH}'")
    op.execute("ALTER TABLE control.invites ALTER COLUMN org_id DROP DEFAULT")
    op.execute(
        """ALTER TABLE control.invites
             ADD CONSTRAINT invites_org_user_fkey
             FOREIGN KEY (org_id, user_id) REFERENCES control.users (org_id, id) ON DELETE CASCADE"""
    )

    for cu, moi, cot, dich, hanh_dong in (
        ("memberships_role_id_fkey", "memberships_role_cung_to_chuc_fkey", "role_id", "roles", "RESTRICT"),
        ("memberships_tenant_id_fkey", "memberships_org_tenant_fkey", "tenant_id", "tenants", "CASCADE"),
        ("memberships_user_id_fkey", "memberships_org_user_fkey", "user_id", "users", "CASCADE"),
    ):
        op.execute(f"ALTER TABLE control.memberships DROP CONSTRAINT {cu}")
        op.execute(
            f"""ALTER TABLE control.memberships ADD CONSTRAINT {moi}
                  FOREIGN KEY (org_id, {cot}) REFERENCES control.{dich} (org_id, id)
                  ON DELETE {hanh_dong}"""
        )
    # Hàm + trigger seed KHÔNG dựng lại — xem docstring đầu file.
