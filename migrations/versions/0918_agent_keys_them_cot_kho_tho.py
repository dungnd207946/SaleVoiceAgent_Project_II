"""agent_keys thêm cột api_key (khoá THÔ) cạnh key_sha256 — không đổi đường xác thực

QUYẾT ĐỊNH GIẢM AN TOÀN, THEO YÊU CẦU TƯỜNG MINH CỦA NGƯỜI VẬN HÀNH (đối chiếu
văn hoá "đánh đổi phải nêu rõ" ở `0917`): `/thu-agent` (repo frontend) cần một
`<select>` chọn khoá THEO TÊN mà vẫn nối WS thật được — tức backend phải trả
lại được khoá thô sau khi tạo, không chỉ đúng một lần như `0900` đã thiết kế
(`bi_mat.sinh_khoa()`: "không đường nào đọc lại được, kể cả admin").

CỐ Ý **THÊM CỘT**, KHÔNG ĐỔI/BỎ `key_sha256`: đường xác thực thật
(`repo.tra_khoa`, `repo.cham_last_used`, rate-limit ở `service._cho_qua_nhip`)
tiếp tục tra theo hash như cũ, không đụng tới. `api_key` chỉ phục vụ MỘT việc
mới: liệt kê khoá kèm giá trị thô để FE dựng `<select>`. Đây là lựa chọn nhỏ
hơn hẳn "bỏ hash, chỉ lưu thô" (đã cân nhắc rồi bỏ) — giữ nguyên mọi bất biến
cũ, chỉ mở thêm một mặt lộ.

`NULL`able, KHÔNG `NOT NULL`: khoá đã tạo TRƯỚC migration này không có cách
nào lấy lại bản thô để backfill (đúng tính chất một-chiều của sha256) — hàng
cũ sẽ có `api_key IS NULL`, và `/thu-agent` chỉ chọn được khoá tạo SAU migration
này. Không UNIQUE (khác `key_sha256`): NULL không phá UNIQUE trong Postgres,
nhưng thêm ràng buộc cho một cột chỉ phục vụ hiển thị là thêm việc không ai cần.

HỆ QUẢ CHẤP NHẬN: từ nay ai đọc được `control.agent_keys` (backup, replica, log
dump, admin DB) có luôn khoá thật của các khoá tạo sau migration này — khác
với trước (chỉ có hash một chiều, vô dụng nếu lộ ra ngoài DB).

Revision ID: 0918_agent_keys_kho_tho
Revises: 0917_bo_agent_api
"""

from alembic import op

revision = "0918_agent_keys_kho_tho"
down_revision = "0917_bo_agent_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.agent_keys ADD COLUMN api_key text")


def downgrade() -> None:
    op.execute("ALTER TABLE control.agent_keys DROP COLUMN api_key")
