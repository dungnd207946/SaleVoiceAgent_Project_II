"""`tenant_data.nhan_vat` — người dẫn (nhân vật lip sync) do workspace tự tạo.

Tab Voice có người dẫn MẶC ĐỊNH (đóng gói trong service lipsync-musetalk). Khách tạo thêm
người dẫn riêng từ một VIDEO tự quay, hoặc từ một ẢNH (sinh video bằng API ngoài — nhà
cung cấp chọn bằng env, xem `modules/nhan_vat/settings.py`). Mỗi hàng đi qua các trạng thái:

    tao_video ─► dung ─► xem_truoc ─► san_sang          (nguồn ảnh)
                 dung ─► xem_truoc ─► san_sang          (nguồn video)
         └──────────┴──────────┴─► loi (loi_ma — FE đổi thành hướng dẫn, «Thử lại» được)

`avatar_id` là id của nhân vật trên service lipsync (dùng chung mọi tenant) ⇒ duy nhất
TOÀN CỤC, sinh ngẫu nhiên (khó đoán — trình duyệt gửi nó trên URL WebSocket).

`dang_dung` — nhân vật tab Voice đang dùng; không hàng nào `dang_dung` = dùng người dẫn
mặc định. Tối đa MỘT hàng mỗi tenant (unique index một phần).

Revision ID: 0970_nhan_vat
Revises: 0969_billing_purpose_playbook
"""

from alembic import op

revision = "0970_nhan_vat"
down_revision = "0969_billing_purpose_playbook"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_data.nhan_vat (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            ten           text NOT NULL CONSTRAINT nhan_vat_ten_check CHECK (btrim(ten) <> '' AND length(ten) <= 60),
            nguon         text NOT NULL CONSTRAINT nhan_vat_nguon_check CHECK (nguon IN ('video', 'anh')),
            trang_thai    text NOT NULL CONSTRAINT nhan_vat_trang_thai_check
                              CHECK (trang_thai IN ('tao_video', 'dung', 'xem_truoc', 'san_sang', 'loi')),
            buoc          text,
            tien_do       real NOT NULL DEFAULT 0,
            loi_ma        text,
            loi_chi_tiet  text,
            avatar_id     text NOT NULL UNIQUE CONSTRAINT nhan_vat_avatar_id_check
                              CHECK (avatar_id ~ '^[a-z0-9][a-z0-9_-]{2,63}$'),
            mo_ta         text CONSTRAINT nhan_vat_mo_ta_check CHECK (length(mo_ta) <= 500),
            anh_key       text,
            video_key     text,
            video_tay_key text,
            poster_key    text,
            tac_vu        jsonb NOT NULL DEFAULT '{}'::jsonb,
            xem_truoc     jsonb NOT NULL DEFAULT '[]'::jsonb,
            dang_dung     boolean NOT NULL DEFAULT false,
            dong_y_luc    timestamptz NOT NULL,
            tao_boi       text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX nhan_vat_tenant_idx ON tenant_data.nhan_vat (tenant_id, created_at)")
    op.execute("CREATE UNIQUE INDEX nhan_vat_dang_dung_key ON tenant_data.nhan_vat (tenant_id) WHERE dang_dung")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.nhan_vat')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_data.nhan_vat")
