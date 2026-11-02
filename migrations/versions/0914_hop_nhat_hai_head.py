"""Hợp nhất hai head — `alembic upgrade head` gãy trên develop kể từ 2026-08-06

TRIỆU CHỨNG (đo trên chính develop, không phải suy đoán):

    $ alembic heads
    0912_full_conversation (head)
    0913_bat_lai_rls_tenant_data (head)

    $ alembic upgrade head
    FAILED: Multiple head revisions are present for given argument 'head'

Tức `make migrate` và `make up` tắc cho MỌI người clone mới, và cho CI.

VÌ SAO CÓ HAI HEAD: hai MR mở song song, mỗi bên nhận `0911_tenant_id_gach_ngang`
làm cha — hợp lệ ở thời điểm viết — rồi merge riêng rẽ.

    0911_tenant_id_gach_ngang
    ├── 0912_config_agent  →  0913_bat_lai_rls_tenant_data
    └── 0912_full_conversation

Git không thấy gì vì hai tên tệp khác nhau; chỉ alembic thấy, và chỉ khi ai đó
chạy migrate. Không có cổng CI nào chạy `alembic heads`, nên nó lọt tới develop.

VÌ SAO HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA. Cách một dòng là sửa `down_revision` của
`0912_full_conversation` thành `0913_bat_lai_rls_tenant_data`. Nó SAI ÂM THẦM với
môi trường đã áp nhánh kia: DB đó mang `alembic_version = '0912_full_conversation'`,
và sau khi đổi cha thì alembic coi mọi tổ tiên MỚI của nó — gồm `0912_config_agent`
và `0913` — là đã áp. DB thiếu bảng, alembic tưởng đủ, và không lệnh nào báo.
Ta không kiểm được từ đây môi trường nào đã áp nhánh nào, nên không được đánh cược.

Điểm hợp nhất không viết lại tổ tiên của bất kỳ tệp nào. DB đang ở nhánh nào cũng
đi tiếp đúng: áp nốt nhánh còn thiếu, rồi tới đây.

KHÔNG CÓ DDL. Đây là một nút trong đồ thị, không phải một thay đổi lược đồ. Thân
hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay đổi lược đồ trong một
tệp mà tên nó nói rằng không có.

Revision ID: 0914_hop_nhat_hai_head
Revises: 0913_bat_lai_rls_tenant_data, 0912_full_conversation
"""

revision = "0914_hop_nhat_hai_head"
down_revision = ("0913_bat_lai_rls_tenant_data", "0912_full_conversation")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây sẽ tách lại thành hai nhánh, đúng như trước."""
