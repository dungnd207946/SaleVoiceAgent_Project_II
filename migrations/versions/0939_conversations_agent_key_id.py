"""tenant_data.conversations — thêm cột `agent_key_id`

VẤN ĐỀ NÓ GIẢI: một workspace có NHIỀU khoá agent (`control.agent_keys`, 0900) —
mỗi pod/kênh/lần thử nghiệm một khoá. Hàng `conversations` hiện chỉ nói phiên
thuộc tenant nào và đến từ `source` nào (0916), KHÔNG nói khoá nào đã tạo ra nó.
Khi một khoá bị lộ, bị tắt, hay khi cần tách số liệu theo từng pod, không có
đường nào quy phiên về khoá — phải suy đoán qua thời gian và `source`.

VÌ SAO `bigint` NULLABLE, CÓ FK `ON DELETE SET NULL`:
  · `bigint` khớp `control.agent_keys.id` (`bigserial`, 0900).
  · CÓ FK bắc ngang `tenant_data` → `control` — đó là lệ SẴN CÓ của repo này, KHÔNG
    phải ngoại lệ: 19 khoá ngoại như vậy đang chạy, và chính `conversations` đã có
    `tenant_id → control.tenants(id)`. Tiền lệ khớp từng nét là
    `kb_files.uploaded_by → control.users(id) ON DELETE SET NULL` (cột nullable trỏ
    một hàng control-plane).
    ⚠️ FK KHÔNG đòi role agent phải đọc được `control.agent_keys`: Postgres kiểm
    ràng buộc bằng trigger RI nội bộ chạy với quyền của CHỦ bảng, không phải quyền
    của người ghi. Đo được: `agent_all`/`odyssey_agent` có ZERO quyền trên
    `control.users` mà FK của `kb_files` vẫn chạy nhiều tháng nay. Bản nháp đầu của
    migration này từ chối FK vì lý lẽ ngược lại — lý lẽ đó SAI.
  · `ON DELETE SET NULL` chứ không `CASCADE`: xoá một khoá KHÔNG được phép xoá lịch
    sử hội thoại. Thực tế chưa câu SQL nào trong repo xoá hàng `agent_keys` (thu hồi
    = đặt `revoked_at`, xem `repo.dat_trang_thai_khoa`), nhưng `agent_keys.deployment_id`
    có `ON DELETE CASCADE` từ `0900` — nên xoá một deployment SẼ quét sạch khoá của
    nó, và không có vế `SET NULL` ở đây thì thao tác đó kéo theo hội thoại.
  · NULLABLE — hàng đã có KHÔNG biết khoá nào tạo ra chúng, và không có nguồn nào
    backfill được. `NULL` nói đúng sự thật đó ("không biết"), khác hẳn `0`/`-1` là
    hai giá trị trông như khoá thật. Cũng là điều kiện để `SET NULL` hợp lệ.

KHÔNG dùng lý lẽ của `0921`/`0924` cho cột này. Hai bảng đó bỏ FK vì THỨ TỰ GHI:
`session_id` trỏ một hàng `conversations` mà agent có thể chưa chốt lúc ghi. Ở đây
ngược hẳn — hàng `agent_keys` chắc chắn tồn tại TRƯỚC, vì không có nó thì pod không
gọi nổi `/runtime-credentials` để biết `agent_key_id`.

CHỈ SỐ: `conversations_agent_key_idx` cho đường "mọi phiên của khoá X" — câu hỏi
duy nhất cột này sinh ra. Partial `WHERE agent_key_id IS NOT NULL` để hàng cũ
(và mọi hàng agent chưa gửi khoá) không chiếm chỗ trong index.

KHÔNG REWRITE BẢNG: `ADD COLUMN` nullable không DEFAULT là thao tác metadata.

KHÔNG CẦN GRANT LẠI CHO AGENT: `control.grant_agent_write()` (0005/0905) cấp
`GRANT SELECT, INSERT, UPDATE ON <bảng>` — quyền mức BẢNG, nên cột mới nằm trong
đó sẵn. Cùng ghi chú với 0912; nếu hàm ấy đổi sang grant mức CỘT thì chỗ này phải
cấp lại tay.

Revision ID: 0939_conversations_agent_key_id
Revises: 0938_hop_nhat_hai_head
"""

from alembic import op

revision = "0939_conversations_agent_key_id"
down_revision = "0938_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_data.conversations
            ADD COLUMN agent_key_id bigint
                REFERENCES control.agent_keys(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX conversations_agent_key_idx
            ON tenant_data.conversations (agent_key_id)
         WHERE agent_key_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # DROP COLUMN xoá luôn index đi kèm — không cần DROP INDEX riêng.
    op.execute("ALTER TABLE tenant_data.conversations DROP COLUMN agent_key_id")
