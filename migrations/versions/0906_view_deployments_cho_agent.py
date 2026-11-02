"""agent_api.deployments — agent tra `deployment_id` của chính mình để ghi nhịp tim

VẤN ĐỀ NÓ GIẢI (tìm ra lúc kiểm chứng DB dùng chung, không phải suy luận):
`control.agent_heartbeats.deployment_id` có FK về `control.deployments`, và agent KHÔNG có
quyền đọc bảng đó (đúng luật cổng 5). Trên luồng cũ, agent nhận `deployment_id` từ response
của `POST /api/v1/agent/bootstrap` (`dau-noi-agent.md` G-8: "lấy từ bootstrap response, không
tự sinh, không đoán"). Nhưng khi agent nối THẲNG Postgres của một DB dùng chung, nó không có
đường nào lấy id đó — câu INSERT nhịp tim vỡ với:

    violates foreign key constraint "agent_heartbeats_deployment_fkey"

View này là đường tra tối thiểu để đóng đúng chỗ đó. Hợp đồng §1.4.

CỐ Ý KHÔNG DỰNG `tenant_status` (§1.2) VÀ `tenant_keys` (§1.3):
  · `tenant_status` — bootstrap đã từ chối tenant không active trước khi cấp credential.
  · `tenant_keys` — đây là bề mặt rộng nhất trong bốn cái: nó đưa hash khoá của TOÀN BỘ
    tenant cho agent, và làm Portal mất `agent_keys.last_used_at` cùng dấu vết bootstrap
    trong `audit_log`. Không luồng nào hôm nay cần nó.
Cả hai chỉ nên dựng nếu team agent chốt BỎ bootstrap — xem `docs/contracts/
danh-gia-dung-chung-db.md`. Dựng sẵn một bề mặt chưa ai dùng là mở rộng phạm vi rò rỉ
để đổi lấy một tiện lợi chưa tồn tại.

⚠️ CẬP NHẬT 2026-08-05 — ĐIỀU KIỆN TRÊN ĐÃ THOẢ, HAI VIEW ĐÓ GIỜ ĐÃ CÓ.
Team agent chốt bỏ `/bootstrap` và chuyển sang db-mode, nên `0907_view_control_plane_
cho_agent_dbmode.py` dựng cả `tenant_status` lẫn `tenant_keys` — kèm phần ghi lại cái giá
đã lường trước ở đoạn trên (mất `last_used_at`, mất dấu vết audit, mất nhịp chống dò khoá).
Đoạn "CỐ Ý KHÔNG DỰNG" phía trên giữ nguyên để lưu LÝ DO lúc đó, không phải để mô tả
trạng thái hôm nay. Đọc 0907 trước khi kết luận bề mặt agent gồm những gì.

`kind` có trong view vì agent phải chọn ĐÚNG deployment của loại process nó đang chạy
('chat' hay 'voice'). Không có `endpoint`: agent biết địa chỉ của chính nó, và một cột địa
chỉ của deployment KHÁC là thứ nó không có nhu cầu đọc.

Khuyến nghị vận hành (KHÔNG cưỡng chế bằng unique index ở đây): giữ ≤1 deployment còn sống
cho mỗi (tenant, kind). `control.deployments` không có UNIQUE trên cặp đó, và thêm vào sẽ đổi
hành vi của `enrollment.them_deployment()` — hàm đó chèn vô điều kiện, không có bảo vệ
idempotent, nên một unique index biến lần provisioning thứ hai thành lỗi 500. Nếu có >1 dòng,
agent chọn `id` lớn nhất (hợp đồng §1.4).

Revision ID: 0906_view_deployments
Revises: 0905_grant_seq
"""

from alembic import op

revision = "0906_view_deployments"
down_revision = "0905_grant_seq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW agent_api.deployments AS
        SELECT d.tenant_id, d.id, d.kind
          FROM control.deployments d
         WHERE d.tenant_id = portal.current_tenant()
        """
    )
    # No-op tường minh: ALTER DEFAULT PRIVILEGES của 0005 đã tự cấp cho view mới.
    op.execute("GRANT SELECT ON agent_api.deployments TO agent_all")


def downgrade() -> None:
    op.execute("DROP VIEW agent_api.deployments")
