"""tool agent `analyze_projects` — 2 view read-only + 2 role sandbox cho SQL của LLM

BỐI CẢNH: `docs/contracts/agent-analyze-projects-sql-ro-contract.md` (agent, nhánh
`sql-agent`, 2026-08-26) + `docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md`.
Agent thêm tool để LLM tự viết một câu SQL `SELECT` trả lời câu hỏi thống kê
("dự án nào nhiều loại hình nhất"...). Vì SQL đó là input không đáng tin, nó chạy
dưới 3 khoá độc lập ở phía agent (không thuộc migration này): transaction
`READ ONLY`, `SET LOCAL ROLE agent_sql_ro`, RLS `tenant_isolation` sẵn có. Việc
của migration này CHỈ là dựng đúng 2 view + 2 role + quyền tối thiểu.

VÌ SAO CẦN VIEW RIÊNG, KHÔNG CHO LLM SELECT THẲNG `tenant_data.projects`/`units`:
schema `tenant_data` có GRANT SELECT cho PUBLIC trên MỌI bảng từ `0909` (cách ly
dựa hẳn vào RLS FORCE, không dựa GRANT — xem CLAUDE.md mục schema Postgres), nên
`agent_<tenant>` vốn ĐÃ đọc được `contacts`/`conversations`/toàn bộ cột nội bộ và
cả hàng draft/archived của chính tenant mình. Hai view này là ALLOWLIST thu hẹp
xuống đúng cột + đúng trạng thái `published` mà LLM được phép thấy khi chạy dưới
`agent_sql_ro` — đây là khoá chính, không phải tiện ích phụ.

VÌ SAO KHÔNG SỬA `control.create_agent_role()` NHƯ VĂN BẢN CONTRACT §2 MÔ TẢ:
`agent_all` (`0003_role_and_isolation_helper.py:45`) là role nhóm mà MỌI
`agent_<tenant_id>` đã là thành viên từ lúc tạo, và Postgres cho `SET ROLE` bắc
cầu qua chuỗi membership theo mặc định — `GRANT agent_sql_ro TO agent_all` một
dòng phủ được cả tenant hiện có LẪN tenant tạo sau này, đúng khuôn quy ước đã ghi
sẵn trong comment của chính `create_agent_role()` (`0911:102-104`: "thêm view hay
bảng mới thì grant cho agent_all, không sửa đây"). Không cần vòng lặp backfill
theo `pg_roles`, không cần đụng một hàm `SECURITY DEFINER`.

⚠️ DOWNGRADE PHẢI `REVOKE` TRƯỚC KHI `DROP ROLE` — khác bản rollback rút gọn ở
contract §7 (`DROP VIEW ...; DROP ROLE ...;` suông): Postgres từ chối `DROP ROLE`
một role còn ACL nào đó (ở đây là `GRANT USAGE ON SCHEMA`/`GRANT SELECT` trên bảng
gốc) — báo lỗi liệt kê "privileges for schema tenant_data" chứ không tự dọn. Object
DO role SỞ HỮU (2 view) thì khác — `DROP VIEW` trước đã gỡ luôn phần đó.

⚠️⚠️ CẢNH BÁO BẢO MẬT CHƯA ĐÓNG — ĐỌC TRƯỚC KHI BẬT TOOL CHO TENANT THẬT (đo
2026-09-07 trên DB dev, xem
`docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md` §0):
`agent_sql_ro` KHÔNG bị chặn khỏi `tenant_data.contacts`/`conversations`/bảng
gốc `projects`/`units` (chưa lọc `status='published'`) — vì `tenant_data.*` có
`GRANT SELECT ... TO PUBLIC` từ `0909`, và Postgres không cho REVOKE riêng một
role khỏi quyền đã cấp cho PUBLIC. 2 view + 2 role ở migration này tồn tại
đúng như thiết kế, nhưng KHÔNG đạt được mục tiêu cô lập cột/trạng thái mà
contract §4 mô tả. Chưa sửa trong migration này (quyết định 2026-09-07, để
thành task riêng — hướng sửa: RESTRICTIVE RLS policy chặn theo `current_user`
trên các bảng nhạy cảm). KHÔNG bật `"analyze_projects"` trong `skills` của bất
kỳ tenant thật nào cho tới khi việc đó xong.

Revision ID: 0958_analyze_projects_sql_ro
Revises: 0957_hop_nhat_hai_head
"""

from alembic import op

