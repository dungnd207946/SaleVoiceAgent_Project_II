"""contacts · conversations · appointments — ba bảng agent GHI

VẤN ĐỀ NÓ GIẢI: `docs/contracts/dau-noi-agent.md` G-6 đã báo trước "ba bảng contacts ·
conversations · appointments SẼ có". Chúng đã tồn tại và đang được ghi ở DB của team agent
(154 hàng của tenant `noble`), nhưng Portal chưa có chỗ chứa. Muốn một DB dùng chung thì
Portal phải sở hữu ba bảng này, dưới đúng luật cách ly của nó.

HÌNH DẠNG LẤY TỪ BẢNG ĐANG CHẠY CỦA HỌ, không tự thiết kế lại: agent đang INSERT vào đúng
những cột này. Đổi tên cột hay đổi kiểu ở đây là bắt họ sửa code cho một việc mà lẽ ra chỉ
là đổi DSN. Ba chỗ Portal SIẾT thêm (dữ liệu hiện có thoả cả ba, đã kiểm):

  · `contacts` PK `(tenant_id, phone)` — của họ không có PK. 6/6 hàng đã duy nhất theo cặp
    đó, và một liên hệ hai hàng thì không có hàng nào là "hồ sơ của số này".
  · `conversations` UNIQUE `(tenant_id, session_id)` — 11/11 đã duy nhất.
  · `appointments` UNIQUE `(tenant_id, appointment_id)` — 147/147 `appointment_id` phân biệt.

⚠️ `appointments.appointment_id` GIỮ NULLABLE dù 0/147 hàng là NULL. Bảng của họ cho NULL,
nên nếu agent có một đường ghi nào không đặt trường đó, siết thành NOT NULL làm đường ghi đó
VỠ ngay lúc đổi DSN — một lỗi do Portal gây ra trên code Portal không đọc được. UNIQUE vẫn
có tác dụng chống trùng vì Postgres cho phép nhiều NULL trong UNIQUE.

⚠️ `appointments.project_code` KHÔNG có FK về `projects` — QUYẾT ĐỊNH DO DỮ LIỆU ÉP RA, không
phải bỏ sót. 147/147 hàng có `project_code` là `NCLB`/`SLC`, KHÔNG khớp bất kỳ hàng nào trong
41 project của họ. Đặt FK ở đây là từ chối 100% dữ liệu cần nạp. Hai mã đó trông như mã nội
bộ của luồng đặt hẹn, không phải khoá ngoại vào catalog. Cổng
`test_appointments_khong_co_fk_project_code` ghi lại lý do để lần sau ai đó "thêm FK cho
chuẩn" phải đọc trước khi làm.

VÌ SAO GỌI `grant_agent_write()` CHỨ KHÔNG DỰNG VIEW `agent_api`: ba bảng này là write-back —
agent ghi thì phải đọc lại được cái nó ghi, nên gate cột của `agent_api` không áp được (một
view chỉ-đọc không cho INSERT). Đây đúng là trường hợp mà `control.grant_agent_write()` được
xuất ra để phục vụ (spec §8.1), và cổng 5 đã ghi sẵn cảnh báo: bảng nào đi qua hàm này thì
agent có SELECT TRỰC TIẾP trên bảng gốc, tức KHÔNG còn gate cột. Với ba bảng này thì chấp
nhận được vì chúng KHÔNG mang dữ liệu catalog — chúng mang chính thứ agent vừa tạo ra.
Người thêm dòng vào `AGENT_WRITABLE_TENANT_DATA_TABLES` phải biết điều đó.

Revision ID: 0903_write_back
Revises: 0902_zone_nullable
"""

from alembic import op

