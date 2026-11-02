"""tenant_data.conversation_messages — từng lượt nói thành HÀNG, gỡ cột full_conversation

VẤN ĐỀ NÓ GIẢI: `0912_full_conversation` đặt cả transcript vào một cột `jsonb` trên
`tenant_data.conversations`. Chủ sản phẩm đổi hướng (06/08): mỗi lượt nói là một
HÀNG riêng. Hình dạng bảng dưới đây do họ đưa, không phải Portal tự thiết kế lại.

VÌ SAO HÀNG TỐT HƠN CỘT JSONB — ghi lại để lần sau không ai lật ngược mà không biết
mình đang đánh đổi gì:
  · Append một lượt là `INSERT` một hàng, không phải đọc-sửa-ghi cả mảng. Hai lượt
    tới cùng lúc thì với `jsonb` là một lượt bị nuốt, với bảng là hai hàng.
  · Đếm số lượt của một phiên là `count(*)` trên chỉ mục, không phải kéo cả
    transcript về rồi đo độ dài mảng.
  · `meta` mở cho TỪNG lượt (tool_calls · latency · interrupted · cached · source)
    mà không phải nong một schema dùng chung.

GỠ `conversations.full_conversation` NGAY TRONG MIGRATION NÀY, không để lại: đã đo
trên DB dev trước khi viết — `conversations` có **0 hàng**, và **0 hàng** nào có
`full_conversation <> '[]'`. Không có dữ liệu để mất. Để một cột chết nằm lại là mời
đường ghi thứ hai cho cùng một sự thật, và sáu tháng nữa không ai biết cột nào thật.

⚠️ ĐỌC `0913_bat_lai_rls_tenant_data` TRƯỚC KHI SỬA DÒNG `enforce_tenant_isolation`
BÊN DƯỚI. Lịch sử RLS của repo này đảo chiều hai lần trong đúng một ngày: `0909` dỡ
toàn bộ, rồi `0913` bật lại sau khi đo được agent của `anphu` đọc thấy 6 dự án
trong khi tenant đó chỉ có 2. Bảng này gọi `enforce_tenant_isolation()` để nằm cùng
hàng với mọi bảng `tenant_data` khác — đúng luật 2 của CLAUDE.md, và đúng lớp thứ
hai mà `0913` dựng lên. Nó KHÔNG thay cho `WHERE tenant_id` trong `src/portal`:
`0913` nói thẳng rằng một lớp là một điểm chết.

⚠️ `0913` KHÔNG với tới bảng này được. Nó quét `pg_class` **tại thời điểm nó chạy**,
mà bảng này sinh ra sau. Ai xoá dòng `enforce_tenant_isolation` bên dưới sẽ tạo ra
đúng một bảng không có RLS giữa một schema có RLS — loại lệch không có triệu chứng
cho tới khi nó lộ dữ liệu.

BA THỨ CỐ Ý KHÔNG SIẾT:
  · KHÔNG `CHECK (role IN ('user','assistant','tool'))`. Ba giá trị đó là chú thích
    trong DDL người ta đưa, không phải hợp đồng đã ký. Một `role` thứ tư từ phía
    agent mà gặp CHECK thì đường ghi của họ VỠ; không có CHECK thì màn Hội thoại
    render nó thành dòng hệ thống và không ai mất gì.
  · KHÔNG FK `(tenant_id, session_id)` về `conversations` dù bảng kia có UNIQUE đúng
    cặp đó. Agent có thể ghi lượt nói TRƯỚC khi chốt hàng phiên; đặt FK ở đây là
    quyết định hộ thứ tự ghi cho một hệ mà Portal không đọc được code. Cùng lý lẽ
    `appointments.project_code` của `0903`.
  · KHÔNG chỉ mục phụ. PK `(tenant_id, session_id, seq)` đã phục vụ cả hai truy vấn
    của màn: đọc một phiên theo thứ tự, và đếm số lượt mỗi phiên.

CÓ giữ FK `tenant_id -> control.tenants(id) ON DELETE CASCADE` (DDL gốc không có).
Mọi bảng `tenant_data` khác đều có; thiếu nó thì xoá một tenant để lại lượt nói mồ
côi không ai dọn, và một `tenant_id` gõ sai vẫn ghi vào được.

Revision ID: 0915_convo_messages
Revises: 0914_hop_nhat_hai_head
"""

from alembic import op

revision = "0915_convo_messages"
down_revision = "0914_hop_nhat_hai_head"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE tenant_data.conversation_messages (
            tenant_id  {_TENANT_FK},
            -- KHÔNG FK về conversations — xem docstring.
            session_id text NOT NULL
                       CONSTRAINT convo_msg_session_check CHECK (session_id <> ''),
            -- Thứ tự trong phiên, 0-based. Nằm trong PK nên vừa là thứ tự vừa là
            -- chống ghi trùng: append lại cùng seq thì VỠ, không âm thầm đè.
            seq        int NOT NULL CONSTRAINT convo_msg_seq_check CHECK (seq >= 0),
            role       text NOT NULL CONSTRAINT convo_msg_role_check CHECK (role <> ''),
            content    text NOT NULL DEFAULT '',
            -- Mốc lúc append, UTC. NOT NULL và KHÔNG `DEFAULT now()`: giờ của một lượt
            -- nói là giờ nó được nói ra, không phải giờ nó chạm tới DB. Có default thì
            -- một đường ghi quên đặt trường này sẽ lặng lẽ đóng dấu sai giờ, và không
            -- ai phát hiện được vì con số vẫn hợp lý.
            created_at timestamptz NOT NULL,
            -- tool_calls · latency · interrupted · cached · source…
            meta       jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            PRIMARY KEY (tenant_id, session_id, seq)
        )
        """
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.conversation_messages')")
    op.execute("SELECT control.grant_agent_write('tenant_data.conversation_messages')")

    # Gỡ cột của 0912. An toàn vì đã đo: 0 hàng `conversations`, 0 hàng có transcript.
    op.execute("ALTER TABLE tenant_data.conversations DROP COLUMN full_conversation")


def downgrade() -> None:
    # Dựng lại cột RỖNG — KHÔNG đổ ngược dữ liệu từ `conversation_messages` sang. Một
    # phép gộp như vậy trông giống khôi phục nhưng thực ra SINH RA một transcript chưa
    # từng tồn tại ở cột đó. Muốn quay lui thật thì viết đường chuyển dữ liệu có chủ
    # đích, đừng giấu nó trong downgrade().
    op.execute("ALTER TABLE tenant_data.conversations ADD COLUMN full_conversation jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("DROP TABLE tenant_data.conversation_messages")
