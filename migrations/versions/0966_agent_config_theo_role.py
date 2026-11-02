"""agent_config theo ROLE (sale/customer) + bỏ hẳn bản nháp/lịch sử version/con trỏ live.

HAI VIỆC, MỘT MIGRATION — vì chúng là một quyết định (2026-09-29, người dùng chốt):

  1. `tenant_data.agent_config` từ MỘT hàng/tenant thành HAI hàng/tenant — một cho người
     dùng agent là `sale`, một cho `customer`. Khoá đổi `UNIQUE (tenant_id)` →
     `UNIQUE (tenant_id, role)`. Hàng hiện có của mỗi tenant thành `customer`, và hàng
     `sale` được CHÉP từ nó (người dùng vào tab Sale chỉnh tiếp, thay vì gặp bộ mặc định).
     Cột `role` KHÔNG giữ DEFAULT sau khi backfill: mọi lần ghi từ nay phải nói rõ role,
     một INSERT quên role mà vẫn lọt thành `customer` là hỏng im lặng.

  2. Portal thôi quản lý version: bấm Lưu là ghi thẳng `agent_config`, agent thấy ngay.
     `control.config_drafts` · `control.config_versions` · `control.config_live` bị DROP.
     Agent (chế độ `AGENT_CONFIG_SOURCE=db`) chưa bao giờ đọc ba bảng này — nó chỉ đọc
     `tenant_data.agent_config` — nên bỏ chúng không đổi hành vi agent.

  ⚠️ CỘT `version` VẪN Ở LẠI và vẫn phải TĂNG mỗi lần Lưu. Nó không còn là "phiên bản"
  theo nghĩa lịch sử, mà là bộ đếm để agent biết có gì đổi: agent cache runner theo
  `(tenant, version)` (`odyssey-agent/.../facade.py::_resolve_current_version`), lưu mà
  không tăng số thì hội thoại mới vẫn chạy cấu hình cũ. Hai hàng của một tenant luôn mang
  CÙNG một số (ghi chung một lần Lưu).

⚠️ AGENT PHẢI LỌC `role` TRƯỚC KHI MIGRATION NÀY CHẠY TRÊN MÔI TRƯỜNG CÓ POD THẬT.
Câu đọc hiện tại của agent là `SELECT … FROM tenant_data.agent_config WHERE tenant_id = $1`
+ `fetchrow` — ngay khi hàng `sale` xuất hiện (backfill ở dưới), `fetchrow` lấy MỘT HÀNG
BẤT KỲ, tức khách có thể được phục vụ bằng cấu hình dành cho sale. Không lỗi nào phát ra.

MẤT DỮ LIỆU CÓ CHỦ Ý (không lùi được):
  · `config_versions` — toàn bộ lịch sử đã publish. Bảng này từng cố ý BẤT BIẾN (0200).
  · `config_drafts` — mọi bản nháp CHƯA áp dụng. Không đẩy vào `agent_config`: đó là thứ
    chưa ai bấm áp dụng, ghi nó lên là bật cho khách một cấu hình không ai duyệt.
  `downgrade()` dựng lại ba bảng RỖNG, không khôi phục được dữ liệu.

Kèm: xoá job `publish`/`rollback` còn `queued` trong `control.jobs` — handler của chúng
(`modules/config/jobs.py`) bị xoá cùng đợt, worker nhặt phải hàng đó sẽ chết ở "không có
handler cho kind".

Revision ID: 0966_agent_config_theo_role
Revises: 0965_hop_nhat_hai_head
"""

from alembic import op

revision = "0966_agent_config_theo_role"
down_revision = "0965_hop_nhat_hai_head"
branch_labels = None
depends_on = None

# Đóng băng trong file (luật migration: không import `portal.*`).
_VAI_TRO = ("sale", "customer")

# Mọi cột dữ liệu của hàng phẳng, trừ `id`/`role`/`created_at`/`updated_at`.
_COT = (
    "name, brand_name, self_pronoun, customer_pronoun, greeting, "
    "scope_does, scope_does_not, refusal_line, departments, "
    "tone, reply_length, skills, version, tts_normalization"
)


