"""Hợp nhất hai head 0921/0924 — `alembic upgrade head` gãy trên develop, lần thứ năm

TRIỆU CHỨNG (job deploy CI, image 9633dd8e):

    $ docker compose -f ${COMPOSE_FILE} run --rm migrate
    INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
    ERROR [alembic.util.messaging] Multiple head revisions are present for given
    argument 'head'
    FAILED: Job failed: exit status 255

    $ alembic heads
    0921_bang_agent_feedback
    0924_escalations

VÌ SAO CÓ HAI HEAD: `0921_bang_agent_feedback` và `0923_hop_nhat_0920` cùng nhận
`0920_hop_nhat_hai_head_0919` làm cha — nhánh feedback được viết trên một checkout
chưa có `0922_media_file_name`, còn điểm hợp nhất 0923 (rồi `0924_escalations` nối
lên nó) được viết trên một checkout chưa có nhánh feedback. Cả hai merge riêng rẽ
vào develop:

    0920_hop_nhat_hai_head_0919
    ├── 0921_bang_agent_feedback          (tạo tenant_data.agent_feedback)
    └── 0923_hop_nhat_0920 → 0924_escalations   (tạo tenant_data.escalations)

Vẫn đúng bài học đã ghi ở `0914_hop_nhat_hai_head`, `0919_hop_nhat_hai_head_0918`,
`0920_hop_nhat_hai_head_0919` và `0923_hop_nhat_hai_head_0920`: git merge sạch cả
hai lần vì tên tệp khác nhau, chỉ alembic thấy, và chỉ khi ai đó chạy migrate —
nên nó lại đi thẳng vào develop mà không MR nào đỏ.

HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA: đổi `down_revision` của `0921_bang_agent_feedback`
thành `0924_escalations` sẽ làm alembic coi cả nhánh media/escalations là tổ tiên
đã áp trên một DB thật ra chưa từng chạy qua nó. Điểm hợp nhất không viết lại tổ
tiên của tệp nào — DB đang ở nhánh nào cũng đi tiếp đúng: áp nốt nhánh còn thiếu
rồi tới đây.

HAI NHÁNH ĐỘC LẬP THẬT: một bên tạo bảng `tenant_data.agent_feedback`, bên kia
thêm cột cho `media` rồi tạo bảng `tenant_data.escalations`. Không chồng đối tượng.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có.

Revision ID: 0925_hop_nhat_0924
Revises: 0921_bang_agent_feedback, 0924_escalations
"""

revision = "0925_hop_nhat_0924"
down_revision = ("0921_bang_agent_feedback", "0924_escalations")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
