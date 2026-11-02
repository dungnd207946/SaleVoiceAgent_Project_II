"""tenant_data.escalations — thêm 5 cột phân loại lý do chuyển + chấm lead

Các cột này đã được thêm TAY vào DB dev; migration này đưa chúng vào code để
production có cùng hình dạng bảng. Hình dạng lấy y nguyên từ bảng thực tế:

  · `reason_kind`  text     — loại lý do chuyển cho sale
  · `lead_stage`   text     — giai đoạn lead lúc chuyển
  · `lead_score`   integer  — điểm lead
  · `audience`     text     — đối tượng khách
  · `lead_signals` jsonb    — tín hiệu thô dẫn tới điểm/giai đoạn

Tất cả NULL được, không DEFAULT, không CHECK — cùng lý lẽ `status` ở `0924`: tập giá
trị do agent quyết, Portal không khoá cứng.

`IF NOT EXISTS`: DB dev đã có sẵn cột (thêm tay) — chạy lại không lỗi.

Quyền: GRANT của `0924` (`grant_agent_write`) là ở mức BẢNG nên tự phủ cột mới; RLS
là theo hàng nên không cần đụng tới.

Revision ID: 0968_escalations_lead
Revises: 0967_role_config
"""

from alembic import op

revision = "0968_escalations_lead"
down_revision = "0967_role_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_data.escalations
            ADD COLUMN IF NOT EXISTS reason_kind  text,
            ADD COLUMN IF NOT EXISTS lead_stage   text,
            ADD COLUMN IF NOT EXISTS lead_score   integer,
            ADD COLUMN IF NOT EXISTS audience     text,
            ADD COLUMN IF NOT EXISTS lead_signals jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_data.escalations
            DROP COLUMN IF EXISTS lead_signals,
            DROP COLUMN IF EXISTS audience,
            DROP COLUMN IF EXISTS lead_score,
            DROP COLUMN IF EXISTS lead_stage,
            DROP COLUMN IF EXISTS reason_kind
        """
    )
