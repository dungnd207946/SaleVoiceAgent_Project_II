"""M3 — config_drafts · config_versions · deployments

Ba bảng của đường sống "ô nhập trên portal -> cấu hình agent đọc được".

VÌ SAO `config_versions` PHẢI BẤT BIẾN, VÀ VÌ SAO BẰNG REVOKE CHỨ KHÔNG BẰNG NỘI QUY:
Lời hứa của M3 là "quay lui về đúng bản đã chạy trong một thao tác". Lời hứa đó
chỉ đúng nếu bản đã chạy còn nguyên. Nếu tầng ứng dụng UPDATE được một hàng đã
publish thì bản mà `LIVE` trỏ tới có thể đã bị sửa nội dung — và không ai biết,
vì `bundle_sha` cũng nằm trong hàng đó.

Chú ý cái bẫy: migration 0003 đặt
    ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT,INSERT,UPDATE,DELETE ... TO portal_api
nên MỌI bảng mới trong `control` **tự động** có UPDATE và DELETE. Không REVOKE
tường minh ở đây thì bất biến không tồn tại, và **không test nào một-role phát
hiện ra** — hệt lỗi FORCE RLS mà M1 đã cảnh báo.

VÌ SAO KHÔNG DÙNG TRIGGER CHẶN UPDATE: trigger chạy sau khi quyền đã cho phép,
nên nó chặn được đường đi qua SQL nhưng vẫn để lại quyền trên bảng. Rút quyền là
tầng ngoài cùng — không có quyền thì không có đường nào cả.

VÌ SAO `deployments` Ở ĐÂY chứ không ở M1: migration 0007 để `agent_heartbeats.
deployment_id` không FK và ghi rõ lý do ở dòng 11 — bảng thuộc M3. Giờ M3 tới thì
đóng nốt: heartbeat trỏ vào pod không tồn tại là trạng thái không ai chẩn được.

VÌ SAO BA BẢNG NÀY KHÔNG DƯỚI RLS: chúng ở `control`, cùng hạng với `users` ·
`memberships` · `jobs`. Phạm vi tenant của chúng do tầng API đặt từ membership đã
xác thực, không do Postgres. Khai tường minh ở tests/isolation/test_isolation_catalog.py.

Revision ID: 0200_config_store
Revises: 0101_memberships
"""

from alembic import op

revision = "0200_config_store"
down_revision = "0101_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── deployments — pod của một tenant ────────────────────────────────────
    # `kind` là CHECK chứ không phải enum: thêm kênh thứ ba (ví dụ 'zalo') không
    # được là một migration sửa kiểu, vì kiểu enum khoá cả bảng lúc ALTER.
    op.execute(
        """
        CREATE TABLE control.deployments (
            id             bigserial PRIMARY KEY,
            tenant_id      text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            kind           text NOT NULL
                           CONSTRAINT deployments_kind_check CHECK (kind IN ('chat', 'voice')),
            endpoint       text NOT NULL DEFAULT '',
            provisioned_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX deployments_tenant_idx ON control.deployments (tenant_id)")

    # Đóng nốt chỗ M1 để trống (0007 dòng 11).
    op.execute(
        """
        ALTER TABLE control.agent_heartbeats
            ADD CONSTRAINT agent_heartbeats_deployment_fkey
            FOREIGN KEY (deployment_id) REFERENCES control.deployments(id) ON DELETE CASCADE
        """
    )

    # ─── config_drafts — ĐÚNG MỘT bản nháp mỗi tenant ────────────────────────
    # PK là tenant_id, không phải id tự tăng: hai bản nháp thì không có bản nào
    # là "cái sắp được áp dụng", và nút Áp dụng mất nghĩa.
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

    # ─── config_versions — BẤT BIẾN sau khi ghi ──────────────────────────────
    # `version` là int tăng dần trong phạm vi một tenant (quyết định #9, hiển thị
    # `vN`). Không phải global sequence: hai tenant publish xen kẽ mà số nhảy cóc
    # thì người dùng hỏi "v3 của tôi đâu" và không có câu trả lời nào tử tế.
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
            PRIMARY KEY (tenant_id, version)
        )
        """
    )

    # CỔNG 3. Rút UPDATE và DELETE mà DEFAULT PRIVILEGES của 0003 vừa cấp.
    # INSERT và SELECT GIỮ NGUYÊN: job publish chạy bằng portal_api và phải ghi
    # được hàng mới. "Khoá sạch bảng" làm cổng 3 xanh và publish chết.
    op.execute("REVOKE UPDATE, DELETE ON control.config_versions FROM portal_api")


def downgrade() -> None:
    op.execute("DROP TABLE control.config_versions")
    op.execute("DROP TABLE control.config_drafts")
    op.execute("ALTER TABLE control.agent_heartbeats DROP CONSTRAINT agent_heartbeats_deployment_fkey")
    op.execute("DROP TABLE control.deployments")
