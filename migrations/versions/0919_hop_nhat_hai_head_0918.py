"""Hợp nhất hai head 0918 — `alembic upgrade head` gãy trên develop từ 2026-08-11

TRIỆU CHỨNG (job deploy của CI, không phải suy đoán):

    $ docker compose run --rm migrate
    ERROR [alembic.util.messaging] Multiple head revisions are present for given
    argument 'head'
    FAILED: Job failed: exit status 255

    $ alembic heads
    0918_agent_keys_kho_tho (head)
    0918_media_category_csbh (head)

VÌ SAO CÓ HAI HEAD: hai MR mở song song, mỗi bên nhận `0917_bo_agent_api` làm cha
— hợp lệ ở thời điểm viết — rồi merge riêng rẽ vào develop.

    0917_bo_agent_api
    ├── 0918_agent_keys_kho_tho      (cột control.agent_keys.api_key)
    └── 0918_media_category_csbh     (CHECK media.category lên 8 giá trị)

Lần thứ hai repo này gặp đúng lỗi đó — xem `0914_hop_nhat_hai_head`. Git merge
sạch cả hai lần vì tên tệp khác nhau; chỉ alembic thấy, và chỉ khi ai đó chạy
migrate. `tests/unit/test_alembic_mot_head.py` bắt được, nhưng nó chạy trên NHÁNH
— không nhánh nào một mình có hai head, nên cổng xanh ở cả hai MR rồi vỡ sau merge.

VÌ SAO HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA — lần này có bằng chứng, không chỉ là lý lẽ:
Aurora dev đo 2026-08-11 có `control.agent_keys.api_key` nhưng `media_category_hop_le`
vẫn 7 giá trị, tức nó ĐANG ở `0918_agent_keys_kho_tho`. Sửa `down_revision` của
nhánh kia thành `0918_agent_keys_kho_tho` sẽ làm alembic coi `0918_media_category_csbh`
là tổ tiên đã áp trên chính DB chưa áp nó — CHECK ở lại 7 giá trị vĩnh viễn và
không lệnh nào báo.

Điểm hợp nhất không viết lại tổ tiên của tệp nào. DB đang ở nhánh nào cũng đi tiếp
đúng: áp nốt nhánh còn thiếu, rồi tới đây.

HAI NHÁNH ĐỘC LẬP THẬT, đã đối chiếu: một bên `control.agent_keys`, một bên
CHECK trên `tenant_data.media`. Không chồng đối tượng nên thứ tự áp không đổi kết quả.

KHÔNG CÓ DDL. Đây là một nút trong đồ thị, không phải một thay đổi lược đồ. Thân
hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay đổi lược đồ trong một
tệp mà tên nó nói rằng không có.

Revision ID: 0919_hop_nhat_hai_head_0918
Revises: 0918_agent_keys_kho_tho, 0918_media_category_csbh
"""

revision = "0919_hop_nhat_hai_head_0918"
down_revision = ("0918_agent_keys_kho_tho", "0918_media_category_csbh")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