def upgrade() -> None:
    # ── 1. Cột role ──────────────────────────────────────────────────────────
    # DEFAULT tạm để hàng hiện có thành `customer`; bỏ DEFAULT ngay sau đó.
    vai_tro = ", ".join(f"'{v}'" for v in _VAI_TRO)
    op.execute(
        f"""
        ALTER TABLE tenant_data.agent_config
          ADD COLUMN role text NOT NULL DEFAULT 'customer'
          CONSTRAINT agent_config_role_check CHECK (role IN ({vai_tro}))
        """
    )
    op.execute("ALTER TABLE tenant_data.agent_config ALTER COLUMN role DROP DEFAULT")

    # ── 2. Khoá theo (tenant, role) ──────────────────────────────────────────
    # Đây là đích của `ON CONFLICT (tenant_id, role)` trong `agent_config.luu()`.
    op.execute("ALTER TABLE tenant_data.agent_config DROP CONSTRAINT agent_config_tenant_key")
    op.execute(
        "ALTER TABLE tenant_data.agent_config ADD CONSTRAINT agent_config_tenant_role_key UNIQUE (tenant_id, role)"
    )

    # ── 3. Hàng sale = bản chép của customer ─────────────────────────────────
    # ⚠️ `agent_config` BẬT RLS + FORCE (từ `0956`). Migration không set `app.tenant_id`,
    # nên thiếu cặp NO FORCE/FORCE thì câu dưới đọc 0 hàng trên môi trường thật (migrator
    # là owner KHÔNG superuser) và BÁO THÀNH CÔNG — mọi tenant mất hàng `sale` im lặng.
    # Testcontainer chạy superuser nên không test DB nào bắt được; cổng tĩnh
    # `tests/unit/test_migration_backfill_rls.py` canh chỗ này. Cùng khuôn `0961`.
    op.execute("ALTER TABLE tenant_data.agent_config NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        INSERT INTO tenant_data.agent_config (tenant_id, role, {_COT})
        SELECT tenant_id, 'sale', {_COT}
          FROM tenant_data.agent_config
         WHERE role = 'customer'
        ON CONFLICT (tenant_id, role) DO NOTHING
        """
    )
    op.execute("ALTER TABLE tenant_data.agent_config FORCE ROW LEVEL SECURITY")

    # ── 4. Job cũ không còn handler ──────────────────────────────────────────
    op.execute("DELETE FROM control.jobs WHERE kind IN ('publish', 'rollback')")

    # ── 5. Bỏ bản nháp · lịch sử · con trỏ ───────────────────────────────────
    # `config_live` trước: nó có FK tổ hợp tới `config_versions` (0904).
    op.execute("DROP TABLE control.config_live")
    op.execute("DROP TABLE control.config_versions")
    op.execute("DROP TABLE control.config_drafts")


def downgrade() -> None:
    # Dựng lại ba bảng đúng hình dạng ở `0965` — RỖNG. Dữ liệu đã DROP không về được.
    op.execute(
        """
        CREATE TABLE control.config_drafts (
            tenant_id      text PRIMARY KEY REFERENCES control.tenants(id) ON DELETE CASCADE,
            payload        jsonb NOT NULL,
            schema_version integer NOT NULL,
            updated_at     timestamptz NOT NULL DEFAULT now(),
            updated_by     text REFERENCES control.users(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.config_versions (
            tenant_id    text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            version      integer NOT NULL CONSTRAINT config_versions_version_check CHECK (version > 0),
            payload      jsonb NOT NULL,
            bundle_sha   text NOT NULL CONSTRAINT config_versions_sha_check CHECK (bundle_sha <> ''),
            note         text NOT NULL DEFAULT '',
            published_at timestamptz NOT NULL DEFAULT now(),
            published_by text REFERENCES control.users(id) ON DELETE SET NULL,
            config_agent jsonb,
            PRIMARY KEY (tenant_id, version),
            CONSTRAINT config_versions_config_agent_tu_v3
                CHECK (config_agent IS NOT NULL OR (payload->>'schema_version')::int < 3)
        )
        """
    )
    op.execute("REVOKE UPDATE, DELETE ON control.config_versions FROM portal_api")
    op.execute(
        """
        CREATE TABLE control.config_live (
            tenant_id  text PRIMARY KEY REFERENCES control.tenants(id) ON DELETE CASCADE,
            version    integer NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT config_live_version_fk FOREIGN KEY (tenant_id, version)
                REFERENCES control.config_versions (tenant_id, version) ON DELETE CASCADE
        )
        """
    )

    # Về lại một hàng/tenant: giữ `customer`, bỏ `sale`.
    op.execute("ALTER TABLE tenant_data.agent_config NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM tenant_data.agent_config WHERE role = 'sale'")
    op.execute("ALTER TABLE tenant_data.agent_config FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_data.agent_config DROP CONSTRAINT agent_config_tenant_role_key")
    op.execute("ALTER TABLE tenant_data.agent_config ADD CONSTRAINT agent_config_tenant_key UNIQUE (tenant_id)")
    op.execute("ALTER TABLE tenant_data.agent_config DROP COLUMN role")