revision = "0903_write_back"
down_revision = "0902_zone_nullable"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    # ─── contacts — hồ sơ một số điện thoại ──────────────────────────────────
    # PK là (tenant_id, phone), KHÔNG phải id tự tăng: bảng này là "những gì ta biết
    # về số này", nên hai hàng cùng số thì không hàng nào là sự thật. Cùng lý lẽ với
    # `config_drafts` (0200) chọn tenant_id làm PK.
    op.execute(
        f"""
        CREATE TABLE tenant_data.contacts (
            tenant_id  {_TENANT_FK},
            phone      text NOT NULL CONSTRAINT contacts_phone_check CHECK (phone <> ''),
            snapshot   text NOT NULL DEFAULT '',
            profile    jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, phone)
        )
        """
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.contacts')")
    op.execute("SELECT control.grant_agent_write('tenant_data.contacts')")

    # ─── conversations — một phiên hội thoại ─────────────────────────────────
    op.execute(
        f"""
        CREATE TABLE tenant_data.conversations (
            id                   bigserial PRIMARY KEY,
            tenant_id            {_TENANT_FK},
            session_id           text NOT NULL
                                 CONSTRAINT conversations_session_check CHECK (session_id <> ''),
            phone                text,
            customer_name        text,
            -- `project` là TÊN dự án dạng chữ tự do mà agent nghe được trong hội thoại,
            -- KHÔNG phải `project_code`. Không đổi tên thành project_code: nó không
            -- phải mã, và đặt tên như mã sẽ mời một FK không đúng ngữ nghĩa.
            project              text,
            transferred_to_sales boolean NOT NULL DEFAULT false,
            -- Version config agent đang chạy lúc diễn ra hội thoại. Không FK về
            -- config_versions: một hội thoại vẫn có ý nghĩa sau khi version bị dọn.
            running_version      integer,
            summary              text,
            skill_calls          jsonb NOT NULL DEFAULT '[]'::jsonb,
            started_at           timestamptz,
            ended_at             timestamptz,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT conversations_tenant_session_key UNIQUE (tenant_id, session_id)
        )
        """
    )
    op.execute("CREATE INDEX conversations_tenant_phone_idx ON tenant_data.conversations (tenant_id, phone)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.conversations')")
    op.execute("SELECT control.grant_agent_write('tenant_data.conversations')")

    # ─── appointments — lịch hẹn agent chốt được ─────────────────────────────
    op.execute(
        f"""
        CREATE TABLE tenant_data.appointments (
            id              bigserial PRIMARY KEY,
            tenant_id       {_TENANT_FK},
            appointment_id  text
                            CONSTRAINT appointments_appt_id_check
                            CHECK (appointment_id IS NULL OR appointment_id <> ''),
            session_id      text,
            customer_name   text,
            phone           text,
            -- KHÔNG FK — xem header. Mã ở đây là mã của luồng đặt hẹn, không phải
            -- khoá ngoại vào catalog dự án.
            project_code    text,
            -- `preferred_date`/`preferred_time` là TEXT, không phải date/time: nguồn
            -- là câu khách nói ("cuối tuần này", "chiều thứ 7"). Ép sang date ở tầng
            -- lưu trữ nghĩa là phải đoán, và đoán sai thì mất bản gốc.
            preferred_date  text,
            preferred_time  text,
            status          text NOT NULL DEFAULT 'scheduled'
                            CONSTRAINT appointments_status_check
                            CHECK (status IN ('scheduled', 'confirmed', 'cancelled', 'completed')),
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT appointments_tenant_appt_key UNIQUE (tenant_id, appointment_id)
        )
        """
    )
    op.execute("CREATE INDEX appointments_tenant_session_idx ON tenant_data.appointments (tenant_id, session_id)")
    op.execute("CREATE INDEX appointments_tenant_phone_idx ON tenant_data.appointments (tenant_id, phone)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.appointments')")
    op.execute("SELECT control.grant_agent_write('tenant_data.appointments')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.appointments")
    op.execute("DROP TABLE tenant_data.conversations")
    op.execute("DROP TABLE tenant_data.contacts")
