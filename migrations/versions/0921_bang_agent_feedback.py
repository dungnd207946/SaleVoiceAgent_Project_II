"""tenant_data.agent_feedback — feedback người dùng cuối gửi sau khi dùng agent

VẤN ĐỀ NÓ GIẢI: bên agent (`santa-hotline-agent`) sắp có FE hỏi feedback cuối
phiên (1-5 sao + comment tuỳ chọn). Cần một chỗ chứa, ghi đúng tenant, và FE
Portal đọc lại được theo workspace.

VÌ SAO GHI QUA `/agent/feedback` (endpoint mới, `enrollment/router.py`) CHỨ
KHÔNG PHẢI AGENT TỰ INSERT NHƯ 4 BẢNG WRITE-BACK (`0903`/`0915`): những bảng đó
agent tự ghi bằng role Postgres của chính nó (`agent_<tenant_id>`, RLS lo cách
ly). Feedback đi một đường khác: BE của agent pod gọi HTTP tới Portal bằng
CHÍNH `AGENT_API_KEY` nó đã có sẵn cho `/runtime-credentials` — Portal (role
`portal_api`) tự suy tenant từ khoá (`repo.tra_khoa`) rồi ghi hộ qua
`tenant_conn()`. Do đó bảng này KHÔNG gọi `control.grant_agent_write()` — vai
`agent_all` không cần và không nên có quyền trực tiếp trên bảng này, vì
`agent_all` không phải người ghi.

`session_id` NOT NULL, KHÔNG FK về `conversations` — CÙNG LÝ LẼ với
`conversation_messages` (`0915`): Portal không kiểm soát được BE agent gọi
feedback trước hay sau khi hàng `conversations` được chốt, và một FK ở đây là
quyết định hộ thứ tự một hệ mà Portal không đọc được code.

`rating smallint 1-5` — quyết định sản phẩm (không phải thumbs up/down) chốt
2026-08-12. `comment` rỗng hợp lệ — không phải ai cho sao cũng viết thêm.

Gọi `control.enforce_tenant_isolation()` (luật 2 CLAUDE.md) — hàm này VỪA bật
RLS FORCE + policy `tenant_isolation`, VỪA `GRANT SELECT, INSERT, UPDATE,
DELETE ON ... TO portal_api` (xem `0003_role_and_isolation_helper.py`) — không
cần viết GRANT tay thêm cho `portal_api` như `0910` phải làm (bảng đó cố ý
KHÔNG gọi hàm này nên phải tự cấp).

Chỉ mục `(tenant_id, id DESC)` phục vụ đúng truy vấn màn feedback của Portal:
liệt kê mới nhất trước, phân trang keyset theo `id`, lọc theo workspace hiện tại.

Revision ID: 0921_bang_agent_feedback
Revises: 0920_hop_nhat_hai_head_0919
"""

from alembic import op

revision = "0921_bang_agent_feedback"
down_revision = "0920_hop_nhat_hai_head_0919"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE tenant_data.agent_feedback (
            id         bigserial PRIMARY KEY,
            tenant_id  {_TENANT_FK},
            session_id text NOT NULL
                       CONSTRAINT agent_feedback_session_check CHECK (session_id <> ''),
            rating     smallint NOT NULL
                       CONSTRAINT agent_feedback_rating_check CHECK (rating BETWEEN 1 AND 5),
            comment    text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX agent_feedback_tenant_id_idx ON tenant_data.agent_feedback (tenant_id, id DESC)")
    op.execute("CREATE INDEX agent_feedback_tenant_session_idx ON tenant_data.agent_feedback (tenant_id, session_id)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.agent_feedback')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.agent_feedback")