revision = "0958_analyze_projects_sql_ro"
down_revision = "0957_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bước 1: hai role — guard idempotent, CREATE ROLE không có IF NOT EXISTS.
    # agent_kb_view_owner: owner của 2 view. NOBYPASSRLS là load-bearing — view
    # chạy theo quyền owner (definer semantics); owner bị FORCE RLS siết thì
    # policy tenant_isolation (control.enforce_tenant_isolation, đã bật từ 0400
    # trên cả hai bảng gốc) vẫn lọc tenant xuyên qua view.
    # agent_sql_ro: túi quyền chạy SQL của LLM, NOLOGIN — "mặc tạm" bằng
    # SET LOCAL ROLE, không qua runtime-credentials.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_kb_view_owner') THEN
                CREATE ROLE agent_kb_view_owner NOLOGIN NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_sql_ro') THEN
                CREATE ROLE agent_sql_ro NOLOGIN;
            END IF;
        END $$
        """
    )

    # Bước 2: quyền nền cho owner — phải có TRƯỚC khi nó làm chủ view.
    op.execute("GRANT USAGE ON SCHEMA tenant_data TO agent_kb_view_owner, agent_sql_ro")
    op.execute("GRANT SELECT ON tenant_data.projects, tenant_data.units TO agent_kb_view_owner")

    # Bước 3: hai view — CREATE OR REPLACE, chạy lại không mất owner/grant, chỉ
    # cho phép THÊM cột vào CUỐI khi tiến hoá về sau (xem docstring spec §1.3).
    # Filter status='published' ở CẢ units LẪN project cha: khoá chống lộ
    # draft/archived — LLM không tự lọc được. KHÔNG thêm cột tenant_id/text dài
    # (overview, body...): chống lộ nội bộ + chống SELECT * nổ context.
    op.execute(
        """
        CREATE OR REPLACE VIEW tenant_data.agent_projects_v AS
        SELECT project_code, name, region, address, investor, developer,
               category, sale_phase, ownership_form, total_land_area_m2
        FROM tenant_data.projects
        WHERE status = 'published'
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW tenant_data.agent_units_v AS
        SELECT u.project_code, p.name AS project_name, u.zone_code, u.unit_code,
               u.product_type, u.bedrooms, u.block, u.floor, u.direction,
               u.area_built_m2, u.area_land_m2, u.price_vnd, u.price_per_m2_vnd,
               u.sale_status
        FROM tenant_data.units u
        JOIN tenant_data.projects p USING (tenant_id, project_code)
        WHERE u.status = 'published' AND p.status = 'published'
        """
    )

    # Bước 4: gán owner + quyền đọc view — idempotent, chạy lại vô hại.
    op.execute("ALTER VIEW tenant_data.agent_projects_v OWNER TO agent_kb_view_owner")
    op.execute("ALTER VIEW tenant_data.agent_units_v    OWNER TO agent_kb_view_owner")
    op.execute("GRANT SELECT ON tenant_data.agent_projects_v, tenant_data.agent_units_v TO agent_sql_ro")

    # Bước 5: membership — MỘT dòng phủ mọi tenant (xem docstring). GRANT lặp lại
    # chỉ báo NOTICE "already a member", vô hại.
    op.execute("GRANT agent_sql_ro TO agent_all")

    # Fallback/dự phòng theo đúng yêu cầu contract §1.2 — Portal hiện KHÔNG dùng
    # portal_api làm đường phục vụ agent (serving path thật là role per-tenant từ
    # /runtime-credentials), giữ dòng này chỉ vì bên agent yêu cầu tường minh cho
    # một deployment mode khác họ có thể có.
    op.execute("GRANT agent_sql_ro TO portal_api")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS tenant_data.agent_units_v")
    op.execute("DROP VIEW IF EXISTS tenant_data.agent_projects_v")

    # REVOKE trước DROP ROLE — xem cảnh báo ở docstring đầu file.
    op.execute("REVOKE ALL ON SCHEMA tenant_data FROM agent_sql_ro")
    op.execute("REVOKE ALL ON SCHEMA tenant_data FROM agent_kb_view_owner")
    op.execute("REVOKE ALL ON tenant_data.projects, tenant_data.units FROM agent_kb_view_owner")
    op.execute("REVOKE agent_sql_ro FROM agent_all")
    op.execute("REVOKE agent_sql_ro FROM portal_api")

    op.execute("DROP ROLE IF EXISTS agent_sql_ro")
    op.execute("DROP ROLE IF EXISTS agent_kb_view_owner")
