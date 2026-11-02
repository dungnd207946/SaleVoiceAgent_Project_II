"""Hợp nhất hai head 0919 — `alembic upgrade head` gãy trên develop, lần thứ ba

TRIỆU CHỨNG (job deploy CI):

    $ docker compose run --rm migrate
    ERROR [alembic.util.messaging] Multiple head revisions are present for given
    argument 'head'
    FAILED: Job failed: exit status 255

    $ alembic heads
    0919_bo_cot_kind
    0919_hop_nhat_hai_head_0918

VÌ SAO CÓ HAI HEAD: `0919_bo_cot_kind_deployments` được viết trên một checkout
chưa có `0918_media_category_csbh` / `0919_hop_nhat_hai_head_0918` (nhánh khác,
merge vào develop song song) — nên nó nhận `0918_agent_keys_kho_tho` làm cha,
hợp lệ ở thời điểm viết, rồi cả hai merge riêng rẽ vào develop:

    0918_agent_keys_kho_tho
    ├── 0919_bo_cot_kind_deployments   (bỏ cột control.deployments.kind)
    └── 0919_hop_nhat_hai_head_0918     (điểm hợp nhất của lần hai-head trước)

Đúng bài học đã ghi ở `0914_hop_nhat_hai_head`/`0919_hop_nhat_hai_head_0918`: git
merge sạch cả hai lần vì tên tệp khác nhau, chỉ alembic thấy, và chỉ khi ai đó
chạy migrate — nên nó lại đi thẳng vào develop mà không MR nào đỏ.

HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA: đổi `down_revision` của `0919_bo_cot_kind_deployments`
thành `0919_hop_nhat_hai_head_0918` sẽ làm alembic coi mergepoint đó là tổ tiên đã
áp trên một DB thật ra chưa từng chạy qua nó. Điểm hợp nhất không viết lại tổ tiên
của tệp nào — DB đang ở nhánh nào cũng đi tiếp đúng: áp nốt nhánh còn thiếu rồi
tới đây.

HAI NHÁNH ĐỘC LẬP THẬT: một bên xoá cột `control.deployments.kind`, một bên là
một node hợp nhất rỗng (không DDL) của đợt hai-head trước. Không chồng đối tượng.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có.

Revision ID: 0920_hop_nhat_hai_head_0919
Revises: 0919_bo_cot_kind, 0919_hop_nhat_hai_head_0918
"""

revision = "0920_hop_nhat_hai_head_0919"
down_revision = ("0919_bo_cot_kind", "0919_hop_nhat_hai_head_0918")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
