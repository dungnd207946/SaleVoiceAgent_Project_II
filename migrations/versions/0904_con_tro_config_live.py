"""control.config_live + agent_api.agent_published_config — con trỏ "bản nào đang chạy"

VẤN ĐỀ NÓ GIẢI: agent phải đọc config từ Postgres (hợp đồng
`docs/contracts/agent-postgres-read-contract.md` §1.1), nhưng con trỏ LIVE của Portal nằm
trên KHO TỆP (object `tenants/<t>/LIVE`), không nằm trong DB. Nên trên một DB dùng chung,
agent không có cách nào biết version nào đang phục vụ.

⚠️ ĐÂY LÀ MỘT QUYẾT ĐỊNH MỘT CHIỀU, PHẢI ĐỌC TRƯỚC KHI SỬA.
`service.doc_version_dang_live()` loại tường minh phương án `tenants.live_version` với lý lẽ
đúng: "bản sao thứ hai của một sự thật mà con trỏ đã giữ, và hai bản sao thì có ngày lệch —
cụ thể là khi ghi con trỏ xong mà cập nhật cột hỏng. Lúc đó không có bản nào tự nhận là sai."

Lý lẽ đó KHÔNG mất đi vì bảng này ra đời. Nó chuyển thành một nghĩa vụ: kể từ migration này,
`control.config_live` là **sự thật duy nhất** về "bản nào đang chạy", và object `LIVE` trên
kho tệp phải trở thành **bản phái sinh** (ghi ra để tương thích cũ) hoặc bị bỏ. Hai nguồn
cùng tự nhận là sự thật là đúng cái bug mà comment kia cảnh báo. Ai đọc file này mà thấy
`_ghi_con_tro()` vẫn là đường ghi duy nhất thì việc dời chưa xong.

VÌ SAO MỘT BẢNG CON TRỎ CHỨ KHÔNG PHẢI `max(version)`: Portal có quay lui
(`service.quay_lui()` đổi con trỏ, KHÔNG sinh version mới). Sau một lần quay lui,
`max(version)` = 2 nhưng bản đang phục vụ = 1. Một view build bằng `max(version)` nói dối
đúng vào lúc người vận hành cần sự thật nhất. Đây cũng là chỗ hợp đồng của team agent ghi
SAI ("version đơn điệu tăng / tenant") — cổng
`test_quay_lui_view_tra_version_CU_khong_phai_max` canh đúng điều đó.

VÌ SAO CÓ FK TỔ HỢP `(tenant_id, version)`: không có nó, một lần ghi con trỏ sai trỏ vào
version không tồn tại làm view trả 0 hàng, và agent fail-closed về mặc định — hệ chạy sạch
trong khi tenant đó mất cấu hình. Im lặng và khó chẩn. FK biến nó thành lỗi ngay lúc ghi.

`ON DELETE CASCADE` trên cả hai FK, KHÔNG phải RESTRICT: khi xoá một tenant, Postgres cascade
sang `config_versions` VÀ `config_live` cùng lúc, và RESTRICT ở FK thứ hai sẽ vỡ tuỳ thứ tự
Postgres chọn. `config_versions` vốn bất biến với `portal_api` (0200 REVOKE UPDATE, DELETE),
nên đường duy nhất xoá được một version là cascade từ tenant — CASCADE ở đây không mở thêm
đường nào.

VIEW ĐÚNG BA CỘT của hợp đồng §1.1 (`tenant_id`, `version`, `config`) — không thêm cột nào
"cho tiện". View của team agent hôm nay cũng đúng ba cột đó, nên đổi DSN là xong, không phải
sửa câu SELECT nào phía họ.

Revision ID: 0904_config_live
Revises: 0903_write_back
"""

from alembic import op

revision = "0904_config_live"
down_revision = "0903_write_back"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PK là tenant_id (không phải id tự tăng): một tenant có ĐÚNG MỘT bản đang chạy.
    # Hai hàng thì không hàng nào là "bản đang chạy", và đó chính là trạng thái mà cả
    # người vận hành lẫn agent không chẩn được.
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

    # KHÔNG grant gì cho agent trên bảng này. Agent đọc nó QUA view DEFINER bên dưới —
    # đúng luật cổng 5 (bảng `control` duy nhất agent có quyền là `agent_heartbeats`).
    # `portal_api` có DML nhờ ALTER DEFAULT PRIVILEGES của 0003, không cần grant thêm.
    op.execute(
        """
        CREATE VIEW agent_api.agent_published_config AS
        SELECT v.tenant_id, v.version, v.payload AS config
          FROM control.config_versions v
          JOIN control.config_live    l ON l.tenant_id = v.tenant_id AND l.version = v.version
         WHERE v.tenant_id = portal.current_tenant()
        """
    )
    # ALTER DEFAULT PRIVILEGES của 0005 đã tự cấp SELECT cho agent_all trên view mới;
    # câu này là no-op tường minh, để người đọc migration không phải đi tra chỗ khác.
    op.execute("GRANT SELECT ON agent_api.agent_published_config TO agent_all")


def downgrade() -> None:
    op.execute("DROP VIEW agent_api.agent_published_config")
    op.execute("DROP TABLE control.config_live")
