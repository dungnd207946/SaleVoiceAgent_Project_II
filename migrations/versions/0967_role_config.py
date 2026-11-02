"""`tenant_data.role_config` — người dùng agent tự tạo role, không còn danh sách đóng.

`0966` chia `agent_config` theo role với danh sách ĐÓNG `('sale', 'customer')` (CHECK).
Người dùng chốt (2026-09-30): role do workspace tự tạo/đổi tên/xoá, riêng `customer`
(«Khách hàng») là role MẶC ĐỊNH — mọi tenant luôn có, và không xoá được. Các phần cấu hình
trong một role vẫn y hệt nhau (một hàng `agent_config` mỗi role, như `0966`).

  · `role_config (tenant_id, key, ten, icon, thu_tu)` — `key` BẤT BIẾN (là thứ
    `agent_config.role` lưu), `ten` là tên hiển thị, đổi được. Đổi tên không chạm hàng cấu
    hình. `icon` là MÃ icon trên tab (FE giữ bảng mã → hình; mã lạ/NULL thì FE tự chọn một
    hình theo `key`) — DB chỉ kiểm hình dạng chuỗi, không giữ danh sách đóng: thêm hình
    mới là việc của FE, không phải một migration.
  · CHECK `agent_config_role_check` → FK `(tenant_id, role) → role_config(tenant_id, key)
    ON DELETE CASCADE`: xoá role là mất luôn hàng cấu hình của nó. Câu đọc của agent
    (`WHERE tenant_id = $1 AND role = $2`) KHÔNG đổi, không cần join.

ROLE `customer` CÓ SẴN KHI TẠO TENANT — cưỡng chế ở DB bằng trigger trên `control.tenants`,
không ở `workspace/service.tao()`: tenant còn sinh ra từ `seed_owner`, từ import, từ fixture
test (44 tệp INSERT thẳng). Đặt ở tầng app thì mỗi đường đó là một chỗ quên. Chỉ tạo hàng
ROLE, KHÔNG tạo hàng `agent_config` — role chưa lưu lần nào thì `GET /config` trả bộ mặc
định (`laMacDinh`), đúng như workspace mới trước đây.

`customer` KHÔNG XOÁ ĐƯỢC — cũng cưỡng chế ở DB (trigger BEFORE DELETE), trừ khi chính tenant
đang bị xoá (cascade: lúc đó hàng tenant đã biến mất). `key` không đổi được (BEFORE UPDATE).

⚠️ RLS: `role_config` bật RLS + FORCE như mọi bảng `tenant_data`. Trigger tạo role chạy
trong giao dịch tạo tenant, nơi `app.tenant_id` CHƯA trỏ vào tenant mới (nó chưa tồn tại) —
nên trigger tự đặt `app.tenant_id` cục bộ, INSERT, rồi trả lại giá trị cũ. Không dùng
SECURITY DEFINER: FORCE áp cả cho chủ bảng, định nghĩa lại người chạy không gỡ được RLS.

Backfill: mọi tenant hiện có nhận `customer`; tenant nào đã có hàng `agent_config` role
`sale` (backfill của `0966`) nhận thêm role `sale` («Sale») — giữ nguyên thứ họ đang thấy.

Revision ID: 0967_role_config
Revises: 0966_agent_config_theo_role
"""

from alembic import op

revision = "0967_role_config"
down_revision = "0966_agent_config_theo_role"
branch_labels = None
depends_on = None

# Đóng băng trong file (luật migration: không import `portal.*`).
_KEY_MAC_DINH = "customer"
_TEN_MAC_DINH = "Khách hàng"
_ICON_MAC_DINH = "khach"


