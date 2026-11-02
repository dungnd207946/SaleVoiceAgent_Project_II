"""control.audit_log — nhật ký hoạt động (bản tối thiểu)

AI SỞ HỮU BẢNG NÀY, VÀ VÌ SAO NÓ Ở ĐÂY CHỨ KHÔNG Ở M8:
Màn «Nhật ký & Dữ liệu» thuộc M8, và M8 sẽ là chủ bảng này. Nhưng nhật ký ghi một
SỰ KIỆN, và sự kiện chỉ xảy ra một lần. Nếu M5 ship trước mà không ghi thì mọi
lần áp dụng cấu hình từ nay tới lúc M8 xong đều mất dấu — đúng quãng có nhiều
thay đổi nhất, lúc khách đang thử nghiệm và lúc câu hỏi "ai đổi cái gì" hay nhất.

Nên M5 tạo bản TỐI THIỂU và ghi vào; M8 mở rộng (retention 6 tháng, job xoá, lọc
theo loại, nhật ký đọc bản ghi thoại của PQ_01 BR-Q07). Đổi chủ sở hữu là sửa một
dòng trong tests/integration/test_control_schema.py.

VÌ SAO `chi_tiet` LÀ jsonb CHỨ KHÔNG PHẢI CỘT RỜI: mỗi loại hành động cần dữ kiện
khác nhau — publish cần `version` + `truong_da_doi`, xoá tài liệu (M6) cần tên
tệp, đọc bản ghi thoại (M2b) cần id cuộc gọi. Cột rời nghĩa là mỗi module thêm
một migration ALTER, và bảng đầy cột NULL.

VÌ SAO KHÔNG CÓ FK TỪ `actor` SANG `users`: nhật ký phải sống lâu hơn tài khoản.
Xoá một nhân viên mà xoá luôn dấu vết những gì họ đã đổi là mất đúng thứ nhật ký
tồn tại để giữ. `ON DELETE SET NULL` cũng không đủ — cần biết AI, kể cả khi họ
không còn.

Revision ID: 0201_audit_log
Revises: 0200_config_store
"""

from alembic import op

revision = "0201_audit_log"
down_revision = "0200_config_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.audit_log (
            id        bigserial PRIMARY KEY,
            tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            hanh_dong text NOT NULL CHECK (hanh_dong <> ''),
            actor     text NOT NULL DEFAULT '',
            chi_tiet  jsonb NOT NULL DEFAULT '{}'::jsonb,
            luc       timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # Màn Nhật ký luôn hỏi "của workspace này, mới nhất trước".
    op.execute("CREATE INDEX audit_log_tenant_luc_idx ON control.audit_log (tenant_id, luc DESC)")

    # Nhật ký chỉ được GHI THÊM. Sửa hay xoá một hàng nhật ký làm nó hết là nhật
    # ký — cùng lý lẽ với bất biến của config_versions ở 0200, và cùng cái bẫy:
    # ALTER DEFAULT PRIVILEGES của 0003 vừa tự cấp UPDATE/DELETE cho portal_api.
    op.execute("REVOKE UPDATE, DELETE ON control.audit_log FROM portal_api")


def downgrade() -> None:
    op.execute("DROP TABLE control.audit_log")
