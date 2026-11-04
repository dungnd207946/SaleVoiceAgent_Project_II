"""Baseline mới: schema `shop` — bán lẻ điện thoại, không tenant.

Thay toàn bộ 126 migration của domain BĐS (control / tenant_data / billing),
lấy lại được từ lịch sử git nếu cần. DDL nằm trong `_data/0001_shop/schema.sql`,
đóng băng theo thời điểm như mọi migration data — đừng sửa tệp đó sau khi đã áp,
thay đổi sau này viết migration mới.

Role (đều NOLOGIN, cấp LOGIN ở môi trường bằng tay — xem `make grant-api-dev`):
- `portal_api`      — API/admin: CRUD mọi bảng `shop`.
- `shop_agent_ro`   — text-to-SQL của agent: CHỈ SELECT trên 3 view `agent_*`.
- `shop_agent_rw`   — agent ghi lại: thừa hưởng `shop_agent_ro` + ghi `customers`, `reservations`.
Role là đối tượng cấp cluster nên tạo có guard (DB dev cũ đã có `portal_api`).

Thiết kế: docs/superpowers/specs/2026-11-02-phone-shop-db-design.md

Revision ID: 0001_shop
Revises:
"""

from pathlib import Path

from alembic import op

revision = "0001_shop"
down_revision = None
branch_labels = None
depends_on = None

_DDL = Path(__file__).parent / "_data" / "0001_shop" / "schema.sql"
_ROLES = ("portal_api", "shop_agent_ro", "shop_agent_rw")


def upgrade() -> None:
    op.execute(_DDL.read_text(encoding="utf-8"))

    for role in _ROLES:
        op.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} NOLOGIN;
              END IF;
            END $$
            """
        )

    op.execute("GRANT USAGE ON SCHEMA shop TO portal_api, shop_agent_ro, shop_agent_rw")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA shop TO portal_api")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA shop TO portal_api")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA shop GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal_api")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA shop GRANT USAGE, SELECT ON SEQUENCES TO portal_api")

    # Agent không bao giờ đọc bảng gốc — chỉ view đã lọc cột public.
    op.execute("GRANT SELECT ON shop.agent_products_v, shop.agent_promotions_v, shop.agent_stock_v TO shop_agent_ro")
    op.execute("GRANT shop_agent_ro TO shop_agent_rw")
    op.execute("GRANT SELECT, INSERT, UPDATE ON shop.customers, shop.reservations TO shop_agent_rw")
    op.execute("GRANT USAGE ON SEQUENCE shop.customers_id_seq, shop.reservations_id_seq TO shop_agent_rw")


def downgrade() -> None:
    op.execute("DROP SCHEMA shop CASCADE")
    # Role giữ lại: là đối tượng cấp cluster, DB khác trên cùng server có thể đang dùng.
