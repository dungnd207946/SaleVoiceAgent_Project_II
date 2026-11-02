"""3 bảng control lõi: neo danh tính + cơ chế gate cột

M1 CHỈ tạo ba bảng này. Module sau tự sở hữu bảng của nó:
  users · memberships                    -> M2a (dải revision 0100-0149)
  config_drafts · config_versions
  tenants.live_version · deployments     -> M3  (0200-0299)
  jobs · agent_heartbeats                -> vẫn M1, nhưng migration riêng (0006, 0007)
  appointments · contacts · conversations -> M7  (0600-0699)

VÌ SAO tenants KHÔNG có cột `plan`: hoá đơn không được gắn vào khoá cách ly.
tenants.id là khoá dùng cho BỐN việc cùng lúc (policy RLS · TENANT_ID của pod ·
đường dẫn tenants/<id>/ trên kho tệp · tên collection kb_<id>). Gắn gói cước
vào đây thì lúc một tập đoàn cần nhiều workspace sẽ phải đánh lại đúng cái
khoá cách ly. Đường lùi rẻ đã để sẵn: thêm bảng `accounts` PHÍA TRÊN tenants.

VÌ SAO lifecycle chứ không phải status: status hiển thị (provisioning ·
publishing · ready · disconnected) là HÀM THUẦN của lifecycle + heartbeat +
live_version — xem portal.core.tenant_status. Không thể vừa lưu vừa suy ra.

Revision ID: 0002_control_core
Revises: 0001_schemas
"""

from alembic import op

revision = "0002_control_core"
down_revision = "0001_schemas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CHECK trên id ở TẦNG DB, không chỉ tầng app: slug đi thẳng vào tên role
    # agent_<id> trong control.create_agent_role(). Một slug có ký tự lạ là một
    # đường injection vào câu CREATE ROLE.
    op.execute(
        """
        CREATE TABLE control.tenants (
            id         text PRIMARY KEY
                       CONSTRAINT tenants_id_check CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$'),
            name       text NOT NULL,
            lifecycle  text NOT NULL DEFAULT 'active'
                       CONSTRAINT tenants_lifecycle_check
                       CHECK (lifecycle IN ('active', 'suspended', 'closed')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE control.tenant_verticals (
            tenant_id  text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            vertical   text NOT NULL CHECK (vertical IN ('realestate', 'finance')),
            enabled_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, vertical)
        )
        """
    )

    # Bản HIỆU LỰC của chính sách field. View agent_api đọc bảng này để cưỡng
    # chế gate cột. M3 ghi lại toàn bộ bảng mỗi lần publish; màn khai trường
    # của M4 ghi vào config_drafts, KHÔNG ghi thẳng vào đây.
    #
    # is_core = true  -> cột thật, gate bằng CASE WHEN trong view
    # is_core = false -> key trong extras jsonb, gate bằng portal.gated_extras()
    #
    # agent_readable -> tier 1: agent thấy field (ExtraFieldSpec)
    # filterable + match_op -> tier 2: field bơm vào tool schema (ToolParamSpec)
    op.execute(
        """
        CREATE TABLE control.field_policy_live (
            tenant_id      text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            entity         text NOT NULL,
            field          text NOT NULL,
            is_core        boolean NOT NULL DEFAULT false,
            agent_readable boolean NOT NULL DEFAULT false,
            filterable     boolean NOT NULL DEFAULT false,
            match_op       text
                           CONSTRAINT field_policy_live_match_op_check
                           CHECK (match_op IS NULL OR match_op IN
                                  ('eq', 'substring', 'gte', 'lte', 'exists', 'contains')),
            label_vi       text NOT NULL DEFAULT '',
            type           text NOT NULL DEFAULT 'text',
            enum_values    text[],
            PRIMARY KEY (tenant_id, entity, field),
            CONSTRAINT field_policy_live_filterable_needs_op
                CHECK (NOT filterable OR match_op IS NOT NULL),
            CONSTRAINT field_policy_live_enum_needs_type
                CHECK (enum_values IS NULL OR type = 'enum')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE control.field_policy_live")
    op.execute("DROP TABLE control.tenant_verticals")
    op.execute("DROP TABLE control.tenants")
