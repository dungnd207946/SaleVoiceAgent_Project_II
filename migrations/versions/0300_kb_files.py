"""tenant_data.kb_files — sổ tài liệu của workspace (M6)

VÌ SAO Ở `tenant_data` CHỨ KHÔNG PHẢI `control`, khác với ba bảng của M3:
đây là dữ liệu NGHIỆP VỤ của khách. Tên tệp mang tên dự án, `uploaded_by` là
nhân viên của họ, và danh sách tài liệu nói họ đang bán gì. Dữ liệu như thế đặt
ở `control` là đặt ở chỗ KHÔNG có RLS — cổng 6 của M1 sẽ bắt, nhưng lý do phải
nằm ở đây để người đọc migration hiểu ngay.

Hệ quả: gọi `control.enforce_tenant_isolation()` như mọi bảng tenant_data khác.
Không gọi thì cổng 6 đỏ ngay ở CI, không phải chờ ai review nhớ ra.

BA TRẠNG THÁI, KHÔNG BỐN (KB_01 §II.3): `dang_xu_ly · san_sang · loi`. Bản trước
của spec M6 có thêm `dang_tai_len` — sai: hàng chỉ được tạo SAU khi file đã lên
kho tệp, nên trạng thái đó không bao giờ quan sát được từ giao diện.

VÌ SAO `chunk_count` KHÔNG PHẢI NGUỒN SỰ THẬT: số chunk thật nằm ở Qdrant. Cột
này là con số để HIỆN, cập nhật sau khi index xong. Đọc nó để quyết định nghiệp
vụ (ví dụ "có chunk thì coi như sẵn sàng") là tin vào bản sao — `state` mới là
thứ quyết định, và BR06 gắn vào `state`.

Revision ID: 0300_kb_files
Revises: 0201_audit_log
"""

from alembic import op

revision = "0300_kb_files"
down_revision = "0201_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_data.kb_files (
            id          bigserial PRIMARY KEY,
            tenant_id   text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            ten_file    text NOT NULL CHECK (ten_file <> ''),
            s3_key      text NOT NULL CHECK (s3_key <> ''),
            kich_thuoc  bigint NOT NULL CHECK (kich_thuoc > 0),
            loai        text NOT NULL
                        CONSTRAINT kb_files_loai_check CHECK (loai IN ('pdf', 'docx', 'xlsx')),
            state       text NOT NULL DEFAULT 'dang_xu_ly'
                        CONSTRAINT kb_files_state_check CHECK (state IN ('dang_xu_ly', 'san_sang', 'loi')),
            chunk_count integer NOT NULL DEFAULT 0,
            loi_message text NOT NULL DEFAULT '',
            uploaded_at timestamptz NOT NULL DEFAULT now(),
            uploaded_by text REFERENCES control.users(id) ON DELETE SET NULL
        )
        """
    )

    # Danh sách luôn hỏi "của workspace này, mới nhất trước" (KB_01 §II.3).
    op.execute("CREATE INDEX kb_files_tenant_moi_idx ON tenant_data.kb_files (tenant_id, uploaded_at DESC)")

    # Bật RLS + FORCE + policy + grant cho portal_api. Cổng 6 của M1 quét đúng
    # ba thứ đó; bỏ dòng này là CI đỏ, không phải là một lỗ hổng im lặng.
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.kb_files')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.kb_files")
