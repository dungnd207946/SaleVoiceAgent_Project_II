"""hợp nhất hai head `0954` — bảng giá vendor × cột tts_normalization

VÌ SAO CÓ TỆP NÀY: hai nhánh cùng gắn vào `0953_bu_invites_role_id` rồi cùng
được merge vào `develop`:
  * `0954_bang_gia_vendor`   — bảng giá VND theo giá vendor (billing)
  * `0954_tts_normalization` — cột `tenant_data.agent_config.tts_normalization`
Alembic không chọn hộ giữa hai head, nên `alembic upgrade head` ở bước deploy
chết ngay từ lúc phân giải mục tiêu, TRƯỚC khi chạy bất kỳ DDL nào:
    Multiple head revisions are present for given argument 'head'
Đó là lỗi đã làm job `deploy:dev` đỏ với exit 255 — không phải nội dung của một
trong hai migration.

⚠️ ĐỌC LOG DEPLOY CHO ĐÚNG CHỖ: `docker compose run --rm migrate` xoá container
ngay khi xong, nên khối `after_script` (`compose logs --tail=40`) KHÔNG in được
lỗi này — nó chỉ in log các service còn sống (postgres healthy, backend 200).
Traceback nằm inline ngay dưới dòng `run --rm migrate` trong job log.

GIAO CỦA HAI TẬP ĐỐI TƯỢNG LÀ RỖNG, nên thứ tự áp nào cũng ra cùng một lược đồ:
  * `0954_bang_gia_vendor` chỉ chạm `billing.price_version` (INSERT một bản giá,
    chuyển cờ `is_default`, hạ `status` bản `0949`) — không một câu lệnh nào
    ngoài schema `billing`.
  * `0954_tts_normalization` chỉ chạm `tenant_data.agent_config` (ADD COLUMN
    `tts_normalization`) — không nhắc `billing`.
Không có thứ tự nào giữa hai bên tạo ra phụ thuộc: cột `tts_normalization` không
tham gia định giá, và không dòng giá nào đọc `agent_config`.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có. Cùng khuôn với
`0951_hop_nhat_hai_head_0950.py`, `0943_hop_nhat_hai_head` và các bản trước.

Revision ID: 0955_hop_nhat_hai_head
Revises: 0954_bang_gia_vendor, 0954_tts_normalization
"""

revision = "0955_hop_nhat_hai_head"
down_revision = ("0954_bang_gia_vendor", "0954_tts_normalization")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
