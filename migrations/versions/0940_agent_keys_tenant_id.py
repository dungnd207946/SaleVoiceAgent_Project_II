"""control.agent_keys treo thẳng vào tenant — bỏ tầng trung gian `deployment_id`

VÌ SAO BỎ: `deployment_id` (từ `0900`) là đường DUY NHẤT để một hàng khoá biết
mình thuộc tenant nào. Mô hình lúc đó là "1 tenant → N pod (`kind` chat/voice,
mỗi pod một `endpoint`) → mỗi pod bộ khoá riêng", nên khoá gắn vào POD chứ không
gắn vào tenant. Ba việc đã làm mô hình đó rỗng nghĩa:

  · `0917` `DROP SCHEMA agent_api` — view `tenant_keys`, nơi lập luận "JOIN chứ
    không thêm cột" của `0907` được viết ra, không còn tồn tại.
  · `0919` bỏ cột `kind` — một khoá dùng chung cho cả chat lẫn voice.
  · `service.phat_khoa_cho_tenant` tự cấp phát deployment nếu chưa có, và
    `repo.deployment_cua_tenant` luôn lấy hàng cũ nhất ⇒ thực tế 1 tenant = 1
    deployment.

`control.deployments` hôm nay còn `id · tenant_id · endpoint · provisioned_at`,
trong đó `endpoint` mặc định `''` và KHÔNG đường code nào ghi vào — nó chỉ được
SELECT ra ở màn admin.

VÌ SAO ĐÂY KHÔNG PHẢI "NGUỒN SỰ THẬT THỨ HAI" (phản biện của `0907:132`): lập
luận đó chống lại việc THÊM `tenant_id` cạnh `deployment_id`. Đây là THAY — sau
migration không còn đường nào khác suy ra tenant của một khoá, nên không có hai
nguồn để lệch.

LỖI TIỀM ẨN ĐƯỢC ĐÓNG LUÔN: DB không cấm >1 deployment cho một tenant (`0906`
ghi rõ là cố ý). Khi có, `repo.deployment_cua_tenant` lấy hàng CŨ NHẤT còn hợp
đồng agent (`0906` §1.4) bảo agent chọn id LỚN NHẤT — khoá treo một hàng,
heartbeat treo hàng khác, không lỗi nào phát ra.

CASCADE GIỮ NGUYÊN NGỮ NGHĨA: trước đây xoá tenant → cascade qua `deployments` →
tới khoá. Giờ một chặng thay vì hai. Bỏ `ON DELETE CASCADE` ở đây là để lại khoá
mồ côi trỏ vào workspace đã xoá.

KHÔNG ĐỤNG `control.deployments`: bảng vẫn còn, `agent_heartbeats` vẫn FK vào nó,
và màn admin vẫn liệt kê. Bỏ hẳn bảng + đổi khoá heartbeat sang `tenant_id` là
việc của một migration sau, và nó cần `odyssey-agent` bỏ khái niệm deployment
trước. Xem `docs/superpowers/specs/2026-08-19-agent-keys-tenant-id-design.md`.

GRANT KHÔNG ĐỔI: thêm/bớt cột không chạm `GRANT ... ON control.agent_keys TO
portal_api` của `0900`.

Revision ID: 0940_agent_keys_tenant
Revises: 0939_conversations_agent_key_id
"""

from alembic import op

revision = "0940_agent_keys_tenant"
down_revision = "0939_conversations_agent_key_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE control.agent_keys
            ADD COLUMN tenant_id text REFERENCES control.tenants(id) ON DELETE CASCADE
        """
    )
    op.execute(
        """
        UPDATE control.agent_keys k
           SET tenant_id = d.tenant_id
          FROM control.deployments d
         WHERE d.id = k.deployment_id
        """
    )
    # NOT NULL SAU backfill: mọi hàng đều có `deployment_id` NOT NULL với FK về
    # `deployments`, nên câu UPDATE trên phủ hết — không có hàng nào sót lại NULL.
    op.execute("ALTER TABLE control.agent_keys ALTER COLUMN tenant_id SET NOT NULL")

    # `agent_keys_deployment_idx` (0900) rơi theo cột — không cần DROP INDEX riêng.
    op.execute("ALTER TABLE control.agent_keys DROP COLUMN deployment_id")
    op.execute("CREATE INDEX agent_keys_tenant_idx ON control.agent_keys (tenant_id)")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE control.agent_keys
            ADD COLUMN deployment_id bigint REFERENCES control.deployments(id) ON DELETE CASCADE
        """
    )

    # PHẢI DỰNG BÙ HÀNG `deployments`: sau `upgrade`, đường phát khoá của owner
    # workspace KHÔNG tạo deployment nữa, nên có thật những tenant có khoá mà
    # không có hàng deployment nào. Thiếu bước này thì `SET NOT NULL` bên dưới vỡ
    # trên đúng những DB đã chạy production một thời gian.
    op.execute(
        """
        INSERT INTO control.deployments (tenant_id)
        SELECT DISTINCT k.tenant_id
          FROM control.agent_keys k
         WHERE NOT EXISTS (SELECT 1 FROM control.deployments d WHERE d.tenant_id = k.tenant_id)
        """
    )
    # `ORDER BY d.id LIMIT 1` = hàng CŨ NHẤT, khớp `repo.deployment_cua_tenant`
    # trước `0940`. Tenant nào có sẵn nhiều deployment thì khoá về đúng hàng mà
    # code cũ đã chọn, không phải một hàng khác.
    op.execute(
        """
        UPDATE control.agent_keys k
           SET deployment_id = (
               SELECT d.id FROM control.deployments d
                WHERE d.tenant_id = k.tenant_id ORDER BY d.id LIMIT 1)
        """
    )
    op.execute("ALTER TABLE control.agent_keys ALTER COLUMN deployment_id SET NOT NULL")

    op.execute("ALTER TABLE control.agent_keys DROP COLUMN tenant_id")
    op.execute("CREATE INDEX agent_keys_deployment_idx ON control.agent_keys (deployment_id)")
