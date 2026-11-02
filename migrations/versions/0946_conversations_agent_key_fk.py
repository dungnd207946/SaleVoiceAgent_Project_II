"""siết attribution: composite FK + ON DELETE RESTRICT trên conversations.agent_key_id

HAI LỖ ĐANG MỞ, đo được trên DB dev 2026-08-20:

① FK hiện tại `conversations_agent_key_id_fkey` chỉ tham chiếu `agent_keys(id)`.
   Về mặt DB, gán khoá của tenant A cho conversation của tenant B là HỢP LỆ. Data
   hiện không có ca nào (đã kiểm: 0 hàng lệch tenant), nhưng không gì chặn. Từ khi
   `0940` cho `agent_keys` cột `tenant_id`, việc này chặn được bằng composite FK —
   trước đó thì không.

② `ON DELETE SET NULL` nghĩa là xoá một khoá thì TOÀN BỘ usage quá khứ của nó rơi
   về "chưa phân loại": mất thông tin ai đã dùng, mà không lỗi nào phát ra và số
   tổng vẫn đúng nên không ai thấy. Bảng đã có `revoked_at` — đường đúng là thu hồi,
   không xoá. RESTRICT biến quy ước đó thành ràng buộc.

⚠️ ĐƯỜNG XOÁ KHOÁ Ở TẦNG APP: endpoint tenant `POST /agent/keys/{key_id}` (`status:
active|inactive`) đã set `revoked_at` chứ không DELETE — không có gì phải sửa.
Đường admin nền tảng `DELETE /admin/keys/{key_id}` gọi `service.thu_hoi_khoa` →
`repo.thu_hoi_khoa`, cũng chỉ `UPDATE ... SET revoked_at = now()` (đã đọc code,
không phải suy đoán) — dù tên hàm/method HTTP gợi ý xoá, nó chưa từng ném DELETE
thật. Không có khoảng hở 500 nào cần đóng ở app layer cho migration này.

Revision ID: 0946_conversations_agent_key_fk
Revises: 0945_billing_action
"""

from alembic import op

revision = "0946_conversations_agent_key_fk"
down_revision = "0945_billing_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.agent_keys ADD CONSTRAINT agent_keys_tenant_id_uk UNIQUE (tenant_id, id)")
    op.execute("ALTER TABLE tenant_data.conversations DROP CONSTRAINT IF EXISTS conversations_agent_key_id_fkey")
    op.execute(
        """ALTER TABLE tenant_data.conversations
           ADD CONSTRAINT conversations_agent_key_fkey
           FOREIGN KEY (tenant_id, agent_key_id)
           REFERENCES control.agent_keys (tenant_id, id) ON DELETE RESTRICT"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.conversations DROP CONSTRAINT IF EXISTS conversations_agent_key_fkey")
    op.execute(
        """ALTER TABLE tenant_data.conversations
           ADD CONSTRAINT conversations_agent_key_id_fkey
           FOREIGN KEY (agent_key_id) REFERENCES control.agent_keys (id)
           ON DELETE SET NULL"""
    )
    op.execute("ALTER TABLE control.agent_keys DROP CONSTRAINT IF EXISTS agent_keys_tenant_id_uk")
