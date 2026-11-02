"""control.agent_heartbeats — chiều GHI của seam agent

VÌ SAO Ở M1 CHỨ KHÔNG Ở M3: M2a cần nó cho badge trạng thái workspace ở app
shell, M9 cần nó cho bước 3 wizard. Để nó ở M3 là buộc hai module đợi.
Nó cũng nhất quán về khái niệm — M1 sở hữu TOÀN BỘ seam agent: agent_api view
là đường agent ĐỌC, bảng này là đường agent GHI.

VÌ SAO BẢNG HẸP RIÊNG, KHÔNG NHÉT VÀO tenants: agent ghi bảng này mỗi 20 giây.
Nhét vào tenants là cho agent quyền UPDATE trên neo danh tính của cả hệ.

VÌ SAO deployment_id KHÔNG CÓ FK Ở ĐÂY: bảng control.deployments thuộc M3.
Giữ cột từ đầu để không phải đổi PRIMARY KEY về sau; M3 thêm FK trong migration
0200-0299 của nó.

VÌ SAO RLS CÓ POLICY THEO ROLE, KHÔNG PHẢI MỘT `CHECK`:
Bảng này là ngoại lệ duy nhất của "schema control không có RLS" — vì nó là bảng
control plane DUY NHẤT mà agent được GHI, nên phải có gì đó chặn agent_hb1 ghi
hàng của hb2.

Cách sai mà dễ nghĩ ra đầu tiên: CHECK (tenant_id = portal.current_tenant()).
Nó chạy, nhưng nó là một CHECK phụ thuộc BIẾN PHIÊN — và
`pg_restore` một bản sao lưu sẽ nạp lại từng hàng KHÔNG có app.tenant_id nào
được đặt, nên CHECK ra false và **mọi hàng bị từ chối**. Kho tệp và Postgres
đều mang lời hứa sao lưu (retention 6 tháng nằm trong hợp đồng), nên một cơ chế
làm restore vỡ là lỗi thật, không phải chuyện lý thuyết.

Cách đúng: RLS với HAI policy phân theo role.
  - agent_all  -> chỉ hàng của tenant mình, cả đọc lẫn ghi
  - portal_api -> tất cả. Portal PHẢI đọc được heartbeat của mọi workspace:
                  admin nền tảng xem tình trạng vận hành là quyền control plane
                  (không phải quyền đọc dữ liệu tenant).
RLS chỉ áp lúc truy vấn, không áp lúc COPY của pg_restore -> restore sạch.

KHÔNG dùng FORCE ở đây: `control` là dữ liệu control plane, và owner
(portal_migrator) cần khôi phục/sửa được bằng tay. Catalog test (cổng 6) chỉ
quét schema tenant_data nên không đòi FORCE ở bảng này.

Revision ID: 0007_heartbeats
Revises: 0006_jobs
"""

from alembic import op

revision = "0007_heartbeats"
down_revision = "0006_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.agent_heartbeats (
            tenant_id       text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            deployment_id   bigint NOT NULL,
            running_version integer,
            bundle_sha      text NOT NULL DEFAULT '',
            agent_version   text NOT NULL DEFAULT '',
            last_error      text NOT NULL DEFAULT '',
            last_seen_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, deployment_id)
        )
        """
    )
    op.execute("ALTER TABLE control.agent_heartbeats ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY hb_agent_own_tenant ON control.agent_heartbeats
            TO agent_all
            USING (tenant_id = portal.current_tenant())
            WITH CHECK (tenant_id = portal.current_tenant())
        """
    )
    op.execute(
        """
        CREATE POLICY hb_portal_all ON control.agent_heartbeats
            TO portal_api
            USING (true) WITH CHECK (true)
        """
    )

    # Agent cần USAGE trên control để với tới bảng này — và ĐÚNG bảng này.
    # Cấp cho NHÓM nên role tạo về sau cũng có ngay, và create_agent_role()
    # không phải sửa. Cổng 5 canh rằng không ai nới thêm bảng control nào khác.
    op.execute("GRANT USAGE ON SCHEMA control TO agent_all")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.agent_heartbeats TO agent_all")


def downgrade() -> None:
    op.execute("DROP TABLE control.agent_heartbeats")
    op.execute("REVOKE USAGE ON SCHEMA control FROM agent_all")
