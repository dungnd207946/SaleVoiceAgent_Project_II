"""tenant_data.agent_config — cột `tts_normalization` (từ điển cách đọc TTS của tenant)

VÌ SAO OBJECT CHỨ KHÔNG PHẢI MẢNG, khác `departments`/`skills`: đó đúng hình dạng
`{term: read_as}` mà `_normalize.py` bên agent đang parse từ file nền
(`data/tts_normalize_vi.json`), nên phép trộn bên đó là một dòng thay vì thêm một tầng dịch.

Cột này là LỚP CHỒNG LÊN bộ nền, không thay nó. Trùng khoá thì tenant thắng.

⚠️ HỆ QUẢ Ở REPO AGENT: `agent_config_store._read_from_db` giải mã mọi cột jsonb bằng
`_decode(...) or []`, và `{}` là FALSY trong Python — một từ điển rỗng sẽ thành `[]` rồi
`parse_config` nhận list ở chỗ nó chờ dict. Hai cột jsonb hiện có đều là mảng nên dòng đó
chưa từng sai. Bên agent phải có một tập cột riêng giải mã bằng `or {}`.

⚠️ THỨ TỰ DEPLOY MỘT CHIỀU: migration này TRƯỚC, agent SAU. Đảo lại thì agent không chết —
`read_published_config` bắt `except Exception` rồi phục vụ cache last-good trên đĩa, nên nó
ĐÓNG BĂNG ở bản cũ và mọi lần publish sau đó bị bỏ qua, không dấu hiệu nào.

KHÔNG REWRITE BẢNG: `DEFAULT` là hằng không volatile, nên Postgres 11+ làm
`ADD COLUMN NOT NULL DEFAULT` ở mức metadata thuần.

KHÔNG CẦN GRANT LẠI: quyền trên `tenant_data.agent_config` cấp ở mức BẢNG, cột mới thừa
hưởng sẵn.

Revision ID: 0954_tts_normalization
Revises: 0953_bu_invites_role_id
"""

from alembic import op

revision = "0954_tts_normalization"
down_revision = "0953_bu_invites_role_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_data.agent_config
            ADD COLUMN tts_normalization jsonb NOT NULL DEFAULT '{}'::jsonb
            CONSTRAINT agent_config_tts_normalization_object_check
            CHECK (jsonb_typeof(tts_normalization) = 'object')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.agent_config DROP COLUMN tts_normalization")