def upgrade() -> None:
    # ── 1. Bảng ──────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE tenant_data.role_config (
            tenant_id  text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            key        text NOT NULL CONSTRAINT role_config_key_check CHECK (key ~ '^[a-z][a-z0-9_]{1,31}$'),
            ten        text NOT NULL CONSTRAINT role_config_ten_check CHECK (btrim(ten) <> '' AND length(ten) <= 40),
            icon       text CONSTRAINT role_config_icon_check CHECK (icon ~ '^[a-z0-9_]{1,32}$'),
            thu_tu     integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, key)
        )
        """
    )
    # Tên trùng không phân biệt hoa/thường/khoảng trắng hai đầu — hai tab cùng tên là hai
    # tab không ai phân biệt được.
    op.execute("CREATE UNIQUE INDEX role_config_ten_key ON tenant_data.role_config (tenant_id, lower(btrim(ten)))")

    # ── 2. Backfill — TRƯỚC khi bật RLS trên bảng mới; `agent_config` thì đang FORCE ──
    op.execute(
        f"""
        INSERT INTO tenant_data.role_config (tenant_id, key, ten, icon, thu_tu)
        SELECT id, '{_KEY_MAC_DINH}', '{_TEN_MAC_DINH}', '{_ICON_MAC_DINH}', 0 FROM control.tenants
        """
    )
    op.execute("ALTER TABLE tenant_data.agent_config NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        INSERT INTO tenant_data.role_config (tenant_id, key, ten, icon, thu_tu)
        SELECT DISTINCT tenant_id, 'sale', 'Sale', 'sale', 1
          FROM tenant_data.agent_config
         WHERE role = 'sale'
        """
    )
    op.execute("ALTER TABLE tenant_data.agent_config FORCE ROW LEVEL SECURITY")

    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.role_config')")
    # Agent đọc được danh sách role của tenant mình (RLS lọc theo `agent_<tenant>`), cùng
    # quyền mà `0909` cấp cho mọi bảng `tenant_data`.
    op.execute("GRANT SELECT ON tenant_data.role_config TO PUBLIC")

    # ── 3. agent_config.role: danh sách đóng → FK ────────────────────────────
    op.execute("ALTER TABLE tenant_data.agent_config DROP CONSTRAINT agent_config_role_check")
    op.execute(
        """
        ALTER TABLE tenant_data.agent_config
          ADD CONSTRAINT agent_config_role_fk FOREIGN KEY (tenant_id, role)
          REFERENCES tenant_data.role_config (tenant_id, key) ON DELETE CASCADE
        """
    )

    # ── 4. Tạo tenant ⇒ có sẵn role mặc định ─────────────────────────────────
    op.execute(
        f"""
        CREATE FUNCTION control.tao_role_mac_dinh() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE v_cu text := current_setting('app.tenant_id', true);
        BEGIN
            -- RLS của role_config đòi tenant_id = portal.current_tenant(): trỏ tạm vào
            -- tenant mới, ghi, rồi trả lại đúng giá trị cũ cho phần còn lại giao dịch.
            PERFORM set_config('app.tenant_id', NEW.id, true);
            INSERT INTO tenant_data.role_config (tenant_id, key, ten, icon, thu_tu)
            VALUES (NEW.id, '{_KEY_MAC_DINH}', '{_TEN_MAC_DINH}', '{_ICON_MAC_DINH}', 0)
            ON CONFLICT DO NOTHING;
            PERFORM set_config('app.tenant_id', coalesce(v_cu, ''), true);
            RETURN NULL;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER tenants_tao_role_mac_dinh AFTER INSERT ON control.tenants
        FOR EACH ROW EXECUTE FUNCTION control.tao_role_mac_dinh()
        """
    )

    # ── 5. Role mặc định không xoá được · key không đổi được ─────────────────
    op.execute(
        f"""
        CREATE FUNCTION control.chan_sua_role_config() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF NEW.key <> OLD.key OR NEW.tenant_id <> OLD.tenant_id THEN
                    RAISE EXCEPTION 'role_config.key bất biến (% → %)', OLD.key, NEW.key;
                END IF;
                RETURN NEW;
            END IF;
            -- DELETE: tenant còn sống ⇒ đây là xoá role, không phải cascade từ xoá tenant.
            IF OLD.key = '{_KEY_MAC_DINH}'
               AND EXISTS (SELECT 1 FROM control.tenants WHERE id = OLD.tenant_id) THEN
                RAISE EXCEPTION 'role mặc định % không xoá được', OLD.key;
            END IF;
            RETURN OLD;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER role_config_chan_sua BEFORE UPDATE OR DELETE ON tenant_data.role_config
        FOR EACH ROW EXECUTE FUNCTION control.chan_sua_role_config()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER role_config_chan_sua ON tenant_data.role_config")
    op.execute("DROP FUNCTION control.chan_sua_role_config()")
    op.execute("DROP TRIGGER tenants_tao_role_mac_dinh ON control.tenants")
    op.execute("DROP FUNCTION control.tao_role_mac_dinh()")

    # Về lại danh sách đóng của `0966`: hàng của role tự tạo không có chỗ ở đó.
    op.execute("ALTER TABLE tenant_data.agent_config DROP CONSTRAINT agent_config_role_fk")
    op.execute("ALTER TABLE tenant_data.agent_config NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM tenant_data.agent_config WHERE role NOT IN ('sale', 'customer')")
    op.execute("ALTER TABLE tenant_data.agent_config FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        ALTER TABLE tenant_data.agent_config
          ADD CONSTRAINT agent_config_role_check CHECK (role IN ('sale', 'customer'))
        """
    )
    op.execute("DROP TABLE tenant_data.role_config")
