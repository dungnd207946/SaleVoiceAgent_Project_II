"""GRANT SELECT schema control cho PUBLIC — mọi role đọc được, không cần gán nhóm

VÌ SAO CÓ MIGRATION NÀY: một hệ thống agent bên ngoài (service thứ 3, không phải
`agent_<tenant>` chạy qua `agent_api`) cần đọc dữ liệu của MỌI tenant trong một kết nối,
rồi tự thêm `WHERE tenant_id = ...` theo logic của họ. Các view `agent_api.*` (0904/0906/0907)
không dùng được cho việc này — chúng BẮT BUỘC lọc `portal.current_tenant()`, thiết kế fail-closed
cho đúng một tenant mỗi session, không phải cho một bên đọc toàn cục.

VÌ SAO KHÔNG SỬA VIEW `agent_api.*`: sửa view là sửa chung cho MỌI consumer, kể cả role
`agent_<tenant>` mà agent thật của từng khách hàng đang dùng — bỏ filter ở đó sẽ để một agent
của tenant A đọc được dữ liệu tenant B. Bài toán ở đây tách bạch: cấp thêm một CỬA MỚI đọc
thẳng schema `control`, không đụng cửa cũ.

VÌ SAO LÀ `PUBLIC` CHỨ KHÔNG MỘT ROLE NHÓM: bản đầu của migration này dựng một role nhóm
NOLOGIN (`control_readonly`) để giới hạn ai được đọc. Chủ đích của người vận hành là bỏ hẳn
giới hạn — "ai cũng đọc được", tự siết lại dần sau bằng tay khi cần — nên đổi thẳng sang
`PUBLIC`, pseudo-role đại diện "mọi role trên cluster", không cần bước `GRANT ... TO <role>`
nào nữa cả.

⚠️ CÁI GIÁ PHẢI GHI RA, ĐỌC TRƯỚC KHI CHẠY TRÊN PRODUCTION: sau migration này, MỌI role có
thể login vào Postgres của DB này — kể cả role tạo sau, không liên quan gì đến bên thứ 3 đang
cần — đều `SELECT` được toàn bộ schema `control`, gồm `agent_keys`/`agent_credentials` của
TẤT CẢ tenant cùng lúc. Không còn ranh giới nào ở tầng DB; ranh giới tenant từ đây là trách
nhiệm của code phía người đọc (câu `WHERE` họ tự viết), không phải Postgres. Muốn siết lại một
phần cho một số role cụ thể sau này thì `REVOKE ... FROM PUBLIC` rồi `GRANT ... TO <role cụ thể>`
— làm tay, không cần migration mới.

Revision ID: 0908_readonly_control
Revises: 0907_view_control_plane
"""

from alembic import op

revision = "0908_readonly_control"
down_revision = "0907_view_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA control TO PUBLIC")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA control TO PUBLIC")

    # Bảng `control` tạo về sau (migration mới) cũng tự động được đọc — không ai phải nhớ
    # thêm một GRANT mỗi lần có bảng mới.
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT ON TABLES TO PUBLIC")


def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control REVOKE SELECT ON TABLES FROM PUBLIC")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA control FROM PUBLIC")
    op.execute("REVOKE USAGE ON SCHEMA control FROM PUBLIC")
